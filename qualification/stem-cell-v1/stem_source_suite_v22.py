"""Complete non-material Stem test discovery with explicit original evidence obligations.

Never claims that source-only results certify any original model, publisher,
independent future window, Head learning or production model selection.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
import unittest

# These tests MUST remain real and fail closed when directly invoked without
# original material. Their own original-artifact GitHub jobs own the evidence.
ORIGINAL_EVIDENCE = {
    "test_v18_original_independent_review": ".github/workflows/hepta-stem-v18-original-physical.yml",
    "test_v19_original_replay": ".github/workflows/hepta-stem-v19-trainonly-original.yml",
    "test_v20_original_training": ".github/workflows/hepta-stem-v20-independent-adam.yml",
    "test_v21_banking77_original": ".github/workflows/hepta-stem-v21-original-cross-family.yml",
}
SCHEMA = "hepta.stem.v22.source-and-original-coverage.v1"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def inventory(repo: Path):
    repo = Path(repo).resolve(strict=True)
    directory = repo / "qualification/stem-cell-v1"
    require(directory.is_dir() and not directory.is_symlink(), "real stem test root required")
    direct = sorted(directory.glob("test_*.py"))
    nested = [x for x in directory.rglob("test_*.py") if x.parent != directory]
    require(not nested, "unclassified nested tests require explicit discovery implementation")
    names = [f.stem for f in direct]
    require(len(names) == len(set(names)), "unique Python source-only module identities required")
    require(set(ORIGINAL_EVIDENCE) <= set(names), "original evidence test unexpectedly missing")
    for name, path in ORIGINAL_EVIDENCE.items():
        workflow = repo / path
        require(workflow.is_file() and not workflow.is_symlink(), "mandatory original CI missing: " + name)
        source = workflow.read_text(encoding="utf-8")
        require("pull_request:" in source
                and "persist-credentials: false" in source
                and ("-m unittest -q " + name) in source,
                "mandatory original test must physically run on PR HEAD: " + name)
        require("upload-artifact@" not in source or "original-" not in source.split("name:", 1)[0],
                "source manifest has no production authorization")  # no test bypass
    source = tuple(n for n in names if n not in ORIGINAL_EVIDENCE)
    require(bool(source), "no real source tests found")
    return {"root": repo, "directory": directory, "source_modules": source,
            "original_required": dict(ORIGINAL_EVIDENCE)}


def run(repo: Path, receipt: Path | None = None, *, stream=None) -> int:
    inv = inventory(repo)
    directory = str(inv["directory"])
    sys.path.insert(0, directory)
    try:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in inv["source_modules"]:
            # Imports and load_tests may fail normally; never synthesize passes.
            suite.addTests(loader.loadTestsFromName(name))
        count = suite.countTestCases()
        require(count > 0, "no source test assertions selected")
        result = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2).run(suite)
    finally:
        sys.path.remove(directory)
    data = {
        "schema": SCHEMA,
        "source_modules": list(inv["source_modules"]),
        "original_material_tests_required_in_separate_ci": inv["original_required"],
        "source_selected_assertions": count,
        "source_failures": len(result.failures),
        "source_errors": len(result.errors),
        "source_skips": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
        "source_passed": result.wasSuccessful(),
        "original_material_ran_here": False,
        "independent_original_model_or_publisher_evidence_qualified": False,
        "production_authorized": False,
        "decision": "SOURCE_ONLY_DOES_NOT_QUALIFY_ORIGINAL_MODEL",
    }
    if receipt is not None:
        path = Path(receipt)
        require(path.parent.is_dir() and not path.is_symlink(), "create-only receipt directory required")
        with path.open("x", encoding="utf-8") as out:
            json.dump(data, out, sort_keys=True, indent=2)
    return 0 if result.wasSuccessful() else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    args = p.parse_args()
    raise SystemExit(run(args.repo_root, args.receipt))


if __name__ == "__main__":
    main()
