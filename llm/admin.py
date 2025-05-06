from django.contrib import admin

from llm import models

# Register your models here.
admin.site.register(models.Provider)
admin.site.register(models.LLMModel)
