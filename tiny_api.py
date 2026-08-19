"""
tiny_api.py

Módulo responsável pela comunicação com a API 2.0 do Tiny/Olist.
Suporta múltiplas contas (uma por CNPJ) - no Tiny, cada CNPJ é uma conta
separada, com seu próprio token de API.

Uso básico:
    from tiny_api import consultar_pedido_por_ecommerce, salvar_token, TinyAPIError

    # Rodar uma vez por conta, para salvar o token com segurança no
    # Gerenciador de Credenciais do Windows (não precisa mais repetir isso
    # depois):
    salvar_token("990d19b85cdce16b249abf42ea66c71e65a5e9ff507ff74487b3709b004375ff", nome_conta="Luma")

    pedido = consultar_pedido_por_ecommerce("260717VYHN0A2F", nome_conta="Luma")
    print(pedido["nome"], pedido["valor"])
"""

import keyring
import requests
from datetime import datetime, timedelta
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# --- Configurações -----------------------------------------------------

SERVICO_KEYRING = "RoboEtiquetas"
USUARIO_KEYRING = "tiny_api_token"

# Nomes das contas/CNPJs cadastrados no robô, na ordem em que são
# tentados ao procurar um pedido. Pra cadastrar um CNPJ novo, basta
# acrescentar o nome aqui e rodar o ConfigurarToken pra ele.
CONTAS = ["Luma", "LM"]

URL_PEDIDOS_PESQUISA = "https://api.tiny.com.br/api2/pedidos.pesquisa.php"
URL_PEDIDO_OBTER = "https://api.tiny.com.br/api2/pedido.obter.php"

# Códigos de erro do Tiny que valem a pena tentar de novo (instabilidade
# temporária), conforme a tabela oficial de códigos de erro da API.
CODIGOS_ERRO_TRANSITORIOS = {
    5,   # API bloqueada ou sem acesso
    6,   # API bloqueada momentaneamente - muitos acessos no último minuto
    11,  # API bloqueada momentaneamente - muitos acessos concorrentes
    35,  # Ocorreu um erro inesperado, tente novamente mais tarde
    99,  # Sistema em manutenção
}


class TinyAPIError(Exception):
    """Erro retornado pela API do Tiny (ex: token inválido, pedido não encontrado)."""

    def __init__(self, codigo_erro, mensagem):
        self.codigo_erro = codigo_erro
        self.mensagem = mensagem
        super().__init__(f"[Tiny API erro {codigo_erro}] {mensagem}")


class TinyErroTransitorio(TinyAPIError):
    """Subclasse usada só para acionar o retry automático."""


# --- Gerenciamento do token ---------------------------------------------

def _chave_keyring(nome_conta: str) -> str:
    # A primeira conta cadastrada usa a MESMA chave de sempre, sem sufixo
    # - assim quem já tinha configurado o token antes não precisa refazer
    # nada. Só as contas extras usam uma chave com o nome no final.
    if nome_conta == CONTAS[0]:
        return USUARIO_KEYRING
    return f"{USUARIO_KEYRING}_{nome_conta}"


def salvar_token(token: str, nome_conta: str = CONTAS[0]) -> None:
    """Salva o token da API do Tiny de uma conta no Gerenciador de Credenciais do Windows."""
    keyring.set_password(SERVICO_KEYRING, _chave_keyring(nome_conta), token)


def obter_token(nome_conta: str = CONTAS[0]) -> str:
    """Recupera o token salvo de uma conta. Lança erro claro se ainda não foi configurado."""
    token = keyring.get_password(SERVICO_KEYRING, _chave_keyring(nome_conta))
    if not token:
        raise RuntimeError(
            f"Nenhum token da API do Tiny foi encontrado para a conta '{nome_conta}'. "
            f"Rode o ConfigurarToken (ou salvar_token('SEU_TOKEN_AQUI', nome_conta='{nome_conta}')) antes de continuar."
        )
    return token


# --- Consulta de pedidos --------------------------------------------------

@retry(
    retry=retry_if_exception_type(TinyErroTransitorio),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
def _chamar_api_pedidos(params: dict) -> dict:
    """Faz a chamada POST à API do Tiny e trata os códigos de erro do retorno."""
    resposta = requests.post(URL_PEDIDOS_PESQUISA, data=params, timeout=15)
    resposta.raise_for_status()
    dados = resposta.json()

    retorno = dados.get("retorno", {})
    status = retorno.get("status")

    if status == "Erro":
        codigo = int(retorno.get("codigo_erro", -1))
        erros = retorno.get("erros", [])
        mensagem = erros[0]["erro"] if erros else "Erro desconhecido"

        if codigo in CODIGOS_ERRO_TRANSITORIOS:
            raise TinyErroTransitorio(codigo, mensagem)
        raise TinyAPIError(codigo, mensagem)

    return retorno


def consultar_pedido_por_ecommerce(numero_ecommerce: str, nome_conta: str = CONTAS[0]) -> dict:
    """
    Consulta um pedido pelo identificador do e-commerce (ex: código da Shopee),
    numa conta específica.

    Retorna um dicionário com os dados do pedido (nome, valor, situação, etc.).
    Lança TinyAPIError se o pedido não for encontrado ou se o pedido retornado
    não corresponder ao identificador buscado (checagem de segurança).
    """
    token = obter_token(nome_conta)

    params = {
        "token": token,
        "formato": "json",
        "numeroEcommerce": numero_ecommerce,
    }

    retorno = _chamar_api_pedidos(params)

    pedidos = retorno.get("pedidos", [])
    if not pedidos:
        raise TinyAPIError(20, f"Nenhum pedido encontrado para '{numero_ecommerce}' na conta '{nome_conta}'")

    pedido = pedidos[0]["pedido"]

    # Checagem de segurança: confirma que o pedido devolvido é mesmo o que
    # foi buscado (evita o tipo de erro que já pegamos no Postman, quando
    # numero e numeroEcommerce foram confundidos).
    if pedido.get("numero_ecommerce") != numero_ecommerce:
        raise TinyAPIError(
            -1,
            f"Pedido retornado ({pedido.get('numero_ecommerce')}) não bate "
            f"com o identificador buscado ({numero_ecommerce})",
        )

    return pedido


def consultar_pedido_multi_conta(numero_ecommerce: str) -> tuple:
    """
    Tenta localizar e obter o pedido completo em cada conta cadastrada (ver
    CONTAS), na ordem, até achar. Devolve (pedido_completo, nome_conta).
    Lança o último erro se não encontrar em nenhuma delas.
    """
    ultimo_erro = None
    for nome_conta in CONTAS:
        try:
            resumo = consultar_pedido_por_ecommerce(numero_ecommerce, nome_conta=nome_conta)
            return obter_pedido_completo(resumo["id"], nome_conta=nome_conta), nome_conta
        except TinyAPIError as e:
            ultimo_erro = e
            continue
    raise ultimo_erro


@retry(
    retry=retry_if_exception_type(TinyErroTransitorio),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
def _chamar_api_pedido_obter(params: dict) -> dict:
    """Faz a chamada POST ao pedido.obter.php e trata os códigos de erro do retorno."""
    resposta = requests.post(URL_PEDIDO_OBTER, data=params, timeout=15)
    resposta.raise_for_status()
    dados = resposta.json()

    retorno = dados.get("retorno", {})
    status = retorno.get("status")

    if status == "Erro":
        codigo = int(retorno.get("codigo_erro", -1))
        erros = retorno.get("erros", [])
        mensagem = erros[0]["erro"] if erros else "Erro desconhecido"

        if codigo in CODIGOS_ERRO_TRANSITORIOS:
            raise TinyErroTransitorio(codigo, mensagem)
        raise TinyAPIError(codigo, mensagem)

    return retorno


def obter_pedido_completo(id_pedido, nome_conta: str = CONTAS[0]) -> dict:
    """
    Busca os dados completos de um pedido pelo seu id interno na Tiny (o
    mesmo id devolvido por consultar_pedido_por_ecommerce), numa conta
    específica - o id só é válido dentro da conta de onde ele veio.

    Retorna um dicionário com os dados do pedido, incluindo:
      - numero, numero_ecommerce, situacao, codigo_rastreamento
      - cliente: {nome, ...}
      - itens: lista de dicionários {codigo, descricao, unidade, quantidade, valor_unitario}
    """
    token = obter_token(nome_conta)

    params = {
        "token": token,
        "formato": "json",
        "id": id_pedido,
    }

    retorno = _chamar_api_pedido_obter(params)
    pedido = retorno.get("pedido")

    if not pedido:
        raise TinyAPIError(-1, f"Pedido com id '{id_pedido}' não encontrado na conta '{nome_conta}'")

    # Achata a lista de itens (a API devolve cada item embrulhado num
    # dicionário {"item": {...}}) para facilitar o uso no resto do código.
    itens_brutos = pedido.get("itens", [])
    pedido["itens"] = [item["item"] for item in itens_brutos]

    return pedido


def listar_pedidos_recentes(dias_para_tras: int = 5, nome_conta: str = CONTAS[0]) -> list:
    """
    Busca todos os pedidos cadastrados nos últimos `dias_para_tras` dias
    numa conta específica, percorrendo todas as páginas de resultado, e
    devolve a lista completa.

    Útil para montar um índice local (por exemplo, por código de
    rastreamento) UMA VEZ SÓ ao processar um lote de várias etiquetas, em
    vez de repetir a mesma busca por data para cada etiqueta individual -
    lotes de 100+ etiquetas do mesmo e-commerce (ex: TikTok Shop) fariam
    dezenas de buscas redundantes se cada etiqueta buscasse por conta
    própria.
    """
    token = obter_token(nome_conta)

    hoje = datetime.now()
    data_inicial = (hoje - timedelta(days=dias_para_tras)).strftime("%d/%m/%Y")
    data_final = hoje.strftime("%d/%m/%Y")

    pedidos = []
    pagina = 1
    while True:
        params = {
            "token": token,
            "formato": "json",
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "pagina": pagina,
        }
        retorno = _chamar_api_pedidos(params)

        for item in retorno.get("pedidos", []):
            pedidos.append(item["pedido"])

        numero_paginas = int(retorno.get("numero_paginas", 1))
        if pagina >= numero_paginas:
            break
        pagina += 1

    return pedidos


def buscar_pedido_por_rastreio(codigo_rastreamento: str, dias_para_tras: int = 5, nome_conta: str = CONTAS[0]) -> dict:
    """
    Busca um único pedido pelo código de rastreamento, numa conta
    específica (usado, por exemplo, pelas etiquetas do TikTok Shop, que
    trazem só o código de rastreio, não um identificador de e-commerce). A
    API da Tiny não permite filtrar diretamente por esse campo, então
    busca por data e compara manualmente.

    Para processar VÁRIAS etiquetas de uma vez, prefira chamar
    listar_pedidos_recentes() uma única vez e montar um índice (dict) por
    código de rastreamento - essa função aqui é para uso avulso, com uma
    etiqueta só (ex: testes manuais), já que faz sua própria busca do
    zero toda vez que é chamada.
    """
    for pedido in listar_pedidos_recentes(dias_para_tras, nome_conta=nome_conta):
        if pedido.get("codigo_rastreamento") == codigo_rastreamento:
            return pedido

    raise TinyAPIError(
        20,
        f"Nenhum pedido encontrado com o código de rastreamento '{codigo_rastreamento}' "
        f"nos últimos {dias_para_tras} dias na conta '{nome_conta}'",
    )


# --- Teste manual rápido --------------------------------------------------

if __name__ == "__main__":
    identificador_teste = input("Digite o numeroEcommerce para testar: ").strip()
    try:
        pedido, nome_conta = consultar_pedido_multi_conta(identificador_teste)
        print(f"\nPedido encontrado na conta '{nome_conta}':")
        print(f"  Número Tiny:      {pedido['numero']}")
        print(f"  Cliente:          {pedido['nome']}")
        print(f"  Valor:            R$ {pedido['valor']}")
        print(f"  Situação:         {pedido['situacao']}")
    except TinyAPIError as e:
        print(f"\nErro ao consultar pedido: {e}")
