"""Faturas, glosas, NFs e tarefas fictícias, com banco isolado e datas fixas."""

import json
import sqlite3
from datetime import date

import pytest

from mesclador import pendencias

HOJE = date(2026, 11, 2)

# Esquema exato da versão 1 (pendencias.py e horas.py antes da v2), para testar a migração.
ESQUEMA_V1_TESTE = """
    CREATE TABLE fatura (
        id INTEGER PRIMARY KEY, empresa TEXT NOT NULL, competencia TEXT NOT NULL,
        referencia TEXT NOT NULL DEFAULT '', oficio_data TEXT, resposta_data TEXT,
        nf TEXT NOT NULL DEFAULT 'nao_solicitada' CHECK (nf IN ('nao_solicitada', 'solicitada', 'emitida')),
        nf_data TEXT, nota TEXT NOT NULL DEFAULT '', criada_em TEXT NOT NULL,
        UNIQUE (empresa, competencia, referencia));
    CREATE TABLE tarefa (
        id INTEGER PRIMARY KEY, empresa TEXT NOT NULL, texto TEXT NOT NULL, prazo TEXT,
        concluida_em TEXT, criada_em TEXT NOT NULL);
    PRAGMA user_version = 1;
"""
HORAS_V1_TESTE = """
    CREATE TABLE tipo_horas (id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE COLLATE NOCASE);
    CREATE TABLE sessao (id INTEGER PRIMARY KEY, tipo_id INTEGER NOT NULL REFERENCES tipo_horas(id),
        tarefa TEXT NOT NULL DEFAULT '', empresa TEXT, inicio TEXT NOT NULL, fim TEXT);
    CREATE UNIQUE INDEX sessao_unica_aberta ON sessao ((1)) WHERE fim IS NULL;
    INSERT INTO tipo_horas (nome) VALUES ('Auditoria'), ('Produtividade');
    INSERT INTO sessao (tipo_id, tarefa, empresa, inicio, fim)
        VALUES (1, '', 'EMPRESA A', '2026-10-01T09:00:00', '2026-10-01T10:00:00'),
               (2, 'Organizar agenda fictícia', NULL, '2026-10-02T09:00:00', NULL);
"""


def criar_banco_v1(caminho, com_horas=True):
    with sqlite3.connect(caminho) as banco:
        banco.executescript(ESQUEMA_V1_TESTE + (HORAS_V1_TESTE if com_horas else ""))
        banco.executemany("""INSERT INTO fatura (empresa, competencia, referencia, oficio_data,
                             resposta_data, nf, nf_data, nota, criada_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", [
            ("EMPRESA A", "2026-08", "", None, None, "nao_solicitada", None, "", "2026-09-03T10:00:00"),
            ("EMPRESA A", "2026-09", "Lote 1", "2026-10-10", None, "solicitada", "2026-10-12", "Cobrar",
             "2026-10-04T10:00:00"),
            ("EMPRESA B", "2026-09", "", "2026-10-01", "2026-10-20", "emitida", "2026-10-25", "",
             "2026-10-05T11:00:00"),
            ("EMPRESA B", "2026-07", "", None, "2026-09-15", "nao_solicitada", None, "", "2026-08-05T09:00:00"),
        ])
        banco.executemany("INSERT INTO tarefa (empresa, texto, prazo, concluida_em, criada_em) VALUES (?, ?, ?, ?, ?)", [
            ("EMPRESA A", "Conferir documento fictício", "2026-11-10", None, "2026-10-01T08:00:00"),
            ("EMPRESA B", "Tarefa concluída fictícia", None, "2026-10-20", "2026-10-02T08:00:00"),
        ])


def ler(caminho, comando, parametros=()):
    with sqlite3.connect(caminho) as banco:
        banco.row_factory = sqlite3.Row
        return [dict(linha) for linha in banco.execute(comando, parametros)]


# ------------------------------------------------------------------ migração

def test_migracao_v1_para_v2_preserva_tudo_e_faz_copia(config):
    criar_banco_v1(config.trabalho_arquivo)
    pendencias.abrir_banco(config).close()
    caminho = config.trabalho_arquivo
    assert ler(caminho, "PRAGMA user_version")[0]["user_version"] == 2
    # cópia de segurança fiel ao banco v1
    copias = list(caminho.parent.glob("trabalho.db.v1-*.bak"))
    assert len(copias) == 1
    assert ler(copias[0], "PRAGMA user_version")[0]["user_version"] == 1
    assert len(ler(copias[0], "SELECT * FROM fatura")) == 4
    # faturas: nada se perde; as já registradas contam como enviadas
    faturas = ler(caminho, "SELECT * FROM fatura ORDER BY id")
    assert [f["enviada_em"] for f in faturas] == ["2026-09-03", "2026-10-04", "2026-10-05", "2026-08-05"]
    assert faturas[1]["nota"] == "Cobrar" and faturas[1]["oficio_data"] == "2026-10-10"
    assert all(f["valor_apresentado"] is None for f in faturas)
    # glosas: "Respondi a glosa" vira recurso enviado, valor não informado
    glosas = ler(caminho, "SELECT * FROM glosa ORDER BY fatura_id")
    assert [(g["fatura_id"], g["oficio_data"], g["recurso_data"]) for g in glosas] == [
        (2, "2026-10-10", None), (3, "2026-10-01", "2026-10-20"), (4, "2026-09-15", "2026-09-15")]
    assert all(g["valor_glosado"] is None and json.loads(g["historico"]) == [] for g in glosas)
    assert glosas[2]["nota"] == "migrado: ofício sem data"
    # NFs: uma principal por fatura, com a data no campo certo
    nfs = ler(caminho, "SELECT * FROM nota_fiscal ORDER BY fatura_id")
    assert [(n["fatura_id"], n["origem"], n["situacao"], n["solicitada_em"], n["emitida_em"]) for n in nfs] == [
        (1, "principal", "nao_solicitada", None, None), (2, "principal", "solicitada", "2026-10-12", None),
        (3, "principal", "emitida", None, "2026-10-25"), (4, "principal", "nao_solicitada", None, None)]
    # tarefas e sessões intactas, com as colunas novas
    tarefas = ler(caminho, "SELECT * FROM tarefa ORDER BY id")
    assert [(t["id"], t["empresa"], t["texto"], t["concluida_em"], t["fatura_id"]) for t in tarefas] == [
        (1, "EMPRESA A", "Conferir documento fictício", None, None),
        (2, "EMPRESA B", "Tarefa concluída fictícia", "2026-10-20", None)]
    sessoes = ler(caminho, "SELECT * FROM sessao ORDER BY id")
    assert [(s["tipo_id"], s["empresa"], s["fim"], s["tarefa_id"]) for s in sessoes] == [
        (1, "EMPRESA A", "2026-10-01T10:00:00", None), (2, None, None, None)]
    assert ler(caminho, "PRAGMA foreign_key_check") == []
    assert ler(caminho, "PRAGMA integrity_check")[0]["integrity_check"] == "ok"
    # tarefa agora aceita ficar sem empresa
    with sqlite3.connect(caminho) as banco:
        banco.execute("INSERT INTO tarefa (empresa, texto, criada_em) VALUES (NULL, 'Geral', '2026-11-01')")


def test_migracao_sem_tabela_de_sessoes_cria_com_tarefa_id(config):
    criar_banco_v1(config.trabalho_arquivo, com_horas=False)
    pendencias.abrir_banco(config).close()
    colunas = [c["name"] for c in ler(config.trabalho_arquivo, "PRAGMA table_info(sessao)")]
    assert colunas == ["id", "tipo_id", "tarefa", "empresa", "inicio", "fim", "tarefa_id"]


def test_banco_novo_vai_direto_para_v2_sem_copia(config):
    pendencias.abrir_banco(config).close()
    assert ler(config.trabalho_arquivo, "PRAGMA user_version")[0]["user_version"] == 2
    assert not list(config.trabalho_arquivo.parent.glob("*.bak"))
    tabelas = {t["name"] for t in ler(config.trabalho_arquivo, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"fatura", "glosa", "nota_fiscal", "tarefa", "sessao", "tipo_horas"} <= tabelas


def test_banco_v2_nao_migra_de_novo(config):
    criar_banco_v1(config.trabalho_arquivo)
    pendencias.abrir_banco(config).close()
    pendencias.abrir_banco(config).close()
    assert len(list(config.trabalho_arquivo.parent.glob("*.bak"))) == 1
    assert len(ler(config.trabalho_arquivo, "SELECT * FROM glosa")) == 3


def test_versao_mais_nova_do_banco_da_erro_claro(config):
    with sqlite3.connect(config.trabalho_arquivo) as banco:
        banco.execute("PRAGMA user_version = 3")
    with pytest.raises(RuntimeError, match="não suportada"):
        pendencias.abrir_banco(config)


def test_migracao_com_erro_nao_altera_nada(config):
    criar_banco_v1(config.trabalho_arquivo)
    with sqlite3.connect(config.trabalho_arquivo) as banco:   # tabela que impede a criação da nova
        banco.execute("CREATE TABLE glosa (x INTEGER)")
    with pytest.raises(RuntimeError, match="nada foi alterado"):
        pendencias.abrir_banco(config)
    caminho = config.trabalho_arquivo
    assert ler(caminho, "PRAGMA user_version")[0]["user_version"] == 1
    assert [c["name"] for c in ler(caminho, "PRAGMA table_info(fatura)")][-1] == "criada_em"
    assert len(ler(caminho, "SELECT * FROM tarefa")) == 2
    assert [c["name"] for c in ler(caminho, "PRAGMA table_info(sessao)")][-1] == "fim"
    assert len(list(caminho.parent.glob("*.bak"))) == 1


def test_migrado_aparece_com_valor_nao_informado(config):
    criar_banco_v1(config.trabalho_arquivo)
    dados = pendencias.listar(config, HOJE)
    faturas = {f["id"]: f for empresa in dados["empresas"] for f in empresa["faturas"] if f["id"]}
    assert faturas[2]["situacao"]["etapa"] == "prazo"
    assert faturas[3]["situacao"]["etapa"] == "aguardando_resposta"
    assert faturas[2]["valores"]["incompleto"] is True
    assert faturas[1]["situacao"]["etapa"] == "aguardando_oficio"
    assert dados["totais"]["incompletas"] == 4


# ------------------------------------------------------------------ regras

def test_prazo_de_envio_e_dia_fixo_do_mes_seguinte():
    assert pendencias.limite_envio("2026-10") == date(2026, 11, 5)
    assert pendencias.limite_envio("2026-12") == date(2027, 1, 5)
    assert pendencias.limite_envio("2026-01", dia=31) == date(2026, 2, 28)
    fatura = {"competencia": "2026-10", "enviada_em": None}
    assert pendencias.avaliar(fatura, None, HOJE) == {
        "etapa": "a_enviar", "faixa": "vencendo", "limite": "2026-11-05", "dias_restantes": 3}
    assert pendencias.avaliar(fatura, None, date(2026, 11, 6))["faixa"] == "vencida"
    assert pendencias.avaliar(fatura, None, date(2026, 10, 20))["faixa"] == "no_prazo"
    assert pendencias.avaliar(fatura, None, HOJE, dia_envio=10)["limite"] == "2026-11-10"


def test_etapas_da_glosa_com_hoje_fixo():
    fatura = {"competencia": "2026-08", "enviada_em": "2026-09-03"}
    assert pendencias.avaliar(fatura, None, HOJE) == {"etapa": "aguardando_oficio", "dias_de_espera": 60}
    glosa = {"oficio_data": "2026-09-03", "valor_glosado": 100000, "recurso_data": None,
             "sem_recurso_data": None, "resposta_data": None}
    assert pendencias.avaliar(fatura, glosa, HOJE) == {
        "etapa": "prazo", "faixa": "vencendo", "limite": "2026-11-02", "dias_restantes": 0}
    assert pendencias.avaliar(fatura, glosa, date(2026, 11, 3))["faixa"] == "vencida"
    assert pendencias.avaliar(fatura, glosa, date(2026, 10, 22))["faixa"] == "no_prazo"
    assert pendencias.avaliar(fatura, glosa, HOJE, prazo_dias=45)["limite"] == "2026-10-18"
    assert pendencias.avaliar(fatura, glosa, date(2026, 10, 25), alerta_dias=5)["faixa"] == "no_prazo"
    assert pendencias.avaliar(fatura, {**glosa, "valor_glosado": 0}, HOJE) == {"etapa": "encerrada", "motivo": "sem_glosa"}
    assert pendencias.avaliar(fatura, {**glosa, "sem_recurso_data": "2026-09-10"}, HOJE)["motivo"] == "sem_recurso"
    recurso = {**glosa, "recurso_data": "2026-10-30"}
    assert pendencias.avaliar(fatura, recurso, HOJE) == {"etapa": "aguardando_resposta", "dias_de_espera": 3}
    assert pendencias.avaliar(fatura, {**recurso, "resposta_data": "2026-11-01"}, HOJE)["motivo"] == "respondida"


def test_contas_da_fatura():
    fatura = {"valor_apresentado": 1000000}
    base = {"valor_glosado": 100000, "valor_recursado": 80000, "valor_acatado": 50000, "historico": []}
    nf_paga = {"valor": 900000, "paga_em": "2026-10-01"}
    contas = pendencias.calcular_valores(fatura, base, [nf_paga], "prazo")
    assert (contas["previsto"], contas["a_receber"], contas["em_disputa"], contas["glosa_mantida"]) == (
        900000, 0, 100000, 0)
    contas = pendencias.calcular_valores(fatura, base, [nf_paga], "aguardando_resposta")
    assert (contas["em_disputa"], contas["glosa_mantida"]) == (80000, 20000)
    contas = pendencias.calcular_valores(fatura, base, [nf_paga], "encerrada")
    assert (contas["previsto"], contas["a_receber"], contas["glosa_mantida"], contas["acatado"]) == (
        950000, 50000, 50000, 50000)
    contas = pendencias.calcular_valores(fatura, None, [], "aguardando_oficio")
    assert (contas["em_analise"], contas["a_receber"]) == (1000000, 0)
    # segundo recurso: o acatado anterior continua contando
    segundo = {**base, "historico": [{"valor_acatado": 30000}], "valor_recursado": 40000, "valor_acatado": None}
    contas = pendencias.calcular_valores(fatura, segundo, [nf_paga], "aguardando_resposta")
    assert (contas["previsto"], contas["em_disputa"], contas["glosa_mantida"], contas["acatado"]) == (
        930000, 40000, 30000, 30000)


def test_tarefa_com_sem_prazo_e_concluida():
    tarefa = {"prazo": None, "concluida_em": None}
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31)) == {"faixa": "sem_prazo"}
    tarefa["prazo"] = "2026-10-30"
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31))["faixa"] == "vencida"
    tarefa["prazo"] = "2026-11-02"
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31))["faixa"] == "vencendo"
    tarefa["concluida_em"] = "2026-10-31"
    assert pendencias.avaliar_tarefa(tarefa, date(2026, 10, 31)) is None


# ------------------------------------------------------------------ rotas

def _fatura(cliente, **campos):
    resposta = cliente.post("/pendencias/fatura", json={"empresa": "EMPRESA A", "competencia": "2026-09", **campos})
    assert resposta.status_code == 200, resposta.get_json()
    return resposta.get_json()["id"]


def _da_fatura(config, numero, hoje=HOJE):
    dados = pendencias.listar(config, hoje)
    return next(f for empresa in dados["empresas"] for f in empresa["faturas"] if f["id"] == numero)


def test_fluxo_completo_da_fatura(config, cliente):
    numero = _fatura(cliente, valor_apresentado=4123800, enviada_em="2026-10-04")
    fatura = _da_fatura(config, numero)
    assert fatura["situacao"]["etapa"] == "aguardando_oficio"
    assert [(n["origem"], n["situacao"], n["pronta"]) for n in fatura["nfs"]] == [("principal", "nao_solicitada", False)]
    # ofício: a NF principal passa a valer apresentado − glosado
    assert cliente.post(f"/pendencias/fatura/{numero}/glosa", json={
        "oficio_data": "2026-10-10", "valor_glosado": 182405, "oficio_numero": "1.204/2026"}).status_code == 200
    fatura = _da_fatura(config, numero)
    glosa = fatura["glosa"]["id"]
    assert fatura["situacao"]["etapa"] == "prazo" and fatura["situacao"]["limite"] == "2026-12-09"
    assert fatura["nfs"][0]["valor"] == 4123800 - 182405 and fatura["nfs"][0]["pronta"] is True
    # um ofício por fatura: registrar de novo só corrige o mesmo
    corrigido = cliente.post(f"/pendencias/fatura/{numero}/glosa", json={"oficio_numero": "1.205/2026"})
    assert corrigido.get_json()["id"] == glosa
    assert cliente.post(f"/pendencias/fatura/{numero}/glosa", json={"oficio_data": "2026-10-03"}).status_code == 400
    # recurso: não passa do glosado nem é anterior ao ofício
    for erro in ({"recurso_data": "2026-10-20", "valor_recursado": 182406},
                 {"recurso_data": "2026-10-09", "valor_recursado": 1000},
                 {"resposta_data": "2026-10-21"}):
        resposta = cliente.post(f"/pendencias/glosa/{glosa}", json=erro)
        assert resposta.status_code == 400 and resposta.get_json()["erro"]
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={
        "recurso_data": "2026-10-20", "valor_recursado": 159000}).status_code == 200
    fatura = _da_fatura(config, numero)
    assert fatura["situacao"]["etapa"] == "aguardando_resposta"
    assert (fatura["valores"]["em_disputa"], fatura["valores"]["glosa_mantida"]) == (159000, 23405)
    # resposta: acatado ≤ recursado; acatado vira a NF do recurso
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={
        "resposta_data": "2026-10-30", "valor_acatado": 159001}).status_code == 400
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={
        "resposta_data": "2026-10-30", "valor_acatado": 113500}).status_code == 200
    fatura = _da_fatura(config, numero)
    assert fatura["situacao"] == {"etapa": "encerrada", "motivo": "respondida"}
    assert [(n["origem"], n["valor"]) for n in fatura["nfs"]] == [("principal", 3941395), ("recurso", 113500)]
    # NF: solicitada → emitida → paga, com datas em ordem
    principal = fatura["nfs"][0]["id"]
    assert cliente.post(f"/pendencias/nf/{principal}", json={"situacao": "solicitada"}).status_code == 400
    assert cliente.post(f"/pendencias/nf/{principal}", json={"paga_em": "2026-10-28"}).status_code == 400
    assert cliente.post(f"/pendencias/nf/{principal}", json={
        "situacao": "solicitada", "solicitada_em": "2026-10-15"}).status_code == 200
    assert cliente.post(f"/pendencias/nf/{principal}", json={
        "situacao": "emitida", "emitida_em": "2026-10-14"}).status_code == 400
    assert cliente.post(f"/pendencias/nf/{principal}", json={
        "situacao": "emitida", "emitida_em": "2026-10-18", "numero": "001187"}).status_code == 200
    assert cliente.post(f"/pendencias/nf/{principal}", json={"paga_em": "2026-10-28"}).status_code == 200
    fatura = _da_fatura(config, numero)
    assert fatura["valores"]["recebido"] == 3941395 and fatura["valores"]["a_receber"] == 113500
    # caso raro: novo recurso guarda o anterior no histórico
    assert cliente.post(f"/pendencias/glosa/{glosa}/novo-recurso", json={
        "recurso_data": "2026-10-29", "valor_recursado": 1000}).status_code == 400   # antes da resposta
    assert cliente.post(f"/pendencias/glosa/{glosa}/novo-recurso", json={
        "recurso_data": "2026-11-01", "valor_recursado": 68906}).status_code == 400  # passa do que sobrou
    assert cliente.post(f"/pendencias/glosa/{glosa}/novo-recurso", json={
        "recurso_data": "2026-11-01", "valor_recursado": 68905}).status_code == 200
    fatura = _da_fatura(config, numero)
    assert fatura["situacao"]["etapa"] == "aguardando_resposta"
    assert fatura["glosa"]["historico"] == [{"recurso_data": "2026-10-20", "valor_recursado": 159000,
                                            "resposta_data": "2026-10-30", "valor_acatado": 113500}]
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={
        "resposta_data": "2026-11-02", "valor_acatado": 20000}).status_code == 200
    fatura = _da_fatura(config, numero)
    assert [(n["origem"], n["rodada"], n["valor"]) for n in fatura["nfs"]] == [
        ("principal", None, 3941395), ("recurso", 1, 113500), ("recurso", 2, 20000)]
    assert fatura["valores"]["acatado"] == 133500 and fatura["valores"]["glosa_mantida"] == 182405 - 133500


def test_nao_vou_recorrer_e_oficio_sem_glosa(config, cliente):
    numero = _fatura(cliente, valor_apresentado=100000, enviada_em="2026-10-04")
    cliente.post(f"/pendencias/fatura/{numero}/glosa", json={"oficio_data": "2026-10-10", "valor_glosado": 5000})
    glosa = _da_fatura(config, numero)["glosa"]["id"]
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={"sem_recurso_data": "2026-10-12"}).status_code == 200
    fatura = _da_fatura(config, numero)
    assert fatura["situacao"]["motivo"] == "sem_recurso" and fatura["valores"]["glosa_mantida"] == 5000
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={
        "recurso_data": "2026-10-12", "valor_recursado": 10}).status_code == 400
    assert cliente.post(f"/pendencias/glosa/{glosa}", json={"sem_recurso_data": None}).status_code == 200
    assert _da_fatura(config, numero)["situacao"]["etapa"] == "prazo"
    assert cliente.post(f"/pendencias/fatura/{numero}/glosa", json={"valor_glosado": 0}).status_code == 200
    assert _da_fatura(config, numero)["situacao"]["motivo"] == "sem_glosa"
    assert cliente.post(f"/pendencias/fatura/{numero}/glosa", json={"valor_glosado": 100001}).status_code == 400
    assert cliente.post(f"/pendencias/glosa/{glosa}/excluir", json={}).status_code == 200
    assert _da_fatura(config, numero)["glosa"] is None


def test_fatura_a_enviar_e_competencias_esperadas(config, cliente):
    config.mes_inicial = "2026-09"
    dados = pendencias.listar(config, HOJE)
    a, b = dados["empresas"]
    assert [(f["competencia"], f["virtual"], f["situacao"]["faixa"]) for f in a["faturas"]] == [
        ("2026-09", True, "vencida"), ("2026-10", True, "vencendo")]
    assert dados["totais"]["a_enviar"] == 4 and dados["totais"]["a_enviar_vencidas"] == 2
    # registrar sem data de envio continua a enviar; com a data, sai da lista
    numero = _fatura(cliente, competencia="2026-10")
    assert _da_fatura(config, numero)["situacao"]["etapa"] == "a_enviar"
    assert cliente.post(f"/pendencias/fatura/{numero}/glosa", json={
        "oficio_data": "2026-11-01", "valor_glosado": 0}).status_code == 400
    assert cliente.post(f"/pendencias/fatura/{numero}", json={"enviada_em": "2026-11-02"}).status_code == 200
    dados = pendencias.listar(config, HOJE)
    assert [f["competencia"] for f in dados["empresas"][0]["faturas"] if f["situacao"]["etapa"] == "a_enviar"] == ["2026-09"]
    assert dados["totais"]["a_enviar"] == 3 and dados["totais"]["aguardando_oficio"] == 1
    # dia configurado
    config.dia_envio_fatura = 10
    assert pendencias.listar(config, HOJE)["empresas"][1]["faturas"][1]["situacao"]["limite"] == "2026-11-10"


def test_totais_para_a_inicio(config, cliente):
    primeira = _fatura(cliente, competencia="2026-08", valor_apresentado=200000, enviada_em="2026-09-03")
    cliente.post(f"/pendencias/fatura/{primeira}/glosa", json={"oficio_data": "2026-09-03", "valor_glosado": 10000})
    segunda = _fatura(cliente, competencia="2026-09", valor_apresentado=300000, enviada_em="2026-10-03")
    cliente.post(f"/pendencias/fatura/{segunda}/glosa", json={"oficio_data": "2026-10-03", "valor_glosado": 0})
    totais = pendencias.listar(config, HOJE)["totais"]
    assert totais["glosas_vencendo"] == 1 and totais["glosas_vencidas"] == 0
    assert totais["nf_a_solicitar"] == 2 and totais["encerradas"] == 1
    assert totais["a_receber"] == 190000 + 300000 and totais["em_disputa"] == 10000
    assert pendencias.listar(config, date(2026, 11, 3))["totais"]["glosas_vencidas"] == 1


def test_api_valida_campos_sem_gravar(config, cliente):
    base = {"empresa": "EMPRESA A", "competencia": "2026-09"}
    invalidas = [
        {**base, "empresa": "DESCONHECIDA"}, {**base, "empresa": ["EMPRESA A"]},
        {**base, "competencia": "2026-13"}, {**base, "competencia": "0000-01"},
        {**base, "referencia": 1}, {**base, "paciente": "Pessoa Fictícia"},
        {**base, "valor_apresentado": -1}, {**base, "valor_apresentado": 10.5},
        {**base, "valor_apresentado": True}, {**base, "enviada_em": "02/11/2026"},
        {**base, "oficio_data": "2026-10-01"},   # campo da v1 não é mais aceito
    ]
    for entrada in invalidas:
        resposta = cliente.post("/pendencias/fatura", json=entrada)
        assert resposta.status_code == 400 and resposta.get_json()["erro"], entrada
    assert cliente.post("/pendencias/fatura", json=base).status_code == 200
    assert cliente.post("/pendencias/fatura", json=base).status_code == 400   # mesma competência e referência
    for entrada in ({"nf": "emitida"}, {"empresa": "EMPRESA B"}, {"nota": 10}, {}, []):
        assert cliente.post("/pendencias/fatura/1", json=entrada).status_code == 400
    assert cliente.post("/pendencias/fatura/999", json={"nota": "Teste"}).status_code == 404
    assert cliente.post("/pendencias/fatura/999/glosa", json={"oficio_data": "2026-10-01", "valor_glosado": 1}).status_code == 404
    assert cliente.post("/pendencias/glosa/999", json={"nota": "x"}).status_code == 404
    assert cliente.post("/pendencias/nf/999", json={"numero": "1"}).status_code == 404
    with sqlite3.connect(config.trabalho_arquivo) as banco:
        assert banco.execute("SELECT count(*) FROM fatura").fetchone()[0] == 1
        assert banco.execute("SELECT count(*) FROM glosa").fetchone()[0] == 0


def test_tarefas_com_e_sem_empresa(config, cliente):
    for corpo in ({"empresa": "EMPRESA A", "texto": "Conferir fatura fictícia", "prazo": "2026-11-04"},
                  {"texto": "Organizar a semana"}, {"empresa": None, "texto": "Geral", "prazo": None}):
        assert cliente.post("/pendencias/tarefa", json=corpo).status_code == 200
    for corpo in ({"empresa": "EMPRESA A", "texto": ""}, {"texto": "x", "prazo": "2026-13-01"},
                  {"empresa": "DESCONHECIDA", "texto": "x"}, {"texto": "x", "fatura_id": 99},
                  {"texto": "x", "fatura_id": "1"}):
        assert cliente.post("/pendencias/tarefa", json=corpo).status_code == 400
    dados = pendencias.listar_tarefas(config, date(2026, 11, 2))
    assert [(t["empresa"], t["faixa"]) for t in dados["tarefas"]] == [
        ("EMPRESA A", "vencendo"), (None, "sem_prazo"), (None, "sem_prazo")]
    assert cliente.post("/pendencias/tarefa/1", json={"concluida": True}).status_code == 200
    for corpo in ({"concluida": "sim"}, {"concluida_em": "2026-02-30"}, {"texto": " "},
                  {"concluida": True, "concluida_em": None}):
        assert cliente.post("/pendencias/tarefa/2", json=corpo).status_code == 400
    assert cliente.post("/pendencias/tarefa/999", json={"texto": "Conferir"}).status_code == 404
    assert len(cliente.get("/pendencias/tarefas").get_json()["tarefas"]) == 2
    assert pendencias.listar(config, HOJE)["totais"]["tarefas"] == 2


# ------------------------------------------------------------------ telas

def test_pagina_pendencias_resumo_empresas_e_quadros(cliente):
    resposta = cliente.get("/pendencias/")
    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert "<title>Pendências · Área de trabalho</title>" in html
    assert 'href="/pendencias/" class="ativa" aria-current="page"' in html
    # ordem pedida: resumo em R$, por empresa (colapsável), quadros
    assert html.index('id="pendResumo"') < html.index('id="pendEmpresas"') < html.index('id="pendQuadro"')
    for coluna in ("Aguardando ofício", "Prazo do recurso", "Aguardando resposta", "Encerradas"):
        assert coluna in html
    assert html.index("Aguardando ofício") < html.index("Prazo do recurso") < html.index("Aguardando resposta")
    for coluna in ("A solicitar", "Solicitada", "Emitida · a receber", "Paga"):
        assert coluna in html
    for texto in ("Registrar fatura", "Chegou o ofício de glosa", "Recurso enviado", "Não vou recorrer",
                  "Chegou a resposta", "Novo recurso", "Registrar pagamento", "valor não informado",
                  "Fatura a enviar"):
        assert texto in html
    # formulários sob demanda, estado lembrado e nada de "Nova tarefa" aqui
    assert "<dialog" in html and "showModal()" in html
    assert "pendenciasAberta:" in html and "pendenciasQuadro" in html
    pagina = html.split('<main class="pend">')[1].split("{% endblock %}")[0]
    assert "Nova tarefa" not in pagina.split("</main>")[0] and 'id="formTarefa"' not in html
    assert "https://" not in html
    assert '"/pendencias/dados"' in html
    # tudo pela competência: nada de recorte pela data em que o dinheiro entrou
    assert "últimos 60 dias" not in html and "Recebido no mês" not in html


def test_inicio_mostra_contadores_novos(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'id="inicioPendencias"' in html
    assert 'fetch("/pendencias/dados")' in html
    for trecho in ("totais.a_enviar", "totais.glosas_vencidas", "totais.glosas_vencendo",
                   "totais.aguardando_resposta", "totais.nf_a_solicitar", "totais.a_receber",
                   "Faturas a enviar", "Recursos aguardando resposta", "A receber"):
        assert trecho in html
    assert '"/pendencias/"' in html


def test_postit_le_tarefas_da_rota_propria(cliente):
    for rota in ("/", "/painel/", "/mesclar", "/pendencias/"):
        html = cliente.get(rota).get_data(as_text=True)
        assert 'id="postitBotao"' in html and 'src="/static/postit.js"' in html
    codigo = cliente.get("/static/postit.js").get_data(as_text=True)
    assert 'fetch("/pendencias/tarefas")' in codigo and '"Sem empresa"' in codigo
    assert "campos.empresa.value || null" in codigo
