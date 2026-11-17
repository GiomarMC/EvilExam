"""Importación tolerante del banco de preguntas desde CSV.

Versión ligera del analizador (contrato, sección 5.1): detecta codificación y
separador, reconoce las columnas por nombre aproximado o por contenido, limpia
los textos, normaliza categorías y descarta filas vacías, cortas o duplicadas.
"""
import csv
import difflib
import io
import unicodedata

from .models import Pregunta

ALIAS = {
    "numero": ["n", "no", "nro", "num", "numero", "id", "#"],
    "categoria": ["categoria", "tipo", "grupo"],
    "patron": ["patron", "pattern", "tema"],
    "pregunta": ["pregunta", "enunciado", "question"],
    "puntos_clave": ["puntos_clave", "puntos clave", "respuesta", "rubrica"],
    "activa": ["activa", "activo"],
}
CATEGORIAS = ["Estructural", "Comportamiento", "Integración", "Creacional"]


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().replace("°", "").replace("º", "").split())


def _limpio(texto):
    return " ".join(str(texto or "").replace(" ", " ").split()).strip('"“” ')


def _categoria(valor):
    valor = _limpio(valor)
    if not valor:
        return ""
    claves = {_norm(c): c for c in CATEGORIAS}
    n = _norm(valor)
    cerca = difflib.get_close_matches(n, claves, n=1, cutoff=0.7)
    if not cerca and n.endswith("es"):
        cerca = difflib.get_close_matches(n[:-2], claves, n=1, cutoff=0.7)
    return claves[cerca[0]] if cerca else valor.capitalize()


def _decodificar(crudo):
    for codec in ("utf-8-sig", "cp1252"):
        try:
            return crudo.decode(codec), codec
        except UnicodeDecodeError:
            continue
    return crudo.decode("latin-1", errors="replace"), "latin-1"


def _columnas_por_nombre(fila):
    mapa = {}
    for i, celda in enumerate(fila):
        n = _norm(celda)
        if not n:
            continue
        for campo, nombres in ALIAS.items():
            if campo in mapa.values():
                continue
            if n in nombres or difflib.get_close_matches(n, nombres, n=1, cutoff=0.75):
                mapa[i] = campo
                break
    return mapa


def _columnas_por_contenido(filas):
    ancho = max(len(f) for f in filas)
    columnas = [[f[i].strip() for f in filas if i < len(f) and f[i].strip()] for i in range(ancho)]
    mapa = {}
    largos = [sum(map(len, c)) / len(c) if c else 0 for c in columnas]
    i_preg = max(range(ancho), key=lambda i: largos[i])
    mapa[i_preg] = "pregunta"
    cats = {_norm(c) for c in CATEGORIAS}
    for i, col in enumerate(columnas):
        if i in mapa or not col:
            continue
        if all(v.isdigit() for v in col) and "numero" not in mapa.values():
            mapa[i] = "numero"
        elif sum(_norm(_categoria(v)) in cats for v in col) >= len(col) * 0.6 and "categoria" not in mapa.values():
            mapa[i] = "categoria"
        elif sum(";" in v for v in col) >= len(col) * 0.5 and "puntos_clave" not in mapa.values():
            mapa[i] = "puntos_clave"
        elif "patron" not in mapa.values() and largos[i] < 40:
            mapa[i] = "patron"
    return mapa


def analizar(crudo):
    """Devuelve (filas_limpias, reporte) sin tocar la base de datos."""
    texto, codec = _decodificar(crudo)
    try:
        sep = csv.Sniffer().sniff(texto[:5000], delimiters=",;\t|").delimiter
    except csv.Error:
        sep = ","
    filas = [f for f in csv.reader(io.StringIO(texto), delimiter=sep) if any(c.strip() for c in f)]
    reporte = {"codificacion": codec, "separador": {"\t": "tabulación"}.get(sep, sep),
               "validas": 0, "descartadas": [], "encabezado": False}
    if not filas:
        return [], reporte

    mapa = _columnas_por_nombre(filas[0])
    if "pregunta" in mapa.values():
        reporte["encabezado"] = True
        filas = filas[1:]
    else:
        mapa = _columnas_por_contenido(filas)

    limpias, vistas = [], set()
    for n_fila, fila in enumerate(filas, start=2 if reporte["encabezado"] else 1):
        d = {campo: _limpio(fila[i]) for i, campo in mapa.items() if i < len(fila)}
        pregunta = d.get("pregunta", "")
        if len(pregunta) < 10:
            reporte["descartadas"].append(f"Fila {n_fila}: sin pregunta o demasiado corta")
            continue
        if _norm(pregunta) in vistas:
            reporte["descartadas"].append(f"Fila {n_fila}: pregunta duplicada")
            continue
        vistas.add(_norm(pregunta))
        limpias.append({
            "categoria": _categoria(d.get("categoria", "")),
            "patron": d.get("patron", ""),
            "pregunta": pregunta,
            "puntos_clave": d.get("puntos_clave", ""),
            "activa": _norm(d.get("activa", "si")) not in ("no", "0", "false", "n"),
        })
    reporte["validas"] = len(limpias)
    return limpias, reporte


def importar(crudo, reemplazar=False):
    filas, reporte = analizar(crudo)
    if not filas:
        return reporte
    if reemplazar:
        Pregunta.objects.all().delete()
        existentes, base = set(), 0
    else:
        existentes = {_norm(p) for p in Pregunta.objects.values_list("pregunta", flat=True)}
        base = Pregunta.objects.count()
    nuevas = []
    for f in filas:
        if _norm(f["pregunta"]) in existentes:
            reporte["descartadas"].append(f"Ya estaba en el banco: {f['pregunta'][:60]}")
            continue
        nuevas.append(Pregunta(numero=base + len(nuevas) + 1, **f))
    Pregunta.objects.bulk_create(nuevas)
    reporte["validas"] = len(nuevas)
    return reporte


def exportar(queryset):
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(["N°", "Categoría", "Patrón", "Pregunta", "puntos_clave", "activa"])
    for p in queryset:
        w.writerow([p.numero, p.categoria, p.patron, p.pregunta, p.puntos_clave, "si" if p.activa else "no"])
    return "﻿" + salida.getvalue()
