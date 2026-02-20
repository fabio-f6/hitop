from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('website/', include('website.urls', namespace='website')),
    path('polls/', include('polls.urls', namespace='polls')),
    path('', lambda request: redirect('website:home')),
]
