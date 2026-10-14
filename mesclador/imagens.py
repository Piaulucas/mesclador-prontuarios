"""Páginas como imagem: renderizar PDF, ajustar legibilidade e nomear a pasta de saída.

Os ajustes (brilho, contraste, realce) valem para a página INTEIRA e são definidos por página. De propósito,
não há ferramenta para apagar ou editar trechos: o conteúdo do documento não muda.
"""

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

DPI_EXPORTACAO = 200     # boa leitura e arquivo de tamanho razoável
LIMITE_AJUSTE = 100      # brilho/contraste vão de -100 a +100


def paginas_do_pdf(caminho, dpi=DPI_EXPORTACAO):
    """Gera (numero_da_pagina, imagem PIL RGB) para cada página do PDF."""
    pdf = pdfium.PdfDocument(str(caminho))
    try:
        for i in range(len(pdf)):
            yield i + 1, pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()


def _fator(valor):
    """-100..100 -> 0..2 (0 = sem mudança vira fator 1)."""
    v = max(-LIMITE_AJUSTE, min(LIMITE_AJUSTE, int(valor or 0)))
    return 1 + v / LIMITE_AJUSTE


def ajustar(img, brilho=0, contraste=0, realce=False, giro=0):
    """Aplica os ajustes na página inteira e devolve uma nova imagem RGB.
    realce: tons de cinza + contraste automático + nitidez (destaca a escrita a caneta)."""
    img = img.convert("RGB")
    if realce:
        img = ImageOps.autocontrast(img.convert("L"), cutoff=2)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
    if brilho:
        img = ImageEnhance.Brightness(img).enhance(_fator(brilho))
    if contraste:
        img = ImageEnhance.Contrast(img).enhance(_fator(contraste))
    giro = int(giro or 0) % 360
    if giro:
        img = img.rotate(-giro, expand=True)   # PIL gira no sentido anti-horário
    return img


def pasta_livre(base, nome):
    """base/nome, ou base/nome (2), (3)... se já existir. Nunca reaproveita uma pasta."""
    base = Path(base)
    candidata = base / nome
    n = 2
    while candidata.exists():
        candidata = base / f"{nome} ({n})"
        n += 1
    return candidata
