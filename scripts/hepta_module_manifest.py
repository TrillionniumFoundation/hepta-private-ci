#!/usr/bin/env python3
"""Render and verify legacy module projections from one manifest per module."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_GLOB = "docs/modules/*/module.json"


class ManifestError(ValueError):
    pass


def load_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ManifestError(f"duplicate key {key} in {path}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def manifests(root: Path = ROOT):
    rows = []
    for path in sorted(root.glob(MANIFEST_GLOB)):
        value = load_json(path)
        if (
            value.get("schema") != "hepta.module-manifest.v1"
            or value.get("schemaVersion") != 1
        ):
            raise ManifestError(f"invalid manifest schema: {path}")
        module = value.get("module")
        if not isinstance(module, dict) or not isinstance(module.get("id"), str):
            raise ManifestError(f"invalid module payload: {path}")
        expected = root / "docs/modules" / module["id"] / "module.json"
        if path != expected:
            raise ManifestError(f"manifest path mismatch: {path}")
        ci = value.get("ci")
        if not isinstance(ci, dict) or ci.get("tier") not in {
            "ordinary",
            "stateful",
            "effect",
            "release",
        }:
            raise ManifestError(f"invalid CI tier: {path}")
        if ci.get("ordinaryFeedbackBudgetMinutes") != 10:
            raise ManifestError(f"ordinary feedback budget drift: {path}")
        composition = value.get("composition")
        if (
            not isinstance(composition, dict)
            or composition.get("agentdCoreDependency") is not False
        ):
            raise ManifestError(f"module widens Agentd core: {path}")
        rows.append((path, value))
    ids = [value["module"]["id"] for _, value in rows]
    if not ids or len(ids) != len(set(ids)):
        raise ManifestError("empty or duplicate module manifest set")
    return rows


def projected_modules(root: Path = ROOT):
    return [value["module"] for _, value in manifests(root)]


def render(root: Path = ROOT, *, check: bool = False):
    registry_path = root / "docs/modules/MODULES.json"
    registry = load_json(registry_path)
    registry["modules"] = projected_modules(root)
    rendered = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
    changed = registry_path.read_text(encoding="utf-8") != rendered
    if changed and check:
        raise ManifestError(
            "MODULES.json is not generated from module manifests"
        )
    if changed:
        registry_path.write_text(rendered, encoding="utf-8")

    matrix = {
        "schema": "hepta.module-ci-matrix.v1",
        "schemaVersion": 1,
        "ordinaryFeedbackBudgetMinutes": 10,
        "modules": [
            {
                "module": value["module"]["id"],
                "tier": value["ci"]["tier"],
                "roots": [
                    item["path"]
                    for item in value["module"].get("rootBindings", [])
                ],
                "exactCandidateRequired": value["ci"][
                    "exactCandidateRequired"
                ],
                "targetHostRequired": value["ci"]["targetHostRequired"],
            }
            for _, value in manifests(root)
        ],
    }
    matrix_path = root / "docs/modules/CI_MATRIX.json"
    matrix_rendered = json.dumps(matrix, indent=2, ensure_ascii=False) + "\n"
    matrix_changed = (
        not matrix_path.exists()
        or matrix_path.read_text(encoding="utf-8") != matrix_rendered
    )
    if matrix_changed and check:
        raise ManifestError(
            "CI_MATRIX.json is not generated from module manifests"
        )
    if matrix_changed:
        matrix_path.write_text(matrix_rendered, encoding="utf-8")
    return changed or matrix_changed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render", "check", "list"))
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "list":
        print(
            "\n".join(
                value["module"]["id"] for _, value in manifests(root)
            )
        )
        return 0
    render(root, check=args.command == "check")
    result = {
        "status": (
            "PASS_HEPTA_MODULE_MANIFEST"
            if args.command == "check"
            else "RENDERED_HEPTA_MODULE_MANIFEST"
        ),
        "modules": len(manifests(root)),
        "canonical": "docs/modules/*/module.json",
        "authorityGranted": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ManifestError, OSError, ValueError, TypeError) as error:
        print(f"FAIL_HEPTA_MODULE_MANIFEST: {error}", file=sys.stderr)
        raise SystemExit(1)
