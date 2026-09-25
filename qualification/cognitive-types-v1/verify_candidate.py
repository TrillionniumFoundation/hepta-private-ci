#!/usr/bin/env python3
"""Bind actual checkout and fetched current base; preserve stale trigger metadata."""

import json
import os
from pathlib import Path
import re
import subprocess


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def verify_identity(kind, actual, parents, expected_head, current_base):
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (actual, expected_head, current_base)):
        raise ValueError("invalid candidate identity")
    if kind == "exact-head":
        if actual != expected_head:
            raise ValueError("exact-head drift")
    elif kind == "synthetic-merge":
        if parents != [current_base, expected_head]:
            raise ValueError("synthetic merge does not bind fetched current base and exact head")
    else:
        raise ValueError("unknown candidate kind")


def main():
    base_ref = os.environ["BASE_REF"]
    subprocess.run(["git", "check-ref-format", "refs/heads/" + base_ref], check=True)
    current_base = git("rev-parse", "refs/remotes/origin/" + base_ref)
    actual = git("rev-parse", "HEAD")
    parents = git("show", "-s", "--format=%P", "HEAD").split()
    receipt = {
        "schema": "hepta.cognitive-types.candidate.v1",
        "candidate": actual,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "head": os.environ["HEAD_SHA"],
        "base": current_base,
        "trigger_base": os.environ.get("BASE_SHA", ""),
        "kind": os.environ["CANDIDATE_KIND"],
        "parents": parents,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "product_activation": False,
    }
    try:
        verify_identity(receipt["kind"], actual, parents, receipt["head"], current_base)
    except ValueError as error:
        receipt["identity_valid"] = False
        receipt["identity_error"] = str(error)
    else:
        receipt["identity_valid"] = True
    Path(os.environ["RUNNER_TEMP"], "hnmf-candidate.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    if not receipt["identity_valid"]:
        raise SystemExit(receipt["identity_error"])


if __name__ == "__main__":
    main()
