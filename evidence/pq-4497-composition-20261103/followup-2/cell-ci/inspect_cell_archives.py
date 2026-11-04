import hashlib
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).parent
SOURCE = "2d7506108fd1b7813d5afbe2bbb0aaf5d9460c6d"
MERGE = "21ceefde202d58ef60e937d637f725727a9fe086"
BASE = "3a81000aae08c658276958d678874aca4db5eedd"
TREE = "80562dbe724b082f388828b32fb305d036e8dff7"
MINIMUMS = {
    "host-material.json": 23,
    "cli-process.json": 3,
    "arg0-owner.json": 1,
    "original-owner.json": 40,
    "canonical-pq-contracts.json": 195,
    "pq-initial-material.json": 1,
    "pq-initial-clock.json": 1,
    "initial-startup-budget.json": 1,
    "pq-native-turn-start.json": 1,
}
EXACT = {
    "pq-initial-material.json": "selection::initial_smollm_genesis::tests::pq_initial_tests::pq_initial_material_keeps_selector_current_and_final_use_profile_bound",
    "pq-initial-clock.json": "smollm_cognitive_host::initial::time::tests::initial_consumers_retain_the_real_pq_clock_and_refuse_wall_time_after_failure",
    "initial-startup-budget.json": "smollm_neural_read::tests::expired_startup_is_not_restarted_and_cannot_admit_claim_or_spawn",
    "pq-native-turn-start.json": "native_app_server::tests::pq_final_use::real_agentd_turn_start_consumes_explicit_pq_config_and_external_mldsa_grant",
}
UNIX_CASES = [
    "authority_trust_unix::tests::actual_clock_rejects_rollback_cross_request_signature_domain_and_expiry",
    "authority_trust_unix::tests::actual_external_cas_is_exact_durable_and_never_replaced_by_local_state",
    "authority_trust_unix::learning_tests::external_learning_floor_is_typed_exact_and_retains_rotation_after_client_restart",
]
BUILD_COMMAND = [
    "cargo", "build", "--manifest-path", "codex-rs/Cargo.toml", "-p",
    "codex-cli", "--bin", "codex", "--locked", "--message-format=json",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(directory):
    out = directory / "extracted"
    metadata = json.loads((directory / "artifact-metadata.json").read_text())
    assert metadata["digest"] == "sha256:" + sha(directory / "artifact.zip")
    assert metadata["size_in_bytes"] == (directory / "artifact.zip").stat().st_size
    assert metadata["workflow_run"]["id"] == 41609576379
    assert metadata["workflow_run"]["head_sha"] == SOURCE
    candidate = json.loads((out / "candidate-tuple.json").read_text())
    assert candidate["base_sha"] == BASE and candidate["source_sha"] == SOURCE
    assert candidate["source_tree"] == candidate["tested_tree"] == TREE
    tested = SOURCE if candidate["lane"] == "source-head" else MERGE
    assert candidate["tested_sha"] == tested
    commands = {}
    raw_records = {}
    raw_logs = {}
    for path in sorted(out.glob("*.json")):
        r = json.loads(path.read_text())
        if "command" not in r:
            continue
        assert r["source_sha"] == SOURCE and r["tested_sha"] == tested
        assert r["base_sha"] == BASE and r["lane"] == candidate["lane"]
        assert r["run_id"] == "41609576379" and r["run_attempt"] == "1"
        assert r["job"] == "cell-host-v2"
        assert r["before"] == r["after"]
        assert r["before"]["commit"] == tested
        assert r["before"]["tree"] == TREE and r["before"]["dirty"] is False
        assert r["before"]["parents"] == (["0baf43cf4bf8f953fff079725348de1d8f26434f"] if tested == SOURCE else [BASE, SOURCE])
        if tested == MERGE:
            assert r["recomputed_merge_tree"] == TREE
        assert Path(r["log_file"]).name == r["log_file"]
        log = out / r["log_file"]
        assert log.stat().st_size == r["log_bytes"] and sha(log) == r["log_sha256"]
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log.read_text())
        summaries = [line.strip() for line in text.splitlines() if re.search(r"^\s*Summary \[", line)]
        retry_lines = [line.strip() for line in text.splitlines() if re.search(r"^\s*(?:TRY\s+\d+\s+(?:FAIL|PASS)|RETRY)", line)]
        pass_lines = [line.strip() for line in text.splitlines() if re.search(r"^\s*PASS \[", line)]
        if path.name in MINIMUMS:
            assert r["minimum_tests"] == MINIMUMS[path.name]
            assert len(summaries) == 1
            match = re.search(r"(\d+) tests? run: (\d+) passed", summaries[0])
            assert match and int(match[2]) == r["observed_passed_tests"]
            failures = re.search(r"(\d+) failed", summaries[0])
            assert (int(failures[1]) if failures else 0) == r["observed_failed_tests"]
        exact_pass = None
        if path.name in EXACT:
            selector = EXACT[path.name]
            assert "test(=" + selector + ")" in r["command"]
            exact_pass = [line for line in pass_lines if line.endswith(" " + selector)]
            assert len(exact_pass) == 1
        commands[path.name] = {
            key: r[key]
            for key in ("command", "status", "command_exit_code", "exit_code", "minimum_tests", "observed_passed_tests", "observed_failed_tests", "timed_out", "output_limit_exceeded", "elapsed_seconds", "log_file", "log_bytes", "log_sha256")
        }
        commands[path.name].update({"nextest_summaries": summaries, "retry_lines": retry_lines, "exact_pass": exact_pass})
        raw_records[path.name] = r
        raw_logs[path.name] = text
    missing = sorted(set(MINIMUMS) - set(commands))
    assert not missing, missing
    unix_pass = []
    for case in UNIX_CASES:
        lines = [line.strip() for line in raw_logs["canonical-pq-contracts.json"].splitlines() if re.search(r"^\s*PASS \[", line) and line.endswith(" " + case)]
        assert len(lines) == 1
        unix_pass.extend(lines)
    binding = json.loads((out / "pq-codex-binding.json").read_text())
    build = raw_records["pq-build-codex.json"]
    native = raw_records["pq-native-turn-start.json"]
    assert build["command"] == BUILD_COMMAND
    assert binding["build_record_sha256"] == sha(out / "pq-build-codex.json")
    assert binding["build_log_sha256"] == build["log_sha256"]
    assert binding["source"] == build["before"] == native["before"]
    assert binding["workflow_event_commit"] == MERGE
    assert re.fullmatch(r"[0-9a-f]{64}", binding["sha256"])
    rows = [json.loads(line) for line in raw_logs["pq-build-codex.json"].splitlines() if line.startswith("{")]
    assert [row["success"] for row in rows if row.get("reason") == "build-finished"] == [True]
    selected = [row for row in rows if row.get("reason") == "compiler-artifact" and row.get("target", {}).get("name") == "codex"]
    assert len(selected) == 1
    selected = selected[0]
    work = PurePosixPath(build["working_directory"])
    assert selected["package_id"].startswith("path+" + (work / "codex-rs/cli").as_uri() + "#codex-cli@")
    assert selected["manifest_path"] == str(work / "codex-rs/cli/Cargo.toml")
    assert selected["target"]["src_path"] == str(work / "codex-rs/cli/src/main.rs")
    assert selected["target"]["kind"] == ["bin"] and selected["fresh"] is False
    assert selected["executable"] == binding["executable"]
    assert selected["filenames"] == [binding["executable"]]
    executable = PurePosixPath(binding["executable"])
    assert executable.is_absolute() and not executable.is_relative_to(work)
    assert re.fullmatch(r"/home/runner/work/_temp/hepta-cell-host-target\.[A-Za-z0-9]+/debug/codex", str(executable))
    result = {
        "job_id": int(directory.name.removeprefix("cell-")),
        "artifact_id": metadata["id"],
        "artifact_name": metadata["name"],
        "archive_bytes": metadata["size_in_bytes"],
        "archive_sha256": sha(directory / "artifact.zip"),
        "run_id": 41609576379,
        "run_attempt": 1,
        "candidate": candidate,
        "all_command_logs_sha256_and_length_verified": True,
        "all_sources_unchanged_clean_and_bound": True,
        "all_commands_passed": all(r["status"] == "passed" and r["exit_code"] == r["command_exit_code"] == 0 and not r["timed_out"] and not r["output_limit_exceeded"] for r in raw_records.values()),
        "actual_unix_trust_tests": unix_pass,
        "commands": commands,
        "native_binding": binding,
        "fresh_codex_cargo_artifact": selected,
        "binding_verification_limit": "The unchanged workflow enforces executable ELF, source/package/path and before/after binary hash on the runner. This independent archive inspection verifies the recorded binding against the exact Cargo build and test receipts/logs. The Codex executable itself is not included in this observation ZIP and was not independently downloaded or rehashed here.",
        "clippy_scope": "The CI command is the original just fix with unchanged-source enforcement. It is not reported as the separate local no-fix strict Clippy result.",
    }
    (directory / "inspection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    for directory in sorted(ROOT.glob("cell-*")):
        if directory.is_dir() and (directory / "artifact-metadata.json").is_file():
            result = inspect(directory)
            print(json.dumps({"job_id": result["job_id"], "artifact_id": result["artifact_id"], "all_commands_passed": result["all_commands_passed"], "counts": {name: result["commands"][name]["observed_passed_tests"] for name in MINIMUMS}}, ensure_ascii=False))
