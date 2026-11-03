#!/usr/bin/env python3
"""Bind successful Rust qualification diagnostics to an exact Git subject."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def verify_subject(kind, evaluated, source, base, parents):
    if any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (evaluated, source, base)):
        raise ValueError("invalid exact source identity")
    if kind == "head":
        if evaluated != source:
            raise ValueError("head does not match source")
    elif kind == "merge":
        if parents != [evaluated, base, source]:
            raise ValueError("merge does not preserve exact ordered parents")
    else:
        raise ValueError("unknown subject")


def summary(text, minimum=1):
    matches = re.findall(r"Summary\s+\[[^\]]+\]\s+(\d+) tests run: (\d+) passed, (\d+) skipped", text)
    if len(matches) != 1:
        raise ValueError("missing unambiguous successful nextest summary")
    run, passed, skipped = map(int, matches[0])
    if run < minimum or run != passed or skipped != 0:
        raise ValueError("all selected subject tests must execute and pass")
    return {"run": run, "passed": passed, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", choices=["head", "merge"], required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evaluated = git("rev-parse", "HEAD")
    verify_subject(args.subject, evaluated, args.source_sha, args.base_sha, git("rev-list", "--parents", "-n", "1", "HEAD").split())
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("qualification subject has tracked changes")
    log = args.out.parent / "tests.txt"
    data = log.read_bytes()
    counts = summary(data.decode("utf-8"), minimum=65 if platform.system() == "Linux" else 53)
    receipt = {
        "schema": "hepta.ui-control.rust-qualification-receipt.v1",
        "subject": {"kind": args.subject, "source": args.source_sha, "base": args.base_sha,
                    "commit": evaluated, "tree": git("rev-parse", "HEAD^{tree}")},
        "tests": counts,
        "rawTestLogSha256": hashlib.sha256(data).hexdigest(),
        "cargoLockSha256": hashlib.sha256((ROOT / "apps/hepta-control-ui/Cargo.lock").read_bytes()).hexdigest(),
        "claimBoundary": {"localRepositoryChecks": True, "browserParityComplete": False,
                          "crossPlatformControlStoreComplete": False, "realBackendQualified": False,
                          "independentAcceptance": False, "production": False, "activation": False, "release": False},
    }
    args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
