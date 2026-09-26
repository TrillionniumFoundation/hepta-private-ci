#!/usr/bin/env python3
"""Fail closed when automation schema, migrations, maps or docs drift."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DOCS = (
    "docs/modules/automation.taskflow/TECHNICAL.md",
    "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
    "qualification/module-execution-dossiers/detail/automation.taskflow.md",
    "docs/readiness/LANE_B_NATIVE_HOST.md",
)


class SchemaDrift(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaDrift(message)


def verify(root: Path = ROOT) -> dict[str, object]:
    lib = (root / "codex-rs/hepta-automation/src/lib.rs").read_text(encoding="utf-8")
    match = re.search(r"AUTOMATION_SCHEMA_VERSION:\s*u32\s*=\s*(\d+)\s*;", lib)
    require(match is not None, "AUTOMATION_SCHEMA_VERSION is missing")
    code_version = int(match.group(1))

    migrations = sorted((root / "codex-rs/hepta-automation/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    require(bool(migrations), "automation migrations are missing")
    migration_versions = [int(path.name.split("_", 1)[0]) for path in migrations]
    require(len(migration_versions) == len(set(migration_versions)), "duplicate migration version")
    migration_version = max(migration_versions)

    implementation = json.loads(
        (root / "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json").read_text(encoding="utf-8")
    )
    map_version = implementation.get("storeSchemaVersion")
    require(isinstance(map_version, int), "implementation map storeSchemaVersion is missing")
    require(
        implementation.get("migrationHead") == "0019_converged_owner_schema.sql",
        "implementation map migrationHead drift",
    )

    doc_versions: dict[str, int] = {}
    for relative in TARGET_DOCS:
        text = (root / relative).read_text(encoding="utf-8")
        marker = re.search(r"Automation store schema:\s*v(\d+)", text)
        require(marker is not None, f"{relative}: schema marker is missing")
        require("schema v16" not in text and "schema-v16" not in text, f"{relative}: stale v16 statement")
        doc_versions[relative] = int(marker.group(1))

    versions = {code_version, migration_version, map_version, *doc_versions.values()}
    require(len(versions) == 1, f"automation schema drift: {sorted(versions)}")
    require(code_version == 19, f"expected schema v19, observed v{code_version}")

    runbook = (root / TARGET_DOCS[1]).read_text(encoding="utf-8")
    for required in (
        "destination_operation_dedupe",
        "automation_timer_lifecycle",
        "0019_converged_owner_schema.sql",
        "Older binaries **MUST NOT**",
        "Cross-host boundary",
    ):
        require(required in runbook, f"migration runbook lacks {required!r}")

    callers = tomllib.loads((root / "CALLERS.toml").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in callers["boundary"]}
    effect_host = "codex-rs/hepta-agentd/src/automation_effect_host.rs"
    require(
        effect_host in rows["automation_taskflow_provider_effect_bridge"]["product_callers"],
        "ProviderEffectTaskFlowDriver has no product caller",
    )
    require(
        effect_host in rows["http_provider_effect_adapter"]["product_callers"],
        "HTTP provider-effect adapter has no product caller",
    )
    require(
        implementation["claimBoundary"]["externalEffectProductCompositionComplete"] is True,
        "implementation map does not record repository effect composition closure",
    )
    require(
        implementation["claimBoundary"]["release"] is False,
        "source drift check must not grant release",
    )

    return {
        "schema": "hepta.automation-taskflow.schema-drift-receipt.v1",
        "status": "PASS_AUTOMATION_TASKFLOW_SCHEMA_V19",
        "version": code_version,
        "migrationHead": migrations[-1].name,
        "documents": sorted(doc_versions),
        "productEffectCaller": effect_host,
        "release": False,
    }


def main() -> int:
    try:
        receipt = verify()
    except (OSError, ValueError, KeyError, SchemaDrift) as exc:
        print(f"FAIL_AUTOMATION_TASKFLOW_SCHEMA: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
