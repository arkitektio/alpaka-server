# api/models.py
from django.db import models
from authentikate.models import User


class ChromaCollection(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional: ownership or visibility
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    embedder = models.ForeignKey(
        "llm.LLMModel", on_delete=models.CASCADE, related_name="embedder_for"
    )

    def __str__(self):
        return self.name