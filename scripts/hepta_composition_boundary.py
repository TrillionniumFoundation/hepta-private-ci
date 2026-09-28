#!/usr/bin/env python3
"""Verify Agentd core and product composition dependency boundaries."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hepta_dependencies(path: Path) -> set[str]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        name
        for name in document.get("dependencies", {})
        if name.startswith("codex-hepta-")
    }


def main() -> None:
    core = hepta_dependencies(ROOT / "codex-rs/hepta-agentd-core/Cargo.toml")
    if core != {"codex-hepta-types"}:
        raise SystemExit(
            "Agentd core dependency boundary changed: " + ", ".join(sorted(core))
        )
    agentd = hepta_dependencies(ROOT / "codex-rs/hepta-agentd/Cargo.toml")
    required = {
        "codex-hepta-agent-protocol",
        "codex-hepta-agentd-core",
        "codex-hepta-agent-components",
        "codex-hepta-app-bridge",
        "codex-hepta-app-host",
    }
    if agentd != required:
        raise SystemExit(
            "Agentd direct Hepta dependency boundary changed: "
            + ", ".join(sorted(agentd))
        )
    allowed_imports = {
        "codex_hepta_agent_components",
        "codex_hepta_agent_protocol",
        "codex_hepta_agentd",
        "codex_hepta_agentd_core",
        "codex_hepta_app_bridge",
        "codex_hepta_app_host",
    }
    direct: list[str] = []
    root = ROOT / "codex-rs/hepta-agentd/src"
    for path in root.rglob("*.rs"):
        # Qualification fixtures may use dev-dependencies to exercise real
        # product owners.  The production source graph must cross only the
        # stable composition boundaries.
        if path.name.endswith("_tests.rs") or path.name == "test_support.rs":
            continue
        text = path.read_text(encoding="utf-8")
        for crate in re.findall(r"\b(codex_hepta_[a-z0-9_]+)::", text):
            if crate not in allowed_imports:
                direct.append(f"{path.relative_to(ROOT)}:{crate}")
    if direct:
        raise SystemExit("Agentd direct product imports: " + ", ".join(direct[:20]))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_COMPOSITION_BOUNDARY",
                "coreDependencies": sorted(core),
                "agentdDependencies": sorted(agentd),
                "directProductImports": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
