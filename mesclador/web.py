"""Aplicação Flask: a interface local e as rotas que ela usa."""

import tempfile
import uuid
from datetime import date
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from . import pdfs, planilha, seletor


def _ano_mes(texto):
    """'2026-10' -> (2026, 10). Erro de formato vira ValueError."""
    ano, mes = (int(x) for x in str(texto).split("-"))
    if not 1 <= mes <= 12:
        raise ValueError("mês fora do intervalo")
    return ano, mes


def _antes_do_inicio(config, ano, mes):
    """True se o mês é anterior ao mes_inicial configurado."""
    if not config.mes_inicial:
        return False
    return (ano, mes) < _ano_mes(config.mes_inicial)


def create_app(config, pasta_temp=None):
    """Cria o app. `pasta_temp` guarda as cópias de trabalho dos arquivos enviados."""
    app = Flask(__name__)
    temp = Path(pasta_temp or tempfile.mkdtemp(prefix="mesclador_"))
    temp.mkdir(parents=True, exist_ok=True)
    arquivos = {}   # id -> {"caminho", "nome", "tipo", "paginas"}  (só em memória)
    salvos = set()  # PDFs gerados nesta sessão (os únicos que /abrir aceita)
    app.config["PASTA_TEMP"] = temp

    def descartar(id_):
        a = arquivos.pop(id_, None)
        if a:
            a["caminho"].unlink(missing_ok=True)
            (temp / f"{id_}_mini.jpg").unlink(missing_ok=True)

    def nome_arquivo(numero, nome):
        """Nº com pelo menos 2 dígitos para o Finder ordenar certo: '04 - JOSE DA SILVA.pdf'."""
        numero = planilha.numero_para_texto(numero)
        if numero.isdigit():
            numero = numero.lstrip("0").zfill(2)    # '4' e '004' -> '04'; '123' continua '123'
        nome = pdfs.limpar_nome_arquivo(planilha.normalizar(nome))
        return f"{numero} - {nome}.pdf"

    def pasta_valida(texto):
        """Pasta principal escolhida: precisa ser um caminho absoluto que existe."""
        if not texto:
            return None
        pasta = Path(texto).expanduser()
        return pasta if pasta.is_absolute() and pasta.is_dir() else None

    def montar_destino(pasta, tipo, numero, nome):
        """Devolve (caminho_final, subpasta_ja_existe)."""
        aba = config.aba_do_tipo(tipo)
        subpasta, existe = pdfs.achar_subpasta(pasta, aba.palavra_subpasta, tipo)
        return subpasta / nome_arquivo(numero, nome), existe

    # ---------------------------------------------------------- páginas

    @app.get("/")
    def index():
        hoje = date.today()
        mes_padrao = max(f"{hoje.year}-{hoje.month:02d}", config.mes_inicial or "")
        return render_template("index.html", empresas=list(config.empresas), tipos=config.tipos,
                               mes_padrao=mes_padrao, mes_minimo=config.mes_inicial)

    # ---------------------------------------------------------- arquivos

    def registrar(nome, salvar_em):
        """Guarda um arquivo enviado e gera a miniatura. `salvar_em(caminho)` grava o conteúdo."""
        tipo = pdfs.tipo_do_arquivo(nome)
        if not tipo:
            return {"erro": f"{nome}: formato não suportado"}
        id_ = uuid.uuid4().hex[:12]
        caminho = temp / f"{id_}{Path(nome).suffix.lower()}"
        salvar_em(caminho)
        try:
            paginas = pdfs.gerar_miniatura(caminho, tipo, temp / f"{id_}_mini.jpg")
        except Exception as e:
            caminho.unlink(missing_ok=True)
            return {"erro": f"{nome}: não consegui abrir ({e})"}
        arquivos[id_] = {"caminho": caminho, "nome": nome, "tipo": tipo, "paginas": paginas}
        return {"id": id_, "nome": nome, "paginas": paginas}

    @app.post("/enviar")
    def enviar():
        """Recebe arquivos soltos, arquivos vindos de uma pasta ou um .zip baixado do Drive."""
        resposta = []
        for f in request.files.getlist("arquivos"):
            nome = Path(f.filename).name          # o navegador pode mandar "pasta/arquivo.jpg"
            if nome.lower().endswith(".zip"):
                try:
                    conteudo = pdfs.arquivos_do_zip(f.stream)
                except Exception as e:
                    resposta.append({"erro": f"{nome}: zip inválido ({e})"})
                    continue
                if not conteudo:
                    resposta.append({"erro": f"{nome}: nenhum PDF ou imagem dentro do zip"})
                for nome_interno, dados in conteudo:
                    resposta.append(registrar(nome_interno, lambda c, d=dados: c.write_bytes(d)))
            else:
                resposta.append(registrar(nome, f.save))
        return jsonify(resposta)

    @app.get("/miniatura/<id_>")
    def miniatura(id_):
        if id_ not in arquivos:
            abort(404)
        return send_file(temp / f"{id_}_mini.jpg", mimetype="image/jpeg")

    @app.post("/remover/<id_>")
    def remover(id_):
        descartar(id_)
        return jsonify(ok=True)

    # ---------------------------------------------------------- planilha

    @app.get("/planilhas")
    def planilhas():
        base = config.empresas.get(request.args.get("empresa", ""))
        try:
            ano, mes = _ano_mes(request.args.get("mes", ""))
        except ValueError:
            return jsonify([])
        if _antes_do_inicio(config, ano, mes):
            return jsonify([])
        return jsonify(planilha.listar_planilhas(base, ano, mes, somente_do_mes=True))

    @app.get("/buscar")
    def buscar():
        base = config.empresas.get(request.args.get("empresa", ""))
        caminho = planilha.resolver_caminho(base, request.args.get("planilha", ""))
        numero = request.args.get("numero", "")
        if not caminho or not numero.strip():
            return jsonify([])
        try:
            remocoes = planilha.ler_planilha(caminho, config.abas)
        except Exception as e:
            return jsonify(erro=f"Não consegui ler a planilha: {e}"), 400
        return jsonify(planilha.buscar(remocoes, numero, request.args.get("tipo") or None))

    @app.get("/previa")
    def previa():
        a = request.args
        tipo = a.get("tipo", "")
        arquivo = nome_arquivo(a.get("numero", "") or "?", a.get("nome", "") or "NOME")
        pasta = pasta_valida(a.get("pasta", ""))
        if not pasta or tipo not in config.tipos:
            return jsonify(caminho=f"(escolha a pasta)/{tipo}/{arquivo}", aviso="Escolha a pasta principal.")
        destino, existe = montar_destino(pasta, tipo, a.get("numero", "") or "?", a.get("nome", "") or "NOME")
        aviso = "" if existe else f"A subpasta {destino.parent.name} não existe e será criada."
        return jsonify(caminho=f"{pasta.name}/{destino.parent.name}/{arquivo}", aviso=aviso)

    @app.post("/escolher-pasta")
    def escolher_pasta():
        inicial = pasta_valida((request.get_json(silent=True) or {}).get("atual")) or config.pasta_inicial
        try:
            caminho = seletor.escolher_pasta(inicial if inicial and Path(inicial).is_dir() else None)
        except seletor.SeletorIndisponivel as e:
            return jsonify(erro=str(e)), 400
        return jsonify(caminho=caminho)

    # ---------------------------------------------------------- salvar

    @app.post("/salvar")
    def salvar():
        d = request.get_json(force=True)
        itens = d.get("itens", [])
        pasta = pasta_valida(d.get("pasta", ""))
        empresa, tipo = d.get("empresa", ""), d.get("tipo", "")
        numero, nome = str(d.get("numero", "")).strip(), str(d.get("nome", "")).strip()

        if not itens:
            return jsonify(erro="Nenhum arquivo para mesclar."), 400
        if empresa not in config.empresas or tipo not in config.tipos:
            return jsonify(erro="Empresa ou tipo inválido."), 400
        if not numero or not nome:
            return jsonify(erro="Preencha o Nº e o nome."), 400
        if not pasta:
            return jsonify(erro="Escolha a pasta principal (ela precisa existir)."), 400
        if any(i.get("id") not in arquivos for i in itens):
            return jsonify(erro="Algum arquivo sumiu da sessão. Arraste de novo."), 400
        try:
            ano, mes = _ano_mes(d.get("mes", ""))
        except ValueError:
            return jsonify(erro="Mês inválido."), 400
        if _antes_do_inicio(config, ano, mes):
            return jsonify(erro=f"Meses anteriores a {config.mes_inicial} não são usados."), 400

        destino, _ = montar_destino(pasta, tipo, numero, nome)
        if destino.exists() and not d.get("sobrescrever"):
            return jsonify(existe=True, caminho=str(destino)), 409

        writer = pdfs.mesclar([(arquivos[i["id"]]["caminho"], arquivos[i["id"]]["tipo"], i.get("giro", 0))
                               for i in itens])
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "wb") as f:
            writer.write(f)

        for i in itens:
            descartar(i["id"])
        salvos.add(destino.resolve())
        return jsonify(ok=True, caminho=str(destino), paginas=len(writer.pages),
                       relativo=f"{destino.parent.name}/{destino.name}")

    @app.get("/abrir")
    def abrir():
        """Abre um PDF salvo nesta sessão (nenhum outro arquivo do computador)."""
        caminho = Path(request.args.get("caminho", "")).resolve()
        if caminho not in salvos or not caminho.is_file():
            abort(404)
        return send_file(caminho, mimetype="application/pdf")

    return app
