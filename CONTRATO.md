# Contrato técnico: Plataforma de Lecciones Orales

**Curso:** Diseño de Patrones
**Versión:** 1.2
**Fecha:** 16/11/2026

---

## 1. Objetivo

Construir una página web donde los alumnos rinden una lección oral grabada (rostro y voz). Al terminar, el sistema guarda el video en Google Drive junto con un análisis en `.txt` que indica en qué segundos hubo conductas sospechosas y una nota aproximada. Un administrador monitorea todos los ingresos y envíos y gestiona el banco de preguntas.

El sistema **solo alerta**: no bloquea ni anula exámenes. La decisión final la toma el docente.

---

## 2. Requisitos acordados

| Tema | Decisión |
|---|---|
| Acceso del alumno | Ingresa nombre y correo (sin contraseña) |
| Datos guardados | Nombre y correo |
| Dispositivo | Solo PC |
| Preguntas por examen | 5, al azar, sin repetir, del banco de 100 |
| Tiempo por pregunta | 15 s de lectura en silencio + 20 s de respuesta |
| Duración total | 5 × 35 s = 175 s (unos 3 minutos) |
| Reintentos | No. Una vez iniciado, no hay vuelta atrás |
| Grabación | Video completo |
| Destino | Carpeta de Google Drive, una subcarpeta por alumno |
| Trampa | Leer la pregunta en voz alta y mirar hacia abajo |
| Acción ante trampa | Solo alerta en el análisis, sin avisar al alumno |
| Banco de preguntas | CSV, editable desde la vista de admin |

---

## 3. Flujo del alumno

```
1. Ingreso          Nombre + correo
       │
2. Permisos         Cámara y micrófono
       │
3. Chequeo facial   Detecta rostro, iluminación y encuadre.
                    Calibra la posición "mirando a la pantalla" (línea base)
       │
4. Aviso            "El examen empezará y no podrás volver atrás"
       │
5. [Empezar examen] Inicia la grabación (una sola, continua)
       │
6. Por cada pregunta (×5):
       ├─ 15 s  Lectura en silencio  (pregunta visible, contador)
       └─ 20 s  Respuesta oral       (pregunta visible, contador)
       │
7. Fin              Se detiene la grabación y se sube el video
       │
8. Confirmación     "Tu lección fue enviada"
```

**Reglas del flujo**
- Las fases avanzan solas por tiempo; el alumno no puede saltar ni retroceder.
- Si recarga o cierra la pestaña, la sesión queda como **Interrumpida** y no puede volver a empezar. Solo el admin puede habilitarle un nuevo intento.
- Un mismo correo no puede rendir dos veces, salvo que el admin lo habilite.
- Solo se puede ingresar dentro del horario configurado por el admin.

---

## 4. Vistas

### 4.1 Vista del alumno
- Formulario de ingreso
- Chequeo facial con vista previa de la cámara
- Pantalla de aviso y botón **Empezar examen**
- Pantalla de examen: pregunta, fase actual (Lectura / Respuesta), contador regresivo y progreso (Pregunta 2 de 5)
- Pantalla final de confirmación

### 4.2 Vista del administrador
Se entra con **contraseña** usando la autenticación nativa de Django (contraseña hasheada con PBKDF2). Se puede cambiar desde la propia vista. Tras 5 intentos fallidos, el acceso se bloquea por 15 minutos (`django-axes`).

La vista se construye sobre **Django Admin** personalizado, que ya trae login, tablas con filtros, búsqueda y formularios de edición.

**Panel de monitoreo**

| Columna | Descripción |
|---|---|
| Alumno | Nombre y correo |
| Ingreso | Fecha y hora en que entró |
| Estado | Ingresó / En examen / Enviado / Interrumpido / Error de subida |
| Alertas | Cantidad de eventos sospechosos |
| Nota aprox. | Sobre 20 |
| Drive | Enlace a la carpeta del alumno |

Con filtros por estado y fecha, contadores arriba (ingresos totales, enviados, interrumpidos, con alertas) y acción para **habilitar nuevo intento**.

**Banco de preguntas**
- Tabla con buscar, agregar, editar, desactivar y eliminar
- Importar CSV (reemplazar o agregar) y exportar CSV
- Validación del formato al importar

**Horario**
- Definir una o varias ventanas de examen con fecha, hora de inicio y hora de fin (por ejemplo, 20/11/2026 de 08:00 a 12:00).
- Fuera de horario, el alumno ve "La lección no está disponible" y la hora de la próxima apertura.
- Interruptor manual **Abrir / Cerrar ahora**, que se impone al horario.
- Si el alumno ya empezó antes del cierre, termina normalmente: el horario solo controla el **inicio**.
- La hora se maneja en zona horaria de Lima (UTC-5) y la valida el servidor, no la PC del alumno.

**Configuración**

| Parámetro | Valor por defecto |
|---|---|
| Preguntas por examen | 5 |
| Segundos de lectura | 15 |
| Segundos de respuesta | 20 |
| Mezcla por categoría | No (al azar entre todas) |
| Umbral de "mirar abajo" (segundos) | 2 |
| Mostrar o no la nota al alumno al terminar | No |
| Carpeta de Drive destino | Carpeta del curso |
| Contraseña de admin | Se cambia aquí |

Los cambios aplican solo a los exámenes que empiezan después de guardarlos; los que están en curso siguen con la configuración con la que empezaron.

---

## 5. Banco de preguntas

Formato actual del CSV:

```csv
N°,Categoría,Patrón,Pregunta
1,Estructural,Adapter,¿Qué problema resuelve el patrón Adapter y en qué situaciones resulta conveniente utilizarlo?
```

Contenido actual: 100 preguntas en 3 categorías (Estructural, Comportamiento, Integración).

**Columnas opcionales recomendadas** (mejoran la nota automática):

| Columna | Uso |
|---|---|
| `puntos_clave` | Ideas que debe mencionar una buena respuesta, separadas por `;` |
| `activa` | `si` / `no`, para sacar preguntas sin borrarlas |

Si `puntos_clave` está vacío, el evaluador califica con su conocimiento general de patrones de diseño.

**Selección:** 5 preguntas al azar entre las activas. Opción configurable: forzar mezcla de categorías (por ejemplo, 2 estructurales, 2 de comportamiento y 1 de integración).

### 5.1 Analizador de CSV

El CSV puede llegar desordenado (exportado de Excel, columnas en otro orden, sin encabezado, con errores de tipeo). Antes de importar, el analizador lo limpia y muestra un reporte al admin.

**Pipeline**

```
Archivo subido
   │
1. Codificación   Detecta UTF-8, UTF-8 con BOM o Latin-1/Windows-1252 (Excel)
   │
2. Separador      Detecta , ; tabulación o |
   │
3. Columnas       Identifica cada columna por su nombre o por su contenido
   │
4. Limpieza       Normaliza textos, categorías y patrones
   │
5. Completado     Infiere datos faltantes
   │
6. Validación     Marca duplicados y filas con errores
   │
7. Orden          Ordena por categoría y patrón, y renumera
   │
8. Vista previa   El admin revisa, corrige y confirma
```

**3. Identificación de columnas**

| Columna | Por nombre (sin tildes ni mayúsculas) | Por contenido, si no hay encabezado |
|---|---|---|
| Número | `n°`, `nro`, `num`, `numero`, `id`, `#` | Enteros consecutivos |
| Categoría | `categoria`, `tipo`, `grupo` | Valores tipo Estructural / Comportamiento / Integración |
| Patrón | `patron`, `pattern`, `tema` | Nombres de patrones conocidos (Adapter, Observer...) |
| Pregunta | `pregunta`, `enunciado`, `question` | Texto largo, normalmente con `¿` o `?` |
| Puntos clave | `puntos_clave`, `respuesta`, `rubrica` | Texto con `;` |

Se usa coincidencia aproximada (*fuzzy*) para tolerar errores de tipeo como `Categria` o `Patorn`. La única columna obligatoria es **Pregunta**.

**4. y 5. Limpieza y completado**

| Problema | Corrección |
|---|---|
| Espacios de más, saltos de línea, comillas mal cerradas | Se limpian |
| Filas vacías | Se eliminan |
| `estructurales`, `ESTRUCTURAL`, `Estrutural` | → `Estructural` |
| `adaptor`, `ADAPTER`, `Patrón Adapter` | → `Adapter` (contra la lista de los 23 patrones GoF) |
| Falta la categoría pero hay patrón | Se infiere: Adapter → Estructural, Observer → Comportamiento |
| Falta el patrón | Se busca un nombre de patrón dentro del texto de la pregunta |
| Hay varios patrones en la fila | Categoría `Integración` |
| Falta el número o está repetido | Se renumera |

**6. Validación**

| Tipo | Criterio |
|---|---|
| Duplicado exacto | Mismo texto tras normalizar |
| Posible duplicado | Similitud de texto ≥ 90 % |
| Error | Sin pregunta, o pregunta de menos de 10 caracteres |
| Advertencia | No se pudo inferir el patrón o la categoría |

**8. Vista previa en el admin**

```
Archivo: banco_v2.csv   (codificación: Windows-1252, separador: ;)

✔ 96 filas válidas   ✎ 14 corregidas   ⚠ 3 advertencias   ✖ 1 error   ⧉ 2 duplicados

[Tabla con las filas, resaltando lo corregido y lo marcado]

Modo:  ( ) Reemplazar banco   (•) Agregar al banco
[Descartar marcadas]  [Importar]
```

Las filas con advertencias o errores se pueden editar en la misma tabla antes de confirmar. Nada se guarda hasta que el admin pulsa **Importar**, y cada importación queda registrada para poder deshacerla.

Acepta también `.xlsx`, ya que muchos docentes editan el banco en Excel.

**Librerías:** `pandas`, `charset-normalizer`, `csv.Sniffer`, `rapidfuzz`, `unidecode`, `openpyxl`.

---

## 6. Análisis

El análisis se divide para que sea ligero: la detección facial ocurre **en el navegador del alumno durante el examen** (el servidor no procesa video) y el servidor solo procesa el **audio de los 5 tramos de respuesta** (unos 100 s en total).

### 6.1 Detección de "mirar hacia abajo" (navegador)
- **MediaPipe Face Landmarker** analiza la cámara en vivo (5 a 10 fps es suficiente).
- Se calcula el ángulo vertical de la cabeza (*pitch*) y la posición del iris respecto a la línea base del paso 3.
- **Alerta** si la mirada está por debajo del umbral durante más de 2 s seguidos.
- También se registra si no hay rostro o si hay más de uno.
- Cada evento se guarda con su segundo de inicio y fin relativo al inicio del video.

### 6.2 Detección de "leer la pregunta en voz alta"
Dos señales complementarias:

| Señal | Dónde | Cómo |
|---|---|---|
| Habla durante los 15 s de lectura | Navegador | Detector de voz (Web Audio API / VAD). La lectura debe ser en silencio, así que cualquier habla sostenida en esa fase es alerta |
| Respuesta que repite la pregunta | Servidor | Similitud entre la transcripción y el texto de la pregunta. Si es alta, alerta |

### 6.3 Transcripción y nota (servidor)
1. Con los tiempos de cada fase, se recortan los 5 tramos de respuesta del audio (`ffmpeg`).
2. Se transcribe cada tramo con **Whisper** en español.
3. Un **LLM como evaluador** recibe la pregunta, los puntos clave (si existen) y la transcripción, y devuelve JSON:
   ```json
   { "puntaje": 3, "max": 4, "justificacion": "Explica el propósito pero no da ejemplo." }
   ```
4. Nota final = suma de los 5 puntajes (4 puntos por pregunta, total sobre 20).

---

## 7. Salida en Google Drive

**Estructura**

```
Diseño de Patrones - Lecciones Orales/
└── Perez Juan - jperez@unsa.edu.pe - 2026-11-20 10-32/
    ├── video.webm
    └── analisis.txt
```

**Formato de `analisis.txt`**

```
LECCIÓN ORAL - DISEÑO DE PATRONES
Alumno:   Juan Pérez
Correo:   jperez@unsa.edu.pe
Fecha:    20/11/2026 10:32
Duración: 02:55

NOTA APROXIMADA: 14 / 20

DETALLE POR PREGUNTA
[P1] 00:00 - 00:35 | Adapter | 3/4
  Pregunta: ¿Qué problema resuelve el patrón Adapter...?
  Transcripción: "El adapter sirve para que dos clases con interfaces..."
  Comentario: Explica el propósito, falta un caso de uso.

[P2] 00:35 - 01:10 | Observer | 2/4
  ...

ALERTAS (3)
00:07 - 00:12  Habla durante la fase de lectura (P1)
01:22 - 01:26  Mirada hacia abajo (P3)
02:30 - 02:33  Rostro no detectado (P5)

NOTA: Las alertas y la nota son orientativas. Revisar el video antes de tomar decisiones.
```

Los segundos están referidos al inicio del video para poder saltar directo al momento.

---

## 8. Herramientas

| Componente | Herramienta | Por qué |
|---|---|---|
| Framework | **Django** | Un solo proyecto para todo: páginas, API, admin y tareas |
| Páginas del alumno | Plantillas de Django + JavaScript | Sin frontend separado; el JS solo maneja cámara, temporizadores y subida |
| Vista de admin | Django Admin personalizado | Login, tablas, filtros y formularios ya incluidos |
| Bloqueo de intentos de login | `django-axes` | Bloqueo tras intentos fallidos |
| Grabación | MediaRecorder (navegador) | Nativo, genera `.webm` sin instalar nada |
| Detección facial | MediaPipe Face Landmarker (JS) | Corre en el navegador del alumno, sin costo de servidor |
| Detección de voz en lectura | Web Audio API + VAD | Ligero, en el navegador |
| Base de datos | PostgreSQL con el ORM de Django | Sesiones, eventos, banco, horarios y configuración |
| Recorte de audio | ffmpeg | Extraer los 5 tramos de respuesta |
| Transcripción | Whisper vía API, o faster-whisper `small` local | API: más rápido y sin carga en el servidor. Local: gratis, unos segundos por tramo en CPU |
| Nota | LLM ligero vía API (Claude Haiku o similar) | Evalúa respuestas abiertas mejor que la similitud de texto |
| Similitud pregunta/respuesta | Embeddings multilingües (`paraphrase-multilingual-MiniLM`) | Liviano, corre en CPU |
| Almacenamiento final | Google Drive API | Requisito del cliente |
| Tareas en segundo plano | `django-q2` | Usa la misma base de datos, sin Redis; suficiente para este volumen |
| Analizador de CSV | pandas + charset-normalizer + rapidfuzz | Ver sección 5.1 |
| Despliegue | Docker Compose (Django + PostgreSQL + Nginx) en un VPS de 2 vCPU y 4 GB de RAM | Alcanza usando la API para Whisper; con Whisper local, 4 vCPU y 8 GB |

**Nota sobre Google Drive:** las cuentas de servicio no tienen cuota propia de almacenamiento, así que no pueden subir archivos a un Drive personal. Hay dos opciones: usar una **Unidad compartida** (requiere Google Workspace) o autorizar con **OAuth la cuenta del docente** una sola vez y guardar el refresh token en el servidor.

---

## 9. Arquitectura

```
┌───────────────── Navegador del alumno ─────────────────┐
│  Plantilla Django + JS                                 │
│  ├─ MediaRecorder ──────── video.webm ───────────┐     │
│  ├─ MediaPipe ─── eventos de mirada/rostro ──┐   │     │
│  └─ VAD ──────── habla en fase de lectura ───┤   │     │
└──────────────────────────────────────────────┼───┼─────┘
                                               ▼   ▼
┌──────────────────────── Servidor ──────────────────────┐
│  Django (vistas + admin + django-q2)                   │
│  ├─ PostgreSQL: sesiones, eventos, preguntas           │
│  └─ Tarea en segundo plano:                            │
│       ffmpeg → Whisper → LLM evaluador → analisis.txt  │
│                                    │                   │
└────────────────────────────────────┼───────────────────┘
                                     ▼
                          Google Drive (video + txt)
                                     ▲
                          Vista admin (monitoreo)
```

---

## 10. Modelo de datos

| Tabla | Campos principales |
|---|---|
| `preguntas` | id, numero, categoria, patron, pregunta, puntos_clave, activa |
| `sesiones` | id, nombre, correo, estado, inicio, fin, nota, n_alertas, drive_url, intento |
| `sesion_preguntas` | sesion_id, pregunta_id, orden, inicio_seg, fin_seg, transcripcion, puntaje, justificacion |
| `eventos` | sesion_id, tipo, inicio_seg, fin_seg, pregunta_orden |
| `auth_user` (Django) | Usuario admin con contraseña hasheada |
| `importaciones_csv` | id, archivo, fecha, filas_importadas, filas_descartadas, reporte |
| `horarios` | id, inicio, fin, activo |
| `configuracion` | clave, valor (preguntas, tiempos, umbral, carpeta Drive, apertura manual) |

---

## 11. Requisitos no funcionales

- **Navegadores:** Chrome y Edge actualizados en PC.
- **Video:** 480p, unos 10 MB por alumno.
- **Tiempo de procesamiento:** el análisis debe estar en Drive en menos de 2 minutos tras el envío.
- **Robustez:** si falla la subida, se reintenta automáticamente y el admin ve el estado **Error de subida**.
- **Privacidad:** texto de consentimiento antes del chequeo facial, indicando que se graba rostro y voz y que el video se guarda en Drive del curso.
- **Seguridad:** vista de admin protegida; las credenciales de Drive y de las APIs solo en el servidor.

---

## 12. Fuera de alcance (versión 1)

- Uso desde celular
- Login con contraseña o verificación de identidad del alumno
- Avisos al alumno durante el examen
- Bloqueo o anulación automática por trampa
- Detección de otras voces (diarización)

---

## 13. Riesgos y supuestos

| Riesgo | Mitigación |
|---|---|
| Cualquiera puede escribir el correo de otro alumno | Opcional: código de 6 dígitos enviado al correo antes de empezar |
| Falsos positivos de "mirar abajo" (pensar, lentes, cámara baja) | Calibración inicial, umbral de 2 s y revisión humana |
| 20 s es poco para preguntas de diseño o integración | Considerar más tiempo para la categoría Integración |
| La nota automática puede equivocarse | Se presenta como aproximada; el docente decide |
| Cuota o permisos de Drive | Usar OAuth del docente o Unidad compartida (ver sección 8) |

---

## 14. Entregables y criterios de aceptación

| # | Entregable | Criterio de aceptación |
|---|---|---|
| 1 | Flujo del alumno completo | Rinde 5 preguntas con 15 s + 20 s cada una, sin poder retroceder |
| 2 | Grabación y subida | El video completo aparece en su carpeta de Drive con el nombre correcto |
| 3 | Detección facial | Mirar hacia abajo más de 2 s genera una alerta con el segundo correcto |
| 4 | Detección de lectura en voz alta | Hablar en la fase de lectura genera una alerta con el segundo correcto |
| 5 | Nota aproximada | `analisis.txt` incluye transcripción, puntaje por pregunta y nota sobre 20 |
| 6 | Panel de admin | Muestra todos los ingresos con estado, alertas, nota y enlace a Drive |
| 7 | Gestión del banco | El admin puede importar, editar, desactivar y exportar preguntas |
| 8 | Horario | Fuera de la ventana configurada nadie puede iniciar; dentro sí |
| 9 | Acceso y configuración | El admin entra con contraseña, la puede cambiar y modificar los parámetros de la sección 4.2 |
| 10 | Analizador de CSV | Un CSV desordenado (otro separador, columnas en otro orden, sin encabezado, categorías mal escritas) se importa correctamente tras la vista previa |

---

## 15. Fases sugeridas

1. Proyecto Django y vista de admin: login, banco de preguntas, horario y configuración
2. Analizador de CSV con vista previa
3. Flujo del alumno con temporizadores y grabación
4. Subida a Google Drive
5. MediaPipe y VAD en el navegador (eventos)
6. Transcripción, evaluación y generación de `analisis.txt`
7. Panel de monitoreo y pruebas con alumnos reales
