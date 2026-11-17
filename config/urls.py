from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "Lecciones Orales · Diseño de Patrones"
admin.site.site_title = "Lecciones Orales"
admin.site.index_title = "Panel del docente"

urlpatterns = [
    path("admin/", RedirectView.as_view(url="/panel/"), name="inicio_docente"),
    path("admin/gestion/", RedirectView.as_view(url="/admin/lecciones/")),
    path("admin/", admin.site.urls),
    path("", include("lecciones.urls")),
]
