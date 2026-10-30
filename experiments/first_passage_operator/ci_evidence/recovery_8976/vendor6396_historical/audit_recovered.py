"""Read-only integrity audit of the historical 6396 vendor CI artifact.

This does not execute Rust, resolve dependencies, or validate reconstructed code.
The output is separate from the original immutable artifact contents.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    base = args.directory.resolve()
    artifact = base / "artifact"
    archive = (base / "artifact.zip").read_bytes()
    assert len(archive) == 150422
    assert sha256(archive) == "34a4cb7dcf62317d8948da6ca14c20b52fdbd92eaf02d1585ce66aceda09e592"
    manifest = json.loads((artifact / "artifact-manifest.json").read_text())
    actual_paths = {str(p.relative_to(artifact)) for p in artifact.rglob("*") if p.is_file()}
    assert actual_paths == set(manifest) | {"artifact-manifest.json"}
    for name, expected in manifest.items():
        data = (artifact / name).read_bytes()
        assert len(data) == expected["bytes"], name
        assert sha256(data) == expected["sha256"], name

    provenance = json.loads((artifact / "source-provenance.json").read_text())
    assert provenance["source_head"] == "6396bc013fdb16a955cced8a746e27279311361c"
    compat = artifact / "vendor-compatibility"
    receipt = json.loads((compat / "RECEIPT.json").read_text())
    assert receipt["passed"] == 6 and receipt["failures"] == []
    assert receipt["root_lock_before_sha256"] == receipt["root_lock_after_sha256"]
    assert receipt["root_lock_before_sha256"] == provenance["input_sha256"]["codex-rs/Cargo.lock"]
    lock = gzip.decompress((compat / "isolated.Cargo.lock.gz").read_bytes())
    assert sha256(lock) == receipt["isolated_lock_sha256"]
    for command in receipt["commands"]:
        assert command["exit_code"] == 0
        compressed = (compat / command["log"]).read_bytes()
        raw = gzip.decompress(compressed)
        assert len(raw) == command["log_uncompressed_bytes"]
        assert sha256(raw) == command["log_uncompressed_sha256"]
        assert sha256(compressed) == command["log_gzip_sha256"]

    tests = {}
    for package, expected in receipt["expected_tests"].items():
        cases = list(ET.parse(compat / f"{package}.junit.xml").getroot().iter("testcase"))
        assert sorted(case.attrib["name"] for case in cases) == sorted(expected), package
        for case in cases:
            assert not any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
        tests[package] = {"passed": len(cases), "skipped": 0, "names": expected}
    assert sum(item["passed"] for item in tests.values()) == 6

    inventories = {}
    for package, vendor in receipt["vendors"].items():
        inventory = json.loads((compat / vendor["source_inventory"]).read_text())
        assert len(inventory) == vendor["files"]
        assert len({item["path"] for item in inventory}) == len(inventory)
        root = args.repo / "codex-rs/third_party" / vendor["directory"]
        missing, different, matched = [], [], 0
        for item in inventory:
            path = root / item["path"]
            if not path.is_file():
                missing.append(item["path"])
                continue
            data = path.read_bytes()
            if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
                different.append(item["path"])
            else:
                matched += 1
        inventories[package] = {
            "historical_files": len(inventory),
            "materialized_matching": matched,
            "materialized_different": different,
            "not_materialized": len(missing),
        }

    output = {
        "schema": 1,
        "kind": "historical remote artifact integrity audit; no test execution",
        "head_sha": provenance["source_head"],
        "workflow_run_id": 40990854701,
        "artifact_id": 12949765079,
        "archive_sha256": sha256(archive),
        "manifest_members_verified": len(manifest),
        "full_log_commands_verified": len(receipt["commands"]),
        "historical_tests": tests,
        "source_inventory": inventories,
        "historical_source_file_count": sum(v["historical_files"] for v in inventories.values()),
        "audit_script_sha256": sha256(Path(__file__).read_bytes()),
        "limitations": [
            "This is the exact historical 6396 artifact, not a fresh test run.",
            "Missing vendor files in a sparse recovery checkout cannot be compared locally.",
            "These isolated vendor tests do not establish root consumer or Bazel build success.",
            "Reconstructed alias, macro-import, and path-fixture changes need fresh validation.",
        ],
    }
    with args.output.open("x") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"integrity": "passed", "historical_tests": 6, "output": str(args.output)}))


if __name__ == "__main__":
    main()
