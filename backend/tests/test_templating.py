"""Tests for hollerbox.core.templating."""

from __future__ import annotations

import pytest

from hollerbox.core.templating import (
    SECRET_REDACTION,
    ResolverScope,
    UnresolvedReferenceError,
    find_references,
    resolve,
)


@pytest.fixture
def scope() -> ResolverScope:
    return ResolverScope(
        inputs={"topic": "AI infra", "count": 7, "options": {"deep": True}},
        steps={
            "fetch": {
                "output": {"body": "hello world", "items": [1, 2, 3]},
                "status": "success",
            }
        },
        secrets={"OPENAI_API_KEY": "sk-real-secret"},
        settings={"default_provider": "anthropic"},
        run={"id": "abc123", "date": "2026-05-24", "timestamp": "2026-05-24T12:00:00Z"},
    )


class TestNativeTypePreservation:
    def test_whole_string_int(self, scope):
        assert resolve("${inputs.count}", scope) == 7

    def test_whole_string_dict(self, scope):
        assert resolve("${inputs.options}", scope) == {"deep": True}

    def test_whole_string_list(self, scope):
        assert resolve("${steps.fetch.output.items}", scope) == [1, 2, 3]

    def test_embedded_int_becomes_string(self, scope):
        assert resolve("count=${inputs.count}", scope) == "count=7"

    def test_embedded_dict_becomes_string(self, scope):
        # Embedded references always become strings.
        out = resolve("opts=${inputs.options}", scope)
        assert out == "opts={'deep': True}"


class TestPathResolution:
    def test_dict_walk(self, scope):
        assert resolve("${inputs.topic}", scope) == "AI infra"

    def test_nested_step_output(self, scope):
        assert resolve("${steps.fetch.output.body}", scope) == "hello world"

    def test_settings_namespace(self, scope):
        assert resolve("${settings.default_provider}", scope) == "anthropic"

    def test_run_metadata(self, scope):
        assert resolve("${run.id}", scope) == "abc123"


class TestRecursive:
    def test_dict_values_resolved(self, scope):
        assert resolve({"a": "${inputs.topic}", "b": 42}, scope) == {
            "a": "AI infra",
            "b": 42,
        }

    def test_list_values_resolved(self, scope):
        assert resolve(["${inputs.count}", "literal"], scope) == [7, "literal"]

    def test_passthrough_non_template_types(self, scope):
        assert resolve(42, scope) == 42
        assert resolve(True, scope) is True
        assert resolve(None, scope) is None


class TestSecretRedaction:
    def test_secret_resolves_to_real_value_by_default(self, scope):
        assert resolve("${secrets.OPENAI_API_KEY}", scope) == "sk-real-secret"

    def test_secret_redacted_when_flagged(self, scope):
        assert resolve("${secrets.OPENAI_API_KEY}", scope, redact_secrets=True) == SECRET_REDACTION

    def test_embedded_secret_redacted_in_string(self, scope):
        out = resolve("Bearer ${secrets.OPENAI_API_KEY}", scope, redact_secrets=True)
        assert out == f"Bearer {SECRET_REDACTION}"

    def test_secret_inside_dict_redacted(self, scope):
        out = resolve(
            {"headers": {"Authorization": "Bearer ${secrets.OPENAI_API_KEY}"}},
            scope,
            redact_secrets=True,
        )
        assert out == {"headers": {"Authorization": f"Bearer {SECRET_REDACTION}"}}

    def test_redact_still_errors_on_missing_secret(self, scope):
        with pytest.raises(UnresolvedReferenceError):
            resolve("${secrets.MISSING}", scope, redact_secrets=True)


class TestErrors:
    def test_unknown_namespace(self, scope):
        with pytest.raises(UnresolvedReferenceError, match="namespace"):
            resolve("${nope.foo}", scope)

    def test_missing_dict_key(self, scope):
        with pytest.raises(UnresolvedReferenceError, match="missing 'missing'"):
            resolve("${inputs.missing}", scope)

    def test_missing_deep_key(self, scope):
        with pytest.raises(UnresolvedReferenceError, match="depth 3"):
            resolve("${steps.fetch.output.nope}", scope)

    def test_empty_reference(self, scope):
        with pytest.raises(UnresolvedReferenceError):
            resolve("${}", scope)


class TestFindReferences:
    def test_finds_all(self):
        value = {
            "a": "${inputs.x}",
            "b": "hello ${steps.s.output.y}!",
            "c": ["${secrets.K}", 42, "${run.id}"],
        }
        assert sorted(find_references(value)) == sorted(
            ["inputs.x", "steps.s.output.y", "secrets.K", "run.id"]
        )

    def test_returns_empty_when_no_templates(self):
        assert find_references({"a": 1, "b": [2, "plain"]}) == []
