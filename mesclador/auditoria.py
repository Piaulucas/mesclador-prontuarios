"""Leitura da auditoria do mês, sem alterar planilhas ou pastas de prontuários."""

import re
import unicodedata
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from .config import MESES
from . import planilha, pdfs


AMARELOS = {"FFFFFF00", "FFFFFF99", "FFFFE699"}
VERMELHOS = {"FFFF0000", "FFFFC7CE", "FFFF9999"}
PADRAO_PDF = re.compile(r"^(\d+)\s*-\s*(.+)\.pdf$", re.IGNORECASE)


def pasta_prontuarios(config, empresa, ano, mes):
    """Resolve a pasta do mês; aceita MARCO quando o molde MARÇO não existe."""
    molde = config.auditoria_prontuarios.get(empresa)
    if not molde:
        return None
    caminho = Path(molde.format(ano=ano, mm=f"{int(mes):02d}", MES=MESES[int(mes) - 1])).expanduser()
    if caminho.is_dir():
        return caminho
    mes_sem_acento = "".join(c for c in unicodedata.normalize("NFKD", MESES[int(mes) - 1])
                             if not unicodedata.combining(c))
    variante = Path(molde.format(ano=ano, mm=f"{int(mes):02d}", MES=mes_sem_acento)).expanduser()
    return variante if variante.is_dir() else None


def localizar_prontuarios(config, empresa, ano, mes):
    """Devolve a pasta e um aviso quando ela não estiver disponível."""
    pasta = pasta_prontuarios(config, empresa, ano, mes)
    return {"pasta": pasta,
            "aviso": None if pasta else "Pasta de prontuários do mês não encontrada."}


def _cor_da_celula(celula):
    preenchimento = celula.fill
    if preenchimento.patternType is None:
        return None
    cor = preenchimento.fgColor
    if preenchimento.patternType != "solid" or cor.type != "rgb" or cor.tint != 0:
        return "cor_desconhecida"
    rgb = cor.rgb
    if not isinstance(rgb, str) or len(rgb) != 8:
        return "cor_desconhecida"
    rgb = rgb.upper()
    if rgb in VERMELHOS:
        return "com_equipe"
    if rgb in AMARELOS:
        return "por_auditar"
    return "cor_desconhecida"


def cor_da_linha(aba, linha, col_numero="B", col_observacoes="T"):
    """Vermelho prevalece; qualquer cor ilegível impede aprovação silenciosa."""
    inicio = column_index_from_string(col_numero)
    fim = column_index_from_string(col_observacoes)
    estados = {_cor_da_celula(aba.cell(linha, coluna)) for coluna in range(inicio, fim + 1)}
    if "com_equipe" in estados:
        return "com_equipe"
    if "cor_desconhecida" in estados:
        return "cor_desconhecida"
    if "por_auditar" in estados:
        return "por_auditar"
    return "concluida"


def comentario_da_linha(aba, linha, col_numero="B", col_observacoes="T"):
    """Primeiro comentário entre Nº e observações, sem o prefixo Autor:."""
    for coluna in range(column_index_from_string(col_numero),
                        column_index_from_string(col_observacoes) + 1):
        comentario = aba.cell(linha, coluna).comment
        if comentario:
            return re.sub(r"^\s*Autor:\s*", "", comentario.text.strip(), flags=re.IGNORECASE)
    return ""


def ler_fichas(caminho, abas):
    """Lê fichas das abas configuradas, parando na primeira linha sem paciente."""
    livro = load_workbook(caminho, data_only=True)
    fichas = []
    try:
        nomes = {planilha.normalizar(nome): nome for nome in livro.sheetnames}
        for configuracao in abas:
            nome_aba = next((nomes[planilha.normalizar(nome)] for nome in configuracao.nomes
                             if planilha.normalizar(nome) in nomes), None)
            if nome_aba is None:
                continue
            aba = livro[nome_aba]
            for linha in range(configuracao.primeira_linha, aba.max_row + 1):
                paciente = aba[f"{configuracao.col_nome}{linha}"].value
                if paciente is None or not str(paciente).strip():
                    break
                numero = planilha.numero_para_texto(aba[f"{configuracao.col_numero}{linha}"].value)
                posicao = linha - configuracao.primeira_linha + 1
                numero_codigo = int(numero) if numero.isdigit() else numero
                fichas.append({"ficha": f"{configuracao.codigo}{numero_codigo:02d}" if isinstance(numero_codigo, int)
                               else f"{configuracao.codigo}{numero}",
                               "numero": numero, "paciente": planilha.normalizar(paciente),
                               "tipo": configuracao.tipo, "aba": nome_aba, "linha": linha,
                               "posicao": posicao, "estado": cor_da_linha(aba, linha, configuracao.col_numero),
                               "comentario": comentario_da_linha(aba, linha, configuracao.col_numero)})
    finally:
        livro.close()
    return fichas


def listar_pdfs(pasta_mes, aba):
    """Lista PDFs numerados da subpasta configurada, sem criá-la."""
    if not pasta_mes or not Path(pasta_mes).is_dir():
        return []
    alvo = planilha.normalizar(aba.palavra_subpasta or aba.tipo.split("-")[0])
    pastas = sorted(p for p in Path(pasta_mes).iterdir() if p.is_dir()
                    and planilha.normalizar(p.name).startswith(alvo)
                    and ("COVID" in alvo or "COVID" not in planilha.normalizar(p.name)))
    if not pastas:
        return []
    encontrados = []
    for caminho in sorted(pastas[0].iterdir()):
        if not caminho.is_file():
            continue
        resultado = PADRAO_PDF.fullmatch(caminho.name)
        if resultado:
            encontrados.append({"numero": resultado.group(1), "paciente": resultado.group(2),
                                "caminho": caminho})
    return encontrados


def cruzar(fichas, pdfs_por_tipo):
    """Cruza fichas com PDFs e devolve fichas, inconsistências e PDFs sem linha."""
    resultado = []
    inconsistencias = []
    sem_linha = []
    por_tipo = {}
    for ficha in fichas:
        por_tipo.setdefault(ficha["tipo"], []).append(ficha)
    for tipo in dict.fromkeys([*por_tipo, *pdfs_por_tipo]):
        linhas = por_tipo.get(tipo, [])
        arquivos = pdfs_por_tipo.get(tipo, [])
        contagem = Counter(planilha.numero_para_texto(p["numero"]).lstrip("0") for p in arquivos)
        numeros = {planilha.numero_para_texto(f["numero"]).lstrip("0") for f in linhas}
        for arquivo in arquivos:
            numero = planilha.numero_para_texto(arquivo["numero"]).lstrip("0")
            if numero not in numeros:
                sem_linha.append({"tipo": tipo, **arquivo})
        for numero, quantidade in contagem.items():
            if quantidade > 1:
                inconsistencias.append({"tipo": tipo, "numero": numero, "motivo": "pdf_duplicado"})
        for ficha in linhas:
            numero = planilha.numero_para_texto(ficha["numero"]).lstrip("0")
            correspondentes = [p for p in arquivos if planilha.numero_para_texto(p["numero"]).lstrip("0") == numero]
            item = {**ficha, "tem_pdf": bool(correspondentes)}
            resultado.append(item)
            motivos = []
            if ficha["estado"] == "concluida" and not correspondentes:
                motivos.append("sem_cor_sem_pdf")
            if ficha["estado"] == "por_auditar" and correspondentes:
                motivos.append("amarela_com_pdf")
            if ficha["estado"] == "com_equipe" and correspondentes:
                motivos.append("vermelha_com_pdf")
            if ficha["estado"] == "concluida" and ficha["comentario"]:
                motivos.append("sem_cor_com_comentario")
            if ficha["estado"] == "cor_desconhecida":
                motivos.append("cor_desconhecida")
            if not planilha.mesmo_numero(ficha["numero"], ficha["posicao"]):
                motivos.append("numero_fora_da_posicao")
            for arquivo in correspondentes:
                nome_pdf = planilha.normalizar(pdfs.limpar_nome_arquivo(arquivo["paciente"]))
                nome_ficha = planilha.normalizar(pdfs.limpar_nome_arquivo(ficha["paciente"]))
                if nome_pdf != nome_ficha:
                    motivos.append("nome_pdf_diferente")
            inconsistencias.extend({"ficha": ficha["ficha"], "tipo": tipo, "motivo": motivo}
                                    for motivo in dict.fromkeys(motivos))
    return {"fichas": resultado, "inconsistencias": inconsistencias, "pdfs_sem_linha": sem_linha}


def contar(fichas):
    """Conta estados; a porcentagem concluída usa todas as linhas lançadas."""
    estados = Counter(ficha["estado"] for ficha in fichas)
    total = len(fichas)
    return {"lancadas": total, "por_auditar": estados["por_auditar"],
            "com_equipe": estados["com_equipe"], "concluidas": estados["concluida"],
            "cor_desconhecida": estados["cor_desconhecida"],
            "percentual_concluido": 100 * estados["concluida"] / total if total else 0}


def pendencias(fichas):
    """Fichas devolvidas à equipe, ainda sem cálculo de prazos ou registros."""
    return [ficha for ficha in fichas if ficha["estado"] == "com_equipe"]
