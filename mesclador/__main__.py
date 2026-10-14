"""Ponto de entrada:  python -m mesclador  [caminho/do/config.toml]"""

import shutil
import sys
import threading
import webbrowser

from . import config as cfg
from .web import create_app


def main():
    config = cfg.carregar(sys.argv[1] if len(sys.argv) > 1 else None)
    app = create_app(config)
    url = f"http://127.0.0.1:{config.porta}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Mesclador aberto em {url}  (Ctrl+C para fechar)")
    try:
        # 127.0.0.1 = acessível só deste computador
        app.run(host="127.0.0.1", port=config.porta, debug=False)
    finally:
        shutil.rmtree(app.config["PASTA_TEMP"], ignore_errors=True)


if __name__ == "__main__":
    main()
