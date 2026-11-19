#!/usr/bin/env python3
"""Audit HIA exclusions and candidate ancestry without writing any Git refs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


HIA_ROOTS = (
    "ca80ff9feef37fc6d03afdc593ddd7da243f4be7",
    "f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb",
    "f02bb9f3344cdff4e361cca4353540ca0193bd21",
)


def exact_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"expected an exact lowercase commit SHA: {value!r}")
    return value


class AncestryIndex:
    """Index immutable commits in parent-before-child order for protected ancestry."""

    def __init__(self, rows: Iterable[str], seeds: Iterable[str]):
        self.seeds = tuple(sorted(set(map(exact_sha, seeds))))
        seed_bits = {sha: 1 << i for i, sha in enumerate(self.seeds)}
        self.masks: dict[str, int] = {}
        self.parents: dict[str, tuple[str, ...]] = {}
        for row in rows:
            parts = row.split()
            if not parts:
                continue
            sha, *parents = map(exact_sha, parts)
            if sha in self.parents:
                raise ValueError(f"duplicate graph row: {sha}")
            mask = seed_bits.get(sha, 0)
            for parent in parents:
                if parent not in self.masks:
                    raise ValueError(f"incomplete or unordered graph: {sha} -> {parent}")
                mask |= self.masks[parent]
            self.masks[sha] = mask
            self.parents[sha] = tuple(parents)
        missing = set(self.seeds) - self.masks.keys()
        if missing:
            raise ValueError(f"protected seeds missing from graph: {sorted(missing)}")

    def protected_ancestors(self, sha: str) -> list[str]:
        mask = self.masks[exact_sha(sha)]
        return [seed for i, seed in enumerate(self.seeds) if mask & (1 << i)]

    def reachable(self, sha: str) -> set[str]:
        exact_sha(sha)
        todo = [sha]
        seen: set[str] = set()
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(self.parents[current])
        return seen


def protection_decision(
    name: str,
    sha: str,
    protected_names: set[str],
    index: AncestryIndex,
) -> dict:
    """Fail closed on missing objects; preserve exact names, HIA names and descendants."""
    ancestors = index.protected_ancestors(sha)
    reasons = []
    if name in protected_names:
        reasons.append("previously_protected_name")
    if "hia" in name.lower():
        reasons.append("hia_branch_name")
    if ancestors:
        reasons.append("protected_pin_or_descendant")
    return {
        "protected": bool(reasons),
        "reasons": reasons,
        "protected_ancestor_pins": ancestors,
    }


def read_json(path: Path):
    return json.loads(path.read_text())


def input_identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        input=stdin,
        text=True,
    )


def run(args) -> dict:
    protected = read_json(args.protected)
    ordinary = read_json(args.ordinary)
    historical_pins = set(map(exact_sha, read_json(args.pins)))
    if not isinstance(protected, dict) or not isinstance(ordinary, dict):
        raise ValueError("protected and ordinary inputs must be name-keyed mappings")
    if set(protected) & set(ordinary):
        raise ValueError("protected and ordinary names overlap")
    if "main" in protected or "main" in ordinary:
        raise ValueError("main must remain outside retirement classifications")
    named_pins: dict[str, list[str]] = {}
    for name, row in protected.items():
        sha = exact_sha(row["sha"])
        named_pins.setdefault(sha, []).append(name)
    for sha in ordinary.values():
        exact_sha(sha)
    if git(args.repo, "rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError("ancestry requires a non-shallow object graph")
    common = Path(git(args.repo, "rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = args.repo / common
    grafts = common / "info/grafts"
    if grafts.exists() and grafts.read_text().strip():
        raise ValueError("ancestry audit refuses a grafted graph")
    candidate = exact_sha(args.candidate)
    seeds = historical_pins | set(named_pins) | set(HIA_ROOTS)
    revisions = seeds | set(ordinary.values()) | {candidate}
    raw_graph = git(
        args.repo,
        "rev-list",
        "--parents",
        "--topo-order",
        "--reverse",
        "--stdin",
        stdin="\n".join(sorted(revisions)) + "\n",
    )
    index = AncestryIndex(raw_graph.splitlines(), seeds)
    candidate_reachable = index.reachable(candidate)
    added = []
    revised_protected = dict(protected)
    revised_ordinary = {}
    for name, sha in sorted(ordinary.items()):
        decision = protection_decision(name, sha, set(protected), index)
        if decision["protected"]:
            row = {
                "name": name,
                "sha": sha,
                "reasons": decision["reasons"],
                "candidate_contains_tip": sha in candidate_reachable,
                "protected_ancestors": [
                    {
                        "sha": seed,
                        "names": sorted(named_pins.get(seed, [])),
                        "historical_pin": seed in historical_pins,
                        "reviewed_hia_root": seed in HIA_ROOTS,
                    }
                    for seed in decision["protected_ancestor_pins"]
                ],
            }
            added.append(row)
            revised_protected[name] = {
                "sha": sha,
                "reasons": decision["reasons"],
                "historical_protection_review": "preserve_until_explicit_scope_review",
                "protected_ancestor_pins": decision["protected_ancestor_pins"],
            }
        else:
            revised_ordinary[name] = sha
    candidate_pins = index.protected_ancestors(candidate)
    protected_reachable = [
        {"name": name, "sha": row["sha"]}
        for name, row in sorted(revised_protected.items())
        if row["sha"] in candidate_reachable
    ]
    report = {
        "schema": "hepta.hia-scope-independent-audit.v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "repo_path": str(args.repo.resolve()),
        "inputs": {
            "ordinary": input_identity(args.ordinary),
            "protected": input_identity(args.protected),
            "historical_pins": input_identity(args.pins),
        },
        "scope": "Reclassification of the supplied frozen inventory; not a fresh remote census.",
        "graph": {
            "commits": len(index.parents),
            "sha256": hashlib.sha256(raw_graph.encode()).hexdigest(),
            "historical_pin_count": len(historical_pins),
            "effective_seed_count": len(seeds),
            "root_shas": list(HIA_ROOTS),
            "replace_objects_disabled": True,
            "shallow_and_grafted_graphs_rejected": True,
            "all_revisions_exact_sha": True,
        },
        "counts": {
            "original_protected": len(protected),
            "original_ordinary": len(ordinary),
            "newly_preserved_names": len(added),
            "revised_protected": len(revised_protected),
            "revised_ordinary": len(revised_ordinary),
            "main": 1,
            "total": len(protected) + len(ordinary) + 1,
            "original_protected_names_without_hia": sum("hia" not in n.lower() for n in protected),
        },
        "candidate": {
            "sha": candidate,
            "reachable_commits": len(candidate_reachable),
            "protected_ancestor_pins": candidate_pins,
            "protected_names_reachable": protected_reachable,
            "newly_preserved_tips_reachable": [r["name"] for r in added if r["candidate_contains_tip"]],
            "no_protected_ancestry": not candidate_pins and not protected_reachable,
            "ordinary_tips_reachable": sum(s in candidate_reachable for s in revised_ordinary.values()),
            "ordinary_tips_pending": sum(s not in candidate_reachable for s in revised_ordinary.values()),
        },
        "newly_preserved": added,
        "retirement_requirements": [
            "Refresh complete live refs and reclassify every new or changed tip, retaining previous protected names.",
            "Exclude HIA names, protected names and every descendant of protected historical pins.",
            "Require the exact retirement tip reachable from accepted main; candidate coverage alone is insufficient.",
            "Verify required CI on accepted main/candidate and retain semantic conflict-resolution evidence.",
            "Use exact SHA leases on ordinary deletions and re-read protected name/SHA pairs after each batch.",
            "Keep new branches that appeared after the frozen inventory until reviewed; never infer deletion authority from their absence in it.",
        ],
        "mutations": {"git_refs": 0, "existing_input_files": 0},
    }
    args.output.mkdir(parents=True, exist_ok=False)
    snapshots = args.output / "inputs"
    snapshots.mkdir()
    for name, source in [
        ("ordinary.json", args.ordinary),
        ("protected.json", args.protected),
        ("historical-pins.json", args.pins),
    ]:
        (snapshots / name).write_bytes(source.read_bytes())
    for name, value in [
        ("audit.json", report),
        ("protected-reclassified.json", dict(sorted(revised_protected.items()))),
        ("ordinary-reclassified.json", dict(sorted(revised_ordinary.items()))),
    ]:
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ordinary", type=Path, required=True)
    parser.add_argument("--protected", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({"counts": report["counts"], "candidate": report["candidate"]}, indent=2))


if __name__ == "__main__":
    main()
