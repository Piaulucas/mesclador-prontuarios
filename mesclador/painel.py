"""Painel da auditoria e registros manuais de devolução."""

import re
from datetime import date

from flask import Blueprint, jsonify, render_template, request

from . import auditoria, planilha


def mes_padrao(config, hoje=None):
    """Mês que as telas abrem: o atual, ou o anterior enquanto o atual ainda não tem planilha
    em nenhuma empresa (virada do mês, com o anterior ainda em andamento)."""
    hoje = hoje or date.today()
    atual = (hoje.year, hoje.month)
    anterior = (hoje.year - (hoje.month == 1), 12 if hoje.month == 1 else hoje.month - 1)

    def tem_planilha(ano_mes):
        for base in config.empresas.values():
            try:
                if planilha.listar_planilhas(base, *ano_mes, somente_do_mes=True):
                    return True
            except OSError:
                continue
        return False

    texto = lambda ano_mes: f"{ano_mes[0]}-{ano_mes[1]:02d}"
    if (not tem_planilha(atual) and tem_planilha(anterior)
            and texto(anterior) >= (config.mes_inicial or "")):
        return texto(anterior)
    return max(texto(atual), config.mes_inicial or "")


def criar_blueprint(config):
    bp = Blueprint("painel", __name__, url_prefix="/painel")

    def mes_valido(texto):
        return (isinstance(texto, str) and bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto))
                and not texto.startswith("0000-")
                and (not config.mes_inicial or texto >= config.mes_inicial))

    def data_valida(texto):
        if not isinstance(texto, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
            return False
        try:
            date.fromisoformat(texto)
            return True
        except ValueError:
            return False

    @bp.get("/")
    def inicio():
        return render_template("painel.html", pagina="painel", empresas=list(config.empresas),
                               mes_padrao=mes_padrao(config), mes_minimo=config.mes_inicial)

    @bp.get("/dados")
    def dados():
        texto = request.args.get("mes", "")
        if not mes_valido(texto):
            return jsonify(erro="Mês inválido ou anterior ao início configurado."), 400
        ano, mes = map(int, texto.split("-"))
        hoje = date.today().isoformat()
        empresas = []
        totais = {chave: 0 for chave in ("lancadas", "por_auditar", "com_equipe", "concluidas", "cor_desconhecida")}
        totais["falta_escanear"] = 0
        for nome, base in config.empresas.items():
            avisos = []
            item = {"empresa": nome, "aviso": "", "planilha": None,
                    "contagem": auditoria.contar([]), "pendencias": [], "fichas": [],
                    "inconsistencias": [], "pdfs_sem_linha": [], "escaneados_sem_linha": []}
            local = auditoria.localizar_prontuarios(config, nome, ano, mes)
            if local["aviso"]:
                avisos.append(local["aviso"])
            scanners = auditoria.localizar_scanners(config, nome, ano, mes)
            if scanners["aviso"]:
                avisos.append(scanners["aviso"])
            nomes_scanners, aviso_scanners = auditoria.listar_scanners(scanners, ano, mes)
            if aviso_scanners:
                avisos.append(aviso_scanners)
            try:
                candidatas = planilha.listar_planilhas(base, ano, mes, somente_do_mes=True)
                if candidatas:
                    item["planilha"] = candidatas[0]["caminho"]
                    caminho = planilha.resolver_caminho(base, item["planilha"])
                    fichas = auditoria.ler_fichas(caminho, config.abas)
                    pdfs = {aba.tipo: auditoria.listar_pdfs(local["pasta"], aba) for aba in config.abas}
                    cruzamento = auditoria.cruzar(fichas, pdfs)
                    registros = auditoria.ler_registros(config, nome, texto)
                    item["fichas"], divergencias = auditoria.aplicar_registros(
                        cruzamento["fichas"], registros, date.today())
                    item["fichas"], item["escaneados_sem_linha"] = auditoria.conferir_scanners(
                        item["fichas"], nomes_scanners, scanners["pasta"] is not None and not aviso_scanners)
                    item["inconsistencias"] = cruzamento["inconsistencias"] + divergencias
                    item["pdfs_sem_linha"] = [
                        {"tipo": p["tipo"], "numero": p["numero"], "paciente": p["paciente"],
                         "arquivo": p["caminho"].name} for p in cruzamento["pdfs_sem_linha"]]
                    item["contagem"] = auditoria.contar(item["fichas"])
                    item["contagem"]["falta_escanear"] = sum(
                        ficha.get("scanner") == "falta_escanear" for ficha in item["fichas"])
                    item["pendencias"] = auditoria.pendencias(item["fichas"])
                    item["contagem"]["sem_devolucao"] = sum(
                        "ultimo_envio" not in ficha for ficha in item["pendencias"])
                else:
                    avisos.append("Planilha de faturamento do mês não encontrada.")
            except Exception as erro:
                # Uma planilha danificada não impede a leitura das demais empresas.
                avisos.append(f"Não foi possível ler a planilha: {erro}")
                item.update(contagem=auditoria.contar([]), pendencias=[], fichas=[],
                            inconsistencias=[], pdfs_sem_linha=[], escaneados_sem_linha=[])
            item["aviso"] = " ".join(avisos)
            for chave in totais:
                totais[chave] += item["contagem"].get(chave, 0)
            empresas.append(item)
        totais["percentual_concluido"] = (100 * totais["concluidas"] / totais["lancadas"]
                                         if totais["lancadas"] else 0)
        totais["sem_devolucao"] = sum(
            empresa["contagem"].get("sem_devolucao", 0) for empresa in empresas)
        return jsonify(mes=texto, hoje=hoje, totais=totais, empresas=empresas)

    @bp.post("/registro")
    def registro():
        dados = request.get_json(silent=True)
        if not isinstance(dados, dict):
            return jsonify(erro="Registro inválido."), 400
        mes, empresa, ficha = dados.get("mes"), dados.get("empresa"), dados.get("ficha")
        paciente = dados.get("paciente")
        envio, correcao = dados.get("envio"), dados.get("correcao")
        if (not mes_valido(mes) or not isinstance(empresa, str) or empresa not in config.empresas
                or not isinstance(ficha, str)
                or not ficha or not isinstance(paciente, str) or not paciente.strip()
                or (envio is None) == (correcao is None)):
            return jsonify(erro="Mês, empresa, ficha ou paciente inválido."), 400
        if envio is not None:
            if (not isinstance(envio, dict) or not data_valida(envio.get("data"))
                    or not isinstance(envio.get("pedido", ""), str)):
                return jsonify(erro="Data ou nota inválida."), 400
        elif (not isinstance(correcao, dict) or not data_valida(correcao.get("data"))
              or correcao.get("situacao") not in ("nao_recebida", "parcial", "recebida")):
            return jsonify(erro="Data ou situação inválida."), 400
        ano, numero_mes = map(int, mes.split("-"))
        base = config.empresas[empresa]
        try:
            candidatas = planilha.listar_planilhas(base, ano, numero_mes, somente_do_mes=True)
            if not candidatas:
                return jsonify(erro="Planilha do mês não encontrada."), 400
            caminho = planilha.resolver_caminho(base, candidatas[0]["caminho"])
            linha = next((item for item in auditoria.ler_fichas(caminho, config.abas)
                          if item["ficha"] == ficha and item["estado"] == "com_equipe"), None)
        except Exception:
            return jsonify(erro="Não foi possível ler a planilha do mês."), 400
        if not linha or not planilha.nomes_conferem(paciente, linha["paciente"]):
            return jsonify(erro="Ficha ou paciente não confere com a planilha."), 400
        registros = auditoria.ler_registros(config, empresa, mes)
        atual = registros.setdefault("fichas", {}).get(ficha)
        if atual and not planilha.nomes_conferem(atual.get("paciente", ""), linha["paciente"]):
            return jsonify(erro="Há registro de outro paciente para esta ficha."), 409
        atual = registros["fichas"].setdefault(ficha, {"paciente": planilha.normalizar(linha["paciente"]),
                                                  "envios": []})
        if envio is not None:
            atual["envios"].append({"data": envio["data"], "pedido": envio.get("pedido", "").strip()})
        else:
            atual["correcao"] = {"situacao": correcao["situacao"], "data": correcao["data"]}
        auditoria.salvar_registros(config, empresa, mes, registros)
        return jsonify(ok=True)

    return bp
