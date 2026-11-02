// Painel de tarefas: flutuante em todas as telas (arrastável e minimizável) e, na aba
// /tarefas/janela, numa janela própria que no Chrome fica por cima dos outros programas
// (Document Picture-in-Picture). Tudo é salvo no servidor; as abas se avisam por BroadcastChannel.
(() => {
  // referências guardadas: o painel pode mudar de documento (janela por cima)
  const q = id => document.getElementById(id);
  const painel = q("tarefasPainel"), pilula = q("tarefasPilula"), cabecalho = q("tarefasCab");
  const contador = q("tarefasContador"), formulario = q("tarefasNova"), texto = q("tarefasTexto");
  const seletorEmpresa = q("tarefasEmpresa"), prazo = q("tarefasPrazo"), filtros = q("tarefasFiltros");
  const lista = q("tarefasLista"), mensagem = q("tarefasMsg"), prazos = q("tarefasPrazos"), feitas = q("tarefasFeitas");
  const botaoPorCima = q("tarefasPorCima"), botaoManter = q("tarefasManter"), botaoMinimizar = q("tarefasMinimizar");
  if (!painel) return;
  const naJanela = document.body.classList.contains("tarefas-janela");
  const temPip = "documentPictureInPicture" in window;
  const canal = "BroadcastChannel" in window ? new BroadcastChannel("tarefas") : null;
  let dados = null, filtro = lembrarLocal("tarefasFiltro") || "contando", ocupado = false, janelaPip = null;

  function lembrarLocal(chave) { try { return localStorage.getItem(chave); } catch (erro) { return null; } }
  function guardarLocal(chave, valor) { try { localStorage.setItem(chave, valor); } catch (erro) { /* sem armazenamento */ } }
  const escapar = valor => String(valor ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const dois = n => String(n).padStart(2, "0");
  const relogio = s => `${dois(Math.floor(s / 3600))}:${dois(Math.floor(s / 60) % 60)}:${dois(s % 60)}`;
  const curto = s => s >= 3600 ? `${Math.floor(s / 3600)} h ${dois(Math.floor(s / 60) % 60)}` : `${Math.max(1, Math.floor(s / 60))} min`;
  const dataCurta = iso => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  const decorrido = () => dados && dados.ativa ? Math.max(0, Math.floor((Date.now() - new Date(dados.ativa.inicio).getTime()) / 1000)) : 0;
  let temporizadorMsg;
  function avisar(textoAviso) {
    mensagem.textContent = textoAviso;
    clearTimeout(temporizadorMsg);
    temporizadorMsg = setTimeout(() => { mensagem.textContent = ""; }, 5000);
  }
  function avisarMudanca() {
    if (canal) canal.postMessage("mudou");
    window.dispatchEvent(new Event("horasAlteradas"));
  }

  // ---------- desenho ----------
  function desenharContador() {
    const ativa = dados && dados.ativa;
    contador.className = "tp-contador" + (ativa ? "" : " parado");
    contador.innerHTML = ativa
      ? `<span class="tp-l1">Contando · ${escapar(ativa.tipo)} · ${escapar(ativa.empresa || "Sem empresa")}</span>` +
        `<div class="tp-l2"><span class="tp-relogio" data-relogio>${relogio(decorrido())}</span>` +
        `<button type="button" data-parar>■ Parar</button></div>` +
        (ativa.tarefa ? `<span class="tp-tarefa">${ativa.tarefa_id ? "▶ " : ""}${escapar(ativa.tarefa)}</span>` : "")
      : `<span class="tp-l1">Contador parado</span><span class="tp-tarefa">Use ▶ numa tarefa para contar o tempo dela.</span>`;
    const parar = contador.querySelector("[data-parar]");
    if (parar) parar.addEventListener("click", () => pararContador());
  }
  function atualizarPilula() {
    const n = dados ? dados.tarefas.length : 0;
    pilula.textContent = `Tarefas ${n}` + (dados && dados.ativa ? ` · ${relogio(decorrido()).slice(0, 5)}` : "");
  }
  function desenhar() {
    if (!dados) return;
    const empresaContador = dados.ativa && dados.ativa.empresa ? dados.ativa.empresa : "";
    // empresas no seletor; a do contador vem escolhida até o usuário mudar
    const atual = seletorEmpresa.dataset.mexido ? seletorEmpresa.value : empresaContador;
    seletorEmpresa.innerHTML = `<option value="">Sem empresa</option>` +
      dados.empresas.map(nome => `<option value="${escapar(nome)}">${escapar(nome)}</option>`).join("");
    seletorEmpresa.value = dados.empresas.includes(atual) ? atual : "";
    const opcoes = [["contando", empresaContador ? empresaContador + (dados.ativa ? " (contando)" : "") : "Empresa do contador"],
      ["todas", "Todas"], ["prazo", "Com prazo"]];
    filtros.innerHTML = opcoes.map(([chave, rotulo]) =>
      `<button type="button" data-filtro="${chave}" aria-pressed="${filtro === chave}">${escapar(rotulo)}</button>`).join("");
    const ativaId = dados.ativa ? dados.ativa.tarefa_id : null;
    let itens = dados.tarefas.filter(t => filtro === "todas" || (filtro === "prazo" ? t.prazo :
      !empresaContador || t.empresa === empresaContador));
    itens = itens.slice().sort((a, b) => (b.id === ativaId) - (a.id === ativaId));
    lista.innerHTML = itens.length ? itens.map(t => {
      const contando = t.id === ativaId, segundos = t.segundos + (contando ? decorrido() : 0);
      const faixa = ["vencida", "vencendo"].includes(t.faixa) ? t.faixa : "";
      const textoPrazo = !t.prazo ? "" : t.dias_restantes < 0 ? `${-t.dias_restantes} d de atraso` :
        t.dias_restantes === 0 ? "vence hoje" : `até ${dataCurta(t.prazo)}`;
      return `<li class="${contando ? "ativa" : ""}"><input type="checkbox" data-concluir="${t.id}" aria-label="Concluir: ${escapar(t.texto)}">` +
        `<span class="tp-texto">${escapar(t.texto)}</span>` +
        `<button type="button" class="tp-play" data-contar="${t.id}" aria-label="${contando ? "Parar o tempo de" : "Contar o tempo de"}: ${escapar(t.texto)}" ` +
        `title="${contando ? "Parar" : "Contar o tempo desta tarefa"}">${contando ? "■" : "▶"}</button>` +
        `<span class="tp-meta">${filtro !== "contando" || !empresaContador ? `<span>${escapar(t.empresa || "Sem empresa")}</span>` : ""}` +
        `${textoPrazo ? `<span class="${faixa}">${textoPrazo}</span>` : ""}${segundos ? `<span${contando ? " data-gasto" : ""}>${curto(segundos)} gastos</span>` : ""}</span></li>`;
    }).join("") : `<li class="tp-vazio">Nenhuma tarefa aberta${filtro === "contando" && empresaContador ? " da " + escapar(empresaContador) : ""}.</li>`;
    prazos.innerHTML = dados.prazos.length ? `<h3>Prazos de recurso</h3><ul class="tp-prazos">` + dados.prazos.map(p =>
      `<li><span class="${p.faixa}">${escapar(p.empresa)} ${p.competencia.slice(5, 7)}/${p.competencia.slice(0, 4)}` +
      `${p.referencia ? " · " + escapar(p.referencia) : ""}</span><b>${p.dias_restantes < 0 ? -p.dias_restantes + " d de atraso" : p.dias_restantes + " d"}</b></li>`).join("") +
      `</ul>${naJanela ? "" : `<a class="tp-ver" href="/pendencias/">Ver Pendências →</a>`}` : "";
    feitas.hidden = !dados.concluidas_hoje.length;
    feitas.querySelector("summary").textContent = `Concluídas hoje (${dados.concluidas_hoje.length})`;
    feitas.querySelector("ul").innerHTML = dados.concluidas_hoje.map(t =>
      `<li><s>${escapar(t.texto)}</s> · ${escapar(t.empresa || "Sem empresa")}</li>`).join("");
    desenharContador();
    atualizarPilula();
  }

  // ---------- servidor ----------
  async function atualizar() {
    try {
      const resposta = await fetch("/pendencias/tarefas");
      const resultado = await resposta.json();
      if (!resposta.ok) throw new Error(resultado.erro || "Não foi possível ler as tarefas.");
      dados = resultado;
      desenhar();
    } catch (erro) { avisar(erro.message); }
  }
  async function enviar(caminho, corpo) {
    const resposta = await fetch(caminho, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(corpo)});
    const resultado = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(resultado.erro || "Não foi possível salvar.");
    return resultado;
  }
  async function executar(acao) {
    if (ocupado) return;
    ocupado = true;
    try { await acao(); avisarMudanca(); } catch (erro) { avisar(erro.message); }
    finally { ocupado = false; await atualizar(); }
  }
  const pararContador = () => executar(async () => { await enviar("/horas/parar", {}); avisar("Contador parado."); });
  function contar(id) {
    if (dados.ativa && dados.ativa.tarefa_id === id) { pararContador(); return; }
    const tarefa = dados.tarefas.find(t => t.id === id);
    executar(async () => {
      await enviar("/horas/iniciar", {tarefa_id: id});
      avisar(`Contando “${tarefa ? tarefa.texto : "tarefa"}”.` + (dados.ativa ? " A sessão anterior foi encerrada." : ""));
    });
  }
  function concluir(id) {
    executar(async () => {
      const resultado = await enviar(`/pendencias/tarefa/${id}`, {concluida: true});
      avisar(resultado.contador === "voltou" ? "Tarefa concluída. O contador voltou para a atividade anterior."
        : resultado.contador === "parado" ? "Tarefa concluída e contador parado." : "Tarefa concluída.");
    });
  }
  formulario.addEventListener("submit", evento => {
    evento.preventDefault();
    if (!texto.value.trim()) return;
    executar(async () => {
      await enviar("/pendencias/tarefa", {texto: texto.value, empresa: seletorEmpresa.value || null, prazo: prazo.value || null});
      texto.value = ""; prazo.value = "";
      avisar("Tarefa criada.");
      texto.focus();
    });
  });
  seletorEmpresa.addEventListener("change", () => { seletorEmpresa.dataset.mexido = "1"; });
  filtros.addEventListener("click", evento => {
    const botao = evento.target.closest("[data-filtro]");
    if (!botao) return;
    filtro = botao.dataset.filtro; guardarLocal("tarefasFiltro", filtro); desenhar();
  });
  lista.addEventListener("click", evento => {
    const botao = evento.target.closest("[data-contar]");
    if (botao) contar(Number(botao.dataset.contar));
  });
  lista.addEventListener("change", evento => {
    const caixa = evento.target.closest("[data-concluir]");
    if (caixa) { caixa.disabled = true; concluir(Number(caixa.dataset.concluir)); }
  });

  // ---------- minimizar e arrastar (dentro do app) ----------
  function minimizar(sim, focar = true) {
    if (naJanela) return;
    painel.hidden = sim; pilula.hidden = !sim;
    pilula.setAttribute("aria-expanded", String(!sim));
    guardarLocal("tarefasMinimizado", sim ? "sim" : "nao");
    if (sim) { if (focar) pilula.focus(); } else { posicionar(); if (focar) texto.focus(); }
  }
  function posicionar() {
    if (naJanela || window.innerWidth <= 480) { painel.style.left = painel.style.top = ""; return; }
    try {
      const pos = JSON.parse(lembrarLocal("tarefasPosicao"));
      if (!pos) return;
      const x = Math.min(Math.max(0, pos[0]), window.innerWidth - painel.offsetWidth);
      const y = Math.min(Math.max(0, pos[1]), window.innerHeight - 60);
      Object.assign(painel.style, {left: x + "px", top: y + "px", right: "auto", bottom: "auto"});
    } catch (erro) { /* posição lembrada inválida: fica no canto */ }
  }
  let arraste = null;
  cabecalho.addEventListener("pointerdown", evento => {
    if (naJanela || evento.target.closest("button") || window.innerWidth <= 480) return;
    const caixa = painel.getBoundingClientRect();
    arraste = {dx: evento.clientX - caixa.left, dy: evento.clientY - caixa.top};
    cabecalho.setPointerCapture(evento.pointerId);
    cabecalho.classList.add("arrastando");
  });
  cabecalho.addEventListener("pointermove", evento => {
    if (!arraste) return;
    const x = Math.min(Math.max(0, evento.clientX - arraste.dx), window.innerWidth - painel.offsetWidth);
    const y = Math.min(Math.max(0, evento.clientY - arraste.dy), window.innerHeight - 60);
    Object.assign(painel.style, {left: x + "px", top: y + "px", right: "auto", bottom: "auto"});
  });
  cabecalho.addEventListener("pointerup", () => {
    if (!arraste) return;
    arraste = null; cabecalho.classList.remove("arrastando");
    guardarLocal("tarefasPosicao", JSON.stringify([parseInt(painel.style.left, 10), parseInt(painel.style.top, 10)]));
  });
  window.addEventListener("resize", posicionar);
  botaoMinimizar.addEventListener("click", () => minimizar(true));
  pilula.addEventListener("click", () => minimizar(false));
  painel.addEventListener("keydown", evento => { if (evento.key === "Escape" && !naJanela) minimizar(true); });

  // ---------- janela própria e janela por cima ----------
  // A janela por cima (Document PiP) fecha se a aba que a abriu navegar; por isso ela sai
  // da aba /tarefas/janela, que nunca navega. Da aba do app, "↗ Por cima" abre essa aba pequena.
  botaoPorCima.addEventListener("click", () => {
    const janela = window.open("/tarefas/janela", "tarefas", "popup,width=360,height=660");
    if (janela) { janela.focus(); minimizar(true, false); }
    else avisar("O navegador bloqueou a janela. Abra /tarefas/janela numa aba.");
  });
  if (naJanela) {
    painel.hidden = false;
    botaoManter.hidden = !temPip;
    if (!temPip) avisar("Este navegador não mantém janelas por cima. Deixe esta janela ao lado do prontuário.");
  }
  botaoManter.addEventListener("click", async () => {
    if (!temPip || janelaPip) return;
    try {
      janelaPip = await documentPictureInPicture.requestWindow({width: 340, height: 600});
    } catch (erro) { avisar("O Chrome não abriu a janela por cima: " + erro.message); janelaPip = null; return; }
    const doc = janelaPip.document;
    doc.title = "Tarefas";
    doc.documentElement.lang = "pt-BR";
    document.querySelectorAll("style").forEach(estilo => doc.head.append(estilo.cloneNode(true)));
    doc.body.className = "tarefas-janela tarefas-pip";
    botaoManter.hidden = true;
    doc.body.append(painel);
    const marcador = q("tarefasMarcador");
    if (marcador) marcador.hidden = false;
    janelaPip.addEventListener("pagehide", () => {
      document.body.append(painel);
      if (marcador) marcador.hidden = true;
      botaoManter.hidden = false;
      janelaPip = null;
    });
  });
  const trazer = q("tarefasTrazer");
  if (trazer) trazer.addEventListener("click", () => { if (janelaPip) janelaPip.close(); });

  // ---------- relógio e sincronização ----------
  setInterval(() => {
    if (!dados || !dados.ativa) return;
    const campo = contador.querySelector("[data-relogio]");
    if (campo) campo.textContent = relogio(decorrido());
    atualizarPilula();
  }, 1000);
  setInterval(atualizar, 60000);
  if (canal) canal.addEventListener("message", () => { atualizar(); window.dispatchEvent(new Event("horasAlteradas")); });
  window.addEventListener("focus", atualizar);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });

  if (!naJanela) minimizar(lembrarLocal("tarefasMinimizado") !== "nao", false);
  atualizar();
})();
