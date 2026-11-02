"""Registro manual de horas de trabalho, sem dados de pacientes."""

import sqlite3
from datetime import datetime, time, timedelta

from flask import Blueprint, jsonify, render_template, request

from .pendencias import abrir_banco

TIPOS_INICIAIS = ("Auditoria", "Produtividade")


def _abrir_banco(config):
    """As tabelas do contador são criadas pela migração do banco (pendencias.abrir_banco)."""
    banco = abrir_banco(config)
    with banco:
        banco.executemany("INSERT OR IGNORE INTO tipo_horas (nome) VALUES (?)",
                          ((nome,) for nome in TIPOS_INICIAIS))
    return banco


def _entrada(campos, obrigatorios=()):
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or set(dados) - set(campos) or not set(obrigatorios) <= set(dados):
        raise ValueError("Campos inválidos ou ausentes.")
    return dados


def _texto(valor, nome, obrigatorio=False, limite=200):
    if not isinstance(valor, str) or len(valor.strip()) > limite or (obrigatorio and not valor.strip()):
        raise ValueError(f"{nome} inválido.")
    return valor.strip()


def _segundos_por_dia(inicio, fim):
    """Reparte o intervalo [início, fim) nos dias locais atravessados."""
    dia = inicio.date()
    while dia <= fim.date():
        comeco = max(inicio, datetime.combine(dia, time.min))
        proximo = datetime.combine(dia, time.min) + timedelta(days=1)
        termino = min(fim, proximo)
        if termino > comeco:
            yield dia, (termino - comeco).total_seconds()
        dia += timedelta(days=1)


def calcular_totais(sessoes, agora):
    """Devolve segundos por período e tipo, usando o instante de referência informado."""
    hoje = agora.date()
    semana = hoje - timedelta(days=hoje.weekday())
    mes = hoje.replace(day=1)
    limites = {"dia": hoje, "semana": semana, "mes": mes}
    totais = {periodo: {"geral": 0, "por_tipo": {}} for periodo in limites}
    for sessao in sessoes:
        inicio = datetime.fromisoformat(sessao["inicio"])
        fim = min(datetime.fromisoformat(sessao["fim"]), agora) if sessao["fim"] else agora
        if fim <= inicio:
            continue
        for dia, segundos in _segundos_por_dia(inicio, fim):
            for periodo, primeiro in limites.items():
                if primeiro <= dia <= hoje:
                    nome = sessao["tipo"]
                    totais[periodo]["geral"] += segundos
                    por_tipo = totais[periodo]["por_tipo"]
                    por_tipo[nome] = por_tipo.get(nome, 0) + segundos
    for total in totais.values():
        total["geral"] = int(total["geral"])
        total["por_tipo"] = {nome: int(valor) for nome, valor in total["por_tipo"].items()}
    return totais


def listar(config, agora):
    banco = _abrir_banco(config)
    try:
        tipos = [dict(linha) for linha in banco.execute("SELECT id, nome FROM tipo_horas ORDER BY id")]
        sessoes = [dict(linha) for linha in banco.execute("""
            SELECT sessao.id, tipo_horas.nome AS tipo, sessao.tarefa, sessao.empresa,
                   sessao.inicio, sessao.fim FROM sessao
            JOIN tipo_horas ON tipo_horas.id = sessao.tipo_id
            ORDER BY sessao.inicio DESC, sessao.id DESC
        """)]
    finally:
        banco.close()
    return {"agora": agora.isoformat(timespec="seconds"), "tipos": tipos,
            "ativa": next((sessao for sessao in sessoes if sessao["fim"] is None), None),
            "totais": calcular_totais(sessoes, agora), "sessoes": sessoes[:30]}


def parar_sessao_aberta(config, agora):
    """Encerra a sessão em andamento, se houver. Devolve True quando havia uma."""
    banco = _abrir_banco(config)
    try:
        with banco:
            cursor = banco.execute("UPDATE sessao SET fim = ? WHERE fim IS NULL",
                                   (agora.isoformat(timespec="seconds"),))
        return bool(cursor.rowcount)
    finally:
        banco.close()


def criar_blueprint(config, relogio=datetime.now):
    bp = Blueprint("horas", __name__, url_prefix="/horas")

    @bp.get("/")
    def pagina():
        return render_template("horas.html", pagina="horas", empresas=list(config.empresas))

    @bp.get("/dados")
    def dados():
        return jsonify(listar(config, relogio()))

    @bp.post("/tipo")
    def criar_tipo():
        try:
            nome = _texto(_entrada(("nome",), ("nome",))["nome"], "Tipo", True, 80)
            banco = _abrir_banco(config)
            try:
                with banco:
                    cursor = banco.execute("INSERT INTO tipo_horas (nome) VALUES (?)", (nome,))
                return jsonify(ok=True, id=cursor.lastrowid), 201
            finally:
                banco.close()
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400
        except sqlite3.IntegrityError:
            return jsonify(erro="Tipo já cadastrado."), 400

    @bp.post("/iniciar")
    def iniciar():
        try:
            entrada = _entrada(("tipo", "tarefa", "empresa"), ("tipo",))
            tipo = entrada["tipo"]
            if not isinstance(tipo, int) or isinstance(tipo, bool) or tipo <= 0:
                raise ValueError("Tipo inválido.")
            tarefa = _texto(entrada.get("tarefa", ""), "Tarefa")
            empresa = entrada.get("empresa")
            if empresa in (None, ""):
                empresa = None
            elif not isinstance(empresa, str) or empresa not in config.empresas:
                raise ValueError("Empresa inválida.")
            banco = _abrir_banco(config)
            try:
                agora = relogio().isoformat(timespec="seconds")
                with banco:
                    banco.execute("UPDATE sessao SET fim = ? WHERE fim IS NULL", (agora,))
                    cursor = banco.execute("""INSERT INTO sessao (tipo_id, tarefa, empresa, inicio)
                                           VALUES (?, ?, ?, ?)""", (tipo, tarefa, empresa, agora))
                return jsonify(ok=True, id=cursor.lastrowid), 201
            finally:
                banco.close()
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400
        except sqlite3.IntegrityError:
            return jsonify(erro="Tipo inválido."), 400

    @bp.post("/auditoria")
    def iniciar_auditoria():
        """Clique na empresa da Início: conta "Auditoria" dela, sem reiniciar se já estiver contando."""
        try:
            empresa = _entrada(("empresa",), ("empresa",))["empresa"]
            if not isinstance(empresa, str) or empresa not in config.empresas:
                raise ValueError("Empresa inválida.")
            banco = _abrir_banco(config)
            try:
                with banco:
                    tipo = banco.execute("SELECT id FROM tipo_horas WHERE nome = ?",
                                         ("Auditoria",)).fetchone()["id"]
                    ativa = banco.execute("SELECT tipo_id, empresa FROM sessao WHERE fim IS NULL").fetchone()
                    if ativa and ativa["tipo_id"] == tipo and ativa["empresa"] == empresa:
                        return jsonify(ok=True, iniciada=False)
                    agora = relogio().isoformat(timespec="seconds")
                    banco.execute("UPDATE sessao SET fim = ? WHERE fim IS NULL", (agora,))
                    banco.execute("""INSERT INTO sessao (tipo_id, tarefa, empresa, inicio)
                                  VALUES (?, '', ?, ?)""", (tipo, empresa, agora))
                return jsonify(ok=True, iniciada=True)
            finally:
                banco.close()
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400

    @bp.post("/parar")
    def parar():
        try:
            _entrada(())
            if not parar_sessao_aberta(config, relogio()):
                return jsonify(erro="Não há sessão em andamento."), 400
            return jsonify(ok=True)
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400

    @bp.post("/sessao/<int:id_>/excluir")
    def excluir(id_):
        try:
            _entrada(())
            banco = _abrir_banco(config)
            try:
                with banco:
                    cursor = banco.execute("DELETE FROM sessao WHERE id = ? AND fim IS NOT NULL", (id_,))
                if not cursor.rowcount:
                    return jsonify(erro="Sessão encerrada não encontrada."), 404
                return jsonify(ok=True)
            finally:
                banco.close()
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400

    return bp
