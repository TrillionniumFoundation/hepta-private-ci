#!/usr/bin/env python3
"""Targeted source mutants in disposable worktrees, never the candidate tree.

A mutant only counts as killed when it compiles and the same real Rust probe
returns an observable wrong semantic result. Compilation errors, crashes and
missing tools are invalid experiments, not kills. No mutant is pushed or
qualified as a release candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import quality_checks as quality
from run_qualification import git, run_check

RECIPES = [
    {"name": "provenance-logical-identity", "file": "codex-rs/hepta-cognitive-types/src/hnmf.rs",
     "old": "if !provenance_identities.insert((&provenance.source_id, provenance.source_revision)) {",
     "new": "if false && !provenance_identities.insert((&provenance.source_id, provenance.source_revision)) {",
     "case": "event:logical-provenance-conflict", "negative": True},
    {"name": "schema-bound-digest-domain", "file": "codex-rs/hepta-cognitive-types/src/wire.rs",
     "old": 'b"hepta.cognitive.contract.bound-digest.v1\\0"',
     "new": 'b"hepta.cognitive.contract.bound-digest.mutant\\0"',
     "case": "ModalitySpanRefV1:golden", "negative": False},
]


def mutate_once(text, recipe):
    if text.count(recipe["old"]) != 1:
        raise ValueError("mutation anchor must occur exactly once: " + recipe["name"])
    return text.replace(recipe["old"], recipe["new"], 1)


def observed_kill(result):
    return (result.get("exit_code") == 0 and result.get("report", {}).get("outcome") == "accepted"
            and result.get("passed") is False and result.get("status") == "failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("mutation evidence must be outside the source tree")
    candidate = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        parser.error("mutation experiment requires a clean immutable candidate")
    positive, negative = quality.cases(quality.load_vectors(root))
    positive, negative = dict(positive), dict(negative)
    results = []
    output.mkdir(parents=True, exist_ok=True)
    for recipe in RECIPES:
        expected = None if recipe["negative"] else quality.digests(positive[recipe["case"]])
        wire = negative[recipe["case"]] if recipe["negative"] else quality.canonical(positive[recipe["case"]])
        baseline = quality.invoke([str(args.probe.resolve())], wire, expected)
        row = {"recipe": recipe, "baseline": baseline, "candidate_commit": candidate,
               "candidate_tree": tree, "wire_sha256": hashlib.sha256(wire).hexdigest(),
               "killed": False, "status": "infrastructure_invalid"}
        if not baseline["passed"]:
            row["error"] = "baseline must pass before mutation sensitivity is measured"
            results.append(row)
            continue
        with tempfile.TemporaryDirectory(prefix="cognitive-mutant-", dir=output.parent) as temp:
            worktree = Path(temp) / "source"
            added = False
            try:
                git(root, "worktree", "add", "--detach", str(worktree), candidate)
                added = True
                path = worktree / recipe["file"]
                original = path.read_bytes()
                modified = mutate_once(original.decode(), recipe).encode()
                path.write_bytes(modified)
                row.update(original_source_sha256=hashlib.sha256(original).hexdigest(),
                           mutant_source_sha256=hashlib.sha256(modified).hexdigest())
                target = output.parent / "cognitive-mutation-target"
                build = run_check(recipe["name"] + "-build", [
                    "cargo", "build", "--locked", "-p", "codex-hepta-cognitive-types",
                    "--example", "canonical_probe", "--target-dir", str(target)],
                    worktree / "codex-rs", output, timeout=1800)
                row["build"] = build
                if build["status"] == "passed":
                    experiment = quality.invoke([str(target / "debug/examples/canonical_probe")], wire, expected)
                    row["experiment"] = experiment
                    row["killed"] = observed_kill(experiment)
                    row["status"] = "killed" if row["killed"] else (
                        "survived" if experiment.get("passed") else "infrastructure_invalid")
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                row["error"] = f"{type(error).__name__}: {error}"
            finally:
                if added:
                    try:
                        git(root, "worktree", "remove", "--force", str(worktree))
                    except subprocess.SubprocessError as error:
                        row["cleanup_error"] = str(error)
                        row["status"] = "infrastructure_invalid"
                        row["killed"] = False
        results.append(row)
    clean = (git(root, "rev-parse", "HEAD") == candidate
             and git(root, "rev-parse", "HEAD^{tree}") == tree
             and not git(root, "status", "--porcelain", "--untracked-files=all"))
    passed = clean and len(results) == len(RECIPES) and all(row["killed"] for row in results)
    receipt = {"schema": "hepta.cognitive-types.targeted-mutation.v1", "candidate_commit": candidate,
               "candidate_tree": tree, "candidate_unchanged": clean, "passed": passed,
               "scope": "two-targeted-source-mutants-not-global-mutation-coverage", "results": results}
    (output / "mutation-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"passed": passed, "candidate_unchanged": clean,
                      "results": [{"name": row["recipe"]["name"], "status": row["status"]} for row in results]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
