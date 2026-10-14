"""Miniaturas e mesclagem de PDFs/imagens."""

import io
import re
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

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


def _imagem_para_pdf(caminho, giro):
    """Converte uma imagem em PDF de 1 página (em memória), aplicando o giro."""
    with abrir_imagem(caminho) as img:
        if giro:
            img = img.rotate(-giro, expand=True)   # PIL gira no sentido anti-horário
        img = img.convert("RGB")
        dpi = (img.info.get("dpi") or (DPI_PADRAO,))[0] or DPI_PADRAO
        buffer = io.BytesIO()
        img.save(buffer, format="PDF", resolution=float(dpi), quality=85)
    buffer.seek(0)
    return PdfReader(buffer)


def mesclar(itens):
    """Junta os arquivos na ordem recebida.
    itens: lista de (caminho, tipo, giro) — giro em graus, sentido horário (0/90/180/270).
    Devolve um PdfWriter pronto para ser gravado."""
    writer = PdfWriter()
    for caminho, tipo, giro in itens:
        giro = int(giro) % 360
        leitor = PdfReader(caminho) if tipo == "pdf" else _imagem_para_pdf(caminho, giro)
        for pagina in leitor.pages:
            if tipo == "pdf" and giro:
                pagina.rotate(giro)
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
    """Lê um .zip e devolve [(nome_do_arquivo, bytes)] só com PDFs/imagens, em ordem natural
    pelo caminho dentro do zip. Ignora lixo do macOS (__MACOSX, ._*, .DS_Store).
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
        return [(nome, z.read(caminho)) for caminho, nome in itens]
