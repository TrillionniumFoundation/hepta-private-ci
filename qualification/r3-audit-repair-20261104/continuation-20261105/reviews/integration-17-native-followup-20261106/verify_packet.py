#!/usr/bin/env python3
"""Offline original-source/ZIP/log/compact qualification of two Windows library jobs."""
import argparse
import ast
import collections
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import textwrap
import xml.etree.ElementTree as ET
import zipfile

HEAD = "17c6b903a5d5d470b72035f95bb6e087291d7e04"
MERGE = "26cfdcaa70cbd2daecd165137e3b84d2ad1a7284"
TREE = "25020dc30888fa3ffa6f6e8d1073d91edded1756"
BASE = "63652be658ebed8d3052eb789b951793384fd5e4"
PREVIOUS = "840e8b5dbffca017753cdf87482ce325938f313c"
COUNTS = {"hepta-intelligence": 78, "hepta-bao-adapter": 19, "hepta-codex-adapter": 21}
PAIRS = [(13495625588, 127839242912, MERGE, "base-merge", [BASE, HEAD]),
         (13494647856, 127839243318, HEAD, "source-head", [PREVIOUS])]


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def load(root, path):
    return json.loads((root / path).read_bytes())


def unpack(value):
    if "raw" in value:
        value = value["raw"]
    assert not value.get("isError", False)
    return json.loads(value["structuredContent"]["content"])


def merkle(tree):
    assert tree["truncated"] is False and tree["sha"] == TREE
    entries = {item["path"]: item for item in tree["tree"]}
    assert len(entries) == len(tree["tree"])
    children = collections.defaultdict(list)
    for path, entry in entries.items():
        parent, _, name = path.rpartition("/")
        children[parent].append((name, entry))
    def visit(path):
        out = []
        for name, entry in sorted(children[path], key=lambda item: (item[0] + ("/" if item[1]["type"] == "tree" else "")).encode()):
            if entry["type"] == "tree":
                sha = visit(entry["path"])
                assert sha == entry["sha"]
                mode = "40000"
            else:
                sha = entry["sha"]
                mode = entry["mode"]
            out.append(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha))
        data = b"".join(out)
        return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert visit("") == TREE
    leaves = {p: item for p, item in entries.items() if item["type"] != "tree"}
    assert len(leaves) == 10804
    return leaves


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root
    freeze = load(root, "ORIGINALS-FREEZE.json")
    assert len(freeze["files"]) == len({x["path"] for x in freeze["files"]}) == 40
    for item in freeze["files"]:
        assert identity((root / item["path"]).read_bytes()) == {k: item[k] for k in ("bytes", "git_blob", "sha256")}
    leaves = merkle(load(root, "authority/full-tree-25020.json"))
    commit = unpack(load(root, "authority/commit.actual.original.json"))
    merge = unpack(load(root, "authority/merge.actual.original.json"))
    ref = unpack(load(root, "authority/ref.after.original.json"))
    pr = unpack(load(root, "authority/pr.after.original.json"))
    assert commit["sha"] == HEAD and commit["tree"]["sha"] == TREE
    assert [x["sha"] for x in commit["parents"]] == [PREVIOUS]
    assert merge["sha"] == MERGE and merge["tree"]["sha"] == TREE
    assert [x["sha"] for x in merge["parents"]] == [BASE, HEAD]
    assert ref["object"]["sha"] == pr["head"]["sha"] == HEAD
    assert pr["base"]["sha"] == BASE and pr["merge_commit_sha"] == MERGE

    source_records = load(root, "source-full-GET.original.json")["records"] + load(root, "input-source-full-GET.original.json")["records"]
    assert len(source_records) == 13
    for item in source_records:
        content = item["full_GET_original"]["structuredContent"]["content"].encode()
        assert content == (root / "source" / item["path"]).read_bytes()
        assert identity(content)["git_blob"] == item["sha"] == leaves[item["path"]]["sha"]
    workflow = (root / "source/.github/workflows/windows-ordinary-consumers.yml").read_text()
    assert "timeout-minutes: 120" in workflow and "runs-on: windows-2025" in workflow
    assert "uses: ./.github/actions/prepare-bazel-ci" in workflow
    assert "revision: [source-head, base-merge]" in workflow
    scope_start = workflow.index("          scopes = {")
    scope_end = workflow.index("          targets =", scope_start)
    assignment = ast.parse(textwrap.dedent(workflow[scope_start:scope_end])).body[0]
    scopes = ast.literal_eval(assignment.value)
    assert {k: len(v) for k, v in scopes.items()} == {"hepta-intelligence": 4, "hepta-bao-adapter": 8, "hepta-codex-adapter": 3}

    blocking = unpack(load(root, "jobs-42201989815.original.json"))
    supervisor = unpack(load(root, "jobs-42201989809.original.json"))
    ordinary = unpack(load(root, "jobs-42201989580.original.json"))
    artifacts = unpack(load(root, "artifacts-42201989580.original.json"))
    assert blocking["total_count"] == len(blocking["jobs"]) == 0
    assert supervisor["total_count"] == len(supervisor["jobs"]) == 2
    assert all(j["head_sha"] == HEAD and j["status"] == "in_progress" and j["conclusion"] is None for j in supervisor["jobs"])
    assert ordinary["total_count"] == len(ordinary["jobs"]) == 2
    assert artifacts["total_count"] == len(artifacts["artifacts"]) == 2
    job_map = {j["id"]: j for j in ordinary["jobs"]}
    artifact_map = {a["id"]: a for a in artifacts["artifacts"]}
    spec = importlib.util.spec_from_file_location("fixed_compact_projection", root / "project_compact.py")
    projector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(projector)
    results = []
    for aid, jid, checkout, kind, parents in PAIRS:
        job = job_map[jid]
        assert job["head_sha"] == HEAD and job["conclusion"] == "success" and job["status"] == "completed"
        assert job["run_attempt"] == 1 and all(s["conclusion"] == "success" for s in job["steps"])
        raw_log = (root / f"job-{jid}.original.log").read_bytes()
        response = load(root, f"job-{jid}-tool-return.original.json")
        assert response["structuredContent"]["content"].encode() == raw_log
        console = re.sub(r"\x1b\[[0-9;]*m", "", raw_log.decode())
        console = "\n".join(re.sub(r"^\d{4}-\d\d-\d\dT\S+Z ", "", line) for line in console.splitlines())
        assert "HEAD is now at " + checkout[:7] in console
        archive_bytes = (root / f"artifacts/artifact-{aid}.original.zip").read_bytes()
        api = artifact_map[aid]
        assert api["workflow_run"]["id"] == 42201989580 and api["workflow_run"]["head_sha"] == HEAD
        assert len(archive_bytes) == api["size_in_bytes"] and "sha256:" + hashlib.sha256(archive_bytes).hexdigest() == api["digest"]
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert archive.testzip() is None
            members = {info.filename: archive.read(info) for info in archive.infolist()}
            assert len(members) == len(archive.infolist()) == 10
        retained_manifest = load(root, f"artifacts/artifact-{aid}-verification.json")
        assert retained_manifest["member_count"] == len(members)
        for item in retained_manifest["members"]:
            assert identity(members[item["path"]]) == {k: item[k] for k in ("bytes", "git_blob", "sha256")}
        source = json.loads(members["ordinary-consumers/source.json"])
        receipt = json.loads(members["ordinary-consumers/result.json"])
        log = members["ordinary-consumers/original-libraries.log"]
        assert source["head"] == checkout and source["tree"] == TREE and source["parents"] == parents
        assert source["checkout_kind"] == kind and source["run_id"] == "42201989580" and source["run_attempt"] == "1"
        assert len(source["inputs"]) == 9
        input_bindings = []
        for path, digest in source["inputs"].items():
            canonical = (root / "source" / path).read_bytes()
            assert b"\r" not in canonical
            assert hashlib.sha256(canonical.replace(b"\n", b"\r\n")).hexdigest() == digest
            input_bindings.append({"path": path, "fixed_git_blob": leaves[path]["sha"], "worktree_sha256": digest, "exact_byte_transform": "LF_to_CRLF"})
        expected_command = [receipt["launcher"]["path"], ".github/scripts/run-bazel-ci.sh", "--print-failed-action-summary", "--print-failed-test-logs", "--windows-msvc-host-platform", "--", "test", "--platforms=//:windows_x86_64_msvc", "--nocache_test_results", "--flaky_test_attempts=1", "--test_output=all", "--build_metadata=COMMIT_SHA=" + checkout, "--"] + [f"//codex-rs/{name}:{name}-unit-tests" for name in scopes]
        assert receipt["command"] == expected_command
        assert receipt["original_targets"] == expected_command[-3:]
        assert receipt["exit_code"] == 0 and receipt["unchanged_inputs"] is True
        assert hashlib.sha256(log).hexdigest() == receipt["log_sha256"]
        assert members["ordinary-consumers/result.json"].decode().replace("\r\n", "\n").rstrip() in console
        compact_names = [name for name in members if name.endswith(".zst")]
        assert len(compact_names) == 1
        projection, entries = projector.decode(members[compact_names[0]])
        assert json.loads(json.dumps(projection)) == load(root, f"derived/compact-{aid}.json")
        assert projection["record_count"] == 64893
        assert projection["invocation"]["id"] in log.decode()
        assert sum(x["count"] for x in projection["runner_counts"] if x["mnemonic"] == "TestRunner") == 6
        targets = []
        for name, expected_count in COUNTS.items():
            label = f"//codex-rs/{name}:{name}-unit-tests"
            path = f"ordinary-consumers/native-test-logs/codex-rs/{name}/{name}-unit-tests/"
            test_log, xml_bytes = members[path + "test.log"], members[path + "test.xml"]
            text = test_log.decode()
            cases = re.findall(r"(?m)^test (\S+) \.\.\. ok\r?$", text)
            assert len(cases) == len(set(cases)) == expected_count
            summaries = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;", text)
            assert summaries == [(str(expected_count), "0", "0", "0", "0")]
            assert f"running {expected_count} tests" in text
            seen = {case.rsplit("::", 1)[-1] for case in cases}
            assert sorted(seen) == receipt["targets"][name]["observed_passed_names"]
            assert scopes[name] <= seen and receipt["targets"][name]["missing"] == []
            assert sorted(scopes[name]) == receipt["targets"][name]["required_original_controls"]
            xml = ET.fromstring(xml_bytes)
            assert len(list(xml.iter("testcase"))) == 1
            assert not list(xml.iter("failure")) and not list(xml.iter("error")) and not list(xml.iter("skipped"))
            selected = [x for x in projection["selected_spawns"] if x["target_label"] == label]
            product = [x for x in selected if x["args"][0].endswith("\\tw.exe")]
            helper = [x for x in selected if x["args"][0].endswith("\\xml.exe")]
            assert len(selected) == 2 and len(product) == len(helper) == 1
            product, helper = product[0], helper[0]
            assert product["sequence"] < helper["sequence"]
            assert all(x["runner"] == "local" and x["cache_hit"] is False and x["exit_code"] == 0 for x in (product, helper))
            assert product["timeout_millis"] == 300000 and helper["timeout_millis"] == 0
            assert helper["args"][-1] == "0"
            descendants = projector.descendants(entries, helper["input_set_id"])
            inputs = [entries[i] for i in descendants if entries[i].get("type") == "file" and entries[i].get("path") == helper["args"][1]]
            assert len(inputs) == 1
            own_log = inputs[0]["digest"]
            assert own_log["hash"] == hashlib.sha256(test_log).hexdigest() and own_log["size_bytes"] == len(test_log)
            outputs = [x for x in helper["outputs"] if x.get("path") == helper["args"][2]]
            assert len(outputs) == 1
            own_xml = outputs[0]["digest"]
            assert own_xml["hash"] == hashlib.sha256(xml_bytes).hexdigest() and own_xml["size_bytes"] == len(xml_bytes)
            targets.append({"target": label, "rust_cases_passed": expected_count, "rust_cases_failed": 0, "rust_cases_ignored": 0, "filtered": 0, "required_original_controls": sorted(scopes[name]), "test_case_names": sorted(cases), "Bazel_XML_wrapper_cases": 1, "product_TestRunner": {k: product[k] for k in ("sequence", "args", "runner", "cache_hit", "exit_code", "timeout_millis")}, "XML_helper": {k: helper[k] for k in ("sequence", "args", "runner", "cache_hit", "exit_code", "timeout_millis")}, "XML_helper_own_input_test_log": own_log, "XML_helper_own_output_XML": own_xml})
        results.append({"artifact_id": aid, "job_id": jid, "checkout_kind": kind, "actual_checkout": checkout, "tree": TREE, "ordered_parents": parents, "official_ZIP": identity(archive_bytes), "all_10_member_CRC_and_hashes_equal": True, "full_original_job_log": identity(raw_log), "job_log_CR_count": raw_log.count(b"\r"), "captured_9_worktree_input_bindings": input_bindings, "original_command": expected_command, "full_compact_records": projection["record_count"], "full_compact_bytes": projection["decompressed_bytes"], "compact_invocation": projection["invocation"], "product_test_processes": 3, "XML_helper_processes": 3, "targets": targets, "per_checkout_rust_total": {"passed": 118, "failed": 0, "ignored": 0, "filtered": 0}})
    output = {"schema": "hepta-source17-native-Windows-business-libraries-offline-verification-v1", "current_product_head": HEAD, "current_product_tree": TREE, "actual_PR_merge": MERGE, "latest_API_observation_utc": "2026-11-06T10:43:51Z", "original_files_checked": len(freeze["files"]), "full_tree_leaves_checked": len(leaves), "blocking_cut": {"observed_before_utc": "2026-11-06T10:43:30Z", "run_id": 42201989815, "complete_jobs": 0}, "Supervisor_cut": {"observed_before_utc": "2026-11-06T10:43:30Z", "run_id": 42201989809, "complete_jobs": 2, "in_progress": 2}, "ordinary_business_results": results, "denominators": "118 original Rust cases per distinct checkout, not 236 distinct cases; three Bazel XML wrapper cases per checkout; three XML helpers are not test retries", "whole_candidate_qualified": False, "newly_closed_blockers": [], "limitations": ["These original library BUILD targets retain their existing qualification/test dependency replacements; this is not external producer acceptance.", "No B11 strict outside-delete or full-platform qualification follows from these three library targets.", "No result from old840 was transferred; this packet binds head17 and merge26cf directly.", "Offline replay runs only Python and zstd decoding, not Rust/Cargo/Bazel/native tests or CI."]}
    print(json.dumps(output, ensure_ascii=False, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
