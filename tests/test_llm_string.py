"""``LLMModel.llm_string`` must be a litellm-routable string.

litellm routes on the prefix before the first ``/``, which has to be one of its
provider keys. ``Provider.kind`` is authoritative for that; ``Provider.name``
is a free-form display name, and deriving the prefix from it made any provider
with a custom name ("My OpenRouter") silently unroutable.

Needs Django configured but no database (unsaved model instances).
"""

from llm.models import LLMModel, Provider


def make(kind: str, name: str = "My Fancy Provider", model_id: str = "gpt-4") -> LLMModel:
    return LLMModel(provider=Provider(name=name, kind=kind), model_id=model_id)


def test_routes_by_kind_not_display_name():
    assert make("openrouter", name="My OpenRouter").llm_string == "openrouter/gpt-4"


def test_kind_prefix_differs_from_kind_value_where_litellm_does():
    assert make("google", model_id="gemini-pro").llm_string == "gemini/gemini-pro"
    assert make("aws", model_id="claude-3").llm_string == "bedrock/claude-3"


def test_ollama_models_route_with_ollama_prefix():
    assert make("ollama", name="Local Ollama", model_id="llama3").llm_string == "ollama/llama3"


def test_custom_and_unknown_kinds_fall_back_to_name():
    # The name-based convention is all the routing information such a provider
    # carries, so it is preserved for them.
    assert make("custom", name="mygateway").llm_string == "mygateway/gpt-4"
    assert make("unknown", name="legacy").llm_string == "legacy/gpt-4"
