# -*- coding: utf-8 -*-
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# --- Paleta -----------------------------------------------------------
AZUL_ESCURO = colors.HexColor("#0B2447")
AZUL_MEDIO = colors.HexColor("#19376D")
TEAL = colors.HexColor("#0F9D8C")
CINZA_TEXTO = colors.HexColor("#333333")
CINZA_CLARO = colors.HexColor("#6B7280")
FUNDO_CARD = colors.HexColor("#F4F6FA")

LARGURA_PAGINA, ALTURA_PAGINA = A4

doc = SimpleDocTemplate(
    "/mnt/user-data/outputs/RoboEtiquetas_LinkedIn.pdf",
    pagesize=A4,
    topMargin=16 * mm,
    bottomMargin=16 * mm,
    leftMargin=18 * mm,
    rightMargin=18 * mm,
    title="RoboEtiquetas",
)

# --- Estilos ------------------------------------------------------------
estilo_titulo = ParagraphStyle(
    "Titulo", fontName="Helvetica-Bold", fontSize=26, textColor=AZUL_ESCURO,
    spaceAfter=2, leading=30,
)
estilo_subtitulo = ParagraphStyle(
    "Subtitulo", fontName="Helvetica", fontSize=12.5, textColor=TEAL,
    spaceAfter=14, leading=16,
)
estilo_h2 = ParagraphStyle(
    "H2", fontName="Helvetica-Bold", fontSize=13, textColor=AZUL_MEDIO,
    spaceBefore=14, spaceAfter=6, leading=16,
)
estilo_corpo = ParagraphStyle(
    "Corpo", fontName="Helvetica", fontSize=10, textColor=CINZA_TEXTO,
    leading=15, alignment=TA_LEFT,
)
estilo_bullet = ParagraphStyle(
    "Bullet", fontName="Helvetica", fontSize=10, textColor=CINZA_TEXTO,
    leading=15, leftIndent=10, spaceAfter=3,
)
estilo_card_label = ParagraphStyle(
    "CardLabel", fontName="Helvetica-Bold", fontSize=9, textColor=CINZA_CLARO,
    leading=11,
)
estilo_card_valor = ParagraphStyle(
    "CardValor", fontName="Helvetica-Bold", fontSize=15, textColor=AZUL_ESCURO,
    leading=18,
)
estilo_tag = ParagraphStyle(
    "Tag", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.white,
    leading=11, alignment=1,
)
estilo_rodape = ParagraphStyle(
    "Rodape", fontName="Helvetica-Oblique", fontSize=8.5, textColor=CINZA_CLARO,
    leading=12,
)

elementos = []

# --- Cabeçalho ------------------------------------------------------------
elementos.append(Paragraph("RoboEtiquetas", estilo_titulo))
elementos.append(Paragraph(
    "Automação que conecta e-commerce e ERP para acelerar a separação de pedidos",
    estilo_subtitulo,
))
elementos.append(HRFlowable(width="100%", thickness=1.4, color=TEAL, spaceAfter=12))

# --- Cards de destaque ------------------------------------------------------
def celula_card(rotulo, valor):
    return Table(
        [[Paragraph(rotulo, estilo_card_label)], [Paragraph(valor, estilo_card_valor)]],
        colWidths=[52 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), FUNDO_CARD),
            ("TOPPADDING", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]),
    )

linha_cards = Table(
    [[
        celula_card("VOLUME DIÁRIO", "100-150 pedidos"),
        celula_card("CANAIS INTEGRADOS", "3 marketplaces"),
        celula_card("CONTAS TINY", "Multi-CNPJ"),
    ]],
    colWidths=[56 * mm, 56 * mm, 56 * mm],
    style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (1, 0), (-1, -1), 4),
    ]),
)
elementos.append(linha_cards)

# --- O problema -------------------------------------------------------
elementos.append(Paragraph("O problema", estilo_h2))
elementos.append(Paragraph(
    "O Tiny (ERP usado pela empresa) não tem um editor de PDF embutido — a etiqueta de envio "
    "gerada segue exatamente o padrão que vem pronto de cada marketplace (Shopee, Mercado Livre, "
    "TikTok Shop). Essa etiqueta traz apenas os dados de envio (destinatário, remetente, rastreio), "
    "sem SKU nem descrição do produto.",
    estilo_corpo,
))
elementos.append(Spacer(1, 4))
elementos.append(Paragraph(
    "Na prática, isso significava abrir o ERP manualmente, pedido por pedido, só para descobrir o "
    "que precisava ser separado e embalado — um gargalo direto na operação, com um volume de "
    "100 a 150 pedidos por dia só em um dos canais.",
    estilo_corpo,
))

# --- A solução --------------------------------------------------------
elementos.append(Paragraph("A solução", estilo_h2))
elementos.append(Paragraph(
    "Um robô em Python que fica de olho na pasta de downloads, identifica sozinho de qual "
    "marketplace veio cada etiqueta, consulta a API do Tiny para localizar o pedido correspondente "
    "e anexa automaticamente uma segunda página com a lista de itens (SKU, descrição, quantidade) "
    "— pronta para imprimir junto com a etiqueta original.",
    estilo_corpo,
))

itens_solucao = [
    "Reconhecimento automático do modelo de etiqueta (Shopee, Mercado Livre, TikTok Shop)",
    "Busca do pedido na Tiny, testando múltiplas contas/CNPJ em sequência",
    "Geração da página de itens e redimensionamento da etiqueta para o padrão térmico (100x150mm)",
    "Consolidação automática de etiquetas que chegam separadas em um único PDF",
    "Organização automática da pasta de downloads, com log e interface de acompanhamento",
]
for item in itens_solucao:
    elementos.append(Paragraph(f"•  {item}", estilo_bullet))

# --- Impacto -----------------------------------------------------------
elementos.append(Paragraph("Impacto na operação", estilo_h2))
elementos.append(Paragraph(
    "Eliminou a consulta manual pedido a pedido no ERP, agilizando diretamente a etapa de separação "
    "e reduzindo o risco de erro (item esquecido, pedido trocado) em um processo que antes dependia "
    "inteiramente de conferência manual.",
    estilo_corpo,
))

# --- Tecnologias --------------------------------------------------------
elementos.append(Paragraph("Tecnologias utilizadas", estilo_h2))

tags = ["Python", "PyMuPDF", "API REST", "Tkinter", "Watchdog", "PyInstaller"]
largura_tag = 26 * mm
celulas_tags = [Table([[Paragraph(t, estilo_tag)]], colWidths=[largura_tag],
                       style=TableStyle([
                           ("BACKGROUND", (0, 0), (-1, -1), AZUL_MEDIO),
                           ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                       ])) for t in tags]
linha_tags = Table(
    [celulas_tags[:3], celulas_tags[3:]],
    colWidths=[largura_tag] * 3,
    style=TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]),
)
elementos.append(linha_tags)

# --- Rodapé ---------------------------------------------------------------
elementos.append(Spacer(1, 16))
elementos.append(HRFlowable(width="100%", thickness=0.6, color=CINZA_CLARO, spaceAfter=8))
elementos.append(Paragraph(
    "Projeto desenvolvido e implantado internamente na Luma Festas, cobrindo Shopee, Mercado Livre "
    "e TikTok Shop, com suporte a múltiplos marketplaces e CNPJs.",
    estilo_rodape,
))

doc.build(elementos)
print("PDF gerado com sucesso.")
