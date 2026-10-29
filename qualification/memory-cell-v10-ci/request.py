"""Strict mode selection; trigger requests live outside the frozen research tree."""

import argparse
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASELINE, BRANCH, ROOT, REQUEST_RELATIVE, identity, load, require


def read_request():
    request = load(ROOT / REQUEST_RELATIVE, 65_536)
    common = {"schema", "mode", "request_id", "baseline_commit", "source_manifest_sha256",
              "protocol_sha256", "tests_before_final_fix_and_format"}
    mode = request.get("mode")
    require(mode in ("verify", "finalize"), "mode must be verify or finalize")
    require(set(request) == common | ({"verification"} if mode == "finalize" else set()),
            "unexpected request fields")
    require(request["schema"] == "hepta.memory.v10.ci-request.v1" and request["baseline_commit"] == BASELINE
            and request["tests_before_final_fix_and_format"] is True, "request violates fixed source/order contract")
    require(isinstance(request["request_id"], str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", request["request_id"]), "invalid request ID")
    for field, name in (("source_manifest_sha256", "SOURCE_MANIFEST.json"), ("protocol_sha256", "PROTOCOL.json")):
        require(request[field] == identity(ROOT / "qualification/memory-cell-v10" / name)["sha256"],
                "request does not pin the current research " + name)
    if mode == "finalize":
        proof = request["verification"]
        require(isinstance(proof, dict) and set(proof) == {"run_id", "run_attempt", "job_id", "artifact_id",
                "commit", "tree", "transport_sha256", "receipt_sha256"}, "invalid verification proof fields")
        for name in ("run_id", "run_attempt", "job_id", "artifact_id"):
            require(type(proof[name]) is int and proof[name] > 0, "invalid verification integer")
        for name in ("commit", "tree", "transport_sha256", "receipt_sha256"):
            count = 40 if name in ("commit", "tree") else 64
            require(isinstance(proof[name], str) and re.fullmatch("[0-9a-f]{" + str(count) + "}", proof[name]),
                    "invalid verification digest")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH, "unexpected CI branch")
    return request


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    request = read_request()
    if args.github_output is not None:
        with args.github_output.open("a") as output:
            output.write("mode=" + request["mode"] + "\n")
    print("V10 CI mode: " + request["mode"])
