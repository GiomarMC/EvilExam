/* Lección oral: flujo del alumno, grabación y detección en el navegador. */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const CSRF = $('meta[name="csrf"]').content;
  const MP = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
  const MODELO = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

  const S = {
    token: null, stream: null, landmarker: null, sinDeteccion: false,
    audioCtx: null, analizador: null, bufAudio: null, ruido: 0.01, ultimaVoz: -1e9,
    base: null, muestras: [], lienzo: null,
    lectura: 15, respuesta: 20, umbral: 2, preguntas: [],
    grabadora: null, trozos: [], t0: null, enExamen: false, subiendo: false, enviado: false,
    eventos: [], rastreadores: null, idx: -1, fase: null, blob: null, duracion: 0, bucle: null,
  };

  // ---------- utilidades ----------
  function ir(nombre) {
    document.querySelectorAll(".stage").forEach((s) => s.classList.toggle("on", s.dataset.stage === nombre));
    document.body.dataset.stage = nombre;
  }

  function error(id, texto) {
    const el = $(id);
    el.textContent = texto || "";
    el.classList.toggle("ver", !!texto);
  }

  async function api(url, datos) {
    let r;
    try {
      r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
        body: JSON.stringify(datos),
      });
    } catch {
      throw new Error("No hay conexión con el servidor. Inténtalo de nuevo.");
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) throw new Error(j.error || "Ocurrió un error. Inténtalo de nuevo.");
    return j;
  }

  async function conBoton(boton, tarea) {
    boton.disabled = true;
    try { await tarea(); } finally { boton.disabled = false; }
  }

  // ---------- 1. ingreso ----------
  $("#form-ingreso").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    error("#error-ingreso", "");
    if (!f.reportValidity()) return;
    conBoton(f.querySelector("button"), async () => {
      try {
        const r = await api("/api/ingreso/", { nombre: f.nombre.value, correo: f.correo.value });
        S.token = r.token;
        ir("permisos");
      } catch (err) { error("#error-ingreso", err.message); }
    });
  });

  // ---------- 2. permisos ----------
  $("#btn-permisos").addEventListener("click", (e) => conBoton(e.currentTarget, async () => {
    error("#error-permisos", "");
    try {
      S.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 854 }, height: { ideal: 480 }, frameRate: { ideal: 24 }, facingMode: "user" },
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      error("#error-permisos", "No se pudo acceder a la cámara o al micrófono. Revisa los permisos del navegador e inténtalo de nuevo.");
      return;
    }
    $("#preview").srcObject = S.stream;
    $("#camara").srcObject = S.stream;

    S.audioCtx = new AudioContext();
    S.analizador = S.audioCtx.createAnalyser();
    S.analizador.fftSize = 1024;
    S.audioCtx.createMediaStreamSource(S.stream).connect(S.analizador);
    S.bufAudio = new Float32Array(S.analizador.fftSize);

    ir("chequeo");
    cargarDeteccion();
    S.bucle = setInterval(tic, 110);
  }));

  async function cargarDeteccion() {
    try {
      const vision = await import(`${MP}/vision_bundle.mjs`);
      const archivos = await vision.FilesetResolver.forVisionTasks(`${MP}/wasm`);
      S.landmarker = await vision.FaceLandmarker.createFromOptions(archivos, {
        baseOptions: { modelAssetPath: MODELO, delegate: "GPU" },
        runningMode: "VIDEO", numFaces: 2, outputFaceBlendshapes: true,
      });
    } catch (err) {
      console.warn("Detección facial no disponible:", err);
      S.sinDeteccion = true;
    }
  }

  // ---------- medición por cuadro ----------
  function volumen() {
    S.analizador.getFloatTimeDomainData(S.bufAudio);
    let suma = 0;
    for (const v of S.bufAudio) suma += v * v;
    return Math.sqrt(suma / S.bufAudio.length);
  }

  function brillo(video) {
    if (!S.lienzo) { S.lienzo = document.createElement("canvas"); S.lienzo.width = 48; S.lienzo.height = 36; }
    const ctx = S.lienzo.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, 48, 36);
    const px = ctx.getImageData(0, 0, 48, 36).data;
    let suma = 0;
    for (let i = 0; i < px.length; i += 4) suma += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    return suma / (px.length / 4);
  }

  /** Devuelve {n, r, ojos, cx, cy, alto}: r crece cuando la cabeza se inclina hacia abajo. */
  function rostro(video) {
    if (!S.landmarker || video.readyState < 2) return null;
    let res;
    try { res = S.landmarker.detectForVideo(video, performance.now()); } catch { return null; }
    const n = res.faceLandmarks.length;
    if (n !== 1) return { n };
    const lm = res.faceLandmarks[0];
    const frente = lm[10], menton = lm[152], nariz = lm[1];
    const alto = menton.y - frente.y;
    let ojos = 0;
    for (const c of res.faceBlendshapes?.[0]?.categories || []) {
      if (c.categoryName === "eyeLookDownLeft" || c.categoryName === "eyeLookDownRight") ojos += c.score / 2;
    }
    return { n, r: (nariz.y - frente.y) / alto, ojos, cx: nariz.x, cy: (frente.y + menton.y) / 2, alto };
  }

  function tic() {
    const video = $("#camara");
    const cara = rostro(video);
    const vol = volumen();
    if (S.enExamen) ticExamen(cara, vol);
    else if (document.body.dataset.stage === "chequeo") ticChequeo(video, cara, vol);
  }

  // ---------- 3. chequeo ----------
  function marcar(clave, ok) {
    $(`#lista-chequeo [data-k="${clave}"]`).classList.toggle("ok", !!ok);
  }

  function ticChequeo(video, cara, vol) {
    S.ruido = S.ruido * 0.95 + Math.min(vol, 0.05) * 0.05;
    const micOk = S.stream.getAudioTracks().some((t) => t.readyState === "live" && !t.muted);
    const b = video.readyState >= 2 ? brillo(video) : 0;
    const luzOk = b > 55 && b < 225;
    marcar("mic", micOk);
    marcar("luz", luzOk);

    const nota = $("#nota-chequeo");
    if (S.sinDeteccion) {
      // Sin MediaPipe (por ejemplo, sin internet) se permite continuar y se deja constancia.
      marcar("rostro", false); marcar("encuadre", false);
      nota.textContent = "No se pudo cargar la detección facial. Puedes continuar; quedará registrado.";
      $("#btn-chequeo").disabled = !(micOk && luzOk);
      return;
    }
    if (!S.landmarker) { nota.textContent = "Preparando la detección…"; return; }

    const hay = cara && cara.n === 1;
    const encuadreOk = hay && Math.abs(cara.cx - 0.5) < 0.2 && cara.cy > 0.25 && cara.cy < 0.75 && cara.alto > 0.22 && cara.alto < 0.8;
    marcar("rostro", hay);
    marcar("encuadre", encuadreOk);

    if (hay && encuadreOk && luzOk) S.muestras.push(cara); else S.muestras = [];
    if (S.muestras.length > 18) S.muestras.shift();
    const listo = S.muestras.length >= 18 && micOk;
    if (listo) {
      const media = (k) => S.muestras.reduce((a, m) => a + m[k], 0) / S.muestras.length;
      S.base = { r: media("r"), ojos: media("ojos") };
    }
    $("#btn-chequeo").disabled = !listo;
    nota.textContent = listo ? "Todo listo." :
      !cara || cara.n === 0 ? "No vemos tu rostro." :
      cara.n > 1 ? "Debe haber una sola persona frente a la cámara." :
      !luzOk ? "Mejora la iluminación de tu rostro." :
      !encuadreOk ? "Centra tu rostro en el recuadro." : "Mantén la mirada en la pantalla…";
  }

  $("#btn-chequeo").addEventListener("click", () => ir("aviso"));

  // ---------- 4 y 5. examen ----------
  $("#btn-empezar").addEventListener("click", (e) => conBoton(e.currentTarget, async () => {
    error("#error-aviso", "");
    let r;
    try { r = await api("/api/iniciar/", { token: S.token }); }
    catch (err) { error("#error-aviso", err.message); return; }
    Object.assign(S, { lectura: r.lectura, respuesta: r.respuesta, umbral: r.umbral, preguntas: r.preguntas });
    empezar();
  }));

  function rastreador(tipo, minimo) {
    let ini = null;
    return (activo, t) => {
      if (activo) { if (ini === null) ini = t; return; }
      if (ini !== null && t - ini >= minimo) {
        S.eventos.push({
          tipo, inicio: +ini.toFixed(1), fin: +t.toFixed(1),
          pregunta: Math.min(S.preguntas.length, Math.floor(ini / (S.lectura + S.respuesta)) + 1),
        });
      }
      ini = null;
    };
  }

  function empezar() {
    const tipo = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m));
    S.grabadora = new MediaRecorder(S.stream, { mimeType: tipo, videoBitsPerSecond: 420000, audioBitsPerSecond: 48000 });
    S.grabadora.ondataavailable = (e) => e.data.size && S.trozos.push(e.data);
    S.grabadora.onstart = () => {
      S.t0 = performance.now();
      S.enExamen = true;
      if (S.sinDeteccion) S.eventos.push({ tipo: "sin_deteccion", inicio: 0, fin: 0, pregunta: null });
    };
    S.rastreadores = {
      abajo: rastreador("mirada_abajo", S.umbral),
      sinRostro: rastreador("sin_rostro", 1),
      varios: rastreador("varios_rostros", 1),
      habla: rastreador("habla_lectura", 1.2),
    };
    $("#puntos").innerHTML = S.preguntas.map(() => "<i></i>").join("");
    pintar(0, "lectura", S.lectura, 1);
    ir("examen");
    S.grabadora.start(1000);
  }

  function pintar(idx, fase, resta, fraccion) {
    if (idx !== S.idx) {
      const p = $("#pregunta");
      const texto = S.preguntas[idx].texto;
      if (S.idx < 0) p.textContent = texto;
      else {
        p.classList.add("cambia");
        setTimeout(() => { p.textContent = texto; p.classList.remove("cambia"); }, 420);
      }
      $("#progreso-texto").textContent = `Pregunta ${idx + 1} de ${S.preguntas.length}`;
      document.querySelectorAll("#puntos i").forEach((el, i) => {
        el.className = i < idx ? "hecha" : i === idx ? "actual" : "";
      });
      S.idx = idx;
    }
    if (fase !== S.fase) {
      $("#examen").dataset.fase = fase;
      document.body.dataset.fase = fase;
      $("#chip").textContent = fase === "lectura" ? "Lectura en silencio" : "Respuesta oral";
      $("#instruccion").textContent = fase === "lectura" ? "Lee la pregunta en silencio." : "Responde en voz alta.";
      S.fase = fase;
    }
    $("#contador").textContent = Math.max(0, Math.ceil(resta));
    $("#arco").style.strokeDashoffset = (339.3 * (1 - fraccion)).toFixed(1);
  }

  function ticExamen(cara, vol) {
    const t = (performance.now() - S.t0) / 1000;
    const bloque = S.lectura + S.respuesta;
    const total = bloque * S.preguntas.length;
    if (t >= total) { terminar(total); return; }

    const idx = Math.floor(t / bloque);
    const enBloque = t - idx * bloque;
    const fase = enBloque < S.lectura ? "lectura" : "respuesta";
    const dur = fase === "lectura" ? S.lectura : S.respuesta;
    const resta = fase === "lectura" ? S.lectura - enBloque : bloque - enBloque;
    pintar(idx, fase, resta, resta / dur);

    // Voz: por encima del ruido de fondo, con una pequeña cola para no cortar entre sílabas.
    if (vol > Math.max(S.ruido * 3.5, 0.025)) S.ultimaVoz = t;
    S.rastreadores.habla(fase === "lectura" && t - S.ultimaVoz < 0.4, t);

    if (S.landmarker && cara) {
      S.rastreadores.sinRostro(cara.n === 0, t);
      S.rastreadores.varios(cara.n > 1, t);
      const abajo = cara.n === 1 && S.base && (cara.r - S.base.r > 0.07 || cara.ojos - S.base.ojos > 0.3);
      S.rastreadores.abajo(!!abajo, t);
    }
  }

  function terminar(total) {
    S.enExamen = false;
    clearInterval(S.bucle);
    Object.values(S.rastreadores).forEach((r) => r(false, total));
    S.duracion = total;
    S.subiendo = true;
    delete document.body.dataset.fase;
    ir("subida");
    S.grabadora.onstop = () => {
      S.blob = new Blob(S.trozos, { type: "video/webm" });
      S.stream.getTracks().forEach((p) => p.stop());
      S.audioCtx.close();
      subir(1);
    };
    S.grabadora.stop();
  }

  // ---------- 6. subida ----------
  function subir(intento) {
    const cuerpo = new FormData();
    cuerpo.append("token", S.token);
    cuerpo.append("datos", JSON.stringify({ duracion: S.duracion, eventos: S.eventos }));
    cuerpo.append("video", S.blob, "video.webm");

    $("#btn-reintentar").hidden = true;
    $("#texto-subida").textContent = intento > 1 ? `Reintentando el envío (${intento} de 3)…` : "No cierres esta pestaña.";

    const x = new XMLHttpRequest();
    x.open("POST", "/api/enviar/");
    x.setRequestHeader("X-CSRFToken", CSRF);
    x.upload.onprogress = (e) => { if (e.lengthComputable) $("#barra-subida").style.width = `${(e.loaded / e.total) * 100}%`; };
    const fallo = () => {
      if (intento < 3) { setTimeout(() => subir(intento + 1), 2000 * intento); return; }
      $("#texto-subida").textContent = "No se pudo enviar el video. Revisa tu conexión y vuelve a intentarlo sin cerrar la pestaña.";
      $("#btn-reintentar").hidden = false;
    };
    x.onerror = fallo;
    x.onload = () => {
      let j = {};
      try { j = JSON.parse(x.responseText); } catch { /* respuesta no JSON */ }
      if (x.status !== 200 || !j.ok) { fallo(); return; }
      S.enviado = true;
      S.subiendo = false;
      if (j.nota !== null && j.nota !== undefined) $("#texto-fin").textContent = `Nota aproximada: ${j.nota} / 20. Ya puedes cerrar esta pestaña.`;
      ir("fin");
    };
    x.send(cuerpo);
  }

  $("#btn-reintentar").addEventListener("click", () => subir(1));

  // ---------- cierre o recarga ----------
  window.addEventListener("beforeunload", (e) => {
    if (S.enExamen || S.subiendo) e.preventDefault();
  });
  window.addEventListener("pagehide", () => {
    if (S.enviado || !(S.enExamen || S.subiendo)) return;
    const cuerpo = new FormData();
    cuerpo.append("token", S.token);
    cuerpo.append("fase", S.subiendo ? "subida" : "examen");
    cuerpo.append("eventos", JSON.stringify(S.eventos));
    navigator.sendBeacon("/api/interrumpir/", cuerpo);
  });
})();
