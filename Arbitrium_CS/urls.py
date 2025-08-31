from django.contrib import admin
from django.urls import path
from base.views import dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
]
