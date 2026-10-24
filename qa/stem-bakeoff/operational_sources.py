"""Acquire only protocol-pinned Git objects; retain exact command logs and hashes."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from operational_cohort_plan import canonical, digest


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree_bytes(directory):
    return sum(p.stat().st_size for p in Path(directory).rglob("*") if p.is_file())


def acquire(protocol, output):
    raw = Path(protocol).read_bytes()
    plan = json.loads(raw)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    binding = digest(raw)
    cap = plan["execution_policy"]["acquired_artifact_byte_limit"]
    receipts = []
    for project, spec in plan["projects"].items():
        if (re.fullmatch(r"[A-Za-z0-9_.-]+", project) is None or
                re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", spec["url"]) is None):
            raise ValueError("source acquisition accepts only the pinned public GitHub project names")
        revisions = sorted({revision for bug in plan["bugs"] if bug["project"] == project
                            for revision in bug["revisions"].values()})
        if not revisions or any(re.fullmatch(r"[0-9a-f]{40}", r) is None for r in revisions):
            raise ValueError("full immutable revisions required")
        store = output / (project + ".git")
        receipt_path = output / (project + ".acquisition.json")
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_bytes())
            if receipt["protocol_sha256"] != binding or receipt["revisions"] != revisions:
                raise ValueError("existing source receipt belongs to another plan")
            for item in receipt["packs"]:
                if file_sha(store / item["path"]) != item["sha256"]:
                    raise ValueError("existing pinned Git object pack changed")
            receipts.append(receipt)
            continue
        if not store.exists():
            subprocess.run(["git", "init", "--bare", str(store)], check=True, capture_output=True, timeout=30)
        command = ["git", "--git-dir=" + str(store), "-c", "protocol.file.allow=never",
                   "fetch", "--no-tags", "--depth=1", spec["url"], *revisions]
        start = time.perf_counter_ns()
        with (output / (project + ".fetch.log")).open("wb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode:
            raise RuntimeError("source fetch failed; see " + str(log.name))
        if tree_bytes(output) > cap:
            raise ValueError("source artifact budget exceeded; stop acquisition")
        trees = {}
        for revision in revisions:
            trees[revision] = subprocess.check_output(["git", "--git-dir=" + str(store), "rev-parse", revision + "^{tree}"], text=True).strip()
        packs = [{"path": str(p.relative_to(store)), "bytes": p.stat().st_size, "sha256": file_sha(p)}
                 for p in sorted((store / "objects" / "pack").glob("*.pack"))]
        receipt = {"schema": "hepta.operational-source-acquisition.v1", "protocol_sha256": binding,
            "project": project, "url": spec["url"], "revisions": revisions, "trees": trees,
            "command": command, "wall_ns": time.perf_counter_ns() - start, "returncode": result.returncode,
            "packs": packs, "git_store_bytes": tree_bytes(store), "network_transfer_bytes": None,
            "network_transfer_note": "Git pack storage is measured; no fabricated socket transfer count.",
            "log_sha256": file_sha(output / (project + ".fetch.log"))}
        receipt_path.write_bytes(canonical(receipt))
        receipts.append(receipt)
        print(json.dumps({"project": project, "revisions": len(revisions), "git_store_bytes": receipt["git_store_bytes"]}), flush=True)
    result = {"schema": "hepta.operational-source-bank.v1", "protocol_sha256": binding,
        "projects": len(receipts), "pinned_revisions": sum(len(r["revisions"]) for r in receipts),
        "acquired_source_bytes": tree_bytes(output), "source_code_sha256": file_sha(__file__),
        "receipts": {r["project"]: file_sha(output / (r["project"] + ".acquisition.json")) for r in receipts}}
    (output / "manifest.json").write_bytes(canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.protocol, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
