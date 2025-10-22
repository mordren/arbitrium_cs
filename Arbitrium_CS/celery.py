import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Arbitrium_CS.settings")

app = Celery("Arbitrium_CS")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()