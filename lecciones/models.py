import uuid

from django.db import models


class Pregunta(models.Model):
    numero = models.PositiveIntegerField("N°", default=0)
    categoria = models.CharField("categoría", max_length=60, blank=True)
    patron = models.CharField("patrón", max_length=80, blank=True)
    pregunta = models.TextField()
    puntos_clave = models.TextField(
        blank=True, help_text="Ideas que debe mencionar una buena respuesta, separadas por ;"
    )
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["numero", "id"]

    def __str__(self):
        return f"{self.numero}. {self.pregunta[:70]}"


class Configuracion(models.Model):
    AUTO, ABIERTO, CERRADO = "auto", "abierto", "cerrado"
    APERTURA = [
        (AUTO, "Según el horario"),
        (ABIERTO, "Abierto ahora (ignora el horario)"),
        (CERRADO, "Cerrado ahora (ignora el horario)"),
    ]

    preguntas_por_examen = models.PositiveSmallIntegerField(default=5)
    segundos_lectura = models.PositiveSmallIntegerField(default=15)
    segundos_respuesta = models.PositiveSmallIntegerField(default=20)
    mezcla_por_categoria = models.BooleanField(
        "mezcla por categoría", default=False,
        help_text="Reparte las preguntas entre las categorías en vez de sortear entre todas.",
    )
    umbral_mirar_abajo = models.FloatField(
        'umbral de "mirar abajo" (segundos)', default=2
    )
    mostrar_nota = models.BooleanField("mostrar la nota al alumno al terminar", default=False)
    carpeta_drive = models.CharField(
        "carpeta de Drive destino", max_length=200, blank=True,
        help_text="Aún sin uso: por ahora los videos se guardan en la carpeta local «entregas».",
    )
    apertura = models.CharField("apertura manual", max_length=10, choices=APERTURA, default=AUTO)

    class Meta:
        verbose_name = "configuración"
        verbose_name_plural = "configuración"

    def __str__(self):
        return "Configuración del examen"

    @classmethod
    def actual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Horario(models.Model):
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "ventana de examen"
        verbose_name_plural = "horario"

    def __str__(self):
        return f"{self.inicio:%d/%m/%Y %H:%M} – {self.fin:%H:%M}"


class Sesion(models.Model):
    INGRESO, EN_EXAMEN, ENVIADO, INTERRUMPIDO, ERROR_SUBIDA = (
        "ingreso", "en_examen", "enviado", "interrumpido", "error_subida",
    )
    ESTADOS = [
        (INGRESO, "Ingresó"),
        (EN_EXAMEN, "En examen"),
        (ENVIADO, "Enviado"),
        (INTERRUMPIDO, "Interrumpido"),
        (ERROR_SUBIDA, "Error de subida"),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    nombre = models.CharField(max_length=120)
    correo = models.EmailField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default=INGRESO)
    ingreso = models.DateTimeField(auto_now_add=True)
    inicio = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    nota = models.PositiveSmallIntegerField("nota aprox.", null=True, blank=True)
    n_alertas = models.PositiveIntegerField("alertas", default=0)
    drive_url = models.URLField(blank=True)
    intento = models.PositiveSmallIntegerField(default=1)
    rehabilitada = models.BooleanField(
        "nuevo intento habilitado", default=False,
        help_text="Si está marcado, este correo puede volver a rendir.",
    )
    config = models.JSONField(default=dict, blank=True)
    carpeta = models.CharField(max_length=255, blank=True)

    PENDIENTE, PROCESANDO, LISTO, SIN_NOTA, ERROR = "pendiente", "procesando", "listo", "sin_nota", "error"
    ANALISIS = [
        (PENDIENTE, "Pendiente"),
        (PROCESANDO, "Procesando"),
        (LISTO, "Listo"),
        (SIN_NOTA, "Transcrito, sin nota"),
        (ERROR, "Error"),
    ]
    analisis = models.CharField("análisis", max_length=12, choices=ANALISIS, default=PENDIENTE)
    analisis_detalle = models.CharField("detalle del análisis", max_length=500, blank=True)

    class Meta:
        ordering = ["-ingreso"]
        verbose_name = "sesión"
        verbose_name_plural = "monitoreo de sesiones"

    def __str__(self):
        return f"{self.nombre} <{self.correo}>"


class SesionPregunta(models.Model):
    sesion = models.ForeignKey(Sesion, on_delete=models.CASCADE, related_name="preguntas")
    pregunta = models.ForeignKey(Pregunta, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    patron = models.CharField(max_length=80, blank=True)
    orden = models.PositiveSmallIntegerField()
    inicio_seg = models.FloatField(null=True, blank=True)
    fin_seg = models.FloatField(null=True, blank=True)
    transcripcion = models.TextField(blank=True)
    puntaje = models.PositiveSmallIntegerField(null=True, blank=True)
    justificacion = models.TextField(blank=True)

    class Meta:
        ordering = ["orden"]
        verbose_name = "pregunta de la sesión"
        verbose_name_plural = "preguntas de la sesión"


class Evento(models.Model):
    TIPOS = [
        ("mirada_abajo", "Mirada hacia abajo"),
        ("habla_lectura", "Habla durante la fase de lectura"),
        ("sin_rostro", "Rostro no detectado"),
        ("varios_rostros", "Más de un rostro"),
        ("sin_deteccion", "Detección facial no disponible"),
        ("repite_pregunta", "La respuesta repite la pregunta"),
    ]

    sesion = models.ForeignKey(Sesion, on_delete=models.CASCADE, related_name="eventos")
    tipo = models.CharField(max_length=20, choices=TIPOS)
    inicio_seg = models.FloatField()
    fin_seg = models.FloatField()
    pregunta_orden = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["inicio_seg"]
