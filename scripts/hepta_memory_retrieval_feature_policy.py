#!/usr/bin/env python3
"""Enforce the default-controlled memory.retrieval Cargo and product contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib

LEGACY_FEATURE = "legacy-uncontrolled-retrieval"
CRATE_MANIFEST = Path("codex-rs/hepta-memory-retrieval/Cargo.toml")
COMPOSITION = Path("qualification/memory-retrieval/product-composition.json")
CONTROLLED_API_GUIDE = Path("docs/modules/memory.retrieval/CONTROLLED_API.md")


class FeaturePolicyError(ValueError):
    pass


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise FeaturePolicyError(f"cannot read {path}: {error}") from error


def audit(root: Path) -> list[str]:
    violations: list[str] = []
    crate_manifest = root / CRATE_MANIFEST
    if not crate_manifest.is_file():
        raise FeaturePolicyError(f"missing {CRATE_MANIFEST.as_posix()}")
    crate = _load_toml(crate_manifest)
    features = crate.get("features")
    if not isinstance(features, dict):
        violations.append("retrieval crate has no [features] table")
    else:
        if features.get("default") != []:
            violations.append("retrieval crate default features must be empty")
        if features.get(LEGACY_FEATURE) != []:
            violations.append(f"{LEGACY_FEATURE} must be an empty opt-in marker")

    codex_root = root / "codex-rs"
    if not codex_root.is_dir():
        raise FeaturePolicyError("missing codex-rs workspace")
    for manifest in sorted(codex_root.rglob("Cargo.toml")):
        if manifest == crate_manifest:
            continue
        try:
            text = manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise FeaturePolicyError(f"cannot read {manifest}: {error}") from error
        if LEGACY_FEATURE in text:
            violations.append(
                f"{manifest.relative_to(root).as_posix()} enables or mentions {LEGACY_FEATURE}"
            )

    composition_path = root / COMPOSITION
    if not composition_path.is_file():
        violations.append(f"missing {COMPOSITION.as_posix()}")
    else:
        try:
            composition = json.loads(composition_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise FeaturePolicyError(f"cannot read {COMPOSITION}: {error}") from error
        policy = composition.get("controlledApi")
        expected = {
            "defaultFeatures": [],
            "legacyFeature": LEGACY_FEATURE,
            "legacyFeatureProductionAllowed": False,
            "workControlRequired": True,
            "absoluteDeadlineForwardingRequired": True,
        }
        if not isinstance(policy, dict):
            violations.append("product composition has no controlledApi policy")
        else:
            for field, value in expected.items():
                if policy.get(field) != value:
                    violations.append(
                        f"product composition controlledApi.{field} must equal {value!r}"
                    )

    if not (root / CONTROLLED_API_GUIDE).is_file():
        violations.append(f"missing {CONTROLLED_API_GUIDE.as_posix()}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        violations = audit(args.root.resolve())
        if violations:
            raise FeaturePolicyError("\n".join(violations))
        print("memory.retrieval default-controlled feature policy is valid")
    except FeaturePolicyError as error:
        print(f"memory.retrieval feature policy refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
