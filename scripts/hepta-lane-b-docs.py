#!/usr/bin/env python3
"""Closed-world validator for Lane B implementation documentation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRUTH = "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
INDEX = "qualification/lane-b/README.md"
NATIVE = "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md"
COMPOSITION = "docs/readiness/LANE_B_RUNTIME_COMPOSITION.md"
MODULES = [
    "runtime.supervisor",
    "runtime.fleet",
    "runtime.agentd",
    "runtime.codex",
    "inference.control",
    "inference.worker",
    "automation.taskflow",
    "channel.matrix",
    "browser.servo",
    "ui.control",
    "ui.native",
]
COMPOSITION_SECTIONS = [
    "## 1. Purpose and truth boundary",
    "## 2. Canonical module set",
    "## 3. Runtime and process topology",
    "## 4. Identity tuple",
    "## 5. Startup order",
    "## 6. Normal request path",
    "## 7. Automation path",
    "## 8. Matrix path",
    "## 9. Browser path",
    "## 10. UI path",
    "## 11. Cancellation and deadline semantics",
    "## 12. Backpressure and resource exhaustion",
    "## 13. Fault-state matrix",
    "## 14. Shutdown and rollback order",
    "## 15. Module maturity at the baseline",
    "## 16. Evidence package required for activation",
    "## 17. Acceptance rule",
]
NATIVE_SECTIONS = ["## 1. Review method"] + [
    f"## {index}. `{module}`" for index, module in enumerate(MODULES, start=2)
] + ["## 13. Cross-module closure conditions"]
FORBIDDEN = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)


class Invalid(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in items:
        if key in output:
            raise Invalid(f"duplicate key {key}")
        output[key] = value
    return output


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def load_json(path: str) -> dict[str, Any]:
    try:
        return json.loads(
            (ROOT / path).read_text(encoding="utf-8"), object_pairs_hook=pairs
        )
    except Exception as exc:
        raise Invalid(f"{path}: {exc}") from exc


def load_text(path: str) -> str:
    file = ROOT / path
    need(file.is_file(), f"missing {path}")
    return file.read_text(encoding="utf-8")


def verify_document(
    path: str,
    text: str,
    title: str,
    sections: list[str],
    minimum_bytes: int,
    minimum_words: int,
) -> None:
    need(text.startswith(title + "\n"), f"{path} title")
    need(len(text.encode("utf-8")) >= minimum_bytes, f"{path} too small")
    need(len(re.findall(r"\b[\w.-]+\b", text)) >= minimum_words, f"{path} too short")
    need(not FORBIDDEN.search(text), f"{path} unresolved marker")
    positions = []
    for section in sections:
        position = text.find(section)
        need(position >= 0, f"{path} missing {section}")
        positions.append(position)
    need(positions == sorted(positions), f"{path} section order")
    for module in MODULES:
        need(module in text, f"{path} missing module {module}")
    for phrase in [
        "production",
        "terminal observer",
        "rollback",
        "independent",
        "exact",
    ]:
        need(phrase.lower() in text.lower(), f"{path} missing concept {phrase}")


def verify() -> int:
    truth = load_json(TRUTH)
    index = load_text(INDEX)
    native = load_text(NATIVE)
    composition = load_text(COMPOSITION)

    need(truth.get("moduleOrder") == MODULES, "truth module order")
    rows = truth.get("modules")
    need(isinstance(rows, list), "truth module rows")
    need([row.get("module") for row in rows] == MODULES, "truth module closed set")
    need(
        truth.get("claimBoundary", {}).get("repositoryTruthModelClosed") is True,
        "truth closure",
    )
    for unsupported in [
        "targetDesignImplementationClosed",
        "productionConsumerCallsitesProved",
        "productExecutionProved",
        "deploymentProved",
        "independentAcceptanceProved",
    ]:
        need(
            truth.get("claimBoundary", {}).get(unsupported) is False,
            f"unsupported positive claim {unsupported}",
        )

    for path in [TRUTH, NATIVE, COMPOSITION]:
        need(path in index, f"index missing {path}")
    need("hepta-lane-b-truth.py verify" in index, "index truth command")
    need("hepta-lane-b-docs.py verify" in index, "index docs command")
    need(not FORBIDDEN.search(index), "index unresolved marker")

    verify_document(
        NATIVE,
        native,
        "# Lane B native implementation closure status",
        NATIVE_SECTIONS,
        12_000,
        1_500,
    )
    verify_document(
        COMPOSITION,
        composition,
        "# Lane B runtime composition and failure semantics",
        COMPOSITION_SECTIONS,
        10_000,
        1_300,
    )

    for row in rows:
        module = row["module"]
        need(f"`{module}`" in native, f"native detail heading {module}")
        gaps = row.get("residualGaps")
        need(isinstance(gaps, list) and gaps, f"{module} residual gaps")
        for operation in row.get("operations", []):
            need(
                operation["designOperation"] in native,
                f"native detail missing {module}/{operation['designOperation']}",
            )

    need(
        "target implementation closure remains false" in native,
        "native document closure boundary",
    )
    need(
        "Target implementation closure additionally requires" in composition,
        "composition acceptance boundary",
    )

    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_IMPLEMENTATION_DOCUMENTS",
                "modules": len(MODULES),
                "documents": 3,
                "targetDesignImplementationClosed": False,
                "productionConsumerCallsitesProved": False,
                "productExecutionProved": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(verify())
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_IMPLEMENTATION_DOCUMENTS: {exc}") from exc
