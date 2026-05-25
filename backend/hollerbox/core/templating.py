"""${...} reference resolution.

Templates live inside workflow YAML — anywhere a user can write a value, they
can write `${path.to.thing}` and the engine resolves it against the current
run scope (inputs, prior step outputs, secrets, settings, run metadata).

Two cardinal behaviors:

1. **Native-type preservation.** If a value is *entirely* one reference
   (e.g. `${inputs.count}`), the resolved value keeps its native type
   (int, list, dict, bool, etc.). If it is embedded in a larger string
   (e.g. `"count is ${inputs.count}"`), normal string interpolation
   happens.

2. **Secret redaction is opt-in at the call site.** `resolve()` returns
   real values for execution. `resolve(..., redact_secrets=True)` returns
   the same shape with anything that came from `secrets.*` replaced by
   `••••`. The Runner uses the redacted form when snapshotting context to
   the database / logs so secrets never get persisted (§10 of the brief).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SECRET_REDACTION = "••••"

# Match `${...}` even when the inside is empty/whitespace so we can fail
# loudly on `${}` rather than silently treating it as a literal string.
_TEMPLATE_RE = re.compile(r"\$\{([^${}]*)\}")


class UnresolvedReferenceError(ValueError):
    """A `${...}` reference points to a value not present in scope."""


@dataclass
class ResolverScope:
    """All namespaces a template reference may pull from in a single run."""

    inputs: dict[str, Any]
    steps: dict[str, Any]
    secrets: dict[str, Any]
    settings: dict[str, Any]
    run: dict[str, Any]

    def _namespace(self, name: str) -> dict[str, Any]:
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise UnresolvedReferenceError(
                f"Unknown reference namespace '{name}'. "
                "Allowed: inputs, steps, secrets, settings, run."
            ) from exc


def _resolve_path(path: str, scope: ResolverScope, *, redact_secrets: bool) -> Any:
    parts = [p for p in path.strip().split(".") if p]
    if not parts:
        raise UnresolvedReferenceError(f"Empty reference: ${{{path}}}")

    root, *rest = parts
    if root not in {"inputs", "steps", "secrets", "settings", "run"}:
        raise UnresolvedReferenceError(
            f"Unknown reference namespace '{root}' in ${{{path}}}. "
            "Allowed: inputs, steps, secrets, settings, run."
        )

    if root == "secrets" and redact_secrets:
        # Still walk the path so we error on missing references in the same
        # way both modes would — but return the redaction marker instead of
        # the real value.
        _walk(rest, scope._namespace(root), path)
        return SECRET_REDACTION

    return _walk(rest, scope._namespace(root), path)


def _walk(parts: list[str], current: Any, full_path: str) -> Any:
    for depth, part in enumerate(parts, start=1):
        try:
            current = current[part] if isinstance(current, dict) else getattr(current, part)
        except (KeyError, AttributeError, TypeError) as exc:
            raise UnresolvedReferenceError(
                f"Failed to resolve ${{{full_path}}}: missing '{part}' at depth {depth}"
            ) from exc
    return current


def _resolve_string(s: str, scope: ResolverScope, *, redact_secrets: bool) -> Any:
    matches = list(_TEMPLATE_RE.finditer(s))
    if not matches:
        return s

    # Whole-string single reference -> preserve native type.
    only = matches[0]
    if len(matches) == 1 and only.start() == 0 and only.end() == len(s):
        return _resolve_path(only.group(1), scope, redact_secrets=redact_secrets)

    def replace(match: re.Match[str]) -> str:
        value = _resolve_path(match.group(1), scope, redact_secrets=redact_secrets)
        return str(value)

    return _TEMPLATE_RE.sub(replace, s)


def resolve(value: Any, scope: ResolverScope, *, redact_secrets: bool = False) -> Any:
    """Recursively resolve all `${...}` references in `value`.

    Strings, dict values, and list elements are walked. Any other type is
    returned as-is. Raises `UnresolvedReferenceError` on missing references.
    """
    if isinstance(value, str):
        return _resolve_string(value, scope, redact_secrets=redact_secrets)
    if isinstance(value, dict):
        return {k: resolve(v, scope, redact_secrets=redact_secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope, redact_secrets=redact_secrets) for v in value]
    return value


def find_references(value: Any) -> list[str]:
    """Return every `${...}` reference path found inside `value` (no resolution).

    Useful for static analysis — e.g. `hollerbox validate` can list every
    reference a workflow makes without needing a real run scope.
    """
    found: list[str] = []
    _collect(value, found)
    return found


def _collect(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        for m in _TEMPLATE_RE.finditer(value):
            out.append(m.group(1).strip())
    elif isinstance(value, dict):
        for v in value.values():
            _collect(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect(v, out)
