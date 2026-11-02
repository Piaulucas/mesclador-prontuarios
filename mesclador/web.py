"""Aplicação Flask: a interface local e as rotas que ela usa."""

import io
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image

from . import conversor, horas, imagens, navegador, painel, pendencias, pdfs, planilha, seletor, versao as codigo

IDENTIDADE = "mesclador"   # resposta do /ping, para saber se a porta é deste app


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


def create_app(config, pasta_temp=None, versao=None):
    """Cria o app. `pasta_temp` guarda as cópias de trabalho dos arquivos enviados.
    `versao` é o hash do código (calculado aqui, ao iniciar, se não for informado)."""
    app = Flask(__name__)
    app.config["VERSAO"] = versao or codigo.calcular_versao()
    temp = Path(pasta_temp or tempfile.mkdtemp(prefix="mesclador_"))
    temp.mkdir(parents=True, exist_ok=True)
    arquivos = {}   # id -> {"caminho", "nome", "tipo", "paginas"}  (só em memória)
    salvos = set()  # PDFs gerados nesta sessão (os únicos que /abrir aceita)
    app.config["PASTA_TEMP"] = temp

    def encerrar_processo(url):
        navegador.fechar_aba(url)   # fecha a aba do app (macOS, Chrome/Safari)
        shutil.rmtree(temp, ignore_errors=True)
        os._exit(0)          # encerra o servidor (o app roda em segundo plano, sem Terminal)
    app.config["AO_ENCERRAR"] = encerrar_processo   # os testes trocam por uma função inofensiva

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
        return render_template("inicio.html", pagina="inicio", mes_padrao=painel.mes_padrao(config),
                               mes_minimo=config.mes_inicial)

    @app.get("/mesclar")
    def mesclar():
        return render_template("index.html", pagina="mesclar", empresas=list(config.empresas),
                               tipos=config.tipos, mes_padrao=painel.mes_padrao(config),
                               mes_minimo=config.mes_inicial)

    @app.get("/converter")
    def converter():
        return render_template("converter.html", pagina="converter", dpi=imagens.DPI_EXPORTACAO)

    app.register_blueprint(conversor.criar_blueprint(temp))
    app.register_blueprint(painel.criar_blueprint(config))
    app.register_blueprint(pendencias.criar_blueprint(config))
    app.register_blueprint(horas.criar_blueprint(config))

    # ---------------------------------------------------------- arquivos

    def registrar_um(nome, tipo, salvar_em):
        """Guarda um arquivo (1 página, ou imagem) e gera a miniatura."""
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

    def registrar(nome, salvar_em):
        """Guarda um arquivo enviado. Devolve uma lista de itens: PDF de várias páginas
        vira um item por página ('<arquivo>.pdf · p<n>'), para ajustar/girar/remover/ordenar cada uma."""
        tipo = pdfs.tipo_do_arquivo(nome)
        if not tipo:
            return [{"erro": f"{nome}: formato não suportado"}]
        if tipo != "pdf":
            return [registrar_um(nome, tipo, salvar_em)]
        original = temp / f"{uuid.uuid4().hex[:12]}_orig.pdf"
        salvar_em(original)
        try:
            partes = pdfs.dividir_pdf(original)
            if not partes:
                return [registrar_um(nome, tipo, lambda c: shutil.copyfile(original, c))]
            return [registrar_um(f"{nome} · p{n}", tipo, lambda c, d=dados: c.write_bytes(d))
                    for n, dados in enumerate(partes, start=1)]
        finally:
            original.unlink(missing_ok=True)

    @app.post("/enviar")
    def enviar():
        """Recebe arquivos soltos, arquivos vindos de uma pasta ou um .zip baixado do Drive."""
        resposta = []
        for f in request.files.getlist("arquivos"):
            nome = Path(f.filename).name          # o navegador pode mandar "pasta/arquivo.jpg"
            if nome.lower().endswith(".zip"):
                try:
                    conteudo, pasta_raiz = pdfs.arquivos_do_zip(f.stream)
                except Exception as e:
                    resposta.append({"erro": f"{nome}: zip inválido ({e})"})
                    continue
                if not conteudo:
                    resposta.append({"erro": f"{nome}: nenhum PDF ou imagem dentro do zip"})
                # nome do paciente: do nome do zip ou, se for genérico, da pasta dentro dele
                origem = planilha.nome_da_origem(nome) or planilha.nome_da_origem(pasta_raiz)
                for nome_interno, dados in conteudo:
                    for item in registrar(nome_interno, lambda c, d=dados: c.write_bytes(d)):
                        if origem and "id" in item:
                            item["origem"] = origem
                        resposta.append(item)
            else:
                resposta.extend(registrar(nome, f.save))
        validos = [item for item in resposta if "id" in item]
        for item in validos:
            item["documento"] = pdfs.documento_do_arquivo(item["nome"])
        origem_pasta = request.form.get("origem", "")
        if origem_pasta and not origem_pasta.lower().endswith(".zip") and "," not in origem_pasta:
            origem_pasta = planilha.nome_da_origem(origem_pasta)
            if origem_pasta and len(origem_pasta.split()) < 2:
                origem_pasta = None
        else:
            origem_pasta = None
        if origem_pasta:
            for item in validos:
                item.setdefault("origem", origem_pasta)
        if validos and not any(item.get("origem") for item in validos):
            nomes_atuais = [arquivos[id_]["nome"] for id_ in request.form.getlist("ids_atuais") if id_ in arquivos]
            origem_arquivo = planilha.nome_dos_arquivos(nomes_atuais + [item["nome"] for item in validos])
            if origem_arquivo:
                for item in validos:
                    item["origem_arquivo"] = origem_arquivo
        ordenados = iter(pdfs.ordenar_lote(validos))
        return jsonify([next(ordenados) if "id" in item else item for item in resposta])

    @app.get("/miniatura/<id_>")
    def miniatura(id_):
        if id_ not in arquivos:
            abort(404)
        a = request.args
        try:
            ajustes = {"brilho": int(a.get("brilho", 0) or 0), "contraste": int(a.get("contraste", 0) or 0),
                       "realce": a.get("realce") in ("1", "true")}
            tam = int(a["tam"]) if a.get("tam") else None
        except ValueError:
            abort(400)
        if tam is None and pdfs.ajuste_neutro(ajustes):
            return send_file(temp / f"{id_}_mini.jpg", mimetype="image/jpeg")
        if tam is None:
            img = Image.open(temp / f"{id_}_mini.jpg")
        else:   # prévia maior (ver ampliada): renderiza de novo a 1ª página
            img = pdfs.primeira_pagina(arquivos[id_]["caminho"], arquivos[id_]["tipo"], max(100, min(tam, 2000)))
        img = imagens.ajustar(img, **ajustes)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg", max_age=0)

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

    @app.get("/sugerir")
    def sugerir():
        base = config.empresas.get(request.args.get("empresa", ""))
        caminho = planilha.resolver_caminho(base, request.args.get("planilha", ""))
        nome_origem = planilha.nome_da_origem(request.args.get("origem", ""))
        if not caminho or not nome_origem:
            return jsonify([])
        try:
            remocoes = planilha.ler_planilha(caminho, config.abas)
        except Exception as e:
            return jsonify(erro=f"Não consegui ler a planilha: {e}"), 400
        return jsonify(planilha.buscar_por_nome(remocoes, nome_origem))

    @app.get("/previa")
    def previa():
        a = request.args
        tipo = a.get("tipo", "")
        if not pasta_valida(a.get("pasta", "")) or tipo not in config.tipos:
            arquivo = nome_arquivo(a.get("numero", "") or "?", a.get("nome", "") or "NOME")
            return jsonify(caminho=f"(escolha a pasta)/{tipo}/{arquivo}", aviso="Escolha a pasta principal.",
                           **conferencia(a.get("origem", ""), a.get("nome", "")))
        arquivo = nome_arquivo(a.get("numero", "") or "?", a.get("nome", "") or "NOME")
        pasta = pasta_valida(a.get("pasta", ""))
        destino, existe = montar_destino(pasta, tipo, a.get("numero", "") or "?", a.get("nome", "") or "NOME")
        aviso = "" if existe else f"A subpasta {destino.parent.name} não existe e será criada."
        return jsonify(caminho=f"{pasta.name}/{destino.parent.name}/{arquivo}", aviso=aviso,
                       **conferencia(a.get("origem", ""), a.get("nome", "")))

    def conferencia(origem, nome):
        """Compara o nome do zip/pasta com o nome da planilha.
        confere = True/False, ou None quando não há nome de origem para comparar."""
        nome_origem = planilha.nome_da_origem(origem)
        if not nome_origem or not str(nome).strip():
            return {"confere": None, "nome_origem": nome_origem}
        return {"confere": planilha.nomes_conferem(nome_origem, nome), "nome_origem": nome_origem}

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

        try:
            ajustes = [{"brilho": int(i.get("brilho", 0) or 0), "contraste": int(i.get("contraste", 0) or 0),
                        "realce": i.get("realce") in (True, "1", "true")} for i in itens]
        except (TypeError, ValueError):
            return jsonify(erro="Ajuste de imagem inválido."), 400

        writer = pdfs.mesclar([(arquivos[i["id"]]["caminho"], arquivos[i["id"]]["tipo"], i.get("giro", 0), aj)
                               for i, aj in zip(itens, ajustes)])
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

    @app.get("/ping")
    def ping():
        return IDENTIDADE

    @app.get("/versao")
    def versao_do_codigo():
        # hash do código com que esta instância foi iniciada (o ícone compara com o da pasta)
        return app.config["VERSAO"]

    @app.post("/encerrar")
    def encerrar():
        # Botão "Encerrar": para o contador de horas que ficou ligado. O reinício por
        # versão nova (__main__) não manda o pedido e mantém a contagem.
        if (request.get_json(silent=True) or {}).get("parar_horas") is True:
            horas.parar_sessao_aberta(config, datetime.now())
        # espera um pouco para a resposta chegar ao navegador antes de encerrar
        url = request.host_url.rstrip("/")   # ex.: http://127.0.0.1:5050
        threading.Timer(0.3, app.config["AO_ENCERRAR"], args=[url]).start()
        return jsonify(ok=True)

    return app
