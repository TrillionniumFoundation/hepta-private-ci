#!/usr/bin/env python3
"""Classify a change into ordinary, stateful, effect, or release CI tiers."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = {"ordinary": 0, "stateful": 1, "effect": 2, "release": 3}


def changed_paths(base, head):
    return subprocess.check_output(
        ["git", "diff", "--name-only", base, head, "--"],
        cwd=ROOT,
        text=True,
    ).splitlines()


def manifests():
    rows = []
    for path in sorted((ROOT / "docs/modules").glob("*/module.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        roots = [
            item["path"].rstrip("/")
            for item in value["module"].get("rootBindings", [])
        ]
        rows.append((value["module"]["id"], value["ci"]["tier"], roots))
    return rows


def max_tier(left, right):
    return left if ORDER[left] >= ORDER[right] else right


def classify(paths):
    tier = "ordinary"
    reasons = []
    rows = manifests()
    release_roots = (
        ".github/workflows/",
        "docs/branch-policy.json",
        "docs/security/",
        "qualification/",
    )
    effect_roots = (
        "codex-rs/hepta-contracts/",
        "codex-rs/hepta-operations/",
        "codex-rs/hepta-authbus/",
        "codex-rs/hepta-bao-adapter/",
        "apps/hepta-browser/",
        "apps/hepta-native/",
    )
    for path in paths:
        path_tier = "ordinary"
        if path == "codex-rs/Cargo.lock" or path.startswith(release_roots):
            path_tier = "release"
        elif path.startswith(effect_roots):
            path_tier = "effect"
        else:
            for module_id, module_tier, roots in rows:
                if any(
                    path == root or path.startswith(root + "/")
                    for root in roots
                ):
                    path_tier = max_tier(path_tier, module_tier)
                    if module_tier != "ordinary":
                        reasons.append(f"{module_id}:{module_tier}")
        tier = max_tier(tier, path_tier)
    lanes = (
        ["source-head"]
        if tier == "ordinary"
        else ["source-head", "base-merge"]
    )
    return tier, lanes, sorted(set(reasons))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()
    paths = changed_paths(args.base, args.head)
    tier, lanes, reasons = classify(paths)
    result = {
        "risk": tier,
        "lanes": lanes,
        "paths": len(paths),
        "reasons": reasons,
    }
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as target:
            target.write(f"risk={tier}\n")
            target.write(
                "lanes=" + json.dumps(lanes, separators=(",", ":")) + "\n"
            )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
