# Mesclador de Prontuários

Ferramenta local para montar, um a um, os prontuários que acompanham o faturamento de remoções em UTI móvel: junta as folhas escaneadas (PDF/JPEG/PNG) na ordem certa, busca o nome do paciente na planilha de faturamento pelo Nº da remoção e salva o PDF com o nome e na pasta corretos.

![Tela do Mesclador](docs/tela.png)
_Dados fictícios._

## O problema

Na auditoria de faturamento, cada remoção precisa de um prontuário em PDF nomeado como `04 - NOME DO PACIENTE.pdf` e arquivado na pasta do mês, separado por tipo de remoção (adulto/pediátrico ou neonatal). As folhas chegam escaneadas separadamente, em formatos misturados, com nomes de arquivo sem padrão.

O fluxo manual era: baixar as folhas em `.zip`, extrair, enviar para um site de mesclagem online, baixar o resultado, renomear consultando a planilha e mover para a pasta certa. Além de lento, isso enviava **dados de saúde de pacientes para um serviço de terceiros**.

## O que a ferramenta faz

- Arrastar o **.zip baixado**, a **pasta** extraída ou os arquivos soltos; as folhas entram em ordem natural (`pag2` antes de `pag10`) e o lixo do macOS (`__MACOSX`, `.DS_Store`) é ignorado
- Reordenar arrastando os cartões, girar folhas escaneadas de lado, remover folhas
- Escolher o tipo (ADULTO-PED / NEONATAL) e digitar o Nº da remoção → o nome vem da aba certa da planilha `.xlsx` (a numeração recomeça em cada aba)
- Pré-seleciona a planilha do mês escolhido (pelo mês/ano no caminho do arquivo) e ignora versões antigas/backups
- Você escolhe a pasta principal no seletor nativo do macOS; o app usa a subpasta do tipo (`ADULTO…` / `NEO…`) e a cria se não existir
- Nº com 2 dígitos (`04`, `05`, `10`) para a ordenação ficar certa
- Mostra o caminho final antes de salvar e não sobrescreve sem confirmação
- Roda **só no computador** (`127.0.0.1`): nenhum arquivo sai da máquina, sem dependência de internet

## Decisões de projeto

| Decisão                                           | Motivo                                                                                                                    |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Um prontuário por vez, não em lote                | A ordem das folhas e a escolha do que entra dependem da auditoria humana; automatizar isso esconderia erros               |
| App web local (Flask) em vez de interface desktop | Arrastar e soltar e miniaturas saem prontos no navegador; nenhuma biblioteca externa de front-end, então funciona offline |
| `.gitignore` bloqueia PDF, imagens e planilhas    | Evita que um prontuário real seja versionado por engano                                                                   |
| Não sobrescreve e mostra a prévia do caminho      | Um arquivo com nome errado vira glosa                                                                                     |

## Instalação

Requer Python 3.9+.

```bash
git clone https://github.com/Piaulucas/mesclador-prontuarios.git
cd mesclador-prontuarios
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml   # edite caminhos, empresas e colunas da planilha
```

## Uso

```bash
python3 -m mesclador
```

O navegador abre em `http://127.0.0.1:5050`. Para encerrar, `Ctrl+C` no terminal.

1. Escolha empresa e mês (a planilha do mês é selecionada sozinha)
2. Escolha a pasta principal do mês (fica lembrada por empresa e mês)
3. Arraste o .zip do Drive (ou a pasta, ou os arquivos) e confira a ordem
4. Escolha o tipo, digite o Nº da remoção e pressione Enter
5. `⌘ Enter` (ou o botão) para mesclar e salvar

### Abrir com um ícone (macOS)

Para não precisar do Terminal no dia a dia, crie o ícone uma vez:

```bash
bash macos/criar_app.sh
```

Isso gera `~/Applications/Mesclador.app`; arraste-o para o Dock. O ícone abre o app em segundo plano e, se ele já estiver aberto, só mostra a janela de novo. Para fechar, use o botão **Encerrar o app** na tela. O registro de execução fica em `~/Library/Logs/mesclador.log`. Se a pasta do projeto mudar de lugar, rode o script de novo.

## Configuração

Tudo fica em `config.toml` (veja os comentários em [`config.example.toml`](config.example.toml)):

- `pasta_inicial`: onde o seletor de pasta abre na primeira vez
- `mes_inicial`: primeiro mês de uso; meses anteriores ficam bloqueados
- `[empresas]`: pasta de planilhas de cada empresa (vazio = digitar o nome à mão)
- `[abas."..."]`: nomes possíveis da aba, letras das colunas de Nº e nome, primeira linha de dados e a palavra que identifica a subpasta de destino

## Estrutura

```
mesclador/
  config.py     leitura do config.toml
  planilha.py   listar, ler e buscar na planilha de faturamento
  pdfs.py       miniaturas, conversão de imagem e mesclagem
  seletor.py    seletor de pastas nativo do macOS
  web.py        rotas Flask
  templates/    interface (HTML/CSS/JS sem dependências externas)
tests/          testes com dados fictícios
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Licença

MIT
