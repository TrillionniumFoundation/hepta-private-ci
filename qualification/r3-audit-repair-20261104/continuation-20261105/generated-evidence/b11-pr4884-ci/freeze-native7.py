from pathlib import Path
import base64
import hashlib
import json
import re


ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "terminal/probe-127429723742"


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
job, = [row for row in jobs["jobs"] if row["id"] == 127429723742]
assert run["head_sha"] == "0f6148ea3fbe9d1263354791d5cc63c7e66d4628" and run["run_attempt"] == 1
assert job["conclusion"] == "failure"
assert (DIRECTORY / "job.log").read_bytes() == envelope["log"]["structuredContent"]["content"].encode()
source = DIRECTORY / "members/b11-token-mechanism-probe"
checkout, tree = (source / "source-head-tree.txt").read_text().splitlines()
assert (checkout, tree) == ("b5c23d8943a0a36a14a962175cb2ec75d22d5553", "29316e75554590382268dafa77869fab0394a264")
assert all((source / f"source-status-{side}.txt").read_bytes() == b"" for side in ("before", "after"))
assert int((source / "original-bazel-exit-code.txt").read_text()) == 3
assert int((source / "console-copy-exit-code.txt").read_text()) == 0
assert next(step for step in job["steps"] if step["name"] == "Check for a clean worktree")["conclusion"] == "success"
leaves = {line.split("\t", 1)[1]: line.split("\t", 1)[0] for line in (source / "source-leaves.txt").read_text().splitlines()}
prior_source = ROOT / "terminal/probe-127420172838/members/b11-token-mechanism-probe"
prior_leaves = {line.split("\t", 1)[1]: line.split("\t", 1)[0] for line in (prior_source / "source-leaves.txt").read_text().splitlines()}
assert set(leaves) == set(prior_leaves)
changed = [path for path in leaves if leaves[path] != prior_leaves[path]]
assert changed == [".github/workflows/hepta-windows-token-mechanism-probe.yml"]
assert leaves[changed[0]] == "100644 blob 912e22789665b0081c83ae0fa632d2482e8b0eba"

test_path, = (DIRECTORY / "members/bazel-execution-logs/failed-test-logs").glob("*/targets/0000/test.log")
text = test_path.read_text()
clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
summaries = re.findall(r"^test result: .+$", text, re.M)
assert summaries == ["test result: ok. 92 passed; 0 failed; 0 ignored; 0 measured; 64 filtered out; finished in 1.04s",
                     "test result: FAILED. 55 passed; 7 failed; 2 ignored; 0 measured; 92 filtered out; finished in 0.21s"]
matches = list(re.finditer(r"^---- (\S+) stdout ----$", text, re.M))
failures = []
prior = json.loads((ROOT / "terminal/probe-127420172838/failure-classification.json").read_text())
prior_classes = {row["case"]: row["classification"] for row in prior["failures"]}
assert {m[1] for m in matches} == set(prior_classes) and len(matches) == 7
for index, match in enumerate(matches):
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    block = text[match.start():end].split("\nfailures:\n")[0]
    failures.append({"case": match[1], "line": text.count("\n", 0, match.start()) + 1,
                     "classification": prior_classes[match[1]], "original_block": block})
failure_record = write("failure-classification.json", {"source": record(test_path), "count": 7, "failures": failures,
    "same_failed_names_as_native6": True, "new_product_failure_names": [],
    "scope": "The original full-target result remains 147/7/2; the later harness precondition error is separate."})

control = source / "acl-identity-counterfactual"
terminal_path = control / "counterfactual-terminal.json"
entry_path = control / "source-entry.json"
terminal = json.loads(terminal_path.read_text())
entry = json.loads(entry_path.read_text())
assert set(p.name for p in control.iterdir()) == {terminal_path.name, entry_path.name}
assert terminal["status"] == "INVALID_OR_NOT_RUN"
assert all(terminal[key] is False for key in ("physical_counterfactual_qualified", "physical_oracle_reached",
    "restored_exact_original_bytes", "source_mutated", "source_mutation_attempted"))
assert terminal["restore_error"] is None and terminal["original_target_exit_code_unchanged"] is True
required = ["acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object",
            "acl::tests::existing_native_deny_does_not_require_write_dac",
            "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write",
            "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes"]
counts = {case: len(re.findall(r"^test " + re.escape(case) + r" \.\.\. ok$", clean, re.M)) for case in required}
assert list(counts.values()) == [1, 1, 1, 0]
assert terminal["error"] == f"RuntimeError('original target lacks one exact positive result for {required[-1]}')"
assert entry["head"] == checkout and entry["head_tree"] == tree and entry["status"] == []
assert entry["source_canonical_git_blob"] == "da5346c220c41cf0c83f62b596132c74c02284d8"
interleaved = [{"line": number, "raw": line} for number, line in enumerate(text.splitlines(), 1) if required[-1] in line]
assert len(interleaved) == 1
invalid = write("counterfactual-precondition-review.json", {
    "role": "ACTUAL_HARNESS_PRECONDITION_FAILURE_NEGATIVE_NOT_RUN", "terminal": record(terminal_path),
    "source_entry": record(entry_path), "full_source_test_log": record(test_path), "exact_whole_PASS_line_counts": counts,
    "original_interleaved_line_not_repaired": interleaved, "negative_source_installation_attempted": False,
    "negative_commands": 0, "physical_negative_qualification": False, "restore_error": None,
    "restore_flag_interpretation": "false because source was never mutated; this is not a failed restore",
    "original_whole_result_retained": True, "no_product_retry": True,
    "limits": ["Do not fabricate a PASS by stripping interleaved observation text.",
               "No extra positive or negative command ran. A later reviewed harness must collect independent exact-case records."]})

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
    "parsed": observations, "limits": "Counts describe only complete parsable records; interleaved or broken lines are never repaired. Full original text remains authoritative.",
    "qualifies_B11": False})

archive_path = DIRECTORY / "artifact-13442075776.zip"
archive = archive_path.read_bytes()
assert hashlib.sha256(archive).hexdigest() == "fdd7ecce25df2f5319c397b0320dcde17871a7dc97486ea604f7d46f77674861"
part_directory = DIRECTORY / "archive-parts"
part_directory.mkdir(exist_ok=False)
parts = []
for number, offset in enumerate(range(0, len(archive), 131072)):
    raw = archive[offset:offset + 131072]
    path = part_directory / f"artifact-13442075776-{number:03}.base64"
    path.write_bytes(base64.b64encode(raw) + b"\n")
    parts.append({"sequence": number, "offset": offset, "raw": identity(raw), "encoded": record(path)})
assert b"".join(base64.b64decode(Path(part["encoded"]["local_path"]).read_bytes().strip(), validate=True) for part in parts) == archive
parts_record = write("archive-parts-manifest.json", {"schema": "original-github-artifact-chunks-v1",
    "run_id": run["id"], "job_id": job["id"], "artifact_id": 13442075776,
    "original_archive": record(archive_path), "roundtrip_original_bytes_verified": True,
    "member_crc_and_hash_verification": record(DIRECTORY / "artifact-verification.json"), "parts": parts,
    "git_upload_qualification": "Computed identities until separate actual create+GET map is written."})
review = write("terminal-review.json", {"schema": "b11-diagnostic-pr-native7-terminal-review-v1",
    "role": "ORIGINAL_WHOLE_RESULT_PLUS_INVALID_HARNESS_PRECONDITION_NOT_B11_CLOSURE",
    "head": run["head_sha"], "head_tree": "f717a84a856413d87a3b718b0bcae3adbd16b643",
    "run_id": run["id"], "job_id": job["id"], "run_attempt": 1, "conclusion": job["conclusion"],
    "started_at": job["started_at"], "completed_at": job["completed_at"], "steps": job["steps"],
    "actual_checkout_commit": checkout, "actual_checkout_tree": tree, "source_leaves": leaves,
    "captured_leaf_changes_from_native6": changed, "original_clean_source_before_after": True,
    "original_bazel_exit": 3, "console_copy_exit": 0, "final_clean_worktree_step_success": True,
    "target": "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests", "summaries": summaries,
    "combined_disjoint_counts": {"total_named_tests": 156, "passed": 147, "failed": 7, "ignored": 2},
    "count_limit": "Two disjoint libtest groups in one original target attempt, not retries. Job wrapper-tail repeats are not extra executions.",
    "failure_classification": failure_record, "physical_observations": projection,
    "counterfactual_precondition": invalid, "counterfactual_status": "INVALID_OR_NOT_RUN",
    "negative_executed": False, "source_mutation_attempted": False, "B11_status": "OPEN",
    "evidence": {"job_log": record(DIRECTORY / "job.log"), "full_test_log": record(test_path),
                 "target_level_xml": record(test_path.with_suffix(".xml")), "API": record(DIRECTORY / "terminal-api-envelopes.json"),
                 "archive_verification": record(DIRECTORY / "artifact-verification.json"), "archive_parts_manifest": parts_record},
    "native_or_ref_mutation_by_auditor": False})
print(json.dumps({"review": review, "invalid": invalid, "projection_counts": {k: {n: len(v) for n, v in row.items()} for k, row in observations.items()},
                  "archive_parts": len(parts)}, indent=2))
