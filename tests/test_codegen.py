"""`scripts/generate.py`: which operations it covers, what it prunes, and the 409 facts."""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from typing import Any

import pytest

from doctronic._generated.operations import OPERATIONS
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
    assert generate.skipped_operations(pinned_contract()) == []


def test_operations_without_organization_security_are_skipped() -> None:
    contract = with_browser_operations(pinned_contract())

    assert generate.skipped_operations(contract) == [
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
        *pinned_contract()["components"]["schemas"],
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
