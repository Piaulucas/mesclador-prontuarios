"""Leitura do arquivo de configuração (config.toml).

O config.toml real NÃO vai para o git (está no .gitignore): ele tem caminhos
do seu computador e nomes de clientes. No repositório fica só o config.example.toml.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:                      # Python 3.9/3.10 (o do macOS pode ser antigo)
    import tomli as tomllib

MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO",
         "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


@dataclass
class Aba:
    nomes: list          # nomes que essa aba pode ter na planilha (varia entre empresas)
    tipo: str            # tipo de remoção = subpasta de destino
    col_numero: str      # letra da coluna do Nº
    col_nome: str        # letra da coluna do nome do paciente
    primeira_linha: int  # primeira linha com dados
    palavra_subpasta: str = ""   # subpasta de destino = a que começa com esta palavra (ex.: "NEO")
    codigo: str = ""             # código da ficha; padrão: 3 primeiras letras do tipo

    def __post_init__(self):
        if not self.codigo:
            self.codigo = self.tipo[:3].upper()


@dataclass
class Config:
    pasta_inicial: Path               # onde o seletor de pasta abre na primeira vez
    empresas: dict                    # nome -> Path da pasta de planilhas (ou None)
    abas: list = field(default_factory=list)
    porta: int = 5050
    mes_inicial: str = ""             # "AAAA-MM": meses anteriores ficam bloqueados (vazio = sem limite)
    auditoria_prontuarios: dict = field(default_factory=dict)  # empresa -> molde da pasta do mês

    @property
    def tipos(self):
        return [a.tipo for a in self.abas]

    def aba_do_tipo(self, tipo):
        return next((a for a in self.abas if a.tipo == tipo), None)


def _caminho(texto):
    return Path(texto).expanduser() if texto else None


def carregar(caminho=None):
    """Lê o TOML e devolve um Config. Ordem de busca:
    argumento > variável MESCLADOR_CONFIG > config.toml na raiz do projeto."""
    caminho = Path(caminho or os.environ.get("MESCLADOR_CONFIG") or RAIZ_PROJETO / "config.toml")
    if not caminho.exists():
        raise SystemExit(
            f"Configuração não encontrada: {caminho}\n"
            "Copie config.example.toml para config.toml e ajuste os caminhos."
        )
    with open(caminho, "rb") as f:
        dados = tomllib.load(f)

    abas = [
        Aba(nomes=a.get("nomes_aba", [tipo]), tipo=tipo, col_numero=a["col_numero"].upper(),
            col_nome=a["col_nome"].upper(), primeira_linha=int(a.get("primeira_linha", 2)),
            palavra_subpasta=a.get("palavra_subpasta", tipo.split("-")[0]),
            codigo=a.get("codigo", ""))
        for tipo, a in dados.get("abas", {}).items()
    ]
    if not abas:
        raise SystemExit("config.toml precisa de pelo menos uma seção [abas.\"TIPO\"].")

    return Config(
        pasta_inicial=_caminho(dados.get("pasta_inicial") or "~"),
        empresas={nome: _caminho(p) for nome, p in dados.get("empresas", {}).items()},
        abas=abas,
        porta=int(dados.get("porta", 5050)),
        mes_inicial=str(dados.get("mes_inicial", "")),
        auditoria_prontuarios=dados.get("auditoria", {}).get("prontuarios", {}),
    )
