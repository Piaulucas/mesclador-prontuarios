"""Auditoria com planilhas e nomes inteiramente fictícios."""

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Color, PatternFill

from mesclador import auditoria
from mesclador.config import Aba, Config


ABAS = [Aba(["ADULTO-PED"], "ADULTO-PED", "B", "D", 16, "ADULTO"),
        Aba(["ADULTO-PED COVID"], "ADULTO-PED COVID", "B", "D", 16,
            "ADULTO_PED_COVID", "COV"),
        Aba(["NEONATAL COVID"], "NEONATAL COVID", "B", "D", 16,
            "NEONATAL_COVID", "NCV")]


def preencher(celula, cor):
    celula.fill = PatternFill(fill_type="solid", fgColor=cor)


def salvar_planilha(tmp_path, linhas):
    livro = Workbook()
    livro.active.title = ABAS[0].tipo
    for indice, configuracao in enumerate(ABAS):
        aba = livro.active if indice == 0 else livro.create_sheet(configuracao.tipo)
        for linha, numero, paciente, cor, comentario in linhas.get(configuracao.tipo, []):
            aba[f"B{linha}"] = numero
            aba[f"D{linha}"] = paciente
            if cor == "tema":
                aba[f"E{linha}"].fill = PatternFill(fill_type="solid", fgColor=Color(theme=1))
            elif cor == "indexada":
                aba[f"E{linha}"].fill = PatternFill(fill_type="solid", fgColor=Color(indexed=5))
            elif cor == "tint":
                aba[f"E{linha}"].fill = PatternFill(fill_type="solid", fgColor=Color(rgb="FFFFFF00", tint=0.2))
            elif cor:
                preencher(aba[f"E{linha}"], cor)
            if comentario:
                aba[f"T{linha}"].comment = Comment(comentario, "Autor Fictício")
    caminho = tmp_path / "faturamento_ficticio.xlsx"
    livro.save(caminho)
    return caminho


def criar_pdf(pasta, nome):
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(b"PDF ficticio")


def test_cores_comentarios_total_e_contagem(tmp_path):
    linhas = {"ADULTO-PED": [
        (16, 1, "Ana Exemplo", "FFFFFF00", None),
        (17, 2, "Bruno Exemplo", "FFFF0000", "Autor: Enviar BDV"),
        (18, 3, "Clara Exemplo", None, None),
        (19, 4, "Dora Exemplo", "tema", None),
        (20, None, "   ", None, None),
        (21, 6, "Linha Após Total", None, None)]}
    fichas = auditoria.ler_fichas(salvar_planilha(tmp_path, linhas), ABAS)
    assert [f["estado"] for f in fichas] == [
        "por_auditar", "com_equipe", "concluida", "cor_desconhecida"]
    assert [f["ficha"] for f in fichas] == ["ADU01", "ADU02", "ADU03", "ADU04"]
    assert fichas[1]["comentario"] == "Enviar BDV"
    assert auditoria.contar(fichas) == {
        "lancadas": 4, "por_auditar": 1, "com_equipe": 1,
        "concluidas": 1, "cor_desconhecida": 1, "percentual_concluido": 25}
    assert [f["ficha"] for f in auditoria.pendencias(fichas)] == ["ADU02"]
    assert auditoria.contar([])["percentual_concluido"] == 0


def test_cor_vermelha_prevalece_e_cores_ilegiveis_nao_aprovam(tmp_path):
    caminho = salvar_planilha(tmp_path, {"ADULTO-PED": [
        (16, 1, "Ana Exemplo", "indexada", None),
        (17, 2, "Bruno Exemplo", "tint", None),
        (18, 3, "Clara Exemplo", "FF00FF00", None)]})
    from openpyxl import load_workbook
    livro = load_workbook(caminho)
    preencher(livro.active["F19"], "FFFFFF00")
    preencher(livro.active["G19"], "FFFFC7CE")
    livro.active["B19"] = 4
    livro.active["D19"] = "Dora Exemplo"
    livro.save(caminho)
    livro.close()
    assert [f["estado"] for f in auditoria.ler_fichas(caminho, ABAS)] == [
        "cor_desconhecida", "cor_desconhecida", "cor_desconhecida", "com_equipe"]


def test_cada_inconsistencia_e_pdfs_sem_linha(tmp_path):
    linhas = {"ADULTO-PED": [
        (16, 1, "Ana Exemplo", None, None),
        (17, 2, "Bruno Exemplo", "FFFFFF99", None),
        (18, 3, "Clara Exemplo", "FFFF9999", None),
        (19, 4, "Dora Exemplo", None, "Autor: Revisar"),
        (20, 8, "Eva Exemplo", "tema", None),
        (21, 6, "José Fictício", None, None)]}
    fichas = auditoria.ler_fichas(salvar_planilha(tmp_path, linhas), ABAS)
    pasta = tmp_path / "mes" / "ADULTO-PED"
    for nome in ["02 - Bruno Exemplo.pdf", "03 - Clara Exemplo.pdf",
                 "04 - Dora Exemplo.pdf", "06 - JOSE FICTICIO.pdf",
                 "06 - Outra Pessoa.pdf", "99 - Sem Linha.pdf"]:
        criar_pdf(pasta, nome)
    pdfs = auditoria.listar_pdfs(tmp_path / "mes", ABAS[0])
    dados = auditoria.cruzar(fichas, {"ADULTO-PED": pdfs})
    motivos = [i["motivo"] for i in dados["inconsistencias"]]
    assert set(motivos) == {
        "sem_cor_sem_pdf", "amarela_com_pdf", "vermelha_com_pdf",
        "sem_cor_com_comentario", "cor_desconhecida", "numero_fora_da_posicao",
        "pdf_duplicado", "nome_pdf_diferente"}
    assert motivos.count("nome_pdf_diferente") == 1
    assert [p["numero"] for p in dados["pdfs_sem_linha"]] == ["99"]
    assert dados["fichas"][0]["tem_pdf"] is False


def test_covid_tem_codigo_e_subpasta_proprios(tmp_path):
    caminho = salvar_planilha(tmp_path, {
        "ADULTO-PED": [(16, 1, "Ana Exemplo", None, None)],
        "ADULTO-PED COVID": [(16, 1, "Bia Exemplo", None, None)],
        "NEONATAL COVID": [(16, 1, "Cris Exemplo", None, None)]})
    fichas = auditoria.ler_fichas(caminho, ABAS)
    assert [f["ficha"] for f in fichas] == ["ADU01", "COV01", "NCV01"]
    criar_pdf(tmp_path / "mes" / "ADULTO_PED_COVID", "01 - Bia Exemplo.pdf")
    assert auditoria.listar_pdfs(tmp_path / "mes", ABAS[0]) == []
    assert len(auditoria.listar_pdfs(tmp_path / "mes", ABAS[1])) == 1
    assert len(auditoria.cruzar([], {"ADULTO-PED COVID": auditoria.listar_pdfs(
        tmp_path / "mes", ABAS[1])})["pdfs_sem_linha"]) == 1


def test_pasta_do_mes_ausente_e_variante_sem_acento(tmp_path):
    config = Config(tmp_path, {}, ABAS, auditoria_prontuarios={
        "EMPRESA FICTÍCIA": str(tmp_path / "{ano}" / "{mm}_{MES}")})
    assert auditoria.pasta_prontuarios(config, "EMPRESA FICTÍCIA", 2026, 3) is None
    assert auditoria.localizar_prontuarios(config, "EMPRESA FICTÍCIA", 2026, 3)["aviso"]
    assert auditoria.listar_pdfs(None, ABAS[0]) == []
    pasta = tmp_path / "2026" / "03_MARCO"
    pasta.mkdir(parents=True)
    assert auditoria.pasta_prontuarios(config, "EMPRESA FICTÍCIA", 2026, 3) == pasta
    assert auditoria.localizar_prontuarios(config, "EMPRESA FICTÍCIA", 2026, 3)["aviso"] is None
