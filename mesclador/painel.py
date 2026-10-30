"""Painel somente leitura da auditoria de prontuários."""

import re
from datetime import date

from flask import Blueprint, jsonify, render_template, request

from . import auditoria, planilha


def criar_blueprint(config):
    bp = Blueprint("painel", __name__, url_prefix="/painel")

    @bp.get("/")
    def inicio():
        hoje = date.today()
        mes_padrao = max(f"{hoje.year}-{hoje.month:02d}", config.mes_inicial or "")
        return render_template("painel.html", pagina="painel", empresas=list(config.empresas),
                               mes_padrao=mes_padrao, mes_minimo=config.mes_inicial)

    @bp.get("/dados")
    def dados():
        texto = request.args.get("mes", "")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto) or texto.startswith("0000-") or (config.mes_inicial and texto < config.mes_inicial):
            return jsonify(erro="Mês inválido ou anterior ao início configurado."), 400
        ano, mes = map(int, texto.split("-"))
        hoje = date.today().isoformat()
        empresas = []
        totais = {chave: 0 for chave in ("lancadas", "por_auditar", "com_equipe", "concluidas", "cor_desconhecida")}
        for nome, base in config.empresas.items():
            avisos = []
            item = {"empresa": nome, "aviso": "", "planilha": None,
                    "contagem": auditoria.contar([]), "pendencias": [], "fichas": [],
                    "inconsistencias": [], "pdfs_sem_linha": []}
            local = auditoria.localizar_prontuarios(config, nome, ano, mes)
            if local["aviso"]:
                avisos.append(local["aviso"])
            try:
                candidatas = planilha.listar_planilhas(base, ano, mes, somente_do_mes=True)
                if candidatas:
                    item["planilha"] = candidatas[0]["caminho"]
                    caminho = planilha.resolver_caminho(base, item["planilha"])
                    fichas = auditoria.ler_fichas(caminho, config.abas)
                    pdfs = {aba.tipo: auditoria.listar_pdfs(local["pasta"], aba) for aba in config.abas}
                    cruzamento = auditoria.cruzar(fichas, pdfs)
                    item["fichas"] = cruzamento["fichas"]
                    item["inconsistencias"] = cruzamento["inconsistencias"]
                    item["pdfs_sem_linha"] = [
                        {"tipo": p["tipo"], "numero": p["numero"], "paciente": p["paciente"],
                         "arquivo": p["caminho"].name} for p in cruzamento["pdfs_sem_linha"]]
                    item["contagem"] = auditoria.contar(item["fichas"])
                    item["pendencias"] = [
                        {**ficha, "devolucao": "devolução não registrada"}
                        for ficha in auditoria.pendencias(item["fichas"])]
                else:
                    avisos.append("Planilha de faturamento do mês não encontrada.")
            except Exception as erro:
                # Uma planilha danificada não impede a leitura das demais empresas.
                avisos.append(f"Não foi possível ler a planilha: {erro}")
                item.update(contagem=auditoria.contar([]), pendencias=[], fichas=[],
                            inconsistencias=[], pdfs_sem_linha=[])
            item["aviso"] = " ".join(avisos)
            for chave in totais:
                totais[chave] += item["contagem"][chave]
            empresas.append(item)
        totais["percentual_concluido"] = (100 * totais["concluidas"] / totais["lancadas"]
                                         if totais["lancadas"] else 0)
        totais["sem_devolucao"] = totais["com_equipe"]
        return jsonify(mes=texto, hoje=hoje, totais=totais, empresas=empresas)

    return bp
