from pathlib import Path

from mesclador import config
from mesclador.web import create_app

EXEMPLO = Path(__file__).resolve().parent.parent / "config.example.toml"


def test_config_de_exemplo_e_valido():
    c = config.carregar(EXEMPLO)
    assert c.tipos == ["ADULTO-PED", "NEONATAL", "ADULTO-PED COVID", "NEONATAL COVID"]
    assert c.empresas["EMPRESA EXEMPLO B"] is None
    assert [a.palavra_subpasta for a in c.abas] == [
        "ADULTO", "NEO", "ADULTO_PED_COVID", "NEONATAL_COVID"]
    assert [a.codigo for a in c.abas] == ["ADU", "NEO", "COV", "NCV"]
    assert c.mes_inicial == "2026-10"
    assert c.auditoria_prontuarios["EMPRESA EXEMPLO A"].endswith("/{ano}/{mm}_{MES}")
    assert "EMPRESA EXEMPLO B" not in c.auditoria_prontuarios
    assert c.auditoria_scanners["EMPRESA EXEMPLO A"]["formato"] == "pastas_por_paciente"
    assert c.auditoria_scanners["EMPRESA EXEMPLO B"]["formato"] == "arquivos_soltos"
    assert c.auditoria_scanners["EMPRESA EXEMPLO A"]["pasta"].endswith("SCANNERS/EMPRESA A")
    assert c.pasta_registros == Path("~/Library/Application Support/Mesclador/auditoria").expanduser()
    assert c.abas[0].nomes == ["ADULTO-PED", "Remoção ADULTO-PED"] and c.abas[0].primeira_linha == 16


def test_codigo_padrao_usa_tres_primeiras_letras_maiusculas(tmp_path):
    caminho = tmp_path / "config.toml"
    caminho.write_text('[abas."adulto-ped"]\ncol_numero = "B"\ncol_nome = "D"\n', encoding="utf-8")

    assert config.carregar(caminho).abas[0].codigo == "ADU"
    assert config.carregar(caminho).auditoria_prontuarios == {}
    assert config.carregar(caminho).auditoria_scanners == {}
    assert config.carregar(caminho).pasta_registros == Path(
        "~/Library/Application Support/Mesclador/auditoria").expanduser()


def test_tipos_covid_do_exemplo_aparecem_na_tela(tmp_path):
    app = create_app(config.carregar(EXEMPLO), pasta_temp=tmp_path / "temp", versao="teste")
    pagina = app.test_client().get("/mesclar").get_data(as_text=True)

    assert "<option>ADULTO-PED COVID</option>" in pagina
    assert "<option>NEONATAL COVID</option>" in pagina
