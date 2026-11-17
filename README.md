# Lecciones Orales · Diseño de Patrones

Plataforma local (Django) para rendir lecciones orales grabadas. El contrato está en `CONTRATO.md`.

## Correr en local

```bash
.venv/bin/python manage.py createsuperuser   # una sola vez: usuario del docente
.venv/bin/python manage.py runserver
```

- Alumno: http://localhost:8000/
- Docente: http://localhost:8000/panel/ (monitoreo en vivo; el banco, el horario y la configuración se abren desde su menú)

Usar Chrome o Edge. La detección facial descarga MediaPipe de internet la primera vez.

## Dónde queda cada cosa

- Videos y `analisis.txt`: carpeta `entregas/`, una subcarpeta por alumno.
- Banco de preguntas: admin → Preguntas (importar / exportar CSV). Hay 18 de ejemplo.
- Apertura: admin → Configuración → «Apertura manual», o ventanas en Horario.

## Transcripción y nota automática

Tras cada envío, en segundo plano: ffmpeg recorta los tramos de respuesta, Whisper
(local, modelo `small`) los transcribe y Claude Haiku pone un puntaje de 0 a 4 por pregunta.

- La transcripción funciona sin configurar nada (requiere `ffmpeg` instalado).
- Para la nota, copia `.env.example` como `.env`, pon tu `ANTHROPIC_API_KEY` y reinicia el servidor.
- Reprocesar: admin → Monitoreo → acción «Reprocesar transcripción y nota», o
  `.venv/bin/python manage.py procesar_analisis`.

## Pendiente del contrato

Subida a Google Drive, vista previa del analizador de CSV y `.xlsx`, PostgreSQL y
Docker para el despliegue.

## Pruebas

```bash
.venv/bin/python manage.py test
```
