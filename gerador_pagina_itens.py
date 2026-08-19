"""
gerador_pagina_itens.py

Gera, em memória, a página "LISTA DE ITENS DO PEDIDO" no mesmo estilo do
protótipo, a partir dos dados retornados por tiny_api.obter_pedido_completo().
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)

# Tamanho padrão de etiqueta térmica de envio: 100mm de largura x 150mm de altura.
TAMANHO_PAGINA = (100 * mm, 150 * mm)
MARGEM = 3 * mm


def gerar_pagina_itens(pedido: dict) -> bytes:
    """
    Recebe o dicionário de pedido (retorno de obter_pedido_completo) e devolve
    os bytes de um PDF de uma página só (100x150mm, tamanho de etiqueta
    térmica), pronto para ser anexado à etiqueta.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=TAMANHO_PAGINA,
        topMargin=MARGEM,
        bottomMargin=MARGEM,
        leftMargin=MARGEM,
        rightMargin=MARGEM,
    )

    estilo_titulo = ParagraphStyle(
        "Titulo", fontName="Helvetica-Bold", fontSize=10, spaceAfter=3,
    )
    estilo_aviso = ParagraphStyle(
        "Aviso", fontName="Helvetica", fontSize=5.5, textColor=colors.grey, spaceAfter=6,
    )
    estilo_info = ParagraphStyle(
        "Info", fontName="Helvetica", fontSize=7.5, spaceAfter=2, leading=9,
    )
    estilo_celula = ParagraphStyle(
        "Celula", fontName="Helvetica", fontSize=6.5, leading=8,
    )
    estilo_cabecalho = ParagraphStyle(
        "Cabecalho", fontName="Helvetica-Bold", fontSize=6.5, textColor=colors.white,
    )

    elementos = []

    elementos.append(Paragraph("LISTA DE ITENS DO PEDIDO", estilo_titulo))
    elementos.append(
        Paragraph("USO INTERNO - NAO SUBSTITUI A ETIQUETA DE ENVIO", estilo_aviso)
    )

    elementos.append(
        Paragraph(f"<b>Pedido:</b> {pedido.get('numero_ecommerce', '')}", estilo_info)
    )
    cliente = pedido.get("cliente", {}) or {}
    elementos.append(
        Paragraph(f"<b>Cliente:</b> {cliente.get('nome', '')}", estilo_info)
    )
    rastreio = pedido.get("codigo_rastreamento", "")
    if rastreio:
        elementos.append(Paragraph(f"<b>Rastreio:</b> {rastreio}", estilo_info))

    elementos.append(Spacer(1, 3 * mm))
    itens = pedido.get("itens", [])

    cabecalho = [
        Paragraph("QTD", estilo_cabecalho),
        Paragraph("SKU", estilo_cabecalho),
        Paragraph("DESCRICAO / VARIACAO", estilo_cabecalho),
    ]
    linhas = [cabecalho]

    total_unidades = 0
    for item in itens:
        quantidade = item.get("quantidade", 0)
        try:
            total_unidades += float(quantidade)
        except (TypeError, ValueError):
            pass

        # Remove ".0" de quantidades inteiras (ex: 4.0 -> 4)
        qtd_str = str(quantidade)
        if qtd_str.endswith(".0"):
            qtd_str = qtd_str[:-2]

        linhas.append([
            Paragraph(qtd_str, estilo_celula),
            Paragraph(item.get("codigo", ""), estilo_celula),
            Paragraph(item.get("descricao", ""), estilo_celula),
        ])

    largura_util = TAMANHO_PAGINA[0] - 2 * MARGEM
    tabela = Table(
        linhas,
        colWidths=[largura_util * 0.12, largura_util * 0.24, largura_util * 0.64],
        repeatRows=1,
    )
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabela)

    elementos.append(Spacer(1, 3 * mm))
    elementos.append(
        Paragraph(
            f"<b>Tipos de produtos:</b> {len(itens)}"
            f"&nbsp;&nbsp;&nbsp;<b>Total de unidades:</b> {int(total_unidades)}",
            estilo_info,
        )
    )

    doc.build(elementos)
    return buffer.getvalue()
