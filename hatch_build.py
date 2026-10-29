"""Hatchling build hook for the sdist: leave out the repository's `.gitignore`.

Hatchling adds the project's VCS ignore file to every sdist as a forced include, and `exclude`
doesn't apply to forced includes, so the file is removed from them here. pyproject.toml enables
this hook for the sdist target only.
"""

from __future__ import annotations

from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

VCS_IGNORE_FILES = {".gitignore", ".hgignore"}


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        forced: dict[str, str] = build_data.get("force_include", {})
        for source, target in list(forced.items()):
            if target in VCS_IGNORE_FILES:
                del forced[source]
