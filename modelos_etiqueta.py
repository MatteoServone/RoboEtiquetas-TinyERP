"""
modelos_etiqueta.py

Cadastro dos modelos de etiqueta que o robô reconhece. Cada modelo sabe:
  - qual texto usar como "âncora" para localizar a etiqueta dentro da
    página (e detectar se há mais de uma etiqueta na mesma página, em
    caso de impressão em lote)
  - como extrair o número do pedido/pack a partir da etiqueta

Para cadastrar um novo modelo (uma nova transportadora/marketplace):
  1. Escreva uma função `_extrair_numero_<nome>(pagina, area_limite=None)`
     que devolve o número do pedido como string, ou None se não achar.
  2. Adicione um dicionário na lista MODELOS_ETIQUETA lá embaixo, com o
     texto-âncora exclusivo desse modelo (um texto que só aparece na
     etiqueta de verdade, não em outras páginas que o PDF possa conter).
"""

import re


def _palavras_por_linha(pagina, area_limite=None):
    """
    Reconstrói as linhas visuais reais da página (ou de uma área
    específica dela), agrupando as palavras pela posição vertical (Y) em
    vez de usar os metadados internos de bloco/linha do PDF, que nem
    sempre refletem o agrupamento visual real (rótulo e valor podem
    pertencer a blocos de desenho diferentes mesmo estando lado a lado).

    Devolve uma lista de linhas, cada uma sendo uma lista de textos
    (strings), já ordenados da esquerda pra direita.
    """
    TOLERANCIA_Y = 3  # pontos - palavras dentro dessa faixa são consideradas na mesma linha

    if area_limite is not None:
        palavras = pagina.get_text("words", clip=area_limite)
    else:
        palavras = pagina.get_text("words")

    palavras_ordenadas = sorted(palavras, key=lambda w: (w[1], w[0]))

    linhas = []
    linha_atual = []
    y_referencia = None

    for x0, y0, x1, y1, texto, *_ in palavras_ordenadas:
        if y_referencia is not None and abs(y0 - y_referencia) > TOLERANCIA_Y:
            linhas.append([t for _, t in sorted(linha_atual, key=lambda p: p[0])])
            linha_atual = []
        linha_atual.append((x0, texto))
        y_referencia = y0

    if linha_atual:
        linhas.append([t for _, t in sorted(linha_atual, key=lambda p: p[0])])

    return linhas


def detectar_grade_de_etiquetas(pagina, texto_ancora: str) -> list:
    """
    Detecta quantas etiquetas individuais existem dentro de uma única
    página do PDF - impressão em lote costuma juntar várias etiquetas
    numa grade (2, 4, 6...) para economizar papel, com células de tamanho
    uniforme. Localiza cada etiqueta pela posição do `texto_ancora`
    (específico de cada modelo cadastrado), conta quantas colunas/linhas
    existem e divide a página em células de tamanho igual. Devolve a
    lista de retângulos correspondentes, um por etiqueta, na ordem de
    leitura (linha por linha, de cima pra baixo, esquerda pra direita).
    """
    import fitz  # import local para não exigir pymupdf em quem só usa as funções de extração

    TOLERANCIA = 15  # pontos - âncoras dentro dessa faixa são consideradas na mesma coluna/linha

    ancoras = [
        (x0, y0)
        for x0, y0, x1, y1, texto, *_ in pagina.get_text("words")
        if texto.strip().upper() == texto_ancora.upper()
    ]

    if not ancoras:
        return [pagina.rect]

    def contar_grupos(valores):
        valores_ordenados = sorted(valores)
        grupos = 1
        for anterior, atual in zip(valores_ordenados, valores_ordenados[1:]):
            if atual - anterior > TOLERANCIA:
                grupos += 1
        return grupos

    num_colunas = contar_grupos([a[0] for a in ancoras])
    num_linhas = contar_grupos([a[1] for a in ancoras])

    largura_celula = pagina.rect.width / num_colunas
    altura_celula = pagina.rect.height / num_linhas

    indices_com_etiqueta = set()
    for x0, y0 in ancoras:
        indice_coluna = min(int((x0 - pagina.rect.x0) // largura_celula), num_colunas - 1)
        indice_linha = min(int((y0 - pagina.rect.y0) // altura_celula), num_linhas - 1)
        indices_com_etiqueta.add((indice_linha, indice_coluna))

    celulas = []
    for indice_linha in range(num_linhas):
        for indice_coluna in range(num_colunas):
            if (indice_linha, indice_coluna) not in indices_com_etiqueta:
                continue  # última linha pode ter menos etiquetas que o resto da grade
            x0 = pagina.rect.x0 + indice_coluna * largura_celula
            y0 = pagina.rect.y0 + indice_linha * altura_celula
            celulas.append(fitz.Rect(x0, y0, x0 + largura_celula, y0 + altura_celula))

    return celulas


# --- Modelo: Shopee ---------------------------------------------------

PADRAO_PEDIDO_SHOPEE = re.compile(r"Pedido:\s*([A-Za-z0-9]+)")


def _extrair_numero_shopee(pagina, area_limite=None) -> str | None:
    for linha in _palavras_por_linha(pagina, area_limite):
        texto_da_linha = " ".join(linha)
        match = PADRAO_PEDIDO_SHOPEE.search(texto_da_linha)
        if match:
            return match.group(1)
    return None


# --- Modelo: Mercado Livre ------------------------------------------------

def _extrair_numero_mercado_livre(pagina, area_limite=None) -> str | None:
    """
    O Mercado Livre identifica o pedido pelo 'Pack ID:'. Na etiqueta, esse
    número às vezes aparece dividido em dois blocos de texto (ex: '20000'
    e '14104659809'), mas representa um único número contínuo quando
    juntos ('2000014104659809') - é assim que ele é usado como
    numeroEcommerce na consulta à Tiny.

    Nem todo envio tem 'Pack ID:' - só aparece quando o envio agrupa mais
    de um pedido na mesma etiqueta. Quando não tem, usa o número de
    'Venda:' no lugar, que sempre aparece.
    """
    linhas = _palavras_por_linha(pagina, area_limite)

    for linha in linhas:
        for i in range(len(linha) - 1):
            if linha[i] == "Pack" and linha[i + 1].startswith("ID"):
                resto = "".join(linha[i + 2:])
                numeros = re.sub(r"[^0-9]", "", resto)
                if numeros:
                    return numeros

    for linha in linhas:
        for i, palavra in enumerate(linha):
            if palavra == "Venda:":
                resto = "".join(linha[i + 1:])
                numeros = re.sub(r"[^0-9]", "", resto)
                if numeros:
                    return numeros

    return None


# --- Cadastro dos modelos -------------------------------------------------
#
# IMPORTANTE:
#   - o texto_ancora de cada modelo precisa ser exclusivo da etiqueta de
#     verdade - não pode aparecer em outras páginas auxiliares que o
#     marketplace às vezes inclui no mesmo PDF (como uma lista de produtos)
#   - a ORDEM importa: modelos com âncora mais específica/exclusiva devem
#     vir primeiro na lista. O Shopee usa "DESTINATÁRIO", que é um texto
#     genérico que outros modelos (como o TikTok Shop) também usam - por
#     isso o Shopee fica por último, como uma opção "resto" (catch-all)
#   - tipo_busca indica como consultar a Tiny com o número extraído:
#       "numero_ecommerce" -> tiny_api.consultar_pedido_por_ecommerce()
#       "rastreio"         -> tiny_api.buscar_pedido_por_rastreio()
#   - acumular_em_lote (opcional, padrão False): marque como True quando o
#     e-commerce baixa UMA ETIQUETA POR ARQUIVO (em vez de um PDF já com o
#     lote inteiro) - o robô vai juntar essas etiquetas num único PDF
#     depois de um tempo sem nada novo chegar, em vez de abrir cada uma
#     separadamente. Modelos que já vêm com o lote todo no mesmo arquivo
#     (Shopee, Mercado Livre) não precisam disso.

MODELOS_ETIQUETA = [
    {
        "nome": "Mercado Livre",
        "texto_ancora": "Envio:",
        "tipo_busca": "numero_ecommerce",
        "extrair_numero": _extrair_numero_mercado_livre,
    },
    {
        "nome": "TikTok Shop",
        "texto_ancora": "REMETENTE:",
        "tipo_busca": "rastreio",
        "extrair_numero": _extrair_numero_shopee,  # mesmo padrão 'Pedido:', mas o valor é o código de rastreio
        "acumular_em_lote": True,
    },
    {
        "nome": "Shopee",
        "texto_ancora": "DESTINATÁRIO",
        "tipo_busca": "numero_ecommerce",
        "extrair_numero": _extrair_numero_shopee,
    },
]


def identificar_modelo(pagina):
    """
    Descobre qual modelo de etiqueta está numa página, testando o
    texto-âncora de cada modelo cadastrado. Devolve o modelo (dict)
    encontrado, ou None se nenhum bater (nesse caso, a página é ignorada
    pelo robô - provavelmente é uma página auxiliar, não uma etiqueta).
    """
    palavras_da_pagina = {
        texto.strip().upper() for _, _, _, _, texto, *_ in pagina.get_text("words")
    }
    for modelo in MODELOS_ETIQUETA:
        if modelo["texto_ancora"].upper() in palavras_da_pagina:
            return modelo
    return None
