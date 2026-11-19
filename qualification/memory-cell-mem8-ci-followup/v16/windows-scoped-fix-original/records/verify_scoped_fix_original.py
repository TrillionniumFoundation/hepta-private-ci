"""Verify original Windows scoped-fix receipts offline; run no native commands."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = "b0547d2f874c0aeb54dabd3491caa2bee49fcb0b"
TREE = "3f89ddeff13d0af85f4abe2690699107357f1038"
HARNESS = "c97586834214c8a0a610f860cc7ae261ce8cccde"


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def load(name):
    return json.loads((ROOT / name).read_text())


def main():
    outer_manifest = ROOT / "PACKAGE_MEMBERS.json"
    if outer_manifest.exists():
        manifest = load("PACKAGE_MEMBERS.json")
        for row in manifest["members"]:
            path = ROOT / row["path"]
            assert path.is_file() and not path.is_symlink()
            assert pin(path.read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
        assert actual == {row["path"] for row in manifest["members"]} | {"PACKAGE_MEMBERS.json"}
        assert not any("DOWNLOAD_INPUT" in path for path in actual)
    jobs = json.loads(load("fix-run-raw.json")["content"])
    assert jobs["total_count"] == len(jobs["jobs"]) == 1
    job = jobs["jobs"][0]
    assert (job["id"], job["run_id"], job["head_sha"], job["status"], job["conclusion"]) == (130583219316, 43038376307, HARNESS, "completed", "failure")
    artifacts = load("fix-artifacts.json")["artifacts"]
    artifact = next(row for row in artifacts if row["id"] == 13865786917)
    raw = (ROOT / "original-job.log").read_bytes()
    assert pin(raw) == load("RAW_IDENTITY.json")
    assert load("fix-full-job.json")["content"].encode() == raw
    archive = (ROOT / "original-artifact.zip").read_bytes()
    assert len(archive) == artifact["size_in_bytes"] == 73486
    assert hashlib.sha256(archive).hexdigest() == artifact["digest"].removeprefix("sha256:") == "fcc5aa8768b96b87c42bc7aa7d7d7d3c597539fda086e4e1c691b58f95578b6d"
    with zipfile.ZipFile(ROOT / "original-artifact.zip") as zip_file:
        assert zip_file.testzip() is None
        members = zip_file.infolist()
        assert len(members) == len({member.filename for member in members}) == 144
        for member in members:
            path = PurePosixPath(member.filename)
            assert not path.is_absolute() and ".." not in path.parts and "\\" not in member.filename
            assert not member.is_dir() and not stat.S_ISLNK(member.external_attr >> 16)
            assert zip_file.read(member) == (ROOT / "files" / member.filename).read_bytes()
    files_manifest = load("files/FILE_MANIFEST.json")
    assert len(files_manifest) == 143
    for row in files_manifest:
        data = (ROOT / "files" / row["path"]).read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    assert {row["path"] for row in files_manifest} | {"FILE_MANIFEST.json"} == {member.filename for member in members}
    result = load("files/RESULT.json")
    collection = load("files/COLLECTION.json")
    anchor = load("files/JOB_ANCHOR.json")
    assert result["status"] == "failed_or_interrupted" and collection["status"] == "partial_or_failed"
    assert result["source_head"] == SOURCE and result["source_tree"] == TREE and result["harness_sha"] == HARNESS
    assert result["run_id"] == "43038376307" and result["run_attempt"] == "1"
    assert result["native_test_commands"] == result["model_commands"] == []
    assert anchor["job_timeout_minutes"] == 65 and anchor["harness_sha"] == HARNESS
    commands = [
        ["just", "fix", "--locked", "-p", "codex-hepta-neuron", "--features", "qualification-owned-file-read"],
        ["just", "fix", "--locked", "-p", "codex-core"],
        ["just", "fix", "--locked", "-p", "codex-windows-sandbox"],
    ]
    phases = []
    first_tools, first_locks = None, None
    for index, command in enumerate(commands, 1):
        name = f"phase-{index}"
        phase = load(f"files/{name}.json")
        assert phase["command"] == command and phase["command_exit_code"] == 0
        assert phase["timeout_observed"] is (False if index < 3 else None)
        assert phase["before"]["commit"] == phase["after"]["commit"] == SOURCE
        assert phase["before"]["tree"] == phase["after"]["tree"] == TREE
        assert phase["before"]["dirty"] is False and phase["after"]["dirty"] is (index == 3)
        assert phase["status"] == ("passed_clean" if index < 3 else "failed_or_interrupted")
        assert phase["before"]["locks"] == phase["after"]["locks"]
        if first_locks is None:
            first_locks = phase["before"]["locks"]
        assert phase["after"]["locks"] == first_locks
        body = (ROOT / "files" / phase["raw_log"]["path"]).read_bytes()
        assert len(body) == phase["raw_log"]["bytes"] and hashlib.sha256(body).hexdigest() == phase["raw_log"]["sha256"]
        before_tools = load(f"files/{name}-tools-before/tools.json")
        after_tools = load(f"files/{name}-tools-after/tools.json")
        assert before_tools == after_tools
        if first_tools is None:
            first_tools = before_tools
        assert before_tools == first_tools
        postimages = load(f"files/{name}-source-after/postimages.json")
        if index < 3:
            assert postimages == []
            assert (ROOT / "files" / f"{name}-source-after/combined.patch").read_bytes() == b""
        else:
            assert len(postimages) == 2
        phases.append({"phase": name, "command": command, "command_exit_code": 0, "before_dirty": False, "after_dirty": index == 3, "status": phase["status"], "timeout_observed": phase["timeout_observed"], "raw": pin(body), "started_at": phase["started_at"], "finished_at": phase["finished_at"], "elapsed_seconds": phase["elapsed_seconds"]})
    rows = load("REVIEWED_CLIPPY_POSTIMAGES.json")
    assert len(rows) == 2
    patch = ROOT / "files/phase-3-source-after/combined.patch"
    assert len(patch.read_bytes()) == 2279
    allowed = {"codex-rs/windows-sandbox-rs/src/elevated_impl.rs", "codex-rs/windows-sandbox-rs/tests/helper_manifest.rs"}
    assert {row["path"] for row in rows} == allowed
    assert set(re.findall(r"^diff --git a/(\S+) b/", patch.read_text(), flags=re.M)) == allowed
    for row in rows:
        assert pin((ROOT / "original-source" / row["path"]).read_bytes()) == row["before"]
        assert pin((ROOT / "files/phase-3-source-after/postimages" / row["path"]).read_bytes()) == row["after"]
    with tempfile.TemporaryDirectory(prefix="mem-scoped-fix-evidence-") as temporary:
        directory = Path(temporary)
        for row in rows:
            target = directory / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "original-source" / row["path"], target)
        for flags in (["--check"], []):
            proc = subprocess.run(["git", "apply", *flags, str(patch)], cwd=directory, capture_output=True, timeout=20)
            assert proc.returncode == 0, proc.stderr
        for row in rows:
            assert (directory / row["path"]).read_bytes() == (ROOT / "files/phase-3-source-after/postimages" / row["path"]).read_bytes()
    return {"schema": "mem8.windows-scoped-fix-original-offline-audit.v1", "status": "EVIDENCE_REPLAY_PASS_ORIGINAL_QUALIFICATION_FAIL", "run_id": 43038376307, "job_id": 130583219316, "run_attempt": 1, "harness_head": HARNESS, "source_head": SOURCE, "source_tree": TREE, "artifact": {"id": 13865786917, **pin(archive)}, "zip_members": 144, "original_file_manifest_entries": 143, "original_full_job": pin(raw), "original_job_conclusion": "failure", "original_result": result["status"], "original_collection": collection["status"], "phases": phases, "tools_equal_across_all_before_after": True, "locks_equal_across_all_before_after": True, "dirty_postimage_paths": sorted(allowed), "native_test_commands": 0, "model_commands": 0, "offline_only": True, "separate_run_level_api_object_supplied": False, "api_boundary": "The supplied fix-run-raw.json is the original jobs API payload, not a separate run endpoint response. Run/job identities are also present in original phase/result/anchor records."}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
