from django.urls import path

from . import panel, views

app_name = "lecciones"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("api/ingreso/", views.api_ingreso, name="api_ingreso"),
    path("api/iniciar/", views.api_iniciar, name="api_iniciar"),
    path("api/enviar/", views.api_enviar, name="api_enviar"),
    path("api/interrumpir/", views.api_interrumpir, name="api_interrumpir"),
    path("panel/", panel.panel, name="panel"),
    path("panel/datos/", panel.datos, name="panel_datos"),
    path("panel/sesion/<int:pk>/", panel.detalle, name="panel_detalle"),
    path("panel/accion/", panel.accion, name="panel_accion"),
    path("archivo/<int:pk>/<str:cual>/", views.archivo, name="archivo"),
]
