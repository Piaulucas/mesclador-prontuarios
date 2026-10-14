"""Ponto de entrada:  python3 -m mesclador  [caminho/do/config.toml]"""

import shutil
import socket
import sys
import threading
import urllib.request
import webbrowser

from . import config as cfg
from . import navegador
from .web import IDENTIDADE, create_app


def ja_esta_rodando(porta):
    """True se o Mesclador já está aberto nesta porta (ex.: clicou no ícone duas vezes)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/ping", timeout=1) as r:
            return r.read().decode() == IDENTIDADE
    except Exception:
        return False


def mostrar(url):
    """Mostra o app: reaproveita a aba aberta; se não houver, abre uma nova."""
    if not navegador.focar_aba(url):
        webbrowser.open(url)


def porta_ocupada(porta):
    """True se outro programa (que não é o Mesclador) está usando a porta."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main():
    config = cfg.carregar(sys.argv[1] if len(sys.argv) > 1 else None)
    url = f"http://127.0.0.1:{config.porta}"

    # Segunda abertura: em vez de dar erro de porta em uso, só mostra a janela que já existe
    if ja_esta_rodando(config.porta):
        print(f"O Mesclador já está aberto em {url}")
        mostrar(url)
        return
    if porta_ocupada(config.porta):
        raise SystemExit(f"A porta {config.porta} está sendo usada por outro programa. "
                         "Troque 'porta' no config.toml.")

    app = create_app(config)
    threading.Timer(1.0, lambda: mostrar(url)).start()
    print(f"Mesclador aberto em {url}  (feche pelo botão Encerrar ou Ctrl+C)")
    try:
        # 127.0.0.1 = acessível só deste computador
        app.run(host="127.0.0.1", port=config.porta, debug=False)
    finally:
        shutil.rmtree(app.config["PASTA_TEMP"], ignore_errors=True)


if __name__ == "__main__":
    main()
