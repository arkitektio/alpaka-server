"""Typed decision models: the counterpart of chat.

A decision ("System One") model does not generate text. It takes a ``state``
(a string, JSON object or array) and a map of named, typed questions -- ``noul``
(yes/no), ``choice`` (one of named options) and ``score`` (an ordered rubric) --
and answers all of them with calibrated probabilities in one call.

Several runtimes speak the same wire protocol (``POST /v1/systemone``,
``GET /v1/models``): TypeSafe's hosted Jev and a self-hosted Ollaya among them.
The backend is picked by ``Provider.kind``; nothing outside this package knows
which one answered. litellm has no such call shape, which is why this lives next
to it rather than behind it.
"""

from .backends import (
    DECISION_BACKENDS,
    DecisionBackend,
    DecisionError,
    DecisionModelInfo,
    OllayaBackend,
    SystemOneBackend,
    backend_for,
    is_decision_kind,
)

__all__ = [
    "DECISION_BACKENDS",
    "DecisionBackend",
    "DecisionError",
    "DecisionModelInfo",
    "OllayaBackend",
    "SystemOneBackend",
    "backend_for",
    "is_decision_kind",
]
