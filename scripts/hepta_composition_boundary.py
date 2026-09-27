#!/usr/bin/env python3
"""Fail if Agentd core regains product dependencies or bypasses packs."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
core = (ROOT / "codex-rs/hepta-agentd-core/Cargo.toml").read_text(
    encoding="utf-8"
)
allowed = {"codex-hepta-types"}
deps = set(
    re.findall(r"^(codex-hepta-[A-Za-z0-9_-]+)\s*=", core, re.M)
)
extra = sorted(deps - allowed)
if extra:
    raise SystemExit(
        "Agentd core depends on product crates: " + ", ".join(extra)
    )

agentd = (ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text(
    encoding="utf-8"
)
required = {"codex-hepta-agentd-core", "codex-hepta-agent-components"}
agentd_deps = set(
    re.findall(r"^(codex-hepta-[A-Za-z0-9_-]+)\s*=", agentd, re.M)
)
if not required.issubset(agentd_deps):
    raise SystemExit("Agentd composition dependencies missing")

product_imports = []
for root in (
    ROOT / "codex-rs/hepta-agentd/src",
    ROOT / "codex-rs/hepta-agentd/tests",
    ROOT / "codex-rs/hepta-agentd/examples",
):
    if not root.exists():
        continue
    for path in root.rglob("*.rs"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"\bcodex_hepta_(?!agent_protocol\b|agent_components\b|"
            r"agentd_core\b|paths\b)[A-Za-z0-9_]+",
            text,
        ):
            product_imports.append(
                f"{path.relative_to(ROOT)}:{match.group(0)}"
            )
if product_imports:
    raise SystemExit(
        "Agentd direct product imports: "
        + ", ".join(product_imports[:20])
    )
print(
    json.dumps(
        {
            "status": "PASS_HEPTA_COMPOSITION_BOUNDARY",
            "coreDependencies": sorted(deps),
            "directProductImports": 0,
        }
    )
)
