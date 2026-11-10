"""Read and bind already-produced C2 v2 evidence; do not execute its tests."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def save(name, value):
    with (OUT / name).open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main():
    source = ROOT / "c2-feasibility-v2"
    assert sha(source / "c2_boundary.py") == "177a23a3d0502a79912efdd2a14a365bc716961698a6949bb45d380ba147e6dd"
    receipt = json.loads((source / "validation/RESULT.json").read_bytes())
    assert receipt["source_before"] == receipt["source_after"] and receipt["returncode"] == 0
    for name, digest in receipt["source_after"].items():
        assert sha(ROOT / name) == digest
    stderr = (source / "validation/stderr.log").read_text()
    assert "Ran 21 tests" in stderr and stderr.strip().endswith("OK")
    assert receipt["independent_counterexamples_sha256"] == sha(ROOT / "clock-c2-independent-review-v1/COUNTEREXAMPLES.json")
    assert not receipt["native_training_started"] and not receipt["native_snapshot_started"]
    old = ROOT / "hcsn-c2-feasibility-20261110-v1.zip"
    assert sha(old) == "23fbe126fb13dc2aee5731919f174b0974abbb237d4e15c201cbf14c6cf05dbe"
    archive = ROOT / "hcsn-c2-feasibility-20261110-v2.zip"
    assert sha(archive) == "cea3eb1509ecec51174b0c86b0f60b5ed4eb938d0739972bcaa6c46f94fb5e96"
    with ZipFile(archive) as zipped:
        names = zipped.namelist()
        assert len(names) == len(set(names)) and zipped.testzip() is None
        for name in names:
            pure = PurePosixPath(name)
            assert not pure.is_absolute() and ".." not in pure.parts and "\\" not in name
        manifest = json.loads(zipped.read("MANIFEST.json"))
        records = manifest.get("files", manifest)
        for name, record in records.items():
            raw = zipped.read(name)
            assert raw == (ROOT / name).read_bytes()
            assert len(raw) == record["bytes"] and hashlib.sha256(raw).hexdigest() == record["sha256"]
    result = {
        "schema": "independent-C2-v2-closure-static-review-v1",
        "source": identity(source / "c2_boundary.py"), "tests": identity(source / "test_c2_boundary.py"),
        "owner_validation": identity(source / "validation/RESULT.json"),
        "owner_stdout": identity(source / "validation/stdout.log"), "owner_stderr": identity(source / "validation/stderr.log"),
        "archive": identity(archive), "archive_crc_safe_unique_paths": True,
        "archive_member_bytes_exact_to_local_inputs": len(records), "archive_members": len(names),
        "v1_capsule_preserved": identity(old),
        "counterexample_result": identity(ROOT / "clock-c2-independent-review-v1/COUNTEREXAMPLES.json"),
        "closed_findings": ["C2-01 first historical plateau", "C2-02 negative initial clock", "C2-03 negative real AdamW second moment"],
        "owner_tests_reported_passed": 21, "tests_rerun_by_this_review": 0,
        "owner_validation_complete_process_wall_seconds": receipt["whole_process_wall_seconds"],
        "owner_validation_waited_child_cpu_seconds": receipt["child_cpu_seconds"],
        "native_checkpoint_read": False, "model_forward_or_training_performed": False,
        "native_C2_started": False, "execution_authorized": False, "scientific_admission": "HOLD",
        "source_data_runtime_admission_still_required": True,
        "outcome": "three prior structural gaps closed by exact versioned code; no new blocker found in the reviewed diff",
    }
    save("RESULT.json", result)
    save("MANIFEST.json", {"files": {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in OUT.iterdir() if p.is_file()}})
    print(json.dumps({"result": identity(OUT / "RESULT.json"), "review": identity(OUT / "REVIEW.md"),
                      "manifest": identity(OUT / "MANIFEST.json")}, indent=2))


if __name__ == "__main__":
    main()
