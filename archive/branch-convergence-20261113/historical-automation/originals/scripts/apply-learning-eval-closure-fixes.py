#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str, *, required: bool = True) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old in text:
        target.write_text(text.replace(old, new), encoding="utf-8")
        return
    if new in text:
        return
    if required:
        raise RuntimeError(f"missing patch marker in {path}: {old[:100]!r}")


def patch_evidence() -> None:
    path = "scripts/hepta-learning-eval-evidence.py"
    patch(
        path,
        '    emitter.add_argument("--runtime-log")\n',
        '    emitter.add_argument("--runtime-log")\n    emitter.add_argument("--capacity")\n',
    )
    patch(
        path,
        '            "runtime",\n        }:\n',
        '            "runtime",\n            "capacity",\n        }:\n',
    )
    patch(
        path,
        '                "fenced_holdout_stale_replica_stress",\n',
        '                "fenced_holdout_stale_replica_stress",\n                "fault_injected_durability_and_checkpoint_capacity",\n',
    )
    patch(
        path,
        '            "fenced_holdout_stale_replica_stress",\n',
        '            "fenced_holdout_stale_replica_stress",\n            "fault_injected_durability_and_checkpoint_capacity",\n',
    )
    patch(
        path,
        '    "docs/modules/learning.eval/TECHNICAL.md",\n',
        '    "docs/modules/learning.eval/TECHNICAL.md",\n    "docs/modules/learning.eval/IMPLEMENTATION_MAP.json",\n    "docs/modules/learning.eval/CURRENT_STATUS.json",\n    "docs/modules/learning.eval/CURRENT_STATUS.md",\n    "docs/modules/learning.eval/TARGET_HOST_EVIDENCE_SCHEMA.json",\n    "docs/modules/learning.eval/TARGET_HOST_QUALIFICATION.md",\n',
    )
    patch(
        path,
        '    "scripts/hepta-learning-eval-evidence.py",\n',
        '    "scripts/hepta-learning-eval-evidence.py",\n    "scripts/hepta-learning-eval-private-api.sh",\n    "scripts/hepta-learning-eval-status.py",\n',
    )
    patch(
        path,
        '    "cargoLockDigest": "codex-rs/Cargo.lock",\n',
        '    "cargoLockDigest": "codex-rs/Cargo.lock",\n    "currentStatusDigest": "docs/modules/learning.eval/CURRENT_STATUS.json",\n    "targetHostSchemaDigest": "docs/modules/learning.eval/TARGET_HOST_EVIDENCE_SCHEMA.json",\n',
    )


def patch_workflow() -> None:
    path = ".github/workflows/hepta-lane-e-gap-closure.yml"
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    runtime = "            --runtime-log .hepta-evidence/learning-eval/runtime-e2e.log \\\n"
    capacity = "            --capacity .hepta-evidence/learning-eval/capacity.json \\\n"
    if capacity not in text:
        if runtime not in text:
            raise RuntimeError("missing learning.eval runtime evidence argument")
        text = text.replace(runtime, runtime + capacity)
    target.write_text(text, encoding="utf-8")


def patch_closed_world() -> None:
    path = "scripts/hepta-lane-e-closure.py"
    patch(
        path,
        '            "cargo-llvm-cov@0.9.1",\n',
        '            "cargo-llvm-cov@0.9.0",\n',
    )
    patch(
        path,
        '            "actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373",\n',
        '            "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",\n',
    )
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    anchor = '        "--runtime-log .hepta-evidence/learning-eval/runtime-e2e.log",\n'
    capacity = '        "--capacity .hepta-evidence/learning-eval/capacity.json",\n'
    if capacity not in text:
        if anchor not in text:
            raise RuntimeError("missing runtime-log closure token")
        text = text.replace(anchor, anchor + capacity, 1)
    target.write_text(text, encoding="utf-8")


def main() -> None:
    patch_evidence()
    patch_workflow()
    patch_closed_world()


if __name__ == "__main__":
    main()
