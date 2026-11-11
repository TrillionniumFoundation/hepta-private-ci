"""Verify immutable downloaded evidence; execute only the reviewed offline verifier."""
import base64
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
COMMIT = "ce99fa1c550338462fc47519381ea39b29db9e03"
HEAD = "2ae5215beaf8d7b7df111a090b82134beae2683d"
TREE = "12159640adcf073b51f3837e75575e11f5c20233"
PINS = {
    "A": (414648, "4cd8bbc40cbd4570f187c56338352e60ebc24efe20f46bf80853448537d4915f", "edfda1dced0bb37ce277336ef93a6a2634b9a0e9", 23),
    "B": (447348, "5148e9b09b0a1ea8c9d394b35b3077b833f86924004e2e6a5eaf295eaa5d4c71", "91b59d73400aa95cbe3e56fba3e8b1ef59d0ae28", 43),
    "W": (187144, "0ff3cd2090f7ce7504c83aacbcf67e9785ce56320235a4ad885ce869649a59c5", "be3cac4b00b36eb56c891d342f3429001cf415ce", 28),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def fetch_bytes(label):
    record = json.loads((ROOT / f"READBACK_{label}.json").read_text())
    assert record["encoding"] == "base64" and COMMIT in record["display_url"]
    data = base64.b64decode("".join(record["content"].split()), validate=True)
    assert blob(data) == record["sha"]
    return data


def members(data):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        for entry in archive:
            name = PurePosixPath(entry.name)
            assert entry.isfile() and not name.is_absolute() and ".." not in name.parts
            assert entry.name not in result
            result[entry.name] = archive.extractfile(entry).read()
            assert len(result[entry.name]) == entry.size
    return result


def verify_manifest(data, rows, exempt=()):
    assert set(data) == {row["path"] for row in rows} | set(exempt)
    for row in rows:
        value = data[row["path"]]
        assert len(value) == row["bytes"] and sha(value) == row["sha256"]


def receipt(data, name, expected_exit):
    record = json.loads(data[name])
    raw = data[record["raw_file"]]
    assert record["exit_code"] == expected_exit and not record["timed_out"]
    assert len(raw) == record["raw_bytes"] and sha(raw) == record["raw_sha256"]
    assert datetime.fromisoformat(record["started_at"]) <= datetime.fromisoformat(record["finished_at"])
    return record, raw


def main():
    archive_manifest = json.loads(fetch_bytes("M"))
    assert blob(fetch_bytes("M")) == "b6f485c4aa41f993bc09c6747415f8c96c1b9b9f"
    unpacked = {}
    archives = []
    for label, (size, digest, git_blob, count) in PINS.items():
        raw = fetch_bytes(label)
        assert len(raw) == size and sha(raw) == digest and blob(raw) == git_blob
        data = members(raw)
        assert len(data) == count
        if label in ("A", "B"):
            manifest = next(row for row in archive_manifest["archives"] if row["git_blob"] == git_blob)
            assert manifest["bytes"] == size and manifest["sha256"] == digest
            verify_manifest(data, manifest["member_manifest"])
        else:
            manifest = json.loads(fetch_bytes("WM"))
            assert blob(fetch_bytes("WM")) == "e971544a8c0050fe98a213cbaefc0851b424efcd"
            verify_manifest(data, manifest["files"], ["MANIFEST.json"])
        unpacked[label] = data
        archives.append({"label": label, "bytes": size, "sha256": digest,
                         "git_blob": git_blob, "members": count, "full_readback_verified": True})

    a = unpacked["A"]
    verify_manifest(a, json.loads(a["FILE_MANIFEST.json"])["members"], ["FILE_MANIFEST.json"])
    result_a = json.loads(a["RESULT.json"])
    assert result_a["status"] == "passed" and result_a["failure"] is None
    assert result_a["source_before"] == {"head": HEAD, "tree": TREE, "status": ""}
    assert result_a["source_after"]["head"] == HEAD and result_a["source_after"]["tree"] == TREE
    assert result_a["source_after"]["status"] == "M codex-rs/hepta-memory/src/production_episodic_test_support.rs"
    assert datetime.fromisoformat(result_a["finished_at"]) <= datetime.fromisoformat(result_a["deadline_utc"])
    assert result_a["native_commands"] == result_a["model_calls"] == 0
    before = a["production_episodic_test_support.before.rs"]
    after = a["production_episodic_test_support.after.rs"]
    signature = b"pub(super) async fn fixture() -> Result<Fixture, Box<dyn std::error::Error>> {"
    assert before.count(signature) == 1 and after == before.replace(signature, b"#[cfg(test)]\n" + signature)
    assert blob(before) == result_a["preimage_git_blob"]
    assert blob(after) == result_a["candidate_git_blob"] == "c822b1c5c4a579737d0487c36c8262926f5186e6"
    _, original_failure = receipt(a, "caller-verify-before.json", 1)
    assert original_failure.startswith(b"FAIL_HEPTA_CALLER_PROOF:")
    _, complete_caller = receipt(a, "caller-verify-after.json", 0)
    caller_report = json.loads(complete_caller)
    assert caller_report["status"] == "PASS_HEPTA_CALLER_CLOSED_SET"
    assert caller_report["rustFilesScanned"] == 6190

    b = unpacked["B"]
    verify_manifest(b, json.loads(b["MEMBER_MANIFEST.json"])["members"], ["MEMBER_MANIFEST.json"])
    original = {name.removeprefix("formatter-attempt/"): data for name, data in b.items()
                if name.startswith("formatter-attempt/")}
    verify_manifest(original, json.loads(original["FILE_MANIFEST.json"])["members"], ["FILE_MANIFEST.json"])
    receipt(original, "format.json", 0)
    failure_b1 = json.loads(original["RESULT.json"])
    failure_b2 = json.loads(b["verification-continuation/RESULT.json"])
    assert failure_b1["status"] == failure_b2["status"] == "failed"
    assert failure_b1["failure"] == "FileNotFoundError: [Errno 2] No such file or directory: 'rg'"
    assert failure_b1["completed"] == ["format"] and failure_b2["completed"] == []
    assert failure_b2["failure"].startswith("AssertionError")
    assert all("caller-verify" not in name and "caller-self-test" not in name for name in b)
    assert failure_b1["rust_tests_executed"] == failure_b1["model_calls"] == 0
    assert failure_b2["rust_tests_executed"] == failure_b2["model_calls"] == 0
    for run in (failure_b1, failure_b2):
        assert datetime.fromisoformat(run["finished_at"]) <= datetime.fromisoformat(run["deadline_utc"])
    lines = b["verification-continuation/all-episodic-import-references.raw.log"].decode().splitlines()
    assert len(lines) == 8
    assert sum(line.startswith("codex-rs/hepta-memory/") for line in lines) == 3
    assert sum(line.startswith("codex-rs/hepta-agentd/") for line in lines) == 5
    for row in failure_b2["final_postimages"]:
        content = original["post-format/" + row["path"]]
        assert blob(content) == row["git_blob"] and sha(content) == row["sha256"]
        assert len(content) == row["bytes"]

    w = unpacked["W"]
    verify_manifest(w, json.loads(w["MANIFEST.json"])["files"], ["MANIFEST.json"])
    verifier = ROOT / "extracted/W/verify.py"
    assert verifier.read_bytes() == w["verify.py"]
    archive_path = ROOT / "windows-current-original.tar.xz"
    archive_path.write_bytes(fetch_bytes("W"))
    executed = subprocess.run([sys.executable, "-B", str(verifier), str(archive_path)],
                              capture_output=True, text=True, timeout=30, check=False)
    assert executed.returncode == 0 and not executed.stderr, executed.stderr
    windows = json.loads(executed.stdout)
    assert windows["counts"] == {"PASS": 115, "LEAK": 1, "FAIL": 8}
    output = {
        "schema": "hepta.mem8.ci-v11.root-complete-readback.v1",
        "immutable_commit": COMMIT,
        "archives": archives,
        "one_line_dirty_candidate": {"original_caller_exit": 1, "candidate_caller_exit": 0,
                                    "rust_files_scanned": 6190, "native_tests_executed": 0},
        "four_path_candidate": {"formatter_exit": 0, "driver_failures": 2,
                                "full_caller_executions": 0, "native_tests_executed": 0,
                                "eight_reference_count_failure_preserved": True},
        "original_windows_current": windows,
        "offline_verifier_replays": 1,
        "archived_drivers_executed": 0,
        "new_native_tests_executed": 0,
        "new_model_requests": 0,
        "qualification_transferred_to_repair_head": False,
        "passed": True,
    }
    (ROOT / "ROOT_READBACK_AUDIT.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
