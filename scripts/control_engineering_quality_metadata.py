#!/usr/bin/env python3
"""Register control.engineering quality-gate source in canonical metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
COMPONENTS = ROOT / "docs/modules/control.engineering/COMPONENTS.json"
TRACEABILITY = ROOT / "docs/modules/control.engineering/TRACEABILITY.json"

OPERATIONS = (
    {
        "operation": "verify_public_api",
        "designOperation": "additive_public_api_compatibility",
        "nativeSymbol": "verify_public_api",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/api_compat.py",
        "state": "source_implemented_blocking_ci",
        "authority": "none",
        "tests": [{"path": "docs/modules/control.engineering/PUBLIC_API.json"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/__init__.py", "symbol": "__all__", "role": "public_export_owner"}],
    },
    {
        "operation": "run_real_mutation_campaign",
        "designOperation": "real_source_mutation_score",
        "nativeSymbol": "run_campaign",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/mutation_campaign.py",
        "state": "source_implemented_blocking_ci",
        "authority": "none",
        "tests": [
            {"path": "tools/hepta-engineering-control/test_clock_policy.py"},
            {"path": "tools/hepta-engineering-control/test_capacity_policy.py"},
            {"path": "tools/hepta-engineering-control/test_production_providers.py"},
            {"path": "tools/hepta-engineering-control/test_worker_registration_renewal.py"},
            {"path": "tools/hepta-engineering-control/test_recovery_rehearsal.py"},
            {"path": "tools/hepta-engineering-control/test_product_runtime.py"},
            {"path": "tools/hepta-engineering-control/test_audit_checkpoint.py"}
        ],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
)

COMPONENT_ROWS = (
    {
        "id": "public-api-compatibility-gate",
        "source": "tools/hepta-engineering-control/control_engineering_v2/api_compat.py",
        "symbols": ["verify_public_api"],
        "state": "source_implemented_blocking_ci",
        "physicalState": "committed PUBLIC_API.json additive export contract",
        "failureModel": ["public_api_missing", "public_api_forbidden", "public_api_unresolved"],
        "resourceBounds": {"contractSchema": "hepta.control-engineering-public-api.v1"},
        "rollback": "restore the compatible export surface or explicitly version the contract"
    },
    {
        "id": "real-source-mutation-campaign",
        "source": "tools/hepta-engineering-control/control_engineering_v2/mutation_campaign.py",
        "symbols": ["SourceMutant", "run_campaign"],
        "state": "source_implemented_blocking_ci",
        "physicalState": "exact git archive without metadata; one real source edit per isolated temporary tree",
        "failureModel": ["mutation_baseline_failed", "mutation_source_drift", "mutation_score_failed"],
        "resourceBounds": {"mutants": 8, "minimumScorePercent": 100, "maximumOutputBytes": 1048576},
        "rollback": "qualification evidence only; never weaken the score or mutate evaluator tests"
    },
)

TRACE_ROWS = (
    {
        "designOperation": "additive_public_api_compatibility",
        "nativeModule": "control_engineering_v2.api_compat",
        "nativeSymbol": "verify_public_api",
        "ownerSymbol": "control_engineering_v2.__all__",
        "tests": ["blocking CI public API check"],
        "state": "source_implemented_blocking_ci",
        "capabilityCeiling": "additive export compatibility and attribute resolution only"
    },
    {
        "designOperation": "real_source_mutation_score",
        "nativeModule": "control_engineering_v2.mutation_campaign",
        "nativeSymbol": "run_campaign",
        "ownerSymbol": "run_campaign",
        "tests": ["eight actual security-boundary source mutants must all be killed by unchanged tests"],
        "state": "source_implemented_blocking_ci",
        "capabilityCeiling": "qualification score only; no merge, production or release authority"
    },
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def upsert(rows: list[dict[str, Any]], additions: tuple[dict[str, Any], ...], key: str) -> None:
    positions = {row.get(key): index for index, row in enumerate(rows) if isinstance(row, dict)}
    for addition in additions:
        value = json.loads(json.dumps(addition))
        identity = value[key]
        if identity in positions:
            rows[positions[identity]] = value
        else:
            positions[identity] = len(rows)
            rows.append(value)


def expected() -> dict[Path, str]:
    implementation = load(MAP)
    upsert(implementation["operations"], OPERATIONS, "operation")
    components = load(COMPONENTS)
    upsert(components["components"], COMPONENT_ROWS, "id")
    traceability = load(TRACEABILITY)
    upsert(traceability["operations"], TRACE_ROWS, "designOperation")
    return {
        MAP: render(implementation),
        COMPONENTS: render(components),
        TRACEABILITY: render(traceability),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "check"))
    args = parser.parse_args()
    changed = []
    for path, value in expected().items():
        if path.read_text(encoding="utf-8") != value:
            changed.append(str(path.relative_to(ROOT)))
            if args.command == "sync":
                path.write_text(value, encoding="utf-8")
    print(json.dumps({"changed": changed, "checkOnly": args.command == "check", "authorityGranted": False}, sort_keys=True))
    if args.command == "check" and changed:
        raise SystemExit("FAIL_CONTROL_ENGINEERING_QUALITY_METADATA_DRIFT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
