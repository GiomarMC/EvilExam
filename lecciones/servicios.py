"""Reglas del examen: horario, sorteo de preguntas y generación del análisis."""
import random
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import Configuracion, Evento, Horario, Pregunta


def esta_abierto(cfg=None, ahora=None):
    cfg = cfg or Configuracion.actual()
    if cfg.apertura == Configuracion.ABIERTO:
        return True
    if cfg.apertura == Configuracion.CERRADO:
        return False
    ahora = ahora or timezone.now()
    return Horario.objects.filter(activo=True, inicio__lte=ahora, fin__gte=ahora).exists()


def proxima_apertura(ahora=None):
    ahora = ahora or timezone.now()
    return Horario.objects.filter(activo=True, inicio__gt=ahora).order_by("inicio").first()


def sortear_preguntas(cfg):
    """Devuelve n preguntas activas al azar y sin repetir, o None si no alcanzan."""
    n = cfg.preguntas_por_examen
    activas = list(Pregunta.objects.filter(activa=True))
    if len(activas) < n:
        return None
    if not cfg.mezcla_por_categoria:
        return random.sample(activas, n)

    grupos = defaultdict(list)
    for p in activas:
        grupos[p.categoria].append(p)
    for lista in grupos.values():
        random.shuffle(lista)
    categorias = list(grupos)
    random.shuffle(categorias)
    elegidas = []
    while len(elegidas) < n:
        for cat in categorias:
            if grupos[cat] and len(elegidas) < n:
                elegidas.append(grupos[cat].pop())
    random.shuffle(elegidas)
    return elegidas


def _mmss(seg):
    seg = max(0, int(round(seg or 0)))
    return f"{seg // 60:02d}:{seg % 60:02d}"


def nombre_carpeta(sesion):
    fecha = timezone.localtime(sesion.inicio or sesion.ingreso)
    base = f"{sesion.nombre} - {sesion.correo} - {fecha:%Y-%m-%d %H-%M}"
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", base).strip()
    if sesion.intento > 1:
        base += f" (intento {sesion.intento})"
    return base


def ruta_carpeta(sesion):
    return Path(settings.MEDIA_ROOT) / sesion.carpeta


def generar_analisis(sesion, duracion):
    tipos = dict(Evento.TIPOS)
    fecha = timezone.localtime(sesion.inicio or sesion.ingreso)
    preguntas = list(sesion.preguntas.all())
    eventos = list(sesion.eventos.all())
    motivo = f" ({sesion.analisis_detalle})" if sesion.analisis_detalle else ""
    nota = f"{sesion.nota} / 20" if sesion.nota is not None else f"pendiente{motivo}"

    lineas = [
        "LECCIÓN ORAL - DISEÑO DE PATRONES",
        f"Alumno:   {sesion.nombre}",
        f"Correo:   {sesion.correo}",
        f"Fecha:    {fecha:%d/%m/%Y %H:%M}",
        f"Duración: {_mmss(duracion)}",
        "",
        f"NOTA APROXIMADA: {nota}",
        "",
        "DETALLE POR PREGUNTA",
    ]
    for sp in preguntas:
        puntaje = f"{sp.puntaje}/4" if sp.puntaje is not None else "-/4"
        lineas.append(
            f"[P{sp.orden}] {_mmss(sp.inicio_seg)} - {_mmss(sp.fin_seg)} | {sp.patron or 'Sin patrón'} | {puntaje}"
        )
        lineas.append(f"  Pregunta: {sp.texto}")
        lineas.append(f'  Transcripción: {chr(34) + sp.transcripcion + chr(34) if sp.transcripcion else "(sin voz detectada)"}')
        lineas.append(f"  Comentario: {sp.justificacion or '(pendiente)'}")
        lineas.append("")

    lineas.append(f"ALERTAS ({len(eventos)})")
    for ev in eventos:
        donde = f" (P{ev.pregunta_orden})" if ev.pregunta_orden else ""
        lineas.append(f"{_mmss(ev.inicio_seg)} - {_mmss(ev.fin_seg)}  {tipos.get(ev.tipo, ev.tipo)}{donde}")
    if not eventos:
        lineas.append("Sin alertas.")
    lineas += [
        "",
        "NOTA: Las alertas y la nota son orientativas. Revisar el video antes de tomar decisiones.",
        "",
    ]
    return "\n".join(lineas)
