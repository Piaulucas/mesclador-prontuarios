"""Abre o seletor de pastas nativo do macOS (o app roda localmente, então isso é possível)."""

import platform
import subprocess


class SeletorIndisponivel(Exception):
    pass


def escolher_pasta(inicial=None, titulo="Escolha a pasta onde os prontuários serão salvos"):
    """Mostra o diálogo do Finder e devolve o caminho escolhido, ou None se cancelado."""
    if platform.system() != "Darwin":
        raise SeletorIndisponivel("O seletor só funciona no macOS — digite o caminho no campo.")
    local = f' default location (POSIX file "{inicial}")' if inicial else ""
    # "path to frontmost application" faz o diálogo abrir na frente do navegador
    script = (f'tell application (path to frontmost application as text) to '
              f'POSIX path of (choose folder with prompt "{titulo}"{local})')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        if "-128" in r.stderr:      # usuário clicou em Cancelar
            return None
        raise SeletorIndisponivel(r.stderr.strip() or "Não consegui abrir o seletor de pastas.")
    return r.stdout.strip().rstrip("/") or "/"
