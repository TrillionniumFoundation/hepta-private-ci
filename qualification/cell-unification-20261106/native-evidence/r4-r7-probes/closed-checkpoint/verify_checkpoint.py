"""Read-only verification of the closed r4/r5/r6/r6b/green-r7 checkpoint."""

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
STEMS = [
    "native-inherited-agentd-r4-strict-diagnostic",
    "native-inherited-r5-strict",
    "native-supervisor-red-r6",
    "native-supervisor-red-r6b",
    "native-supervisor-green-r7",
]
EXPECTED_NAMES = {
    "matrix_exhausted_budget_survives_repeated_supervisor_recovery",
    "matrix_orphan_fault_uses_lease_release_budget_before_writing",
    "matrix_budget_identity_is_checked_even_when_agent_recovery_faults",
    "unresolved_agent_release_cannot_reset_another_release_matrix_budget",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def number(text, label):
    match = re.search(r"^\s*" + re.escape(label) + r":\s*([0-9.]+)\s*$", text, re.M)
    assert match, label
    return float(match[1])


def seconds(value):
    result = 0.0
    for part in value.split(":"):
        result = result * 60 + float(part)
    return result


manifest = read_json(ROOT / "export-manifest.json")
assert len(manifest["files"]) == 25
assert manifest["active_gate_files_read"] is False
verified_files = []
for entry in manifest["files"]:
    path = ROOT / entry["path"]
    data = path.read_bytes()
    assert len(data) == entry["bytes"], entry["path"]
    assert sha256(data) == entry["sha256"], entry["path"]
    if path.suffix == ".json":
        json.loads(data)
    verified_files.append({key: entry[key] for key in ("path", "bytes", "sha256")})

archive = ROOT / "checkpoint-through-r7-probe.tar.gz"
assert archive.stat().st_size == 26322
assert sha256(archive.read_bytes()) == "70c7226d65e29aa234d58458fcff6e5a2b87aab325b24a8bee2f79ab6c24212b"

stages = []
logs = {}
sources = {}
for stem in STEMS:
    receipt = read_json(EVIDENCE / (stem + "-receipt.json"))
    source = read_json(EVIDENCE / receipt["source_manifest"])
    raw_log = (EVIDENCE / (stem + ".log")).read_bytes()
    log = ANSI.sub("", raw_log.decode())
    resources = (EVIDENCE / (stem + "-resources.txt")).read_text()
    assert sha256(raw_log) == receipt["log_sha256"]
    assert receipt["staged_tree"] == source["staged_tree"]
    assert source["parent_head"] == "bef6fa7645df9df12b69fda499e97eed25de6c75"
    assert int(number(resources, "Exit status")) == receipt["exit_code"]
    wall = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)", resources)
    assert wall
    assert abs(seconds(wall[1]) - receipt["elapsed_seconds"]) < 0.1
    assert abs(receipt["end_unix"] - receipt["start_unix"] - receipt["elapsed_seconds"]) < 1e-6
    summary = re.findall(
        r"Summary\s+\[\s*([\d.]+)s\]\s+(\d+) tests run: (\d+) passed(?:, (\d+) failed)?, (\d+) skipped",
        log,
    )
    names_by_result = {}
    for outcome in ("PASS", "FAIL"):
        names_by_result[outcome] = sorted(set(re.findall(
            r"^\s*" + outcome + r"\s+\[[^\]]+\]\s+codex-hepta-supervisor\s+supervisor::tests::restart_recovery::(\w+)\s*$",
            log,
            re.M,
        )))
    diagnostics = [line for line in log.splitlines()
                   if line.startswith("error")
                   and "could not compile" not in line
                   and "recipe `" not in line
                   and not line.startswith("error: command ")]
    stage = {
        "stage": stem,
        "command": receipt["command"],
        "kind": receipt["kind"],
        "source_tree": receipt["staged_tree"],
        "source_manifest": "evidence/" + receipt["source_manifest"],
        "receipt": "evidence/" + stem + "-receipt.json",
        "log": "evidence/" + stem + ".log",
        "log_sha256": receipt["log_sha256"],
        "resource_record": "evidence/" + stem + "-resources.txt",
        "exit_code": receipt["exit_code"],
        "elapsed_seconds_including_compile": receipt["elapsed_seconds"],
        "resource_user_seconds": number(resources, "User time (seconds)"),
        "resource_system_seconds": number(resources, "System time (seconds)"),
        "resource_peak_rss_kbytes": int(number(resources, "Maximum resident set size (kbytes)")),
        "diagnostics": diagnostics,
        "unique_test_names": names_by_result,
        "test_summary": None,
        "receipt_log_resource_source_binding_verified": True,
    }
    if summary:
        assert len(summary) == 1
        duration, total, passed, failed, skipped = summary[0]
        stage["test_summary"] = {
            "test_phase_seconds": float(duration), "run": int(total),
            "passed": int(passed), "failed": int(failed or 0), "skipped": int(skipped),
        }
    logs[stem] = log
    sources[stem] = source
    stages.append(stage)

assert [stage["exit_code"] for stage in stages] == [101, 101, 101, 100, 0]
assert all(stage["test_summary"] is None for stage in stages[:3])
compile_receipt = read_json(EVIDENCE / (STEMS[2] + "-receipt.json"))
assert compile_receipt["expected_behavior_failures_confirmed"] is False
assert compile_receipt["observed_failed_tests"] == []
assert logs[STEMS[2]].count("error[E0659]: `assert_eq` is ambiguous") == 42
assert set(stages[3]["unique_test_names"]["FAIL"]) == EXPECTED_NAMES
assert not stages[3]["unique_test_names"]["PASS"]
assert set(stages[4]["unique_test_names"]["PASS"]) == EXPECTED_NAMES
assert not stages[4]["unique_test_names"]["FAIL"]
assert stages[3]["test_summary"] == {"test_phase_seconds": 0.049, "run": 4, "passed": 0, "failed": 4, "skipped": 120}
assert stages[4]["test_summary"] == {"test_phase_seconds": 0.063, "run": 4, "passed": 4, "failed": 0, "skipped": 120}
assert stages[2]["command"] == stages[3]["command"] == stages[4]["command"]
assert stages[3]["command"][-2:] == ["-E", "test(supervisor::tests::restart_recovery::)"]
assert "Starting 4 tests across 10 binaries (120 tests skipped)" in logs[STEMS[3]]
assert "Starting 4 tests across 10 binaries (120 tests skipped)" in logs[STEMS[4]]

counterexamples = []
red_log = logs[STEMS[3]]
for name, actual, expected, line in [
    ("matrix_exhausted_budget_survives_repeated_supervisor_recovery", 0, 3, 50),
    ("matrix_orphan_fault_uses_lease_release_budget_before_writing", 1, 2, 118),
    ("unresolved_agent_release_cannot_reset_another_release_matrix_budget", 0, 2, 218),
]:
    match = re.search(r"thread 'supervisor::tests::restart_recovery::" + name
                      + r"'[^\n]*panicked at [^\n]*:" + str(line) + r":\d+:\n(.*?)(?=note:)", red_log, re.S)
    assert match
    assert re.search(r"^\s*<" + str(actual) + r"\s*$", match[1], re.M)
    assert re.search(r"^\s*>" + str(expected) + r"\s*$", match[1], re.M)
    counterexamples.append({"test": name, "assertion_line": line, "actual": actual, "expected": expected})
identity_name = "matrix_budget_identity_is_checked_even_when_agent_recovery_faults"
identity = re.search(r"thread 'supervisor::tests::restart_recovery::" + identity_name
                     + r"'[^\n]*:161:5:\n(.*?)(?=note:)", red_log, re.S)
assert identity and "Err(SupervisorError::CorruptLease(message))" in identity[1]
assert 'message.contains("restart budget journal belongs to")' in identity[1]
counterexamples.append({"test": identity_name, "assertion_line": 161,
                        "failed_requirement": "CorruptLease with restart budget journal ownership error"})

red = sources[STEMS[3]]
green = sources[STEMS[4]]
red_files = {entry["path"]: entry for entry in red["changed_files"]}
green_files = {entry["path"]: entry for entry in green["changed_files"]}
test_paths = ["codex-rs/hepta-supervisor/src/supervisor_tests.rs",
              "codex-rs/hepta-supervisor/src/supervisor_restart_recovery_tests.rs"]
for path in test_paths:
    assert red_files[path]["sha256"] == green_files[path]["sha256"]
    assert red_files[path]["git_blob"] == green_files[path]["git_blob"]
assert red_files[test_paths[1]]["sha256"] == "41dd08230db0fb5168f0eba1ef87cac0e9cf912927392a8b7da70f21b326814e"
tree_delta = sorted(path for path in set(red_files) | set(green_files)
                    if red_files.get(path, {}).get("sha256") != green_files.get(path, {}).get("sha256"))

supplement_path = EVIDENCE / "native-supervisor-red-production-tree-binding.json"
assert sha256(supplement_path.read_bytes()) == "b28129b3f7ade57d4df8071e5cf4f306ad42452d65a17c30a82c359bb6f59c43"
supplement = read_json(supplement_path)
assert {item["tree"] for item in supplement["trees"]} == {stages[2]["source_tree"], stages[3]["source_tree"]}
declared_original = {entry["path"]: entry for entry in red["production_before"]}
assert len(declared_original) == 4
for tree in supplement["trees"]:
    assert len(tree["files"]) == 4
    for entry in tree["files"]:
        original = declared_original[entry["path"]]
        assert entry["sha256"] == original["original_sha256"]
        assert entry["git_blob"] == original["original_git_blob"] == entry["base_git_blob"]
        assert entry["byte_identical_to_bef"] is True
        assert entry["path"] not in red_files
        assert green_files[entry["path"]]["sha256"] == original["sha256"]

for version, stage_index in [("r4", 0), ("r5", 1), ("r7", 4)]:
    equivalence = read_json(EVIDENCE / ("native-" + version + "-retained-source-equivalence.json"))
    assert equivalence["current_tree"] == stages[stage_index]["source_tree"]
    assert equivalence["scoped_source_byte_identical"] is True
    assert all(not value for value in equivalence["conservative_all_features_targets_workspace_dependencies_to_changed_packages"].values())

result = {
    "schema": "hepta.closed-native-checkpoint-independent-verification.v1",
    "reviewer": "/root/differentiation_study",
    "outcome": "VERIFIED_CLOSED_EVIDENCE_ONLY",
    "original_export_files_verified": verified_files,
    "original_export_json_files_parsed": sum(entry["path"].endswith(".json") for entry in verified_files),
    "archive_sha256": sha256(archive.read_bytes()),
    "archive_bytes": archive.stat().st_size,
    "additional_source_binding": {"path": str(supplement_path.relative_to(ROOT)), "sha256": sha256(supplement_path.read_bytes()), "bytes": supplement_path.stat().st_size},
    "stages": stages,
    "behavior_counterexamples": counterexamples,
    "red_green_test_sources_identical": [{"path": path, "sha256": red_files[path]["sha256"], "git_blob": red_files[path]["git_blob"]} for path in test_paths],
    "red_production_exactly_base_in_both_red_trees": True,
    "red_green_whole_tree_changed_paths": tree_delta,
    "source_identity_field_caveat": "Original r6/r6b production_before.sha256/bytes describe the proposed candidate B; original_sha256/original_git_blob are the actual old production identity. The supplemental git-show receipt independently binds both red trees to the latter. Original evidence is retained unchanged.",
    "coverage_limits": [
        "r4/r5 are failed strict compilation stages, not test runs.",
        "r6 is an assert_eq macro ambiguity compile failure (42 diagnostics), not a behavioral counterexample.",
        "r6b and green-r7 deliberately select the same four new regression tests; 120 skipped is the focused nextest selection count, not 120 disabled tests or the full-suite ignored count.",
        "The same four test cases appear in both focused stages; their counts must not be added as eight unique tests.",
        "The red-to-green whole-tree delta also contains three core client files; the exact seven changed paths are listed rather than claiming only four files changed in the entire tree.",
        "Earlier retained package receipts remain stage-bound. The dependency-equivalence statements do not claim execution of all features or platforms.",
        "No active r7 strict/r8/later gate files were read by this export or verifier. No complete Supervisor, Agentd, core or full-workspace result is established here.",
        "This readback does not run Rust, alter source, replace original logs, or establish final fmt/publication status.",
    ],
}
print(json.dumps(result, indent=2))
