from pathlib import Path
import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "terminal/probe-127545539398"


def identity(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def record(path):
    return {"local_path": str(path), **identity(path.read_bytes())}


def write(name, value):
    path = DIRECTORY / name
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    return record(path)


envelope = json.loads((DIRECTORY / "terminal-api-envelopes.json").read_text())
run = json.loads(envelope["run"]["structuredContent"]["content"])
jobs = json.loads(envelope["jobs"]["structuredContent"]["content"])
job, = [row for row in jobs["jobs"] if row["id"] == 127545539398]
artifact, = json.loads(envelope["artifacts"]["structuredContent"]["content"])["artifacts"]
assert run["id"] == 42113095723 and run["run_attempt"] == 1
assert run["head_sha"] == "2338281bac08ff68b85dc2146c04a35598e6cbb4"
assert run["conclusion"] == job["conclusion"] == "failure"
assert (DIRECTORY / "job.log").read_bytes() == envelope["log"]["structuredContent"]["content"].encode()
source = DIRECTORY / "members/b11-token-mechanism-probe"
checkout, tree = (source / "source-head-tree.txt").read_text().splitlines()
assert (checkout, tree) == ("8fd0c14cd5853d21eb23571f67461f3fc386c01c", "cb105f2d902326c3c2e187f49c76d5598e6646c3")
assert all((source / f"source-status-{side}.txt").read_bytes() == b"" for side in ("before", "after"))
assert int((source / "original-bazel-exit-code.txt").read_text()) == 3
assert int((source / "console-copy-exit-code.txt").read_text()) == 0
steps = {step["name"]: step for step in job["steps"]}
assert steps["Check for a clean worktree"]["conclusion"] == "success"
assert steps["Run the original setup helper target after exact restoration"]["conclusion"] == "skipped"
leaves = {line.split("\t", 1)[1]: line.split("\t", 1)[0] for line in (source / "source-leaves.txt").read_text().splitlines()}
assert len(leaves) == 78
prior_source = ROOT / "terminal/probe-127429723742/members/b11-token-mechanism-probe"
prior_leaves = {line.split("\t", 1)[1]: line.split("\t", 1)[0] for line in (prior_source / "source-leaves.txt").read_text().splitlines()}
changed = [{"path": path, "before": prior_leaves.get(path), "after": leaves.get(path)}
           for path in sorted(set(leaves) | set(prior_leaves)) if leaves.get(path) != prior_leaves.get(path)]
assert {row["path"] for row in changed} == {
    ".github/workflows/hepta-windows-token-mechanism-probe.yml",
    "codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs",
    "codex-rs/windows-sandbox-rs/src/bin/setup_main/win/read_acl_mutex.rs",
    "codex-rs/windows-sandbox-rs/src/bin/setup_main/win/read_acl_mutex_tests.rs",
}

test_path, = (DIRECTORY / "members/bazel-execution-logs/failed-test-logs").glob("*/targets/0000/test.log")
text = test_path.read_text()
clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
summaries = re.findall(r"^test result: .+$", text, re.M)
assert summaries == ["test result: ok. 92 passed; 0 failed; 0 ignored; 0 measured; 64 filtered out; finished in 1.04s",
                     "test result: FAILED. 55 passed; 7 failed; 2 ignored; 0 measured; 92 filtered out; finished in 0.24s"]
matches = list(re.finditer(r"^---- (\S+) stdout ----$", text, re.M))
prior = json.loads((ROOT / "terminal/probe-127429723742/failure-classification.json").read_text())
prior_classes = {row["case"]: row["classification"] for row in prior["failures"]}
assert {match[1] for match in matches} == set(prior_classes) and len(matches) == 7
failures = []
for index, match in enumerate(matches):
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    block = text[match.start():end].split("\nfailures:\n")[0]
    failures.append({"case": match[1], "line": text.count("\n", 0, match.start()) + 1,
                     "classification": prior_classes[match[1]], "original_block": block})
failure_record = write("failure-classification.json", {"source": record(test_path), "count": 7, "failures": failures,
    "same_failed_names_as_native7": True, "new_product_failure_names": [],
    "scope": "The original full-target result remains 147/7/2. The later bare-bash launcher error ran no exact test."})
xml = ET.parse(test_path.with_suffix(".xml")).getroot()
outer_cases = xml.findall(".//testcase")
assert len(outer_cases) == 1 and len(outer_cases[0].findall("error")) == 1
xml_record = {"root": xml.tag, "case": outer_cases[0].attrib,
              "errors": [error.attrib for error in outer_cases[0].findall("error")],
              "scope": "Original outer bat target XML; not individual libtest qualification."}

control = source / "acl-identity-counterfactual"
terminal_path = control / "counterfactual-terminal.json"
entry_path = control / "source-entry.json"
terminal = json.loads(terminal_path.read_text())
entry = json.loads(entry_path.read_text())
assert {path.name for path in control.iterdir()} == {terminal_path.name, entry_path.name, "positive-01"}
assert terminal["status"] == "INVALID_OR_NOT_RUN" and terminal["positive_scopes"] == []
assert all(terminal[key] is False for key in ("physical_counterfactual_qualified", "physical_oracle_reached",
    "restored_exact_original_bytes", "source_mutated", "source_mutation_attempted"))
assert terminal["restore_error"] is None and terminal["original_target_exit_code_unchanged"] is True
required = ["acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object",
            "acl::tests::existing_native_deny_does_not_require_write_dac",
            "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write",
            "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes"]
assert not set(required) & set(prior_classes)
assert terminal["error"] == f"RuntimeError('exact positive failed: {required[0]}')"
assert entry["head"] == checkout and entry["head_tree"] == tree and entry["status"] == []
assert entry["source_canonical_git_blob"] == "da5346c220c41cf0c83f62b596132c74c02284d8"
scope = control / "positive-01"
assert {path.name for path in scope.iterdir()} == {"command.json", "command-terminal.json", "console.log", "source-before.json", "source-after.json"}
assert entry_path.read_bytes() == (scope / "source-before.json").read_bytes() == (scope / "source-after.json").read_bytes()
command = json.loads((scope / "command.json").read_text())
command_terminal = json.loads((scope / "command-terminal.json").read_text())
assert command["argv"][0] == "bash" and command["case"] == required[0]
assert command_terminal["exit_code"] == 1
console = (scope / "console.log").read_bytes()
decoded_console = console.decode("utf-16-le")
assert len(console) == 504 and decoded_console.startswith("Windows Subsystem for Linux has no installed distributions.")
invalid = write("counterfactual-precondition-review.json", {
    "role": "ACTUAL_LAUNCHER_PRECONDITION_FAILURE_BEFORE_BAZEL_EXACT_TESTS_NOT_RUN",
    "terminal": record(terminal_path), "source_entry": record(entry_path), "full_source_test_log": record(test_path),
    "first_exact_command": {"record": record(scope / "command.json"), "value": command},
    "first_exact_command_terminal": {"record": record(scope / "command-terminal.json"), "value": command_terminal},
    "first_exact_console": {"record": record(scope / "console.log"), "encoding": "UTF-16LE", "decoded_text": decoded_console},
    "entry_before_after_raw_bytes_equal": True, "positive_test_cases_executed": 0,
    "positive_Bazel_invocations_reached": 0, "remaining_exact_commands": 0,
    "negative_source_installation_attempted": False, "negative_commands": 0, "helper_command_executed": False,
    "physical_negative_qualification": False, "restore_error": None,
    "restore_flag_interpretation": "false because source was never mutated; this is not a failed restore",
    "original_whole_result_retained": True, "no_product_retry": True,
    "limits": ["The observed WSL diagnostic proves bare-bash launcher selection failed before Bazel; its exact resolved executable path was not recorded.",
               "No exact libtest/XML or negative result exists. Original whole failure is not erased."]})

observations = {}
for kind in ("row", "restoration", "finalized"):
    good, bad = [], []
    prefix = "PROBE_OBSERVATION_ONLY " + kind + " "
    for number, line in enumerate(text.splitlines(), 1):
        if prefix not in line:
            continue
        try:
            good.append({"line": number, "value": json.loads(line.split(prefix, 1)[1])})
        except json.JSONDecodeError as error:
            bad.append({"line": number, "raw": line, "error": str(error)})
    observations[kind] = {"complete_json": good, "interleaved_not_repaired": bad}
complete = [line for line in text.splitlines() if line == "PROBE_OBSERVATION_ONLY complete rows=8 token_subjects=4 descendants_spawned=0 tests_do_not_qualify_isolation=true"]
assert len(complete) == 1
projection = write("physical-observation-projection.json", {"source": record(test_path),
    "role": "PROBE_OBSERVATION_ONLY_NOT_PRODUCTION_ACCEPTANCE", "complete_marker": complete,
    "parsed": observations, "limits": "Only complete JSON is parsed; interleaved or broken lines remain unrepaired original text.",
    "qualifies_B11": False})

archive_path = DIRECTORY / "artifact.zip"
archive = archive_path.read_bytes()
assert artifact["id"] == 13454109636
assert artifact["digest"] == "sha256:" + hashlib.sha256(archive).hexdigest()
assert hashlib.sha256(archive).hexdigest() == "8b84e8347cc024119d22200862369ae73dc80023607d6d69afcea6862eb2cef7"
verification = json.loads((DIRECTORY / "artifact-verification.json").read_text())
assert len(verification["members"]) == 21
with zipfile.ZipFile(archive_path) as zipped:
    assert zipped.testzip() is None and len(zipped.infolist()) == 21
    assert len({info.filename for info in zipped.infolist()}) == 21
    for row in verification["members"]:
        body = zipped.read(row["path"])
        assert identity(body) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        assert body == (DIRECTORY / "members" / row["path"]).read_bytes()
        assert f"{zipped.getinfo(row['path']).CRC:08x}" == row["crc32"]
part_directory = DIRECTORY / "archive-parts"
part_directory.mkdir(exist_ok=False)
parts = []
for number, offset in enumerate(range(0, len(archive), 131072)):
    raw = archive[offset:offset + 131072]
    path = part_directory / f"artifact-13454109636-{number:03}.base64"
    path.write_bytes(base64.b64encode(raw) + b"\n")
    parts.append({"sequence": number, "offset": offset, "raw": identity(raw), "encoded": record(path)})
assert b"".join(base64.b64decode(Path(part["encoded"]["local_path"]).read_bytes().strip(), validate=True) for part in parts) == archive
parts_record = write("archive-parts-manifest.json", {"schema": "original-github-artifact-chunks-v1",
    "run_id": run["id"], "job_id": job["id"], "artifact_id": artifact["id"], "official_digest": artifact["digest"],
    "original_archive": record(archive_path), "roundtrip_original_bytes_verified": True,
    "member_crc_and_hash_verification": record(DIRECTORY / "artifact-verification.json"), "parts": parts,
    "git_upload_qualification": "Computed identities until separate actual create+GET map is written."})
review = write("terminal-review.json", {"schema": "b11-diagnostic-pr-native8-terminal-review-v1",
    "role": "ORIGINAL_WHOLE_RESULT_PLUS_LAUNCHER_PRECONDITION_FAILURE_NOT_B11_CLOSURE",
    "head": run["head_sha"], "head_tree": "515be77c425a74381a0aa45d06dcb497fd37ec16",
    "run_id": run["id"], "job_id": job["id"], "run_attempt": 1, "conclusion": job["conclusion"],
    "started_at": job["started_at"], "completed_at": job["completed_at"], "steps": job["steps"],
    "actual_checkout_commit": checkout, "actual_checkout_tree": tree, "source_leaves": leaves,
    "captured_leaf_changes_from_native7": changed, "captured_source_leaf_count": 78,
    "original_clean_source_before_after": True, "original_bazel_exit": 3, "console_copy_exit": 0,
    "final_clean_worktree_step_success": True, "target": "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests",
    "summaries": summaries, "outer_target_xml": xml_record,
    "combined_disjoint_counts": {"total_named_tests": 156, "passed": 147, "failed": 7, "ignored": 2},
    "count_limit": "Two disjoint libtest groups in one original target attempt, not retries. Job wrapper-tail repeats are not extra executions.",
    "failure_classification": failure_record, "physical_observations": projection,
    "counterfactual_precondition": invalid, "counterfactual_status": "INVALID_OR_NOT_RUN",
    "exact_test_cases_executed": 0, "negative_executed": False, "source_mutation_attempted": False,
    "helper_executed": False, "B11_status": "OPEN",
    "evidence": {"job_log": record(DIRECTORY / "job.log"), "full_test_log": record(test_path),
                 "target_level_xml": record(test_path.with_suffix(".xml")), "API": record(DIRECTORY / "terminal-api-envelopes.json"),
                 "archive_verification": record(DIRECTORY / "artifact-verification.json"), "archive_parts_manifest": parts_record},
    "native_or_ref_mutation_by_auditor": False})
print(json.dumps({"review": review, "invalid": invalid,
    "projection_counts": {key: {name: len(value) for name, value in row.items()} for key, row in observations.items()},
    "archive_parts": len(parts)}, indent=2))
