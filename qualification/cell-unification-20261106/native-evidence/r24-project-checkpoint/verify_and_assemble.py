#!/usr/bin/env python3
"""Offline r24 archive/log readback and exact-byte formal attachment assembly.

This program never invokes Rust, Git, network tools, test runners or native jobs.
Raw native phase files retain their historical fields. New conclusions are separate.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


HERE = Path(__file__).resolve().parent
WORK = HERE.parents[4]
PREFIX = "native-source50-project-r24"
SOURCE_COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
SOURCE_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
ARCHIVE_SHA256 = "30b71fe512d8e33fdc029942e9987463ff12f98bc3c945d9322176865826f819"
ARCHIVE_BLOB = "b38d2e96c943c68cd0f37d413f01b3b6a424791a"
ARCHIVE_BYTES = 1629778
PRIOR_BLOCKS_SHA256 = "7973eebdabb440199c65e3c2b27229c43a3d3e047d2dd3e9d135234cbcc286a4"
PACKAGES = ["codex-cli", "codex-exec-server", "codex-network-proxy", "codex-external-agent-migration"]
RESULT = re.compile(rb"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$")
SUMMARY = re.compile(rb"^\s*Summary \[\s*([0-9.]+)s\] (\d+) tests run:(.*)$")
STARTING = re.compile(rb"^\s*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)\s*$")


def pin(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def raw_json(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def deterministic_gzip(raw: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", filename="", mtime=0, compresslevel=9) as handle:
        handle.write(raw)
    result = buf.getvalue()
    assert result[4:8] == b"\0\0\0\0" and gzip.decompress(result) == raw
    return result


def exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, f"Refusing different existing bytes: {path}"
    else:
        with path.open("xb") as handle:
            handle.write(data)


def json_load(members: dict[str, bytes], name: str):
    return json.loads(members[name])


def parse_results(log: bytes) -> dict:
    starts, summaries, rows, footer = [], [], [], []
    offset = 0
    for number, raw_line in enumerate(log.splitlines(keepends=True), 1):
        line = raw_line.rstrip(b"\r\n")
        if match := STARTING.fullmatch(line):
            starts.append({"line": number, "byte_offset": offset, "text": line.decode(), "tests": int(match[1]), "binaries": int(match[2]), "reported_skipped": int(match[3])})
        if match := SUMMARY.fullmatch(line):
            assert len(summaries) == 0
            fields = dict((name.decode(), int(count)) for count, name in re.findall(rb"(\d+) (passed|failed|timed out|skipped)", match[3]))
            summaries.append({"line": number, "byte_offset": offset, "text": line.decode(), "seconds": float(match[1]), "tests_run": int(match[2]), "counts": {"PASS": fields.get("passed", 0), "FAIL": fields.get("failed", 0), "TIMEOUT": fields.get("timed out", 0)}, "reported_skipped": fields["skipped"]})
        if match := RESULT.fullmatch(line):
            item = {"status": match[1].decode(), "seconds": float(match[2]), "binary": match[3].decode(), "name": match[4].decode(), "line": number, "byte_offset": offset}
            (footer if summaries else rows).append(item)
        offset += len(raw_line)
    assert len(starts) == len(summaries) == 1
    assert starts[0]["byte_offset"] < rows[0]["byte_offset"] < summaries[0]["byte_offset"]
    assert len({(r["binary"], r["name"]) for r in rows}) == len(rows)
    counts = {key: sum(r["status"] == key for r in rows) for key in ("PASS", "FAIL", "TIMEOUT")}
    assert counts == summaries[0]["counts"]
    assert len(rows) == starts[0]["tests"] == summaries[0]["tests_run"] == 1564
    assert starts[0]["reported_skipped"] == summaries[0]["reported_skipped"] == 3
    assert counts == {"PASS": 1561, "FAIL": 3, "TIMEOUT": 0}
    assert [(r["status"], r["binary"], r["name"]) for r in footer] == [(r["status"], r["binary"], r["name"]) for r in rows if r["status"] != "PASS"]
    return {"starting": starts[0], "summary": summaries[0], "rows": rows, "footer_rows_excluded": footer, "counts": counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closed", type=Path, default=WORK / "native-validation-results/r24-archive-closed")
    parser.add_argument("--prior", type=Path, default=WORK / "native-validation-results/recovered-r23-closed-blocks")
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    output = args.output
    archive_path = args.closed / "checkpoint-r24-closed.tar.gz"
    archive_raw = archive_path.read_bytes()
    assert pin(archive_raw) == {"bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA256, "git_blob": ARCHIVE_BLOB}
    member_bytes, member_info = {}, {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as tar:
        for item in tar.getmembers():
            relative = PurePosixPath(item.name)
            assert item.isfile() and not item.issym() and not item.islnk()
            assert not relative.is_absolute() and ".." not in relative.parts and str(relative) == item.name
            assert item.name not in member_bytes
            data = tar.extractfile(item).read()
            assert len(data) == item.size
            member_bytes[item.name] = data
            member_info[item.name] = {"archive_member": item.name, "transport_mode_decimal": item.mode, **pin(data)}
    assert len(member_bytes) == 249
    index = json_load(member_bytes, "INDEX.json")
    assert index["source_commit"] == SOURCE_COMMIT and index["source_tree"] == SOURCE_TREE and index["source_count"] == 194
    assert len(index["files"]) == 248 and len({r["path"] for r in index["files"]}) == 248
    assert set(member_bytes) == {r["path"] for r in index["files"]} | {"INDEX.json"}
    for row in index["files"]:
        data = member_bytes[row["path"]]
        assert pin(data) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        assert member_info[row["path"]]["transport_mode_decimal"] == row["mode"]
    # Verify the supplied safe extraction too, without changing any of its files.
    extracted = args.closed / "original"
    assert {p.relative_to(extracted).as_posix() for p in extracted.rglob("*") if p.is_file()} == set(member_bytes)
    for path, raw in member_bytes.items():
        local = extracted / path
        assert not local.is_symlink() and local.read_bytes() == raw

    source_raw = member_bytes["input/native-candidate-r24-source.json"]
    assert pin(source_raw)["sha256"] == "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0"
    source = json.loads(source_raw)
    assert source["source_commit"] == SOURCE_COMMIT and source["source_tree"] == SOURCE_TREE
    assert len(source["changed_files"]) == 194
    source_rows = []
    for row in source["changed_files"]:
        name = "source/" + row["path"]
        observed = pin(member_bytes[name])
        assert observed == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        assert row["mode"] in ("100644", "100755")
        source_rows.append({"path": row["path"], "archive_member": name, "original_git_mode_from_fixed_source_manifest": row["mode"], "archive_transport_mode_decimal": member_info[name]["transport_mode_decimal"], **observed})
    assert {r["archive_member"] for r in source_rows} == {name for name in member_bytes if name.startswith("source/")}
    for path, key in (("codex-rs/Cargo.lock", "cargo_lock_sha256"), ("MODULE.bazel.lock", "bazel_lock_sha256")):
        assert pin(member_bytes[f"locks/{path}"])["sha256"] == source[key]
    assert set(r["transport_mode_decimal"] for r in member_info.values()) == {0o600}

    ev = lambda suffix: f"evidence/{PREFIX}-{suffix}"
    env = json_load(member_bytes, ev("environment.json"))
    pre = json_load(member_bytes, ev("preconditions.json"))
    assert env["source_tree"] == pre["source_tree"] == SOURCE_TREE
    assert env["source_commit"] == pre["source_commit"] == SOURCE_COMMIT
    assert env["source_manifest_sha256"] == pin(source_raw)["sha256"]
    assert pre["source_manifest"] == {"path": "native-candidate-r24-source.json", **pin(source_raw)}
    for source_item in pre["lock_originals_and_outer_terminal"]:
        data = member_bytes["input/lock-prerequisites/" + PurePosixPath(source_item["path"]).name]
        assert pin(data) == {key: source_item[key] for key in ("bytes", "sha256", "git_blob")}
    assert json_load(member_bytes, "input/lock-prerequisites/terminal-process-status.json")["exit_code"] == 0

    phases = {}
    expected_codes = {"python-runner": 0, "strict": 0, "tests": 100}
    for phase, code in expected_codes.items():
        receipt = json_load(member_bytes, ev(f"{phase}-receipt.json"))
        raw = json_load(member_bytes, ev(f"{phase}-raw-process-result.json"))
        assert receipt["source_tree"] == raw["source_tree"] == SOURCE_TREE
        assert receipt["source_commit"] == raw["source_commit"] == SOURCE_COMMIT
        assert receipt["source_manifest_sha256"] == pin(source_raw)["sha256"]
        assert receipt["exit_code"] == receipt["effective_exit_code"] == raw["exit_code"] == code
        assert receipt["phase_pass"] == (code == 0)
        assert receipt["command"] == raw["command"] and receipt["cwd"] == raw["cwd"]
        assert receipt["start_unix"] == raw["start_unix"] and receipt["end_unix"] == raw["end_unix"]
        assert receipt["elapsed_seconds"] == raw["end_unix"] - raw["start_unix"]
        assert receipt["source_guards_pass"] and not receipt["fix_fmt_executed"] and not receipt["baseline_used_as_filter"]
        assert pin(member_bytes[ev(f"{phase}.log")])["sha256"] == receipt["log_sha256"]
        resources = member_bytes[ev(f"{phase}-resources.txt")]
        assert pin(resources)["sha256"] == receipt["resources_sha256"]
        assert int(re.search(rb"^\s*Exit status: (\d+)\s*$", resources, re.M)[1]) == code
        for field in ("raw_process_result", "source_postguard", "acceptance_readback"):
            record = receipt[field]
            if record is not None:
                assert pin(member_bytes["evidence/" + record["path"]]) == {key: record[key] for key in ("bytes", "sha256", "git_blob")}
        for when in ("pre", "post"):
            guard = json_load(member_bytes, ev(f"{phase}-source-{when}-verification.json"))
            assert guard["pass"] and guard["actual_tree"] == guard["expected_tree"] == SOURCE_TREE
            assert guard["source_commit"] == SOURCE_COMMIT and guard["changed_file_count"] == 194
            assert not guard["unstaged_paths"] and not guard["untracked_paths"] and not guard["file_mismatches"]
            assert guard["cargo_lock_sha256"] == source["cargo_lock_sha256"] and guard["bazel_lock_sha256"] == source["bazel_lock_sha256"]
            if when == "post":
                assert guard["gate_exit_code"] == code
        phases[phase] = {"command": receipt["command"], "cwd": receipt["cwd"], "raw_exit_code": code, "effective_exit_code": code, "elapsed_seconds_including_build": receipt["elapsed_seconds"], "phase_pass": receipt["phase_pass"], "log": pin(member_bytes[ev(f"{phase}.log")]), "resources": pin(resources), "source_guards_pass": True}
    selectors = [x for package in PACKAGES for x in ("-p", package)]
    assert phases["strict"]["command"] == ["just", "clippy", "--locked", *selectors, "--", "-D", "warnings"]
    assert phases["tests"]["command"] == ["just", "test", "--locked", *selectors, "--retries", "0"]
    assert phases["python-runner"]["command"] == ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_run_nextest*.py", "-v"]

    terminal = json_load(member_bytes, ev("terminal-process-status.json"))
    incomplete = json_load(member_bytes, ev("incomplete.json"))
    assert terminal["exit_code"] == 100 and terminal["state"] == "failed" and terminal["output_durable"] and terminal["output_complete"]
    assert not terminal["timed_out"] and not terminal["cancelled"] and not terminal["automatic_retry"]
    assert terminal["terminal_publication_confirmed"] and terminal["job_id"] == "1a1b17f112c-fc05-792a"
    assert incomplete["effective_exit_code"] == 100 and incomplete["failed_phase"] == "tests"
    assert not incomplete["subsequent_phases_started"] and not incomplete["workspace_started"] and not incomplete["fix_fmt_executed"]
    for record in incomplete["completed_phase_receipts"]:
        assert pin(member_bytes["evidence/" + record["path"]]) == {key: record[key] for key in ("bytes", "sha256", "git_blob")}
    process_read = json_load(member_bytes, ev("original-process-read.json"))
    assert process_read["job_id"] == terminal["job_id"]
    for stream in ("stdout", "stderr"):
        payload = bytes.fromhex(process_read[stream]["bytes_hex"])
        assert payload == member_bytes[ev(f"original-{stream}.txt")]
        assert payload.decode() == process_read[stream]["text"]
        assert len(payload) == terminal["log_bytes"][stream]["stored"]

    pylog = member_bytes[ev("python-runner.log")]
    ran = re.findall(rb"^Ran (\d+) tests in ([0-9.]+)s\s*$", pylog, re.M)
    assert len(ran) == 1 and int(ran[0][0]) == 32 and re.search(rb"^OK\s*$", pylog, re.M)
    assert not re.search(rb"^FAILED|^OK \(skipped=|\.\.\. skipped", pylog, re.M)
    python_ids = re.findall(rb"^test_\S+ \(([^)]+)\) \.\.\. ", pylog, re.M)
    assert len(python_ids) == len(set(python_ids)) == 32
    python_modules = Counter(x.decode().split(".")[0] for x in python_ids)
    assert python_modules == {"test_run_nextest": 10, "test_run_nextest_helpers": 22}

    log = member_bytes[ev("tests.log")]
    parsed = parse_results(log)
    rows = parsed["rows"]
    assert rows == json_load(member_bytes, ev("tests-test-results.json"))
    by_id = {(r["binary"], r["name"]): r for r in rows}
    baseline_raw = member_bytes["input/source50-four-package-r23-baseline.json"]
    baseline = json.loads(baseline_raw)
    assert pin(baseline_raw)["sha256"] == "6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e"
    assert baseline["identity_key"] == ["binary", "name"] and baseline["count"] == 1564 and baseline["packages"] == PACKAGES
    baseline_ids = {(r["binary"], r["name"]) for r in baseline["test_ids"]}
    assert len(baseline_ids) == 1564 and baseline_ids == set(by_id)
    package_counts = {package: {status: sum(r["binary"].split("::", 1)[0] == package and r["status"] == status for r in rows) for status in ("PASS", "FAIL", "TIMEOUT")} for package in PACKAGES}
    native_review = json_load(member_bytes, ev("tests-result-review.json"))
    assert native_review["counts"] == parsed["counts"] and native_review["per_package"] == package_counts
    assert native_review["footer_rows_excluded"] == parsed["footer_rows_excluded"]
    assert not native_review["baseline_missing"] and not native_review["additional_test_ids"] and not native_review["baseline_used_as_filter"]

    failure_index = json_load(member_bytes, "failure-blocks/INDEX.json")
    assert failure_index["log"] == pin(log)
    failures = []
    for idx, row in enumerate(rows):
        if row["status"] == "PASS":
            continue
        end = rows[idx + 1]["byte_offset"] if idx + 1 < len(rows) else parsed["summary"]["byte_offset"]
        block = log[row["byte_offset"]:end]
        native = next(x for x in failure_index["failures"] if (x["binary"], x["name"]) == (row["binary"], row["name"]))
        assert native["byte_offset"] == row["byte_offset"] and native["end_byte_offset"] == end
        assert native["line"] == row["line"] and block == member_bytes["failure-blocks/" + native["file"]]
        assert pin(block) == {key: native[key] for key in ("bytes", "sha256", "git_blob")}
        failures.append({**row, "end_byte_offset": end, "block": {"archive_member": "failure-blocks/" + native["file"], **pin(block)}})
    assert len(failures) == 3

    prior_raw = (args.prior / "native-workspace-r23-closed-failure-blocks.json").read_bytes()
    assert len(prior_raw) == 18716 and pin(prior_raw)["sha256"] == PRIOR_BLOCKS_SHA256
    prior_recovery_raw = (args.prior / "RECOVERY-READBACK.json").read_bytes()
    prior_recovery = json.loads(prior_recovery_raw)
    assert prior_recovery["sha256"] == PRIOR_BLOCKS_SHA256 and prior_recovery["size"] == 18716 and prior_recovery["eof"]
    prior = json.loads(prior_raw)
    assert isinstance(prior, list) and len(prior) == 8 and Counter(x["status"] for x in prior) == {"FAIL": 7, "TIMEOUT": 1}
    transitions = []
    for old in prior:
        old_block = old["text"].encode()
        assert len(old_block) == old["end_byte"] - old["start_byte"] and pin(old_block)["sha256"] == old["sha256"]
        now = by_id[(old["binary"], old["name"])]
        transitions.append({"binary": old["binary"], "name": old["name"], "r23_status": old["status"], "r23_block": {"start_byte": old["start_byte"], "end_byte": old["end_byte"], "sha256": old["sha256"]}, "r24": now})
    assert Counter(x["r24"]["status"] for x in transitions) == {"PASS": 6, "FAIL": 2}
    prior_ids = {(x["binary"], x["name"]) for x in prior}
    new_failure = [x for x in failures if (x["binary"], x["name"]) not in prior_ids]
    assert len(new_failure) == 1 and new_failure[0]["name"] == "http_proxy::tests::http_connect_accept_defers_brokered_host_mitm_until_protocol_detection"

    root_archive_raw = (args.closed / "ROOT-ARCHIVE-READBACK.json").read_bytes()
    root_results_raw = (args.closed / "ROOT-EXECUTED-RESULTS.json").read_bytes()
    root_archive = json.loads(root_archive_raw)
    assert root_archive["archive"] == pin(archive_raw)
    assert root_archive["counts"] == parsed["counts"] and root_archive["unique_executed"] == 1564
    root_results = json.loads(root_results_raw)
    assert [{"result": r["status"], "seconds": f"{r['seconds']:.3f}", "binary": r["binary"], "test": r["name"]} for r in rows] == root_results

    # All validation above precedes attachment assembly. No supplied original is rewritten.
    exact(output / "checkpoint-r24-closed.tar.gz", archive_raw)
    copies, compressed, binaries = [], [], []
    archive_pin = {"path": "checkpoint-r24-closed.tar.gz", **pin(archive_raw), "kind": "original_archive", "already_uploaded_git_blob_reported_by_root": ARCHIVE_BLOB}
    binaries.append(archive_pin)

    def attach(label: str, destination: str, data: bytes, compress: bool = False) -> str:
        stored = deterministic_gzip(data) if compress else data
        path = destination + (".gz" if compress else "")
        exact(output / path, stored)
        mapping = {"original": label, "destination": path, "encoding": "gzip-mtime-0" if compress else "exact-bytes", "original_pin": pin(data), "stored_pin": pin(stored)}
        copies.append(mapping)
        if compress:
            compressed.append(mapping)
            binaries.append({"path": path, **pin(stored), "kind": "deterministic_gzip", "decompressed": pin(data), "gzip_mtime": 0, "decompression_exact": True})
        elif path.endswith(".tar.gz"):
            binaries.append({"path": path, **pin(stored), "kind": "original_nested_archive", "existing_blob_may_be_reused_by_root": True})
        return path

    member_mappings = []
    for name in sorted(member_bytes):
        data = member_bytes[name]
        if name == "INDEX.json" or name.startswith(("evidence/", "input/", "failure-blocks/", "guidance/")):
            compress = len(data) >= 65536 and not name.endswith(".gz")
            if compress:
                data.decode("utf-8")
            stored_name = attach("archive:" + name, "original/" + name, data, compress)
        else:
            stored_name = None
        member_mappings.append({**member_info[name], "standalone_attachment": stored_name, "archive_copy": "checkpoint-r24-closed.tar.gz", "archive_member": name})
    attach("root:ROOT-ARCHIVE-READBACK.json", "root-review/ROOT-ARCHIVE-READBACK.json", root_archive_raw)
    attach("root:ROOT-EXECUTED-RESULTS.json", "root-review/ROOT-EXECUTED-RESULTS.json", root_results_raw, True)
    attach("closed-r23:failure-blocks", "supplemental-r23/native-workspace-r23-closed-failure-blocks.json", prior_raw)
    attach("closed-r23:recovery-receipt", "supplemental-r23/RECOVERY-READBACK.json", prior_recovery_raw)
    if output.resolve() != HERE:
        exact(output / "verify_and_assemble.py", Path(__file__).read_bytes())

    def emit(name: str, value) -> None:
        exact(output / name, raw_json(value))

    exact(output / "readback/EXECUTED-RESULTS.json.gz", deterministic_gzip(raw_json(rows)))
    binaries.append({"path": "readback/EXECUTED-RESULTS.json.gz", **pin((output / "readback/EXECUTED-RESULTS.json.gz").read_bytes()), "kind": "deterministic_gzip_derived_readback", "decompressed": pin(raw_json(rows)), "gzip_mtime": 0, "decompression_exact": True})
    emit("readback/SOURCE-FILES.json", {"schema": "hepta.r24-source-bytes-readback.v1", "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE, "files": source_rows, "independent_full_git_tree_rebuild_performed": False, "git_mode_boundary": "Original Git modes are preserved from the fixed native source manifest. Every archive transport mode is 0600; these transport bits are not substituted for Git file modes."})
    emit("readback/R23-FAILURE-TRANSITIONS.json", {"schema": "hepta.r23-to-r24-closed-failure-transition.v1", "prior_source_commit": baseline["source_commit"], "prior_source_tree": baseline["source_tree"], "prior_failure_file": {"path": "supplemental-r23/native-workspace-r23-closed-failure-blocks.json", **pin(prior_raw)}, "current_source_commit": SOURCE_COMMIT, "current_source_tree": SOURCE_TREE, "transitions": transitions, "prior_nonpassing_now_pass": 6, "prior_nonpassing_still_fail": 2, "current_failure_not_in_prior_eight": new_failure, "prior_full_workspace_log_not_reparsed_in_this_report": True, "current_full_log_independently_reparsed": True})
    readback = {
        "schema": "hepta.r24-independent-formal-readback.v1",
        "status": "EVIDENCE_VERIFIED_ENGINEERING_GATE_FAILED",
        "script": {"path": "verify_and_assemble.py", **pin(Path(__file__).read_bytes())},
        "archive": archive_pin,
        "archive_regular_members": 249, "original_index_rows": 248,
        "all_archive_and_extracted_bytes_verified": True,
        "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE,
        "source_files_all_raw_sha256_and_git_blobs_verified": 194,
        "transport_modes_not_conflated_with_git_modes": True,
        "independent_full_git_tree_rebuild_performed": False,
        "dual_lock_raw_bytes_verified": True,
        "phases": phases,
        "python_tests": {"run": 32, "pass": 32, "skip": 0, "modules": dict(python_modules), "unittest_seconds": float(ran[0][1])},
        "rust_tests": {"log": pin(log), "starting": parsed["starting"], "summary": parsed["summary"], "unique_ids": 1564, "counts": parsed["counts"], "reported_skipped": 3, "skip_identities_not_inferred": True, "duplicate_execution_ids": 0, "footer_rows_excluded": parsed["footer_rows_excluded"], "per_package": package_counts, "baseline_identity_key": ["binary", "name"], "baseline_count": 1564, "baseline_missing": [], "additional_ids": [], "baseline_used_as_filter": False, "failures": failures},
        "old_r23_nonpassing": {"total": 8, "now_pass": 6, "still_fail": 2, "crosswalk": "readback/R23-FAILURE-TRANSITIONS.json"},
        "outer_job": terminal["job_id"], "outer_exit_code": 100,
        "outer_natural_durable_terminal": True,
        "r25_workspace_executed": False,
        "final_fix_fmt_executed": False,
        "no_tests_reexecuted_by_attachment_work": True,
        "root_and_native_result_sets_independently_matched": True,
        "resource_boundary": "Per-phase /usr/bin/time originals are retained. Shared filesystem free-space samples are not a measurement of this task's exclusive resource consumption.",
        "qualification": "FAIL. Python32 and strict0 do not override the original full-tests/outer100. Later candidates and gates are outside this frozen group.",
    }
    emit("INDEPENDENT-READBACK.json", readback)
    emit("ORIGINAL-MEMBER-MAPPING.json", {"schema": "hepta.r24-exact-member-mapping.v1", "archive": archive_pin, "members": member_mappings, "source_locks_and_support_source_preserved_in_archive_without_duplicate_trees": True})
    emit("SOURCE-DESTINATION-MAPPING.json", {"schema": "hepta.r24-formal-byte-copy-mapping.v1", "copies": copies, "gzip_roundtrips_exact": True, "original_historical_fields_unchanged": True})
    emit("GZIP-ROUNDTRIP.json", {"schema": "hepta.r24-deterministic-gzip-readback.v1", "mtime": 0, "filename_header": "empty", "compresslevel": 9, "items": compressed, "derived_rows": {"path": "readback/EXECUTED-RESULTS.json.gz", "original_pin": pin(raw_json(rows)), "stored_pin": pin((output / "readback/EXECUTED-RESULTS.json.gz").read_bytes())}})
    emit("BINARY-PLAN.json", {"schema": "hepta.r24-formal-binary-publication-plan.v1", "upload_performed_by_this_work": False, "repository_relative_root": "qualification/cell-unification-20261106/native-evidence/r24-project-checkpoint", "files": binaries})
    emit("CLOSURE.json", {"schema": "hepta.r24-project-checkpoint-closure.v1", "status": "CLOSED_ORIGINAL_ENGINEERING_FAIL_100", "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE, "source_count": 194, "archive": archive_pin, "source_manifest": "original/input/native-candidate-r24-source.json", "original_index": "original/INDEX.json.gz", "readback": "INDEPENDENT-READBACK.json", "result_counts": {"unique_rust_tests": 1564, "PASS": 1561, "FAIL": 3, "TIMEOUT": 0, "reported_skipped": 3}, "python_run": 32, "python_exit": 0, "strict_exit": 0, "tests_exit": 100, "outer_exit": 100, "workspace_r25_started": False, "final_fix_fmt_executed": False, "closed_evidence_missing": [], "future_native_candidate_qualification": "Not present in this historical closure; source51 preparation is separate.", "science": "HOLD", "authority": "DENY_ALL"})

    fail_table = "\n".join(f"| `{r['binary']}` | `{r['name']}` | {r['seconds']:.3f}s |" for r in failures)
    transition_table = "\n".join(f"| `{r['binary']}` / `{r['name']}` | {r['r23_status']} | {r['r24']['status']} | {r['r24']['seconds']:.3f}s |" for r in transitions)
    readme = f"""# r24：source50 四包原门失败的闭合证据

**工程结论：FAIL，原完整测试与外层进程均自然退出100。** Python runner 的32项测试通过、原严格检查退出0分别成立；它们不替代完整测试结果，也没有触发后续 r25 工作区门或最终 fix/fmt。

源码身份是 commit `{SOURCE_COMMIT}`、tree `{SOURCE_TREE}`，194条变更源码。该身份来自固定源码清单和原生 guard；本附件没有把 GitData 身份等同于 native HEAD checkout。原 native HEAD 值、历史 pending 字段均按原件保留。

## 原门结果

| 阶段 | 原返回码 | 已观察结果 | 原耗时 |
|---|---:|---|---:|
| Python runner 完整发现 | 0 | 32通过、0跳过；10原测试＋22 helper 测试 | 3.8193337917s，总进程 |
| 四包原 strict | 0 | 原 `just clippy --locked … -- -D warnings` | 217.4727106094s |
| 四包原 full tests | 100 | 1564唯一ID＝1561通过＋3失败＋0超时，原报告3跳过 | 503.7940561771s，含构建；nextest64.588s |

选择保持 `codex-cli`、`codex-exec-server`、`codex-network-proxy`、`codex-external-agent-migration`，原 `just test --locked`、`--retries 0`、默认features与已有平台/ignored条件不变。基线1564个 `(binary, name)` 全部出现，没有新增或缺失ID。基线仅用于完整执行后的验收，没有用作过滤器。Summary后的三行失败复述已排除；3个skip只保留原报告总数，不从日志推断具体身份。

| 失败 binary | 测试 | 原耗时 |
|---|---|---:|
{fail_table}

前两项原日志记录真实 helper 在 loopback RTM_NEWADDR 初始化失败；第三项记录 direct CONNECT policy fixture 得到403 `blocked-by-allowlist`。本组保留原失败，不把后来独立诊断或未资格候选写成这次通过。

## r23 旧不通过用例的逐ID交叉核对

r23 的原8个不通过块已从闭合原件精确恢复并单列为补充证据。本轮6个通过、2个仍失败；本轮第三个失败不在此前8项不通过集合中。下表来自本轮完整原日志的唯一ID和原r23块，不是重新运行：

| binary / 测试 | r23 | r24 | r24原耗时 |
|---|---|---|---:|
{transition_table}

完整行号、原字节offset和旧块SHA见 [交叉表](readback/R23-FAILURE-TRANSITIONS.json)。本次附件工作没有重新解析r23完整工作区日志；其8块原始身份及自身字节hash已核验。

## 可复核入口

- [闭合结论](CLOSURE.json) 与 [独立读回](INDEPENDENT-READBACK.json)。
- [原归档](checkpoint-r24-closed.tar.gz) 保留249个regular成员、248条原INDEX及全部194源码和双锁；没有重复复制源码树。
- [原INDEX](original/INDEX.json.gz)、[逐成员映射](ORIGINAL-MEMBER-MAPPING.json) 与 [原件到附件映射](SOURCE-DESTINATION-MAPPING.json)。
- [完整原测试日志](original/evidence/{PREFIX}-tests.log.gz)、[原测试回执](original/evidence/{PREFIX}-tests-receipt.json)、[原资源](original/evidence/{PREFIX}-tests-resources.txt) 和 [原失败块索引](original/failure-blocks/INDEX.json)。
- [原执行runner](original/input/native-run-r24.py)、[固定源码清单](original/input/native-candidate-r24-source.json)、[原基线](original/input/source50-four-package-r23-baseline.json.gz) 与 [根AGENTS](original/guidance/AGENTS.md)。
- [根独立归档读回](root-review/ROOT-ARCHIVE-READBACK.json) 原字节保留；本组另从原日志重算并与其完整结果集合逐项匹配。
- [压缩往返核验](GZIP-ROUNDTRIP.json)、[二进制登记计划](BINARY-PLAN.json)、[全部附件清单](ATTACHMENT-MANIFEST.json)。

大文本采用 filename为空、mtime=0 的gzip，并逐项验证解压结果等于原字节。归档transport mode全部为0600；这不等于源码原Git mode。原Git mode按固定源码清单保留，194份文件的实际字节SHA256和Git blob均重新计算。本组不冒称独立重建了完整Git tree。

资源记录使用每阶段原 `/usr/bin/time`；共享文件系统余量不能相减当作本任务独占消耗。所有源、原回执、失败块、历史字段均未修改。科学HOLD与DENY_ALL不变。
"""
    exact(output / "README.md", readme.encode())
    files = [{"path": p.relative_to(output).as_posix(), **pin(p.read_bytes())} for p in sorted(output.rglob("*")) if p.is_file() and p.name != "ATTACHMENT-MANIFEST.json" and "__pycache__" not in p.parts]
    emit("ATTACHMENT-MANIFEST.json", {"schema": "hepta.r24-formal-attachment-manifest.v1", "classification": "ENGINEERING_FAIL_100", "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE, "file_count": len(files), "total_stored_bytes": sum(r["bytes"] for r in files), "files": files})
    print(json.dumps({"status": "FORMAL_GROUP_CLOSED_ENGINEERING_FAIL_100", "files_excluding_manifest": len(files), "bytes_excluding_manifest": sum(r["bytes"] for r in files), "binary_paths": len(binaries), "counts": parsed["counts"], "old_r23_now_pass": 6, "reports": {name: pin((output / name).read_bytes()) for name in ("CLOSURE.json", "INDEPENDENT-READBACK.json", "BINARY-PLAN.json", "ATTACHMENT-MANIFEST.json")}}, indent=2))


if __name__ == "__main__":
    main()
