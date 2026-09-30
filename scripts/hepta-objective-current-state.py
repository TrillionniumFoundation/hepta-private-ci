#!/usr/bin/env python3
"""Synchronize objective.compiler static source facts across map and narrative docs.

Dynamic source-head, synthetic-merge and target-host outcomes are deliberately
excluded from the checked-in manifest. They are projected only from observed
artifacts by scripts/hepta-objective-evidence-project.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/modules/objective.compiler/CURRENT_STATE.json"
MAP = ROOT / "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json"
NORMATIVE = "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md"
DOCS = (
    ROOT / "docs/modules/objective.compiler/TECHNICAL.md",
    ROOT / "qualification/module-execution-dossiers/detail/objective.compiler.md",
)
BEGIN = "<!-- BEGIN GENERATED OBJECTIVE.COMPILER STATUS -->"
END = "<!-- END GENERATED OBJECTIVE.COMPILER STATUS -->"
SCHEMA = "hepta.objective-compiler-current-state.v2"
PROJECTION_SCHEMA = "hepta.objective-evidence-projection.v2"
STATIC_STATE_KEYS = {
    "core",
    "productComposition",
    "semanticHardening",
    "qualificationEvidence",
    "independentAcceptance",
    "canaryPromotionRollback",
}
FORBIDDEN_DYNAMIC_KEYS = {
    "currentHeadQualification",
    "syntheticMergeQualification",
    "targetHostQualification",
    "checksPassed",
    "measurementObserved",
}


def load(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def digest(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def string_list(manifest: dict[str, Any], key: str) -> list[str]:
    values = manifest.get(key)
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise ValueError(f"{key} must be a non-empty string list")
    return values


def validate(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("schemaVersion") != 2
        or manifest.get("module") != "objective.compiler"
    ):
        raise ValueError("invalid objective current-state identity")
    state = manifest.get("implementationState")
    if (
        not isinstance(state, dict)
        or set(state) != STATIC_STATE_KEYS
        or any(not isinstance(state[key], str) or not state[key] for key in STATIC_STATE_KEYS)
    ):
        raise ValueError("implementationState must contain only static source facts")
    if FORBIDDEN_DYNAMIC_KEYS.intersection(state):
        raise ValueError("dynamic qualification fields are forbidden in source state")

    truth = manifest.get("truth")
    truth_keys = {"productionImplementation", "accepted", "activated", "released"}
    if (
        not isinstance(truth, dict)
        or set(truth) != truth_keys
        or any(type(truth[key]) is not bool for key in truth_keys)
    ):
        raise ValueError("truth must contain four booleans")
    if any(truth.values()):
        raise ValueError(
            "source generation cannot assert production, acceptance, activation or release"
        )

    projection = manifest.get("evidenceProjection")
    if (
        not isinstance(projection, dict)
        or projection.get("schema") != PROJECTION_SCHEMA
        or projection.get("producer") != "scripts/hepta-objective-evidence-project.py"
        or projection.get("manualPassFieldsForbidden") is not True
        or set(projection.get("dynamicClaims", []))
        != {
            "sourceHeadQualification",
            "syntheticMergeQualification",
            "targetHostMeasurement",
        }
    ):
        raise ValueError("invalid dynamic evidence-projection contract")
    string_list(manifest, "requiredChecks")
    string_list(manifest, "externalGates")


def block(manifest: dict[str, Any]) -> str:
    state = manifest["implementationState"]
    truth = manifest["truth"]
    projection = manifest["evidenceProjection"]
    lines = [
        BEGIN,
        "## Generated source-state status",
        "",
        "This block is generated from `docs/modules/objective.compiler/CURRENT_STATE.json`. "
        "The manifest contains static source and policy facts only. Exact source-head, "
        "synthetic-merge and target-host observations are never hand-maintained here; "
        "they are emitted by the receipt-bound evidence projection named below.",
        "",
        f"- Normative execution contract: `{NORMATIVE}`",
        f"- Manifest SHA-256: `{digest(manifest)}`",
        f"- Core: `{state['core']}`",
        f"- Product composition: `{state['productComposition']}`",
        f"- Semantic hardening: `{state['semanticHardening']}`",
        f"- Qualification evidence policy: `{state['qualificationEvidence']}`",
        f"- Independent acceptance: `{state['independentAcceptance']}`",
        f"- Canary/promotion/rollback: `{state['canaryPromotionRollback']}`",
        f"- Dynamic projection schema: `{projection['schema']}`",
        f"- Dynamic projection producer: `{projection['producer']}`",
        "- Manual dynamic pass fields: `forbidden`",
        "",
        "| Source claim | Value |",
        "| --- | --- |",
        f"| `productionImplementation` | `{str(truth['productionImplementation']).lower()}` |",
        f"| `accepted` | `{str(truth['accepted']).lower()}` |",
        f"| `activated` | `{str(truth['activated']).lower()}` |",
        f"| `released` | `{str(truth['released']).lower()}` |",
        "",
        "### Dynamic claims projected only from artifacts",
        "",
        *[f"- `{value}`" for value in projection["dynamicClaims"]],
        "",
        "### Required repository checks",
        "",
        *[f"- `{value}`" for value in manifest["requiredChecks"]],
        "",
        "### External evidence gates",
        "",
        *[f"- {value}" for value in manifest["externalGates"]],
        "",
        END,
    ]
    return "\n".join(lines)


def project(original: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(original)
    state = manifest["implementationState"]
    truth = manifest["truth"]
    result["productionImplementation"] = truth["productionImplementation"]
    result["productCallerState"] = state["productComposition"]
    result["status"] = {
        "implemented": state["core"] == "source_complete",
        "composed": state["productComposition"] != "not_composed",
        "qualified": False,
    }
    boundary = result.get("claimBoundary")
    if not isinstance(boundary, dict):
        boundary = {}
    boundary.update(
        productionImplementation=truth["productionImplementation"],
        productExecutionProved=False,
        independentAcceptance=truth["accepted"],
        activation=truth["activated"],
        release=truth["released"],
    )
    result["claimBoundary"] = boundary
    result["generatedCurrentState"] = {
        "schema": manifest["schema"],
        "schemaVersion": manifest["schemaVersion"],
        "manifestPath": str(MANIFEST.relative_to(ROOT)),
        "normativeExecutionContract": NORMATIVE,
        "manifestSha256": digest(manifest),
        "implementationState": state,
        "truth": truth,
        "evidenceProjection": manifest["evidenceProjection"],
        "requiredChecks": manifest["requiredChecks"],
        "externalGates": manifest["externalGates"],
    }
    return result


def render(text: str, generated: str) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if pattern.search(text):
        return pattern.sub(generated, text, count=1)
    heading = re.search(r"^# .+$", text, re.M)
    if heading is None:
        raise ValueError("document lacks a top-level heading")
    return text[: heading.end()] + "\n\n" + generated + text[heading.end() :]


def sync() -> None:
    manifest = load(MANIFEST)
    validate(manifest)
    MAP.write_text(
        json.dumps(project(load(MAP), manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    generated = block(manifest)
    for path in DOCS:
        path.write_text(render(path.read_text(encoding="utf-8"), generated), encoding="utf-8")


def verify() -> None:
    manifest = load(MANIFEST)
    validate(manifest)
    current = load(MAP)
    if current != project(current, manifest):
        raise SystemExit("FAIL_OBJECTIVE_CURRENT_STATE: implementation map projection drift")
    expected = block(manifest)
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    for path in DOCS:
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match is None or match.group(0) != expected:
            raise SystemExit(
                f"FAIL_OBJECTIVE_CURRENT_STATE: generated block drift in {path.relative_to(ROOT)}"
            )
    print(
        json.dumps(
            {
                "status": "PASS_OBJECTIVE_CURRENT_STATE",
                "module": manifest["module"],
                "manifestSha256": digest(manifest),
                "normativeExecutionContract": NORMATIVE,
                "truth": manifest["truth"],
                "dynamicQualificationSource": "receipt_projection_only",
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "verify"))
    args = parser.parse_args()
    {"sync": sync, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
