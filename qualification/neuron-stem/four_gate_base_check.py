#!/usr/bin/env python3
"""Verify inspected parent files before applying the additive research integration.

This is byte/API compatibility only. It never proves inherited tests, native
execution, model loading or independent outcomes.
"""
import argparse
import hashlib
import inspect
from pathlib import Path
import sys

from four_gate_core import BASE_COMMIT, canonical, require

PARENT_BLOBS = {
    "qualification/neuron-stem/prequential_threeway_review.py": "c67c85e6e48f31c1caaf87fba509a5dfd112306c",
    "qualification/neuron-stem/resource_gate.py": "b619bab730c679706eb77ae0f12501bc20e51790",
    ".github/workflows/hepta-neuron-stem-qualification.yml": "4a0bf0229fa44af230bc6af4a2f09a2b6898f718",
}


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def check(repository, check_api=False):
    root = Path(repository)
    findings = {}
    for relative, expected in PARENT_BLOBS.items():
        path = root / relative
        require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink parent source")
        require(path.is_file(), "missing inherited source: " + relative)
        actual = git_blob_sha(path.read_bytes())
        require(actual == expected, "inherited source drift; re-review before integration: " + relative)
        findings[relative] = actual
    if check_api:
        sys.path.insert(0, str(root / "qualification/neuron-stem"))
        import prequential_threeway_review as inherited
        require(Path(inherited.__file__).resolve() ==
                (root / "qualification/neuron-stem/prequential_threeway_review.py").resolve(),
                "inherited reviewer import path mismatch")
        signature = inspect.signature(inherited.review)
        require(list(signature.parameters) == ["dataset", "trial", "journal_bytes", "nochange", "resources",
                                               "ood_receipts", "min_future_groups", "replicates", "seed"],
                "inherited review API drift")
    return {"inspected_base_commit": BASE_COMMIT, "parent_blob_checks": findings,
            "inherited_review_api_checked": check_api, "inherited_end_to_end_trial_executed": False,
            "production_promotion_permitted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=".")
    parser.add_argument("--check-api", action="store_true")
    args = parser.parse_args()
    try:
        print(canonical(check(args.repository, args.check_api)).decode())
    except (ValueError, OSError, ImportError) as exc:
        print("Parent compatibility unverified: " + str(exc), file=sys.stderr)
        sys.exit(2)
