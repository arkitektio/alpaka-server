# api/models.py
from django.db import models
from llm.enums import FeatureType

class Provider(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    api_key = models.TextField(blank=True, null=True)
    api_base = models.URLField(blank=True, null=True)
    additional_config = models.JSONField(blank=True, null=True)
    creator = models.ForeignKey(
        "authentikate.User", on_delete=models.CASCADE, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ("name", "api_key")
    


class LLMModel(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="models")
    model_id = models.CharField(max_length=255)
    label = models.CharField(max_length=255)
    features = models.JSONField(default=list, blank=True, null=True)
    
    
    @property
    def is_available(self):
        return True
    
    
    @property
    def llm_string(self):
        return f"{self.provider.name}/{self.model_id}"
    
    
    def get_features(self):
        return self.features or []
    
    def has_feature(self, feature: FeatureType):
        return feature in self.get_features()
   
