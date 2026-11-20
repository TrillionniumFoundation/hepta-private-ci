"""Verify frozen E5 materials without importing upstream code or calling a model."""

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

PREFIX_SHA256 = "1319a7884200321c108f08bae4c48e9a0e6417b9eb00b34cb1b9d12c0bf38a69"
IDENTITY_FIELDS = ("source_id", "project_id", "before_commit", "after_commit")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def safe_relative(path):
    value = PurePosixPath(path)
    require(not value.is_absolute() and str(value) == path and ".." not in value.parts, "unsafe input path")
    return path


def checked_blob(binding, blobs):
    digest = binding["sha256"]
    require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "invalid blob key")
    require(digest in blobs, "missing bound bytes")
    raw = blobs[digest]
    require(len(raw) == binding["bytes"] and sha(raw) == digest, "bound bytes changed")
    if "git_blob_sha1" in binding:
        git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(git_sha == binding["git_blob_sha1"], "original Git blob changed")
    return raw


def reconstruct(before, patch, blobs):
    cursor, result = 0, []
    for edit in patch["edits"]:
        start, end = edit["before_start"], edit["before_end"]
        require(type(start) is int and type(end) is int and cursor <= start <= end <= len(before), "invalid patch span")
        require(sha(before[start:end]) == edit["removed_sha256"], "patch preimage differs")
        result += [before[cursor:start], checked_blob(edit["replacement"], blobs)]
        cursor = end
    return b"".join(result + [before[cursor:]])


def is_runtime(path, roots):
    return not {"tests", "test"}.intersection(PurePosixPath(path).parts) and any(
        path == root or path.startswith(root + "/") for root in roots)


def native_receipt(row, variant, blobs):
    evidence = row["native_receipts"][variant]
    required = {"EXIT.json", "PYTEST_INTENT.json", "PYTEST_RETURN.json", "junit.xml", "STDOUT.txt", "STDERR.txt"}
    require(required.issubset(evidence), "incomplete native originals")
    raw = {name: checked_blob(value, blobs) for name, value in evidence.items()}
    receipt, intent, returned = [decode(raw[name]) for name in ["EXIT.json", "PYTEST_INTENT.json", "PYTEST_RETURN.json"]]
    require(receipt["project_id"] == intent["project_id"] == row["project_id"], "native project differs")
    require(receipt["revision"] == intent["revision"] == row[variant + "_commit"], "native revision differs")
    require(receipt["variant"] == intent["variant"] == variant, "native variant differs")
    require(receipt["wait_returncode"] == returned["exit_code"], "native exit receipts disagree")
    for name, key in [("junit.xml", "junit_sha256"), ("STDOUT.txt", "stdout_sha256"), ("STDERR.txt", "stderr_sha256")]:
        require(sha(raw[name]) == receipt[key], "native original output changed")
    require(not receipt["timed_out"] and receipt["errors"] == 0, "native outer timeout or error")
    if variant == "before":
        require(receipt["wait_returncode"] == 1 and receipt["failures"] > 0, "original failure absent")
    else:
        require(receipt["wait_returncode"] == 0 and receipt["failures"] == 0 and receipt["passed"] > 0, "original success absent")
    tests = {x["path"]: x for x in row["native_test_files"]}
    if "test_files" in intent:
        require(intent["after_tests_and_fixtures_unchanged"] and intent["full_selected_function_parameter_sets"], "native fixture guarantee absent")
        require({x["path"]: x["sha256"] for x in intent["test_files"]} == {p: x["sha256"] for p, x in tests.items()}, "original test file set changed")
        require(returned["execution_inputs_unchanged"], "native input mutation")
        require("EXECUTION_MANIFEST.json" in raw, "native execution manifest absent")
        manifest = decode(raw["EXECUTION_MANIFEST.json"])
        variants = {v: {x["path"]: x for x in row["snapshots"][v]} for v in ["before", "after"]}
        expected = {}
        for path in set(variants[variant]) | set(variants["after"]):
            source = variants[variant] if is_runtime(path, row["runtime_roots"]) else variants["after"]
            if path in source:
                expected[path] = source[path]["sha256"]
        require(len({x["path"] for x in manifest}) == len(manifest), "duplicate execution input")
        require({x["path"]: x["sha256"] for x in manifest} == expected, "native fixture/runtime graph changed")
    else:
        require(len(tests) == 1 and intent["original_test_file_unchanged"], "original test guarantee absent")
        require(intent["original_test_sha256"] == next(iter(tests.values()))["sha256"], "original test changed")
    cases = list(ET.fromstring(raw["junit.xml"]).iter("testcase"))
    counts = {"tests": len(cases), "failures": sum(x.find("failure") is not None for x in cases),
              "errors": sum(x.find("error") is not None for x in cases), "skipped": sum(x.find("skipped") is not None for x in cases)}
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    require(all(receipt[k] == value for k, value in counts.items()), "JUnit cardinality/status differs")
    require([(x.get("classname"), x.get("name")) for x in cases] == [(x["class"], x["name"]) for x in receipt["cases"]], "JUnit identities differ from receipt")
    prefix = row["native_case_class_prefixes"][variant]
    normalized = [(x.get("classname", "").removeprefix(prefix) if prefix else x.get("classname", ""), x.get("name")) for x in cases]
    return counts | {"identities": normalized}


def verify_material(row, frozen, blobs):
    require(row["schema"] == "hepta.e5.lossless-repair-material.v1", "wrong material schema")
    require(all(row[key] == frozen[key] for key in IDENTITY_FIELDS), "frozen material identity changed")
    require(row["trajectory"] is None and row["features"] is None and not row["training_execution_admitted"], "fabricated model interface or execution admission")
    require(not row["historical_agent_trajectory_available"], "maintainer history relabeled as trajectory")
    provenance = {p["original_path"]: decode(checked_blob(p, blobs)) for p in row["selection_and_source_provenance"]}
    require(len(provenance) == len(row["selection_and_source_provenance"]), "duplicate provenance path")
    plans = [v for path, v in provenance.items() if path.endswith("/ACQUISITION_PLAN.json")]
    if plans:
        require(len(plans) == 1, "ambiguous acquisition plan")
        entries = [x for x in plans[0]["projects"] if x["source_id"] == row["source_id"]]
        require(len(entries) == 1, "source absent from acquisition plan")
        entry = entries[0]
        require(all(entry[key] == row[key] for key in IDENTITY_FIELDS), "source differs from acquisition plan")
        require(row["runtime_roots"] == entry["product_roots"] and row["native_test_selector"] == entry["keyword"], "original runtime scope or selector changed")
        require([x["path"] for x in row["native_test_files"]] == entry["test_files"], "original selected test files changed")
        require(row["native_case_class_prefixes"] == {v: f"replay-1.{entry['index']}-{v}.work." for v in ["before", "after"]}, "case normalization scope changed")
        require(any(path.endswith("SELECTION_AUDIT.json") for path in provenance), "original selection audit absent")
        required_notices = {x["path"] for x in entry.get("licenses", [])}
        if not required_notices:
            require(row["project_id"] in ["coady/multimethod", "SethMMorton/natsort"], "undeclared license catalog")
            required_notices = {"LICENSE.txt" if row["project_id"] == "coady/multimethod" else "LICENSE"}
    else:
        catalogs = [v for path, v in provenance.items() if path.endswith("/SOURCES.json")]
        require(len(catalogs) == 1 and any(path.endswith("/INTENT.json") for path in provenance), "original selection/source catalog absent")
        entries = [x for x in catalogs[0]["sources"] if x["source_id"] == row["source_id"]]
        require(len(entries) == 1, "source absent from original catalog")
        entry = entries[0]
        roots = {"python-attrs/attrs": ["src/attr", "src/attrs"], "Textualize/rich": ["rich"],
                 "tox-dev/platformdirs": ["src/platformdirs"], "python-humanize/humanize": ["src/humanize"]}
        require(row["runtime_roots"] == roots[row["project_id"]], "original runtime scope changed")
        require(row["native_test_selector"] == " or ".join(entry["selected_tests"]["names"]), "original selector changed")
        require([x["path"] for x in row["native_test_files"]] == [entry["selected_tests"]["path"]], "original test selection changed")
        require(row["native_case_class_prefixes"] == {"before": "", "after": ""}, "old case normalization changed")
        required_notices = {entry["license"]["path"]}
    require(required_notices == {x["path"] for x in row["license_notices"]}, "incomplete or extra license notice set")
    snapshots = {}
    for variant in ["before", "after"]:
        rows = row["snapshots"][variant]
        paths = [safe_relative(x["path"]) for x in rows]
        require(len(set(paths)) == len(paths), "duplicate original source file")
        snapshots[variant] = {x["path"]: checked_blob(x, blobs) for x in rows}
        originals = [v for path, v in provenance.items() if path.endswith(f"-{variant}.json") and "/snapshots/" in path]
        if originals:
            require(len(originals) == 1, "ambiguous original snapshot")
            original = originals[0]
            require(original.get("revision", original.get("commit")) == row[variant + "_commit"], "original snapshot revision changed")
            expected = original["files"]
        else:
            catalogs = [v for path, v in provenance.items() if path.endswith("/SOURCES.json")]
            require(len(catalogs) == 1, "original catalog absent")
            entries = [x for x in catalogs[0]["sources"] if x["source_id"] == row["source_id"]]
            require(len(entries) == 1, "ambiguous original source")
            expected = [{"path": x["path"]} | x[variant] for x in entries[0]["source_files"]]
        keys = ("path", "bytes", "sha256", "git_blob_sha1")
        require([{k: x[k] for k in keys} for x in rows] == [{k: x[k] for k in keys} for x in expected], "retained source inventory changed")
    all_paths = set(snapshots["before"]) | set(snapshots["after"])
    changed = {p for p in all_paths if is_runtime(p, row["runtime_roots"]) and snapshots["before"].get(p) != snapshots["after"].get(p)}
    require(changed and changed == {p["path"] for p in row["runtime_patches"]}, "incomplete or extra runtime repair")
    require(len(changed) == len(row["runtime_patches"]), "duplicate runtime patch")
    for patch in row["runtime_patches"]:
        path = patch["path"]
        before, after = [checked_blob(patch[v], blobs) for v in ["before", "after"]]
        require(all(patch[v + "_exists"] == (path in snapshots[v]) for v in ["before", "after"]), "file existence transport changed")
        require(before == snapshots["before"].get(path, b"") and after == snapshots["after"].get(path, b""), "patch source binding differs")
        require(reconstruct(before, patch, blobs) == after, "patch does not reconstruct exact after bytes")
        checked_blob(patch["review_unified_diff"], blobs)
    require(row["native_test_files"] and row["license_notices"], "test or license notice absent")
    for test in row["native_test_files"]:
        raw = checked_blob(test, blobs)
        require(raw == snapshots["after"][test["path"]], "test differs from complete original after file")
        nodes = list(ast.walk(ast.parse(raw)))
        lines = raw.splitlines(keepends=True)
        complete = []
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in row["native_test_selector"]:
                first = min([node.lineno, *[x.lineno for x in node.decorator_list]]) - 1
                complete.append((node.name, sum(map(len, lines[:first])), sum(map(len, lines[:node.end_lineno]))))
        require([(x["name"], x["start_byte"], x["end_byte"]) for x in test["original_functions"]] == complete, "original function/decorator inventory changed")
        for fn in test["original_functions"]:
            require(raw[fn["start_byte"]:fn["end_byte"]] == checked_blob(fn["complete_function_with_decorators"], blobs), "test function excerpt changed")
            spans = []
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn["name"]:
                    first = min([node.lineno, *[x.lineno for x in node.decorator_list]]) - 1
                    spans.append((sum(map(len, lines[:first])), sum(map(len, lines[:node.end_lineno]))))
            require((fn["start_byte"], fn["end_byte"]) in spans, "truncated original function/decorators")
    for notice in row["license_notices"]:
        raw = checked_blob(notice, blobs)
        if notice["variant"] in snapshots:
            require(raw == snapshots[notice["variant"]][notice["path"]], "license differs from source")
        else:
            plans = [v for path, v in provenance.items() if path.endswith("/ACQUISITION_PLAN.json")]
            declarations = [n for plan in plans for entry in plan["projects"] if entry["source_id"] == row["source_id"] for n in entry.get("licenses", [])]
            require(any(n.get("external_notice") and n["path"] == notice["path"] and n["sha"] == notice["git_blob_sha1"] and n["commit"] == notice["commit"] for n in declarations), "unbound external original license")
    original_runs = [v for path, v in provenance.items() if path.endswith("/replay-1/RESULT.json")]
    require(len(original_runs) == 1, "original replay result absent")
    for variant in ["before", "after"]:
        originals = [x for x in original_runs[0]["stages"] if x["project_id"] == row["project_id"] and x["variant"] == variant]
        require(len(originals) == 1 and originals[0] == decode(checked_blob(row["native_receipts"][variant]["EXIT.json"], blobs)), "native exit differs from retained original replay")
    before, after = [native_receipt(row, v, blobs) for v in ["before", "after"]]
    require(before["identities"] == after["identities"], "full parameter case identities differ")
    sizes = {"runtime_before": sum(len(b) for p, b in snapshots["before"].items() if is_runtime(p, row["runtime_roots"])),
             "changed_runtime_before": sum(p["before"]["bytes"] for p in row["runtime_patches"]),
             "changed_runtime_after": sum(p["after"]["bytes"] for p in row["runtime_patches"]),
             "complete_native_test_files": sum(x["bytes"] for x in row["native_test_files"]),
             "all_retained_before_snapshot": sum(map(len, snapshots["before"].values())),
             "all_retained_after_fixtures": sum(len(b) for p, b in snapshots["after"].items() if not is_runtime(p, row["runtime_roots"])),
             "review_unified_patch": sum(p["review_unified_diff"]["bytes"] for p in row["runtime_patches"])}
    require(row["context_bytes"] == sizes, "context size report changed")
    return {"source_id": row["source_id"], "project_id": row["project_id"], "lossless_material_admitted": True,
            "native_cases_per_variant": before["tests"], "original_before_failures": before["failures"],
            "original_after_passed": after["passed"], "original_after_skipped": after["skipped"],
            "runtime_patch_files": len(row["runtime_patches"]), "context_bytes": row["context_bytes"],
            "existing_codec": row["existing_codec"], "patch_shapes": [p["shape"] for p in row["runtime_patches"]]}


def verify(root, prefix_path):
    prefix_raw = prefix_path.read_bytes()
    require(sha(prefix_raw) == PREFIX_SHA256, "prospective prefix freeze changed")
    frozen = decode(prefix_raw)
    ids = [x["source_id"] for x in frozen["materials"]]
    require(ids == sorted(ids) and len(ids) == len(set(ids)) == 16, "original case-sensitive source order differs")
    require(frozen["prefixes"] == {str(n): ids[:n] for n in [1, 4, 16]}, "source prefix differs")
    index = decode((root / "MATERIAL_INDEX.json").read_bytes())
    require(index["prefix_sha256"] == PREFIX_SHA256, "index prefix binding changed")
    require([x["source_id"] for x in index["materials"]] == ids, "source matrix changed")
    blobs = {p.name: p.read_bytes() for p in (root / "blobs").iterdir() if p.is_file()}
    require(all(sha(raw) == key for key, raw in blobs.items()), "payload content-address changed")
    results = []
    for binding, original in zip(index["materials"], frozen["materials"], strict=True):
        path = root / safe_relative(binding["path"])
        raw = path.read_bytes()
        require(len(raw) == binding["bytes"] and sha(raw) == binding["sha256"], "material record changed")
        results.append(verify_material(decode(raw), original, blobs))
    return {"schema": "hepta.e5.lossless-admission-readout.v1", "source_prefix_sha256": PREFIX_SHA256,
            "materials": results, "material_count": len(results), "new_native_children": 0,
            "model_calls": 0, "training_updates": 0, "training_execution_admitted": False,
            "source_growth_qualified": False, "token_counts_measured": False,
            "unexposed_B_C_admitted": False, "actual_compute_match_established": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root, args.prefix)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "materials"}, sort_keys=True))
