// Tarefas rápidas disponíveis em todas as telas.
(() => {
  const botao = document.getElementById("postitBotao");
  const painel = document.getElementById("postitPainel");
  const formulario = document.getElementById("postitFormulario");
  const filtro = document.getElementById("postitFiltro");
  const lista = document.getElementById("postitTarefas");
  const aviso = document.getElementById("postitAviso");
  const campos = formulario.elements;
  let empresas = [];
  let enviando = false;

  function lembrar(chave) {
    try { return localStorage.getItem(chave); } catch (erro) { return null; }
  }
  function guardar(chave, valor) {
    try { localStorage.setItem(chave, valor); } catch (erro) { /* armazenamento indisponível */ }
  }
  function elemento(tipo, texto) {
    const no = document.createElement(tipo);
    if (texto !== undefined) no.textContent = String(texto);
    return no;
  }
  function mensagem(texto, erro = false) {
    aviso.textContent = texto;
    aviso.className = "msg " + (erro ? "erro" : "ok");
  }
  function abrir(aberto) {
    painel.hidden = !aberto;
    botao.setAttribute("aria-expanded", String(aberto));
    guardar("postitAberto", aberto ? "sim" : "nao");
    if (aberto) {
      campos.texto.focus();
      atualizar().catch(erro => mensagem(erro.message, true));
    } else botao.focus();
  }
  function opcoes(seletor, nomes, selecionado, todas = false) {
    seletor.replaceChildren();
    if (todas) {
      const opcao = elemento("option", "Todas");
      opcao.value = "";
      seletor.append(opcao);
    }
    nomes.forEach(nome => {
      const opcao = elemento("option", nome);
      opcao.value = nome;
      seletor.append(opcao);
    });
    if (nomes.includes(selecionado) || (todas && selecionado === "")) seletor.value = selecionado;
  }
  function desenhar() {
    lista.replaceChildren();
    let totalVisivel = 0;
    empresas.forEach(empresa => {
      if (filtro.value && empresa.empresa !== filtro.value) return;
      const tarefas = empresa.grupos.tarefas;
      if (!tarefas.length) return;
      totalVisivel += tarefas.length;
      const grupo = elemento("section");
      grupo.className = "postit-grupo";
      grupo.append(elemento("h3", empresa.empresa));
      const itens = elemento("ul");
      itens.className = "postit-lista";
      tarefas.forEach(tarefa => {
        const item = elemento("li");
        const rotulo = elemento("label");
        rotulo.className = "postit-linha";
        const caixa = elemento("input");
        caixa.type = "checkbox";
        caixa.setAttribute("aria-label", `Concluir tarefa: ${tarefa.texto}`);
        caixa.addEventListener("change", () => concluir(tarefa.id, caixa));
        rotulo.append(caixa, elemento("span", tarefa.texto));
        item.append(rotulo);
        if (tarefa.prazo) {
          const prazo = elemento("small", `Prazo: ${dataBR(tarefa.prazo)}`);
          prazo.className = "postit-prazo";
          if (["vencida", "vencendo"].includes(tarefa.situacao)) prazo.classList.add(tarefa.situacao);
          item.append(prazo);
        }
        itens.append(item);
      });
      grupo.append(itens);
      lista.append(grupo);
    });
    if (!totalVisivel) lista.append(elemento("p", "Nenhuma tarefa aberta."));
  }
  async function atualizar() {
    const resposta = await fetch("/pendencias/dados");
    const dados = await resposta.json();
    if (!resposta.ok) throw new Error(dados.erro || "Não foi possível ler as tarefas.");
    empresas = dados.empresas;
    botao.textContent = `Tarefas (${dados.totais.tarefas})`;
    const nomes = empresas.map(empresa => empresa.empresa);
    const empresaAtual = campos.empresa.value || lembrar("postitEmpresa") || "";
    const filtroAtual = filtro.value || lembrar("postitFiltro") || "";
    opcoes(campos.empresa, nomes, empresaAtual);
    opcoes(filtro, nomes, filtroAtual, true);
    desenhar();
  }
  async function enviar(caminho, dados) {
    const resposta = await fetch(caminho, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(dados)
    });
    const resultado = await resposta.json();
    if (!resposta.ok) throw new Error(resultado.erro || "Não foi possível salvar a tarefa.");
    await atualizar();
    document.dispatchEvent(new Event("tarefasAtualizadas"));
  }
  async function concluir(id, caixa) {
    if (enviando) { caixa.checked = false; return; }
    enviando = true;
    caixa.disabled = true;
    formulario.querySelector("button[type=submit]").disabled = true;
    try {
      await enviar(`/pendencias/tarefa/${id}`, {concluida: true});
      mensagem("Tarefa concluída.");
    } catch (erro) {
      caixa.checked = false;
      mensagem(erro.message, true);
    } finally {
      enviando = false;
      caixa.disabled = false;
      formulario.querySelector("button[type=submit]").disabled = false;
    }
  }
  formulario.addEventListener("submit", async evento => {
    evento.preventDefault();
    if (enviando) return;
    enviando = true;
    const salvar = formulario.querySelector("button[type=submit]");
    salvar.disabled = true;
    try {
      await enviar("/pendencias/tarefa", {
        empresa: campos.empresa.value, texto: campos.texto.value, prazo: campos.prazo.value || null
      });
      campos.texto.value = "";
      campos.prazo.value = "";
      campos.texto.focus();
      mensagem("Tarefa criada.");
    } catch (erro) { mensagem(erro.message, true); }
    finally { enviando = false; salvar.disabled = false; }
  });
  campos.empresa.addEventListener("change", () => guardar("postitEmpresa", campos.empresa.value));
  filtro.addEventListener("change", () => { guardar("postitFiltro", filtro.value); desenhar(); });
  botao.addEventListener("click", () => abrir(painel.hidden));
  document.addEventListener("keydown", evento => {
    if (evento.key === "Escape" && !painel.hidden) abrir(false);
  });
  document.addEventListener("tarefasAtualizadas", () => atualizar().catch(erro => mensagem(erro.message, true)));
  if (lembrar("postitAberto") === "sim") {
    painel.hidden = false;
    botao.setAttribute("aria-expanded", "true");
  }
  atualizar().catch(erro => mensagem(erro.message, true));
})();
