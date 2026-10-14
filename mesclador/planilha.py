"""Tudo que envolve a planilha de faturamento: listar, ler e buscar o Nº da remoção."""

import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from .config import MESES

_cache = {}   # (caminho, data de modificação) -> remoções lidas


def normalizar(texto):
    """'José  da Silva ' -> 'JOSE DA SILVA' (sem acento, maiúsculo, espaços únicos)."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def numero_para_texto(valor):
    """45, 45.0, '45' ou ' 045 ' -> '45' / '045' (só tira o '.0' e os espaços)."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def mesmo_numero(a, b):
    """'045' e '45' são o mesmo Nº."""
    return numero_para_texto(a).lstrip("0") == numero_para_texto(b).lstrip("0")


def _pontuacao_mes(caminho_relativo, ano, mes):
    """Quanto o caminho do arquivo 'parece' ser do mês escolhido.
    2 = tem o mês e o ano, 1 = só o mês, 0 = nada."""
    texto = normalizar(caminho_relativo)
    tokens = set(re.split(r"[^A-Z0-9]+", texto))
    tem_mes = normalizar(MESES[mes - 1]) in tokens or f"{mes:02d}" in tokens or f"{ano}{mes:02d}" in tokens
    tem_ano = str(ano) in tokens or f"{ano}{mes:02d}" in tokens
    return (2 if tem_ano else 1) if tem_mes else 0


def listar_planilhas(base, ano=None, mes=None, limite=60, somente_do_mes=False):
    """Lista as planilhas (.xlsx/.xlsm) da pasta da empresa.
    As que batem com o mês/ano escolhidos vêm primeiro; depois, as mais recentes.
    Com somente_do_mes=True, devolve apenas as que batem com o mês/ano."""
    if not base or not Path(base).exists():
        return []
    base = Path(base)
    encontradas = []
    for p in base.rglob("*"):
        if p.suffix.lower() not in {".xlsx", ".xlsm"} or p.name.startswith("~$"):
            continue
        partes = p.relative_to(base).parts
        # ignora backups e versões antigas: pastas que começam com "_" e arquivos "BACKUP..."
        if any(parte.startswith("_") for parte in partes[:-1]) or p.name.upper().startswith("BACKUP"):
            continue
        relativo = str(p.relative_to(base))
        pontos = _pontuacao_mes(relativo, ano, mes) if ano and mes else 0
        encontradas.append((pontos, p.stat().st_mtime, relativo))
    if somente_do_mes:
        encontradas = [e for e in encontradas if e[0] == 2]
    encontradas.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [{"caminho": rel, "do_mes": pontos == 2} for pontos, _, rel in encontradas[:limite]]


def resolver_caminho(base, relativo):
    """Caminho relativo vindo da tela -> caminho real, sem permitir sair da pasta base."""
    if not base or not relativo:
        return None
    base = Path(base).resolve()
    caminho = (base / relativo).resolve()
    if base not in caminho.parents or not caminho.is_file():
        return None
    return caminho


def ler_planilha(caminho, abas):
    """Lê as abas configuradas e devolve [{'numero','nome','tipo','aba','linha'}].
    Usa cache enquanto o arquivo não for modificado."""
    caminho = Path(caminho)
    chave = (str(caminho), caminho.stat().st_mtime)
    if chave in _cache:
        return _cache[chave]

    wb = load_workbook(caminho, data_only=True, read_only=True)
    abas_da_planilha = {normalizar(n): n for n in wb.sheetnames}
    remocoes = []
    for aba in abas:
        # usa o primeiro nome configurado que existir nesta planilha
        nome_real = next((abas_da_planilha[normalizar(n)] for n in aba.nomes
                          if normalizar(n) in abas_da_planilha), None)
        if nome_real is None:
            continue
        ws = wb[nome_real]
        i_num = column_index_from_string(aba.col_numero) - 1
        i_nome = column_index_from_string(aba.col_nome) - 1
        ultima_col = max(i_num, i_nome) + 1
        for linha, valores in enumerate(ws.iter_rows(min_row=aba.primeira_linha, max_col=ultima_col,
                                                     values_only=True), start=aba.primeira_linha):
            valores = tuple(valores) + (None,) * (ultima_col - len(valores))
            numero, nome = valores[i_num], valores[i_nome]
            if numero is None or nome is None or str(nome).strip() == "":
                continue
            remocoes.append({"numero": numero_para_texto(numero), "nome": normalizar(nome),
                             "tipo": aba.tipo, "aba": nome_real, "linha": linha})
    wb.close()

    _cache.clear()           # guarda só a última planilha lida
    _cache[chave] = remocoes
    return remocoes


def buscar(remocoes, numero, tipo=None):
    """Remoções com esse Nº. A numeração recomeça em cada aba, então informe o tipo
    para buscar só na aba certa; sem tipo, devolve as de todas as abas."""
    if not numero_para_texto(numero):
        return []
    return [r for r in remocoes if mesmo_numero(r["numero"], numero) and (not tipo or r["tipo"] == tipo)]
