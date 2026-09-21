from django.contrib import admin
from django.urls import include, path


handler400 = "website.error_views.bad_request"
handler403 = "website.error_views.permission_denied"
handler404 = "website.error_views.page_not_found"
handler500 = "website.error_views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),

    # Landing page / autenticação
    path("", include("website.urls", namespace="website")),

    # Questionários
    path("polls/", include("polls.urls", namespace="polls")),
]
