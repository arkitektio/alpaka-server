from django.contrib import admin

from kammer import models

# Register your models here.
admin.site.register(models.Room)
admin.site.register(models.Agent)
admin.site.register(models.Structure)
