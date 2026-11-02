# Instruções para agentes neste repositório

Área de trabalho: app Flask **local** (127.0.0.1) para macOS. A Início acompanha a
auditoria; Mesclar prontuário junta folhas escaneadas em PDF e busca o nome do paciente
na planilha de faturamento; Converter em JPG ajusta a legibilidade. Leia o `README.md` para o contexto do usuário.

## Regras fixas

- **Nunca faça merge, nem commit/push direto na `main`.** Cada tarefa: crie uma branch a
  partir da `main` atualizada (prefixos `feat/`, `fix/`, `test/`, `docs/`), commite, dê push
  e abra o PR com `gh`. O usuário revisa e faz o merge.
- **Antes de criar a branch, confira o ponto de partida.** Se a working tree não estiver
  limpa ou a branch atual não for a `main` ao começar, pare e avise.
- **Não deixe no repositório arquivos gerados ao rodar o app** (logs, servidores de teste,
  saídas). Use pastas temporárias nos testes.
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
  web.py        app Flask: Início (/), Mesclar (/mesclar) e rotas gerais
  painel.py     Auditoria (/painel/) e dados do mês (/painel/dados)
  pendencias.py dados locais de faturas, tarefas e prazos (/pendencias)
  horas.py      contador manual e totais de horas (/horas)
  conversor.py  tela "Converter em JPG" (Blueprint /converter)
  imagens.py    renderização de páginas e ajustes de imagem
  pdfs.py       miniaturas, zip, mesclagem
  planilha.py   leitura da planilha de faturamento e conferência de nomes
  navegador.py  focar/fechar a aba no Chrome/Safari (AppleScript)
  seletor.py    seletor de pastas nativo do macOS
  templates/    base.html (barra superior + JS comum), inicio.html, index.html,
                painel.html, converter.html; _ferramentas.css e _ampliada.html
                (estilo e folha ampliada comuns a Mesclar e Converter)
  static/       postit.js, ampliada.js (folha ampliada com os ajustes ao lado)
macos/          ícone e scripts da Área de trabalho.app
tests/          pytest
```

## Como trabalhar

1. Leia os arquivos envolvidos antes de alterar.
2. Toda mudança de comportamento ganha teste em `tests/`.
3. Rode `python3 -m pytest -q` e só termine com tudo passando.
4. Ao final, responda em poucas linhas: o que mudou (arquivos), resultado dos testes
   e como testar manualmente. Abrir pelo ícone já reinicia uma instância desatualizada; se a
   mudança não aparecer, confira com `curl -s http://127.0.0.1:5050/versao`.
