from pathlib import Path

from django.core.management.base import BaseCommand

from lecciones import importador
from lecciones.models import Configuracion


class Command(BaseCommand):
    help = "Carga un banco de preguntas de ejemplo y crea la configuración por defecto."

    def handle(self, *args, **opciones):
        Configuracion.actual()
        ruta = Path(__file__).resolve().parents[2] / "datos" / "banco_ejemplo.csv"
        reporte = importador.importar(ruta.read_bytes())
        self.stdout.write(self.style.SUCCESS(f"{reporte['validas']} preguntas de ejemplo cargadas."))
