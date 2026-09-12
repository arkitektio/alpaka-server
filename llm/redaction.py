"""Masking for credential-bearing provider configuration.

``Provider.additional_config`` is a free-form JSON blob. It carries harmless
settings (region, deployment name, api version) alongside things that are
effectively passwords, and there is no schema saying which is which. Rather
than withhold the whole blob — clients genuinely need to read the harmless
half — every key whose *name* suggests a credential is masked on the way out.

The check is on the key name, not the value: a name-based rule fails closed for
anything conventionally named, and it never mistakes a legitimate setting for a
secret the way entropy heuristics do.
"""

from typing import Any

REDACTED = "**********"

#: Substrings that mark a key as credential-bearing. Matched case-insensitively
#: against the key with separators stripped, so ``api_key``, ``apiKey`` and
#: ``API-KEY`` all match ``apikey``.
SECRET_KEY_MARKERS = (
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "auth",
    "signature",
    "salt",
    "session",
)


def _is_secret_key(key: str) -> bool:
    """Whether a config key's name marks it as credential-bearing."""
    normalized = key.lower().replace("_", "").replace("-", "").replace(" ", "")
    return any(marker in normalized for marker in SECRET_KEY_MARKERS)


def redact_config(config: Any) -> Any:
    """Return ``config`` with the value of every secret-looking key masked.

    Recurses through nested mappings and lists so a credential nested under
    ``{"headers": {"Authorization": ...}}`` is masked too. Non-mapping values
    are returned unchanged, and ``None`` stays ``None`` so an unset config is
    still distinguishable from an empty one.
    """
    if isinstance(config, dict):
        return {key: REDACTED if _is_secret_key(str(key)) else redact_config(value) for key, value in config.items()}
    if isinstance(config, list):
        return [redact_config(item) for item in config]
    return config
