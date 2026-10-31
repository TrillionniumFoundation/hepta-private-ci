"""Enforce a separate source/candidate freeze for the traditional baselines."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from run_study import execute


BASE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(candidate_commit=None):
    source = BASE / "COMPARISON_FREEZE.json"
    manifest = json.loads(source.read_text())
    for name, digest in manifest["source_sha256"].items():
        if sha(BASE / name) != digest:
            raise RuntimeError("secondary source changed: " + name)
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(key) != "1":
            raise RuntimeError("set " + key + "=1 before Python startup")
    if candidate_commit is not None:
        path = BASE / "COMPARISON_CANDIDATE.json"
        candidate = json.loads(path.read_text())
        if candidate["source_freeze_sha256"] != sha(source):
            raise RuntimeError("secondary candidate source mismatch")
        expected = {f"evidence/comparison/runs/{task}/{family}_w{width}_s{seed}/final.npz"
                    for task in ("associative_recall", "multimodal_evidence", "digits_rows")
                    for family in ("transformer", "lif_surrogate") for width in (16, 32, 64)
                    for seed in (11, 23, 37)}
        if set(candidate["artifact_sha256"]) != expected:
            raise RuntimeError("all 54 secondary candidates are required")
        for name, digest in candidate["artifact_sha256"].items():
            if sha(BASE / name) != digest:
                raise RuntimeError("secondary candidate changed: " + name)
        result = subprocess.run(["git", "show", candidate_commit + ":experiments/"
                                 "hcsn_regeneration_content_20261031/COMPARISON_CANDIDATE.json"],
                                cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            if hashlib.sha256(result.stdout).hexdigest() != sha(path):
                raise RuntimeError("secondary manifest differs from published commit")
        else:
            receipt = json.loads((BASE / "evidence" / "comparison_remote_readback.json").read_text())
            if receipt["commit"] != candidate_commit or receipt["manifest_sha256"] != sha(path):
                raise RuntimeError("missing secondary remote readback")
    return sha(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "dev", "test"))
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--candidate-commit")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.freeze_commit):
        parser.error("published secondary source commit required")
    if args.phase == "test" and not re.fullmatch("[0-9a-f]{40}", args.candidate_commit or ""):
        parser.error("published secondary candidate commit required")
    digest = verify(args.candidate_commit if args.phase == "test" else None)
    command = ["comparison_run.py", "train"] if args.phase == "train" else [
        "comparison_run.py", "evaluate", "--split", args.phase]
    execute("comparison_" + args.phase, command, args.freeze_commit, args.candidate_commit, digest)


if __name__ == "__main__":
    main()
