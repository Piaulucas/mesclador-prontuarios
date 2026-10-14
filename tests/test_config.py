from pathlib import Path

from mesclador import config

EXEMPLO = Path(__file__).resolve().parent.parent / "config.example.toml"


def test_config_de_exemplo_e_valido():
    c = config.carregar(EXEMPLO)
    assert c.tipos == ["ADULTO-PED", "NEONATAL"]
    assert c.empresas["EMPRESA EXEMPLO B"] is None
    assert [a.palavra_subpasta for a in c.abas] == ["ADULTO", "NEO"]
    assert c.mes_inicial == "2026-10"
    assert c.abas[0].nomes == ["ADULTO-PED", "Remoção ADULTO-PED"] and c.abas[0].primeira_linha == 16
