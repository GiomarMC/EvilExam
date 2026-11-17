import json
import re

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from django.conf import settings

from . import analisis, servicios
from .models import Configuracion, Evento, Sesion, SesionPregunta

TIPOS_EVENTO = {t for t, _ in Evento.TIPOS}


def _error(mensaje, status=400):
    return JsonResponse({"ok": False, "error": mensaje}, status=status)


def _sesion(token):
    try:
        return Sesion.objects.filter(token=token).first()
    except (ValidationError, ValueError, TypeError):
        return None


def _guardar_eventos(sesion, crudos):
    """Guarda los eventos enviados por el navegador, descartando lo que no sea válido."""
    sesion.eventos.all().delete()
    nuevos = []
    for ev in (crudos or [])[:500]:
        try:
            tipo = ev["tipo"]
            ini, fin = float(ev["inicio"]), float(ev["fin"])
            orden = ev.get("pregunta")
            orden = int(orden) if orden else None
        except (KeyError, TypeError, ValueError):
            continue
        if tipo in TIPOS_EVENTO and 0 <= ini <= fin < 36000:
            nuevos.append(Evento(sesion=sesion, tipo=tipo, inicio_seg=ini, fin_seg=fin, pregunta_orden=orden))
    Evento.objects.bulk_create(nuevos)
    sesion.n_alertas = len(nuevos)


@require_GET
def inicio(request):
    # Recargar la página durante el examen lo deja como Interrumpido.
    token = request.session.get("sesion_token")
    if token:
        Sesion.objects.filter(token=token, estado=Sesion.EN_EXAMEN).update(
            estado=Sesion.INTERRUMPIDO, fin=timezone.now()
        )

    abierto = servicios.esta_abierto()
    proxima = None if abierto else servicios.proxima_apertura()
    return render(request, "lecciones/alumno.html", {
        "abierto": abierto,
        "proxima": date_format(timezone.localtime(proxima.inicio), "l j \\d\\e F, H:i") if proxima else "",
    })


@require_POST
def api_ingreso(request):
    try:
        datos = json.loads(request.body)
        nombre = " ".join(str(datos.get("nombre", "")).split())
        correo = str(datos.get("correo", "")).strip().lower()
        validate_email(correo)
    except (ValueError, ValidationError):
        return _error("Revisa tu nombre y tu correo.")
    if len(nombre) < 3 or len(nombre) > 120:
        return _error("Escribe tu nombre completo.")
    if not servicios.esta_abierto():
        return _error("La lección no está disponible en este momento.", 403)

    with transaction.atomic():
        previas = list(Sesion.objects.select_for_update().filter(correo__iexact=correo))
        sesion = next((s for s in previas if s.estado == Sesion.INGRESO), None)
        if sesion:
            sesion.nombre = nombre
            sesion.save(update_fields=["nombre"])
        elif any(not s.rehabilitada for s in previas):
            return _error(
                "Este correo ya tiene una lección registrada. "
                "Si necesitas un nuevo intento, pídeselo a tu docente.", 409
            )
        else:
            sesion = Sesion.objects.create(nombre=nombre, correo=correo, intento=len(previas) + 1)

    request.session["sesion_token"] = str(sesion.token)
    return JsonResponse({"ok": True, "token": str(sesion.token)})


@require_POST
def api_iniciar(request):
    try:
        token = json.loads(request.body).get("token")
    except ValueError:
        return _error("Solicitud inválida.")

    with transaction.atomic():
        sesion = Sesion.objects.select_for_update().filter(token=token).first() if _sesion(token) else None
        if not sesion or sesion.estado != Sesion.INGRESO:
            return _error("Esta lección ya fue iniciada y no puede repetirse.", 409)
        cfg = Configuracion.actual()
        # El horario solo controla el inicio: quien ya empezó termina normalmente.
        if not servicios.esta_abierto(cfg):
            return _error("La lección ya no está disponible.", 403)
        preguntas = servicios.sortear_preguntas(cfg)
        if preguntas is None:
            return _error("El banco no tiene suficientes preguntas activas. Avisa a tu docente.", 503)

        sesion.config = {
            "lectura": cfg.segundos_lectura,
            "respuesta": cfg.segundos_respuesta,
            "umbral": cfg.umbral_mirar_abajo,
            "mostrar_nota": cfg.mostrar_nota,
        }
        sesion.estado = Sesion.EN_EXAMEN
        sesion.inicio = timezone.now()
        sesion.save()
        SesionPregunta.objects.bulk_create([
            SesionPregunta(sesion=sesion, pregunta=p, texto=p.pregunta, patron=p.patron, orden=i)
            for i, p in enumerate(preguntas, start=1)
        ])

    return JsonResponse({
        "ok": True,
        "lectura": cfg.segundos_lectura,
        "respuesta": cfg.segundos_respuesta,
        "umbral": cfg.umbral_mirar_abajo,
        "preguntas": [{"orden": i, "texto": p.pregunta} for i, p in enumerate(preguntas, start=1)],
    })


@require_POST
def api_enviar(request):
    sesion = _sesion(request.POST.get("token"))
    video = request.FILES.get("video")
    if not sesion or sesion.estado not in (Sesion.EN_EXAMEN, Sesion.ERROR_SUBIDA):
        return _error("Esta lección no admite envíos.", 409)
    if not video or video.size > 200 * 1024 * 1024:
        return _error("No se recibió el video.")
    try:
        datos = json.loads(request.POST.get("datos", "{}"))
        duracion = float(datos.get("duracion", 0))
    except (ValueError, TypeError):
        return _error("Datos inválidos.")

    sesion.carpeta = sesion.carpeta or servicios.nombre_carpeta(sesion)
    carpeta = servicios.ruta_carpeta(sesion)
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / "video.webm", "wb") as destino:
        for trozo in video.chunks():
            destino.write(trozo)

    bloque = sesion.config.get("lectura", 15) + sesion.config.get("respuesta", 20)
    for sp in sesion.preguntas.all():
        sp.inicio_seg = (sp.orden - 1) * bloque
        sp.fin_seg = sp.orden * bloque
        sp.save(update_fields=["inicio_seg", "fin_seg"])

    _guardar_eventos(sesion, datos.get("eventos"))
    sesion.estado = Sesion.ENVIADO
    sesion.fin = timezone.now()
    sesion.save()
    (carpeta / "analisis.txt").write_text(servicios.generar_analisis(sesion, duracion), encoding="utf-8")

    if settings.ANALISIS_AUTOMATICO:
        analisis.procesar_en_segundo_plano(sesion.pk)

    nota = sesion.nota if sesion.config.get("mostrar_nota") else None
    return JsonResponse({"ok": True, "nota": nota})


@csrf_exempt  # llega por sendBeacon al cerrar la pestaña; se autentica con el token de la sesión
@require_POST
def api_interrumpir(request):
    sesion = _sesion(request.POST.get("token"))
    if sesion and sesion.estado == Sesion.EN_EXAMEN:
        try:
            _guardar_eventos(sesion, json.loads(request.POST.get("eventos", "[]")))
        except ValueError:
            pass
        subiendo = request.POST.get("fase") == "subida"
        sesion.estado = Sesion.ERROR_SUBIDA if subiendo else Sesion.INTERRUMPIDO
        sesion.fin = timezone.now()
        sesion.save()
    return JsonResponse({"ok": True})


@staff_member_required
def archivo(request, pk, cual):
    sesion = get_object_or_404(Sesion, pk=pk)
    nombres = {"video": "video.webm", "analisis": "analisis.txt"}
    if cual not in nombres or not sesion.carpeta:
        raise Http404
    ruta = servicios.ruta_carpeta(sesion) / nombres[cual]
    if not ruta.exists():
        raise Http404
    if cual == "analisis":
        return FileResponse(open(ruta, "rb"), content_type="text/plain; charset=utf-8")
    return _con_rango(request, ruta, "video/webm")


def _con_rango(request, ruta, tipo):
    """Sirve un archivo aceptando la cabecera Range, para que el video permita saltar a un segundo."""
    total = ruta.stat().st_size
    m = re.match(r"bytes=(\d*)-(\d*)$", request.headers.get("Range", ""))
    if not m or not (m.group(1) or m.group(2)):
        resp = FileResponse(open(ruta, "rb"), content_type=tipo)
        resp["Accept-Ranges"] = "bytes"
        return resp
    if m.group(1):
        ini = int(m.group(1))
        fin = min(int(m.group(2)), total - 1) if m.group(2) else total - 1
    else:
        ini, fin = max(0, total - int(m.group(2))), total - 1
    if ini > fin or ini >= total:
        resp = HttpResponse(status=416)
        resp["Content-Range"] = f"bytes */{total}"
        return resp

    def trozos(restante=fin - ini + 1):
        with open(ruta, "rb") as f:
            f.seek(ini)
            while restante > 0:
                datos = f.read(min(65536, restante))
                if not datos:
                    break
                restante -= len(datos)
                yield datos

    resp = StreamingHttpResponse(trozos(), status=206, content_type=tipo)
    resp["Content-Range"] = f"bytes {ini}-{fin}/{total}"
    resp["Content-Length"] = str(fin - ini + 1)
    resp["Accept-Ranges"] = "bytes"
    return resp
