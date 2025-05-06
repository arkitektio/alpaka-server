# api/models.py
from django.db import models


class Provider(models.Model):
    name = models.CharField(max_length=100, unique=True)
    api_key = models.TextField(blank=True, null=True)
    api_base = models.URLField(blank=True, null=True)
    additional_config = models.JSONField(blank=True, null=True)


class LLMModel(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="models")
    model_id = models.CharField(max_length=255)
    label = models.CharField(max_length=255)
