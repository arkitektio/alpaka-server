"""Usage accounting and budgets.

Every LLM call the gateway makes is recorded as a :class:`llm.models.UsageRecord`
through :func:`record_usage` (or the :func:`track_usage` / :func:`atrack_usage`
context managers), and :func:`enforce_budget` is called *before* a call so a
spent hard :class:`llm.models.Budget` blocks it.

Design rules:

- Recording never raises. Accounting must not be able to fail an LLM response.
- Token counts come from the provider when it reports them; for streams the
  final ``usage`` chunk is used, else litellm rebuilds the response and counts
  with tiktoken (approximate for non-OpenAI tokenizers).
- Cost is whatever litellm can price. Models missing from its price map get a
  ``None`` cost, so cost budgets under-count for those; use token budgets there.
- :class:`BudgetExceeded` must be raised outside ``wrap_llm_errors``, which
  rewraps every exception into a generic "LLM request failed" message.
"""

import contextlib
import datetime as dt
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator, Iterator, Optional, Sequence

import litellm
from asgiref.sync import sync_to_async
from authentikate.models import Client, Organization, User
from django.db.models import Q, Sum
from django.utils import timezone

from llm.enums import BudgetPeriod, UsageEndpoint, UsageStatus
from llm.models import Budget, LLMModel, UsageRecord

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised before an LLM call when a hard budget is already spent."""

    def __init__(self, budget: Budget, kind: str, used: Any, limit: Any) -> None:
        self.budget = budget
        self.kind = kind
        self.used = used
        self.limit = limit
        super().__init__(f"Budget {budget.pk} exceeded: {used} of {limit} {kind} used this {budget.period}")


@dataclass
class UsageFacts:
    """Token counts and cost of one call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Extracting usage from litellm responses
# ---------------------------------------------------------------------------


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _get(container: Any, key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key)
    return getattr(container, key, None)


def cost_from_tokens(model_string: Optional[str], prompt_tokens: int, completion_tokens: int, *, call_type: str = "completion") -> Optional[Decimal]:
    """Price a token count with litellm's model map, or ``None`` if the model is unknown."""
    if not model_string or (prompt_tokens == 0 and completion_tokens == 0):
        return None
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(model=model_string, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, call_type=call_type)
    except Exception:
        logger.debug("No price for %s", model_string, exc_info=True)
        return None
    return _decimal(prompt_cost + completion_cost)


def cost_of(response: Any, *, model_string: Optional[str] = None, call_type: str = "completion") -> Optional[Decimal]:
    """The cost litellm attached to ``response``, or its estimate, or ``None``."""
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
        return _decimal(hidden["response_cost"])
    if isinstance(response, dict):
        return None
    try:
        return _decimal(litellm.completion_cost(completion_response=response, model=model_string, call_type=call_type))
    except Exception:
        logger.debug("Could not price response for %s", model_string, exc_info=True)
        return None


def usage_from_response(response: Any, *, model_string: Optional[str] = None, call_type: str = "completion") -> UsageFacts:
    """Read token counts and cost from a litellm response (or a raw JSON dict)."""
    facts = UsageFacts()
    usage = _get(response, "usage") if response is not None else None
    if usage is not None:
        prompt = _int(_get(usage, "prompt_tokens")) or _int(_get(usage, "input_tokens"))
        completion = _int(_get(usage, "completion_tokens")) or _int(_get(usage, "output_tokens"))
        # Embedding responses report total_tokens=0 alongside a real prompt count.
        total = _int(_get(usage, "total_tokens")) or (prompt + completion)
        facts = UsageFacts(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)

    facts.cost = cost_of(response, model_string=model_string, call_type=call_type)
    if facts.cost is None:
        facts.cost = cost_from_tokens(model_string, facts.prompt_tokens, facts.completion_tokens, call_type=call_type)
    return facts


def usage_from_stream(chunks: Sequence[Any], *, messages: Optional[list] = None, model_string: Optional[str] = None, text_completion: bool = False) -> UsageFacts:
    """Token counts and cost of a streamed response.

    Prefers the usage the provider put on its final chunk (``stream_options:
    {include_usage: true}``); otherwise litellm reassembles the chunks and
    counts tokens itself.
    """
    if not chunks:
        return UsageFacts()

    for chunk in reversed(chunks):
        usage = getattr(chunk, "usage", None)
        if usage is not None and _int(getattr(usage, "total_tokens", 0)) > 0:
            facts = UsageFacts(
                prompt_tokens=_int(usage.prompt_tokens),
                completion_tokens=_int(usage.completion_tokens),
                total_tokens=_int(usage.total_tokens),
            )
            facts.cost = cost_from_tokens(model_string, facts.prompt_tokens, facts.completion_tokens)
            return facts

    try:
        if text_completion:
            built = litellm.stream_chunk_builder_text_completion(list(chunks))
        else:
            built = litellm.stream_chunk_builder(list(chunks), messages=messages or [])
    except Exception:
        logger.debug("Could not rebuild stream for usage", exc_info=True)
        return UsageFacts()
    if built is None:
        return UsageFacts()
    return usage_from_response(built, model_string=model_string)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def _instance_or_none(value: Any, cls: type) -> Any:
    return value if isinstance(value, cls) else None


def record_usage(
    *,
    organization: Organization,
    user: Optional[User] = None,
    client: Optional[Client] = None,
    model: Optional[LLMModel] = None,
    endpoint: UsageEndpoint,
    facts: Optional[UsageFacts] = None,
    started_at: Optional[float] = None,
    error: Optional[BaseException] = None,
) -> Optional[UsageRecord]:
    """Persist one call. Never raises: accounting cannot fail an LLM response."""
    try:
        if not isinstance(organization, Organization):
            logger.warning("Usage not recorded: no organization (endpoint=%s)", endpoint)
            return None
        facts = facts or UsageFacts()
        latency_ms = int((time.monotonic() - started_at) * 1000) if started_at is not None else None
        provider = getattr(model, "provider", None)
        kind = getattr(provider, "kind", "") or ""
        error_type = ""
        if error is not None:
            cause = error.__cause__ or error
            error_type = type(cause).__name__[:128]
        return UsageRecord.objects.for_write().create(
            organization=organization,
            user=_instance_or_none(user, User),
            client=_instance_or_none(client, Client),
            model=_instance_or_none(model, LLMModel),
            provider_kind=str(getattr(kind, "value", kind))[:50],
            model_identifier=str(getattr(model, "model_id", "") or "")[:255],
            llm_string=str(getattr(model, "llm_string", "") or "")[:512],
            endpoint=getattr(endpoint, "value", endpoint),
            prompt_tokens=max(facts.prompt_tokens, 0),
            completion_tokens=max(facts.completion_tokens, 0),
            total_tokens=max(facts.total_tokens, 0),
            cost=facts.cost,
            latency_ms=latency_ms,
            status=UsageStatus.ERROR.value if error is not None else UsageStatus.OK.value,
            error_type=error_type,
        )
    except Exception:
        logger.exception("Failed to record LLM usage")
        return None


arecord_usage = sync_to_async(record_usage)


class UsageTracker:
    """Collects the response of a tracked call so the context manager can record it."""

    def __init__(self, model_string: Optional[str]) -> None:
        self.model_string = model_string
        self.response: Any = None
        self.call_type = "completion"
        self.facts: Optional[UsageFacts] = None

    def set(self, response: Any, *, call_type: str = "completion") -> None:
        """Remember the litellm response (or raw JSON) to read usage from."""
        self.response = response
        self.call_type = call_type

    def set_facts(self, facts: UsageFacts) -> None:
        """Provide already-computed usage instead of a response."""
        self.facts = facts

    def resolve(self) -> UsageFacts:
        """The usage to record."""
        if self.facts is not None:
            return self.facts
        if self.response is not None:
            return usage_from_response(self.response, model_string=self.model_string, call_type=self.call_type)
        return UsageFacts()


@contextlib.contextmanager
def track_usage(*, organization: Organization, user: Optional[User], client: Optional[Client], model: Optional[LLMModel], endpoint: UsageEndpoint) -> Iterator[UsageTracker]:
    """Record the call made inside the block, whether it succeeds or fails (sync)."""
    tracker = UsageTracker(getattr(model, "llm_string", None))
    started = time.monotonic()
    try:
        yield tracker
    except Exception as e:
        record_usage(organization=organization, user=user, client=client, model=model, endpoint=endpoint, facts=tracker.resolve(), started_at=started, error=e)
        raise
    record_usage(organization=organization, user=user, client=client, model=model, endpoint=endpoint, facts=tracker.resolve(), started_at=started)


@contextlib.asynccontextmanager
async def atrack_usage(*, organization: Organization, user: Optional[User], client: Optional[Client], model: Optional[LLMModel], endpoint: UsageEndpoint) -> AsyncIterator[UsageTracker]:
    """Record the call made inside the block, whether it succeeds or fails (async)."""
    tracker = UsageTracker(getattr(model, "llm_string", None))
    started = time.monotonic()
    try:
        yield tracker
    except Exception as e:
        await arecord_usage(organization=organization, user=user, client=client, model=model, endpoint=endpoint, facts=tracker.resolve(), started_at=started, error=e)
        raise
    await arecord_usage(organization=organization, user=user, client=client, model=model, endpoint=endpoint, facts=tracker.resolve(), started_at=started)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def period_start(period: "BudgetPeriod | str", now: Optional[dt.datetime] = None) -> dt.datetime:
    """The UTC start of the current period: midnight, Monday, or the 1st."""
    now = now or timezone.now()
    value = getattr(period, "value", period)
    start = now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if value == BudgetPeriod.WEEK.value:
        start -= dt.timedelta(days=start.weekday())
    elif value == BudgetPeriod.MONTH.value:
        start = start.replace(day=1)
    return start


def period_end(period: "BudgetPeriod | str", now: Optional[dt.datetime] = None) -> dt.datetime:
    """The exclusive UTC end of the current period."""
    start = period_start(period, now)
    value = getattr(period, "value", period)
    if value == BudgetPeriod.DAY.value:
        return start + dt.timedelta(days=1)
    if value == BudgetPeriod.WEEK.value:
        return start + dt.timedelta(days=7)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


@dataclass
class BudgetConsumption:
    """How much of a budget has been used in the current period."""

    budget: Budget
    period_start: dt.datetime
    period_end: dt.datetime
    used_tokens: int
    used_cost: Decimal

    @property
    def remaining_tokens(self) -> Optional[int]:
        if self.budget.limit_tokens is None:
            return None
        return max(self.budget.limit_tokens - self.used_tokens, 0)

    @property
    def remaining_cost(self) -> Optional[Decimal]:
        if self.budget.limit_cost is None:
            return None
        return max(self.budget.limit_cost - self.used_cost, Decimal(0))

    @property
    def breached(self) -> Optional[tuple[str, Any, Any]]:
        """``(kind, used, limit)`` for the first exceeded limit, or ``None``."""
        if self.budget.limit_tokens is not None and self.used_tokens >= self.budget.limit_tokens:
            return ("tokens", self.used_tokens, self.budget.limit_tokens)
        if self.budget.limit_cost is not None and self.used_cost >= self.budget.limit_cost:
            return ("USD", self.used_cost, self.budget.limit_cost)
        return None

    @property
    def exceeded(self) -> bool:
        return self.breached is not None


def applicable_budgets(organization: Organization, user: Optional[User], model: Optional[LLMModel]):
    """The budgets that govern a call by ``user`` to ``model`` in ``organization``."""
    user_id = getattr(user, "pk", None) if isinstance(user, User) else None
    model_id = getattr(model, "pk", None) if isinstance(model, LLMModel) else None
    return Budget.objects.for_organization(organization).filter(Q(user__isnull=True) | Q(user_id=user_id)).filter(Q(model__isnull=True) | Q(model_id=model_id)).order_by("id")


def consumption_for(budgets: Sequence[Budget], now: Optional[dt.datetime] = None) -> list[BudgetConsumption]:
    """Current-period consumption for each budget, in one aggregate query."""
    budgets = list(budgets)
    if not budgets:
        return []
    now = now or timezone.now()
    starts = {budget.pk: period_start(budget.period, now) for budget in budgets}

    aggregates: dict[str, Any] = {}
    for budget in budgets:
        scope = Q(created_at__gte=starts[budget.pk])
        if budget.user_id:
            scope &= Q(user_id=budget.user_id)
        if budget.model_id:
            scope &= Q(model_id=budget.model_id)
        aggregates[f"tokens_{budget.pk}"] = Sum("total_tokens", filter=scope)
        aggregates[f"cost_{budget.pk}"] = Sum("cost", filter=scope)

    organization_id = budgets[0].organization_id
    row = UsageRecord.objects.for_organization(organization_id).filter(created_at__gte=min(starts.values())).aggregate(**aggregates)

    return [
        BudgetConsumption(
            budget=budget,
            period_start=starts[budget.pk],
            period_end=period_end(budget.period, now),
            used_tokens=_int(row.get(f"tokens_{budget.pk}")),
            used_cost=_decimal(row.get(f"cost_{budget.pk}")) or Decimal(0),
        )
        for budget in budgets
    ]


def enforce_budget(organization: Organization, user: Optional[User], model: Optional[LLMModel], now: Optional[dt.datetime] = None) -> None:
    """Raise :class:`BudgetExceeded` if a hard budget governing this call is spent.

    Soft budgets only log. Call this *before* the LLM request, outside
    ``wrap_llm_errors``.
    """
    if not isinstance(organization, Organization):
        return
    for consumption in consumption_for(applicable_budgets(organization, user, model), now):
        breach = consumption.breached
        if breach is None:
            continue
        kind, used, limit = breach
        if consumption.budget.hard:
            raise BudgetExceeded(consumption.budget, kind, used, limit)
        logger.warning("Soft budget %s exceeded: %s of %s %s", consumption.budget.pk, used, limit, kind)


aenforce_budget = sync_to_async(enforce_budget)
