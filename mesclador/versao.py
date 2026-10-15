"""Versão do código: hash do CONTEÚDO dos arquivos do app.

Serve para saber se a instância aberta em segundo plano roda o mesmo código que está
na pasta agora. Usa o conteúdo (não a data de modificação nem o commit do git), então
trocar de branch e editar sem commitar também contam, e só "tocar" o arquivo não.
"""

import hashlib
from pathlib import Path

PASTA_CODIGO = Path(__file__).resolve().parent


def _arquivos_do_app(raiz):
    """Todos os .py e os arquivos de templates/ (sem ocultos como .DS_Store e sem __pycache__)."""
    achados = []
    for caminho in raiz.rglob("*"):
        relativo = caminho.relative_to(raiz)
        if not caminho.is_file() or "__pycache__" in relativo.parts or caminho.name.startswith("."):
            continue
        if caminho.suffix == ".py" or relativo.parts[0] == "templates":
            achados.append(relativo)
    return sorted(achados)


def calcular_versao(raiz=PASTA_CODIGO):
    """Hash (hexadecimal) do caminho e do conteúdo de cada arquivo do app."""
    h = hashlib.sha256()
    for relativo in _arquivos_do_app(Path(raiz)):
        h.update(relativo.as_posix().encode() + b"\0")
        h.update((Path(raiz) / relativo).read_bytes() + b"\0")
    return h.hexdigest()
