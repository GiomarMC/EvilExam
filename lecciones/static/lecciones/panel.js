/* Panel de monitoreo: se actualiza solo cada pocos segundos. */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const CSRF = $('meta[name="csrf"]').content;
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const mmss = (s) => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };

  const E = { datos: null, filtro: "", busca: "", sel: new Set(), vistos: null, desfase: 0, abierta: null, firma: "" };

  // ---------- datos ----------
  async function cargar() {
    try {
      const r = await fetch("/panel/datos/", { headers: { Accept: "application/json" } });
      if (r.status === 401 || r.redirected) { location.reload(); return; }
      E.datos = await r.json();
      E.desfase = new Date(E.datos.ahora).getTime() - Date.now();
      $("#en-vivo").classList.remove("caido");
      $("#en-vivo").lastChild.textContent = "En vivo";
      pintar();
    } catch {
      $("#en-vivo").classList.add("caido");
      $("#en-vivo").lastChild.textContent = "Sin conexión";
    }
  }

  async function accion(cuerpo) {
    const r = await fetch("/panel/accion/", {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF }, body: JSON.stringify(cuerpo),
    });
    const j = await r.json().catch(() => ({}));
    aviso(j.mensaje || j.error || "No se pudo completar la acción.");
    await cargar();
    if (E.abierta) abrir(E.abierta, true);
  }

  let tAviso;
  function aviso(texto) {
    const t = $("#toast");
    t.textContent = texto;
    t.classList.add("ver");
    clearTimeout(tAviso);
    tAviso = setTimeout(() => t.classList.remove("ver"), 3200);
  }

  // ---------- pintado ----------
  function coincide(s) {
    const f = E.filtro;
    if (f === "problema" && !["interrumpido", "error_subida"].includes(s.estado)) return false;
    if (f === "alertas" && !s.alertas) return false;
    if (f && !["problema", "alertas"].includes(f) && s.estado !== f) return false;
    if (E.busca && !`${s.nombre} ${s.correo}`.toLowerCase().includes(E.busca)) return false;
    return true;
  }

  function avance(s) {
    if (s.estado !== "en_examen" || !s.inicio) return "";
    const t = (Date.now() + E.desfase - new Date(s.inicio).getTime()) / 1000;
    if (t > s.total_seg + 8) return `<span class="avance-txt">Terminó el tiempo · esperando el envío</span>`;
    const pct = Math.min(100, (t / s.total_seg) * 100);
    return `<span class="avance"><i style="width:${pct.toFixed(1)}%"></i></span><span class="avance-txt">${mmss(t)} / ${mmss(s.total_seg)}</span>`;
  }

  function celdaAnalisis(s) {
    if (s.estado !== "enviado") return `<span class="tenue">—</span>`;
    if (s.analisis === "procesando" || s.analisis === "pendiente") return `<span class="tenue"><i class="girando"></i>${esc(s.analisis_txt)}</span>`;
    return `<span class="tenue">${esc(s.analisis_txt)}</span>`;
  }

  function fila(s) {
    const nueva = E.vistos && !E.vistos.has(s.id) ? " nueva" : "";
    const nivel = s.alertas >= 5 ? " muchas" : s.alertas ? " hay" : "";
    return `<tr data-id="${s.id}" class="${E.sel.has(s.id) ? "sel" : ""}${nueva}">
      <td class="check"><input type="checkbox" ${E.sel.has(s.id) ? "checked" : ""} aria-label="Seleccionar"></td>
      <td class="alumno"><strong>${esc(s.nombre)}${s.intento > 1 ? `<span class="etiqueta-mini">intento ${s.intento}</span>` : ""}${s.rehabilitada ? `<span class="etiqueta-mini">reintento habilitado</span>` : ""}</strong><small>${esc(s.correo)}</small></td>
      <td class="tenue">${esc(s.ingreso)}</td>
      <td><span class="estado ${s.estado}">${esc(s.estado_txt)}</span>${avance(s)}</td>
      <td><span class="alertas${nivel}">${s.alertas}</span></td>
      <td>${s.nota === null ? `<span class="tenue">—</span>` : `<span class="nota">${s.nota}<small> / 20</small></span>`}</td>
      <td>${celdaAnalisis(s)}</td>
    </tr>`;
  }

  function pintar() {
    const d = E.datos;
    if (!d) return;

    // apertura
    const ap = $("#apertura");
    ap.dataset.abierto = d.abierto ? "si" : "no";
    $("#apertura-titulo").textContent = d.abierto ? "La lección está abierta" : "La lección está cerrada";
    const faltan = d.preguntas_activas < d.preguntas_por_examen;
    $("#apertura-detalle").textContent = faltan
      ? `Atención: solo hay ${d.preguntas_activas} preguntas activas y el examen pide ${d.preguntas_por_examen}.`
      : d.abierto ? `${d.preguntas_activas} preguntas activas en el banco.`
      : d.proxima ? `Próxima apertura: ${d.proxima}.` : "Sin próxima apertura programada.";
    $$("#apertura .segmentos button").forEach((b) => b.classList.toggle("on", b.dataset.valor === d.apertura));

    // contadores
    for (const b of $$("#contadores [data-k]")) {
      const v = d.contadores[b.dataset.k];
      b.textContent = b.dataset.k === "promedio" ? (v === null ? "—" : v.toFixed(1)) : v;
    }
    $(".dato.vivo").classList.toggle("activo", d.contadores.en_examen > 0);
    $$("#contadores [data-filtro], #chips button").forEach((b) => b.classList.toggle("on", b.dataset.filtro === E.filtro));

    // filas
    const visibles = d.sesiones.filter(coincide);
    $("#filas").innerHTML = visibles.map(fila).join("");
    $("#vacio").hidden = visibles.length > 0;
    E.vistos = new Set(d.sesiones.map((s) => s.id));
    for (const id of [...E.sel]) if (!E.vistos.has(id)) E.sel.delete(id);
    $("#todos").checked = visibles.length > 0 && visibles.every((s) => E.sel.has(s.id));
    $("#n-sel").textContent = `${E.sel.size} seleccionado${E.sel.size === 1 ? "" : "s"}`;
    $("#acciones").classList.toggle("ver", E.sel.size > 0);

    // si la sesión abierta cambió (por ejemplo terminó el análisis), se refresca el detalle
    if (E.abierta) {
      const s = d.sesiones.find((x) => x.id === E.abierta);
      const firma = s ? `${s.estado}|${s.analisis}|${s.nota}|${s.alertas}|${s.rehabilitada}` : "";
      if (firma !== E.firma) abrir(E.abierta, true);
    }
  }

  // ---------- detalle ----------
  const claseMarca = (tipo) => (tipo === "habla_lectura" || tipo === "repite_pregunta" ? "voz" : tipo === "mirada_abajo" ? "" : "rostro");

  async function abrir(id, silencioso) {
    E.abierta = id;
    const s = E.datos?.sesiones.find((x) => x.id === id);
    E.firma = s ? `${s.estado}|${s.analisis}|${s.nota}|${s.alertas}|${s.rehabilitada}` : "";
    const caja = $("#cajon-contenido");
    const previo = $("video", caja);
    const pos = silencioso && previo ? previo.currentTime : 0;
    if (!silencioso) caja.innerHTML = `<p class="sub">Cargando…</p>`;
    $("#cajon").classList.add("ver");
    $("#velo").classList.add("ver");
    $("#cajon").setAttribute("aria-hidden", "false");

    let d;
    try { d = await (await fetch(`/panel/sesion/${id}/`)).json(); }
    catch { caja.innerHTML = `<p class="sub">No se pudo cargar el detalle.</p>`; return; }
    if (E.abierta !== id) return;

    const bloque = d.lectura + d.respuesta;
    const total = d.total_seg || 1;
    const linea = d.preguntas.length ? `
      <div class="linea" id="linea">
        ${d.preguntas.map((p) => `<div class="tramo" style="width:${(bloque / total) * 100}%">
          <div class="lect" style="width:${(d.lectura / bloque) * 100}%"></div><div class="resp" style="width:${(d.respuesta / bloque) * 100}%">P${p.orden}</div></div>`).join("")}
        ${d.eventos.map((e) => `<div class="marca ${claseMarca(e.tipo)}" data-t="${e.inicio}" title="${esc(e.etiqueta)} · ${mmss(e.inicio)}"
          style="left:${(e.inicio / total) * 100}%;width:${(Math.max(0, e.fin - e.inicio) / total) * 100}%"></div>`).join("")}
        <div class="cursor" id="cursor"></div>
      </div>
      <div class="leyenda"><span><i></i>Mirada</span><span><i class="voz"></i>Voz</span><span><i class="rostro"></i>Rostro</span><span>Franja clara: lectura · oscura: respuesta</span></div>` : "";

    caja.innerHTML = `
      <h2>${esc(d.nombre)}</h2>
      <p class="sub">${esc(d.correo)} · ingresó el ${esc(d.ingreso)}${d.intento > 1 ? ` · intento ${d.intento}` : ""}</p>
      <div class="resumen">
        <span class="estado ${d.estado}">${esc(d.estado_txt)}</span>
        <span class="alertas${d.eventos.length >= 5 ? " muchas" : d.eventos.length ? " hay" : ""}">${d.eventos.length} alerta${d.eventos.length === 1 ? "" : "s"}</span>
        ${d.nota !== null ? `<span class="gran-nota">${d.nota}<small> / 20</small></span>` : ""}
      </div>
      ${d.estado === "enviado" && d.analisis !== "listo" ? `<p class="aviso-linea">${d.analisis === "procesando" || d.analisis === "pendiente" ? `<i class="girando"></i>` : ""}Análisis: ${esc(d.analisis_txt)}${d.analisis_detalle ? ` — ${esc(d.analisis_detalle)}` : ""}</p>` : ""}
      ${d.video ? `<video id="video" src="${d.video}" controls preload="metadata"></video>` : ""}
      ${linea}
      ${d.eventos.length ? `<h3>Alertas</h3><ul class="eventos">${d.eventos.map((e) => `<li>
        <button data-t="${e.inicio}">${mmss(e.inicio)}</button>${esc(e.etiqueta)}<small>${e.pregunta ? `P${e.pregunta} · ` : ""}${Math.max(0, e.fin - e.inicio).toFixed(0)} s</small></li>`).join("")}</ul>` : ""}
      ${d.preguntas.length ? `<h3>Preguntas</h3>${d.preguntas.map((p) => `<article class="preg">
        <header><b>P${p.orden}</b><span>${esc(p.patron)}</span>
          ${d.video ? `<button data-t="${(p.orden - 1) * bloque + d.lectura}">▶ Oír respuesta</button>` : ""}
          <span class="puntaje ${p.puntaje === null ? "nd" : p.puntaje <= 1 ? "bajo" : ""}" ${d.video ? "" : 'style="margin-left:auto"'}>${p.puntaje === null ? "–" : p.puntaje} / 4</span></header>
        <p class="texto">${esc(p.texto)}</p>
        ${p.transcripcion ? `<p class="trans">“${esc(p.transcripcion)}”</p>` : d.estado === "enviado" && d.analisis !== "pendiente" && d.analisis !== "procesando" ? `<p class="trans">Sin voz detectada.</p>` : ""}
        ${p.justificacion ? `<p class="coment">${esc(p.justificacion)}</p>` : ""}
      </article>`).join("")}` : ""}
      <div class="botones">
        ${d.analisis_url ? `<a href="${d.analisis_url}" target="_blank" rel="noopener">Ver analisis.txt</a>` : ""}
        ${d.estado === "enviado" ? `<button data-accion="reprocesar">Reprocesar análisis</button>` : ""}
        ${d.estado !== "ingreso" && !d.rehabilitada ? `<button data-accion="habilitar">Habilitar nuevo intento</button>` : ""}
      </div>`;

    const video = $("#video", caja);
    if (video) {
      if (pos) video.addEventListener("loadedmetadata", () => { video.currentTime = pos; }, { once: true });
      video.addEventListener("timeupdate", () => { const c = $("#cursor"); if (c) c.style.left = `${Math.min(100, (video.currentTime / total) * 100)}%`; });
    }
  }

  function cerrar() {
    E.abierta = null;
    $("#cajon").classList.remove("ver");
    $("#velo").classList.remove("ver");
    $("#cajon").setAttribute("aria-hidden", "true");
    $("#cajon-contenido video")?.pause();
  }

  function saltar(t) {
    const v = $("#video");
    if (!v) return;
    v.currentTime = Math.max(0, t - 1);
    v.play().catch(() => {});
  }

  // ---------- eventos ----------
  $("#filas").addEventListener("click", (e) => {
    const tr = e.target.closest("tr");
    if (!tr) return;
    const id = +tr.dataset.id;
    if (e.target.closest(".check")) {
      E.sel.has(id) ? E.sel.delete(id) : E.sel.add(id);
      pintar();
    } else abrir(id);
  });
  $("#todos").addEventListener("change", (e) => {
    const visibles = E.datos.sesiones.filter(coincide);
    visibles.forEach((s) => (e.target.checked ? E.sel.add(s.id) : E.sel.delete(s.id)));
    pintar();
  });
  $("#buscar").addEventListener("input", (e) => { E.busca = e.target.value.trim().toLowerCase(); pintar(); });
  document.addEventListener("click", (e) => {
    const f = e.target.closest("#chips button, #contadores button[data-filtro]");
    if (f) { E.filtro = E.filtro === f.dataset.filtro && f.closest("#contadores") ? "" : f.dataset.filtro; pintar(); }
  });
  $("#apertura .segmentos").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && !b.classList.contains("on")) accion({ accion: "apertura", valor: b.dataset.valor });
  });
  $("#acciones").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    accion({ accion: b.dataset.accion, ids: [...E.sel] });
    E.sel.clear();
  });
  $("#cajon").addEventListener("click", (e) => {
    const t = e.target.closest("[data-t]");
    if (t) { saltar(+t.dataset.t); return; }
    const linea = e.target.closest("#linea");
    if (linea) { const r = linea.getBoundingClientRect(); const v = $("#video"); if (v && v.duration) saltar(((e.clientX - r.left) / r.width) * v.duration + 1); return; }
    const a = e.target.closest("[data-accion]");
    if (a) accion({ accion: a.dataset.accion, ids: [E.abierta] });
  });
  $("#cerrar").addEventListener("click", cerrar);
  $("#velo").addEventListener("click", cerrar);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrar(); });

  cargar();
  setInterval(cargar, 4000);
  setInterval(() => { if (E.datos?.contadores.en_examen) pintar(); }, 1000);  // avanza las barras de progreso
})();
