#!/usr/bin/env python3
"""Read frozen native evidence only; emit a small independent scoped review.

No network, product execution, CI query, or writes to the author directory.
The fixed compact protobuf reader is reused only as a byte decoder; the
cross-artifact/source/count assertions below are independent of the author
packet verifier. Run with Python -B and the frozen author directory argument.
"""
import ast
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

HEAD = "17c6b903a5d5d470b72035f95bb6e087291d7e04"
MERGE = "26cfdcaa70cbd2daecd165137e3b84d2ad1a7284"
TREE = "25020dc30888fa3ffa6f6e8d1073d91edded1756"
BASE = "63652be658ebed8d3052eb789b951793384fd5e4"
PARENT = "840e8b5dbffca017753cdf87482ce325938f313c"
RUN = 42201989580
COUNTS = {"hepta-intelligence": 78, "hepta-bao-adapter": 19,
          "hepta-codex-adapter": 21}
CONTROL_SOURCES = {
    "hepta-intelligence": "codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs",
    "hepta-bao-adapter": "codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs",
    "hepta-codex-adapter": "codex-rs/hepta-codex-adapter/src/lib_tests.rs",
}
SIDES = [
    (13494647856, 127839243318, "source-head", HEAD, [PARENT]),
    (13495625588, 127839242912, "base-merge", MERGE, [BASE, HEAD]),
]


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest()}


def content(envelope):
    assert not envelope.get("isError", False)
    result = envelope["structuredContent"]["content"]
    assert isinstance(result, str)
    return result


def api(value):
    if "raw" in value:
        value = value["raw"]
    return json.loads(content(value))


def merkle(full):
    assert full["sha"] == TREE and full["truncated"] is False
    rows = full["tree"]
    mapping = {r["path"]: r for r in rows}
    assert len(mapping) == len(rows)
    children = collections.defaultdict(list)
    for row in rows:
        path = row["path"]
        assert not path.startswith("/") and ".." not in path.split("/")
        parent, _, name = path.rpartition("/")
        if parent:
            assert mapping[parent]["type"] == "tree"
        children[parent].append((name, row))
    computed = {}

    def walk(path):
        parts = []
        for name, row in sorted(children[path], key=lambda x:
                x[0].encode() + (b"/" if x[1]["type"] == "tree" else b"")):
            if row["type"] == "tree":
                child = walk(row["path"])
                assert child == row["sha"]
                mode = "40000"
            else:
                assert row["type"] in ("blob", "commit")
                child = row["sha"]
                mode = row["mode"]
            parts.append(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(child))
        body = b"".join(parts)
        sha = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
        computed[path] = sha
        return sha

    assert walk("") == TREE
    return mapping, {"root": TREE, "leaves": sum(r["type"] != "tree" for r in rows),
                     "all_directory_trees_recomputed": len(computed)}


def main(root):
    read = lambda path: (root / path).read_bytes()
    load = lambda path: json.loads(read(path))
    freeze_results = []
    for name, expected, count in [
        ("ORIGINALS-FREEZE.json", "71018f247ef99839762f63ba96d02a079eb213be", 40),
        ("FREEZE.json", "c20d96ac7612a2b92f8463ecf651a2cd8779a28b", 55),
    ]:
        raw = read(name)
        assert identity(raw)["git_blob"] == expected
        rows = json.loads(raw)["files"]
        assert len(rows) == count and len({r["path"] for r in rows}) == count
        for row in rows:
            assert identity(read(row["path"])) == {k: row[k] for k in identity(b"")}
        freeze_results.append({"path": name, **identity(raw), "members": count,
                               "member_bytes": sum(r["bytes"] for r in rows),
                               "all_member_bytes_verified": True})
    full, tree_result = merkle(load("authority/full-tree-25020.json"))
    head = api(load("authority/commit.actual.original.json"))
    merge = api(load("authority/merge.actual.original.json"))
    for obj, sha, parents in [(head, HEAD, [PARENT]), (merge, MERGE, [BASE, HEAD])]:
        assert obj["sha"] == sha and obj["tree"]["sha"] == TREE
        assert [p["sha"] for p in obj["parents"]] == parents
    assert api(load("authority/ref.after.original.json"))["object"]["sha"] == HEAD
    pr = api(load("authority/pr.after.original.json"))
    assert pr["head"]["sha"] == HEAD and pr["base"]["sha"] == BASE
    assert pr["merge_commit_sha"] == MERGE and pr["draft"] and pr["state"] == "open"
    source_rows = load("source-full-GET.original.json")["records"] + load(
        "input-source-full-GET.original.json")["records"]
    assert len(source_rows) == len({r["path"] for r in source_rows}) == 13
    sources = {}
    source_proof = []
    for row in source_rows:
        data = read("source/" + row["path"])
        assert content(row["full_GET_original"]).encode() == data
        assert identity(data)["git_blob"] == row["sha"] == full[row["path"]]["sha"]
        sources[row["path"]] = data
        source_proof.append({"path": row["path"], "git_blob": row["sha"]})
    smap = load("source-map.json")
    assert smap["tree"] == TREE and len(smap["source_records"]) == 5
    for row in smap["source_records"]:
        assert identity(sources[row["path"]]) == {k: row[k] for k in identity(b"")}
    workflow = sources[".github/workflows/windows-ordinary-consumers.yml"].decode()
    block = re.search(r"          scopes = (\{.*?\n          \})\n          targets =", workflow, re.S)
    assert block
    scopes = ast.literal_eval(block.group(1))
    assert {k: len(v) for k, v in scopes.items()} == {
        "hepta-intelligence": 4, "hepta-bao-adapter": 8, "hepta-codex-adapter": 3}
    for library, controls in scopes.items():
        source = sources[CONTROL_SOURCES[library]].decode()
        for name in controls:
            assert re.search(r"\bfn\s+" + re.escape(name) + r"\s*\(", source)
    assert "runs-on: windows-2025" in workflow and "timeout-minutes: 120" in workflow
    jobs_payload = load(f"jobs-{RUN}.original.json")
    jobs_api = api(jobs_payload)
    assert jobs_api["total_count"] == len(jobs_api["jobs"]) == 2
    jobs = {j["id"]: j for j in jobs_api["jobs"]}
    artifacts_payload = load(f"artifacts-{RUN}.original.json")
    artifacts_api = api(artifacts_payload)
    assert artifacts_api["total_count"] == len(artifacts_api["artifacts"]) == 2
    artifacts = {a["id"]: a for a in artifacts_api["artifacts"]}
    spec = importlib.util.spec_from_file_location("fixed_native_compact_projection", root / "project_compact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    side_results = []
    rosters = {}
    for artifact_id, job_id, kind, checkout, parents in SIDES:
        job = jobs[job_id]
        assert job["run_id"] == RUN and job["head_sha"] == HEAD
        assert job["status"] == "completed" and job["conclusion"] == "success"
        assert job["name"] == f"Original Windows business libraries ({kind})"
        assert job["labels"] == ["windows-2025"]
        assert all(s["status"] == "completed" and s["conclusion"] == "success" for s in job["steps"])
        log = read(f"job-{job_id}.original.log")
        assert content(load(f"job-{job_id}-tool-return.original.json")).encode() == log
        lines = log.decode("utf-8-sig").splitlines()
        console_lines = [re.sub(r"^\d{4}-\d\d-\d\dT\S+Z ", "", l) for l in lines]
        actual_head = [console_lines[i+1] for i, line in enumerate(console_lines[:-1])
                       if 'git.exe" log -1 --format=%H' in line]
        assert actual_head == [checkout]
        assert not any("##[error]" in line for line in lines)
        assert "Microsoft Windows Server 2025" in console_lines
        assert "Image: windows-2025-vs2026" in console_lines
        assert "Version: 20261030.294.1" in console_lines
        assert sum(line == "Executed 3 out of 3 tests: 3 tests pass." for line in console_lines) == 1
        artifact = artifacts[artifact_id]
        raw_zip = read(f"artifacts/artifact-{artifact_id}.original.zip")
        assert len(raw_zip) == artifact["size_in_bytes"]
        assert "sha256:" + identity(raw_zip)["sha256"] == artifact["digest"]
        assert artifact["workflow_run"]["id"] == RUN
        assert artifact["workflow_run"]["head_sha"] == HEAD and not artifact["expired"]
        assert artifact["name"] == f"windows-ordinary-consumers-{kind}-{checkout}-{RUN}"
        archive = zipfile.ZipFile(root / f"artifacts/artifact-{artifact_id}.original.zip")
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names)) == 10
        assert all(not n.startswith("/") and ".." not in n.split("/") for n in names)
        zread = archive.read
        source = json.loads(zread("ordinary-consumers/source.json"))
        result = json.loads(zread("ordinary-consumers/result.json"))
        assert source["head"] == checkout and source["tree"] == TREE
        assert source["parents"] == parents and source["checkout_kind"] == kind
        assert source["run_id"] == str(RUN) and source["run_attempt"] == "1"
        assert len(source["inputs"]) == 9
        for path, digest in source["inputs"].items():
            assert b"\r\n" not in sources[path]
            assert hashlib.sha256(sources[path].replace(b"\n", b"\r\n")).hexdigest() == digest
        labels = [f"//codex-rs/{name}:{name}-unit-tests" for name in COUNTS]
        expected_command_tail = [
            ".github/scripts/run-bazel-ci.sh", "--print-failed-action-summary",
            "--print-failed-test-logs", "--windows-msvc-host-platform", "--", "test",
            "--platforms=//:windows_x86_64_msvc", "--nocache_test_results",
            "--flaky_test_attempts=1", "--test_output=all",
            "--build_metadata=COMMIT_SHA=" + checkout, "--", *labels,
        ]
        assert result["command"][0] == result["launcher"]["path"]
        assert result["command"][1:] == expected_command_tail
        assert result["original_targets"] == labels
        assert result["exit_code"] == 0 and result["unchanged_inputs"] is True
        native_log = zread("ordinary-consumers/original-libraries.log")
        assert identity(native_log)["sha256"] == result["log_sha256"]
        # The workflow prints JSON after Windows text-mode CRLF translation;
        # compare parsed values, never claim console equals original JSON bytes.
        console = "\n".join(console_lines)
        receipt_start = console.index('{\n  "command": [')
        parsed_receipt, _ = json.JSONDecoder().raw_decode(console[receipt_start:])
        assert parsed_receipt == result
        compact_names = [n for n in names if n.endswith(".zst")]
        assert len(compact_names) == 1
        compact, entries = module.decode(zread(compact_names[0]))
        # JSON object keys become strings: normalize only this comparison.
        assert json.loads(json.dumps(compact)) == load(f"derived/compact-{artifact_id}.json")
        assert compact["record_count"] == 64893
        assert sum(x["count"] for x in compact["runner_counts"] if x["mnemonic"] == "TestRunner") == 6
        spawns = compact["selected_spawns"]
        assert len(spawns) == 6 and {s["target_label"] for s in spawns} == set(labels)
        libraries = []
        for name, count in COUNTS.items():
            label = f"//codex-rs/{name}:{name}-unit-tests"
            folder = f"ordinary-consumers/native-test-logs/codex-rs/{name}/{name}-unit-tests/"
            tlog, xml = zread(folder + "test.log"), zread(folder + "test.xml")
            text = tlog.decode()
            cases = re.findall(r"(?m)^test (\S+) \.\.\. (\S+)\r?$", text)
            assert len(cases) == count and len({n for n, status in cases}) == count
            assert all(status == "ok" for n, status in cases)
            summary = re.findall(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;", text)
            assert summary == [("ok", str(count), "0", "0", "0", "0")]
            assert re.findall(r"(?m)^running (\d+) tests\r?$", text) == [str(count)]
            actual_roster = sorted(n for n, status in cases)
            if name in rosters:
                assert rosters[name] == actual_roster
            else:
                rosters[name] = actual_roster
            short_names = {n.rsplit("::", 1)[-1] for n, status in cases}
            retained = result["targets"][name]
            assert set(retained["observed_passed_names"]) == short_names
            assert set(retained["required_original_controls"]) == scopes[name]
            assert retained["missing"] == [] and scopes[name] <= short_names
            assert len(retained["retained"]) == 2
            for item in retained["retained"]:
                payload = zread("ordinary-consumers/native-test-logs/" + item["path"])
                assert len(payload) == item["bytes"] and identity(payload)["sha256"] == item["sha256"]
            normalized_log = native_log.decode().replace("\r\n", "\n")
            for case_name, status in cases:
                assert f"test {case_name} ... ok" in normalized_log
            xml_root = ET.fromstring(xml)
            suites = xml_root.findall(".//testsuite")
            assert len(suites) == 1 and suites[0].get("tests") == "1"
            assert suites[0].get("failures") == suites[0].get("errors") == "0"
            assert len(xml_root.findall(".//testcase")) == 1
            assert not xml_root.findall(".//failure") and not xml_root.findall(".//error")
            assert xml_root.find(".//system-out").text == text
            pair = [s for s in spawns if s["target_label"] == label]
            assert len(pair) == 2
            tests = [s for s in pair if s["args"][0].replace("\\", "/").endswith("/tw.exe")]
            helpers = [s for s in pair if s["args"][0].replace("\\", "/").endswith("/xml.exe")]
            assert len(tests) == len(helpers) == 1
            test, helper = tests[0], helpers[0]
            for spawn in pair:
                assert spawn["runner"] == "local" and spawn["cache_hit"] is False
                assert spawn["exit_code"] == 0 and spawn["status"] == ""
            assert test["timeout_millis"] == 300000
            assert test["args"][1] == f"codex-rs/{name}/{name}-unit-tests.bat"
            assert helper["timeout_millis"] == 0 and helper["args"][-1] == "0"
            descendants = module.descendants(entries, helper["input_set_id"])
            own_input = [entries[i] for i in descendants if entries[i].get("path") == helper["args"][1]]
            assert len(own_input) == 1
            assert own_input[0]["digest"]["hash"] == identity(tlog)["sha256"]
            assert own_input[0]["digest"]["size_bytes"] == len(tlog)
            own_output = [o for o in helper["outputs"] if o.get("path") == helper["args"][2]]
            assert len(own_output) == 1
            assert own_output[0]["digest"]["hash"] == identity(xml)["sha256"]
            assert own_output[0]["digest"]["size_bytes"] == len(xml)
            libraries.append({"name": name, "passed": count, "failed": 0, "ignored": 0,
                "measured": 0, "filtered_out": 0, "unique_full_case_names": len(actual_roster),
                "roster_sha256": hashlib.sha256(("\n".join(actual_roster) + "\n").encode()).hexdigest(),
                "named_controls_passed": sorted(scopes[name]),
                "test_log": identity(tlog), "test_xml": identity(xml),
                "xml_wrapper_cases": 1, "xml_system_out_equals_full_Rust_log": True,
                "product_spawn": {"sequence": test["sequence"], "runner": "local", "cache_hit": False,
                                  "exit_code": 0, "timeout_millis": 300000},
                "XML_helper_spawn": {"sequence": helper["sequence"], "runner": "local", "cache_hit": False,
                                     "exit_code": 0, "timeout_millis": 0},
                "XML_helper_own_input_log_and_own_output_XML_digest_match_archive": True})
        side_results.append({"checkout_kind": kind, "actual_checkout": checkout,
            "tree": TREE, "parents": parents, "job_id": job_id,
            "job_status": "completed", "job_conclusion": "success",
            "started_at": job["started_at"], "completed_at": job["completed_at"],
            "full_job_log": identity(log), "full_MCP_log_equals_original_UTF8_bytes": True,
            "actual_checkout_git_log_command_matched": True,
            "Windows_image": "windows-2025-vs2026 20261030.294.1 / Windows Server 2025 10.0.26100",
            "official_artifact_id": artifact_id, "official_ZIP": identity(raw_zip),
            "official_API_digest_size_equal": True, "ZIP_CRC_all_members": True, "ZIP_members": 10,
            "source_input_hashes_verified": 9, "source_input_transform": "exact Git LF -> Windows CRLF",
            "Bazel_wrapper_exit_code": 0, "original_library_targets": 3,
            "actual_command": result["command"], "unchanged_inputs": True,
            "compact": {"path": compact_names[0], "identity": identity(zread(compact_names[0])),
                "all_records_decoded": compact["record_count"], "decompressed_bytes": compact["decompressed_bytes"],
                "invocation_id": compact["invocation"]["id"], "actual_product_TestRunner_count": 3,
                "XML_helper_TestRunner_count": 3, "selected_product_and_helper_count_equals_all_TestRunner_count": True,
                "other_build_actions_include_cache_hits": True,
                "XML_missing_in_product_spawn_but_materialized_by_own_helper": True},
            "libraries": libraries, "Rust_cases_passed": sum(COUNTS.values()),
            "Bazel_XML_wrapper_cases": 3})
    other_runs = []
    for run in (42201989809, 42201989815):
        value = api(load(f"jobs-{run}.original.json"))
        assert value["total_count"] == len(value["jobs"])
        other_runs.append({"run_id": run, "total_count": value["total_count"],
            "jobs": [{k: j[k] for k in ("id", "head_sha", "status", "conclusion")}
                     for j in value["jobs"]], "not_granted_acceptance_by_this_review": True})
    review = {"schema": "hepta-independent-original-Windows-libraries-native-review-v1",
        "conclusion": "ACCEPT_SCOPED_EVIDENCE", "confirmed_evidence_blockers": [],
        "method": "Local read-only, complete frozen-byte verification and independent cross-checks; no new CI/network/native calls.",
        "author_directory": "integration-ci-review/17c6b903-followup-20261106T1043",
        "frozen_inputs": freeze_results, "run_id": RUN,
        "recorded_jobs_API_capture_cut": jobs_payload.get("capture_completed_before_utc"),
        "recorded_artifacts_API_capture_cut": artifacts_payload.get("capture_completed_before_utc"),
        "source": {"head": HEAD, "head_parents": [PARENT], "actual_merge": MERGE,
            "merge_parents": [BASE, HEAD], "same_tree": TREE, "Merkle": tree_result,
            "fixed_source_full_GET_count": 13, "fixed_source_identities": source_proof,
            "all_full_GET_content_equals_canonical_source_bytes": True,
            "source_map_all_five_records_equal": True,
            "captured_worktree_hashes": "Both checkouts' nine input hashes exactly match canonical fixed Git bytes after LF-to-CRLF transformation. Canonical and worktree bytes are not falsely claimed identical."},
        "sides": side_results,
        "denominators": {"unique_Rust_cases": 118, "passed_case_executions_per_checkout": 118,
            "successful_case_executions_across_two_checkouts": 236,
            "named_original_controls_per_checkout": [4, 8, 3],
            "Bazel_wrapper_testcases_per_checkout": 3,
            "compact_TestRunner_records_per_checkout": 6,
            "product_TestRunner_records_per_checkout": 3, "XML_helper_records_per_checkout": 3,
            "all_Rust_rosters_equal_between_checkouts": True},
        "scope_limits": [
            "Evidence establishes these three complete original Windows business-library targets and their 15 named controls, on each exact checkout shown.",
            "The original workflow uses --nocache_test_results, --flaky_test_attempts=1 and --test_output=all with its original target set. No test-name filter is present. Each actual product spawn has the captured 300000 ms timeout.",
            "XML contains one Bazel wrapper testcase per library, with the complete Rust test log in system-out; it is not 118 individually modeled XML cases.",
            "The compact records prove three local noncached product invocations and three separate local XML helpers per side. Build actions elsewhere may be cached. A product spawn's absent test.xml is not an absent archive XML: its separately recorded helper materializes the exact retained XML.",
            "No B11 sandbox privilege/ACL acceptance, whole-candidate acceptance, whole-repository CI acceptance, or ledger transition is granted.",
            "The other retained jobs APIs are bounded historical observations and do not prove later terminal states. No fresh API query was made.",
        ],
        "other_retained_job_cuts": other_runs,
        "ledger_transition": None,
        "validation_environment": "Python offline hashes, XML/JSON parsing, Git tree calculation, and read-only zstd/protobuf decompression only; no Rust/native product tests executed."}
    print(json.dumps(review, ensure_ascii=False, indent=2) + "\n", end="")


if __name__ == "__main__":
    assert len(sys.argv) == 2, "supply the frozen author directory"
    main(Path(sys.argv[1]).resolve())
