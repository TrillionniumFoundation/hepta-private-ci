"""Read-only verification of the missing v6 baseline before v7 development."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


V6_COMMIT = "febdbb1ebb5e7fb9f585b10b3ec743fb5d22eb24"
V5_COMMIT = "e38d09836c87d970b8c869961d08c1d42499e220"
V3_COMMIT = "1dc975504276d9f7af3b28f0f7b1c2a79ef66d8d"
V6_ROOT = Path("experiments/hcsn_integrated_execution_v6")
PROTOCOL_SHA256 = "c030217c1fc03ebcd1c706c12e2b40c1e300b2956979a9aaccb87ac200899176"
BUNDLES = {
    "v5": (629391107, "9159be343285855a6d1dccb290213791407f8df742a2df1363c17868beb3f1ac"),
    "v6": (353859429, "4d9bc1ee333a582e8cf0718f029337ed49f08f06525a7eccd169df00d99f687f"),
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def inspect(repo, supplied_bundles):
    result = {
        "schema": "hcsn-v7-baseline-recovery-check.v1",
        "expected_identity_source": "Previously delivered v6 identities in the conversation; verified only when matching bytes are present",
        "expected_v6_commit": V6_COMMIT,
        "expected_v5_commit": V5_COMMIT,
        "v3_prerequisite": V3_COMMIT,
        "repository": str(repo),
        "bundles": {},
        "source_and_input_inventory": {},
        "problems": [],
        "new_confirmation_executed": False,
        "confirmation_authorized_by_this_check": False,
    }
    for version, path in supplied_bundles.items():
        expected_bytes, expected_sha = BUNDLES[version]
        record = {"path": str(path), "present": path.is_file()}
        if path.is_file():
            record.update(bytes=path.stat().st_size, sha256=digest(path))
            record["identity_matches"] = record["bytes"] == expected_bytes and record["sha256"] == expected_sha
        else:
            record["identity_matches"] = False
        result["bundles"][version] = record
        if not record["identity_matches"]:
            result["problems"].append("supplied " + version + " bundle is missing or has a different identity")
    if not repo.is_dir():
        result["problems"].append("v6 repository directory is unavailable")
    else:
        for ref in (V5_COMMIT, V6_COMMIT):
            command = ["git", "-C", str(repo), "cat-file", "-t", ref]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if completed.returncode or completed.stdout.strip() != "commit":
                result["problems"].append("missing commit object: " + ref)
        if not result["problems"]:
            completed = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", V6_COMMIT, "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            if completed.returncode:
                result["problems"].append("working HEAD is not v6 or a descendant of v6")
        protocol = repo / V6_ROOT / "configs/frontend/CONFIRMATION_PROTOCOL.json"
        if not protocol.is_file():
            result["problems"].append("v6 confirmation protocol is unavailable")
        elif digest(protocol) != PROTOCOL_SHA256:
            result["problems"].append("v6 confirmation protocol identity differs")
        else:
            document = json.loads(protocol.read_text())
            for group in ("sources", "inputs"):
                declared = document.get(group)
                if not isinstance(declared, dict) or not declared:
                    result["problems"].append("empty or invalid " + group + " inventory")
                    continue
                failures = []
                for name, expected in declared.items():
                    path = (repo / name).resolve()
                    if not path.is_relative_to(repo.resolve()):
                        failures.append({"path": name, "reason": "path escapes repository"})
                    elif not path.is_file():
                        failures.append({"path": name, "reason": "missing; restore committed evidence archive first"})
                    elif digest(path) != expected:
                        failures.append({"path": name, "reason": "SHA256 mismatch"})
                result["source_and_input_inventory"][group] = {
                    "declared": len(declared), "verified": len(declared) - len(failures), "failures": failures,
                }
                if failures:
                    result["problems"].append(group + " inventory incomplete or changed")
    result["ready_for_v7_development"] = not result["problems"]
    result["status"] = "baseline_restored" if result["ready_for_v7_development"] else "blocked_on_v6_assets"
    result["scope"] = "Verifies baseline identities only; does not prove new cohort independence, model quality, or scientific acceptance"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--v5-bundle", type=Path)
    parser.add_argument("--v6-bundle", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    supplied = {v: p for v, p in (("v5", args.v5_bundle), ("v6", args.v6_bundle)) if p is not None}
    result = inspect(args.repo, supplied)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "problems": result["problems"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["ready_for_v7_development"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
