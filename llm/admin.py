from django.contrib import admin

from llm import models

admin.site.register(models.Provider)
admin.site.register(models.ProviderPartner)
admin.site.register(models.LLMModel)
admin.site.register(models.DefaultUse)
admin.site.register(models.UsageRecord)
admin.site.register(models.Budget)
