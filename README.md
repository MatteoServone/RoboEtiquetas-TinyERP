# RoboEtiquetas

Automação que conecta a impressão de etiquetas de envio (Shopee, Mercado Livre e TikTok Shop) com o ERP Tiny, eliminando o trabalho manual de conferir e separar cada pedido.

## Por que esse robô existe

A Luma Festas vende em vários marketplaces integrados ao Tiny. No dia a dia, isso significava um processo manual repetitivo pra cada pedido despachado:

1. Baixar a etiqueta de envio no painel do marketplace
2. Abrir o Tiny e localizar o pedido correspondente
3. Conferir os itens do pedido pra saber o que separar/embalar
4. Imprimir a etiqueta e, muitas vezes, anotar ou copiar os itens à parte

### A causa raiz do problema

O Tiny **não tem um editor de PDF embutido no ERP**. A etiqueta de envio que ele gera segue exatamente o padrão que vem do próprio e-commerce (Shopee, Mercado Livre, TikTok Shop) ou seja, o Tiny não tem como alterar o layout dessa etiqueta antes de imprimir.

O problema prático disso: essa etiqueta, do jeito que vem do e-commerce, **não traz o SKU nem a descrição do produto** só os dados de envio (destinatário, remetente, código de rastreio). Pra saber o que efetivamente tinha dentro daquele pedido, era preciso abrir o Tiny à parte e procurar manualmente, pedido por pedido.

Com um volume de **100 a 150 pedidos por dia** só de um canal, isso virava um gargalo direto na etapa de **separação dos produtos** cada pedido exigia essa consulta manual antes de conseguir separar e embalar, atrasando a operação inteira.

### A solução

Como não dá pra editar o PDF dentro do próprio Tiny, o RoboEtiquetas resolve isso por fora: ele identifica a etiqueta sozinho, busca o pedido certo na API da Tiny e **anexa uma segunda página com o que faltava** SKU, descrição e quantidade de cada item grudada na própria etiqueta, pronta pra imprimir junto. Isso elimina a consulta manual e agiliza diretamente a etapa de separação.

## O que o robô faz

- **Fica de olho na pasta Downloads** o tempo todo, em segundo plano, com uma janela simples mostrando o status atual e uma barra de progresso
- **Reconhece automaticamente o marketplace** de origem de cada etiqueta (Shopee, Mercado Livre, TikTok Shop), cada um com seu próprio jeito de indicar o número do pedido
- **Consulta a Tiny automaticamente**, tentando as contas cadastradas em sequência (a operação roda em dois CNPJs) até achar o pedido certo
- **Gera uma página extra** com a lista de itens do pedido (SKU, descrição, quantidade), no tamanho padrão de etiqueta térmica (100x150mm)
- **Redimensiona a etiqueta original** pra caber certinho em 100x150mm, sem distorcer, mesmo quando ela chega em outro tamanho de página
- **Lida com lotes de etiquetas** tanto quando vêm todas juntas num PDF só (Shopee, Mercado Livre), quanto quando vêm uma por arquivo (TikTok Shop), consolidando essas últimas num único PDF depois de um tempo sem nada novo chegar
- **Organiza a pasta Downloads** automaticamente, movendo cada PDF já processado pra uma subpasta separada por conta (`Processadas Luma`, `Processadas LM`)
- **Registra tudo em log**, com rotação diária e retenção configurável, pra dar pra conferir depois o que foi processado mesmo sem a janela aberta
- **Avisa na tela quando algo falha** (ex: pedido não encontrado na Tiny), com o motivo do erro, sem precisar abrir o log pra descobrir

## Como funciona, por trás dos panos

```
Etiqueta baixada no marketplace
        │
        ▼
Pasta Downloads (monitorada pelo watchdog)
        │
        ▼
Identificação do modelo de etiqueta (Shopee / Mercado Livre / TikTok Shop)
        │
        ▼
Extração do número do pedido (numeroEcommerce ou código de rastreio)
        │
        ▼
Consulta à API do Tiny (tentando cada conta/CNPJ cadastrado)
        │
        ▼
Geração da página de itens + redimensionamento da etiqueta original
        │
        ▼
PDF final salvo em "Processadas <conta>" (aberto automaticamente)
```

## Modelos de etiqueta suportados

| Marketplace | Como é identificado | Como o pedido é localizado |
|---|---|---|
| Shopee | Texto `DESTINATÁRIO` | Número do pedido (`numeroEcommerce`) |
| Mercado Livre | Texto `Envio:` | Pack ID, com fallback pro número de Venda |
| TikTok Shop | Texto `REMETENTE:` | Código de rastreamento (busca por data, já que a Tiny não permite filtrar por esse campo diretamente) |

Novos modelos podem ser cadastrados em `modelos_etiqueta.py` sem precisar mexer no resto do código.

## Requisitos

- Windows
- Python 3.12+ (só pra rodar a partir do código-fonte - o `.exe` empacotado não precisa)
- Conta na Tiny com a API 2.0 habilitada, para cada CNPJ envolvido

## Instalação e configuração

1. Clone o repositório
2. Crie o ambiente virtual e instale as dependências:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Configure o token da API da Tiny pra cada conta cadastrada:
   ```powershell
   python configurar_token.py
   ```
4. Rode o robô:
   ```powershell
   python monitor.py
   ```

### Gerando o executável

```powershell
pyinstaller --onefile --noconsole --name RoboEtiquetas --hidden-import keyring.backends.Windows --hidden-import win32timezone monitor.py
pyinstaller --onefile --name ConfigurarToken configurar_token.py
```

### Iniciar automaticamente com o Windows

Crie um atalho para `dist\RoboEtiquetas.exe` na pasta de Inicialização do Windows (`shell:startup`).

## Configuração ajustável (`config.json`)

Criado automaticamente na primeira execução, ao lado do programa:

```json
{
  "inatividade_lote_segundos": 40,
  "cache_rastreio_validade_segundos": 300,
  "dias_de_log_mantidos": 30
}
```

- `inatividade_lote_segundos`: quanto tempo sem etiqueta nova até consolidar o lote acumulado (usado pelo TikTok Shop)
- `cache_rastreio_validade_segundos`: por quanto tempo o robô reaproveita a lista de pedidos recentes da Tiny antes de buscar de novo
- `dias_de_log_mantidos`: quantos dias de log ficam guardados antes de apagar automaticamente

## Estrutura do projeto

```
monitor.py              # ponto de entrada - monitoramento, processamento, janela
modelos_etiqueta.py      # cadastro dos modelos de etiqueta reconhecidos
tiny_api.py               # integração com a API 2.0 da Tiny (multi-conta)
gerador_pagina_itens.py   # geração da página de itens (100x150mm)
configurar_token.py       # utilitário de configuração inicial de credenciais
```

## Segurança

Os tokens da API da Tiny nunca ficam no código — são salvos com segurança no Gerenciador de Credenciais do Windows, via `keyring`, um por conta/CNPJ.

## Status

Em uso na operação da Luma Festas, cobrindo Shopee, Mercado Livre e TikTok Shop. Novos marketplaces (ex: Shein) podem ser adicionados sob demanda.
