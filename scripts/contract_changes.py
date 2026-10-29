"""Report what changed between two copies of the Doctronic OpenAPI contract, as Markdown.

Usage:
    uv run python scripts/contract_changes.py <old path|url> <new path|url> [--outputs FILE]

Lists the operations the SDK gains and loses, the ones whose runtime facts changed (see
`scripts/generate.py`), and operations the SDK skips because they don't use organization
security. With `--outputs`, also appends `key=value` lines for GitHub Actions to FILE:
`changed`, `added`, `removed`, `modified`, `old-sha256`, `new-sha256`, and `version`.

`regenerate.yml` uses it for the pull request body, and `contract-drift.yml` for its summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from generate import build_operations, load_contract, skipped_operations

Key = tuple[str, str]


def _operations(contract: dict[str, Any]) -> dict[Key, dict[str, Any]]:
    return {(op["method"], op["path"]): op for op in build_operations(contract)}


def _digest(contract: dict[str, Any], source: str) -> str:
    if Path(source).is_file():
        return hashlib.sha256(Path(source).read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


def _summary(contract: dict[str, Any], key: Key) -> str:
    method, path = key
    operation = contract["paths"][path][method.lower()]
    summary = operation.get("summary") or operation.get("operationId", "")
    return f"- `{method} {path}`" + (f": {summary}" if summary else "")


def _changed_facts(before: dict[str, Any], after: dict[str, Any]) -> str:
    return "; ".join(
        f"`{field}` {json.dumps(before.get(field))} to {json.dumps(after.get(field))}"
        for field in sorted(before.keys() | after.keys())
        if field not in ("method", "path") and before.get(field) != after.get(field)
    )


def report(old: dict[str, Any], new: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    before, after = _operations(old), _operations(new)
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    modified = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
    skipped = sorted(set(skipped_operations(new)) - set(skipped_operations(old)))

    old_version = old.get("info", {}).get("version", "")
    new_version = new.get("info", {}).get("version", "")
    lines = [
        f"Contract version: `{old_version}` to `{new_version}`."
        if old_version != new_version
        else f"Contract version: `{new_version}` (unchanged).",
        "",
    ]
    if added:
        lines += ["### New operations", "", *(_summary(new, key) for key in added), ""]
        lines += [
            "Their models and runtime facts are generated. Each needs a hand-written resource "
            "method in `src/doctronic/resources/` and an entry in `RESOURCES` in "
            "`tests/test_models.py`; the tests fail until then.",
            "",
        ]
    if removed:
        lines += ["### Removed operations", "", *(_summary(old, key) for key in removed), ""]
        lines += ["Remove their resource methods; the tests fail until then.", ""]
    if modified:
        lines += ["### Operations whose runtime facts changed", ""]
        lines += [
            f"{_summary(new, key)}. {_changed_facts(before[key], after[key])}" for key in modified
        ]
        lines += [""]
    if skipped:
        lines += ["### New operations the SDK skips (no organization `HTTPBearer` security)", ""]
        lines += [*(_summary(new, key) for key in skipped), ""]
    if not (added or removed or modified or skipped):
        lines += ["No operations were added, removed, or changed.", ""]
    counts = {"added": len(added), "removed": len(removed), "modified": len(modified)}
    return lines, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("old", help="Path or URL of the earlier contract")
    parser.add_argument("new", help="Path or URL of the later contract")
    parser.add_argument("--outputs", help="Append GitHub Actions outputs to this file")
    args = parser.parse_args()

    old, new = load_contract(args.old), load_contract(args.new)
    lines, counts = report(old, new)
    print("\n".join(lines).rstrip())
    if args.outputs:
        old_sha, new_sha = _digest(old, args.old), _digest(new, args.new)
        values = {
            "changed": str(old_sha != new_sha).lower(),
            **{key: str(value) for key, value in counts.items()},
            "old-sha256": old_sha,
            "new-sha256": new_sha,
            "version": str(new.get("info", {}).get("version", "")),
        }
        with open(args.outputs, "a", encoding="utf-8") as output:
            output.writelines(f"{key}={value}\n" for key, value in values.items())


if __name__ == "__main__":
    main()
