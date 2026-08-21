"""Read-side resolvers for the llm app."""

from .provider import default_model_for, llm_model, provider

__all__ = ["default_model_for", "llm_model", "provider"]
