"""Read the one original Windows lint artifact; never execute archived code."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SOURCE = "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
TREE = "658fa040046285116b1fd81b94ff8c96444072ad"
HARNESS = "23d9f41532e5e6310ca791a5b849ab1cff7466eb"
HARNESS_TREE = "4bddc28958d0bde7d2735d0a626c2052d33ccb24"
RUN = 43062162500
JOB = 130667533098
STAGES = [
    ("phase-1-build-sandbox-helpers", "helpers", ["cargo", "build", "--locked", "-p", "codex-windows-sandbox", "--profile", "dev-small", "--message-format=json", "--bin", "codex-windows-sandbox-setup", "--bin", "codex-command-runner"]),
    ("phase-2-fix-codex-windows-sandbox", "fix", ["just", "fix", "--locked", "-p", "codex-windows-sandbox"]),
]


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def digest(data):
    return {key: value for key, value in identity(data).items() if key != "git_blob"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def api(path):
    value = load(path)
    content = value.get("structuredContent", value)
    if isinstance(content, dict) and isinstance(content.get("content"), str):
        return json.loads(content["content"])
    return content


def audit(root):
    plan = load(root / "FROZEN_PLAN.json")
    assert plan["source_head"] == SOURCE and plan["source_tree"] == TREE
    assert plan["native_test_commands"] == [] and plan["job_timeout_minutes"] == 65
    assert plan["native_or_elevated_PASS_admission_dependency"] is False
    jobs = api(root / "TERMINAL_JOBS.json")["jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert (job["id"], job["run_id"], job["head_sha"], job["status"]) == (JOB, RUN, HARNESS, "completed")
    assert job["run_attempt"] == 1
    raw = (root / "original-job.log").read_bytes()
    raw_tool = load(root / "JOB_LOG_TOOL_RESPONSE.json")
    assert raw_tool["structuredContent"]["content"].encode() == raw
    meta = load(root / "ARTIFACT_METADATA.json")
    zip_data = (root / "ORIGINAL_ARTIFACT.zip").read_bytes()
    assert len(zip_data) == meta["size_in_bytes"]
    assert "sha256:" + hashlib.sha256(zip_data).hexdigest() == meta["digest"]
    assert meta["workflow_run"]["id"] == RUN and meta["workflow_run"]["head_sha"] == HARNESS
    files = {}
    with zipfile.ZipFile(root / "ORIGINAL_ARTIFACT.zip") as archive:
        assert archive.testzip() is None
        for row in archive.infolist():
            path = PurePosixPath(row.filename)
            assert not row.is_dir() and row.filename not in files
            assert str(path) == row.filename and not path.is_absolute()
            assert ".." not in path.parts and "\\" not in row.filename and ":" not in row.filename
            assert not stat.S_ISLNK(row.external_attr >> 16)
            files[row.filename] = archive.read(row)
    def read(name):
        return json.loads(files[name].decode("utf-8-sig")) if name in files else None
    manifest = read("FILE_MANIFEST.json")
    if manifest is not None:
        assert len({row["path"] for row in manifest}) == len(manifest)
        assert {row["path"]: {key: row[key] for key in ("bytes", "sha256")} for row in manifest} == {
            name: digest(data) for name, data in files.items() if name != "FILE_MANIFEST.json"}
    anchor = read("JOB_ANCHOR.json")
    assert (anchor["run_id"], anchor["run_attempt"], anchor["harness_sha"], anchor["source_head"], anchor["source_tree"], anchor["job_timeout_minutes"]) == (str(RUN), "1", HARNESS, SOURCE, TREE, 65)
    job_start = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
    deadline = job_start + timedelta(minutes=65)
    first_step = datetime.fromisoformat(anchor["first_step_started_at"])
    assert job_start <= first_step
    result = read("RESULT.json") or {}
    if result:
        assert (result["run_id"], result["run_attempt"], result["harness_sha"], result["source_head"], result["source_tree"]) == (str(RUN), "1", HARNESS, SOURCE, TREE)
        assert result["native_test_commands"] == [] and result["native_tests_executed"] == 0
        assert result["direct_model_requests_issued_by_driver"] == 0
        assert result["physical_network_request_count"] is None
        if "planned_stages" in result:
            assert result["planned_stages"] == [{"id": prefix.split("-", 2)[2], "kind": kind, "command": command} for prefix, kind, command in STAGES]
        assert result.get("phases", []) == [prefix for prefix, _, _ in STAGES][:len(result.get("phases", []))]
    expected_locks = {name: {key: plan["files"][name][key] for key in ("bytes", "sha256")} for name in ("codex-rs/Cargo.lock", "MODULE.bazel.lock")}
    def source_ok(value):
        return isinstance(value, dict) and value.get("commit") == SOURCE and value.get("tree") == TREE and value.get("dirty") is False and value.get("locks") == expected_locks
    def snapshot(name):
        value = read(name + "/identity.json")
        if value is None:
            return None
        rows = read(name + "/postimages.json")
        assert isinstance(rows, list)
        for row in rows:
            if row["state"] == "file":
                assert digest(files[name + "/postimages/" + row["path"]]) == {key: row[key] for key in ("bytes", "sha256")}
        if source_ok(value):
            assert rows == []
            for suffix in ("git-status.raw", "untracked-including-ignored.raw", "working-tree.patch", "index.patch", "combined.patch", "qualified-source.patch"):
                assert files[name + "/" + suffix] == b""
        return value
    baseline = snapshot("source-before")
    tools = read("tools-before/tools.json")
    if tools:
        prefixes = {"rustc": "rustc 1.96.0 ", "cargo": "cargo 1.96.0 ", "clippy-driver": "clippy 0.1.96 ", "just": "just 1.51.0", "cargo-nextest": "cargo-nextest 0.9.103", "python": "Python 3.", "python3": "Python 3."}
        assert set(tools) == set(prefixes)
        for name, row in tools.items():
            assert row["version"].startswith(prefixes[name]) and row["bytes"] > 0
            assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
    if result.get("harness"):
        harness = result["harness"]
        assert harness["head"] == HARNESS and harness["tree"] == HARNESS_TREE
        for key, name in {"driver": "mem_windows_sandbox_fix.py", "support": "mem_windows_sandbox_fix_support.py", "workflow": "hepta-mem-windows-sandbox-fix.yml", "input": "mem-windows-sandbox-fix-plan.json"}.items():
            assert harness[key] == digest((root / "harness" / name).read_bytes())
    phases, helpers, passed = [], None, []
    for prefix, kind, command in STAGES:
        intent, phase = read(prefix + ".intent.json"), read(prefix + ".json")
        if phase is None:
            if intent:
                assert intent["command"] == command and intent["kind"] == kind
                assert intent["command_exit_code"] is None and intent["status"] == "running"
            phases.append({"id": prefix, "state": "INTENT_WITHOUT_TERMINAL_UNKNOWN" if intent else "NOT_STARTED_NO_PHASE_EVIDENCE", "raw": identity(files[prefix + ".raw.log"]) if prefix + ".raw.log" in files else None})
            continue
        assert intent is not None and phase["command"] == command and phase["kind"] == kind
        for key in ("kind", "command", "cwd", "started_at", "before", "helpers_before", "remaining_job_seconds_before"):
            assert intent[key] == phase[key]
        assert intent["command_exit_code"] is None and intent["status"] == "running"
        raw_phase = files[prefix + ".raw.log"]
        assert phase["raw_log"] == {"path": prefix + ".raw.log", **digest(raw_phase)}
        before = snapshot(prefix + "-source-before")
        after = snapshot(prefix + "-source-after")
        immediate = snapshot(prefix + "-observed-source")
        assert before == phase["before"]
        if after is not None:
            assert after == phase.get("after")
        if immediate is not None:
            assert immediate == phase.get("source_immediately_after_command")
        clean = source_ok(before) and source_ok(after) and before == after == baseline
        tools_equal = tools is not None and read(prefix + "-tools-before/tools.json") == read(prefix + "-tools-after/tools.json") == tools
        if kind == "helpers" and phase.get("helper_binding"):
            helpers = phase["helper_binding"]
            assert len(helpers) == 2 and {row["name"] for row in helpers} == {"codex-windows-sandbox-setup", "codex-command-runner"}
            compiler = []
            for line in raw_phase.decode("utf-8", errors="replace").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("reason") == "compiler-artifact":
                    compiler.append(value)
            for helper in helpers:
                matches = [value for value in compiler if value.get("target", {}).get("name") == helper["name"] and value.get("executable", "").replace("\\", "/").lower() == helper["source"].replace("\\", "/").lower()]
                assert matches and helper["bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", helper["sha256"])
                assert all(value["target"]["kind"] == ["bin"] and not value["profile"]["test"] and value["manifest_path"].replace("\\", "/").endswith("/source/codex-rs/windows-sandbox-rs/Cargo.toml") for value in matches)
        helper_equal = bool(helpers) and phase.get("helpers_after") == helpers and (kind == "helpers" or phase.get("helpers_before") == helpers)
        phase_pass = phase["status"] == "passed_clean" and phase["command_exit_code"] == 0 and clean and tools_equal and helper_equal and immediate == baseline and source_ok(immediate)
        if phase["status"] == "passed_clean":
            assert phase_pass and phase["post_command_integrity"] is True and phase["timeout_observed"] is False
            assert all(0 < phase[key] <= 3900 for key in ("remaining_job_seconds_before", "remaining_job_seconds_after"))
            assert first_step <= datetime.fromisoformat(phase["started_at"]) <= datetime.fromisoformat(phase["finished_at"]) < deadline
            passed.append(prefix)
        phases.append({"id": prefix, "kind": kind, "command": command, "state": phase["status"], "command_exit_code": phase["command_exit_code"], "source_before_after_clean": clean, "tools_unchanged": tools_equal, "helpers_unchanged": helper_equal, "raw": identity(raw_phase), "started_at": phase["started_at"], "finished_at": phase["finished_at"], "elapsed_seconds": phase["elapsed_seconds"], "error": phase.get("error"), "integrity_error": phase.get("integrity_error")})
    final = snapshot("source-after")
    collection_snapshot = snapshot("source-at-collection")
    collection = read("COLLECTION.json") or {}
    claimed_success = result.get("status") == "passed_one_clean_windows_sandbox_fix"
    if claimed_success:
        assert result.get("harness") and set(result["harness"]) == {"head", "tree", "driver", "support", "workflow", "input"}
        assert passed == [row[0] for row in STAGES]
        assert result["after"] == final == collection_snapshot == baseline and source_ok(final)
        assert collection["source"] == final and collection["status"] == "qualified_results_retained"
        assert result["helpers_after"] == helpers and result["clean_scoped_fixes"] == ["fix-codex-windows-sandbox"]
        assert manifest is not None and job["conclusion"] == "success"
    return {"schema": "mem8.windows-sandbox-fix-d0f.original-evidence-audit.v1", "run_id": RUN, "job_id": JOB, "attempt": 1, "source_head": SOURCE, "source_tree": TREE, "harness_head": HARNESS, "harness_tree": HARNESS_TREE,
            "job_conclusion": job["conclusion"], "job_started_at": job["started_at"], "job_completed_at": job["completed_at"], "observed_job_start_plus_65_min": deadline.isoformat(),
            "artifact": {"id": meta["id"], **identity(zip_data)}, "archive_members": len(files), "manifest_complete": manifest is not None, "full_job_raw": identity(raw),
            "driver_status": result.get("status", "MISSING_UNKNOWN"), "collection_status": collection.get("status", "MISSING_UNKNOWN"), "qualification_passed": claimed_success,
            "phases": phases, "native_test_commands": 0, "model_commands": 0, "physical_network_requests": None,
            "helpers_boundary": "Original compiler-artifact outputs and driver-observed byte hashes are bound; helper PE binaries are not included in this artifact.",
            "source_rewrite_paths": sorted({row["path"] for name in files if name.endswith("/postimages.json") for row in read(name) or []}),
            "cause_of_cancellation": "UNKNOWN" if job["conclusion"] == "cancelled" else None,
            "archived_commands_executed_by_auditor": 0, "historical_passes_transferred": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.root), indent=2, sort_keys=True))
