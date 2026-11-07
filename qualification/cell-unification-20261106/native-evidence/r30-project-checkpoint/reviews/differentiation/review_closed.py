"""Independent local R30 reader. No runner import, subprocess, or native access."""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import re

PREFIX = "native-source53-project-r30"
JOB = "1a1b25b399f-fc05-7daa"
COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
CARGO = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
SOURCE_SHA = "9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda"
BASELINE_SHA = "92e7ef41b0c2b08b81bb3ad9542f20ec820d86185f80369b4478cb5bd9c20cf1"
BASELINE_BYTES = 555309
SOURCE_BYTES = 56747
COMMANDS = {
    "strict": ["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"],
    "tests": ["just", "test", "--locked", "--retries", "0", "-p", "codex-app-server"],
}
CWD = "/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs"
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
RESULT = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
START = re.compile(r"^\s*Starting ([0-9]+) tests?\b")
SUMMARY = re.compile(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$")
KEYS = ("bytes", "sha256", "git_blob")


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parse_execution(raw, baseline):
    """Parse before Summary only. Report compile/partial execution without fake zero totals."""
    rows_with_end, starts, summaries = [], [], []
    offset = 0
    for number, raw_line in enumerate(raw.splitlines(keepends=True), 1):
        text = ANSI.sub(b"", raw_line).decode("utf-8", errors="replace").rstrip("\r\n")
        if match := START.match(text):
            starts.append({"line": number, "byte_offset": offset, "text": text, "tests": int(match[1])})
        if match := SUMMARY.match(text):
            tail = match[3]
            parsed = {key: (int(found[1]) if (found := re.search(pattern, tail)) else 0)
                      for key, pattern in {
                          "PASS": r"\b(\d+) passed\b", "FAIL": r"\b(\d+) failed\b",
                          "TIMEOUT": r"\b(\d+) timed out\b", "skipped": r"\b(\d+) skipped\b",
                      }.items()}
            summaries.append({"line": number, "byte_offset": offset, "text": text,
                              "tests": int(match[2]), "seconds": float(match[1]), "counts": parsed})
        if match := RESULT.match(text):
            rows_with_end.append({"status": match[1], "seconds": float(match[2]),
                                  "binary": match[3], "name": match[4].strip(),
                                  "line": number, "byte_offset": offset})
        offset += len(raw_line)
    require(len(starts) <= 1 and len(summaries) <= 1, "multiple nextest invocations in one original gate log")
    start, summary = (starts[0] if starts else None), (summaries[0] if summaries else None)
    if summary:
        require(start is not None and start["line"] < summary["line"], "Summary without preceding Starting")
    rows = [row for row in rows_with_end if start and row["line"] > start["line"]
            and (summary is None or row["line"] < summary["line"])]
    footer = [row for row in rows_with_end if summary and row["line"] > summary["line"]]
    pre_start = [row for row in rows_with_end if not start or row["line"] <= start["line"]]
    require(not pre_start, "result-shaped rows outside a declared execution")
    identities = [(row["binary"], row["name"]) for row in rows]
    duplicates = sorted(identity for identity, count in collections.Counter(identities).items() if count > 1)
    require(not duplicates, "duplicate executed binary/name IDs before Summary")
    observed = dict(zip(identities, rows))
    counts = {key: sum(row["status"] == key for row in rows) for key in ("PASS", "FAIL", "TIMEOUT")}
    complete = summary is not None
    if complete:
        require(start["tests"] == summary["tests"] == len(rows), "Starting/Summary/unique row total mismatch")
        require(counts == {key: summary["counts"][key] for key in counts}, "Summary differs from original rows")
    missing, extra = sorted(baseline - set(observed)), sorted(set(observed) - baseline)
    packages = sorted({row["binary"].split("::", 1)[0] for row in rows})
    unexpected = sorted(set(packages) - {"codex-app-server"})
    require(not unexpected, "non-app-server result in this original project gate")
    failure_spans = []
    for i, row in enumerate(rows):
        if row["status"] == "PASS":
            continue
        end = rows[i + 1]["byte_offset"] if i + 1 < len(rows) else (
            summary["byte_offset"] if summary else len(raw))
        block = raw[row["byte_offset"]:end]
        failure_spans.append({"binary": row["binary"], "name": row["name"], "status": row["status"],
                              "seconds": row["seconds"], "first_line": row["line"],
                              "byte_start": row["byte_offset"], "byte_end": end, **pin(block)})
    return rows, {
        "nextest_started": start is not None, "execution_complete": complete,
        "starting": start, "summary": summary, "execution_rows_observed": len(rows),
        "terminal_unique_test_count": len(rows) if complete else None,
        "terminal_counts": counts if complete else None,
        "partial_observed_counts": None if complete else counts,
        "reported_skipped": summary["counts"]["skipped"] if complete else None,
        "skip_identities_inferred": False, "footer_rows_excluded": footer,
        "duplicate_execution_ids": duplicates,
        "baseline_count": len(baseline), "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in extra],
        "baseline_not_pass": [{"binary": b, "name": n} for (b, n), row in observed.items()
                              if (b, n) in baseline and row["status"] != "PASS"],
        "exact_1345_identity_set": complete and not missing and not extra and len(rows) == 1345,
        "all_executed_ids_pass": complete and bool(rows) and counts["FAIL"] == counts["TIMEOUT"] == 0,
        "per_binary": {binary: {key: sum(row["binary"] == binary and row["status"] == key for row in rows)
                                for key in counts} for binary in sorted({row["binary"] for row in rows})},
        "failure_spans": failure_spans,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", type=Path, required=True, help="Only the explicitly closed local evidence directory.")
    ap.add_argument("--terminal", type=Path, required=True)
    ap.add_argument("--terminal-sha256", required=True, help="Pin supplied with the actual closed native terminal.")
    ap.add_argument("--tests-log-sha256", help="Actual closed log pin; required if the tests log exists.")
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--source-manifest", type=Path, required=True)
    ap.add_argument("--source-export", type=Path, help="Optional complete 197-file export; absence is reported explicitly.")
    ap.add_argument("--output", type=Path, required=True, help="New create-only report directory.")
    args = ap.parse_args()
    require(not args.output.exists(), "report output already exists")
    terminal_raw = args.terminal.read_bytes()
    require(pin(terminal_raw)["sha256"] == args.terminal_sha256, "terminal original pin mismatch")
    terminal = json.loads(terminal_raw)
    require(terminal["job_id"] == JOB and isinstance(terminal["exit_code"], int)
            and terminal["state"] in {"succeeded", "failed"}, "not the closed R30 terminal")
    require(terminal["output_complete"] is True and terminal["output_durable"] is True
            and terminal["terminal_publication_confirmed"] is True, "outer output is not complete/durable")
    require(all(value is False for value in terminal["log_truncated"].values())
            and all(value is None for value in terminal["log_errors"].values()), "outer output incomplete")
    for stream in terminal["log_bytes"].values():
        require(stream["seen"] == stream["stored"], "outer recorded output byte count mismatch")
    natural = all(terminal[field] is False for field in ("timed_out", "cancelled", "automatic_retry"))
    baseline_raw, source_raw = args.baseline.read_bytes(), args.source_manifest.read_bytes()
    require(len(baseline_raw) == BASELINE_BYTES and pin(baseline_raw)["sha256"] == BASELINE_SHA, "baseline changed")
    require(len(source_raw) == SOURCE_BYTES and pin(source_raw)["sha256"] == SOURCE_SHA, "source manifest changed")
    baseline_doc, manifest = json.loads(baseline_raw), json.loads(source_raw)
    baseline = {(row["binary"], row["name"]) for row in baseline_doc["test_ids"]}
    require(baseline_doc["count"] == len(baseline) == len(baseline_doc["test_ids"]) == 1345, "baseline ambiguity")
    require(baseline_doc["observed_counts"] == {"PASS": 1344, "FAIL": 1, "TIMEOUT": 0}
            and baseline_doc["original_gate_exit"] == 100, "original R29 history was relabelled")
    require(manifest["source_commit"] == COMMIT and manifest["source_tree"] == TREE
            and manifest["changed_file_count"] == len(manifest["changed_files"]) == 197,
            "wrong registered source53")
    files = {row["path"]: row for row in manifest["changed_files"]}
    require(len(files) == 197 and sum(path.endswith(".rs") for path in files) == 183, "source population changed")
    require(manifest["cargo_lock_sha256"] == CARGO and manifest["bazel_lock_sha256"] == BAZEL,
            "registered lock pins changed")
    originals = {path.name: path.read_bytes() for path in sorted(args.evidence.glob(PREFIX + "-*")) if path.is_file()}
    records = {name: json.loads(raw) for name, raw in originals.items() if name.endswith(".json")}
    issues = []

    def check(ok, message):
        if not ok:
            issues.append(message)

    def pointer(value, name):
        check(name in originals and value == {"path": name, **pin(originals[name])},
              "pointer/bytes differ: " + name)

    def guard(name):
        doc = records.get(name)
        check(doc is not None, "missing actual source guard: " + name)
        if doc is None:
            return None
        expected = {"expected_tree": TREE, "source_commit": COMMIT, "changed_file_count": 197,
                    "pass": True, "actual_tree": TREE, "native_head": HEAD, "unstaged_paths": [],
                    "untracked_paths": [], "changed_path_set_matches": True, "file_mismatches": [],
                    "cargo_lock_sha256": CARGO, "bazel_lock_sha256": BAZEL}
        for key, value in expected.items():
            check(doc.get(key) == value, name + ": " + key)
        return doc

    env = records[PREFIX + "-environment.json"]
    pre = records[PREFIX + "-preconditions.json"]
    for name, doc in (("environment", env), ("preconditions", pre)):
        check(doc["source_commit"] == COMMIT and doc["source_tree"] == TREE, name + " source identity")
        check(doc["diagnostic_only"] is True and doc["behavior_repair_claimed"] is False, name + " classification")
    check(env["source_manifest_sha256"] == SOURCE_SHA and env["source_manifest"] == "native-candidate-r30-source.json",
          "environment source pointer")
    check(env["test_deadlines_features_filters_retries_unchanged"] is True
          and env["sandbox_or_network_protection_environment_overridden"] is False, "environment protections")
    check(pre["actual_changed_file_count"] == 197
          and pre["source_manifest"] == {"path": "native-candidate-r30-source.json", **pin(source_raw)},
          "preconditions source")
    check(pre["cargo_lock_sha256"] == CARGO and pre["bazel_lock_sha256"] == BAZEL, "preconditions locks")
    check(pre["baseline"] == {"path": "source53-app-server-r29-baseline.json", **pin(baseline_raw)},
          "preconditions baseline pin")
    check(pre["previous_source52_workspace_result"] == "FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP",
          "previous R29 failure preserved")
    for key in ("patch_application_performed_by_this_runner", "lock_update_performed_by_this_runner", "python_suite_reexecuted"):
        check(pre[key] is False, "unexpected R30 mutation/reexecution: " + key)
    pointer(pre["initial_source_guard"], PREFIX + "-source-pre-verification.json")
    guard(PREFIX + "-source-pre-verification.json")
    phases = []
    prior_end = None
    rows, parsed = [], None
    for phase in ("strict", "tests"):
        stem = PREFIX + "-" + phase
        raw_name, receipt_name = stem + "-raw-process-result.json", stem + "-receipt.json"
        if raw_name not in originals and receipt_name not in originals:
            phases.append({"phase": phase, "started_with_closed_raw_result": False, "counts": None})
            continue
        check(raw_name in originals and receipt_name in originals, "missing raw/receipt pair: " + phase)
        if raw_name not in originals or receipt_name not in originals:
            continue
        raw, receipt = records[raw_name], records[receipt_name]
        for field in ("phase", "source_tree", "source_commit", "command", "cwd", "start_unix", "end_unix", "exit_code"):
            check(raw[field] == receipt[field], phase + " raw/receipt field " + field)
        check(raw["schema"] == "hepta.native-raw-process-result.v1" and receipt["schema"] == "hepta.native-gate-receipt.v2",
              phase + " schema")
        check(raw["phase"] == phase and raw["source_tree"] == TREE and raw["source_commit"] == COMMIT
              and raw["command"] == COMMANDS[phase] and raw["cwd"] == CWD, phase + " actual command/identity")
        check(raw["end_unix"] >= raw["start_unix"]
              and abs(receipt["elapsed_seconds"] - (raw["end_unix"] - raw["start_unix"])) < 1e-6,
              phase + " elapsed accounting")
        if prior_end is not None:
            check(raw["start_unix"] >= prior_end, "phase overlap/order")
        prior_end = raw["end_unix"]
        pointer(receipt["raw_process_result"], raw_name)
        preguard = guard(stem + "-source-pre-verification.json")
        postguard = guard(stem + "-source-post-verification.json")
        pointer(receipt["source_postguard"], stem + "-source-post-verification.json")
        if postguard:
            check(postguard.get("phase") == phase and postguard.get("gate_exit_code") == raw["exit_code"],
                  phase + " postguard original exit")
        log, resource = originals[stem + ".log"], originals[stem + "-resources.txt"]
        check(receipt["log_sha256"] == pin(log)["sha256"] and receipt["resources_sha256"] == pin(resource)["sha256"],
              phase + " output hashes")
        check(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource, re.M) == [str(raw["exit_code"]).encode()],
              phase + " original resource exit")
        check(receipt["source_manifest_sha256"] == SOURCE_SHA and receipt["packages"] == ["codex-app-server"]
              and receipt["features"] == "unchanged_defaults" and receipt["filters"] == "no_additions",
              phase + " source/scope")
        check(receipt["baseline_used_as_filter"] is False and receipt["fix_fmt_executed"] is False
              and receipt["diagnostic_only"] is True and receipt["behavior_repair_claimed"] is False,
              phase + " classification/selection")
        check(receipt["retries"] == (0 if phase == "tests" else None), phase + " retry contract")
        effective = raw["exit_code"] if raw["exit_code"] else (1 if receipt["issues"] else 0)
        check(receipt["effective_exit_code"] == effective and receipt["phase_pass"] == (effective == 0),
              phase + " raw/effective semantics")
        if phase == "tests":
            require(args.tests_log_sha256 and pin(log)["sha256"] == args.tests_log_sha256, "closed tests log external pin missing/differs")
            rows, parsed = parse_execution(log, baseline)
            row_name, review_name = stem + "-test-results.json", stem + "-result-review.json"
            if row_name in records:
                check(records[row_name] == rows, "native derived rows differ from independent original log")
            if review_name in records:
                derived = records[review_name]
                if parsed["execution_complete"]:
                    for a, b in (("unique_test_count", "terminal_unique_test_count"), ("counts", "terminal_counts"),
                                 ("reported_skipped", "reported_skipped"), ("baseline_missing", "baseline_missing"),
                                 ("additional_test_ids", "additional_test_ids"), ("footer_rows_excluded", "footer_rows_excluded")):
                        check(derived[a] == parsed[b], "native derived review differs: " + a)
                    check(derived["pass"] == (parsed["exact_1345_identity_set"] and parsed["all_executed_ids_pass"]),
                          "native acceptance boolean differs")
                if receipt["acceptance_readback"] is not None:
                    pointer(receipt["acceptance_readback"], review_name)
        phases.append({"phase": phase, "started_with_closed_raw_result": True, "command": raw["command"],
                       "raw_exit": raw["exit_code"], "effective_exit": receipt["effective_exit_code"],
                       "elapsed_seconds": receipt["elapsed_seconds"], "phase_pass": receipt["phase_pass"],
                       "source_guards_pass": receipt["source_guards_pass"],
                       "raw_result": {"path": raw_name, **pin(originals[raw_name])},
                       "receipt": {"path": receipt_name, **pin(originals[receipt_name])},
                       "log": {"path": stem + ".log", **pin(log)}, "resources": {"path": stem + "-resources.txt", **pin(resource)}})
    completed_phases = [phase for phase in phases if phase.get("started_with_closed_raw_result")]
    if completed_phases:
        check(terminal["exit_code"] == completed_phases[-1]["effective_exit"], "outer/final phase effective return")
        check(terminal["at_unix_ms"] / 1000 >= prior_end, "outer terminal before original child end")
    pass_observed = natural and terminal["state"] == "succeeded" and terminal["exit_code"] == 0
    complete_name, incomplete_name = PREFIX + "-complete.json", PREFIX + "-incomplete.json"
    if pass_observed:
        check(len(completed_phases) == 2 and all(phase["phase_pass"] for phase in completed_phases), "success without both phases")
        check(parsed is not None and parsed["exact_1345_identity_set"] and parsed["all_executed_ids_pass"], "success without full exact PASS")
        check(complete_name in records and incomplete_name not in records, "wrong successful closure set")
        if complete_name in records:
            complete = records[complete_name]
            check(complete["source_commit"] == COMMIT and complete["source_tree"] == TREE
                  and complete["strict_exit"] == complete["tests_exit"] == 0
                  and complete["required_old_ids"] == 1345 and complete["all_old_ids_observed_pass"] is True,
                  "completion identity/counts")
            check(complete["source_manifest_sha256"] == SOURCE_SHA and complete["source_guards_pass"] is True
                  and complete["cargo_lock_sha256"] == CARGO and complete["bazel_lock_sha256"] == BAZEL,
                  "completion guards/locks")
            check(complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False
                  and complete["original_r29_failure_relabelled_as_pass"] is False
                  and complete["fix_fmt_executed"] is False, "completion diagnostic boundary")
            check(len(complete["phase_receipts"]) == 2, "successful completion receipt count")
            for value, phase in zip(complete["phase_receipts"], ("strict", "tests")):
                pointer(value, PREFIX + "-" + phase + "-receipt.json")
            guard(PREFIX + "-source-final-verification.json")
        required = {PREFIX + suffix for suffix in (
            "-environment.json", "-preconditions.json", "-source-pre-verification.json",
            "-source-final-verification.json", "-complete.json",
            "-tests-test-results.json", "-tests-result-review.json")}
        required |= {PREFIX + "-" + phase + suffix for phase in ("strict", "tests") for suffix in (
            "-source-pre-verification.json", ".log", "-resources.txt", "-raw-process-result.json",
            "-source-post-verification.json", "-receipt.json")}
        check(len(required) == 19 and required <= set(originals), "missing one of 19 successful originals")
    else:
        check(complete_name not in records, "failed outer has a successful complete record")
        if incomplete_name in records:
            incomplete = records[incomplete_name]
            check(incomplete["source_commit"] == COMMIT and incomplete["source_tree"] == TREE
                  and incomplete["effective_exit_code"] == terminal["exit_code"]
                  and incomplete["subsequent_phases_started"] is False
                  and incomplete["source_retained"] is True, "incomplete record differs")

    source_readback = {"registered_manifest_rows": 197, "raw_files_independently_read": 0,
                       "scope": "REGISTERED_MANIFEST_AND_CLOSED_NATIVE_GUARDS_ONLY",
                       "full_export_bytes_pending": args.source_export is None}
    if args.source_export is not None:
        read_rows = []
        for path, expected in sorted(files.items()):
            local = args.source_export / path
            require(local.is_file() and not local.is_symlink(), "missing raw exported source: " + path)
            data = local.read_bytes()
            check(pin(data) == {key: expected[key] for key in KEYS}, "raw exported source differs: " + path)
            read_rows.append({"path": path, "declared_git_mode": expected["mode"], **pin(data)})
        source_readback.update(raw_files_independently_read=len(read_rows),
                               scope="197_RAW_SHA_AND_GIT_BLOB_BYTES_PLUS_NATIVE_GUARDS",
                               full_export_bytes_pending=False, files=read_rows,
                               tar_permission_bits_not_substituted_for_Git_mode=True)
    observed_by_id = {(row["binary"], row["name"]): row for row in rows}
    old_failed = [{"original_R29_observation": row,
                   "current_R30_observation": observed_by_id.get((row["binary"], row["name"]))}
                  for row in baseline_doc["observed_results"] if row["status"] != "PASS"]
    result = {
        "schema": "hepta.source53-r30-independent-closure.v1",
        "classification": "EVIDENCE_INCONSISTENCY" if issues else ("CLOSED_ENGINEERING_PROJECT_PASS" if pass_observed else "CLOSED_ENGINEERING_PROJECT_FAILED"),
        "source_commit": COMMIT, "source_tree": TREE, "native_HEAD": HEAD,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "integrity_errors": issues, "source_manifest": pin(source_raw), "source_readback": source_readback,
        "terminal": {"original": pin(terminal_raw), "job": JOB, "state": terminal["state"], "exit_code": terminal["exit_code"], "natural": natural},
        "phase_results": phases, "execution": parsed, "baseline": pin(baseline_raw),
        "baseline_per_binary_original_counts": baseline_doc["binary_counts"],
        "original_R29_failed_observation_not_relabelled": old_failed,
        "original_R29_gate_exit": 100, "identity_set_used_as_test_filter": False,
        "workspace_qualification": False, "finalizer_qualification_from_project_only": False,
        "all_evidence_original_pins": [{"path": name, **pin(data)} for name, data in sorted(originals.items())],
        "skip_identities_inferred": False, "host_free_space_samples_are_not_exclusive_task_cost": True,
        "runner_imported_or_executed": False, "native_Rust_metadata_fix_fmt_or_tests_executed_by_this_reader": False,
    }
    args.output.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        with (args.output / name).open("xb") as stream:
            stream.write(data)
        return {"path": name, **pin(data)}
    if parsed:
        for i, block in enumerate(parsed["failure_spans"], 1):
            save("failure-" + str(i) + ".txt", originals[PREFIX + "-tests.log"][block["byte_start"]:block["byte_end"]])
    rows_pin = save("EXECUTED-ROWS.json", (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode())
    result["independent_rows"] = rows_pin
    report_pin = save("INDEPENDENT-READBACK.json", (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"report": report_pin, "classification": result["classification"], "integrity_errors": issues}, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
