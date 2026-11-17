"""Panel de monitoreo en vivo para el docente."""
import json

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_GET, require_POST

from . import analisis, servicios
from .models import Configuracion, Evento, Pregunta, Sesion


def _total_seg(sesion, cfg):
    c = sesion.config or {}
    n = len(sesion.preguntas.all()) or cfg.preguntas_por_examen
    return n * (c.get("lectura", cfg.segundos_lectura) + c.get("respuesta", cfg.segundos_respuesta))


@staff_member_required
@require_GET
def panel(request):
    return render(request, "lecciones/panel.html")


@staff_member_required
@require_GET
def datos(request):
    cfg = Configuracion.actual()
    abierto = servicios.esta_abierto(cfg)
    proxima = None if abierto else servicios.proxima_apertura()
    todas = Sesion.objects.all()

    sesiones = []
    for s in todas.prefetch_related("preguntas")[:500]:
        sesiones.append({
            "id": s.pk,
            "nombre": s.nombre,
            "correo": s.correo,
            "estado": s.estado,
            "estado_txt": s.get_estado_display(),
            "ingreso": date_format(timezone.localtime(s.ingreso), "d/m H:i"),
            "inicio": s.inicio.isoformat() if s.inicio else None,
            "total_seg": _total_seg(s, cfg),
            "alertas": s.n_alertas,
            "nota": s.nota,
            "analisis": s.analisis,
            "analisis_txt": s.get_analisis_display(),
            "intento": s.intento,
            "rehabilitada": s.rehabilitada,
        })

    return JsonResponse({
        "ahora": timezone.now().isoformat(),
        "abierto": abierto,
        "apertura": cfg.apertura,
        "proxima": date_format(timezone.localtime(proxima.inicio), "l j \\d\\e F, H:i") if proxima else "",
        "preguntas_activas": Pregunta.objects.filter(activa=True).count(),
        "preguntas_por_examen": cfg.preguntas_por_examen,
        "contadores": {
            "total": todas.count(),
            "en_examen": todas.filter(estado=Sesion.EN_EXAMEN).count(),
            "enviado": todas.filter(estado=Sesion.ENVIADO).count(),
            "interrumpido": todas.filter(estado__in=[Sesion.INTERRUMPIDO, Sesion.ERROR_SUBIDA]).count(),
            "con_alertas": todas.filter(n_alertas__gt=0).count(),
            "promedio": todas.filter(nota__isnull=False).aggregate(p=Avg("nota"))["p"],
        },
        "sesiones": sesiones,
    })


@staff_member_required
@require_GET
def detalle(request, pk):
    s = get_object_or_404(Sesion, pk=pk)
    cfg = Configuracion.actual()
    tipos = dict(Evento.TIPOS)
    c = s.config or {}
    hay_archivos = s.estado == Sesion.ENVIADO and bool(s.carpeta)
    return JsonResponse({
        "id": s.pk,
        "nombre": s.nombre,
        "correo": s.correo,
        "estado": s.estado,
        "estado_txt": s.get_estado_display(),
        "ingreso": date_format(timezone.localtime(s.ingreso), "d/m/Y H:i"),
        "intento": s.intento,
        "rehabilitada": s.rehabilitada,
        "nota": s.nota,
        "analisis": s.analisis,
        "analisis_txt": s.get_analisis_display(),
        "analisis_detalle": s.analisis_detalle,
        "lectura": c.get("lectura", cfg.segundos_lectura),
        "respuesta": c.get("respuesta", cfg.segundos_respuesta),
        "total_seg": _total_seg(s, cfg),
        "video": reverse("lecciones:archivo", args=[s.pk, "video"]) if hay_archivos else None,
        "analisis_url": reverse("lecciones:archivo", args=[s.pk, "analisis"]) if hay_archivos else None,
        "preguntas": [{
            "orden": p.orden, "patron": p.patron, "texto": p.texto,
            "transcripcion": p.transcripcion, "puntaje": p.puntaje, "justificacion": p.justificacion,
        } for p in s.preguntas.all()],
        "eventos": [{
            "tipo": e.tipo, "etiqueta": tipos.get(e.tipo, e.tipo),
            "inicio": e.inicio_seg, "fin": e.fin_seg, "pregunta": e.pregunta_orden,
        } for e in s.eventos.all()],
    })


@staff_member_required
@require_POST
def accion(request):
    try:
        datos_ = json.loads(request.body)
        nombre = datos_.get("accion")
        ids = [int(i) for i in datos_.get("ids", [])]
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "Solicitud inválida."}, status=400)

    if nombre == "apertura" and datos_.get("valor") in dict(Configuracion.APERTURA):
        cfg = Configuracion.actual()
        cfg.apertura = datos_["valor"]
        cfg.save(update_fields=["apertura"])
        return JsonResponse({"ok": True, "mensaje": "Apertura actualizada."})

    sesiones = Sesion.objects.filter(pk__in=ids)
    if nombre == "habilitar":
        n = sesiones.exclude(estado=Sesion.INGRESO).update(rehabilitada=True)
        return JsonResponse({"ok": True, "mensaje": f"Nuevo intento habilitado para {n} alumno(s)."})
    if nombre == "reprocesar":
        enviadas = list(sesiones.filter(estado=Sesion.ENVIADO).values_list("pk", flat=True))
        Sesion.objects.filter(pk__in=enviadas).update(analisis=Sesion.PROCESANDO, analisis_detalle="")
        for pk in enviadas:
            analisis.procesar_en_segundo_plano(pk)
        return JsonResponse({"ok": True, "mensaje": f"Análisis en cola para {len(enviadas)} envío(s)."})
    return JsonResponse({"ok": False, "error": "Acción desconocida."}, status=400)
