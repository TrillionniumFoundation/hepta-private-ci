#!/usr/bin/env python3
"""Reproduce the retained scoped Python checks on either fixed source tree.

This runner was packaged after the retained runs; the raw logs are unchanged.
It does not run Rust, a complete source suite or the full caller proof.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import py_compile
import subprocess
import sys
import tomllib
import unittest


BASE = "514fe5f53cfdc254477667f8862d652ea756c807"
CORRECTED = "4ae6c73ea7731e69c6819c1d188f8ff26ba1fbb7"
BASE_TREE = "490dcafbd5a7f12a8fac19f5fa5b00b5c3ce4879"
CORRECTED_TREE = "f2c7d861717117c9d74591db38bbcf19f06f55fe"
HERE = Path(__file__).resolve().parent


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def owned(path):
    name = Path(path).name
    return (
        name.startswith("cell_q24_training_")
        or name.startswith("cell_q24_candidate_stage_")
        or name in ("cell_q24_candidate_material.rs", "cell_q24_source_bound_stage.rs")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("baseline", "corrected"), required=True)
    args = parser.parse_args()
    root = args.source.resolve()
    output = args.output.resolve()
    if output == root or root in output.parents:
        raise ValueError("qualification output must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    expected_commit = BASE if args.mode == "baseline" else CORRECTED
    expected_tree = BASE_TREE if args.mode == "baseline" else CORRECTED_TREE
    head = git(root, "rev-parse", "HEAD").strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").strip()
    assert head == expected_commit, (head, expected_commit)
    assert tree == expected_tree, (tree, expected_tree)
    assert not git(root, "status", "--porcelain"), "dirty qualification source"
    delta = json.loads((HERE / "complete-row-delta.json").read_text())
    before = tomllib.loads(git(root, "show", BASE + ":CALLERS.toml"))
    after = tomllib.loads((root / "CALLERS.toml").read_text())
    expected = copy.deepcopy(before)
    if args.mode == "corrected":
        for row in delta["rows"]:
            assert expected["protected_file"][row["index"]] == row["before"]
            expected["protected_file"][row["index"]] = row["after"]
    assert expected == after, "unexpected boundary, inventory or protected-row change"
    files = json.loads((HERE / "baseline.json").read_text())["files"]
    suite = unittest.TestSuite()
    for index, name in enumerate(files):
        module = load_module(
            f"owned_reproduction_{index}", root / "qa/b4-no-bypass" / name
        )
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    with (output / "tests.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    raw = (output / "tests.log").read_bytes()
    protected_count = None
    if args.mode == "corrected":
        proof = load_module("owned_reproduction_proof", root / "scripts/verify_hepta_callers.py")
        protected = [row for row in after["protected_file"] if owned(row["path"])]
        proof._verify_protected_files(root, {"protected_file": protected})
        protected_count = len(protected)
        py_compile.compile(
            str(root / "qa/b4-no-bypass/test_original_candidate_stage_source_closure.py"),
            cfile=str(output / "candidate-source-closure.pyc"),
            doraise=True,
        )
        subprocess.run(["git", "-C", str(root), "diff", "--check", BASE, head], check=True)
    assert git(root, "rev-parse", "HEAD").strip() == head
    assert not git(root, "status", "--porcelain"), "source changed during qualification"
    receipt = {
        "mode": args.mode,
        "head": head,
        "tree": tree,
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skips": len(result.skipped),
        "success": result.wasSuccessful(),
        "log_bytes": len(raw),
        "log_sha256": hashlib.sha256(raw).hexdigest(),
        "protected_rows_verified": protected_count,
        "files": files,
        "scope": "owned Python only; no Rust, full source suite or full caller proof",
    }
    (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
