from django.core.management.base import BaseCommand

from lecciones import analisis
from lecciones.models import Sesion


class Command(BaseCommand):
    help = "Transcribe y califica sesiones enviadas. Sin argumentos procesa las que no están listas."

    def add_arguments(self, parser):
        parser.add_argument("ids", nargs="*", type=int, help="IDs de sesión a (re)procesar")

    def handle(self, *args, **opciones):
        sesiones = Sesion.objects.filter(estado=Sesion.ENVIADO)
        sesiones = sesiones.filter(pk__in=opciones["ids"]) if opciones["ids"] else sesiones.exclude(analisis=Sesion.LISTO)
        for sesion in sesiones:
            self.stdout.write(f"Procesando {sesion}…")
            analisis.procesar(sesion.pk)
            sesion.refresh_from_db()
            nota = f"{sesion.nota}/20" if sesion.nota is not None else "sin nota"
            self.stdout.write(f"  {sesion.get_analisis_display()} · {nota} {sesion.analisis_detalle}")
