"""Small builder/verifier integration; no actual scientific archive is opened."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
import time

import archive_build as builder
import archive_integrity as integrity
import archive_integrity_tests as fixtures


def execute(directory):
    started = time.perf_counter_ns()
    data = fixtures.payloads()
    source = directory / "source"
    source.mkdir()
    entries = []
    for index, (name, raw) in enumerate(sorted(data.items())):
        path = source / str(index)
        path.write_bytes(raw)
        entries.append({"source": str(path), "path": name})
    index = {"schema": "hepta.field-bridge.v3.archive-input-index.1", "entries": entries,
             "provenance": fixtures.manifest(data)["provenance"]}
    index_path = directory / "INDEX.json"
    index_path.write_bytes(integrity.canonical(index))
    first, receipt = directory / "first.tar.gz", directory / "first.json"
    built = builder.build(index_path, first, receipt)
    restored = directory / "restored"
    verified = integrity.verify_archive(first, expected_sha256=built["archive_sha256"],
        expected_manifest_sha256=built["manifest_sha256"], restore_paths=["assets/small.bin"], destination=restored)
    assert verified["payload_members"] == len(data) and (restored / "assets/small.bin").read_bytes() == data["assets/small.bin"]
    checks = ["builder_to_independent_full_integrity_and_literal_selective_restore"]
    second = builder.build(index_path, directory / "second.tar.gz", directory / "second.json")
    assert first.read_bytes() == (directory / "second.tar.gz").read_bytes()
    assert built["archive_sha256"] == second["archive_sha256"] and built["manifest_sha256"] == second["manifest_sha256"]
    checks.append("same_explicit_inputs_deterministic_archive_bytes")
    before = integrity.file_sha(first)
    try:
        builder.build(index_path, first, directory / "replacement.json")
    except ValueError:
        pass
    else:
        raise AssertionError("Existing archive was replaced")
    assert integrity.file_sha(first) == before and not (directory / "first.tar.gz.partial").exists()
    checks.append("existing_archive_not_overwritten")
    invalid = []
    duplicate = copy.deepcopy(index)
    duplicate["entries"].append(duplicate["entries"][0])
    invalid.append(("duplicate_input_name", duplicate))
    provenance = copy.deepcopy(index)
    provenance["provenance"]["registered_commits"] = ["not-a-commit"]
    invalid.append(("strict_provenance_preflight", provenance))
    unsafe = copy.deepcopy(index)
    unsafe["entries"][0]["path"] = "run"
    invalid.append(("strict_root_only_path_preflight", unsafe))
    for name, value in invalid:
        index_path.write_bytes(integrity.canonical(value))
        output, record = directory / (name + ".tar.gz"), directory / (name + ".json")
        try:
            builder.build(index_path, output, record)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid explicit index accepted: " + name)
        assert not output.exists() and not output.with_name(output.name + ".partial").exists() and not record.exists()
        checks.append(name + "_no_partial")
    return {"schema": "hepta.field-bridge.v3.archive-build-contract.1", "passed": True, "synthetic_only": True,
        "check_count": len(checks), "checks": checks,
        "source_files": {Path(path).name: integrity.file_sha(path) for path in (builder.__file__, integrity.__file__, __file__)},
        "scientific_model_observer_native_network_calls": 0, "verification_wall_ns": time.perf_counter_ns() - started}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    with tempfile.TemporaryDirectory(prefix="v3-archive-build-contract-") as directory:
        result = execute(Path(directory))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": result["passed"], "check_count": result["check_count"]}))
