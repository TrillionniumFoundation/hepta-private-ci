"""Verify the retained original CI failure and its exact formatter-derived edit.

This reads evidence only. It does not run Rust, rustfmt, just, tests, or Git.
"""

import difflib
import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


HEAD = "eed4d6bb61b789b19f60facc79f9e031765fa4c9"
TREE = "ca1c4671ef6b2773280d01b5d76c6166252f5856"
RUN = 42063947910
JOB = 127372805931
DEFAULT_BASE = Path(__file__).resolve().parent


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def check_identity(data, expected):
    actual = identity(data)
    for key in actual:
        assert expected[key] == actual[key], (key, expected, actual)
    return actual


def original_api(path):
    value = json.loads(path.read_bytes())
    for _ in range(8):
        if isinstance(value, str):
            value = json.loads(value)
        elif "api_content" in value:
            value = value["api_content"]
        elif "structuredContent" in value:
            value = value["structuredContent"]
        elif isinstance(value.get("content"), str):
            value = value["content"]
        elif isinstance(value.get("content"), list):
            value = next(item["text"] for item in value["content"] if item["type"] == "text")
        else:
            return value
    raise AssertionError("Unsupported original API envelope")


def verify(base):
    receipt = json.loads((base / "static-reconstruction.json").read_bytes())
    assert receipt["head"] == HEAD and receipt["tree"] == TREE
    raw = (base / "originals/job-127372805931.log").read_bytes()
    check_identity(raw, receipt["original_log"])
    text = raw.decode()
    assert f"source={HEAD} tree={TREE} parents=5b6331250ff459033bd44d1a95daec70131277cc" in text
    assert f"git checkout --progress --force {HEAD}" in text
    assert "##[group]Run cargo +1.95.0 fmt --all -- --check" in text
    assert "2026-11-05T21:51:27.5725309Z ##[error]Process completed with exit code 1." in text

    runs = original_api(base / "originals/main-runs-api-root-2221.original.json")
    run = next(row for row in runs["workflow_runs"] if row["id"] == RUN)
    assert run["head_sha"] == HEAD and run["head_commit"]["tree_id"] == TREE
    assert run["run_attempt"] == 1 and run["status"] == "completed" and run["conclusion"] == "failure"
    jobs = original_api(base / "originals/jobs-api-root-2221.original.json")
    assert len(jobs["jobs"]) == jobs["total_count"]
    job = next(row for row in jobs["jobs"] if row["id"] == JOB)
    assert job["run_id"] == RUN and job["run_attempt"] == 1 and job["head_sha"] == HEAD
    assert job["status"] == "completed" and job["conclusion"] == "failure"
    steps = {step["number"]: step for step in job["steps"]}
    assert steps[13]["name"] == "Verify full-workspace canonical Rust format on Linux"
    assert steps[13]["conclusion"] == "failure"
    for number in (3, 8, 9, 10, 11, 12, 15, 16, 17):
        assert steps[number]["conclusion"] == "success", steps[number]
    assert [s["number"] for s in job["steps"] if s["conclusion"] == "failure"] == [13]
    step_slice = (base / "originals/fmt-step-complete-job-slice.log.txt").read_bytes()
    assert raw.count(step_slice) == 1
    step_start = raw.index(step_slice)

    pre_actual = json.loads((base / "preimages.actual-readback.json").read_bytes())
    assert pre_actual["head"] == HEAD and pre_actual["tree"] == TREE
    for row in pre_actual["files"]:
        data = (base / "source-before" / (row["logical_source_path"] + ".source.txt")).read_bytes()
        check_identity(data, row)
        assert row["actual_full_GET_byte_equal"]
        assert row["leaf"]["sha"] == row["git_blob"]
    post_actual = json.loads((base / "postimages.actual-readback.json").read_bytes())
    post_actual_by_path = {row["logical_source_path"]: row for row in post_actual["objects"]}
    assert len(post_actual_by_path) == 2 and post_actual["head"] == HEAD

    lines = raw.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    header = re.compile(rb"^\d{4}-\d\d-\d\dT\S+Z Diff in /home/runner/work/hepta-private-ci/hepta-private-ci/(codex-rs/[^:]+):(\d+):")
    timestamp = re.compile(rb"^\d{4}-\d\d-\d\dT\S+Z ")
    originals = {}
    rebuilt = {}
    hunks = []
    for index, line in enumerate(lines):
        match = header.match(line)
        if not match:
            continue
        path = match[1].decode()
        body = []
        end = index + 1
        for next_line in lines[index + 1:]:
            unprefixed = timestamp.sub(b"", next_line)
            if not unprefixed.startswith((b" ", b"+", b"-")):
                break
            body.append(unprefixed)
            end += 1
        before = b"".join(value[1:] for value in body if not value.startswith(b"+"))
        after = b"".join(value[1:] for value in body if not value.startswith(b"-"))
        if path not in originals:
            originals[path] = (base / "source-before" / (path + ".source.txt")).read_bytes()
            rebuilt[path] = originals[path]
        assert originals[path].count(before) == rebuilt[path].count(before) == 1
        assert originals[path][:originals[path].index(before)].count(b"\n") + 1 == int(match[2])
        rebuilt[path] = rebuilt[path].replace(before, after, 1)
        retained = receipt["four_original_hunks"][len(hunks)]
        assert retained["logical_source_path"] == path
        assert retained["original_source_line"] == int(match[2])
        assert retained["original_job_start_line"] == index + 1
        assert retained["original_job_end_line"] == end
        assert retained["original_job_start_byte"] == offsets[index]
        assert retained["original_job_end_byte"] == offsets[end]
        full_slice = b"".join(lines[index:end])
        assert full_slice == (base / "originals" / retained["original_slice"]["file"]).read_bytes()
        assert step_start <= offsets[index] < offsets[end] <= step_start + len(step_slice)
        check_identity(full_slice, retained["original_slice"])
        check_identity(before, retained["derived_before_block"])
        check_identity(after, retained["derived_after_block"])
        hunks.append(retained)
    assert len(hunks) == 4 and len(rebuilt) == 2
    source_rows = []
    patch = []
    for path in sorted(rebuilt):
        before, after = originals[path], rebuilt[path]
        assert after == (base / "source-after" / (path + ".source.txt")).read_bytes()
        source = next(row for row in receipt["source_rows"] if row["logical_source_path"] == path)
        before_id = check_identity(before, source["before"])
        after_id = check_identity(after, source["after"])
        actual = post_actual_by_path[path]
        assert actual["git_blob"] == actual["created"]["sha"] == actual["readback_blob_sha"] == after_id["git_blob"]
        assert actual["bytes"] == after_id["bytes"] and actual["actual_full_GET_byte_equal"]
        compact_before = re.sub(rb"\s+", b"", before)
        compact_after = re.sub(rb"\s+", b"", after)
        if path.endswith("environment_selection.rs"):
            assert compact_before == compact_after
            assert before.count(b",") == after.count(b",") == 610
            optional_comma_count = 0
        else:
            with_comma = b'("requires_openai_auth".to_string(),TomlValue::Boolean(false),)'
            without_comma = b'("requires_openai_auth".to_string(),TomlValue::Boolean(false))'
            assert compact_after.count(with_comma) == 1
            assert compact_before == compact_after.replace(with_comma, without_comma, 1)
            assert after.count(b",") == before.count(b",") + 1
            optional_comma_count = 1
        quoted = rb'"(?:\\.|[^"\\])*"'
        assert re.findall(quoted, before) == re.findall(quoted, after)
        patch.extend([f"diff --git a/{path} b/{path}\n", f"index {before_id['git_blob']}..{after_id['git_blob']} 100644\n"])
        patch.extend(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
        source_rows.append({
            "logical_source_path": path,
            "before": before_id,
            "after": after_id,
            "full_source_reconstructed_exactly_from_original_formatter_hunks": True,
            "pure_nonwhitespace_byte_equal": compact_before == compact_after,
            "optional_trailing_commas_added": optional_comma_count,
            "all_quoted_literal_matches_byte_equal": True,
        })
    patch_bytes = "".join(patch).encode()
    assert patch_bytes == (base / "format-only.patch").read_bytes()
    check_identity(patch_bytes, receipt["patch"])
    assert len(receipt["isolated_git_roundtrip"]) == 4
    assert all(row["exit_code"] == 0 for row in receipt["isolated_git_roundtrip"])
    assert not receipt["Rust_rustfmt_just_test_fix_or_other_native_command_executed"]

    artifacts_api = original_api(base / "originals/artifacts-complete-page.original.json")
    assert len(artifacts_api["artifacts"]) == artifacts_api["total_count"]
    artifact_rows = []
    for artifact_id, expected_count in ((13456116767, 3), (13455858457, 14)):
        metadata = next(row for row in artifacts_api["artifacts"] if row["id"] == artifact_id)
        data = (base / "originals" / f"artifact-{artifact_id}.zip").read_bytes()
        ident = identity(data)
        assert metadata["size_in_bytes"] == ident["bytes"]
        assert metadata["digest"] == "sha256:" + ident["sha256"]
        assert metadata["workflow_run"]["id"] == RUN and metadata["workflow_run"]["head_sha"] == HEAD
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert archive.testzip() is None
            assert archive.namelist() == ["junit.xml"]
            xml = archive.read("junit.xml")
            assert xml == (base / "originals" / f"artifact-{artifact_id}" / "junit.xml").read_bytes()
        root = ET.fromstring(xml)
        cases = root.findall(".//testcase")
        assert int(root.attrib["tests"]) == len(cases) == expected_count
        assert root.attrib["failures"] == root.attrib["errors"] == "0"
        assert not root.findall(".//failure") and not root.findall(".//error") and not root.findall(".//skipped")
        assert not root.findall(".//rerunFailure") and not root.findall(".//flakyFailure")
        case_rows = []
        for case in cases:
            suffix = case.attrib["classname"] + " " + case.attrib["name"]
            pass_lines = [line for line in text.splitlines() if "PASS [" in line and line.endswith(suffix)]
            assert len(pass_lines) == 2, (suffix, len(pass_lines))
            case_rows.append({
                "classname": case.attrib["classname"],
                "name": case.attrib["name"],
                "seconds": case.attrib["time"],
                "junit_result": "PASS",
                "original_raw_PASS_display_rows": pass_lines,
                "display_duplication_explanation": "One execution and its final-status-level all summary; these are not two executions.",
            })
        assert f"{expected_count} tests run: {expected_count} passed, 0 skipped" in text
        artifact_rows.append({"artifact_id": artifact_id, **ident, "CRC_and_official_digest_match": True, "xml": identity(xml), "cases": case_rows})

    return {
        "schema": "eed-original-format-failure-verification-v1",
        "head": HEAD,
        "tree": TREE,
        "run_id": RUN,
        "job_id": JOB,
        "run_attempt": 1,
        "job_status": "completed",
        "job_conclusion": "failure",
        "only_failed_step": steps[13],
        "raw_original": identity(raw),
        "full_original_format_step": {**identity(step_slice), "start_byte": step_start, "end_byte": step_start + len(step_slice)},
        "original_formatter_diff_hunks": len(hunks),
        "source_rows": source_rows,
        "exact_formatter_derived_patch": identity(patch_bytes),
        "original_native_supervisor_and_protocol_artifacts": artifact_rows,
        "original_supervisor_clippy_step": steps[12],
        "original_checkout_immutability_step": steps[17],
        "local_just_test_fix_fmt": "NOT_RUN",
        "new_candidate_native_qualification": "NOT_RUN",
        "old_3_plus_14_results_do_not_qualify_codex_core_or_new_candidate": True,
        "assertions_calls_time_budgets_strings_and_source_outside_formatter_hunks_unchanged": True,
        "verifier_executes_only_evidence_reads_and_hash_XML_ZIP_reconstruction": True,
    }


if __name__ == "__main__":
    result = verify(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BASE)
    print(json.dumps(result, ensure_ascii=False, indent=2))
