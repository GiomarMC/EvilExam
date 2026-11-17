import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from . import importador
from .models import Configuracion, Horario, Pregunta, Sesion

TMP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP, ANALISIS_AUTOMATICO=False)
class FlujoAlumnoTests(TestCase):
    def setUp(self):
        for i in range(8):
            Pregunta.objects.create(numero=i + 1, categoria="Estructural", patron="Adapter", pregunta=f"¿Pregunta número {i}?")
        self.cfg = Configuracion.actual()
        self.cfg.apertura = Configuracion.ABIERTO
        self.cfg.save()

    def post(self, url, datos):
        return self.client.post(url, json.dumps(datos), content_type="application/json")

    def ingresar(self, correo="ana@utp.edu.pe"):
        return self.post("/api/ingreso/", {"nombre": "Ana Ruiz", "correo": correo})

    def test_flujo_completo(self):
        token = self.ingresar().json()["token"]
        r = self.post("/api/iniciar/", {"token": token}).json()
        self.assertEqual(len(r["preguntas"]), 5)
        self.assertEqual(len({p["texto"] for p in r["preguntas"]}), 5)
        self.assertEqual((r["lectura"], r["respuesta"]), (15, 20))

        datos = {"duracion": 175, "eventos": [
            {"tipo": "mirada_abajo", "inicio": 82, "fin": 86, "pregunta": 3},
            {"tipo": "habla_lectura", "inicio": 7, "fin": 12, "pregunta": 1},
            {"tipo": "inventado", "inicio": 1, "fin": 2},
        ]}
        r = self.client.post("/api/enviar/", {
            "token": token, "datos": json.dumps(datos),
            "video": SimpleUploadedFile("video.webm", b"webm", content_type="video/webm"),
        })
        self.assertEqual(r.status_code, 200)
        s = Sesion.objects.get(token=token)
        self.assertEqual((s.estado, s.n_alertas), (Sesion.ENVIADO, 2))
        carpeta = Path(TMP) / s.carpeta
        self.assertTrue((carpeta / "video.webm").exists())
        analisis = (carpeta / "analisis.txt").read_text(encoding="utf-8")
        self.assertIn("ALERTAS (2)", analisis)
        self.assertIn("01:22 - 01:26  Mirada hacia abajo (P3)", analisis)
        self.assertIn("[P2] 00:35 - 01:10", analisis)

    def test_no_puede_rendir_dos_veces_salvo_habilitacion(self):
        token = self.ingresar().json()["token"]
        self.post("/api/iniciar/", {"token": token})
        self.assertEqual(self.post("/api/iniciar/", {"token": token}).status_code, 409)
        self.assertEqual(self.ingresar("ANA@utp.edu.pe").status_code, 409)
        Sesion.objects.update(rehabilitada=True)
        r = self.ingresar()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Sesion.objects.get(token=r.json()["token"]).intento, 2)

    def test_recargar_interrumpe(self):
        token = self.ingresar().json()["token"]
        self.post("/api/iniciar/", {"token": token})
        self.client.get("/")
        self.assertEqual(Sesion.objects.get(token=token).estado, Sesion.INTERRUMPIDO)
        self.assertEqual(self.ingresar().status_code, 409)

    def test_cerrar_pestana_interrumpe(self):
        token = self.ingresar().json()["token"]
        self.post("/api/iniciar/", {"token": token})
        self.client.post("/api/interrumpir/", {"token": token, "fase": "examen", "eventos": "[]"})
        self.assertEqual(Sesion.objects.get(token=token).estado, Sesion.INTERRUMPIDO)

    def test_horario(self):
        self.cfg.apertura = Configuracion.AUTO
        self.cfg.save()
        self.assertEqual(self.ingresar().status_code, 403)
        self.assertContains(self.client.get("/"), "La lección no está disponible")
        ahora = timezone.now()
        Horario.objects.create(inicio=ahora - timedelta(hours=1), fin=ahora + timedelta(hours=1))
        self.assertEqual(self.ingresar().status_code, 200)
        self.cfg.apertura = Configuracion.CERRADO
        self.cfg.save()
        self.assertEqual(self.ingresar("otro@utp.edu.pe").status_code, 403)

    def test_panel_exige_docente(self):
        self.assertEqual(self.client.get("/panel/datos/").status_code, 302)
        self.assertEqual(self.client.post("/panel/accion/", "{}", content_type="application/json").status_code, 302)

    def test_video_con_rango(self):
        token = self.ingresar().json()["token"]
        self.post("/api/iniciar/", {"token": token})
        self.client.post("/api/enviar/", {"token": token, "datos": json.dumps({"duracion": 175, "eventos": []}),
                         "video": SimpleUploadedFile("video.webm", b"0123456789", content_type="video/webm")})
        s = Sesion.objects.get(token=token)
        self.client.force_login(User.objects.create_superuser("doc2", password="x"))
        r = self.client.get(f"/archivo/{s.pk}/video/", headers={"Range": "bytes=2-5"})
        self.assertEqual((r.status_code, b"".join(r.streaming_content), r["Content-Range"]), (206, b"2345", "bytes 2-5/10"))
        r = self.client.get(f"/archivo/{s.pk}/video/", headers={"Range": "bytes=-3"})
        self.assertEqual(b"".join(r.streaming_content), b"789")

    def test_admin(self):
        self.ingresar()
        self.client.force_login(User.objects.create_superuser("docente", password="x"))
        self.assertRedirects(self.client.get("/admin/"), "/panel/")
        self.assertContains(self.client.get("/panel/"), "Monitoreo")
        d = self.client.get("/panel/datos/").json()
        self.assertEqual((d["contadores"]["total"], d["sesiones"][0]["correo"]), (1, "ana@utp.edu.pe"))
        sid = d["sesiones"][0]["id"]
        self.assertEqual(self.client.get(f"/panel/sesion/{sid}/").json()["nombre"], "Ana Ruiz")
        r = self.client.post("/panel/accion/", json.dumps({"accion": "apertura", "valor": "cerrado"}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(Configuracion.actual().apertura, "cerrado")
        for url in ("/admin/lecciones/", "/admin/lecciones/sesion/", "/admin/lecciones/pregunta/",
                    "/admin/lecciones/pregunta/importar/", "/admin/lecciones/horario/add/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/admin/lecciones/configuracion/", follow=True).status_code, 200)
        self.assertContains(self.client.get("/admin/lecciones/pregunta/exportar/"), "Pregunta")


class ImportadorTests(TestCase):
    def test_csv_desordenado(self):
        crudo = (
            "Patorn;Categria;Enunciado\r\n"
            "Adapter;estructurales;¿Qué problema resuelve el patrón Adapter?\r\n"
            ";;\r\n"
            "Observer;COMPORTAMIENTO;¿Cómo notifica el sujeto a sus observadores?\r\n"
            "Observer;Comportamiento;¿Cómo notifica el sujeto a sus observadores?\r\n"
            "X;Y;corta\r\n"
        ).encode("cp1252")
        reporte = importador.importar(crudo)
        self.assertEqual((reporte["codificacion"], reporte["separador"], reporte["validas"]), ("cp1252", ";", 2))
        self.assertEqual(len(reporte["descartadas"]), 2)
        p = Pregunta.objects.get(patron="Adapter")
        self.assertEqual((p.categoria, p.numero), ("Estructural", 1))

    def test_sin_encabezado(self):
        crudo = "1,Estructural,Facade,¿Qué ventajas ofrece el patrón Facade?\n2,Comportamiento,State,¿En qué se diferencia State de Strategy?\n".encode()
        self.assertEqual(importador.importar(crudo)["validas"], 2)
        self.assertEqual(Pregunta.objects.get(patron="State").categoria, "Comportamiento")


class AnalisisTests(TestCase):
    def test_detecta_respuesta_que_repite_la_pregunta(self):
        from .analisis import _repite_pregunta
        pregunta = "¿Qué problema resuelve el patrón Adapter y en qué situaciones resulta conveniente utilizarlo?"
        leida = [(0.0, 6.5, "Qué problema resuelve el patrón adaptar y en qué situaciones resulta conveniente utilizarlo."),
                 (6.5, 12.0, "Bueno, sirve para conectar clases.")]
        propia = [(0.0, 8.0, "El adapter permite que dos clases con interfaces incompatibles trabajen juntas mediante un envoltorio.")]
        self.assertEqual(_repite_pregunta(pregunta, leida), 6.5)
        self.assertIsNone(_repite_pregunta(pregunta, propia))
        self.assertIsNone(_repite_pregunta(pregunta, []))
