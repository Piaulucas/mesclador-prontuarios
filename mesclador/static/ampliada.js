// Folha ampliada com os ajustes ao lado (telas Mesclar prontuário e Converter em JPG).
// Os ajustes valem para a página INTEIRA (brilho, contraste, realce e giro); nada altera o que está escrito.
//
// criarAmpliacao(opcoes) devolve { abrir(id), atualizar(), fechar(), aberta() }.
// opcoes:
//   lista()            itens na ordem da tela: {id, nome, giro, brilho, contraste, realce}
//   url(item, neutro)  endereço da prévia grande (neutro = sem ajustes)
//   titulo(item, i, n) texto do cabeçalho do painel (ex.: "Folha 2 de 5")
//   detalhe(item)      texto abaixo do título (nome do arquivo, tipo)
//   aoAjustar(item)    chamado quando brilho, contraste ou realce mudam
//   aoGirar(item)      chamado quando a folha gira
function criarAmpliacao(opcoes) {
  const el = id => document.getElementById(id);
  const caixa = el("ampliada"), area = el("ampliadaFolha");
  const base = el("imgBase"), exata = el("imgAmpliada");
  const controles = { brilho: el("ampBrilho"), contraste: el("ampContraste"), realce: el("ampRealce") };
  let atualId = null, timer = null, pedido = 0, quemAbriu = null;

  const atual = () => opcoes.lista().find(x => x.id === atualId);
  const ajustada = it => it.brilho !== 0 || it.contraste !== 0 || it.realce;

  // aproximação instantânea enquanto o servidor prepara a prévia exata
  function filtro(it) {
    const partes = [];
    if (it.realce) partes.push("grayscale(1) contrast(1.4)");
    if (it.brilho) partes.push(`brightness(${1 + it.brilho / 100})`);
    if (it.contraste) partes.push(`contrast(${1 + it.contraste / 100})`);
    return partes.length ? partes.join(" ") : "none";
  }

  // cabe a imagem (girada ou não) na área, sem cortar
  function encaixar() {
    const it = atual();
    if (!it) return;
    const largura = area.clientWidth - 8, altura = area.clientHeight - 8;
    const deitada = it.giro % 180 !== 0;
    [base, exata].forEach(img => {
      if (!img.naturalWidth) return;
      const w = deitada ? img.naturalHeight : img.naturalWidth;
      const h = deitada ? img.naturalWidth : img.naturalHeight;
      const escala = Math.min(largura / w, altura / h);
      img.style.width = `${img.naturalWidth * escala}px`;
      img.style.height = `${img.naturalHeight * escala}px`;
      img.style.transform = `translate(-50%, -50%) rotate(${it.giro}deg)`;
    });
  }
  base.addEventListener("load", encaixar);
  window.addEventListener("resize", encaixar);

  function mostrarBase(it) {   // folha sem ajuste do servidor + filtro do navegador
    base.style.filter = filtro(it);
    base.classList.remove("oculta");
    exata.classList.add("oculta");
  }
  function carregarExata(it) {
    if (!ajustada(it)) { el("ampliadaCarregando").hidden = true; return; }
    const numero = ++pedido;
    const endereco = opcoes.url(it, false);
    el("ampliadaCarregando").hidden = false;
    exata.onload = () => {
      if (numero !== pedido) return;
      el("ampliadaCarregando").hidden = true;
      encaixar();
      exata.classList.remove("oculta");
      base.classList.add("oculta");
    };
    exata.onerror = () => { if (numero === pedido) el("ampliadaCarregando").hidden = true; };
    exata.src = endereco;
  }
  function mostrarFolha(it) {
    const endereco = opcoes.url(it, true);
    if (base.dataset.endereco !== endereco) { base.dataset.endereco = endereco; base.src = endereco; }
    mostrarBase(it);
    clearTimeout(timer);
    carregarExata(it);
    encaixar();
  }

  function carregarControles(it) {
    controles.brilho.value = it.brilho;
    controles.contraste.value = it.contraste;
    controles.realce.checked = it.realce;
    el("ampVBrilho").textContent = it.brilho;
    el("ampVContraste").textContent = it.contraste;
  }

  function atualizar() {   // a lista mudou (giro, remoção, ordem): redesenha o que está aberto
    if (!atualId) return;
    const lista = opcoes.lista();
    const indice = lista.findIndex(x => x.id === atualId);
    if (indice < 0) { fechar(); return; }
    const it = lista[indice];
    el("ampliadaTitulo").textContent = opcoes.titulo(it, indice, lista.length);
    el("ampliadaNome").textContent = opcoes.detalhe(it);
    el("ampliadaPosicao").textContent = `${indice + 1}/${lista.length} · ${it.nome}`;
    el("ampliadaAnterior").hidden = indice === 0;
    el("ampliadaProximo").hidden = indice === lista.length - 1;
    carregarControles(it);
    if (base.dataset.id !== it.id) { base.dataset.id = it.id; mostrarFolha(it); }
    else encaixar();
  }

  function abrir(id) {
    quemAbriu = document.activeElement;
    atualId = id;
    base.dataset.id = "";
    caixa.hidden = false;
    document.body.style.overflow = "hidden";
    atualizar();
    el("ampliadaFechar").focus();
  }
  function fechar() {
    atualId = null; pedido++; clearTimeout(timer);
    caixa.hidden = true;
    document.body.style.overflow = "";
    if (quemAbriu && document.contains(quemAbriu)) quemAbriu.focus();
  }
  function mover(direcao) {
    const lista = opcoes.lista();
    const indice = lista.findIndex(x => x.id === atualId);
    if (indice < 0 || indice + direcao < 0 || indice + direcao >= lista.length) return;
    atualId = lista[indice + direcao].id;
    atualizar();
  }

  function aoMexer() {
    const it = atual();
    if (!it) return;
    it.brilho = +controles.brilho.value;
    it.contraste = +controles.contraste.value;
    it.realce = controles.realce.checked;
    el("ampVBrilho").textContent = it.brilho;
    el("ampVContraste").textContent = it.contraste;
    pedido++;
    mostrarBase(it);
    el("ampliadaCarregando").hidden = true;
    clearTimeout(timer);   // espera parar de arrastar para não pedir a prévia a cada pixel
    timer = setTimeout(() => { carregarExata(it); opcoes.aoAjustar(it); }, 250);
  }
  controles.brilho.addEventListener("input", aoMexer);
  controles.contraste.addEventListener("input", aoMexer);
  controles.realce.addEventListener("change", aoMexer);

  el("ampGirar").onclick = () => {
    const it = atual();
    if (!it) return;
    it.giro = (it.giro + 90) % 360;
    opcoes.aoGirar(it);
    encaixar();
  };
  el("ampRestaurar").onclick = () => {
    const it = atual();
    if (!it) return;
    Object.assign(it, { brilho: 0, contraste: 0, realce: false });
    carregarControles(it);
    aoMexer();
  };
  el("ampAplicarTodas").onclick = () => {
    const origem = atual();
    if (!origem) return;
    opcoes.lista().forEach(it => {
      if (it === origem) return;
      Object.assign(it, { brilho: origem.brilho, contraste: origem.contraste, realce: origem.realce });
      opcoes.aoAjustar(it);
    });
    opcoes.aoAjustar(origem);
  };

  el("ampliadaFechar").onclick = fechar;
  el("ampliadaAnterior").onclick = () => mover(-1);
  el("ampliadaProximo").onclick = () => mover(1);
  caixa.addEventListener("click", e => { if (e.target === caixa || e.target === area) fechar(); });
  document.addEventListener("keydown", e => {
    if (caixa.hidden) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); fechar(); return; }
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.target.matches && e.target.matches("input[type=range]")) return;   // as setas mexem no controle
    e.preventDefault(); e.stopPropagation();
    mover(e.key === "ArrowLeft" ? -1 : 1);
  }, true);

  return { abrir, atualizar, fechar, aberta: () => !caixa.hidden };
}
