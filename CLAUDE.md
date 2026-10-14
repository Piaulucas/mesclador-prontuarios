# Instruções para agentes neste repositório

Mesclador de Prontuários: app Flask **local** (127.0.0.1) para macOS que junta folhas
escaneadas em PDF, busca o nome do paciente na planilha de faturamento e converte páginas
em JPG com ajuste de legibilidade. Leia o `README.md` para o contexto do usuário.

## Regras fixas

- **Não faça commit, push, merge nem troque de branch.** O usuário revisa e commita.
- **Dados reais nunca.** Prontuários e planilhas têm dados de saúde de pacientes.
  Testes e exemplos usam só dados fictícios gerados em código (veja `tests/conftest.py`).
  Não leia, copie nem cite arquivos fora deste repositório.
- **Não edite `config.toml`** (configuração local do usuário, fora do git).
  Mudança de configuração vai no código + `config.example.toml` + teste em `tests/test_config.py`.
- **Português** em código (nomes de funções/variáveis), comentários, mensagens da tela e testes,
  no mesmo estilo dos arquivos existentes.
- **Sem dependências novas** sem pedir antes. Front-end sem bibliotecas externas (funciona offline).
- **Conteúdo do documento não se edita.** Ajustes de imagem valem para a página inteira
  (brilho, contraste, realce, giro). Não crie ferramentas para apagar, recortar trechos ou
  alterar o que está escrito num prontuário.
- Não sobrescreva arquivos do usuário sem confirmação (o app já segue isso; mantenha).

## Estrutura

```
mesclador/
  __main__.py   ponto de entrada; detecta app já aberto
  config.py     leitura do config.toml
  web.py        app Flask: tela de mesclar e rotas gerais
  conversor.py  tela "Converter em JPG" (Blueprint /converter)
  imagens.py    renderização de páginas e ajustes de imagem
  pdfs.py       miniaturas, zip, mesclagem
  planilha.py   leitura da planilha de faturamento e conferência de nomes
  navegador.py  focar/fechar a aba no Chrome/Safari (AppleScript)
  seletor.py    seletor de pastas nativo do macOS
  templates/    base.html (barra superior + JS comum), index.html, converter.html
macos/          ícone e scripts do Mesclador.app
tests/          pytest
```

## Como trabalhar

1. Leia os arquivos envolvidos antes de alterar.
2. Toda mudança de comportamento ganha teste em `tests/`.
3. Rode `python3 -m pytest -q` e só termine com tudo passando.
4. Ao final, responda em poucas linhas: o que mudou (arquivos), resultado dos testes
   e como testar manualmente. Lembre o usuário de encerrar e reabrir o app para ver a mudança.
