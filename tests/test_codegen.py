"""`scripts/generate.py`: which operations it covers, what it prunes, the 409 facts, and events."""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from doctronic._generated.events import STREAM_EVENTS, WEBHOOK_EVENTS
from doctronic._generated.operations import CONTRACT_VERSION, OPERATIONS
from tests.helpers import ROOT, load_generator, load_script, pinned_contract

generate = load_generator()
contract_changes = load_script("contract_changes")

SLOT_TAKEN = "error.appointments.slot_unavailable"
PAYLOAD_MISMATCH = "error.idempotency.payload_mismatch"
CONCURRENT = "error.idempotency.concurrent_request"


def with_browser_operations(contract: dict[str, Any]) -> dict[str, Any]:
    """The contract plus operations that a browser session token calls, as the embed docs add.

    Their schemas reuse the names `role` and `state` for new enums. If the generator kept those
    schemas, datamodel-code-generator would rename the SDK's `Role` and `State` to avoid them.
    """
    contract = copy.deepcopy(contract)
    contract["components"]["securitySchemes"]["BrowserSessionToken"] = {
        "type": "http",
        "scheme": "bearer",
    }
    schemas = contract["components"]["schemas"]
    schemas["BrowserTheme"] = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": ["visitor", "host"]},
            "state": {"type": "string", "enum": ["open", "closed"]},
        },
    }
    schemas["BrowserConfig"] = {
        "type": "object",
        "properties": {
            "theme": {"$ref": "#/components/schemas/BrowserTheme"},
            "chat": {"$ref": "#/components/schemas/ChatResponse"},  # Shared with the SDK.
        },
    }
    schemas["UnusedByAnyOperation"] = {"type": "object", "properties": {"x": {"type": "string"}}}
    response = {
        "200": {
            "description": "OK",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/BrowserConfig"}}
            },
        }
    }
    contract["paths"]["/browser/config/"] = {
        "get": {"operationId": "browser_config", "security": [], "responses": response}
    }
    contract["paths"]["/browser/chats/{chatId}/rating/"] = {
        "post": {
            "operationId": "browser_rating",
            "security": [{"BrowserSessionToken": []}],
            "responses": response,
        }
    }
    return contract


def with_retryable_codes(contract: dict[str, Any], *, extension: object) -> dict[str, Any]:
    contract = copy.deepcopy(contract)
    conflict = contract["paths"]["/appointments/scheduled/"]["post"]["responses"]["409"]
    media = conflict["content"]["application/json"]
    media.pop("example", None)
    media["examples"] = {
        name: {"value": {"code": code, "message": "x", "data": None}}
        for name, code in [
            ("slot", SLOT_TAKEN),
            ("mismatch", PAYLOAD_MISMATCH),
            ("busy", CONCURRENT),
        ]
    }
    conflict.pop("x-doctronic-retryable-codes", None)
    if extension is not None:
        conflict["x-doctronic-retryable-codes"] = extension
    return contract


def facts(contract: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(op["method"], op["path"]): op for op in generate.build_operations(contract)}


def test_the_pinned_contract_gives_the_committed_operations() -> None:
    operations = facts(pinned_contract())

    assert set(operations) == set(OPERATIONS)
    for key, op in operations.items():
        committed = OPERATIONS[key]
        assert op["idempotent"] is committed.idempotent
        assert op["user_scoped"] is committed.user_scoped
        assert op["stream"] is committed.stream
        assert op["data_required"] is committed.data_required
        assert set(op["statuses"]) == committed.statuses
        assert set(op["conflict_codes"]) == committed.conflict_codes


def test_the_pinned_contract_is_the_default() -> None:
    assert Path(generate.PINNED_CONTRACT) == ROOT / "openapi" / "doctronic-v1.json"
    assert pinned_contract()["info"]["version"] == CONTRACT_VERSION
    # The embed operations take a browser session token, not the organization API token.
    skipped = generate.skipped_operations(pinned_contract())
    assert skipped
    assert all(path.startswith("/embed/") for _, path in skipped)


def test_operations_without_organization_security_are_skipped() -> None:
    contract = with_browser_operations(pinned_contract())

    assert generate.skipped_operations(contract) == [
        *generate.skipped_operations(pinned_contract()),
        ("GET", "/browser/config/"),
        ("POST", "/browser/chats/{chatId}/rating/"),
    ]
    assert facts(contract) == facts(pinned_contract())


def test_schemas_only_skipped_operations_use_are_pruned() -> None:
    contract = with_browser_operations(pinned_contract())

    pruned = generate.organization_contract(contract)

    schemas = pruned["components"]["schemas"]
    assert "BrowserConfig" not in schemas
    assert "BrowserTheme" not in schemas
    assert "ChatResponse" in schemas  # An SDK operation uses it too.
    assert "UnusedByAnyOperation" in schemas  # No operation uses it, so it isn't pruned.
    assert "/browser/config/" not in pruned["paths"]
    assert pruned["components"]["schemas"].keys() == {
        *generate.organization_contract(pinned_contract())["components"]["schemas"],
        "UnusedByAnyOperation",
    }
    assert "/browser/config/" in contract["paths"]  # The input isn't modified.


def _generator_supports_this_python() -> bool:
    from datamodel_code_generator import PythonVersion

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    return running in {version.value for version in PythonVersion}


@pytest.mark.skipif(
    not _generator_supports_this_python(),
    reason="The pinned datamodel-code-generator doesn't run on this Python. CI generates on 3.13.",
)
def test_skipped_operations_leave_the_models_unchanged(tmp_path: Path) -> None:
    contract = with_browser_operations(pinned_contract())
    del contract["components"]["schemas"]["UnusedByAnyOperation"]
    output = tmp_path / "models.py"

    generate.generate_models(generate.organization_contract(contract), output)

    # Compared as syntax trees: the formatter's line breaks depend on the output directory.
    committed = ROOT / "src" / "doctronic" / "_generated" / "models.py"
    assert ast.dump(ast.parse(output.read_text(encoding="utf-8"))) == ast.dump(
        ast.parse(committed.read_text(encoding="utf-8"))
    )


def test_a_contract_without_the_organization_scheme_is_rejected() -> None:
    contract = pinned_contract()
    del contract["components"]["securitySchemes"]["HTTPBearer"]

    with pytest.raises(SystemExit, match="HTTPBearer"):
        generate.build_operations(contract)


def test_documented_409_codes_are_final_without_the_extension() -> None:
    contract = with_retryable_codes(pinned_contract(), extension=None)

    operation = facts(contract)[("POST", "/appointments/scheduled/")]

    assert operation["conflict_codes"] == sorted([SLOT_TAKEN, PAYLOAD_MISMATCH, CONCURRENT])


def test_codes_the_extension_lists_are_retryable() -> None:
    contract = with_retryable_codes(pinned_contract(), extension=[CONCURRENT])

    operation = facts(contract)[("POST", "/appointments/scheduled/")]

    assert operation["conflict_codes"] == sorted([SLOT_TAKEN, PAYLOAD_MISMATCH])


@pytest.mark.parametrize("extension", ["error.idempotency.concurrent_request", [1], [""], {"a": 1}])
def test_a_malformed_extension_is_rejected(extension: object) -> None:
    contract = with_retryable_codes(pinned_contract(), extension=extension)

    with pytest.raises(SystemExit, match="x-doctronic-retryable-codes"):
        generate.build_operations(contract)


def test_change_report_lists_new_removed_and_skipped_operations() -> None:
    old = pinned_contract()
    del old["paths"]["/coverage/"]
    new = with_browser_operations(pinned_contract())
    del new["paths"]["/address/"]["get"]

    lines, counts = contract_changes.report(old, new)

    text = "\n".join(lines)
    assert counts == {"added": 1, "removed": 1, "modified": 0}
    assert "### New operations\n\n- `PUT /coverage/`" in text
    assert "### Removed operations\n\n- `GET /address/`" in text
    assert "- `GET /browser/config/`" in text
    assert "- `POST /browser/chats/{chatId}/rating/`" in text


def test_change_report_for_the_same_contract() -> None:
    lines, counts = contract_changes.report(pinned_contract(), pinned_contract())

    assert counts == {"added": 0, "removed": 0, "modified": 0}
    assert "No operations were added, removed, or changed." in lines


STREAM = ("/chats/{chatId}/stream/", "post", "200", "text/event-stream")


def stream_media(contract: dict[str, Any]) -> dict[str, Any]:
    path, method, status, media_type = STREAM
    media: dict[str, Any] = contract["paths"][path][method]["responses"][status]["content"][
        media_type
    ]
    return media


def test_the_events_table_is_the_pinned_contract_events() -> None:
    contract = generate.organization_contract(pinned_contract())

    stream = generate.stream_events(contract)
    webhooks = generate.webhook_events(contract)

    assert [(name, model.__name__) for name, model in STREAM_EVENTS.items()] == stream
    assert [(name, model.__name__) for name, model in WEBHOOK_EVENTS.items()] == webhooks
    assert set(STREAM_EVENTS) == {
        "message.start",
        "message.content",
        "message.stop",
        "guardian",
        "skill_code.cta",
        "ai_consultation.complete",
        "conversation.offtopic",
        "conversation.end",
        "error",
    }
    assert set(WEBHOOK_EVENTS) == {
        "appointment.call_ended",
        "appointment.practitioner_joined",
        "appointment.waiting_room_ready",
        "artifact.ready",
    }


def test_schemas_the_webhooks_use_are_kept() -> None:
    contract = with_browser_operations(pinned_contract())
    # A skipped operation shares a webhook's schema; the webhook keeps it in the models.
    theme = contract["components"]["schemas"]["BrowserTheme"]
    theme["properties"]["artifact"] = {"$ref": "#/components/schemas/ArtifactReadyData"}

    pruned = generate.organization_contract(contract)

    assert "BrowserTheme" not in pruned["components"]["schemas"]
    assert "ArtifactReadyData" in pruned["components"]["schemas"]
    assert generate.webhook_events(pruned) == generate.webhook_events(contract)


def without_event_schema(contract: dict[str, Any]) -> None:
    del stream_media(contract)["x-doctronic-event-schema"]


def without_webhooks(contract: dict[str, Any]) -> None:
    del contract["webhooks"]


def with_empty_webhooks(contract: dict[str, Any]) -> None:
    contract["webhooks"] = {}


def with_inline_event_schema(contract: dict[str, Any]) -> None:
    stream_media(contract)["x-doctronic-event-schema"] = {"type": "object"}


def with_mismatched_event_type(contract: dict[str, Any]) -> None:
    event = contract["components"]["schemas"]["StreamChatGuardianEvent"]
    event["properties"]["type"]["const"] = "guardian.v2"


def with_undiscriminated_events(contract: dict[str, Any]) -> None:
    del contract["components"]["schemas"]["StreamChatEvent"]["discriminator"]


def without_signature_header(contract: dict[str, Any]) -> None:
    contract["webhooks"]["artifact.ready"]["post"]["parameters"] = []


def without_required_occurred_at(contract: dict[str, Any]) -> None:
    payload = contract["components"]["schemas"]["ArtifactReadyPayload"]
    payload["required"] = [name for name in payload["required"] if name != "occurredAt"]


def with_mismatched_webhook_event(contract: dict[str, Any]) -> None:
    payload = contract["components"]["schemas"]["ArtifactReadyPayload"]
    payload["properties"]["event"]["const"] = "artifact.created"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (without_event_schema, "has no `x-doctronic-event-schema`"),
        (with_inline_event_schema, r"must be a `\$ref`"),
        (with_undiscriminated_events, "discriminator"),
        (with_mismatched_event_type, "'guardian'"),
        (without_webhooks, "no `webhooks`"),
        (with_empty_webhooks, "no `webhooks`"),
        (without_signature_header, "X-Doctronic-Signature"),
        (without_required_occurred_at, "occurredAt"),
        (with_mismatched_webhook_event, "'artifact.ready'"),
    ],
    ids=lambda value: getattr(value, "__name__", ""),
)
def test_a_contract_without_the_event_models_fails_loudly(
    change: Any, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = pinned_contract()
    change(contract)
    source = tmp_path / "contract.json"
    source.write_text(json.dumps(contract), encoding="utf-8")
    output = tmp_path / "_generated"
    monkeypatch.setattr(generate, "OUTPUT_DIR", output)
    monkeypatch.setattr(sys, "argv", ["generate.py", "--contract", str(source)])

    with pytest.raises(SystemExit, match=message):
        generate.main()

    assert not output.exists()  # Nothing written, so the previous output stays.
