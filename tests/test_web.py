from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser

import pytest

from pypdf import PdfReader

from tests.conftest import criar_planilha, jpeg, pdf


def enviar(cliente, *arquivos, origem="", ids_atuais=()):
    return cliente.post("/enviar", data={"arquivos": list(arquivos), "origem": origem,
                                        "ids_atuais": list(ids_atuais)},
                        content_type="multipart/form-data").get_json()


PASTA = {}   # preenchido pelo fixture autouse abaixo


@pytest.fixture(autouse=True)
def _pasta(pasta_principal):
    PASTA["p"] = str(pasta_principal)


def corpo(ids, **extra):
    base = {"itens": [{"id": i, "giro": 0} for i in ids], "empresa": "EMPRESA A", "pasta": PASTA["p"],
            "mes": "2026-10", "tipo": "ADULTO-PED", "numero": "045", "nome": "José da Silva"}
    base.update(extra)
    return base


def test_enviar_recusa_formato_nao_suportado(cliente):
    resp = enviar(cliente, (jpeg(), "f1.jpg"), (pdf(1), "f2.pdf"), (jpeg(), "nota.docx"))
    assert [r.get("paginas") for r in resp[:2]] == [1, 1]
    assert "formato não suportado" in resp[2]["erro"]


def test_salva_na_subpasta_existente_com_numero_exato(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (pdf(2), "a.pdf"), (jpeg(), "b.jpg"))]
    r = cliente.post("/salvar", json=corpo(ids))
    assert r.status_code == 200
    esperado = pasta_principal / "Adulto e Pediátrico" / "45 - JOSE DA SILVA.pdf"
    assert Path(r.get_json()["caminho"]) == esperado
    assert len(PdfReader(esperado).pages) == 3


def test_cria_subpasta_quando_nao_existe(cliente, pasta_principal):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    r = cliente.post("/salvar", json=corpo([id1], tipo="NEONATAL", numero="4", nome="RN de Fulana"))
    assert Path(r.get_json()["caminho"]) == pasta_principal / "NEONATAL" / "04 - RN DE FULANA.pdf"


def test_pasta_inexistente_da_erro(cliente, tmp_path):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    assert cliente.post("/salvar", json=corpo([id1], pasta=str(tmp_path / "nao-existe"))).status_code == 400


def test_nao_sobrescreve_sem_confirmar(cliente):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    cliente.post("/salvar", json=corpo([id1]))
    id2 = enviar(cliente, (jpeg(), "b.jpg"))[0]["id"]
    assert cliente.post("/salvar", json=corpo([id2])).status_code == 409
    assert cliente.post("/salvar", json=corpo([id2], sobrescrever=True)).status_code == 200


def test_salvar_sem_nome_da_erro(cliente):
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    assert cliente.post("/salvar", json=corpo([id1], nome="")).status_code == 400


def test_planilhas_e_busca(cliente):
    lista = cliente.get("/planilhas?empresa=EMPRESA A&mes=2026-10").get_json()
    assert lista[0]["caminho"] == "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx"
    achados = cliente.get("/buscar", query_string={"empresa": "EMPRESA A",
                                                   "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx", "numero": "3",
                                                   "tipo": "NEONATAL"}).get_json()
    assert [a["nome"] for a in achados] == ["RN DE FULANA"]


def test_sugerir_um_candidato(cliente):
    achados = cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                         "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx",
                         "origem": "MARIA TESTE-20261014T190644Z-001.zip"}).get_json()
    assert [(a["numero"], a["tipo"], a["nome"]) for a in achados] == [("3", "ADULTO-PED", "MARIA TESTE")]


def test_sugerir_varios_candidatos_em_abas_diferentes(cliente, pasta_planilhas):
    criar_planilha(pasta_planilhas / "sugestoes.xlsx",
                   [(4, "Maria Fictícia de Souza")], [(7, "Maria Souza")])
    achados = cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                         "planilha": "sugestoes.xlsx", "origem": "MARIA SOUZA"}).get_json()
    assert [(a["numero"], a["tipo"]) for a in achados] == [("7", "NEONATAL"), ("4", "ADULTO-PED")]


def test_sugerir_zip_generico(cliente):
    assert cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                      "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx",
                      "origem": "drive-download-20261014T190644Z-1-001.zip"}).get_json() == []


def test_sugerir_nome_de_uma_palavra(cliente):
    assert cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                      "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx",
                      "origem": "MARIA-20261014T190644Z-001.zip"}).get_json() == []


def test_sugerir_planilha_invalida_ou_fora_da_pasta(cliente, pasta_planilhas):
    criar_planilha(pasta_planilhas.parent / "fora.xlsx", [(4, "Maria Teste")], [])
    for caminho in ("inexistente.xlsx", "../fora.xlsx"):
        r = cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                        "planilha": caminho, "origem": "MARIA TESTE"})
        assert r.status_code == 200 and r.get_json() == []


def test_sugerir_planilha_ilegivel(cliente, pasta_planilhas):
    (pasta_planilhas / "ilegivel.xlsx").write_text("planilha fictícia inválida")
    r = cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                    "planilha": "ilegivel.xlsx", "origem": "MARIA TESTE"})
    assert r.status_code == 400 and "erro" in r.get_json()


def test_empresa_sem_planilha(cliente):
    assert cliente.get("/planilhas?empresa=EMPRESA B&mes=2026-10").get_json() == []


def test_abrir_so_aceita_pdfs_salvos_na_sessao(cliente):
    assert cliente.get("/abrir?caminho=/etc/passwd").status_code == 404
    id1 = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    caminho = cliente.post("/salvar", json=corpo([id1])).get_json()["caminho"]
    assert cliente.get("/abrir", query_string={"caminho": caminho}).status_code == 200


def test_previa(cliente):
    r = cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "NEONATAL",
                                             "numero": "003", "nome": "rn de fulana"}).get_json()
    assert r["caminho"] == "PRONTUARIOS OUTUBRO/NEONATAL/03 - RN DE FULANA.pdf"
    assert "será criada" in r["aviso"]
    r = cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "ADULTO-PED",
                                             "numero": "12", "nome": "x"}).get_json()
    assert r["caminho"] == "PRONTUARIOS OUTUBRO/Adulto e Pediátrico/12 - X.pdf" and r["aviso"] == ""


def test_seletor_fora_do_mac_avisa(cliente, monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    r = cliente.post("/escolher-pasta", json={})
    assert r.status_code == 400 and "macOS" in r.get_json()["erro"]


def test_pagina_inicial(cliente):
    inicio = cliente.get("/")
    assert inicio.status_code == 200
    html = inicio.get_data(as_text=True)
    assert "<title>Início · Área de trabalho</title>" in html
    assert 'href="/"' in html and 'href="/painel/"' in html
    assert 'href="/mesclar"' in html and 'href="/converter"' in html
    assert "/painel/dados?mes=" in html
    assert "ficha.paciente" not in html and "empresa.fichas" in html
    assert "Área de trabalho" in html
    assert '<h1>Mesclar prontuário</h1>' in cliente.get("/mesclar").get_data(as_text=True)


def test_pagina_inicial_mostra_barra_acessivel_por_empresa(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert '.inicio-barra { display: flex; height: 8px;' in html
    assert '.inicio-aprovadas { background: var(--ok); }' in html
    assert '.inicio-equipe { background: var(--erro); }' in html
    assert '.inicio-pendentes { background: #d9a232; }' in html
    assert 'noInicio("span", Math.round(empresa.contagem.percentual_concluido) + "%")' in html
    assert 'barra.setAttribute("role", "img")' in html
    assert 'barra.setAttribute("aria-label", descricao)' in html
    assert 'barra.title = descricao' in html
    assert '${empresa.contagem.lancadas} no total' in html
    assert 'parte.style.width = (empresa.contagem.lancadas ?' in html
    assert 'linha.append(cabecalho, barra, legenda)' in html
    assert '${empresa.contagem[chave]} ${rotulo}' in html
    assert 'Visão do mês atual' not in html
    assert 'function dataHoraAtual()' in html
    assert 'Andamento do mês' not in html
    assert 'Dados lidos em' not in html
    assert 'cartao.append(noInicio("strong", valor), noInicio("span", rotulo))' in html


@pytest.mark.parametrize("rota", ["/mesclar", "/converter"])
def test_ampliacao_tem_setas_e_indicador_nas_duas_telas(cliente, rota):
    class Elementos(HTMLParser):
        def __init__(self):
            super().__init__()
            self.por_id = {}

        def handle_starttag(self, tag, attrs):
            atributos = dict(attrs)
            if "id" in atributos:
                self.por_id[atributos["id"]] = (tag, atributos)

    pagina = cliente.get(rota).get_data(as_text=True)
    elementos = Elementos()
    elementos.feed(pagina)
    for id_ in ("ampliadaAnterior", "ampliadaProximo"):
        tag, atributos = elementos.por_id[id_]
        assert tag == "button" and atributos["type"] == "button" and atributos["aria-label"]
    assert elementos.por_id["ampliadaPosicao"][0] == "span"
    assert elementos.por_id["ampliada"][0] == "div"
    assert elementos.por_id["imgAmpliada"][0] == "img"


class Ancestrais(HTMLParser):
    """Guarda, para cada id, a tag, os atributos e os ids dos elementos que o contêm."""
    VAZIAS = {"input", "img", "br", "meta", "link", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.pilha, self.por_id = [], {}

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if "id" in atributos:
            self.por_id[atributos["id"]] = (tag, atributos, [i for _, i in self.pilha if i])
        if tag not in self.VAZIAS:
            self.pilha.append((tag, atributos.get("id")))

    def handle_endtag(self, tag):
        while self.pilha:
            if self.pilha.pop()[0] == tag:
                break


def elementos_da_tela(cliente, rota):
    leitor = Ancestrais()
    leitor.feed(cliente.get(rota).get_data(as_text=True))
    return leitor.por_id


@pytest.mark.parametrize("rota", ["/mesclar", "/converter"])
def test_ajustes_ficam_ao_lado_da_folha_ampliada(cliente, rota):
    elementos = elementos_da_tela(cliente, rota)
    for id_ in ("ampBrilho", "ampContraste", "ampRealce", "ampGirar", "ampAplicarTodas", "ampRestaurar",
                "ampliadaFechar", "imgAmpliada", "imgBase"):
        assert "ampliada" in elementos[id_][2], id_
    assert elementos["ampliada"][1].get("role") == "dialog" and "hidden" in elementos["ampliada"][1]
    pagina = cliente.get(rota).get_data(as_text=True)
    assert 'src="/static/ampliada.js"' in pagina and "criarAmpliacao({" in pagina
    assert "Restaurar esta página" in pagina and "Realçar escrita (tons de cinza)" in pagina


def test_mesclar_grade_limpa_e_salvar_sempre_a_vista(cliente):
    elementos = elementos_da_tela(cliente, "/mesclar")
    pagina = cliente.get("/mesclar").get_data(as_text=True)
    # nenhum controle de ajuste fora da folha ampliada
    assert not {"ajustesPagina", "brilho", "contraste", "realce"} & set(elementos)
    # a área de soltar é o primeiro cartão da grade
    assert "grade" in elementos["zona"][2]
    for id_ in ("escolher", "escolherDir", "seletor", "seletorDir"):
        assert "zona" in elementos[id_][2]
    # salvar e o caminho final ficam na barra fixa do rodapé
    for id_ in ("salvar", "previa", "msgSalvar", "faltando"):
        assert "barraSalvar" in elementos[id_][2], id_
    assert "Mesclar e salvar (⌘ Enter)" in pagina and ".barra-fixa { position: fixed;" in pagina
    # a ordem inteira numa linha de fichas
    assert elementos["ordemLista"][0] == "ol" and "function desenharOrdem()" in pagina
    for titulo in ("1 · Faturamento", "2 · Remoção", "3 · Destino"):
        assert titulo in pagina
    for acao in ("ampliar", "girar", "remover"):
        assert f'data-acao="{acao}"' in pagina


def test_folha_ampliada_tem_script_estatico(cliente):
    resposta = cliente.get("/static/ampliada.js")
    assert resposta.status_code == 200
    codigo = resposta.get_data(as_text=True)
    resposta.close()
    for trecho in ("function criarAmpliacao(opcoes)", 'el("ampBrilho")', 'el("ampAplicarTodas")',
                   "opcoes.aoGirar(it)", "opcoes.aoAjustar(it)", 'e.key === "Escape"',
                   'matches("input[type=range]")', "brightness(", "grayscale(1)"):
        assert trecho in codigo, trecho


def test_telas_abrem_com_e_sem_logo_local(cliente):
    pasta_estatica = Path(__file__).resolve().parents[1] / "mesclador" / "static"
    logo = pasta_estatica / "logo-local.svg"
    if logo.exists():
        pytest.skip("Logo local existente não deve ser sobrescrito pelo teste")

    pasta_criada = not pasta_estatica.exists()
    pasta_estatica.mkdir(exist_ok=True)
    try:
        for rota in ("/mesclar", "/converter"):
            assert cliente.get(rota).status_code == 200

        logo.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
        for rota in ("/mesclar", "/converter"):
            assert cliente.get(rota).status_code == 200
    finally:
        logo.unlink(missing_ok=True)
        if pasta_criada:
            pasta_estatica.rmdir()


def test_lista_so_planilhas_do_mes(cliente):
    lista = cliente.get("/planilhas?empresa=EMPRESA A&mes=2026-10").get_json()
    assert [p["caminho"] for p in lista] == ["2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx"]
    assert cliente.get("/planilhas?empresa=EMPRESA A&mes=2026-11").get_json() == []


def test_mes_anterior_ao_inicio_e_bloqueado(config, tmp_path):
    from mesclador.web import create_app
    config.mes_inicial = "2026-10"
    c = create_app(config, pasta_temp=tmp_path / "t2").test_client()
    assert c.get("/planilhas?empresa=EMPRESA A&mes=2026-09").get_json() == []
    id1 = enviar(c, (jpeg(), "a.jpg"))[0]["id"]
    r = c.post("/salvar", json=corpo([id1], mes="2026-09"))
    assert r.status_code == 400
    assert c.post("/salvar", json=corpo([id1], mes="2026-10")).status_code == 200


def test_numero_com_dois_digitos(cliente):
    casos = {"4": "04", "004": "04", "10": "10", "045": "45", "123": "123"}
    for entrada, esperado in casos.items():
        r = cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "ADULTO-PED",
                                                 "numero": entrada, "nome": "x"}).get_json()
        assert r["caminho"].endswith(f"/{esperado} - X.pdf"), (entrada, r)


def zip_do_drive():
    """Imita o .zip do Google Drive: pasta com o nome do paciente, folhas fora de ordem
    alfabética simples e lixo do macOS."""
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("FULANO DE TAL/folha10.jpg", jpeg().getvalue())
        z.writestr("FULANO DE TAL/folha2.jpg", jpeg().getvalue())
        z.writestr("FULANO DE TAL/folha1.pdf", pdf(2).getvalue())
        z.writestr("FULANO DE TAL/.DS_Store", b"x")
        z.writestr("FULANO DE TAL/leia-me.txt", b"x")
        z.writestr("__MACOSX/FULANO DE TAL/._folha2.jpg", b"x")
    b.seek(0)
    return b


def test_enviar_zip_extrai_em_ordem_natural_e_ignora_lixo(cliente):
    resp = enviar(cliente, (zip_do_drive(), "FULANO DE TAL-20261014.zip"))
    assert [r["nome"] for r in resp] == ["folha1.pdf · p1", "folha1.pdf · p2", "folha2.jpg", "folha10.jpg"]
    assert [r["paginas"] for r in resp] == [1, 1, 1, 1]


def test_enviar_zip_sugere_ordem_sesab_e_informa_documentos(cliente):
    import io, zipfile
    lote = io.BytesIO()
    with zipfile.ZipFile(lote, "w") as z:
        for nome in ("FDR.jpg", "BDV.pdf", "Formulario.jpg", "0/scan_9.jpg"):
            z.writestr(nome, pdf(2).getvalue() if nome.endswith(".pdf") else jpeg().getvalue())
    lote.seek(0)
    resp = enviar(cliente, (lote, "ficticio.zip"))
    assert [(r["nome"], r["documento"]) for r in resp] == [
        ("Formulario.jpg", "formulario"), ("BDV.pdf · p1", "bdv"),
        ("BDV.pdf · p2", "bdv"), ("FDR.jpg", "fdr"), ("scan_9.jpg", None)]


def test_enviar_so_ordena_o_lote_recebido(cliente):
    primeiro = enviar(cliente, (jpeg(), "FDR.jpg"), (jpeg(), "Formulario.jpg"))
    ordem_manual = [primeiro[1]["id"], primeiro[0]["id"]]
    segundo = enviar(cliente, (jpeg(), "BDV.jpg"), (jpeg(), "scan_2.jpg"))
    assert [r["nome"] for r in segundo] == ["BDV.jpg", "scan_2.jpg"]
    assert [r["id"] for r in primeiro] == [ordem_manual[1], ordem_manual[0]]
    assert ordem_manual + [r["id"] for r in segundo] == [
        primeiro[1]["id"], primeiro[0]["id"], segundo[0]["id"], segundo[1]["id"]]


def test_zip_mesclado_e_salvo(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (zip_do_drive(), "p.zip"))]
    r = cliente.post("/salvar", json=corpo(ids, numero="7"))
    assert len(PdfReader(r.get_json()["caminho"]).pages) == 4


def test_zip_sem_arquivos_validos_avisa(cliente):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("nota.txt", b"x")
    b.seek(0)
    [r] = enviar(cliente, (b, "vazio.zip"))
    assert "nenhum PDF ou imagem" in r["erro"]


def test_zip_corrompido_avisa(cliente):
    import io
    [r] = enviar(cliente, (io.BytesIO(b"isto nao e um zip"), "ruim.zip"))
    assert "zip inválido" in r["erro"]


def test_arquivo_vindo_de_pasta_usa_so_o_nome(cliente):
    [r] = enviar(cliente, (jpeg(), "FULANO/folha1.jpg"))
    assert r["nome"] == "folha1.jpg"


def zip_com(nomes):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n in nomes:
            z.writestr(n, jpeg().getvalue())
    b.seek(0)
    return b


def test_zip_com_nome_do_paciente_informa_origem(cliente):
    resp = enviar(cliente, (zip_com(["MARIA SOUZA/a.jpg"]), "MARIA SOUZA-20261014T190644Z-001.zip"))
    assert resp[0]["origem"] == "MARIA SOUZA"


def test_drive_download_usa_pasta_interna(cliente):
    resp = enviar(cliente, (zip_com(["JOSE SILVA/a.jpg", "JOSE SILVA/b.jpg"]), "drive-download-20261014T1-001.zip"))
    assert resp[0]["origem"] == "JOSE SILVA"


def test_drive_download_sem_pasta_nao_confere(cliente):
    resp = enviar(cliente, (zip_com(["a.jpg", "b.jpg"]), "drive-download-20261014T190644Z-1-001.zip"))
    assert all("origem" not in r for r in resp)


def test_arquivos_soltos_informam_nome_consensual_para_sugestao(cliente):
    resp = enviar(cliente, (jpeg(), "Maria Teste (FDR).jpg"),
                  (jpeg(), "Maria Teste (BDV).jpg"),
                  (jpeg(), "Maria Teste (FORMULARIO).jpg"))
    assert all(r["origem_arquivo"] == "MARIA TESTE" for r in resp)
    achados = cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                           "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx",
                           "origem": resp[0]["origem_arquivo"]}).get_json()
    assert [(r["numero"], r["nome"]) for r in achados] == [("3", "MARIA TESTE")]


def test_zip_e_pasta_genericos_usam_nome_dos_arquivos(cliente):
    nomes = ["Maria Teste (FORMULARIO).jpg", "Maria Teste [BDV].jpg"]
    zip_resp = enviar(cliente, (zip_com(nomes), "drive-download-20261014T190644Z-1-001.zip"))
    pasta_resp = enviar(cliente, *((jpeg(), nome) for nome in nomes), origem="drive-download-20261014T190644Z-1-001")
    assert all(r["origem_arquivo"] == "MARIA TESTE" and "origem" not in r for r in zip_resp + pasta_resp)


def test_nome_do_zip_ou_pasta_tem_prioridade(cliente):
    nomes = ["Ana Souza (FORMULARIO).jpg", "Ana Souza (BDV).jpg"]
    zip_resp = enviar(cliente, (zip_com(nomes), "MARIA TESTE-20261014T190644Z-001.zip"))
    pasta_resp = enviar(cliente, *((jpeg(), nome) for nome in nomes), origem="MARIA TESTE")
    assert all(r["origem"] == "MARIA TESTE" and "origem_arquivo" not in r for r in zip_resp + pasta_resp)


def test_nomes_misturados_ou_genericos_nao_sugerem_origem(cliente):
    misto = enviar(cliente, (jpeg(), "Maria Teste (FDR).jpg"), (jpeg(), "Ana Souza (BDV).jpg"))
    generico = enviar(cliente, (jpeg(), "scan_1.jpg"), (jpeg(), "IMG_0001.jpg"))
    assert all("origem_arquivo" not in r and "origem" not in r for r in misto + generico)


def test_envios_soltos_sucessivos_com_nomes_diferentes_nao_sugerem(cliente):
    primeiro = enviar(cliente, (jpeg(), "Lia Exemplo (FDR).jpg"))
    segundo = enviar(cliente, (jpeg(), "Maria Teste (BDV).jpg"), ids_atuais=[primeiro[0]["id"]])
    assert "origem_arquivo" not in segundo[0]


def test_nome_dos_arquivos_ausente_da_planilha_nao_tem_candidato(cliente):
    resp = enviar(cliente, (jpeg(), "Lia Exemplo (FDR).jpg"))
    assert resp[0]["origem_arquivo"] == "LIA EXEMPLO"
    assert cliente.get("/sugerir", query_string={"empresa": "EMPRESA A",
                       "planilha": "2026/10_Planilha_de_Faturamento_Exemplo_Outubro_26.xlsx",
                       "origem": resp[0]["origem_arquivo"]}).get_json() == []


def test_previa_informa_conferencia(cliente):
    def conf(origem, nome):
        return cliente.get("/previa", query_string={"pasta": PASTA["p"], "tipo": "ADULTO-PED", "numero": "4",
                                                    "nome": nome, "origem": origem}).get_json()["confere"]
    assert conf("MARIA SOUZA", "MARIA FICTICIA DE SOUZA") is True
    assert conf("MARIA SOUZA", "ANA PEREIRA") is False
    assert conf("drive-download-20261014T190644Z-1-001", "ANA PEREIRA") is None
    assert conf("", "ANA PEREIRA") is None


def test_ping_identifica_o_app(cliente):
    assert cliente.get("/ping").get_data(as_text=True) == "mesclador"


def test_encerrar_chama_a_rotina_de_saida(config, tmp_path):
    import time
    from mesclador.web import create_app
    app = create_app(config, pasta_temp=tmp_path / "t3")
    chamado = []
    app.config["AO_ENCERRAR"] = lambda url: chamado.append(url)   # não mata o processo do teste
    assert app.test_client().post("/encerrar").get_json() == {"ok": True}
    time.sleep(0.5)
    assert chamado == ["http://localhost"]   # endereço usado para achar e fechar a aba


# ---------- ajustes de legibilidade por item (tela de mesclar) ----------

def _cinza(valor=100, largura=300, altura=400):
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (largura, altura), (valor, valor, valor)).save(b, "JPEG")
    b.seek(0)
    return b


def _media_da_pagina(caminho, indice):
    import pypdfium2 as pdfium
    from PIL import ImageStat
    doc = pdfium.PdfDocument(str(caminho))
    try:
        img = doc[indice].render(scale=1).to_pil().convert("L")
    finally:
        doc.close()
    return ImageStat.Stat(img).mean[0]


def test_mesclar_com_ajuste_clareia_so_o_item_ajustado(cliente, pasta_principal):
    ids = [r["id"] for r in enviar(cliente, (_cinza(100), "a.jpg"), (pdf(1), "b.pdf"))]
    itens = [{"id": ids[0], "giro": 0, "brilho": 60, "contraste": 0, "realce": False},
             {"id": ids[1], "giro": 0, "brilho": 0, "contraste": 0, "realce": False}]
    r = cliente.post("/salvar", json=corpo(ids, itens=itens))
    assert r.status_code == 200
    saida = Path(r.get_json()["caminho"])
    assert _media_da_pagina(saida, 0) > 100 + 20          # imagem ficou mais clara que o original
    pagina_pdf = PdfReader(saida).pages[1]
    assert (float(pagina_pdf.mediabox.width), float(pagina_pdf.mediabox.height)) == (595, 842)   # PDF sem ajuste não virou imagem


def test_mesclar_pdf_com_realce_mantem_as_paginas(cliente):
    ids = [r["id"] for r in enviar(cliente, (pdf(2), "a.pdf"))]
    assert len(ids) == 2   # uma folha por página
    itens = [{"id": i, "giro": 0, "brilho": 0, "contraste": 0, "realce": True} for i in ids]
    r = cliente.post("/salvar", json=corpo(ids, itens=itens))
    assert r.status_code == 200
    assert len(PdfReader(r.get_json()["caminho"]).pages) == 2


def test_salvar_recusa_ajuste_invalido(cliente):
    ids = [r["id"] for r in enviar(cliente, (jpeg(), "a.jpg"))]
    itens = [{"id": ids[0], "giro": 0, "brilho": "muito"}]
    assert cliente.post("/salvar", json=corpo(ids, itens=itens)).status_code == 400


def test_miniatura_com_ajuste_responde_jpeg(cliente):
    id_ = enviar(cliente, (jpeg(), "a.jpg"))[0]["id"]
    r = cliente.get(f"/miniatura/{id_}?brilho=50&contraste=-20&realce=1")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    assert cliente.get(f"/miniatura/{id_}?brilho=abc").status_code == 400


def test_miniatura_ampliada_renderiza_a_primeira_pagina(cliente):
    from io import BytesIO
    from PIL import Image
    id_ = enviar(cliente, (pdf(2), "a.pdf"))[0]["id"]
    r = cliente.get(f"/miniatura/{id_}?tam=1400&brilho=10")
    assert r.mimetype == "image/jpeg"
    assert max(Image.open(BytesIO(r.data)).size) > 1000


# ---------- PDF de várias páginas vira um cartão por página ----------

def test_pdf_de_varias_paginas_vira_um_item_por_pagina(cliente):
    resp = enviar(cliente, (pdf(3), "x.pdf"))
    assert [r["nome"] for r in resp] == ["x.pdf · p1", "x.pdf · p2", "x.pdf · p3"]
    assert [r["paginas"] for r in resp] == [1, 1, 1]


def test_zip_com_pdf_de_duas_paginas_e_imagem_mantem_ordem_e_origem(cliente):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("MARIA SOUZA/a.pdf", pdf(2).getvalue())
        z.writestr("MARIA SOUZA/b.jpg", jpeg().getvalue())
    b.seek(0)
    resp = enviar(cliente, (b, "MARIA SOUZA-20261014T190644Z-001.zip"))
    assert [r["nome"] for r in resp] == ["a.pdf · p1", "a.pdf · p2", "b.jpg"]
    assert all(r["origem"] == "MARIA SOUZA" for r in resp)


def test_mesclar_paginas_separadas_na_ordem_nova_sem_virar_imagem(cliente):
    p1, p2, p3 = (r["id"] for r in enviar(cliente, (pdf(3), "x.pdf")))
    r = cliente.post("/salvar", json=corpo([p3, p1, p2], itens=[{"id": i, "giro": 0} for i in (p3, p1)]))
    assert r.status_code == 200
    paginas = PdfReader(r.get_json()["caminho"]).pages
    assert len(paginas) == 2
    assert all((float(p.mediabox.width), float(p.mediabox.height)) == (595, 842) for p in paginas)


def test_versao_devolve_o_hash_do_codigo(config, tmp_path):
    from mesclador.versao import calcular_versao
    from mesclador.web import create_app
    app = create_app(config, pasta_temp=tmp_path / "t4")
    assert app.test_client().get("/versao").get_data(as_text=True) == calcular_versao()


def test_versao_informada_na_criacao_e_a_que_a_rota_devolve(config, tmp_path):
    from mesclador.web import create_app
    app = create_app(config, pasta_temp=tmp_path / "t5", versao="abc123")
    assert app.test_client().get("/versao").get_data(as_text=True) == "abc123"


def test_horas_aparece_na_navegacao_e_na_pagina(cliente):
    for rota in ("/", "/painel/", "/mesclar", "/horas/"):
        html = cliente.get(rota).get_data(as_text=True)
        assert 'href="/horas/"' in html
        assert 'id="horasIndicador"' in html
        assert 'fetch("/horas/dados")' in html
        assert 'setInterval(atualizarIndicadorHoras, 1000)' in html
    pagina = cliente.get("/horas/").get_data(as_text=True)
    for identificador in ("horasTipo", "horasNovoTipo", "horasTarefa", "horasEmpresa",
                          "horasIniciar", "horasParar", "horasRelogio", "horasTotais", "horasSessoes"):
        assert f'id="{identificador}"' in pagina
    assert 'href="/horas/" class="ativa"' in pagina
    assert '.textContent =' in pagina


def test_tela_horas_usa_data_dd_mm_aa(cliente):
    html = cliente.get("/horas/").get_data(as_text=True)
    assert "function horasDataHora(data)" in html
    assert "toLocaleString" not in html


def test_indicador_de_horas_mostra_empresa_e_tempo_em_caixa_com_borda(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'border: 1px solid var(--acento)' in html
    assert '${horasEmpresa || "Sem empresa"} · ${tempo}' in html
    assert '● ${horasTipo}' not in html
    assert 'indicador.title = horasDescricao' in html


def test_inicio_tem_seletor_de_mes_compartilhado_com_a_auditoria(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'id="inicioMes" type="month"' in html
    assert 'lembrar("painelMes")' in html
    assert 'guardar("painelMes", campoMes.value)' in html
    assert 'encodeURIComponent(campoMes.value)' in html


def test_empresa_da_inicio_abre_auditoria_e_conta_tempo(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'noInicio("a", "", "inicio-empresa inicio-link")' in html
    assert '"/horas/auditoria"' in html
    assert "new URLSearchParams({mes: dados.mes, empresa: empresa.empresa})" in html
    # a aba Auditoria pelo menu não mexe no contador
    assert "/horas/auditoria" not in cliente.get("/painel/").get_data(as_text=True)


def test_encerrar_pelo_botao_para_o_contador_e_reinicio_mantem(config, tmp_path):
    from mesclador import horas
    from mesclador.web import create_app
    app = create_app(config, pasta_temp=tmp_path / "t4")
    app.config["AO_ENCERRAR"] = lambda url: None
    cliente = app.test_client()
    assert cliente.post("/horas/auditoria", json={"empresa": "EMPRESA A"}).status_code == 200
    # reinício por versão nova (__main__ manda POST sem corpo): continua contando
    assert cliente.post("/encerrar", data=b"").status_code == 200
    assert horas.listar(config, datetime.now())["ativa"]["empresa"] == "EMPRESA A"
    # botão Encerrar da barra: para a contagem
    assert cliente.post("/encerrar", json={"parar_horas": True}).status_code == 200
    assert horas.listar(config, datetime.now())["ativa"] is None
    assert "JSON.stringify({parar_horas: true})" in cliente.get("/").get_data(as_text=True)
