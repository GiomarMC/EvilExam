from django.contrib import admin, messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html

from . import analisis, importador
from .models import Configuracion, Evento, Horario, Pregunta, Sesion, SesionPregunta


class SoloLectura:
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class SesionPreguntaInline(SoloLectura, admin.TabularInline):
    model = SesionPregunta
    fields = ("orden", "patron", "texto", "puntaje", "transcripcion", "justificacion")


class EventoInline(SoloLectura, admin.TabularInline):
    model = Evento
    fields = ("tipo", "inicio_seg", "fin_seg", "pregunta_orden")


@admin.register(Sesion)
class SesionAdmin(admin.ModelAdmin):
    list_display = ("alumno", "ingreso", "estado_color", "n_alertas", "nota_aprox", "analisis", "archivos", "intento", "rehabilitada")
    list_filter = ("estado", "ingreso")
    search_fields = ("nombre", "correo")
    date_hierarchy = "ingreso"
    actions = ["habilitar_nuevo_intento", "reprocesar_analisis"]
    inlines = [SesionPreguntaInline, EventoInline]
    exclude = ("config", "drive_url")
    change_list_template = "admin/lecciones/sesion/change_list.html"

    COLORES = {
        Sesion.INGRESO: "#6b7280", Sesion.EN_EXAMEN: "#b45309", Sesion.ENVIADO: "#15803d",
        Sesion.INTERRUMPIDO: "#c8102e", Sesion.ERROR_SUBIDA: "#c8102e",
    }

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Alumno", ordering="nombre")
    def alumno(self, obj):
        return format_html("<strong>{}</strong><br><small>{}</small>", obj.nombre, obj.correo)

    @admin.display(description="Estado", ordering="estado")
    def estado_color(self, obj):
        return format_html(
            '<span style="color:{};font-weight:600">● {}</span>',
            self.COLORES.get(obj.estado, "#111"), obj.get_estado_display(),
        )

    @admin.display(description="Nota aprox.", ordering="nota")
    def nota_aprox(self, obj):
        return f"{obj.nota} / 20" if obj.nota is not None else "—"

    @admin.display(description="Archivos")
    def archivos(self, obj):
        if obj.estado != Sesion.ENVIADO or not obj.carpeta:
            return "—"
        return format_html(
            '<a href="{}" target="_blank">Video</a> · <a href="{}" target="_blank">Análisis</a>',
            reverse("lecciones:archivo", args=[obj.pk, "video"]),
            reverse("lecciones:archivo", args=[obj.pk, "analisis"]),
        )

    @admin.action(description="Habilitar nuevo intento")
    def habilitar_nuevo_intento(self, request, queryset):
        n = queryset.update(rehabilitada=True)
        self.message_user(request, f"Nuevo intento habilitado para {n} sesión(es).", messages.SUCCESS)

    @admin.action(description="Reprocesar transcripción y nota")
    def reprocesar_analisis(self, request, queryset):
        enviadas = queryset.filter(estado=Sesion.ENVIADO)
        for sesion in enviadas:
            analisis.procesar_en_segundo_plano(sesion.pk)
        self.message_user(
            request, f"Análisis en cola para {enviadas.count()} sesión(es). Recarga en un minuto.", messages.SUCCESS
        )

    def changelist_view(self, request, extra_context=None):
        qs = Sesion.objects
        contadores = [
            ("Ingresos", qs.count()),
            ("Enviados", qs.filter(estado=Sesion.ENVIADO).count()),
            ("Interrumpidos", qs.filter(estado=Sesion.INTERRUMPIDO).count()),
            ("Con alertas", qs.filter(n_alertas__gt=0).count()),
        ]
        return super().changelist_view(request, {**(extra_context or {}), "contadores": contadores})


@admin.register(Pregunta)
class PreguntaAdmin(admin.ModelAdmin):
    list_display = ("numero", "categoria", "patron", "pregunta_corta", "activa")
    list_display_links = ("numero", "pregunta_corta")
    list_editable = ("activa",)
    list_filter = ("activa", "categoria")
    search_fields = ("pregunta", "patron", "categoria")
    actions = ["activar", "desactivar", "exportar_csv"]
    change_list_template = "admin/lecciones/pregunta/change_list.html"

    @admin.display(description="Pregunta")
    def pregunta_corta(self, obj):
        return obj.pregunta if len(obj.pregunta) < 110 else obj.pregunta[:107] + "…"

    @admin.action(description="Activar seleccionadas")
    def activar(self, request, queryset):
        queryset.update(activa=True)

    @admin.action(description="Desactivar seleccionadas")
    def desactivar(self, request, queryset):
        queryset.update(activa=False)

    @admin.action(description="Exportar seleccionadas a CSV")
    def exportar_csv(self, request, queryset):
        return self._csv(queryset)

    def _csv(self, queryset):
        resp = HttpResponse(importador.exportar(queryset), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="banco_preguntas.csv"'
        return resp

    def get_urls(self):
        extra = [
            path("importar/", self.admin_site.admin_view(self.importar_view), name="lecciones_pregunta_importar"),
            path("exportar/", self.admin_site.admin_view(self.exportar_view), name="lecciones_pregunta_exportar"),
        ]
        return extra + super().get_urls()

    def exportar_view(self, request):
        return self._csv(Pregunta.objects.all())

    def importar_view(self, request):
        if request.method == "POST" and request.FILES.get("archivo"):
            reporte = importador.importar(
                request.FILES["archivo"].read(), reemplazar=request.POST.get("modo") == "reemplazar"
            )
            self.message_user(
                request,
                f"{reporte['validas']} preguntas importadas "
                f"(codificación {reporte['codificacion']}, separador «{reporte['separador']}»).",
                messages.SUCCESS if reporte["validas"] else messages.WARNING,
            )
            for linea in reporte["descartadas"][:15]:
                self.message_user(request, linea, messages.WARNING)
            return HttpResponseRedirect(reverse("admin:lecciones_pregunta_changelist"))
        contexto = {**self.admin_site.each_context(request), "opts": self.model._meta, "title": "Importar banco desde CSV"}
        return render(request, "admin/lecciones/pregunta/importar.html", contexto)


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ("inicio", "fin", "activo")
    list_editable = ("activo",)


@admin.register(Configuracion)
class ConfiguracionAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        cfg = Configuracion.actual()
        return HttpResponseRedirect(reverse("admin:lecciones_configuracion_change", args=[cfg.pk]))
