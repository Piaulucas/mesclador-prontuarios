"""Tela "Converter em JPG": cada página de PDFs/imagens vira um JPG, com ajuste de legibilidade.

Os JPGs vão para uma pasta nova dentro de Downloads, para serem editados e depois
voltarem ao app pela tela de mesclar.
"""

import io
import platform
import subprocess
import uuid
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, request, send_file
from PIL import Image

from . import imagens, pdfs, planilha

TAM_PREVIA = 1400    # lado maior da imagem guardada para prévia (miniatura e "ver maior")


def _pasta_downloads():
    return Path(current_app.config.get("PASTA_DOWNLOADS") or Path.home() / "Downloads")


def criar_blueprint(temp):
    bp = Blueprint("conversor", __name__, url_prefix="/converter")
    temp = Path(temp)
    paginas = {}   # id -> {"cheia": Path, "previa": Path, "nome": str}

    def guardar_pagina(img, nome):
        id_ = uuid.uuid4().hex[:12]
        cheia, previa = temp / f"conv_{id_}.png", temp / f"conv_{id_}_previa.png"
        img.save(cheia)
        p = img.copy()
        p.thumbnail((TAM_PREVIA, TAM_PREVIA))
        p.save(previa)
        paginas[id_] = {"cheia": cheia, "previa": previa, "nome": nome}
        return {"id": id_, "nome": nome}

    def expandir(nome, abrir):
        """Transforma um arquivo (PDF ou imagem) em páginas. abrir() devolve o caminho no disco."""
        tipo = pdfs.tipo_do_arquivo(nome)
        if tipo == "pdf":
            caminho = abrir()
            try:
                return [guardar_pagina(img, f"{nome} · p{n}") for n, img in imagens.paginas_do_pdf(caminho)]
            finally:
                caminho.unlink(missing_ok=True)
        if tipo == "img":
            caminho = abrir()
            try:
                with pdfs.abrir_imagem(caminho) as img:
                    return [guardar_pagina(img.convert("RGB"), nome)]
            finally:
                caminho.unlink(missing_ok=True)
        return [{"erro": f"{nome}: formato não suportado"}]

    def gravar_temp(sufixo, escrever):
        caminho = temp / f"entrada_{uuid.uuid4().hex[:12]}{sufixo}"
        escrever(caminho)
        return caminho

    @bp.post("/enviar")
    def enviar():
        resposta, sugestao = [], None
        for f in request.files.getlist("arquivos"):
            nome = Path(f.filename).name
            sufixo = Path(nome).suffix.lower()
            try:
                if sufixo == ".zip":
                    conteudo, pasta_raiz = pdfs.arquivos_do_zip(f.stream)
                    if not conteudo:
                        resposta.append({"erro": f"{nome}: nenhum PDF ou imagem dentro do zip"})
                    sugestao = sugestao or planilha.nome_da_origem(nome) or planilha.nome_da_origem(pasta_raiz)
                    for nome_interno, dados in conteudo:
                        resposta += expandir(nome_interno, lambda d=dados, n=nome_interno:
                                             gravar_temp(Path(n).suffix.lower(), lambda c: c.write_bytes(d)))
                else:
                    resposta += expandir(nome, lambda: gravar_temp(sufixo, f.save))
                    sugestao = sugestao or Path(nome).stem
            except Exception as e:
                resposta.append({"erro": f"{nome}: não consegui abrir ({e})"})
        return jsonify(paginas=resposta, sugestao_nome=sugestao or "")

    @bp.get("/previa/<id_>")
    def previa(id_):
        """Prévia com os ajustes. tam = lado maior em pixels (miniatura ou ver maior)."""
        p = paginas.get(id_) or abort(404)
        a = request.args
        tam = min(int(a.get("tam", 400)), TAM_PREVIA)
        with Image.open(p["previa"]) as img:
            img = img.copy()
        img.thumbnail((tam, tam))
        img = imagens.ajustar(img, a.get("brilho", 0), a.get("contraste", 0), a.get("realce") == "1")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg", max_age=0)

    @bp.post("/remover/<id_>")
    def remover(id_):
        p = paginas.pop(id_, None)
        if p:
            p["cheia"].unlink(missing_ok=True)
            p["previa"].unlink(missing_ok=True)
        return jsonify(ok=True)

    @bp.post("/exportar")
    def exportar():
        d = request.get_json(force=True)
        itens = d.get("paginas", [])
        nome = pdfs.limpar_nome_arquivo(str(d.get("nome", "")).strip())
        if not itens:
            return jsonify(erro="Nenhuma página para exportar."), 400
        if not nome:
            return jsonify(erro="Dê um nome para a pasta."), 400
        if any(i.get("id") not in paginas for i in itens):
            return jsonify(erro="Alguma página sumiu da sessão. Arraste de novo."), 400

        downloads = _pasta_downloads()
        if not downloads.is_dir():
            return jsonify(erro=f"Pasta Downloads não encontrada: {downloads}"), 400
        destino = imagens.pasta_livre(downloads, nome)
        destino.mkdir()
        for n, item in enumerate(itens, start=1):
            with Image.open(paginas[item["id"]]["cheia"]) as img:
                saida = imagens.ajustar(img, item.get("brilho", 0), item.get("contraste", 0),
                                        bool(item.get("realce")), item.get("giro", 0))
            saida.save(destino / f"{nome} - {n:02d}.jpg", "JPEG", quality=92,
                       dpi=(imagens.DPI_EXPORTACAO, imagens.DPI_EXPORTACAO))
        current_app.config.setdefault("PASTAS_EXPORTADAS", set()).add(destino.resolve())
        return jsonify(ok=True, pasta=str(destino), nome_pasta=destino.name, quantidade=len(itens))

    @bp.post("/mostrar")
    def mostrar():
        """Abre no Finder uma pasta exportada nesta sessão."""
        pasta = Path(str((request.get_json(silent=True) or {}).get("pasta", ""))).resolve()
        if pasta not in current_app.config.get("PASTAS_EXPORTADAS", set()):
            abort(404)
        if platform.system() != "Darwin":
            return jsonify(erro="Abrir no Finder só funciona no macOS."), 400
        subprocess.run(["open", str(pasta)], check=False)
        return jsonify(ok=True)

    return bp
