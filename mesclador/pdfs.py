"""Miniaturas e mesclagem de PDFs/imagens."""

import io
import re
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

from . import imagens

EXT_PDF = {".pdf"}
EXT_IMG = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic"}
DPI_PADRAO = 150   # usado quando a imagem não informa a resolução


def tipo_do_arquivo(nome):
    """'pdf', 'img' ou None (formato não suportado)."""
    ext = Path(nome).suffix.lower()
    if ext in EXT_PDF:
        return "pdf"
    if ext in EXT_IMG:
        return "img"
    return None


def limpar_nome_arquivo(texto):
    """Remove caracteres que o macOS/Windows não aceitam em nome de arquivo."""
    return re.sub(r'[\\/:*?"<>|]', "", texto).strip()


def abrir_imagem(caminho):
    """Abre a imagem já com a rotação da câmera (EXIF) aplicada."""
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".heic":
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            raise ValueError("Para fotos HEIC instale: pip install pillow-heif")
        register_heif_opener()
    return ImageOps.exif_transpose(Image.open(caminho))


def gerar_miniatura(caminho, tipo, destino, tamanho=(360, 480)):
    """Salva a miniatura da 1ª página em `destino` (JPEG) e devolve o nº de páginas."""
    if tipo == "pdf":
        pdf = pdfium.PdfDocument(str(caminho))
        try:
            paginas = len(pdf)
            img = pdf[0].render(scale=0.5).to_pil()
        finally:
            pdf.close()
    else:
        paginas = 1
        img = abrir_imagem(caminho)
    img = img.convert("RGB")
    img.thumbnail(tamanho)
    img.save(destino, "JPEG", quality=80)
    return paginas


def dividir_pdf(caminho):
    """Se o PDF tem mais de 1 página, devolve uma lista com o conteúdo (bytes) de um PDF por página,
    copiando as páginas sem renderizar. PDF de 1 página (ou ilegível para o pypdf): None."""
    try:
        leitor = PdfReader(caminho)
        if len(leitor.pages) < 2:
            return None
        partes = []
        for pagina in leitor.pages:
            writer = PdfWriter()
            writer.add_page(pagina)
            buffer = io.BytesIO()
            writer.write(buffer)
            partes.append(buffer.getvalue())
        return partes
    except Exception:
        return None


def primeira_pagina(caminho, tipo, lado):
    """1ª página do arquivo como imagem PIL RGB, com o lado maior em ~`lado` px (prévia ampliada)."""
    if tipo == "pdf":
        pdf = pdfium.PdfDocument(str(caminho))
        try:
            largura, altura = pdf[0].get_size()
            img = pdf[0].render(scale=lado / max(largura, altura)).to_pil()
        finally:
            pdf.close()
    else:
        img = abrir_imagem(caminho)
    img = img.convert("RGB")
    img.thumbnail((lado, lado))
    return img


def ajuste_neutro(ajustes):
    """True se não há brilho, contraste nem realce (a página não precisa ser reprocessada)."""
    a = ajustes or {}
    return not (a.get("brilho") or a.get("contraste") or a.get("realce"))


def _imagem_para_pdf(img, dpi):
    """Converte uma imagem PIL em PDF de 1 página (em memória), já com os ajustes e o giro aplicados."""
    buffer = io.BytesIO()
    img.save(buffer, format="PDF", resolution=float(dpi), quality=85)
    buffer.seek(0)
    return PdfReader(buffer)


def _paginas_ajustadas(caminho, tipo, giro, ajustes):
    """Páginas como imagem com os ajustes da página inteira aplicados (PDF a 200 DPI)."""
    if tipo == "pdf":
        for _, img in imagens.paginas_do_pdf(caminho, imagens.DPI_EXPORTACAO):
            yield imagens.ajustar(img, giro=giro, **ajustes), imagens.DPI_EXPORTACAO
    else:
        with abrir_imagem(caminho) as img:
            dpi = (img.info.get("dpi") or (DPI_PADRAO,))[0] or DPI_PADRAO
            yield imagens.ajustar(img, giro=giro, **ajustes), dpi


def mesclar(itens):
    """Junta os arquivos na ordem recebida.
    itens: lista de (caminho, tipo, giro) ou (caminho, tipo, giro, ajustes) — giro em graus, sentido horário
    (0/90/180/270); ajustes = {"brilho", "contraste", "realce"}.
    Sem ajuste, a página do PDF é copiada sem alteração; com ajuste, vira imagem (PDF a 200 DPI).
    Devolve um PdfWriter pronto para ser gravado."""
    writer = PdfWriter()
    for caminho, tipo, giro, *resto in itens:
        giro = int(giro) % 360
        ajustes = resto[0] if resto else None
        if ajuste_neutro(ajustes) and tipo == "pdf":
            for pagina in PdfReader(caminho).pages:
                if giro:
                    pagina.rotate(giro)
                writer.add_page(pagina)
            continue
        ajustes = {k: (ajustes or {}).get(k, padrao) for k, padrao in (("brilho", 0), ("contraste", 0), ("realce", False))}
        for img, dpi in _paginas_ajustadas(caminho, tipo, giro, ajustes):
            for pagina in _imagem_para_pdf(img, dpi).pages:
                writer.add_page(pagina)
    return writer


def achar_subpasta(pasta, palavra, nome_padrao):
    """Dentro de `pasta`, procura uma subpasta cujo nome comece com `palavra`
    (sem diferenciar maiúsculas/acentos). Devolve (caminho, existe).
    Se não houver, devolve pasta/nome_padrao para ser criada."""
    from .planilha import normalizar
    alvo = normalizar(palavra)
    candidatas = sorted(p for p in Path(pasta).iterdir()
                        if p.is_dir() and normalizar(p.name).startswith(alvo))
    if candidatas:
        return candidatas[0], True
    return Path(pasta) / nome_padrao, False


def ordem_natural(texto):
    """Chave de ordenação: 'pag2' antes de 'pag10'."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", texto.lower())]


def arquivos_do_zip(origem):
    """Lê um .zip e devolve ([(nome_do_arquivo, bytes)], pasta_raiz).
    Só PDFs/imagens, em ordem natural pelo caminho dentro do zip; ignora lixo do macOS
    (__MACOSX, ._*, .DS_Store). pasta_raiz é a pasta única que contém tudo (ex.: o nome
    do paciente quando a pasta foi baixada inteira do Drive), ou None.
    Nada é extraído para o disco com o nome original (evita caminhos maliciosos no zip)."""
    itens = []
    with zipfile.ZipFile(origem) as z:
        for info in z.infolist():
            caminho = info.filename
            partes = caminho.replace("\\", "/").split("/")
            nome = partes[-1]
            if info.is_dir() or "__MACOSX" in partes or nome.startswith("."):
                continue
            if tipo_do_arquivo(nome):
                itens.append((caminho, nome))
        itens.sort(key=lambda x: ordem_natural(x[0]))
        raizes = {c.replace("\\", "/").split("/")[0] if "/" in c.replace("\\", "/") else None
                  for c, _ in itens}
        pasta_raiz = raizes.pop() if len(raizes) == 1 else None
        return [(nome, z.read(caminho)) for caminho, nome in itens], pasta_raiz
