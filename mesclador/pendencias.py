"""Faturas, glosas, notas fiscais, tarefas e prazos locais, sem dados de pacientes.

Valores em centavos (inteiros) e datas como texto AAAA-MM-DD. A situação de cada
fatura (a enviar, aguardando ofício, prazo do recurso, aguardando resposta,
encerrada) é sempre calculada, nunca gravada.
"""

import calendar
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

VERSAO_BANCO = 2
NFS = ("nao_solicitada", "solicitada", "emitida")
VALOR_MAXIMO = 10 ** 13   # centavos; muito acima de qualquer fatura real

# Esquema da versão 1 (antes de glosa e NF terem tabela própria).
ESQUEMA_V1 = [
    """CREATE TABLE IF NOT EXISTS fatura (
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
    )""",
    """CREATE TABLE IF NOT EXISTS tarefa (
        id INTEGER PRIMARY KEY,
        empresa TEXT NOT NULL,
        texto TEXT NOT NULL,
        prazo TEXT,
        concluida_em TEXT,
        criada_em TEXT NOT NULL
    )""",
]

# Versão 1 -> 2. As colunas antigas de fatura (oficio_data, resposta_data, nf, nf_data)
# ficam no banco, sem uso, para permitir voltar atrás.
MIGRACAO_V2 = [
    # contador de horas: antes era criado por horas.py, fora do controle de versão
    """CREATE TABLE IF NOT EXISTS tipo_horas (
        id INTEGER PRIMARY KEY,
        nome TEXT NOT NULL UNIQUE COLLATE NOCASE
    )""",
    """CREATE TABLE IF NOT EXISTS sessao (
        id INTEGER PRIMARY KEY,
        tipo_id INTEGER NOT NULL REFERENCES tipo_horas(id),
        tarefa TEXT NOT NULL DEFAULT '',
        empresa TEXT,
        inicio TEXT NOT NULL,
        fim TEXT
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS sessao_unica_aberta ON sessao ((1)) WHERE fim IS NULL",
    # fatura: valor apresentado e data de envio (as já registradas contam como enviadas)
    """ALTER TABLE fatura ADD COLUMN valor_apresentado INTEGER
        CHECK (valor_apresentado IS NULL OR valor_apresentado >= 0)""",
    "ALTER TABLE fatura ADD COLUMN enviada_em TEXT",
    "UPDATE fatura SET enviada_em = substr(criada_em, 1, 10)",
    # um ofício de glosa por fatura; recursos anteriores ficam em historico (JSON)
    """CREATE TABLE glosa (
        id INTEGER PRIMARY KEY,
        fatura_id INTEGER NOT NULL UNIQUE REFERENCES fatura(id) ON DELETE CASCADE,
        oficio_data TEXT NOT NULL,
        oficio_numero TEXT NOT NULL DEFAULT '',
        valor_glosado INTEGER CHECK (valor_glosado IS NULL OR valor_glosado >= 0),
        recurso_data TEXT,
        valor_recursado INTEGER CHECK (valor_recursado IS NULL OR valor_recursado >= 0),
        sem_recurso_data TEXT,
        resposta_data TEXT,
        valor_acatado INTEGER CHECK (valor_acatado IS NULL OR valor_acatado >= 0),
        historico TEXT NOT NULL DEFAULT '[]',
        nota TEXT NOT NULL DEFAULT '',
        criada_em TEXT NOT NULL,
        CHECK (resposta_data IS NULL OR recurso_data IS NOT NULL),
        CHECK (recurso_data IS NULL OR sem_recurso_data IS NULL)
    )""",
    """CREATE TABLE nota_fiscal (
        id INTEGER PRIMARY KEY,
        fatura_id INTEGER NOT NULL REFERENCES fatura(id) ON DELETE CASCADE,
        origem TEXT NOT NULL DEFAULT 'principal' CHECK (origem IN ('principal', 'recurso')),
        rodada INTEGER,
        situacao TEXT NOT NULL DEFAULT 'nao_solicitada'
            CHECK (situacao IN ('nao_solicitada', 'solicitada', 'emitida')),
        solicitada_em TEXT,
        emitida_em TEXT,
        numero TEXT NOT NULL DEFAULT '',
        valor INTEGER CHECK (valor IS NULL OR valor >= 0),
        paga_em TEXT,
        criada_em TEXT NOT NULL,
        CHECK (paga_em IS NULL OR situacao = 'emitida')
    )""",
    "CREATE INDEX nota_fiscal_fatura ON nota_fiscal (fatura_id)",
    # "Respondi a glosa" da v1 era o envio do recurso; o valor glosado fica "não informado"
    """INSERT INTO glosa (fatura_id, oficio_data, recurso_data, nota, criada_em)
        SELECT id, COALESCE(oficio_data, resposta_data), resposta_data,
               CASE WHEN oficio_data IS NULL THEN 'migrado: ofício sem data' ELSE '' END, criada_em
        FROM fatura WHERE oficio_data IS NOT NULL OR resposta_data IS NOT NULL""",
    """INSERT INTO nota_fiscal (fatura_id, origem, situacao, solicitada_em, emitida_em, criada_em)
        SELECT id, 'principal', nf,
               CASE WHEN nf = 'solicitada' THEN nf_data END,
               CASE WHEN nf = 'emitida' THEN nf_data END, criada_em
        FROM fatura""",
    # tarefa: empresa passa a ser opcional (exige reconstruir a tabela) e pode apontar para a fatura
    """CREATE TABLE tarefa_v2 (
        id INTEGER PRIMARY KEY,
        empresa TEXT,
        texto TEXT NOT NULL,
        prazo TEXT,
        concluida_em TEXT,
        criada_em TEXT NOT NULL,
        fatura_id INTEGER REFERENCES fatura(id) ON DELETE SET NULL
    )""",
    """INSERT INTO tarefa_v2 (id, empresa, texto, prazo, concluida_em, criada_em)
        SELECT id, empresa, texto, prazo, concluida_em, criada_em FROM tarefa""",
    "DROP TABLE tarefa",
    "ALTER TABLE tarefa_v2 RENAME TO tarefa",
    # tempo contado em cada tarefa
    "ALTER TABLE sessao ADD COLUMN tarefa_id INTEGER REFERENCES tarefa(id) ON DELETE SET NULL",
]


# ------------------------------------------------------------------ banco

def _conectar(caminho):
    banco = sqlite3.connect(caminho)
    banco.row_factory = sqlite3.Row
    banco.execute("PRAGMA foreign_keys = ON")
    return banco


def copia_de_seguranca(caminho, versao):
    """Copia o banco para trabalho.db.v1-AAAAMMDD-HHMMSS.bak, na mesma pasta."""
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = caminho.with_name(f"{caminho.name}.v{versao}-{carimbo}.bak")
    numero = 1
    while destino.exists():
        destino = caminho.with_name(f"{caminho.name}.v{versao}-{carimbo}-{numero}.bak")
        numero += 1
    origem, copia = sqlite3.connect(caminho), sqlite3.connect(destino)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()
    return destino


def _migrar(caminho, versao):
    """Leva o banco à versão atual numa transação só; se algo falhar, nada muda."""
    if versao == 1:
        try:
            copia_de_seguranca(caminho, versao)
        except (sqlite3.Error, OSError) as erro:
            raise RuntimeError("Não foi possível fazer a cópia de segurança do banco de trabalho; "
                               f"nada foi alterado ({erro}).") from erro
    banco = sqlite3.connect(caminho, isolation_level=None)
    try:
        banco.execute("PRAGMA foreign_keys = ON")
        banco.execute("BEGIN IMMEDIATE")
        try:
            # outra aba pode ter migrado enquanto esperávamos a vez
            atual = banco.execute("PRAGMA user_version").fetchone()[0]
            passos = (ESQUEMA_V1 if atual == 0 else []) + (MIGRACAO_V2 if atual < 2 else [])
            for comando in passos:
                banco.execute(comando)
            if passos:
                if banco.execute("PRAGMA foreign_key_check").fetchall():
                    raise sqlite3.IntegrityError("referências inválidas depois da migração")
                banco.execute(f"PRAGMA user_version = {VERSAO_BANCO}")
            banco.execute("COMMIT")
        except Exception:
            banco.execute("ROLLBACK")
            raise
    except sqlite3.Error as erro:
        raise RuntimeError(f"Não foi possível atualizar o banco de trabalho; nada foi alterado ({erro}).") from erro
    finally:
        banco.close()


def abrir_banco(config):
    """Abre o banco, criando o esquema na primeira abertura ou migrando um banco antigo."""
    caminho = Path(config.trabalho_arquivo).expanduser()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    banco = _conectar(caminho)
    versao = banco.execute("PRAGMA user_version").fetchone()[0]
    if versao > VERSAO_BANCO:
        banco.close()
        raise RuntimeError("Versão do banco de trabalho não suportada.")
    if versao < VERSAO_BANCO:
        banco.close()
        _migrar(caminho, versao)
        banco = _conectar(caminho)
    return banco


# ------------------------------------------------------------------ datas e prazos

def _data(texto):
    if not isinstance(texto, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        raise ValueError("Data inválida; use AAAA-MM-DD.")
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ValueError("Data inválida; use AAAA-MM-DD.") from erro


def _data_opcional(texto):
    return None if texto is None else _data(texto).isoformat()


def _competencia(texto):
    if not isinstance(texto, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto):
        raise ValueError("Competência inválida; use AAAA-MM.")
    if int(texto[:4]) < 1:
        raise ValueError("Competência inválida; use AAAA-MM.")
    return texto


def _mes_seguinte(competencia):
    ano, mes = map(int, competencia.split("-"))
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def limite_envio(competencia, dia=5):
    """Prazo de envio da fatura: dia fixo (5) do mês seguinte à competência."""
    ano, mes = _mes_seguinte(competencia)
    return date(ano, mes, max(1, min(int(dia), calendar.monthrange(ano, mes)[1])))


def _faixa(limite, hoje, alerta_dias):
    restantes = (limite - hoje).days
    faixa = "vencida" if restantes < 0 else "vencendo" if restantes <= alerta_dias else "no_prazo"
    return {"faixa": faixa, "limite": limite.isoformat(), "dias_restantes": restantes}


def avaliar(fatura, glosa, hoje, prazo_dias=60, alerta_dias=10, dia_envio=5):
    """Etapa da fatura, com data de referência injetada."""
    if not fatura.get("enviada_em"):
        return {"etapa": "a_enviar",
                **_faixa(limite_envio(fatura["competencia"], dia_envio), hoje, alerta_dias)}
    if not glosa:
        return {"etapa": "aguardando_oficio",
                "dias_de_espera": max(0, (hoje - _data(fatura["enviada_em"])).days)}
    if glosa["valor_glosado"] == 0:
        return {"etapa": "encerrada", "motivo": "sem_glosa"}
    if glosa["resposta_data"]:
        return {"etapa": "encerrada", "motivo": "respondida"}
    if glosa["sem_recurso_data"]:
        return {"etapa": "encerrada", "motivo": "sem_recurso"}
    if glosa["recurso_data"]:
        return {"etapa": "aguardando_resposta",
                "dias_de_espera": max(0, (hoje - _data(glosa["recurso_data"])).days)}
    return {"etapa": "prazo",
            **_faixa(_data(glosa["oficio_data"]) + timedelta(days=prazo_dias), hoje, alerta_dias)}


def avaliar_tarefa(tarefa, hoje, alerta_dias=10):
    if tarefa["concluida_em"]:
        return None
    return _faixa(_data(tarefa["prazo"]), hoje, alerta_dias) if tarefa["prazo"] else {"faixa": "sem_prazo"}


def _acatado_anterior(glosa):
    return sum(item.get("valor_acatado") or 0 for item in (glosa or {}).get("historico", []))


def calcular_valores(fatura, glosa, nfs, etapa):
    """Contas da fatura (G = glosado, R = recursado, A = acatado), em centavos.

    previsto = apresentado − G + A; a receber = previsto − recebido (NFs pagas).
    Em disputa: G enquanto o prazo corre, R enquanto o recurso espera resposta.
    Glosa mantida: o que não foi recorrido ou não foi acatado.
    """
    apresentado = fatura.get("valor_apresentado")
    recebido = sum(nf["valor"] or 0 for nf in nfs if nf["paga_em"])
    glosado = (glosa or {}).get("valor_glosado") or 0
    recursado = (glosa or {}).get("valor_recursado") or 0
    acatado = _acatado_anterior(glosa)
    em_disputa = mantida = em_analise = 0
    previsto = None
    if etapa == "aguardando_oficio":
        em_analise = apresentado or 0
    elif etapa in ("prazo", "aguardando_resposta", "encerrada"):
        if etapa == "prazo":
            em_disputa = glosado
        elif etapa == "aguardando_resposta":
            em_disputa = recursado
            mantida = max(0, glosado - acatado - recursado)
        else:
            acatado += glosa.get("valor_acatado") or 0
            mantida = max(0, glosado - acatado)
        if apresentado is not None:
            previsto = apresentado - glosado + acatado
    if etapa == "a_enviar":
        a_receber = 0
    elif previsto is not None:
        a_receber = max(0, previsto - recebido)
    else:   # sem valor apresentado: o que as NFs ainda não pagas somam
        a_receber = sum(nf["valor"] or 0 for nf in nfs if not nf["paga_em"]) if glosa else 0
    incompleto = apresentado is None or bool(glosa and (
        glosa.get("valor_glosado") is None
        or (glosa.get("recurso_data") and glosa.get("valor_recursado") is None)
        or (glosa.get("resposta_data") and glosa.get("valor_acatado") is None)))
    return {"apresentado": apresentado, "previsto": previsto, "recebido": recebido,
            "a_receber": a_receber, "em_disputa": em_disputa, "glosa_mantida": mantida,
            "em_analise": em_analise, "acatado": acatado, "incompleto": incompleto}


def competencias_esperadas(config, hoje):
    """Competências cuja fatura já deveria ter sido apresentada: de mes_inicial até o mês passado."""
    ano, mes = (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)
    ultima = f"{ano:04d}-{mes:02d}"
    inicial = config.mes_inicial if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", config.mes_inicial or "") else ultima
    lista, atual = [], inicial
    while atual <= ultima and len(lista) < 240:
        lista.append(atual)
        ano, mes = _mes_seguinte(atual)
        atual = f"{ano:04d}-{mes:02d}"
    return lista


# ------------------------------------------------------------------ validação

def _campos(dados, permitidos, obrigatorios=()):
    if not isinstance(dados, dict) or set(dados) - set(permitidos) or not set(obrigatorios) <= set(dados):
        raise ValueError("Campos inválidos ou ausentes.")
    if not dados:
        raise ValueError("Informe ao menos um campo para atualizar.")


def _empresa(valor, config, opcional=False):
    if opcional and valor in (None, ""):
        return None
    if not isinstance(valor, str) or valor not in config.empresas:
        raise ValueError("Empresa inválida.")
    return valor


def _texto(valor, nome, obrigatorio=False, limite=500):
    if not isinstance(valor, str) or len(valor.strip()) > limite or (obrigatorio and not valor.strip()):
        raise ValueError(f"{nome} inválido.")
    return valor.strip()


def _centavos(valor, nome, opcional=True):
    if valor is None and opcional:
        return None
    if not isinstance(valor, int) or isinstance(valor, bool) or not 0 <= valor <= VALOR_MAXIMO:
        raise ValueError(f"{nome} inválido; informe o valor em centavos.")
    return valor


def _reais(centavos):
    texto = f"{centavos / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def _fatura_validada(dados, config, criacao=False):
    permitidos = ("empresa", "competencia", "referencia", "valor_apresentado", "enviada_em", "nota")
    _campos(dados, permitidos if criacao else permitidos[2:], ("empresa", "competencia") if criacao else ())
    valores = {}
    for chave, valor in dados.items():
        if chave == "empresa":
            valores[chave] = _empresa(valor, config)
        elif chave == "competencia":
            valores[chave] = _competencia(valor)
        elif chave in ("referencia", "nota"):
            valores[chave] = _texto(valor, chave.capitalize())
        elif chave == "valor_apresentado":
            valores[chave] = _centavos(valor, "Valor apresentado")
        elif chave == "enviada_em":
            valores[chave] = _data_opcional(valor)
    return valores


CAMPOS_GLOSA = ("oficio_data", "oficio_numero", "valor_glosado", "recurso_data", "valor_recursado",
                "sem_recurso_data", "resposta_data", "valor_acatado", "nota")


def _glosa_validada(dados, permitidos=CAMPOS_GLOSA, obrigatorios=()):
    _campos(dados, permitidos, obrigatorios)
    valores = {}
    for chave, valor in dados.items():
        if chave in ("oficio_numero", "nota"):
            valores[chave] = _texto(valor, "Nº do ofício" if chave == "oficio_numero" else "Nota")
        elif chave.startswith("valor_"):
            nomes = {"valor_glosado": "Valor glosado", "valor_recursado": "Valor recursado",
                     "valor_acatado": "Valor acatado"}
            valores[chave] = _centavos(valor, nomes[chave])
        elif chave == "oficio_data":
            valores[chave] = _data(valor).isoformat()
        else:
            valores[chave] = _data_opcional(valor)
    return valores


def _conferir_glosa(glosa, fatura):
    """Regras do fluxo: ofício → recurso (≤ glosado) ou "não vou recorrer" → resposta (≤ recursado)."""
    if glosa["valor_recursado"] is not None and not glosa["recurso_data"]:
        raise ValueError("Informe a data de envio do recurso.")
    if glosa["valor_acatado"] is not None and not glosa["resposta_data"]:
        raise ValueError("Informe a data da resposta do recurso.")
    if glosa["resposta_data"] and not glosa["recurso_data"]:
        raise ValueError("Registre o recurso antes da resposta.")
    if glosa["recurso_data"] and glosa["sem_recurso_data"]:
        raise ValueError("A glosa não pode ter recurso e “Não vou recorrer” ao mesmo tempo.")
    if glosa["valor_glosado"] == 0 and (glosa["recurso_data"] or glosa["sem_recurso_data"]):
        raise ValueError("Ofício sem glosa não tem recurso.")
    apresentado = fatura["valor_apresentado"]
    if glosa["valor_glosado"] is not None and apresentado is not None and glosa["valor_glosado"] > apresentado:
        raise ValueError(f"O valor glosado passa do apresentado ({_reais(apresentado)}).")
    disponivel = None if glosa["valor_glosado"] is None else glosa["valor_glosado"] - _acatado_anterior(glosa)
    if glosa["valor_recursado"] is not None and disponivel is not None and glosa["valor_recursado"] > disponivel:
        raise ValueError(f"O valor recursado não pode passar do glosado ({_reais(disponivel)}).")
    if (glosa["valor_acatado"] is not None and glosa["valor_recursado"] is not None
            and glosa["valor_acatado"] > glosa["valor_recursado"]):
        raise ValueError(f"O valor acatado não pode passar do recursado ({_reais(glosa['valor_recursado'])}).")
    if fatura["enviada_em"] and glosa["oficio_data"] < fatura["enviada_em"]:
        raise ValueError("O ofício não pode ser anterior ao envio da fatura.")
    anterior = glosa["historico"][-1]["resposta_data"] if glosa["historico"] else glosa["oficio_data"]
    for chave, nome in (("recurso_data", "O recurso"), ("sem_recurso_data", "A decisão de não recorrer")):
        if glosa[chave] and glosa[chave] < anterior:
            raise ValueError(f"{nome} não pode ser anterior a {_data(anterior).strftime('%d/%m/%Y')}.")
    if glosa["resposta_data"] and glosa["resposta_data"] < glosa["recurso_data"]:
        raise ValueError("A resposta não pode ser anterior ao envio do recurso.")


CAMPOS_NF = ("situacao", "solicitada_em", "emitida_em", "numero", "valor", "paga_em")


def _nf_validada(dados):
    _campos(dados, CAMPOS_NF)
    valores = {}
    for chave, valor in dados.items():
        if chave == "situacao":
            if valor not in NFS:
                raise ValueError("Situação da NF inválida.")
            valores[chave] = valor
        elif chave == "numero":
            valores[chave] = _texto(valor, "Nº da NF", limite=60)
        elif chave == "valor":
            valores[chave] = _centavos(valor, "Valor da NF")
        else:
            valores[chave] = _data_opcional(valor)
    return valores


def _conferir_nf(nf):
    if nf["situacao"] == "solicitada" and not nf["solicitada_em"]:
        raise ValueError("Informe a data da solicitação.")
    if nf["situacao"] == "emitida" and not nf["emitida_em"]:
        raise ValueError("Informe a data de emissão.")
    if nf["paga_em"] and nf["situacao"] != "emitida":
        raise ValueError("Só uma NF emitida pode estar paga.")
    datas = [nf["solicitada_em"], nf["emitida_em"] if nf["situacao"] == "emitida" else None, nf["paga_em"]]
    datas = [valor for valor in datas if valor]
    if datas != sorted(datas):
        raise ValueError("As datas da NF estão fora de ordem (solicitada, emitida, paga).")


def _tarefa_validada(dados, config, criacao=False):
    permitidos = ("empresa", "texto", "prazo", "fatura_id")
    _campos(dados, permitidos if criacao else permitidos + ("concluida", "concluida_em"),
            ("texto",) if criacao else ())
    if "concluida" in dados and "concluida_em" in dados:
        raise ValueError("Informe apenas uma forma de conclusão.")
    valores = {}
    for chave, valor in dados.items():
        if chave == "empresa":
            valores[chave] = _empresa(valor, config, opcional=True)
        elif chave == "texto":
            valores[chave] = _texto(valor, "Texto", obrigatorio=True)
        elif chave in ("prazo", "concluida_em"):
            valores[chave] = _data_opcional(valor)
        elif chave == "fatura_id":
            if valor is not None and (not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0):
                raise ValueError("Fatura inválida.")
            valores[chave] = valor
        elif chave == "concluida":
            if not isinstance(valor, bool):
                raise ValueError("Conclusão inválida.")
            valores["concluida_em"] = date.today().isoformat() if valor else None
    return valores


# ------------------------------------------------------------------ leitura

def _glosa_dict(linha):
    if linha is None:
        return None
    glosa = dict(linha)
    try:
        glosa["historico"] = json.loads(glosa["historico"] or "[]")
    except ValueError:
        glosa["historico"] = []
    return glosa


def _ler_tudo(banco):
    faturas = [dict(linha) for linha in banco.execute(
        "SELECT * FROM fatura ORDER BY competencia, referencia, id")]
    glosas = {linha["fatura_id"]: _glosa_dict(linha) for linha in banco.execute("SELECT * FROM glosa")}
    nfs = {}
    for linha in banco.execute("SELECT * FROM nota_fiscal ORDER BY origem = 'recurso', rodada, id"):
        nfs.setdefault(linha["fatura_id"], []).append(dict(linha))
    return faturas, glosas, nfs


def _montar_fatura(fatura, glosa, nfs, hoje, config):
    situacao = avaliar(fatura, glosa, hoje, config.prazo_glosa_dias, config.alerta_dias,
                       config.dia_envio_fatura)
    for nf in nfs:
        # a NF principal só pode ser pedida depois do ofício (já com o valor líquido)
        nf["pronta"] = nf["origem"] == "recurso" or glosa is not None
    for chave in ("oficio_data", "resposta_data", "nf", "nf_data"):   # colunas da v1, sem uso
        fatura.pop(chave, None)
    return {**fatura, "virtual": False, "glosa": glosa, "nfs": nfs, "situacao": situacao,
            "valores": calcular_valores(fatura, glosa, nfs, situacao["etapa"])}


def _virtual(empresa, competencia, hoje, config):
    fatura = {"id": None, "empresa": empresa, "competencia": competencia, "referencia": "",
              "valor_apresentado": None, "enviada_em": None, "nota": ""}
    return {**_montar_fatura(fatura, None, [], hoje, config), "virtual": True}


def _contagens_vazias():
    return {"a_enviar": 0, "a_enviar_vencidas": 0, "a_enviar_vencendo": 0,
            "aguardando_oficio": 0, "glosas_vencidas": 0, "glosas_vencendo": 0, "glosas_no_prazo": 0,
            "aguardando_resposta": 0, "encerradas": 0, "nf_a_solicitar": 0, "nf_solicitadas": 0,
            "nf_emitidas_sem_pagamento": 0, "incompletas": 0,
            "apresentado": 0, "a_receber": 0, "recebido": 0, "em_disputa": 0, "glosa_mantida": 0,
            "em_analise": 0, "recuperado": 0}


def _acumular(totais, fatura):
    situacao, valores = fatura["situacao"], fatura["valores"]
    etapa = situacao["etapa"]
    if etapa == "a_enviar":
        totais["a_enviar"] += 1
        if situacao["faixa"] in ("vencida", "vencendo"):
            totais["a_enviar_" + {"vencida": "vencidas", "vencendo": "vencendo"}[situacao["faixa"]]] += 1
    elif etapa == "prazo":
        totais["glosas_" + {"vencida": "vencidas", "vencendo": "vencendo", "no_prazo": "no_prazo"}[situacao["faixa"]]] += 1
    elif etapa in ("aguardando_oficio", "aguardando_resposta"):
        totais[etapa] += 1
    else:
        totais["encerradas"] += 1
    for nf in fatura["nfs"]:
        if nf["situacao"] == "nao_solicitada" and nf["pronta"]:
            totais["nf_a_solicitar"] += 1
        elif nf["situacao"] == "solicitada":
            totais["nf_solicitadas"] += 1
        elif nf["situacao"] == "emitida" and not nf["paga_em"]:
            totais["nf_emitidas_sem_pagamento"] += 1
    if not fatura["virtual"] and valores["incompleto"]:
        totais["incompletas"] += 1
    for chave in ("a_receber", "recebido", "em_disputa", "glosa_mantida", "em_analise"):
        totais[chave] += valores[chave]
    totais["apresentado"] += valores["apresentado"] or 0
    totais["recuperado"] += valores["acatado"]


def listar(config, hoje):
    """Tudo o que a tela de Pendências e a Início precisam, com as contas já feitas."""
    banco = abrir_banco(config)
    try:
        faturas, glosas, nfs = _ler_tudo(banco)
        tarefas_abertas = banco.execute("SELECT count(*) FROM tarefa WHERE concluida_em IS NULL").fetchone()[0]
    finally:
        banco.close()
    esperadas = competencias_esperadas(config, hoje)
    totais = _contagens_vazias()
    resultado, competencias = [], set()
    for nome in config.empresas:
        lista = [_montar_fatura(fatura, glosas.get(fatura["id"]), nfs.get(fatura["id"], []), hoje, config)
                 for fatura in faturas if fatura["empresa"] == nome]
        registradas = {fatura["competencia"] for fatura in lista}
        lista += [_virtual(nome, competencia, hoje, config) for competencia in esperadas
                  if competencia not in registradas]
        lista.sort(key=lambda item: (item["competencia"], item["referencia"], item["id"] or 0))
        contagens = _contagens_vazias()
        for fatura in lista:
            _acumular(contagens, fatura)
            _acumular(totais, fatura)
            competencias.add(fatura["competencia"])
        resultado.append({"empresa": nome, "faturas": lista, "totais": contagens})
    totais["tarefas"] = tarefas_abertas
    return {"hoje": hoje.isoformat(), "empresas": resultado, "totais": totais,
            "competencias": sorted(competencias),
            "prazos": {"glosa_dias": config.prazo_glosa_dias, "alerta_dias": config.alerta_dias,
                       "dia_envio_fatura": config.dia_envio_fatura}}


def listar_tarefas(config, hoje):
    banco = abrir_banco(config)
    try:
        linhas = [dict(linha) for linha in banco.execute(
            "SELECT * FROM tarefa WHERE concluida_em IS NULL ORDER BY prazo IS NULL, prazo, id")]
    finally:
        banco.close()
    tarefas = [{**tarefa, **avaliar_tarefa(tarefa, hoje, config.alerta_dias)} for tarefa in linhas
               if tarefa["empresa"] is None or tarefa["empresa"] in config.empresas]
    return {"hoje": hoje.isoformat(), "empresas": list(config.empresas), "tarefas": tarefas}


# ------------------------------------------------------------------ gravação

def _gravar(banco, tabela, valores, id_=None):
    colunas = list(valores)
    if id_ is None:
        comando = f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join('?' for _ in colunas)})"
        return banco.execute(comando, [valores[chave] for chave in colunas]).lastrowid
    comando = f"UPDATE {tabela} SET {', '.join(chave + ' = ?' for chave in colunas)} WHERE id = ?"
    cursor = banco.execute(comando, [valores[chave] for chave in colunas] + [id_])
    return id_ if cursor.rowcount else None


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _ajustar_nf_principal(banco, fatura, glosa):
    """Com o ofício, a NF principal passa a valer apresentado − glosado (se ainda não foi paga)."""
    if fatura["valor_apresentado"] is None or glosa is None or glosa["valor_glosado"] is None:
        return
    banco.execute("""UPDATE nota_fiscal SET valor = ? WHERE fatura_id = ? AND origem = 'principal'
                     AND paga_em IS NULL""",
                  (max(0, fatura["valor_apresentado"] - glosa["valor_glosado"]), fatura["id"]))


def _ajustar_nf_recurso(banco, glosa):
    """O valor acatado na resposta vira a NF do recurso (uma por rodada de recurso)."""
    rodada = len(glosa["historico"]) + 1
    nf = banco.execute("""SELECT * FROM nota_fiscal WHERE fatura_id = ? AND origem = 'recurso'
                          AND rodada = ?""", (glosa["fatura_id"], rodada)).fetchone()
    acatado = glosa["valor_acatado"] if glosa["resposta_data"] else None
    if acatado:
        if nf is None:
            banco.execute("""INSERT INTO nota_fiscal (fatura_id, origem, rodada, valor, criada_em)
                             VALUES (?, 'recurso', ?, ?, ?)""", (glosa["fatura_id"], rodada, acatado, _agora()))
        elif nf["paga_em"] is None:
            banco.execute("UPDATE nota_fiscal SET valor = ? WHERE id = ?", (acatado, nf["id"]))
    elif nf is not None and nf["situacao"] == "nao_solicitada":
        banco.execute("DELETE FROM nota_fiscal WHERE id = ?", (nf["id"],))


def _salvar_glosa(banco, fatura, glosa_atual, mudancas):
    novo = dict(glosa_atual or {"id": None, "fatura_id": fatura["id"], "oficio_numero": "",
                                "valor_glosado": None, "recurso_data": None, "valor_recursado": None,
                                "sem_recurso_data": None, "resposta_data": None, "valor_acatado": None,
                                "historico": [], "nota": ""})
    novo.update(mudancas)
    _conferir_glosa(novo, fatura)
    colunas = {chave: novo[chave] for chave in CAMPOS_GLOSA}
    colunas["historico"] = json.dumps(novo["historico"], ensure_ascii=False)
    if novo["id"] is None:
        colunas.update(fatura_id=fatura["id"], criada_em=_agora())
        novo["id"] = _gravar(banco, "glosa", colunas)
    else:
        _gravar(banco, "glosa", colunas, novo["id"])
    _ajustar_nf_principal(banco, fatura, novo)
    _ajustar_nf_recurso(banco, novo)
    return novo["id"]


def criar_blueprint(config):
    bp = Blueprint("pendencias", __name__, url_prefix="/pendencias")

    def resposta_de(acao):
        """Executa a gravação numa transação e devolve o JSON padrão das rotas."""
        try:
            banco = abrir_banco(config)
            try:
                with banco:
                    numero = acao(banco)
            finally:
                banco.close()
            if numero is None:
                return jsonify(erro="Registro não encontrado."), 404
            return jsonify(ok=True, id=numero)
        except ValueError as erro:
            return jsonify(erro=str(erro)), 400
        except sqlite3.IntegrityError as erro:
            if "UNIQUE" in str(erro):
                return jsonify(erro="Fatura já cadastrada para esta empresa, competência e referência."), 400
            return jsonify(erro="Registro inconsistente; confira as datas e os valores."), 400
        except RuntimeError as erro:
            return jsonify(erro=str(erro)), 500

    def entrada():
        return request.get_json(silent=True)

    def fatura_de(banco, id_):
        linha = banco.execute("SELECT * FROM fatura WHERE id = ?", (id_,)).fetchone()
        return dict(linha) if linha else None

    def glosa_de(banco, id_):
        return _glosa_dict(banco.execute("SELECT * FROM glosa WHERE id = ?", (id_,)).fetchone())

    @bp.get("/")
    def pagina():
        return render_template("pendencias.html", pagina="pendencias", empresas=list(config.empresas))

    @bp.get("/dados")
    def dados():
        try:
            return jsonify(listar(config, date.today()))
        except RuntimeError as erro:
            return jsonify(erro=str(erro)), 500

    @bp.get("/tarefas")
    def tarefas():
        try:
            return jsonify(listar_tarefas(config, date.today()))
        except RuntimeError as erro:
            return jsonify(erro=str(erro)), 500

    @bp.post("/fatura")
    def criar_fatura():
        def acao(banco):
            valores = _fatura_validada(entrada(), config, criacao=True)
            valores["criada_em"] = _agora()
            numero = _gravar(banco, "fatura", valores)
            banco.execute("""INSERT INTO nota_fiscal (fatura_id, origem, criada_em)
                             VALUES (?, 'principal', ?)""", (numero, valores["criada_em"]))
            return numero
        return resposta_de(acao)

    @bp.post("/fatura/<int:id_>")
    def atualizar_fatura(id_):
        def acao(banco):
            valores = _fatura_validada(entrada(), config)
            fatura = fatura_de(banco, id_)
            if fatura is None:
                return None
            fatura.update(valores)
            glosa = _glosa_dict(banco.execute("SELECT * FROM glosa WHERE fatura_id = ?", (id_,)).fetchone())
            if glosa:
                if not fatura["enviada_em"]:
                    raise ValueError("A fatura já tem ofício de glosa; a data de envio não pode ficar vazia.")
                _conferir_glosa(glosa, fatura)
            _gravar(banco, "fatura", valores, id_)
            _ajustar_nf_principal(banco, fatura, glosa)
            return id_
        return resposta_de(acao)

    @bp.post("/fatura/<int:id_>/glosa")
    def registrar_oficio(id_):
        """Chegou o ofício de glosa (ou corrige os dados dele)."""
        def acao(banco):
            fatura = fatura_de(banco, id_)
            if fatura is None:
                return None
            atual = _glosa_dict(banco.execute("SELECT * FROM glosa WHERE fatura_id = ?", (id_,)).fetchone())
            mudancas = _glosa_validada(entrada(), ("oficio_data", "oficio_numero", "valor_glosado", "nota"),
                                       () if atual else ("oficio_data", "valor_glosado"))
            if not fatura["enviada_em"]:
                raise ValueError("Registre antes o envio da fatura.")
            return _salvar_glosa(banco, fatura, atual, mudancas)
        return resposta_de(acao)

    @bp.post("/glosa/<int:id_>")
    def atualizar_glosa(id_):
        """Recurso, "Não vou recorrer", resposta e nota (campos parciais)."""
        def acao(banco):
            mudancas = _glosa_validada(entrada())
            atual = glosa_de(banco, id_)
            if atual is None:
                return None
            return _salvar_glosa(banco, fatura_de(banco, atual["fatura_id"]), atual, mudancas)
        return resposta_de(acao)

    @bp.post("/glosa/<int:id_>/novo-recurso")
    def novo_recurso(id_):
        """Caso raro: depois da resposta, um novo recurso. O anterior vai para o histórico."""
        def acao(banco):
            mudancas = _glosa_validada(entrada(), ("recurso_data", "valor_recursado"),
                                       ("recurso_data", "valor_recursado"))
            atual = glosa_de(banco, id_)
            if atual is None:
                return None
            if not atual["resposta_data"]:
                raise ValueError("Só dá para fazer um novo recurso depois da resposta do anterior.")
            if not mudancas["recurso_data"]:
                raise ValueError("Informe a data de envio do recurso.")
            anterior = {chave: atual[chave] for chave in
                        ("recurso_data", "valor_recursado", "resposta_data", "valor_acatado")}
            atual["historico"] = atual["historico"] + [anterior]
            mudancas.update(resposta_data=None, valor_acatado=None)
            return _salvar_glosa(banco, fatura_de(banco, atual["fatura_id"]), atual, mudancas)
        return resposta_de(acao)

    @bp.post("/glosa/<int:id_>/excluir")
    def excluir_glosa(id_):
        """Desfaz um ofício registrado por engano."""
        def acao(banco):
            _campos(entrada() or {"confirmar": True}, ("confirmar",))
            atual = glosa_de(banco, id_)
            if atual is None:
                return None
            banco.execute("""DELETE FROM nota_fiscal WHERE fatura_id = ? AND origem = 'recurso'
                             AND situacao = 'nao_solicitada'""", (atual["fatura_id"],))
            banco.execute("DELETE FROM glosa WHERE id = ?", (id_,))
            return id_
        return resposta_de(acao)

    @bp.post("/nf/<int:id_>")
    def atualizar_nf(id_):
        def acao(banco):
            mudancas = _nf_validada(entrada())
            linha = banco.execute("SELECT * FROM nota_fiscal WHERE id = ?", (id_,)).fetchone()
            if linha is None:
                return None
            nf = {**dict(linha), **mudancas}
            if nf["situacao"] != "emitida":      # voltar a situação limpa as datas das etapas seguintes
                nf["emitida_em"] = None
            if nf["situacao"] == "nao_solicitada":
                nf["solicitada_em"] = None
            _conferir_nf(nf)
            return _gravar(banco, "nota_fiscal", {chave: nf[chave] for chave in CAMPOS_NF}, id_)
        return resposta_de(acao)

    def salvar_tarefa(id_=None):
        def acao(banco):
            valores = _tarefa_validada(entrada(), config, criacao=id_ is None)
            if valores.get("fatura_id") and not fatura_de(banco, valores["fatura_id"]):
                raise ValueError("Fatura inválida.")
            if id_ is None:
                valores["criada_em"] = _agora()
            return _gravar(banco, "tarefa", valores, id_)
        return resposta_de(acao)

    @bp.post("/tarefa")
    def criar_tarefa():
        return salvar_tarefa()

    @bp.post("/tarefa/<int:id_>")
    def atualizar_tarefa(id_):
        return salvar_tarefa(id_)

    return bp
