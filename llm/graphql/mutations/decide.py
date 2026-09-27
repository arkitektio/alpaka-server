"""Typed decisions over GraphQL.

The questions are typed inputs rather than a JSON blob, and the answers a typed
union, so a client is checked against the schema instead of against whichever
backend happens to answer. Limits that differ between backends (how many
options, how many rubric levels) are left to the backend, whose refusal comes
back as the error.
"""

import json
from typing import Any, List

from asgiref.sync import sync_to_async
from kante.types import Info

from llm.decision import backend_for
from llm.enums import DefaultKind, UsageEndpoint
from llm.errors import ensure_decision, wrap_llm_errors
from llm.graphql.mutations.chat import resolve_model
from llm.inputs import DecideInput, QuestionInput
from llm.types import ChoiceAnswer, Decision, DecisionAnswer, NoulAnswer, OptionProbability, ScoreAnswer, ScoreLevel, Usage
from llm.usage import aenforce_budget, atrack_usage


class InvalidQuestions(Exception):
    """Raised when a decide request's questions cannot be sent as asked."""


def _unique(keys: List[str], what: str) -> None:
    seen = set()
    for key in keys:
        if not key:
            raise InvalidQuestions(f"Every {what} needs a non-empty key.")
        if key in seen:
            raise InvalidQuestions(f"The {what} key '{key}' is used twice; keys must be unique.")
        seen.add(key)


def serialize_questions(questions: List[QuestionInput]) -> dict:
    """Shape the typed question inputs into the systemone ``questions`` map."""
    if not questions:
        raise InvalidQuestions("Ask at least one question.")

    wire: dict[str, dict] = {}
    keys = []
    for question in questions:
        if question.noul:
            q = question.noul
            body: dict[str, Any] = {"type": "noul", "instructions": q.instructions}
            criteria = {name: text for name, text in (("true", q.if_true), ("false", q.if_false)) if text is not None}
            if criteria:
                body["criteria"] = criteria
        elif question.choice:
            q = question.choice
            _unique([option.key for option in q.options], f"option of '{q.key}'")
            body = {"type": "choice", "instructions": q.instructions, "criteria": {option.key: option.description for option in q.options}}
        elif question.score:
            q = question.score
            body = {"type": "score", "instructions": q.instructions, "criteria": list(q.levels)}
        else:  # pragma: no cover - @oneOf guarantees exactly one
            raise InvalidQuestions("A question must be one of noul, choice or score.")
        keys.append(q.key)
        wire[q.key] = body

    _unique(keys, "question")
    return wire


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def to_answer(key: str, answer: dict) -> DecisionAnswer:
    """Map one wire answer onto the GraphQL union, by its ``type``."""
    kind = answer.get("type")
    if kind == "noul":
        return NoulAnswer(key=key, noul=float(answer["noul"]))
    if kind == "choice":
        return ChoiceAnswer(
            key=key,
            choice=answer["choice"],
            confidence=float(answer["confidence"]),
            probabilities=[OptionProbability(key=option, probability=float(p)) for option, p in answer.get("probabilities", {}).items()],
        )
    if kind == "score":
        legend = answer.get("legend", {})
        probabilities = answer.get("probabilities", {})
        return ScoreAnswer(
            key=key,
            score=float(answer["score"]),
            confidence=float(answer["confidence"]),
            levels=[ScoreLevel(level=int(level), description=_text(legend[level]), probability=float(probabilities.get(level, 0.0))) for level in sorted(legend, key=int)],
        )
    raise ValueError(f"Unknown answer type {kind!r} for question '{key}'")


def to_decision(response: dict, question_keys: List[str]) -> Decision:
    """Map a systemone response onto ``Decision``, answers in question order."""
    answers = response.get("answers", {})
    missing = [key for key in question_keys if key not in answers]
    if missing:
        raise ValueError(f"The model returned no answer for {', '.join(missing)}")
    usage = response.get("usage") or {}
    prompt, completion = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    return Decision(
        model=response.get("model", ""),
        answers=[to_answer(key, answers[key]) for key in question_keys],
        usage=Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion),
    )


async def decide(info: Info, input: DecideInput) -> Decision:
    """Ask a decision model typed questions about one state."""
    questions = serialize_questions(input.questions)
    model = await sync_to_async(resolve_model)(info, input.model, DefaultKind.DECISION)
    ensure_decision(model)

    request = info.context.request
    # Outside wrap_llm_errors on purpose: a spent budget is not an upstream failure.
    await aenforce_budget(request.organization, request.user, model)

    backend = backend_for(model.provider)
    async with atrack_usage(organization=request.organization, user=request.user, client=request.client, model=model, endpoint=UsageEndpoint.GRAPHQL_DECIDE) as track:
        with wrap_llm_errors(model):
            response = await backend.decide(model, input.state, questions)
        track.set_facts(backend.usage_of(response))

    return to_decision(response, list(questions))
