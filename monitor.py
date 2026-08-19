"""
monitor.py

Fica de olho na pasta Downloads. Sempre que uma etiqueta em PDF aparece
(Shopee, Mercado Livre, ou outro modelo cadastrado em modelos_etiqueta.py),
extrai o número do pedido, consulta a Tiny e anexa uma página com a lista
de itens do pedido para cada etiqueta encontrada - substituindo o PDF
original.

Configurações ajustáveis (tempo de espera do lote, validade do cache, dias
de log mantidos) ficam em config.json, ao lado do programa - editável sem
precisar recompilar.

Para rodar:
    python monitor.py
(feche a janela para parar)
"""

import json
import logging
import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from datetime import datetime
from tkinter import messagebox, ttk
from logging.handlers import TimedRotatingFileHandler

import fitz  # pymupdf
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from tiny_api import (
    consultar_pedido_multi_conta,
    listar_pedidos_recentes,
    obter_pedido_completo,
    TinyAPIError,
    CONTAS,
)
from gerador_pagina_itens import gerar_pagina_itens
from modelos_etiqueta import identificar_modelo, detectar_grade_de_etiquetas

PASTA_MONITORADA = os.path.join(os.path.expanduser("~"), "Downloads")

# Fila usada para o watchdog (que roda numa thread separada) avisar a
# janela (que roda na thread principal) do progresso, sem os dois threads
# mexerem diretamente um no outro - jeito seguro de conectar as duas partes.
fila_status = queue.Queue()

# Pasta base do programa - quando rodando como script normal, é a pasta do
# próprio monitor.py; quando empacotado como .exe pelo PyInstaller (modo
# --onefile), __file__ aponta para uma pasta temporária que some ao fechar
# o programa - por isso, nesse caso, usamos a pasta onde o .exe realmente
# está (sys.executable).
if getattr(sys, "frozen", False):
    DIRETORIO_BASE = os.path.dirname(sys.executable)
else:
    DIRETORIO_BASE = os.path.dirname(os.path.abspath(__file__))

# --- Configurações ajustáveis ---------------------------------------------
#
# Ficam em config.json, ao lado do programa - dá pra ajustar sem precisar
# recompilar o .exe. Se o arquivo não existir ainda (primeira vez rodando),
# é criado automaticamente com os valores padrão abaixo.

CAMINHO_CONFIG = os.path.join(DIRETORIO_BASE, "config.json")

CONFIGURACOES_PADRAO = {
    "inatividade_lote_segundos": 40,
    "cache_rastreio_validade_segundos": 300,
    "dias_de_log_mantidos": 30,
}


def _carregar_configuracoes() -> dict:
    if not os.path.exists(CAMINHO_CONFIG):
        try:
            with open(CAMINHO_CONFIG, "w", encoding="utf-8") as f:
                json.dump(CONFIGURACOES_PADRAO, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        return dict(CONFIGURACOES_PADRAO)

    try:
        with open(CAMINHO_CONFIG, "r", encoding="utf-8") as f:
            configuracoes_salvas = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(CONFIGURACOES_PADRAO)

    configuracoes = dict(CONFIGURACOES_PADRAO)
    configuracoes.update(configuracoes_salvas)
    return configuracoes


CONFIG = _carregar_configuracoes()

PASTA_LOGS = os.path.join(DIRETORIO_BASE, "logs")
ARQUIVO_LOG = os.path.join(PASTA_LOGS, "roboetiquetas.log")

# Pasta onde os PDFs consolidados (várias etiquetas baixadas separadamente,
# juntadas num arquivo só) são salvos. Fica FORA da pasta Downloads de
# propósito - se fosse salvo lá, o próprio robô detectaria esse arquivo como
# se fosse uma etiqueta nova e tentaria processá-lo de novo.
PASTA_LOTES = os.path.join(DIRETORIO_BASE, "lotes prontos")

logger = logging.getLogger("roboetiquetas")


def _configurar_logger():
    """
    Configura o log para gravar tanto no terminal quanto em arquivo.
    O arquivo gira todo dia à meia-noite (um arquivo por dia), mantendo os
    últimos dias definidos em config.json - assim dá pra conferir depois o
    que o robô fez, mesmo rodando em segundo plano sem terminal visível.
    """
    os.makedirs(PASTA_LOGS, exist_ok=True)

    logger.setLevel(logging.INFO)

    formato_arquivo = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    formato_console = logging.Formatter("%(message)s")

    manipulador_arquivo = TimedRotatingFileHandler(
        ARQUIVO_LOG, when="midnight", backupCount=CONFIG["dias_de_log_mantidos"], encoding="utf-8"
    )
    manipulador_arquivo.setFormatter(formato_arquivo)

    manipulador_console = logging.StreamHandler()
    manipulador_console.setFormatter(formato_console)

    logger.addHandler(manipulador_arquivo)
    logger.addHandler(manipulador_console)


# Alguns e-commerces (ex: TikTok Shop) baixam UM PDF POR ETIQUETA, em vez de
# um PDF só com o lote inteiro. Sem cache, cada arquivo novo dispararia sua
# própria busca por pedidos recentes na Tiny (~15-20s cada) para montar o
# índice por código de rastreamento - em um lote de 100+ etiquetas baixadas
# separadamente, isso desperdiçaria dezenas de minutos repetindo a mesma
# busca. Esse cache compartilha o índice entre arquivos diferentes por um
# tempo limitado, já que a Tiny não tem como avisar o robô quando um pedido
# novo é cadastrado.
_cache_rastreio_trava = threading.Lock()
_cache_rastreio_indices = {}     # nome_conta -> {codigo_rastreamento: pedido}
_cache_rastreio_expiracoes = {}  # nome_conta -> timestamp de expiração


def _obter_indice_rastreio(nome_conta: str, forcar_atualizacao: bool = False) -> dict:
    """
    Devolve o índice {codigo_rastreamento: pedido} de uma conta específica,
    reaproveitando o cache se ainda estiver dentro da validade. Só busca de
    novo na Tiny quando o cache expira ou quando forcar_atualizacao=True
    (usado quando um pedido não é encontrado no cache - pode ser um
    despacho muito recente).
    """
    global _cache_rastreio_indices, _cache_rastreio_expiracoes

    with _cache_rastreio_trava:
        expira_em = _cache_rastreio_expiracoes.get(nome_conta, 0.0)
        if not forcar_atualizacao and time.time() < expira_em:
            return _cache_rastreio_indices.get(nome_conta, {})

        pedidos_recentes = listar_pedidos_recentes(nome_conta=nome_conta)
        indice = {
            pedido["codigo_rastreamento"]: pedido
            for pedido in pedidos_recentes
            if pedido.get("codigo_rastreamento")
        }
        _cache_rastreio_indices[nome_conta] = indice
        _cache_rastreio_expiracoes[nome_conta] = time.time() + CONFIG["cache_rastreio_validade_segundos"]
        return indice


def _buscar_por_rastreio_multi_conta(codigo_rastreamento: str) -> tuple:
    """
    Procura o código de rastreamento no índice de cada conta cadastrada,
    na ordem (ver CONTAS). Devolve (pedido_resumo, nome_conta) ou
    (None, None) se não achar em nenhuma - mesmo depois de forçar uma
    atualização dos índices.
    """
    for nome_conta in CONTAS:
        indice = _obter_indice_rastreio(nome_conta)
        pedido = indice.get(codigo_rastreamento)
        if pedido:
            return pedido, nome_conta

    # Não achou em nenhuma conta com o cache atual - pode ser um despacho
    # muito recente. Força atualização de todas antes de desistir de vez.
    for nome_conta in CONTAS:
        indice = _obter_indice_rastreio(nome_conta, forcar_atualizacao=True)
        pedido = indice.get(codigo_rastreamento)
        if pedido:
            return pedido, nome_conta

    return None, None


# Quantos segundos sem nenhum arquivo novo chegar até o robô considerar que
# o lote "terminou" e juntar tudo que acumulou num PDF único (ajustável em
# config.json).
_lote_trava = threading.Lock()
_lote_doc = None
_lote_timer = None


def _adicionar_ao_lote(doc_paginas):
    """
    Acrescenta as páginas de uma etiqueta já processada ao PDF do lote
    atual (em memória), e reinicia o temporizador de inatividade - só
    quando ele "estourar" (sem nenhuma etiqueta nova chegando por um
    tempo) é que o lote é salvo e aberto de fato.
    """
    global _lote_doc, _lote_timer

    with _lote_trava:
        if _lote_doc is None:
            _lote_doc = fitz.open()
        _lote_doc.insert_pdf(doc_paginas)

        if _lote_timer is not None:
            _lote_timer.cancel()
        _lote_timer = threading.Timer(CONFIG["inatividade_lote_segundos"], _finalizar_lote)
        _lote_timer.daemon = True
        _lote_timer.start()


def _finalizar_lote():
    """
    Junta tudo que foi acumulado desde o último lote consolidado num único
    PDF, salva numa pasta separada (fora da pasta monitorada) e abre
    automaticamente. Chamado sozinho pelo temporizador de inatividade.
    """
    global _lote_doc, _lote_timer

    with _lote_trava:
        doc = _lote_doc
        _lote_doc = None
        _lote_timer = None

    if doc is None or doc.page_count == 0:
        return

    fila_status.put(("status", "Criando lote de etiquetas..."))

    os.makedirs(PASTA_LOTES, exist_ok=True)
    nome_arquivo = f"Etiquetas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    caminho_lote = os.path.join(PASTA_LOTES, nome_arquivo)

    total_paginas = doc.page_count
    doc.save(caminho_lote)
    doc.close()

    logger.info(f"[lote finalizado] '{nome_arquivo}' criado com {total_paginas} página(s) em '{PASTA_LOTES}'.\n")
    fila_status.put(("consolidado", caminho_lote, total_paginas))

    try:
        os.startfile(caminho_lote)
    except OSError as e:
        logger.warning(f"Não foi possível abrir o PDF do lote automaticamente: {e}")

# Tamanho padrão de etiqueta térmica de envio: 100mm x 150mm, convertido
# para pontos PDF (1 polegada = 72 pontos = 25.4mm).
LARGURA_ETIQUETA_PT = 100 / 25.4 * 72
ALTURA_ETIQUETA_PT = 150 / 25.4 * 72

# Extensões que sabemos que são downloads ainda incompletos - ignoramos
# direto, sem nem tentar abrir.
EXTENSOES_IGNORADAS = {".crdownload", ".tmp", ".part", ".download"}


def _mover_para_processadas(caminho: str, nome_conta: str = None) -> str:
    """
    Move o PDF já processado da pasta Downloads para uma subpasta
    'Processadas <conta>' (ex: 'Processadas Luma', 'Processadas LM'), pra
    não acumular centenas de arquivos "usados" misturados com os que ainda
    vão chegar, já separados por qual conta/CNPJ encontrou o pedido. Se a
    conta não foi identificada (nenhum pedido encontrado no arquivo), usa
    uma pasta genérica 'Processadas'. Devolve o novo caminho.
    """
    nome_pasta = f"Processadas {nome_conta}" if nome_conta else "Processadas"
    pasta_destino = os.path.join(PASTA_MONITORADA, nome_pasta)
    os.makedirs(pasta_destino, exist_ok=True)

    nome_arquivo = os.path.basename(caminho)
    destino = os.path.join(pasta_destino, nome_arquivo)

    # Evita sobrescrever caso já exista um arquivo com esse nome ali
    # (raro, mas pode acontecer com nomes genéricos reaproveitados).
    raiz, extensao = os.path.splitext(nome_arquivo)
    contador = 1
    while os.path.exists(destino):
        destino = os.path.join(pasta_destino, f"{raiz} ({contador}){extensao}")
        contador += 1

    shutil.move(caminho, destino)
    return destino


def _e_um_pdf(caminho: str) -> bool:
    """Confere pela assinatura do arquivo (primeiros bytes), não pelo nome -
    alguns sites entregam o PDF sem a extensão .pdf no nome do arquivo."""
    try:
        with open(caminho, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False

# Tempo (segundos) que esperamos o arquivo parar de crescer antes de mexer nele
# (evita pegar um PDF que o navegador ainda está terminando de baixar).
INTERVALO_VERIFICACAO_ESTABILIDADE = 1.0
TENTATIVAS_MAXIMAS_ESTABILIDADE = 15


def _arquivo_esta_estavel(caminho: str) -> bool:
    """Espera o tamanho do arquivo parar de mudar, para garantir que o download terminou."""
    tamanho_anterior = -1
    for _ in range(TENTATIVAS_MAXIMAS_ESTABILIDADE):
        try:
            tamanho_atual = os.path.getsize(caminho)
        except OSError:
            return False  # arquivo sumiu ou ainda não existe de fato

        if tamanho_atual == tamanho_anterior and tamanho_atual > 0:
            return True

        tamanho_anterior = tamanho_atual
        time.sleep(INTERVALO_VERIFICACAO_ESTABILIDADE)

    return False


def _detectar_area_de_conteudo(pagina, area_limite=None) -> "fitz.Rect":
    """
    Calcula a caixa delimitadora (bounding box) de tudo que está
    efetivamente desenhado dentro de `area_limite` (texto, imagens como
    QR codes/logos, e desenhos vetoriais como códigos de barras) - para
    saber onde uma etiqueta específica realmente termina, ignorando
    espaço em branco ao redor e conteúdo de etiquetas vizinhas.
    """
    if area_limite is None:
        area_limite = pagina.rect

    caixa = fitz.Rect()  # começa vazia; include_rect vai expandindo

    for bloco in pagina.get_text("dict", clip=area_limite)["blocks"]:
        caixa.include_rect(fitz.Rect(bloco["bbox"]))

    for imagem in pagina.get_image_info():
        retangulo_imagem = fitz.Rect(imagem["bbox"])
        if retangulo_imagem.intersects(area_limite):
            caixa.include_rect(retangulo_imagem & area_limite)

    for desenho in pagina.get_drawings():
        retangulo_desenho = fitz.Rect(desenho["rect"])
        if retangulo_desenho.intersects(area_limite):
            caixa.include_rect(retangulo_desenho & area_limite)

    if caixa.is_empty:
        return area_limite  # não achou nada desenhado - usa a área inteira

    # Pequena margem de segurança, sem deixar passar dos limites da área
    caixa.x0 = max(area_limite.x0, caixa.x0 - 2)
    caixa.y0 = max(area_limite.y0, caixa.y0 - 2)
    caixa.x1 = min(area_limite.x1, caixa.x1 + 2)
    caixa.y1 = min(area_limite.y1, caixa.y1 + 2)

    return caixa


def _adicionar_pagina_redimensionada(doc_destino, doc_origem, indice_pagina: int, area_origem=None):
    """
    Pega a área `area_origem` da página `indice_pagina` do `doc_origem`
    (uma etiqueta - pode ser a página inteira ou só uma célula de uma
    grade com várias etiquetas), redimensiona o conteúdo real (ignorando
    espaço em branco) para caber em 100x150mm sem distorcer, e adiciona
    como nova página no final do `doc_destino`.
    """
    pagina_original = doc_origem[indice_pagina]
    if area_origem is None:
        area_origem = pagina_original.rect

    area_conteudo = _detectar_area_de_conteudo(pagina_original, area_origem)

    escala = min(
        LARGURA_ETIQUETA_PT / area_conteudo.width,
        ALTURA_ETIQUETA_PT / area_conteudo.height,
    )
    largura_final = area_conteudo.width * escala
    altura_final = area_conteudo.height * escala

    deslocamento_x = (LARGURA_ETIQUETA_PT - largura_final) / 2
    deslocamento_y = (ALTURA_ETIQUETA_PT - altura_final) / 2

    nova_pagina = doc_destino.new_page(width=LARGURA_ETIQUETA_PT, height=ALTURA_ETIQUETA_PT)
    retangulo_destino = fitz.Rect(
        deslocamento_x,
        deslocamento_y,
        deslocamento_x + largura_final,
        deslocamento_y + altura_final,
    )
    nova_pagina.show_pdf_page(retangulo_destino, doc_origem, indice_pagina, clip=area_conteudo)


# Marca colocada nos metadados do PDF final, para saber que ele já foi
# processado - evita reprocessar (e duplicar as páginas de itens) quando o
# próprio robô sobrescreve o arquivo e o Watchdog detecta a mudança de novo.
MARCADOR_PROCESSADO = "RoboEtiquetas:processado"


def _ja_processado(doc) -> bool:
    return MARCADOR_PROCESSADO in (doc.metadata.get("keywords") or "")


def _marcar_como_processado(doc):
    metadados = dict(doc.metadata or {})
    metadados["keywords"] = MARCADOR_PROCESSADO
    doc.set_metadata(metadados)


def processar_pdf(caminho: str):
    nome_arquivo = os.path.basename(caminho)

    if not _arquivo_esta_estavel(caminho):
        logger.info(f"[ignorado] '{nome_arquivo}' não estabilizou a tempo, pulando.")
        return

    if not _e_um_pdf(caminho):
        return  # não é um PDF (ou ainda não terminou de ser escrito) - ignora silenciosamente

    try:
        doc_original = fitz.open(caminho)
    except Exception:
        logger.warning(f"[ignorado] '{nome_arquivo}' não é um PDF válido.")
        return

    if _ja_processado(doc_original):
        doc_original.close()
        return

    total_paginas = doc_original.page_count

    # Mapeia todas as etiquetas do PDF, já considerando que: (1) cada
    # página pode conter mais de uma etiqueta lado a lado (impressão em
    # lote) e (2) o PDF pode ter páginas auxiliares que não são etiquetas
    # de verdade (ex: o Mercado Livre inclui uma página com a lista de
    # produtos, além da etiqueta) - essas são identificadas e ignoradas.
    etiquetas = []  # lista de (indice_pagina, retangulo_da_etiqueta, modelo)
    for indice in range(total_paginas):
        pagina = doc_original[indice]
        modelo = identificar_modelo(pagina)

        if modelo is None:
            logger.warning(f"  [aviso] página {indice + 1}: nenhum modelo de etiqueta reconhecido - página ignorada.")
            continue

        for celula in detectar_grade_de_etiquetas(pagina, modelo["texto_ancora"]):
            etiquetas.append((indice, celula, modelo))

    plural = "s" if len(etiquetas) != 1 else ""
    logger.info(f"[detectado] '{nome_arquivo}': {len(etiquetas)} etiqueta{plural} em {total_paginas} página(s) do PDF. Processando...")
    fila_status.put(("lote_inicio", len(etiquetas), nome_arquivo))

    doc_final = fitz.open()
    algum_pedido_processado = False
    contas_encontradas = []  # uma entrada por pedido encontrado com sucesso, usado pra decidir a subpasta "Processadas <conta>"

    for numero_da_etiqueta, (indice_pagina, celula, modelo) in enumerate(etiquetas, start=1):
        pagina = doc_original[indice_pagina]
        numero_ecommerce = modelo["extrair_numero"](pagina, area_limite=celula)

        # A etiqueta original (redimensionada) sempre entra, mesmo que a
        # consulta à Tiny falhe depois - assim nenhuma etiqueta se perde.
        _adicionar_pagina_redimensionada(doc_final, doc_original, indice_pagina, area_origem=celula)

        if not numero_ecommerce:
            logger.warning(f"  [aviso] etiqueta {numero_da_etiqueta} ({modelo['nome']}): número do pedido não encontrado - mantendo só a etiqueta original.")
            continue

        logger.info(f"  [etiqueta {numero_da_etiqueta}] {modelo['nome']}, pedido {numero_ecommerce}: consultando a Tiny...")
        fila_status.put(("lote_progresso", numero_da_etiqueta, len(etiquetas), f"{modelo['nome']} - pedido {numero_ecommerce}"))
        try:
            if modelo.get("tipo_busca") == "rastreio":
                pedido_resumo, nome_conta_encontrada = _buscar_por_rastreio_multi_conta(numero_ecommerce)
                if pedido_resumo is None:
                    raise TinyAPIError(
                        20,
                        f"Nenhum pedido encontrado com o código de rastreamento '{numero_ecommerce}' "
                        f"em nenhuma das contas cadastradas ({', '.join(CONTAS)})",
                    )
                pedido_completo = obter_pedido_completo(pedido_resumo["id"], nome_conta=nome_conta_encontrada)
            else:
                pedido_completo, nome_conta_encontrada = consultar_pedido_multi_conta(numero_ecommerce)
        except TinyAPIError as e:
            logger.error(f"  [erro] pedido {numero_ecommerce}: {e}")
            fila_status.put(("erro", numero_ecommerce, str(e)))
            continue

        contas_encontradas.append(nome_conta_encontrada)

        pdf_pagina_itens = gerar_pagina_itens(pedido_completo)
        doc_pagina_itens = fitz.open("pdf", pdf_pagina_itens)
        doc_final.insert_pdf(doc_pagina_itens)
        doc_pagina_itens.close()
        algum_pedido_processado = True

        logger.info(f"  [ok] pedido {numero_ecommerce}: {len(pedido_completo['itens'])} item(ns) adicionados.")

    doc_original.close()
    _marcar_como_processado(doc_final)

    caminho_temporario = caminho + ".tmp"
    doc_final.save(caminho_temporario)
    doc_final.close()
    os.replace(caminho_temporario, caminho)

    # Move pra pasta "Processadas <conta>" antes de abrir/acumular - assim
    # a pasta Downloads não fica lotada de arquivos já tratados, já
    # separados por qual conta/CNPJ encontrou o pedido. Se o arquivo tiver
    # etiquetas de mais de uma conta (raro, mas possível), usa a conta que
    # apareceu mais vezes nesse arquivo. Se nenhum pedido foi encontrado,
    # usa uma pasta genérica.
    conta_predominante = Counter(contas_encontradas).most_common(1)[0][0] if contas_encontradas else None
    caminho = _mover_para_processadas(caminho, nome_conta=conta_predominante)

    # Só acumula no lote quando o modelo baixa uma etiqueta por arquivo
    # (ex: TikTok Shop) - evita uma enxurrada de janelas abrindo. Modelos
    # que já vêm com o lote inteiro num arquivo só (Shopee, Mercado Livre)
    # abrem na hora, como antes.
    deve_acumular_em_lote = any(modelo.get("acumular_em_lote") for _, _, modelo in etiquetas)

    if deve_acumular_em_lote:
        doc_para_lote = fitz.open(caminho)
        _adicionar_ao_lote(doc_para_lote)
        doc_para_lote.close()
    else:
        try:
            os.startfile(caminho)
        except OSError as e:
            logger.warning(f"Não foi possível abrir o PDF automaticamente: {e}")

    if algum_pedido_processado:
        logger.info(f"[concluído] '{nome_arquivo}' atualizado ({len(etiquetas)} etiqueta{plural} processada{plural}).\n")
    else:
        logger.info(f"[concluído] '{nome_arquivo}' redimensionado, mas nenhum pedido foi encontrado na Tiny.\n")

    fila_status.put(("lote_fim",))


class HandlerEtiquetas(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self._ja_processando = set()

    def on_created(self, event):
        if event.is_directory or self._e_extensao_ignorada(event.src_path):
            return
        self._processar_com_protecao(event.src_path)

    def on_moved(self, event):
        # Navegadores costumam baixar para um nome temporário (.crdownload,
        # .tmp) e só renomear para o nome final quando o download termina.
        # Isso dispara um evento de "movido", não de "criado".
        if event.is_directory or self._e_extensao_ignorada(event.dest_path):
            return
        self._processar_com_protecao(event.dest_path)

    @staticmethod
    def _e_extensao_ignorada(caminho: str) -> bool:
        _, extensao = os.path.splitext(caminho)
        return extensao.lower() in EXTENSOES_IGNORADAS

    def _processar_com_protecao(self, caminho: str):
        if caminho in self._ja_processando:
            return
        self._ja_processando.add(caminho)
        try:
            processar_pdf(caminho)
        except Exception:
            logger.exception(f"[erro inesperado] ao processar '{caminho}':")
        finally:
            self._ja_processando.discard(caminho)


class JanelaStatus:
    """
    Janela simples que mostra o que o robô está fazendo agora e, durante o
    processamento de um lote de etiquetas, uma barra de progresso. Só lê da
    fila_status (nunca mexe direto no watchdog/na thread de processamento),
    então é seguro rodar isso na thread principal enquanto o watchdog roda
    na dele.
    """

    INTERVALO_VERIFICACAO_MS = 200

    def __init__(self, root, ao_fechar):
        self.root = root
        self.ao_fechar = ao_fechar
        self.contagem_erros = 0

        root.title("RoboEtiquetas")
        root.geometry("400x200")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._confirmar_fechar)

        # Garante que a janela apareça em primeiro plano ao abrir, em vez
        # de ficar escondida atrás de outras janelas já abertas.
        root.lift()
        root.attributes("-topmost", True)
        root.after(300, lambda: root.attributes("-topmost", False))
        root.focus_force()

        self.label_status = tk.Label(
            root, text="Aguardando novas etiquetas...", wraplength=370, justify="left", anchor="w"
        )
        self.label_status.pack(padx=15, pady=(18, 8), fill="x")

        self.barra = ttk.Progressbar(root, orient="horizontal", length=370, mode="determinate")
        self.barra.pack(padx=15, pady=4)

        self.label_contador = tk.Label(root, text="", anchor="w")
        self.label_contador.pack(padx=15, pady=(2, 10), fill="x")

        self.label_erros = tk.Label(root, text="", fg="#b00020", anchor="w", justify="left", wraplength=370)
        self.label_erros.pack(padx=15, pady=(0, 2), fill="x")

        self.link_limpar_erros = tk.Label(root, text="", fg="#0066cc", cursor="hand2", anchor="e")
        self.link_limpar_erros.pack(padx=15, pady=(0, 10), fill="x")
        self.link_limpar_erros.bind("<Button-1>", lambda e: self._limpar_erros())

        self._verificar_fila()

    def _confirmar_fechar(self):
        if messagebox.askyesno(
            "Encerrar RoboEtiquetas",
            "Tem certeza que quer encerrar o robô?\n\nEnquanto ele estiver fechado, nenhuma etiqueta nova será processada.",
        ):
            self._fechar()

    def _fechar(self):
        self.label_status.config(text="Encerrando...")
        self.root.update()
        self.ao_fechar()
        self.root.destroy()

    def _limpar_erros(self):
        self.contagem_erros = 0
        self.label_erros.config(text="")
        self.link_limpar_erros.config(text="")

    def _verificar_fila(self):
        try:
            while True:
                self._processar_evento(fila_status.get_nowait())
        except queue.Empty:
            pass
        self.root.after(self.INTERVALO_VERIFICACAO_MS, self._verificar_fila)

    def _processar_evento(self, evento):
        tipo = evento[0]

        if tipo == "status":
            _, texto = evento
            self.label_status.config(text=texto)

        elif tipo == "lote_inicio":
            _, total, nome_arquivo = evento
            self.barra["maximum"] = max(total, 1)
            self.barra["value"] = 0
            self.label_status.config(text=f"Processando '{nome_arquivo}'...")
            self.label_contador.config(text=f"0 de {total} etiqueta(s)")

        elif tipo == "lote_progresso":
            _, atual, total, detalhe = evento
            self.barra["value"] = atual
            self.label_contador.config(text=f"{atual} de {total} etiqueta(s)")
            self.label_status.config(text=detalhe)

        elif tipo == "lote_fim":
            self.barra["value"] = 0
            self.label_contador.config(text="")
            self.label_status.config(text="Aguardando novas etiquetas...")

        elif tipo == "consolidado":
            _, caminho, total = evento
            nome_arquivo = os.path.basename(caminho)
            self.label_status.config(text=f"Lote consolidado: {nome_arquivo} ({total} página(s))")

        elif tipo == "erro":
            _, numero_pedido, mensagem = evento
            self.contagem_erros += 1
            plural = "s" if self.contagem_erros != 1 else ""
            mensagem_curta = mensagem if len(mensagem) <= 90 else mensagem[:87] + "..."
            self.label_erros.config(
                text=f"⚠ {self.contagem_erros} erro{plural} - pedido {numero_pedido}:\n{mensagem_curta}"
            )
            self.link_limpar_erros.config(text="limpar")


def main():
    _configurar_logger()

    try:
        logger.info(f"Monitorando: {PASTA_MONITORADA}")
        logger.info(f"Log sendo salvo em: {ARQUIVO_LOG}")
        logger.info("Aguardando novas etiquetas em PDF...\n")

        observer = Observer()
        observer.schedule(HandlerEtiquetas(), PASTA_MONITORADA, recursive=False)
        observer.start()

        def parar_observer():
            logger.info("Encerrado pelo usuário.")
            observer.stop()
            observer.join()
            _finalizar_lote()  # não perde etiquetas já processadas mas ainda não consolidadas

        root = tk.Tk()
        JanelaStatus(root, ao_fechar=parar_observer)
        root.mainloop()
    except Exception:
        # Garante que um erro logo na inicialização fique registrado no log
        # em vez de simplesmente sumir - importante porque o .exe roda sem
        # janela de terminal visível (--noconsole).
        logger.exception("[erro fatal] O robô parou de funcionar:")
        raise


if __name__ == "__main__":
    main()
