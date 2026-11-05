from pathlib import Path
import base64
import hashlib
import json
import re


ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "terminal/probe-127420172838"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def record(path):
    return {"local_path": str(path), **identity(path.read_bytes())}


def write(name, value):
    path = DIRECTORY / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return record(path)


api = json.loads((DIRECTORY / "terminal-api-envelopes.json").read_text())
run = json.loads(api["run"]["structuredContent"]["content"])
jobs = json.loads(api["jobs"]["structuredContent"]["content"])
job, = [row for row in jobs["jobs"] if row["id"] == 127420172838]
assert run["head_sha"] == "19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14"
assert run["run_attempt"] == 1 and job["conclusion"] == "failure"
assert (DIRECTORY / "job.log").read_bytes() == api["log"]["structuredContent"]["content"].encode()
test_path, = list((DIRECTORY / "members/bazel-execution-logs/failed-test-logs").glob("*/targets/0000/test.log"))
text = test_path.read_text()
lines = text.splitlines()
summaries = []
for number, line in enumerate(lines, 1):
    found = re.fullmatch(r"test result: (?:FAILED|ok)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([\d.]+)s", line)
    if found:
        summaries.append({"line": number, "raw": line, "passed": int(found[1]), "failed": int(found[2]),
                          "ignored": int(found[3]), "filtered_out": int(found[5]), "seconds": found[6]})
assert [(s["passed"], s["failed"], s["ignored"], s["filtered_out"]) for s in summaries] == [(92, 0, 0, 64), (55, 7, 2, 92)]
matches = list(re.finditer(r"^---- (\S+) stdout ----$", text, re.M))
failures = []
for index, match in enumerate(matches):
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    block = text[match.start():end].split("\nfailures:\n")[0]
    failures.append({"case": match[1], "line": text.count("\n", 0, match.start()) + 1, "original_block": block})
assert len(failures) == len({x["case"] for x in failures}) == 7
direct = [{"case": m[1], "result": m[2], "line": text.count("\n", 0, m.start()) + 1}
          for m in re.finditer(r"test ([a-zA-Z0-9_:]+) \.\.\. (ok|FAILED|ignored)", text)]
probe = "token::integrity_probe::integrity_mechanism_probe_observation_only"
assert any(x["case"] == probe and x["result"] == "ok" for x in direct)
complete = [{"line": n, "raw": line} for n, line in enumerate(lines, 1)
            if line == "PROBE_OBSERVATION_ONLY complete rows=8 token_subjects=4 descendants_spawned=0 tests_do_not_qualify_isolation=true"]
assert len(complete) == 1
parsed = {}
for kind in ("row", "restoration", "finalized"):
    good, interleaved = [], []
    marker = "PROBE_OBSERVATION_ONLY " + kind + " "
    for number, line in enumerate(lines, 1):
        if marker not in line:
            continue
        try:
            good.append({"line": number, "value": json.loads(line.split(marker, 1)[1])})
        except json.JSONDecodeError as error:
            interleaved.append({"line": number, "raw": line, "error": str(error)})
    parsed[kind] = {"complete_json": good, "interleaved_not_repaired": interleaved}
assert len(parsed["row"]["complete_json"]) == 6 and len(parsed["row"]["interleaved_not_repaired"]) == 1
for kind in ("restoration", "finalized"):
    assert len(parsed[kind]["complete_json"]) == 8 and not parsed[kind]["interleaved_not_repaired"]
expected_rows = {(subject, level) for subject in ("host", "current_strict", "current_strict_low", "full_restricting_explicit_read")
                 for level in ("medium", "low_other_cohort")}
assert {(r["value"]["subject"], r["value"]["outside_level"]) for r in parsed["finalized"]["complete_json"]} == expected_rows
restored = [r["value"] for r in parsed["restoration"]["complete_json"]]
assert all(len(row["results"]) == 10 and all("error" not in item for item in row["results"]) for row in restored)
assert all(item["pending"] == 1 or item["restored_survivor"] is True for row in restored for item in row["results"])
source = DIRECTORY / "members/b11-token-mechanism-probe"
checkout, tree = (source / "source-head-tree.txt").read_text().splitlines()
assert checkout == "69040075a846c7032a3bafc7a0b623e7c0257619"
assert tree == "75181bf7e4f119d08945003339b32aa0782ef41c"
assert all((source / f"source-status-{side}.txt").read_bytes() == b"" for side in ("before", "after"))
leaves = {}
for line in (source / "source-leaves.txt").read_text().splitlines():
    mode, typ, tail = line.split(" ", 2)
    sha, path = tail.split("\t", 1)
    leaves[path] = {"mode": mode, "type": typ, "git_blob": sha}
expected = {
    ".github/workflows/hepta-windows-token-mechanism-probe.yml": "70f3145268e042ec04fbfe85eda83ccbbc4ff79c",
    "codex-rs/windows-sandbox-rs/src/acl_deny.rs": "da5346c220c41cf0c83f62b596132c74c02284d8",
    "codex-rs/windows-sandbox-rs/src/acl_tests.rs": "ec0264a7615097bec1b554cb60918b4f4662eec2",
    "codex-rs/windows-sandbox-rs/src/unified_exec/acl_setup_tests.rs": "5390daefe0f872866764cb567ad13f22c0675cf4",
    "codex-rs/windows-sandbox-rs/src/token.rs": "b22acb5556f6af3b4c250a2441f161ee448ea1c1",
    "codex-rs/windows-sandbox-rs/src/token_integrity_probe_support.rs": "7a7008f9becf09578ca953c849401eda93eb94b2",
    "codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs": "2a384792e8ba88518c26943716e8c3a39a523f9b",
    "codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs": "d8511f92f9fbd9d58061238dbf3181152c74ccbc",
}
assert all(leaves[path]["git_blob"] == sha for path, sha in expected.items())
old_test, = list((ROOT / "terminal/probe-127383345954/members/bazel-execution-logs/failed-test-logs").glob("*/targets/0000/test.log"))
old_failures = set(re.findall(r"^---- (\S+) stdout ----$", old_test.read_text(), re.M))
new_failures = {row["case"] for row in failures}
improved = sorted(old_failures - new_failures)
assert improved == ["acl::tests::existing_native_deny_does_not_require_write_dac",
                    "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write",
                    "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes"]
assert not new_failures - old_failures
assert all(any(row["case"] == name and row["result"] == "ok" for row in direct) for name in improved)

import runpy
helper = ROOT.parent / "b11-acl-repair-20261105/counterfactual-workflow-v2/candidate/.github/scripts/run_b11_acl_identity_counterfactual.py"
api_parser = runpy.run_path(str(helper), run_name="native6_readonly_parser")
positive, positive_manifest = api_parser["retained_log"](DIRECTORY / "members/bazel-execution-logs", checkout, tree, False)
assert positive[".log"][0] == test_path.read_bytes()
positive_text = api_parser["ANSI"].sub("", positive[".log"][0].decode()).replace("\r", "")
required_cases = [api_parser["CASE"], "acl::tests::existing_native_deny_does_not_require_write_dac",
    "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write",
    "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes"]
positive_rows = []
for case in required_cases:
    found = list(re.finditer(r"^test " + re.escape(case) + r" \.\.\. ok$", positive_text, re.M))
    assert len(found) == 1, case
    positive_rows.append({"case": case, "result": "PASS", "line": positive_text.count("\n", 0, found[0].start()) + 1})
physical_markers = [line for line in positive_text.splitlines() if line.startswith("deny_repair_identity:")]
assert physical_markers == [
    "deny_repair_identity: directory=false returned_ok=false replacement_changed=false original_changed=false",
    "deny_repair_identity: directory=true returned_ok=false replacement_changed=false original_changed=false"]
summary = api_parser["target_terminal"]((source / "bazel-console.log").read_bytes(), "FAILED")
positive_prerequisites = write("counterfactual-positive-prerequisites.json", {
    "schema": "b11-counterfactual-positive-prerequisites-from-actual-native6",
    "status": "FOUR_ORIGINAL_POSITIVE_PREREQUISITES_CONFIRMED_NEGATIVE_NOT_RUN",
    "actual_checkout_commit": checkout, "actual_checkout_tree": tree,
    "source_leaves": [{"path": path, **leaves[path]} for path in expected],
    "original_target_summary": summary, "original_bazel_exit_code": 3,
    "required_cases": positive_rows, "file_and_directory_identity_markers": physical_markers,
    "retained_manifest": positive_manifest, "retained_files": {k: v[1] for k, v in positive.items()},
    "reviewed_counterfactual_script": record(helper), "only_readonly_parsers_called": True,
    "script_main_or_native_executed": False,
    "qualification_limits": ["This records a completed original full-target run. A future same-job negative must freshly establish its own original positive prerequisites.",
                             "No identity-removal source was installed or run. The counterfactual and strict B11 isolation remain unqualified."]})

classifications = []
for row in failures:
    case = row["case"]
    if "ReOpenFile for deny repair failed" in row["original_block"]:
        kind = "PRODUCTION_REPAIR_ENDPOINT_REOPEN_ACCESS_DENIED"
    elif case == "acl::tests::existing_native_deny_does_not_require_write_dac":
        kind = "HOST_NEGATIVE_PRECONDITION_FAILED_REOPEN_SUCCEEDED"
    elif case == "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces":
        kind = "ACTUAL_STRICT_TOKEN_OUTSIDE_DELETE_ESCAPE"
    elif "delete_routes_require" in case:
        kind = "ORDINARY_HOST_NEITHER_PRECONDITION_FAILED_BEFORE_RESTRICTED_SUBJECT"
    else:
        assert "test lock poisoned" in row["original_block"]
        kind = "SHARED_TEST_MUTEX_POISON_NOT_INDEPENDENT_BUSINESS_ORACLE"
    classifications.append({**row, "classification": kind})
classification = write("failure-classification.json", {"source": record(test_path), "failures": classifications,
    "count": 7, "prior_original_source": record(old_test), "new_failures": [], "three_now_direct_pass": improved,
    "claim_limit": "Three prior failing names now directly PASS. This actual candidate result is not a proof that a particular omitted ReOpenFile right was the unique previous cause; the identity counterfactual remains unexecuted."})
projection = write("physical-observation-projection.json", {"schema": "b11-eight-row-native-observation-v3",
    "source": record(test_path), "role": "PROBE_OBSERVATION_ONLY_NOT_PRODUCTION_ACCEPTANCE", "complete_marker": complete,
    "token_lines": [{"line": n, "raw": line} for n, line in enumerate(lines, 1) if line.startswith("PROBE_OBSERVATION_ONLY token ")],
    "parsed": parsed, "broken_prefix_context_lines": [{"line": n, "raw": line} for n, line in enumerate(lines, 1) if '"subject":"current_strict_low","outside_level":"medium"' in line and not line.startswith("PROBE_OBSERVATION_ONLY ")], "interleaved_limit": "Only six complete row JSON values parse. Host-medium has an intact prefix but interleaved JSON; current_strict_low-medium also has a broken prefix. Their full raw lines remain unchanged, never reconstructed as valid JSON. Eight finalized and restoration records are intact.",
    "restoration_objects": 80, "restoration_errors": 0,
    "restored_survivors": sum(item["restored_survivor"] for row in restored for item in row["results"]),
    "deleted_pending_objects": sum(item["pending"] for row in restored for item in row["results"]),
    "descendants_spawned": 0})
archive_path = DIRECTORY / "artifact-13438699284.zip"
archive = archive_path.read_bytes()
assert hashlib.sha256(archive).hexdigest() == "341e7b854d79329ee0c42113957f1d8c86bd6b74229fb6b4b2f1562c25ca8285"
part_directory = DIRECTORY / "archive-parts"
part_directory.mkdir(exist_ok=False)
parts = []
for number, offset in enumerate(range(0, len(archive), 131072)):
    raw = archive[offset:offset + 131072]
    path = part_directory / f"artifact-13438699284-{number:03}.base64"
    path.write_bytes(base64.b64encode(raw) + b"\n")
    parts.append({"sequence": number, "offset": offset, "raw": identity(raw), "encoded": record(path)})
assert b"".join(base64.b64decode(Path(part["encoded"]["local_path"]).read_bytes().strip(), validate=True) for part in parts) == archive
parts_record = write("archive-parts-manifest.json", {"schema": "original-github-artifact-chunks-v1", "run_id": run["id"],
    "job_id": job["id"], "artifact_id": 13438699284, "head_sha": run["head_sha"], "original_archive": record(archive_path),
    "roundtrip_original_bytes_verified": True, "member_crc_and_hash_verification": record(DIRECTORY / "artifact-verification.json"),
    "parts": parts, "git_upload_qualification": "Computed identities until separate actual create+GET map is written."})
review = write("terminal-review.json", {"schema": "b11-diagnostic-pr-native-terminal-review-v4",
    "role": "ORIGINAL_RESULT_EVIDENCE_NOT_B11_CLOSURE", "head": run["head_sha"], "head_tree": "17ac791ce156d05d4d1cd13cddf9184e528293a1",
    "run_id": run["id"], "run_attempt": 1, "job_id": job["id"], "conclusion": job["conclusion"],
    "started_at": job["started_at"], "completed_at": job["completed_at"], "actual_checkout_commit": checkout, "actual_checkout_tree": tree,
    "source_scope": "Actual merge checkout combines published primary fixes with diagnostic ACL identity V3; not relabelled as the head tree. Parent/whole-tree bridge is independently supplied by root.",
    "source_leaf_checks": [{"path": path, **leaves[path]} for path in expected], "clean_worktree_before_after": True,
    "target": "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests", "summaries": summaries,
    "combined_disjoint_counts": {"total_named_tests": 156, "passed": 147, "failed": 7, "ignored": 2},
    "count_limit": "Two disjoint libtest groups in one target attempt. Wrapper-tail repetition is not a second attempt. XML is target-level.",
    "direct_status_records": direct, "direct_status_parse_limit": "Only contiguous names/statuses are listed; interleaved absent forms are not inferred as direct PASS.",
    "failure_classification": classification, "physical_observation_projection": projection,
    "probe_fixture_reached_complete_eight_rows": True, "probe_fixture_pass": True,
    "counterfactual_positive_prerequisites": positive_prerequisites,
    "three_now_direct_pass": improved, "original_bazel_exit_code": int((source / "original-bazel-exit-code.txt").read_text()),
    "console_copy_exit_code": int((source / "console-copy-exit-code.txt").read_text()),
    "limits": ["Both existing directory repair cases and the original no-WRITE_DAC case now directly PASS, with all original assertions. New file/directory replacement control also PASS. This scoped result does not close strict token isolation.",
               "The approved identity-removal counterfactual has not run; its XML101/marker/assertion/finally endpoint remains pending.",
               "One strict-token test physically deletes outside objects. Two matrix cases fail ordinary-host Neither preconditions before restricted subjects.",
               "Four shared-test-lock poison failures do not independently establish sandbox isolation failures.",
               "Eight-row impersonation controls involve no descendant process, loader, normal UI caller or Job lifetime qualification.",
               "All previous original result sets remain immutable, including native5 143/10/2, native4 140/13/2 and native2/native3 139/14/2."],
    "evidence": {"full_job_log": record(DIRECTORY / "job.log"), "full_test_log": record(test_path),
                 "target_level_xml": record(test_path.with_suffix(".xml")), "api_envelopes": record(DIRECTORY / "terminal-api-envelopes.json"),
                 "full_archive": record(archive_path), "archive_verification": record(DIRECTORY / "artifact-verification.json"),
                 "archive_chunk_manifest": parts_record},
    "qualification": {"B11_status": "OPEN", "strict_token_qualified": False, "directory_acl_repair_positive_scope_passed": True, "identity_counterfactual_qualified": False,
                      "legacy_helper_qualified": False, "retry_or_rerun_started_by_auditor": False, "native_host_or_source_changed_by_auditor": False}})
print(json.dumps({"review": review, "classification": classification, "projection": projection, "archive_parts": len(parts)}))
