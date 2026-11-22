import decimal

import strawberry
from strawberry import scalars

from llm import enums


@strawberry.input(description="A large language model to change with")
class ProviderInput:
    """A large language model provider"""

    description: str | None = None
    name: str | None = None
    kind: enums.ProviderKind
    api_key: str | None = None
    api_base: str | None = None
    additional_config: scalars.JSON | None = None


@strawberry.input(description="A large language model function defintion")
class FunctionDefinitionInput:
    """A function definition for a large language model"""

    name: str
    description: str | None = None
    parameters: scalars.JSON | None = None  # JSON Schema object


@strawberry.input(description="A large language model function call")
class ToolInput:
    """A function call for a large language model"""

    type: enums.ToolType = enums.ToolType.FUNCTION
    function: FunctionDefinitionInput


# --- CHAT INPUT MESSAGES ---


@strawberry.input(description="A function call input")
class FunctionCallInput:
    """A function call input for a large language model"""

    name: str
    arguments: str


@strawberry.input(description="A tool call input")
class ToolCallInput:
    """A tool call input for a large language model"""

    id: str
    function: FunctionCallInput
    type: enums.ToolType


@strawberry.input(description="A chat message input")
class ChatMessageInput:
    """A chat message input for a large language model"""

    role: enums.Role
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    function_call: FunctionCallInput | None = None
    tool_calls: list[ToolCallInput] | None = None


@strawberry.input(description="A chat completion request")
class ChatInput:
    """A chat completion request for a large language model.

    The optional generation parameters mirror those the OpenAI-compatible REST
    endpoint accepts, so the two front doors take the same request.
    """

    messages: list[ChatMessageInput]
    model: strawberry.ID | None = None
    tools: list[ToolInput] | None = None
    tool_choice: scalars.JSON | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: list[str] | None = None
    n: int | None = None
    response_format: scalars.JSON | None = None


@strawberry.input(description="The image")
class ImageInput:
    model: strawberry.ID | None = None
    description: str


@strawberry.input(description="The input for using a model for a specific task")
class UseModelForInput:
    """The model to register, and the task to register it against."""

    model: strawberry.ID
    kind: enums.DefaultKind


@strawberry.input(description="A budget to create")
class CreateBudgetInput:
    """A new cap on LLM consumption. Applies to the whole organization unless narrowed to a user and/or a model."""

    user: strawberry.ID | None = None
    model: strawberry.ID | None = None
    period: enums.BudgetPeriod = enums.BudgetPeriod.MONTH
    limit_tokens: int | None = None
    limit_cost: decimal.Decimal | None = None
    hard: bool = True


@strawberry.input(
    description="Changes to a budget; omitted fields are left as they are, explicit nulls clear a limit"
)
class UpdateBudgetInput:
    """A partial update of a budget."""

    id: strawberry.ID
    period: enums.BudgetPeriod | None = strawberry.UNSET
    limit_tokens: int | None = strawberry.UNSET
    limit_cost: decimal.Decimal | None = strawberry.UNSET
    hard: bool | None = strawberry.UNSET


@strawberry.input(description="The budget to delete")
class DeleteBudgetInput:
    """The budget to remove."""

    id: strawberry.ID


# --- DECISIONS ---


@strawberry.input(description="A yes/no question or statement about the state")
class NoulQuestionInput:
    """Answered with the probability that the statement is true."""

    key: str = strawberry.field(
        description="Your name for this question; the answer carries it back"
    )
    instructions: str = strawberry.field(
        description="The yes/no question or statement to evaluate"
    )
    if_true: str | None = strawberry.field(
        default=None, description="What counts as a yes"
    )
    if_false: str | None = strawberry.field(
        default=None, description="What counts as a no"
    )


@strawberry.input(description="One option a choice question can pick")
class ChoiceOptionInput:
    """A named option, optionally described."""

    key: str = strawberry.field(
        description="The option's name; the answer picks one of these"
    )
    description: str | None = strawberry.field(
        default=None,
        description="When this option applies; without one the option is read by its name alone",
    )


@strawberry.input(description="A question that picks one of several named options")
class ChoiceQuestionInput:
    """Answered with the most probable option and the probability of each."""

    key: str = strawberry.field(
        description="Your name for this question; the answer carries it back"
    )
    instructions: str = strawberry.field(
        description="What to decide when picking an option"
    )
    options: list[ChoiceOptionInput] = strawberry.field(
        description="The options to choose from"
    )


@strawberry.input(description="A question that rates the state on an ordered rubric")
class ScoreQuestionInput:
    """Answered with the expected level and the probability of each level."""

    key: str = strawberry.field(
        description="Your name for this question; the answer carries it back"
    )
    instructions: str = strawberry.field(description="What to rate")
    levels: list[str] = strawberry.field(
        description="Descriptions of the rubric levels, lowest first; a level's position is its score, starting at zero"
    )


@strawberry.input(
    one_of=True, description="A typed question: exactly one of noul, choice or score"
)
class QuestionInput:
    """One question of a decide request."""

    noul: NoulQuestionInput | None = strawberry.UNSET
    choice: ChoiceQuestionInput | None = strawberry.UNSET
    score: ScoreQuestionInput | None = strawberry.UNSET


@strawberry.input(
    description="Typed questions to put to a decision model about one state"
)
class DecideInput:
    """A decide request: every question is answered about the same state, in one call."""

    state: scalars.JSON = strawberry.field(
        description="The content the questions refer to: a string, a JSON object or an array"
    )
    questions: list[QuestionInput] = strawberry.field(
        description="The questions to answer; their keys must be unique"
    )
    model: strawberry.ID | None = strawberry.field(
        default=None,
        description="The decision model to ask; defaults to the caller's default for `decision`",
    )
