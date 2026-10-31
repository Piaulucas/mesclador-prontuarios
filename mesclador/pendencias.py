"""Faturas, tarefas e prazos locais, sem dados de pacientes."""

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, request

GRUPOS = ("vencidas", "vencendo", "no_prazo", "aguardando_terceiros",
          "nf_a_solicitar", "tarefas")
NFS = ("nao_solicitada", "solicitada", "emitida")


def _data(texto):
    if not isinstance(texto, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        raise ValueError("Data inválida; use AAAA-MM-DD.")
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ValueError("Data inválida; use AAAA-MM-DD.") from erro


def _data_opcional(texto):
    return None if texto is None else _data(texto)


def _competencia(texto):
    if not isinstance(texto, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto):
        raise ValueError("Competência inválida; use AAAA-MM.")
    if int(texto[:4]) < 1:
        raise ValueError("Competência inválida; use AAAA-MM.")
    return texto


def _faixa(limite, hoje, alerta_dias):
    restantes = (limite - hoje).days
    situacao = "vencida" if restantes < 0 else "vencendo" if restantes <= alerta_dias else "no_prazo"
    return {"situacao": situacao, "limite": limite.isoformat(), "dias_restantes": restantes}


def avaliar_glosa(fatura, hoje, prazo_dias=60, alerta_dias=10):
    """Classifica a glosa com data de referência injetada."""
    if fatura["resposta_data"]:
        return None
    if not fatura["oficio_data"]:
        ano, mes = map(int, fatura["competencia"].split("-"))
        inicio = date(ano + (mes == 12), mes % 12 + 1, 1)
        return {"situacao": "aguardando_oficio", "dias_de_espera": max(0, (hoje - inicio).days)}
    return _faixa(_data(fatura["oficio_data"]) + timedelta(days=prazo_dias), hoje, alerta_dias)


def avaliar_nf(fatura):
    return {"situacao": "nf_a_solicitar"} if fatura["nf"] == "nao_solicitada" else None


def avaliar_tarefa(tarefa, hoje, alerta_dias=10):
    if tarefa["concluida_em"]:
        return None
    return _faixa(_data(tarefa["prazo"]), hoje, alerta_dias) if tarefa["prazo"] else {"situacao": "sem_prazo"}


def abrir_banco(config):
    """Abre o banco e cria o esquema na primeira abertura."""
    caminho = Path(config.trabalho_arquivo).expanduser()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    banco = sqlite3.connect(caminho)
    banco.row_factory = sqlite3.Row
    banco.execute("PRAGMA foreign_keys = ON")
    versao = banco.execute("PRAGMA user_version").fetchone()[0]
    if versao > 1:
        banco.close()
        raise RuntimeError("Versão do banco de trabalho não suportada.")
    if versao == 0:
        with banco:
            banco.executescript("""
                BEGIN;
                CREATE TABLE IF NOT EXISTS fatura (
                    id INTEGER PRIMARY KEY,
                    empresa TEXT NOT NULL,
                    competencia TEXT NOT NULL,
                    referencia TEXT NOT NULL DEFAULT '',
                    oficio_data TEXT,
                    resposta_data TEXT,
                    nf TEXT NOT NULL DEFAULT 'nao_solicitada'
                        CHECK (nf IN ('nao_solicitada', 'solicitada', 'emitida')),
                    nf_data TEXT,
                    nota TEXT NOT NULL DEFAULT '',
                    criada_em TEXT NOT NULL,
                    UNIQUE (empresa, competencia, referencia)
                );
                CREATE TABLE IF NOT EXISTS tarefa (
                    id INTEGER PRIMARY KEY,
                    empresa TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    prazo TEXT,
                    concluida_em TEXT,
                    criada_em TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                COMMIT;
            """)
    return banco


def _campos(dados, permitidos, obrigatorios=()):
    if not isinstance(dados, dict) or set(dados) - set(permitidos) or not set(obrigatorios) <= set(dados):
        raise ValueError("Campos inválidos ou ausentes.")


def _empresa(valor, config):
    if not isinstance(valor, str) or valor not in config.empresas:
        raise ValueError("Empresa inválida.")
    return valor


def _texto(valor, nome, obrigatorio=False):
    if not isinstance(valor, str) or (obrigatorio and not valor.strip()):
        raise ValueError(f"{nome} inválido.")
    return valor.strip()


def _fatura_validada(dados, config, criacao=False):
    permitidos = ("empresa", "competencia", "referencia") if criacao else (
        "oficio_data", "resposta_data", "nf", "nf_data", "nota")
    _campos(dados, permitidos, ("empresa", "competencia") if criacao else ())
    if not dados and not criacao:
        raise ValueError("Informe ao menos um campo para atualizar.")
    valores = {}
    for chave, valor in dados.items():
        if chave == "empresa":
            valores[chave] = _empresa(valor, config)
        elif chave == "competencia":
            valores[chave] = _competencia(valor)
        elif chave in ("referencia", "nota"):
            valores[chave] = _texto(valor, chave.capitalize())
        elif chave in ("oficio_data", "resposta_data", "nf_data"):
            valores[chave] = _data_opcional(valor).isoformat() if valor is not None else None
        elif chave == "nf":
            if valor not in NFS:
                raise ValueError("Situação da NF inválida.")
            valores[chave] = valor
    return valores


def _tarefa_validada(dados, config, criacao=False):
    _campos(dados, ("empresa", "texto", "prazo") if criacao else
            ("empresa", "texto", "prazo", "concluida", "concluida_em"),
            ("empresa", "texto") if criacao else ())
    if not dados and not criacao:
        raise ValueError("Informe ao menos um campo para atualizar.")
    if "concluida" in dados and "concluida_em" in dados:
        raise ValueError("Informe apenas uma forma de conclusão.")
    valores = {}
    for chave, valor in dados.items():
        if chave == "empresa":
            valores[chave] = _empresa(valor, config)
        elif chave == "texto":
            valores[chave] = _texto(valor, "Texto", obrigatorio=True)
        elif chave == "prazo":
            valores[chave] = _data_opcional(valor).isoformat() if valor is not None else None
        elif chave == "concluida":
            if not isinstance(valor, bool):
                raise ValueError("Conclusão inválida.")
            valores["concluida_em"] = date.today().isoformat() if valor else None
        elif chave == "concluida_em":
            valores[chave] = _data_opcional(valor).isoformat() if valor is not None else None
    return valores


def _gravar(banco, tabela, valores, id_=None):
    colunas = list(valores)
    if id_ is None:
        comando = f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join('?' for _ in colunas)})"
        with banco:
            cursor = banco.execute(comando, [valores[chave] for chave in colunas])
        return cursor.lastrowid
    comando = f"UPDATE {tabela} SET {', '.join(chave + ' = ?' for chave in colunas)} WHERE id = ?"
    with banco:
        cursor = banco.execute(comando, [valores[chave] for chave in colunas] + [id_])
    return id_ if cursor.rowcount else None


def listar(config, hoje):
    resultado = []
    totais = {grupo: 0 for grupo in GRUPOS}
    banco = abrir_banco(config)
    try:
        faturas = [dict(linha) for linha in banco.execute("SELECT * FROM fatura ORDER BY competencia, id")]
        tarefas = [dict(linha) for linha in banco.execute("SELECT * FROM tarefa ORDER BY prazo, id")]
    finally:
        banco.close()
    for nome in config.empresas:
        grupos = {grupo: [] for grupo in GRUPOS}
        for fatura in faturas:
            if fatura["empresa"] != nome:
                continue
            glosa = avaliar_glosa(fatura, hoje, config.prazo_glosa_dias, config.alerta_dias)
            if glosa:
                grupo = "aguardando_terceiros" if glosa["situacao"] == "aguardando_oficio" else (
                    "vencidas" if glosa["situacao"] == "vencida" else glosa["situacao"])
                grupos[grupo].append({**fatura, **glosa})
            nf = avaliar_nf(fatura)
            if nf:
                grupos["nf_a_solicitar"].append({**fatura, **nf})
        for tarefa in tarefas:
            if tarefa["empresa"] == nome:
                avaliacao = avaliar_tarefa(tarefa, hoje, config.alerta_dias)
                if avaliacao:
                    grupos["tarefas"].append({**tarefa, **avaliacao})
        grupos["vencidas"].sort(key=lambda item: (item["limite"], item["id"]))
        grupos["vencendo"].sort(key=lambda item: (item["limite"], item["id"]))
        grupos["aguardando_terceiros"].sort(key=lambda item: (item["competencia"], item["id"]))
        contagens = {grupo: len(grupos[grupo]) for grupo in GRUPOS}
        for grupo in GRUPOS:
            totais[grupo] += contagens[grupo]
        resultado.append({"empresa": nome, "grupos": grupos, "contagens": contagens})
    return {"hoje": hoje.isoformat(), "empresas": resultado, "totais": totais}


def criar_blueprint(config):
    bp = Blueprint("pendencias", __name__, url_prefix="/pendencias")

    @bp.get("/dados")
    def dados():
        return jsonify(listar(config, date.today()))

    def salvar(tabela, id_=None):
        try:
            entrada = request.get_json(silent=True)
            valores = (_fatura_validada(entrada, config, id_ is None) if tabela == "fatura"
                       else _tarefa_validada(entrada, config, id_ is None))
            if id_ is None:
                valores["criada_em"] = datetime.now().isoformat(timespec="seconds")
            banco = abrir_banco(config)
            try:
                numero = _gravar(banco, tabela, valores, id_)
            finally:
                banco.close()
            if numero is None:
                return jsonify(erro="Registro não encontrado."), 404
            return jsonify(ok=True, id=numero)
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400
        except sqlite3.IntegrityError:
            return jsonify(erro="Fatura já cadastrada para esta empresa, competência e referência."), 400

    @bp.post("/fatura")
    def criar_fatura():
        return salvar("fatura")

    @bp.post("/fatura/<int:id_>")
    def atualizar_fatura(id_):
        return salvar("fatura", id_)

    @bp.post("/tarefa")
    def criar_tarefa():
        return salvar("tarefa")

    @bp.post("/tarefa/<int:id_>")
    def atualizar_tarefa(id_):
        return salvar("tarefa", id_)

    return bp
