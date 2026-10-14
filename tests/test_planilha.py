from mesclador import planilha
from tests.conftest import ABAS


def test_normalizar_remove_acento_e_espacos():
    assert planilha.normalizar("  José   da  Silva ") == "JOSE DA SILVA"


def test_mesmo_numero_ignora_zeros_a_esquerda_e_decimal():
    assert planilha.mesmo_numero("045", 45)
    assert planilha.mesmo_numero(46.0, "46")
    assert not planilha.mesmo_numero("45", "450")


def test_planilha_do_mes_vem_primeiro_mesmo_nao_sendo_a_mais_recente(pasta_planilhas):
    lista = planilha.listar_planilhas(pasta_planilhas, 2026, 10)
    assert lista[0] == {"caminho": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", "do_mes": True}
    assert lista[1]["do_mes"] is False


def test_sem_mes_ordena_pela_mais_recente(pasta_planilhas):
    assert "Setembro" in planilha.listar_planilhas(pasta_planilhas)[0]["caminho"]


def test_ignora_versoes_anteriores(pasta_planilhas):
    caminhos = [p["caminho"] for p in planilha.listar_planilhas(pasta_planilhas, 2026, 10)]
    assert not any("_versoes_anteriores" in c for c in caminhos)
    assert len(caminhos) == 2


def test_mes_sem_planilha_nao_marca_nenhuma(pasta_planilhas):
    assert not any(p["do_mes"] for p in planilha.listar_planilhas(pasta_planilhas, 2026, 11))


def test_buscar_numero_unico(pasta_planilhas):
    remocoes = planilha.ler_planilha(pasta_planilhas / "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", ABAS)
    [r] = planilha.buscar(remocoes, "045")
    assert (r["nome"], r["tipo"], r["linha"], r["aba"]) == ("JOSE DA SILVA", "ADULTO-PED", 16, "Remoção ADULTO-PED")


def test_buscar_numero_repetido_em_duas_abas(pasta_planilhas):
    remocoes = planilha.ler_planilha(pasta_planilhas / "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", ABAS)
    assert {r["tipo"] for r in planilha.buscar(remocoes, 3)} == {"ADULTO-PED", "NEONATAL"}


def test_buscar_filtrando_pelo_tipo(pasta_planilhas):
    remocoes = planilha.ler_planilha(pasta_planilhas / "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", ABAS)
    [r] = planilha.buscar(remocoes, 3, "NEONATAL")
    assert r["nome"] == "RN DE FULANA"


def test_aba_sem_prefixo_tambem_e_lida(pasta_planilhas):
    remocoes = planilha.ler_planilha(pasta_planilhas / "2026/09_Planilha_de_Faturamento_Exemplo_Setembro_26.xlsx", ABAS)
    assert planilha.buscar(remocoes, 10)[0]["aba"] == "ADULTO-PED"


def test_buscar_numero_inexistente(pasta_planilhas):
    remocoes = planilha.ler_planilha(pasta_planilhas / "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", ABAS)
    assert planilha.buscar(remocoes, 999) == []


def test_resolver_caminho_nao_sai_da_pasta(pasta_planilhas):
    assert planilha.resolver_caminho(pasta_planilhas, "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx") is not None
    assert planilha.resolver_caminho(pasta_planilhas, "../../etc/passwd") is None


def test_nome_da_origem():
    assert planilha.nome_da_origem("Maria Souza-20261014T190644Z-001.zip") == "MARIA SOUZA"
    assert planilha.nome_da_origem("JOSÉ DA SILVA-20261014T190644Z-1-001") == "JOSE DA SILVA"
    assert planilha.nome_da_origem("drive-download-20261014T190644Z-1-001.zip") is None
    assert planilha.nome_da_origem("drive-download-20261014T181216Z-1-001") is None
    assert planilha.nome_da_origem("") is None and planilha.nome_da_origem(None) is None


def test_nomes_conferem():
    assert planilha.nomes_conferem("MARIA SOUZA", "Maria Fictícia de Souza")       # abreviado
    assert planilha.nomes_conferem("JOSE DA SILVA", "José Silva")                  # partícula
    assert planilha.nomes_conferem("JOAO PEREIRA SANTOS", "JOAO PERERIA SANTOS")   # digitação
    assert not planilha.nomes_conferem("MARIA SOUZA", "ANA SOUZA")                 # outra pessoa
    assert not planilha.nomes_conferem("SOUZA", "MARIA SOUZA")                     # primeiro nome difere
