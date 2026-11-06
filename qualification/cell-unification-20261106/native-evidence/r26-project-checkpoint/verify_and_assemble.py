#!/usr/bin/env python3
"""Offline closed-r26 verification and create-only attachment assembly.

No subprocesses, network, Git commands, Rust, metadata, formatter or gate runs.
Archive originals remain immutable; new conclusions live in separate reports.
"""
from collections import Counter
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

HERE = Path(__file__).resolve().parent
WORK = HERE.parent if HERE.name == "r26-formal-preparation" else HERE.parents[4]
REL = "hepta-cell/qualification/cell-unification-20261106/native-evidence/r26-project-checkpoint"
ARCHIVE_NAME = "checkpoint-r26-closed.tar.gz"
ARCHIVE_PIN = {"bytes": 1667299, "sha256": "1c4f0b7319047291c98ccb52a97a69482247bba317a036294965533d26547683", "git_blob": "8b837b44751b5d72e52982d80d99b445883436cc"}
COMMIT = "e28b0f385ee882f842911044958b2810f62f6379"
TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
PREFIX = "native-source51-project-r26"
JOB = "1a1b1b739ee-fc05-7a70"
EXPORT_JOB = "1a1b1d0e692-fc05-7aee"
PACKAGES = ["codex-cli", "codex-exec-server", "codex-network-proxy", "codex-external-agent-migration"]
CARGO_SHA = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_SHA = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
ROOT_REVIEW_SHA = "da3ecaf9795aefee118564259fac16b13e09707ed002e0f2f95515cab69bc01d"
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
RESULT = re.compile(rb"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$")
START = re.compile(rb"^\s*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)\s*$")
SUMMARY = re.compile(rb"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+(\d+) tests run:(.*)$")


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def raw_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def exact(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, f"create-only mismatch: {path}"
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def gz(raw):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(raw)
    packed = buf.getvalue()
    assert packed[4:8] == b"\0\0\0\0" and gzip.decompress(packed) == raw
    return packed


def safe(path):
    value = PurePosixPath(path)
    assert path and not value.is_absolute() and ".." not in value.parts and "." not in value.parts
    return value


def natural_terminal(value, job, rc):
    assert value["job_id"] == job and value["exit_code"] == rc
    assert value["state"] == ("succeeded" if rc == 0 else "failed")
    assert all(value[k] is False for k in ("timed_out", "cancelled", "automatic_retry"))
    assert all(value[k] is True for k in ("output_complete", "output_durable", "terminal_publication_confirmed"))
    assert all(x is False for x in value["log_truncated"].values())
    assert all(x is None for x in value["log_errors"].values())


def parse_log(raw):
    starts, summaries, records = [], [], []
    offset = 0
    for number, raw_line in enumerate(raw.splitlines(keepends=True), 1):
        line = ANSI.sub(b"", raw_line).rstrip(b"\r\n")
        if m := START.fullmatch(line):
            starts.append({"line": number, "byte_offset": offset, "text": line.decode(), "tests": int(m[1]), "binaries": int(m[2]), "reported_skipped": int(m[3])})
        if m := SUMMARY.fullmatch(line):
            counts = {label.decode(): int(n) for n, label in re.findall(rb"(\d+) (passed|failed|timed out|skipped)", m[3])}
            summaries.append({"line": number, "byte_offset": offset, "text": line.decode(), "seconds": float(m[1]), "tests_run": int(m[2]),
                              "counts": {"PASS": counts.get("passed", 0), "FAIL": counts.get("failed", 0), "TIMEOUT": counts.get("timed out", 0)},
                              "reported_skipped": counts["skipped"]})
        if m := RESULT.fullmatch(line):
            records.append({"status": m[1].decode(), "seconds": float(m[2]), "binary": m[3].decode(), "name": m[4].decode(), "line": number, "byte_offset": offset})
        offset += len(raw_line)
    assert len(starts) == len(summaries) == 1
    start, summary = starts[0], summaries[0]
    rows = [r for r in records if start["line"] < r["line"] < summary["line"]]
    footer = [r for r in records if r["line"] > summary["line"]]
    assert len(rows) + len(footer) == len(records)
    keyed = {(r["binary"], r["name"]): r for r in rows}
    assert len(rows) == len(keyed) == start["tests"] == summary["tests_run"] == 1564
    counts = {s: sum(r["status"] == s for r in rows) for s in ("PASS", "FAIL", "TIMEOUT")}
    assert counts == summary["counts"] == {"PASS": 1562, "FAIL": 2, "TIMEOUT": 0}
    assert start["reported_skipped"] == summary["reported_skipped"] == 3
    failed = [r for r in rows if r["status"] != "PASS"]
    assert len(footer) == 2 and {(r["binary"], r["name"], r["status"]) for r in footer} == {(r["binary"], r["name"], r["status"]) for r in failed}
    assert {r["binary"].split("::", 1)[0] for r in rows} == set(PACKAGES)
    return start, summary, rows, keyed, failed, footer


def verify_sealed(output):
    manifest = json.loads((output / "ATTACHMENT-MANIFEST.json").read_bytes())
    expected = {row["path"] for row in manifest["files"]} | {"ATTACHMENT-MANIFEST.json"}
    actual = {str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()}
    assert actual == expected
    for row in manifest["files"]:
        assert pin((output / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    for row in json.loads((output / "GZIP-ROUNDTRIP.json").read_bytes())["files"]:
        packed = (output / row["path"]).read_bytes()
        assert packed[4:8] == b"\0\0\0\0" and pin(gzip.decompress(packed)) == row["uncompressed"]
    print(json.dumps({"status": "SEALED_BYTES_VERIFIED", "files": len(actual), "bytes": sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
                      "manifest": pin((output / "ATTACHMENT-MANIFEST.json").read_bytes()), "rust_executed": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closed", type=Path, default=WORK / "native-validation-results/r26-archive-closed")
    parser.add_argument("--export", type=Path, default=WORK / "native-validation-results/r26-export-closed")
    parser.add_argument("--prior", type=Path, default=WORK / "hepta-cell/qualification/cell-unification-20261106/native-evidence/r24-project-checkpoint")
    parser.add_argument("--output", type=Path, default=WORK / REL)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_sealed(args.output)
        return
    archive_raw = (args.closed / ARCHIVE_NAME).read_bytes()
    assert pin(archive_raw) == ARCHIVE_PIN
    members, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as tar:
        for member in tar.getmembers():
            safe(member.name)
            assert member.isfile() and not member.issym() and not member.islnk() and member.name not in members
            raw = tar.extractfile(member).read()
            assert len(raw) == member.size
            assert (args.closed / "original" / member.name).read_bytes() == raw
            members[member.name], modes[member.name] = raw, member.mode
    assert len(members) == 279
    index = json.loads(members["INDEX.json"])
    assert index["source_commit"] == COMMIT and index["source_tree"] == TREE and index["source_count"] == 194
    indexed = {row["path"]: row for row in index["files"]}
    assert len(indexed) == len(index["files"]) == 278 and set(indexed) == set(members) - {"INDEX.json"}
    for path, row in indexed.items():
        assert pin(members[path]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        assert modes[path] == row["mode"]  # Original tar/INDEX transport mode, not a Git mode.
    categories = dict(Counter(path.split("/", 1)[0] for path in indexed))
    assert categories == {"evidence": 33, "failure-blocks": 3, "guidance": 1, "input": 44, "locks": 2, "source": 194, "support-source": 1}
    source = json.loads(members["input/native-candidate-r26-source.json"])
    assert source["source_commit"] == COMMIT and source["source_tree"] == TREE
    files = {row["path"]: row for row in source["changed_files"]}
    assert len(files) == 194 and set("source/" + p for p in files) == {p for p in members if p.startswith("source/")}
    source_rows = []
    for path, row in sorted(files.items()):
        assert row["mode"] in ("100644", "100755")
        assert pin(members["source/" + path]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        source_rows.append({**row, "archive_member": "source/" + path, "archive_transport_mode": modes["source/" + path], "raw_and_git_blob_verified": True})
    runtime = "codex-rs/network-proxy/src/runtime.rs"
    assert runtime not in files and pin(members["support-source/" + runtime])["sha256"] == "3214446d85796e5d1c4a308ba53aab3bf7098fc18cd38cfc6f97a1cbb14d2e4f"
    assert len(members["support-source/" + runtime]) == 75473
    assert pin(members["locks/codex-rs/Cargo.lock"])["sha256"] == CARGO_SHA
    assert pin(members["locks/MODULE.bazel.lock"])["sha256"] == BAZEL_SHA
    evidence = lambda suffix: members["evidence/" + PREFIX + suffix]
    record = lambda suffix: json.loads(evidence(suffix))
    phase_data, receipts, previous_end = {}, [], None
    package_args = [value for package in PACKAGES for value in ("-p", package)]
    commands = {
        "python-runner": ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_run_nextest*.py", "-v"],
        "strict": ["just", "clippy", "--locked", *package_args, "--", "-D", "warnings"],
        "tests": ["just", "test", "--locked", *package_args, "--retries", "0"],
    }
    for phase, expected_rc in (("python-runner", 0), ("strict", 0), ("tests", 100)):
        raw, receipt = record("-" + phase + "-raw-process-result.json"), record("-" + phase + "-receipt.json")
        for value in (raw, receipt):
            assert value["source_commit"] == COMMIT and value["source_tree"] == TREE and value["phase"] == phase
            assert value["exit_code"] == expected_rc and value["command"] == commands[phase]
            assert value["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source" + ("" if phase == "python-runner" else "/codex-rs")
        for key in ("source_commit", "source_tree", "phase", "command", "cwd", "exit_code", "start_unix", "end_unix"):
            assert raw[key] == receipt[key]
        assert receipt["effective_exit_code"] == expected_rc and receipt["phase_pass"] is (expected_rc == 0)
        assert receipt["end_unix"] >= receipt["start_unix"] and abs(receipt["elapsed_seconds"] - receipt["end_unix"] + receipt["start_unix"]) < 1e-6
        assert previous_end is None or receipt["start_unix"] >= previous_end
        previous_end = receipt["end_unix"]
        assert receipt["source_manifest_sha256"] == pin(members["input/native-candidate-r26-source.json"])["sha256"]
        assert receipt["raw_process_result"] == {"path": PREFIX + "-" + phase + "-raw-process-result.json", **pin(evidence("-" + phase + "-raw-process-result.json"))}
        assert receipt["log_sha256"] == pin(evidence("-" + phase + ".log"))["sha256"]
        assert receipt["resources_sha256"] == pin(evidence("-" + phase + "-resources.txt"))["sha256"]
        assert re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", evidence("-" + phase + "-resources.txt"), re.M) == [str(expected_rc).encode()]
        for side in ("pre", "post"):
            guard = record("-" + phase + "-source-" + side + "-verification.json")
            assert guard["pass"] is True and guard["actual_tree"] == guard["expected_tree"] == TREE and guard["source_commit"] == COMMIT
            assert guard["changed_file_count"] == 194 and guard["native_head"] == HEAD and guard["changed_path_set_matches"] is True
            assert guard["unstaged_paths"] == guard["untracked_paths"] == guard["file_mismatches"] == []
            assert guard["cargo_lock_sha256"] == CARGO_SHA and guard["bazel_lock_sha256"] == BAZEL_SHA
            if side == "post":
                assert guard["gate_exit_code"] == expected_rc and guard["phase"] == phase
                assert receipt["source_postguard"] == {"path": PREFIX + "-" + phase + "-source-post-verification.json", **pin(evidence("-" + phase + "-source-post-verification.json"))}
        assert receipt["source_guards_pass"] is True and receipt["fix_fmt_executed"] is False and receipt["baseline_used_as_filter"] is False
        assert receipt["features"] == "unchanged_defaults" and receipt["filters"] == "no_additions"
        assert receipt["packages"] == ([] if phase == "python-runner" else PACKAGES)
        if expected_rc == 0:
            assert receipt["issues"] == []
        else:
            assert receipt["issues"] == [{"stage": "closed_log_acceptance", "error": "required original execution coverage/result not met"}]
        receipts.append({"path": PREFIX + "-" + phase + "-receipt.json", **pin(evidence("-" + phase + "-receipt.json"))})
        phase_data[phase] = {"original_exit": expected_rc, "effective_exit": receipt["effective_exit_code"], "elapsed_seconds": receipt["elapsed_seconds"],
                             "log": pin(evidence("-" + phase + ".log")), "raw": receipt["raw_process_result"], "receipt": receipts[-1],
                             "resources": pin(evidence("-" + phase + "-resources.txt")), "source_guards_pass": True}
    python_log = evidence("-python-runner.log")
    python_summary = re.findall(rb"^Ran (\d+) tests in ([0-9.]+)s\s*$", python_log, re.M)
    assert python_summary == [(b"32", b"59.132")] and len(re.findall(rb"^OK\s*$", python_log, re.M)) == 1
    assert not re.findall(rb"^OK \(skipped=", python_log, re.M)
    python_review = record("-python-runner-result-review.json")
    assert python_review["reported_test_count"] == 32 and python_review["reported_skipped"] == 0 and python_review["pass"] is True
    assert python_review["log"] == pin(python_log)
    log = evidence("-tests.log")
    start, summary, rows, keyed, failed, footer = parse_log(log)
    assert rows == record("-tests-test-results.json")
    review = record("-tests-result-review.json")
    assert review["log"] == pin(log) and review["counts"] == summary["counts"]
    assert review["execution_rows"] == review["unique_test_count"] == 1564 and review["reported_skipped"] == 3 and review["pass"] is False
    assert review["footer_rows_excluded"] == footer
    baseline_raw = members["input/source50-four-package-r23-baseline.json"]
    assert pin(baseline_raw)["sha256"] == "6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e"
    baseline = json.loads(baseline_raw)
    baseline_ids = {(r["binary"], r["name"]) for r in baseline["test_ids"]}
    assert len(baseline_ids) == len(baseline["test_ids"]) == 1564 and baseline_ids == set(keyed)
    assert review["baseline_missing"] == review["additional_test_ids"] == []
    assert {(r["binary"], r["name"]) for r in review["baseline_not_pass"]} == {(r["binary"], r["name"]) for r in failed}
    failure_index = json.loads(members["failure-blocks/INDEX.json"])
    assert failure_index["source_tree"] == TREE and failure_index["source_commit"] == COMMIT and failure_index["log"] == pin(log)
    failures = []
    for f in failure_index["failures"]:
        raw = members["failure-blocks/" + f["file"]]
        assert log[f["byte_offset"]:f["end_byte_offset"]] == raw
        assert pin(raw) == {k: f[k] for k in ("bytes", "sha256", "git_blob")}
        row = keyed[(f["binary"], f["name"])]
        assert row["status"] == f["status"] == "FAIL" and row["byte_offset"] == f["byte_offset"] and row["line"] == f["line"]
        assert b"    <Blocked(\n    <    NotAllowedLocal,\n    <)\n    >Allowed\n" in raw
        failures.append({**f, "seconds": row["seconds"], "observed": "Blocked(NotAllowedLocal) != Allowed", "specific_dns_outcome_recorded": False})
    assert len(failures) == 2
    terminal = record("-terminal-process-status.json")
    natural_terminal(terminal, JOB, 100)
    assert terminal["at_unix_ms"] / 1000 >= previous_end
    incomplete = record("-incomplete.json")
    assert incomplete["failed_phase"] == "tests" and incomplete["effective_exit_code"] == 100 and incomplete["completed_phase_receipts"] == receipts
    assert incomplete["subsequent_phases_started"] is False and incomplete["workspace_started"] is False and incomplete["fix_fmt_executed"] is False
    assert "evidence/" + PREFIX + "-complete.json" not in members
    assert pin(members["input/native-run-r26.py"])["sha256"] == "c46f22be2c4b71004dc086870eaf5a69efed0ee32cde47cf33a2ef818f168396"
    assert json.loads(evidence("-original-launch.json"))["job"]["id"] == JOB
    export_guard = record("-export-source-verification.json")
    assert export_guard["source_tree"] == TREE and export_guard["source_count"] == 194 and export_guard["all_source_raw_sha_gitblob_mode_verified"] is True
    assert export_guard["rust_rerun"] is False and export_guard["workspace_started"] is False and export_guard["fix_fmt_executed"] is False

    # Original r24 failure provenance remains source50 evidence; only the transition is new.
    prior_index_raw = (args.prior / "original/failure-blocks/INDEX.json").read_bytes()
    prior_index = json.loads(prior_index_raw)
    prior_log_packed = (args.prior / "original/evidence/native-source50-project-r24-tests.log.gz").read_bytes()
    prior_log = gzip.decompress(prior_log_packed)
    assert pin(prior_log) == prior_index["log"] and prior_index["counts"] == {"PASS": 1561, "FAIL": 3, "TIMEOUT": 0}
    transitions, prior_copies = [], {"failure-blocks/INDEX.json": prior_index_raw}
    for f in prior_index["failures"]:
        raw = (args.prior / "original/failure-blocks" / f["file"]).read_bytes()
        assert raw == prior_log[f["byte_offset"]:f["end_byte_offset"]]
        assert pin(raw) == {k: f[k] for k in ("bytes", "sha256", "git_blob")}
        after = keyed[(f["binary"], f["name"])]
        assert after["status"] == "PASS"
        transitions.append({"binary": f["binary"], "name": f["name"], "source50_r24": {"status": "FAIL", "log": prior_index["log"], "byte_offset": f["byte_offset"], "end_byte_offset": f["end_byte_offset"], "block": {"path": "supplemental-r24/failure-blocks/" + f["file"], **pin(raw)}}, "source51_r26": after})
        prior_copies["failure-blocks/" + f["file"]] = raw
    assert len(transitions) == 3
    preconditions = record("-preconditions.json")
    for p in preconditions["original_r24_failed_100_provenance"]:
        raw = (args.prior / "original/evidence" / p["path"]).read_bytes()
        assert pin(raw) == {k: p[k] for k in ("bytes", "sha256", "git_blob")}
        prior_copies["evidence/" + p["path"]] = raw
    assert preconditions["source_manifest"] == {"path": "native-candidate-r26-source.json", **pin(members["input/native-candidate-r26-source.json"])}
    assert preconditions["source51_bazel_lock_update_executed"] is False
    for p in preconditions["source50_lock_originals_and_outer_terminal"]:
        raw = members["input/lock-prerequisites/" + p["path"].split("/", 1)[1]]
        assert pin(raw) == {k: p[k] for k in ("bytes", "sha256", "git_blob")}
    for k in ("complete", "terminal", "source_postguard", "delta_manifest"):
        p = preconditions["source51_apply"][k]
        assert pin(members["input/apply-prerequisites/" + p["path"].split("/", 1)[1]]) == {key: p[key] for key in ("bytes", "sha256", "git_blob")}
    export_files = {p.name: p.read_bytes() for p in args.export.iterdir() if p.is_file()}
    assert len(export_files) == 10
    local_export = json.loads(export_files["LOCAL-READBACK.json"])
    for row in local_export["original_files"]:
        raw = export_files[row["local_name"]]
        assert len(raw) == row["size"] and pin(raw)["sha256"] == row["sha256"]
    export_terminal = json.loads(export_files["export-terminal-process-status.json"])
    natural_terminal(export_terminal, EXPORT_JOB, 0)
    assert export_terminal == local_export["export_terminal"]
    assert export_files["failure-blocks-INDEX.json"] == members["failure-blocks/INDEX.json"]
    assert export_files[PREFIX + "-export-source-verification.json"] == evidence("-export-source-verification.json")
    assert {k: local_export["archive"][k] for k in ("bytes", "sha256", "git_blob")} == ARCHIVE_PIN
    root_raw = (args.closed / "ROOT-ARCHIVE-READBACK.json").read_bytes()
    assert len(root_raw) == 2906 and pin(root_raw)["sha256"] == ROOT_REVIEW_SHA
    root_review = json.loads(root_raw)
    assert root_review["archive"] == ARCHIVE_PIN and root_review["counts"] == summary["counts"] and root_review["terminal_unique_results"] == 1564
    for phase, result in phase_data.items():
        assert root_review["phase_results"][phase]["log"] == result["log"]
        assert root_review["phase_results"][phase]["elapsed_seconds"] == result["elapsed_seconds"]
    assert [(r["binary"], r["name"], r["seconds"]) for r in root_review["original_r24_three_failures_now_pass"]] == [(r["binary"], r["name"], r["source51_r26"]["seconds"]) for r in transitions]

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    mapping, gzip_records = [], []
    def attach(source_path, dest, raw, compress=True):
        stored = raw
        encoding = "identity"
        if compress and len(raw) >= 65536 and not dest.endswith((".gz", ".tar")):
            raw.decode("utf-8")
            stored, dest, encoding = gz(raw), dest + ".gz", "gzip-mtime-0"
            gzip_records.append({"path": dest, "stored": pin(stored), "uncompressed": pin(raw), "mtime": 0, "roundtrip_exact": True})
        exact(output / dest, stored)
        mapping.append({"source": source_path, "source_pin": pin(raw), "destination": dest, "stored_pin": pin(stored), "encoding": encoding})
        return dest
    attach(str(args.closed / ARCHIVE_NAME), ARCHIVE_NAME, archive_raw, False)
    member_mapping = []
    for path, raw in sorted(members.items()):
        if path.startswith(("source/", "locks/", "support-source/")):
            member_mapping.append({"archive_member": path, **pin(raw), "archive_transport_mode": modes[path], "storage": "unchanged_archive_member_only", "archive": ARCHIVE_NAME})
        else:
            dest = attach(str(args.closed / "original" / path), "original/" + path, raw)
            member_mapping.append({"archive_member": path, **pin(raw), "archive_transport_mode": modes[path], "storage": "archive_and_exact_attachment", "destination": dest})
    attach(str(args.closed / "ROOT-ARCHIVE-READBACK.json"), "root-review/ROOT-ARCHIVE-READBACK.json", root_raw)
    for name, raw in sorted(export_files.items()):
        attach(str(args.export / name), "export-custody/" + name, raw)
    for path, raw in sorted(prior_copies.items()):
        attach(str(args.prior / "original" / path), "supplemental-r24/" + path, raw)
    attach(str(Path(__file__).resolve()), "verify_and_assemble.py", Path(__file__).read_bytes(), False)
    attach("derived:archive-source-raw-and-manifest-git-mode-readback", "readback/SOURCE-FILES.json", raw_json(source_rows))
    attach("derived:full-r26-log-reparsed-result-and-r24-transitions", "readback/R24-FAILURE-TRANSITIONS.json", raw_json({
        "source_before": {"commit": prior_index["source_commit"], "tree": prior_index["source_tree"]},
        "source_after": {"commit": COMMIT, "tree": TREE}, "original_r24_all_three_failures_observed_pass": True,
        "r24_original_log": {"original_formal_path": str(args.prior.relative_to(WORK)) + "/original/evidence/native-source50-project-r24-tests.log.gz", "stored_pin": pin(prior_log_packed), "uncompressed_pin": pin(prior_log)},
        "transitions": transitions, "source52_candidate_or_result_used": False,
    }))
    per_package = {p: {s: sum(r["binary"].split("::", 1)[0] == p and r["status"] == s for r in rows) for s in ("PASS", "FAIL", "TIMEOUT")} for p in PACKAGES}
    assert per_package == review["per_package"]
    derived = {
        "schema": "hepta.r26-independent-closed-readback.v1", "classification": "ENGINEERING_GATE_FAILED_100",
        "archive": ARCHIVE_PIN, "archive_members": 279, "indexed_members": 278, "archive_categories": categories,
        "archive_all_bytes_modes_and_safe_regular_members_verified": True,
        "all_extracted_original_bytes_equal_archive": True,
        "source_commit": COMMIT, "source_tree": TREE, "native_head": HEAD,
        "source_count": 194, "source_raw_sha_and_git_blob_verified": True,
        "source_git_modes": "Bound by the complete original manifest and original native guards; transport mode is independent.",
        "offline_full_repository_tree_reconstructed_here": False,
        "source_tree_evidence": "Original per-phase/write-tree/complete-file native guards, root source publication and archived manifest; no new checkout or execution claim.",
        "cargo_lock_sha256": CARGO_SHA, "bazel_lock_sha256": BAZEL_SHA,
        "runtime_support": {"archive_member": "support-source/" + runtime, **pin(members["support-source/" + runtime]), "not_in_194_changed_manifest": True, "is_original_source51_not_source52_candidate": True},
        "original_runner": pin(members["input/native-run-r26.py"]), "phases": phase_data,
        "python_unittest_summary": {"tests": 32, "skipped": 0, "seconds": 59.132, "status": "OK"},
        "starting": start, "summary": summary, "unique_test_count": len(keyed), "execution_rows": len(rows),
        "counts": summary["counts"], "per_package": per_package, "reported_skipped": 3,
        "skip_identities_inferred": False, "original_rows_exactly_reproduced_from_full_log": True,
        "original_rows": {"archive_member": "evidence/" + PREFIX + "-tests-test-results.json", **pin(evidence("-tests-test-results.json"))},
        "footer_rows_excluded": footer, "baseline": pin(baseline_raw), "baseline_count": len(baseline_ids),
        "baseline_binary_name_set_exact": True, "baseline_missing": [], "baseline_added": [], "baseline_used_as_filter": False,
        "failures": failures, "failure_blocks_exact_original_byte_spans": True,
        "r24_original_three_failures_now_pass": [{"binary": r["binary"], "name": r["name"], **r["source51_r26"]} for r in transitions],
        "original_outer_terminal": {"job_id": JOB, "state": terminal["state"], "exit_code": 100, "timed_out": False, "cancelled": False, "pin": pin(evidence("-terminal-process-status.json"))},
        "export_only_terminal": {"job_id": EXPORT_JOB, "exit_code": 0, "pin": pin(export_files["export-terminal-process-status.json"]), "not_a_rust_gate": True},
        "r27_started": False, "r25_historical_template_remains_unexecuted": True,
        "fix_fmt_executed": False, "rust_rerun_by_readback": False,
        "source50_lock_result_is_historical_and_not_new_source51_lock_execution": True,
        "source52_not_qualified_by_this_group": True, "science": "HOLD", "authority": "DENY_ALL",
    }
    exact(output / "INDEPENDENT-READBACK.json", raw_json(derived))
    exact(output / "ORIGINAL-MEMBER-MAPPING.json", raw_json({"archive": {"path": ARCHIVE_NAME, **ARCHIVE_PIN}, "members": member_mapping, "total_regular_members": 279}))
    closure = {
        "schema": "hepta.r26-project-attachment-closure.v1", "status": "CLOSED_ORIGINAL_GATE_FAILED_100",
        "source_commit": COMMIT, "source_tree": TREE, "native_head": HEAD, "source_count": 194,
        "original_job_id": JOB, "original_test_exit": 100, "original_outer_exit": 100,
        "phase_original_exits": {p: d["original_exit"] for p, d in phase_data.items()},
        "counts": {"unique": 1564, **summary["counts"], "reported_skipped": 3},
        "r24_three_failed_ids_pass_in_r26": True,
        "archive": {"path": ARCHIVE_NAME, **ARCHIVE_PIN, "registered_git_blob_provided_by_root": True},
        "independent_readback": {"path": "INDEPENDENT-READBACK.json", **pin((output / "INDEPENDENT-READBACK.json").read_bytes())},
        "root_original_readback": {"path": "root-review/ROOT-ARCHIVE-READBACK.json", **pin(root_raw)},
        "source_and_locks_storage": "All 194 source files, raw dual locks and unchanged runtime support are retained inside the exact archive, with per-member mapping; not copied as a second source tree.",
        "metadata_boundary": "This original command selected four packages; it is not fresh default-workspace metadata or a complete workspace result.",
        "export_zero_is_not_test_pass": True, "source52_candidates_included": False,
        "r25_and_r27_not_started": True, "fix_fmt_executed": False,
        "science": "HOLD", "authority": "DENY_ALL",
        "closure_gaps": [],
        "limits": ["Reported skip total is retained without inventing per-ID SKIP records.", "NotAllowedLocal was observed; underlying DNS answer/error/deadline was not recorded.", "Tar modes are transport permissions, not Git source modes.", "No new full-tree offline reconstruction or Rust execution was performed by this attachment readback.", "Historical PASS and source51 failure do not transfer qualification to source52."],
    }
    exact(output / "CLOSURE.json", raw_json(closure))
    readme = f'''# r26 原四包门：完整失败证据

**工程门 FAILED100；科学 HOLD；权限 DENY_ALL。** 本组绑定 source51 commit `{COMMIT}`、staged tree `{TREE}`，194 个变更路径。原生 HEAD 为 framework `bef6fa…`，Git 对象身份不冒充 checkout。没有运行新测试或改动源码。

| 原阶段 | 原返回码 | 原进程总秒数 | 结果 |
| --- | ---: | ---: | --- |
| Python runner | 0 | {phase_data['python-runner']['elapsed_seconds']} | unittest 报 32 项、0 skip、OK；自报执行 59.132 秒 |
| 四包 strict | 0 | {phase_data['strict']['elapsed_seconds']} | 原命令通过，source/双锁守卫通过 |
| 四包完整测试 | 100 | {phase_data['tests']['elapsed_seconds']} | nextest 执行 84.109 秒，1564 unique＝1562 PASS＋2 FAIL，0 TIMEOUT；另报 3 skipped |

四包为 CLI、exec-server、network-proxy、external-agent-migration。原 1564 个 binary/name 全出现，无新增 filter；原日志末尾两条失败复述已排除，未重复计数。Python/strict 的成功不把完整项目门变成 PASS。r25、r27 旧惰性工作区门未启动，fix/fmt 未执行。

## 实际失败与旧例变化

| source51/r26 原失败 | 原耗时 | 原观察 |
| --- | ---: | --- |
| `runtime::tests::host_blocked_subdomain_wildcards_exclude_apex` | 5.089 秒 | `Blocked(NotAllowedLocal)`，预期 `Allowed` |
| `runtime::tests::host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist` | 5.267 秒 | 同上 |

完整错误块保存在 [failure-1.txt](original/failure-blocks/failure-1.txt) 与 [failure-2.txt](original/failure-blocks/failure-2.txt)，逐字对应原 log 的 211476..212277 与 212277..213194 byte spans。原件没有给出具体 DNS 回答、resolver 错误或 timeout，不能凭测试耗时推断根因。archive 中 runtime.rs 是 75473 B 的原 source51 support source；source52 的修复候选没有混入此组。

原 r24 三项失败在本轮均实际 PASS：两个 exec-server sandbox/bwrap 例为 1.424 和 0.100 秒；DetectTls policy 例为 0.006 秒。逐 ID、原失败块和新 PASS 行在 [R24-FAILURE-TRANSITIONS.json](readback/R24-FAILURE-TRANSITIONS.json) 中分别绑定两个源码，原 r24 FAILED100 不改写。

## 原件与复算

- [CLOSURE.json](CLOSURE.json) 与 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 是本次新读回结论。
- [checkpoint-r26-closed.tar.gz](checkpoint-r26-closed.tar.gz) 保留 279 个 regular 原成员：194 source、33 evidence、44 input、3 failure-blocks、1 guidance、2 locks、1 support-source 和 INDEX。整个 archive、278 条 INDEX、所有 raw SHA/Git blob、解出字节均逐项核对。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json) 覆盖每个成员；194 source、原双锁与 support-source 从原 archive 读取，没有复制第二棵源码目录。原 INDEX 和 tar 的 transport mode 与源 manifest 的 Git mode 分别处理。
- original/ 内保留完整 log、结果 rows、raw rc、receipt、resources、环境、守卫、原 runner、baseline 和 apply/lock 前置原件；大 UTF-8 文本用 mtime=0 gzip 无损保存，映射记录解压前后完整 pins。
- export-custody/ 保留唯一只读封包任务的原控制回执。其自然退出 0 仅说明归档成功，原 Rust 测试及其外层任务仍自然退出 100。
- root-review/ 的原根报告按原字节保留；supplemental-r24/ 仅补原历史失败与前置证明，不改变旧正式组。

运行 `python3 verify_and_assemble.py --verify-only` 可离线核对本组最终 manifest 和 gzip 往返；它不会执行 runner、Git、Rust、网络、metadata 或 formatter。完整 scope 及局限见 CLOSURE，科学结果仍 HOLD，后续源码不得继承本轮工程资格。
'''
    exact(output / "README.md", readme.encode())
    exact(output / "GZIP-ROUNDTRIP.json", raw_json({"schema": "hepta.lossless-gzip-readback.v1", "files": gzip_records}))
    exact(output / "SOURCE-DESTINATION-MAPPING.json", raw_json({"schema": "hepta.exact-attachment-mapping.v1", "files": mapping, "source_file_count": len(mapping), "original_members": "ORIGINAL-MEMBER-MAPPING.json"}))
    binaries = []
    for path in sorted(output.rglob("*.gz")):
        rel = str(path.relative_to(output))
        raw = path.read_bytes()
        known = ARCHIVE_PIN["git_blob"] if rel == ARCHIVE_NAME else ("09aa5469689cc2d0af5402b506997a3b77f188a4" if rel == "original/input/source51-apply-input.tar.gz" else None)
        if known:
            assert pin(raw)["git_blob"] == known
        binaries.append({"path": rel, "repository_path": "qualification/cell-unification-20261106/native-evidence/r26-project-checkpoint/" + rel, **pin(raw), "existing_registered_git_blob": known, "action": "reuse_known_blob" if known else "root_check_or_upload_by_exact_blob", "uploaded_by_this_task": False})
    exact(output / "BINARY-PLAN.json", raw_json({"schema": "hepta.binary-attachment-plan.v1", "files": binaries, "count": len(binaries), "git_upload_performed": False}))
    final_files = [{"path": str(p.relative_to(output)), **pin(p.read_bytes())} for p in sorted(output.rglob("*")) if p.is_file() and p.name != "ATTACHMENT-MANIFEST.json"]
    exact(output / "ATTACHMENT-MANIFEST.json", raw_json({"schema": "hepta.r26-project-attachment-manifest.v1", "source_commit": COMMIT, "source_tree": TREE, "classification": "ORIGINAL_GATE_FAILED_100", "files": final_files, "file_count_excluding_manifest": len(final_files), "stored_bytes_excluding_manifest": sum(x["bytes"] for x in final_files)}))
    verify_sealed(output)
    print(json.dumps({"closure": pin((output / 'CLOSURE.json').read_bytes()), "independent": pin((output / 'INDEPENDENT-READBACK.json').read_bytes()), "binary_count": len(binaries), "mapping_count": len(mapping), "archive_members": 279, "source_raw_rows": 194, "engineering_gate": "FAILED_100", "rust_rerun": False}, indent=2))


if __name__ == "__main__":
    main()
