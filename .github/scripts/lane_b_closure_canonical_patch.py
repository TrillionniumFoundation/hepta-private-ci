#!/usr/bin/env python3
"""Register the Lane B closure in the canonical document system, then self-delete."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PATH = ROOT / "docs/governance/DOCUMENT_SYSTEM.json"
GLOBAL_VERIFIER = ROOT / "scripts/hepta-docs.py"
SELF = Path(__file__).resolve()

LANE_B_REGISTRY = "docs/lane-b/LANE_B_CLOSURE.json"
LANE_B_STATUS = "docs/lane-b/STATUS.md"
LANE_B_README = "docs/lane-b/README.md"
LANE_B_VERIFIER = "scripts/hepta-lane-b-closure.py"
LANE_B_WORKFLOW = ".github/workflows/hepta-lane-b-closure.yml"

FILES = {
    "current": "docs/CURRENT.json",
    "architecture": "docs/architecture/ARCHITECTURE.json",
    "modules": "docs/modules/MODULES.json",
    "contracts": "docs/contracts/CONTRACTS.json",
    "protocols": "docs/contracts/PROTOCOL_SCHEMAS.json",
    "data": "docs/data/DATA_AUTHORITY.json",
    "work": "docs/delivery/WORK_PACKAGES.json",
    "development": "docs/delivery/DEVELOPMENT_DAG.json",
    "activation": "docs/delivery/ACTIVATION_DAG.json",
    "evidence_dag": "docs/delivery/EVIDENCE_DAG.json",
    "paths": "docs/delivery/PATH_OWNERSHIP.json",
    "objectives": "docs/control-plane/OBJECTIVES.json",
    "ndu": "docs/control-plane/NDU.json",
    "optimization": "docs/control-plane/OPTIMIZATION.json",
    "prompt": "docs/intelligence/PROMPT_INTERVENTIONS.json",
    "learning": "docs/learning/LEARNING_SYSTEM.json",
    "experiments": "docs/learning/EXPERIMENTS.json",
    "artifacts": "docs/learning/ARTIFACTS.json",
    "claims": "docs/evidence/CLAIMS.json",
    "qualification": "docs/evidence/QUALIFICATION.json",
    "evidence": "docs/evidence/INDEX.json",
    "threats": "docs/security/THREAT_MODEL.json",
    "module_docs": "docs/modules/MODULE_DOCS.json",
    "source_bindings": "docs/modules/SOURCE_BINDINGS.json",
    "algorithm_specs": "docs/learning/ALGORITHM_SPECS.json",
    "paper_traceability": "docs/learning/PAPER_TRACEABILITY.json",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)


def shape_paths(value: Any, path: str = "$") -> set[str]:
    result = {path}
    if isinstance(value, dict):
        for key, child in value.items():
            result |= shape_paths(child, f"{path}.{key}")
    elif isinstance(value, list):
        result.add(path + "[]")
        for child in value:
            result |= shape_paths(child, path + "[]")
    else:
        result.add(path + ":" + type(value).__name__)
    return result


def shape_sha(value: Any) -> str:
    return hashlib.sha256("\n".join(sorted(shape_paths(value))).encode("utf-8")).hexdigest()


def patch_global_verifier() -> None:
    text = GLOBAL_VERIFIER.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'HNMF_GAPS = "docs/hnmf/GAPS.json"\nAUTHORITY_KEYS = [',
        'HNMF_GAPS = "docs/hnmf/GAPS.json"\n'
        'LANE_B_REGISTRY = "docs/lane-b/LANE_B_CLOSURE.json"\n'
        'LANE_B_STATUS = "docs/lane-b/STATUS.md"\n'
        'LANE_B_VERIFIER = "scripts/hepta-lane-b-closure.py"\n'
        'LANE_B_WORKFLOW = ".github/workflows/hepta-lane-b-closure.yml"\n'
        'AUTHORITY_KEYS = [',
        "Lane B constants",
    )

    text = replace_once(
        text,
        '    hnmf_gaps = load(HNMF_GAPS)\n    return {',
        '    hnmf_gaps = load(HNMF_GAPS)\n    lane_b = load(LANE_B_REGISTRY)\n    return {',
        "subordinate load",
    )
    text = replace_once(
        text,
        '        "hnmf_gaps": hnmf_gaps,\n    }',
        '        "hnmf_gaps": hnmf_gaps,\n        "lane_b": lane_b,\n    }',
        "subordinate return",
    )

    text = replace_once(
        text,
        '        f"- HNMF reference gaps: **{len(sub[\'hnmf_gaps\'][\'gaps\'])}**",\n',
        '        f"- HNMF reference gaps: **{len(sub[\'hnmf_gaps\'][\'gaps\'])}**",\n'
        '        f"- Lane B runtime modules source-mapped: **{len(sub[\'lane_b\'][\'modules\'])}**",\n'
        '        f"- Lane B repository-internal blockers closed: **{sum(row[\'state\'] == \'closed_by_candidate\' for row in sub[\'lane_b\'][\'repositoryBlockers\'])}**",\n',
        "status Lane B projection",
    )

    text = replace_once(
        text,
        '        "docs/readiness/STATUS.md",\n        "docs/cns/README.md",',
        '        "docs/readiness/STATUS.md",\n'
        '        "docs/lane-b/README.md",\n'
        '        LANE_B_REGISTRY,\n'
        '        LANE_B_STATUS,\n'
        '        "docs/cns/README.md",',
        "canonical Lane B docs",
    )
    text = replace_once(
        text,
        '        HNMF_VERIFIER,\n        "scripts/hepta-paper-evidence.py",',
        '        HNMF_VERIFIER,\n        LANE_B_VERIFIER,\n        "scripts/hepta-paper-evidence.py",',
        "canonical Lane B verifier",
    )
    text = replace_once(
        text,
        '        ".github/workflows/hnmf-qualification.yml",\n        *FILES.values(),',
        '        ".github/workflows/hnmf-qualification.yml",\n        LANE_B_WORKFLOW,\n        *FILES.values(),',
        "canonical Lane B workflow",
    )

    readiness_row = '''            {
                "id": "HEPTA-V8-PRECODING-READINESS",
                "registryPath": READINESS_INDEX,
                "statusPath": "docs/readiness/STATUS.md",
                "validator": "python3 scripts/hepta-readiness.py verify",
                "workflow": ".github/workflows/hepta-implementation-readiness.yml",
                "authorityGranted": False,
            },
'''
    lane_b_row = '''            {
                "id": "HEPTA-LANE-B-RUNTIME-CLOSURE",
                "registryPath": LANE_B_REGISTRY,
                "statusPath": LANE_B_STATUS,
                "validator": "python3 scripts/hepta-lane-b-closure.py verify",
                "workflow": LANE_B_WORKFLOW,
                "authorityGranted": False,
            },
'''
    text = replace_once(text, readiness_row, readiness_row + lane_b_row, "subordinate registry")

    text = replace_once(
        text,
        '        "HNMF subordinate closure",\n    )\n    need((ROOT / "docs/STATUS.md").read_text() == status_text(d), "STATUS stale")',
        '        "HNMF subordinate closure",\n'
        '    )\n'
        '    need(\n'
        '        sub["lane_b"].get("laneId") == "LANE-B-RUNTIME"\n'
        '        and sub["lane_b"].get("moduleCount") == 11\n'
        '        and len(sub["lane_b"].get("modules", [])) == 11\n'
        '        and sub["lane_b"].get("claimBoundary", {}).get("repositoryInternalGapsClosed") is True\n'
        '        and sub["lane_b"].get("claimBoundary", {}).get("allGapsClosed") is False,\n'
        '        "Lane B subordinate closure",\n'
        '    )\n'
        '    need((ROOT / "docs/STATUS.md").read_text() == status_text(d), "STATUS stale")',
        "Lane B subordinate assertion",
    )

    text = replace_once(
        text,
        '        ("HNMF", HNMF_VERIFIER),\n    ]:',
        '        ("HNMF", HNMF_VERIFIER),\n        ("Lane B", LANE_B_VERIFIER),\n    ]:',
        "Lane B verifier invocation",
    )

    text = replace_once(
        text,
        '        "python3 scripts/hepta-hnmf.py verify",\n        "python3 scripts/hepta-docs.py inventory-legacy",',
        '        "python3 scripts/hepta-hnmf.py verify",\n'
        '        "python3 scripts/hepta-lane-b-closure.py self-test",\n'
        '        "python3 scripts/hepta-lane-b-closure.py generate-status --check",\n'
        '        "python3 scripts/hepta-lane-b-closure.py verify",\n'
        '        "python3 scripts/hepta-docs.py inventory-legacy",',
        "development workflow Lane B tokens",
    )

    text = replace_once(
        text,
        '                "hnmfReferenceGaps": len(sub["hnmf_gaps"]["gaps"]),\n                "legacyPaths": 0,',
        '                "hnmfReferenceGaps": len(sub["hnmf_gaps"]["gaps"]),\n'
        '                "laneBModules": len(sub["lane_b"]["modules"]),\n'
        '                "laneBRepositoryInternalGapsClosed": True,\n'
        '                "laneBAllGapsClosed": False,\n'
        '                "legacyPaths": 0,',
        "verification report Lane B fields",
    )

    text = replace_once(
        text,
        '        "hnmfRegistrySha256": hashlib.sha256(\n            (ROOT / HNMF_REGISTRY).read_bytes()\n        ).hexdigest(),\n        "verifiedAt": verified_at,',
        '        "hnmfRegistrySha256": hashlib.sha256(\n'
        '            (ROOT / HNMF_REGISTRY).read_bytes()\n'
        '        ).hexdigest(),\n'
        '        "laneBVerifierSha256": hashlib.sha256(\n'
        '            (ROOT / LANE_B_VERIFIER).read_bytes()\n'
        '        ).hexdigest(),\n'
        '        "laneBRegistrySha256": hashlib.sha256(\n'
        '            (ROOT / LANE_B_REGISTRY).read_bytes()\n'
        '        ).hexdigest(),\n'
        '        "verifiedAt": verified_at,',
        "receipt Lane B digests",
    )

    text = replace_once(
        text,
        '        ("hnmfRegistrySha256", HNMF_REGISTRY, "HNMF registry"),\n    ]:',
        '        ("hnmfRegistrySha256", HNMF_REGISTRY, "HNMF registry"),\n'
        '        ("laneBVerifierSha256", LANE_B_VERIFIER, "Lane B verifier"),\n'
        '        ("laneBRegistrySha256", LANE_B_REGISTRY, "Lane B registry"),\n'
        '    ]:',
        "receipt verification Lane B digests",
    )

    GLOBAL_VERIFIER.write_text(text, encoding="utf-8")


def patch_document_system() -> None:
    system = load(SYSTEM_PATH)

    additions = [
        LANE_B_README,
        LANE_B_REGISTRY,
        LANE_B_STATUS,
        LANE_B_VERIFIER,
        LANE_B_WORKFLOW,
    ]
    for path in additions:
        if path not in system["canonicalPaths"]:
            system["canonicalPaths"].append(path)

    lane_b_row = {
        "id": "HEPTA-LANE-B-RUNTIME-CLOSURE",
        "registryPath": LANE_B_REGISTRY,
        "statusPath": LANE_B_STATUS,
        "validator": "python3 scripts/hepta-lane-b-closure.py verify",
        "workflow": LANE_B_WORKFLOW,
        "authorityGranted": False,
    }
    registries = [row for row in system["subordinateRegistries"] if row["id"] != lane_b_row["id"]]
    readiness_index = next(
        index for index, row in enumerate(registries) if row["id"] == "HEPTA-V8-PRECODING-READINESS"
    )
    registries.insert(readiness_index + 1, lane_b_row)
    system["subordinateRegistries"] = registries

    system.setdefault("generatedProjections", {})[LANE_B_STATUS] = {
        "generator": "python3 scripts/hepta-lane-b-closure.py generate-status",
        "handEditingAllowed": False,
    }

    closures = {row["path"]: row for row in system["registryShapeClosures"]}
    for relative in FILES.values():
        value = load(ROOT / relative)
        row = closures[relative]
        row["topLevelKeys"] = list(value)
        row["recursiveShapeSha256"] = shape_sha(value)

    write_json(SYSTEM_PATH, system)


def update_readiness_index() -> None:
    path = ROOT / "docs/readiness/README.md"
    text = path.read_text(encoding="utf-8")
    marker = "24. [`../../qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json`](../../qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json) — sixteen further implementation-design dispositions, their documents and remaining evidence.\n"
    addition = "25. [`../lane-b/LANE_B_CLOSURE.json`](../lane-b/LANE_B_CLOSURE.json) — Lane B current capability, exact source mapping, remaining bridges and repository-internal closure boundary.\n"
    if addition not in text:
        if marker not in text:
            raise RuntimeError("readiness index insertion point missing")
        text = text.replace(marker, marker + addition, 1)
    path.write_text(text, encoding="utf-8")


def regenerate_global_status() -> None:
    subprocess.run(
        [sys.executable, str(GLOBAL_VERIFIER), "generate-status"],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    patch_global_verifier()
    patch_document_system()
    update_readiness_index()
    regenerate_global_status()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
