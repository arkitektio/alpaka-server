import strawberry
from typing import Optional, List
from enum import Enum

# --- ENUMS ---


@strawberry.enum(description="The type of the message sender")
class Role(str, Enum):
    """The role of the message sender in a chat conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    FUNCTION = "function"


@strawberry.enum(description="The type of the tool")
class ToolType(str, Enum):
    """The type of the tool used in a chat conversation."""

    FUNCTION = "function"  # Currently the only one LiteLLM supports


@strawberry.enum(description="The type of the thinking block")
class ThinkingBlockType(str, Enum):
    """The type of the thinking block in a chat conversation."""

    THINKING = "thinking"


@strawberry.enum(description="A capability a model supports")
class FeatureType(str, Enum):
    """A supported feature type for a large language model.

    These are exactly the values ``llm.logic.detect_features`` writes onto
    ``LLMModel.features``; a value missing from here breaks serialization of the
    whole field, which is what ``"vision"`` used to do.
    """

    EMBEDDING = "embedding"
    CHAT = "chat"
    VISION = "vision"


@strawberry.enum(description="A modality a model can read or emit")
class Modality(str, Enum):
    """A kind of content a model accepts as input or produces as output."""

    IMAGE = "image"
    TEXT = "text"
    AUDIO = "audio"
    VIDEO = "video"



@strawberry.enum(description="A task a model can be made the default for")
class DefaultKind(str, Enum):
    """The task a default model is registered against.

    These were free-form strings duplicated across the manager, the REST views
    and both chat mutations; naming them here makes the valid set discoverable
    in the schema.
    """

    TEXT_GENERATION = "text_generation"
    EMBEDDING = "embedding"
    IMAGE_GENERATION = "image_generation"


@strawberry.enum(description="The kind of LLM provider")
class ProviderKind(str, Enum):
    """The kind/type of LLM provider"""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    COHERE = "cohere"
    MISTRAL = "mistral"
    HUGGINGFACE = "huggingface"
    OLLAMA = "ollama"
    AZURE = "azure"
    AWS = "aws"
    VERTEX_AI = "vertex_ai"
    PALM = "palm"
    REPLICATE = "replicate"
    TOGETHER_AI = "together_ai"
    ANYSCALE = "anyscale"
    FIREWORKS_AI = "fireworks_ai"
    DEEPINFRA = "deepinfra"
    PERPLEXITY = "perplexity"
    GROQ = "groq"
    CUSTOM = "custom"
    UNKNOWN = "unknown"
    OPENROUTER = "openrouter"
