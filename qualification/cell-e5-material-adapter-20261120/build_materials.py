"""Bind retained E5 source bytes without importing projects or running native code."""

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def read(path):
    return json.loads(path.read_bytes())


def blob(raw, output):
    sha = digest(raw)
    path = output / "blobs" / sha
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("content-address collision")
    else:
        path.write_bytes(raw)
    return {"sha256": sha, "bytes": len(raw)}


def bound(path, metadata, output):
    raw = path.read_bytes()
    if digest(raw) != metadata["sha256"] or len(raw) != metadata["bytes"]:
        raise ValueError("original snapshot changed: " + str(path))
    git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if git_sha != metadata["git_blob_sha1"]:
        raise ValueError("original Git blob identity differs: " + str(path))
    return blob(raw, output) | {"path": metadata["path"], "git_blob_sha1": git_sha}


def source_span(raw, node):
    lines = raw.splitlines(keepends=True)
    first = min([node.lineno, *[x.lineno for x in getattr(node, "decorator_list", [])]]) - 1
    return sum(map(len, lines[:first])), sum(map(len, lines[:node.end_lineno]))


def exact_patch(before, after, path, output):
    left, right = before.splitlines(keepends=True), after.splitlines(keepends=True)
    edits = []
    for tag, i, j, k, m in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag != "equal":
            start, end = sum(map(len, left[:i])), sum(map(len, left[:j]))
            edits.append({"before_start": start, "before_end": end,
                          "removed_sha256": digest(before[start:end]),
                          "replacement": blob(b"".join(right[k:m]), output)})
    diff = b"".join(difflib.diff_bytes(difflib.unified_diff, left, right,
                                     fromfile=("a/" + path).encode(),
                                     tofile=("b/" + path).encode()))
    return {"path": path, "before": blob(before, output), "after": blob(after, output),
            "edits": edits, "review_unified_diff": blob(diff, output),
            "authoritative_transport": "exact byte-range replacements; unified diff is review-only"}


def shape(before, after, patch):
    try:
        old, new = ast.parse(before), ast.parse(after)
    except (SyntaxError, UnicodeError) as error:
        return {"kind": "unparsed", "reason": str(error)}
    hits = []
    for node in old.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        start, end = source_span(before, node)
        if all(start <= e["before_start"] <= e["before_end"] <= end for e in patch["edits"]):
            matches = [x for x in new.body if isinstance(x, ast.FunctionDef) and x.name == node.name]
            if len(matches) == 1:
                first, last = source_span(after, matches[0])
                if before[:start] + after[first:last] + before[end:] == after:
                    hits.append({"kind": "one_top_level_function", "function": node.name,
                                 "before_function_bytes": end - start,
                                 "after_function_bytes": last - first,
                                 "closed_payload_bytes": last - first + len(b"```python\n```\n")})
    if len(hits) == 1:
        return hits[0]
    changed = []
    for node in old.body:
        start, end = source_span(before, node)
        if any(start <= e["before_start"] < end or start < e["before_end"] <= end for e in patch["edits"]):
            changed.append({"kind": type(node).__name__, "name": getattr(node, "name", None)})
    return {"kind": "requires_broader_transport", "changed_top_level_nodes": changed}


def runtime(path, roots):
    return not {"test", "tests"}.intersection(Path(path).parts) and any(
        path == root or path.startswith(root + "/") for root in roots)


def main(work, output):
    output.mkdir(exist_ok=False)
    prefix = read(work / "SOURCE_PREFIX_FREEZE.json")
    old_root = work / "input/old"
    original = {x["source_id"]: x for x in read(old_root / "SOURCES.json")["sources"]}
    ten_root = work / "input/ten"
    ten = {x["source_id"]: x for x in read(ten_root / "attempt-3/ACQUISITION_PLAN.json")["projects"]}
    two_root = work / "input/two"
    two = {x["source_id"]: x for x in read(two_root / "ACQUISITION_PLAN.json")["projects"]}
    old_roots = {"python-attrs/attrs": ["src/attr", "src/attrs"], "Textualize/rich": ["rich"],
                 "tox-dev/platformdirs": ["src/platformdirs"], "python-humanize/humanize": ["src/humanize"]}
    all_materials = []
    for frozen in prefix["materials"]:
        source_id, project = frozen["source_id"], frozen["project_id"]
        old = source_id in original
        if old:
            entry, root = original[source_id], old_root
            index = entry["project_id"].split("/")[-1]
            roots = old_roots[project]
            test_files = [entry["selected_tests"]["path"]]
            test_selector = " or ".join(entry["selected_tests"]["names"])
            notices = [entry["license"]["path"]]
            metadata = {v: [{"path": x["path"]} | x[v] for x in entry["source_files"]]
                        for v in ["before", "after"]}
            provenance_paths = [root / x for x in ["INTENT.json", "SOURCES.json", "REPLAY_DEPLOYMENT.json",
                                                   "replay-1/FREEZE.json", "replay-1/RESULT.json"]]
            provenance_paths += sorted((root / "upstream-api").glob("*.json"))
        else:
            if source_id in ten:
                entry = ten[source_id]
                root = ten_root / ("attempt-4" if entry["index"] in [7, 8] else "attempt-3")
                notices = [x["path"] for x in entry["licenses"]]
                selection = ten_root / "attempt-3/SELECTION_AUDIT.json"
            else:
                entry, root = two[source_id], two_root
                notices = ["LICENSE.txt"] if entry["index"] == 0 else ["LICENSE"]
                selection = work / "provenance/two-SELECTION_AUDIT.json"
            index, roots, test_files = entry["index"], entry["product_roots"], entry["test_files"]
            test_selector = entry["keyword"]
            metadata = {v: read(root / f"snapshots/{index}-{v}.json")["files"] for v in ["before", "after"]}
            provenance_paths = [root / "ACQUISITION_PLAN.json", selection, root / "replay-1/FREEZE.json",
                                root / "replay-1/RESULT.json", root / "identity-readback-1/READOUT.json"]
            provenance_paths += [root / f"snapshots/{index}-{v}.json" for v in ["before", "after"]]
            if source_id in ten:
                provenance_paths += [ten_root / "attempt-3/INTENT.json"]
                provenance_paths += sorted((ten_root / "attempt-3").glob("search_*.json"))
            else:
                provenance_paths += [root / x for x in ["BEFORE_REVISION_CORRECTION.json",
                    "METADATA_FREEZE.json", "NATIVE_CONTINUATION_INTENT.json", "SOURCE_REVIEW.json"]]
        for field in ["project_id", "before_commit", "after_commit"]:
            if entry[field] != frozen[field]:
                raise ValueError("prospective identity changed: " + source_id)
        snapshots = {}
        for variant in ["before", "after"]:
            folder = root / f"repositories/{index}/{variant}"
            snapshots[variant] = [bound(folder / x["path"], x, output) for x in metadata[variant]]
        by_path = {v: {x["path"]: x for x in snapshots[v]} for v in snapshots}
        paths = sorted(set(by_path["before"]) | set(by_path["after"]))
        patches = []
        for path in paths:
            if not runtime(path, roots):
                continue
            b = by_path["before"].get(path)
            a = by_path["after"].get(path)
            if b != a:
                before = (output / "blobs" / b["sha256"]).read_bytes() if b else b""
                after = (output / "blobs" / a["sha256"]).read_bytes() if a else b""
                patch = exact_patch(before, after, path, output)
                patch.update(before_exists=b is not None, after_exists=a is not None)
                patch["shape"] = shape(before, after, patch) if path.endswith(".py") else {"kind": "non_python"}
                patches.append(patch)
        native = {}
        for variant in ["before", "after"]:
            folder = root / f"replay-1/{index}-{variant}"
            native[variant] = {x.name: blob(x.read_bytes(), output) for x in sorted(folder.iterdir()) if x.is_file()}
        tested = []
        for path in test_files:
            data = by_path["after"][path]
            raw = (output / "blobs" / data["sha256"]).read_bytes()
            tree = ast.parse(raw)
            funcs = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in test_selector:
                    start, end = source_span(raw, node)
                    funcs.append({"name": node.name, "start_byte": start, "end_byte": end,
                                  "complete_function_with_decorators": blob(raw[start:end], output)})
            tested.append(data | {"original_functions": funcs,
                                  "generated_case_functions_possible": not bool(funcs)})
        bound_notices = []
        for path in notices:
            for variant in ["before", "after"]:
                if path in by_path[variant]:
                    bound_notices.append(by_path[variant][path] | {"variant": variant})
        for notice in entry.get("licenses", []):
            if not notice.get("external_notice"):
                continue
            matches = []
            for file in (ten_root / "attempt-3/notices").glob("*"):
                raw = file.read_bytes()
                git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                if git_sha == notice["sha"]:
                    matches.append(blob(raw, output) | {"path": notice["path"], "git_blob_sha1": git_sha,
                                   "variant": "external_original_notice", "commit": notice["commit"],
                                   "reason": notice["reason"], "original_archive_member": str(file.relative_to(work))})
            if len(matches) != 1:
                raise ValueError("exact separately retained notice required: " + project)
            bound_notices.extend(matches)
        if not bound_notices or not patches:
            raise ValueError("source requires original notice and changed runtime")
        provenance = [{"original_path": str(p.relative_to(work)), **blob(p.read_bytes(), output)} for p in provenance_paths]
        row = {"schema": "hepta.e5.lossless-repair-material.v1", **frozen,
               "complete_evidence_commit": "b6822f9afe283e1e1b4493173ee98cc2f740ef0a" if source_id in ten else frozen["evidence_commit"],
               "training_execution_admitted": False, "historical_agent_trajectory_available": False,
               "trajectory": None, "features": None, "runtime_roots": roots, "snapshots": snapshots,
               "runtime_patches": patches, "native_test_selector": test_selector, "native_test_files": tested,
               "license_notices": bound_notices, "native_receipts": native, "selection_and_source_provenance": provenance,
               "native_case_class_prefixes": {v: "" if old else f"replay-1.{index}-{v}.work." for v in ["before", "after"]},
               "snapshot_scope": "Original retained execution/source scope, not a whole-repository claim",
               "context_bytes": {"runtime_before": sum(x["bytes"] for x in snapshots["before"] if runtime(x["path"], roots)),
                   "changed_runtime_before": sum(x["before"]["bytes"] for x in patches),
                   "changed_runtime_after": sum(x["after"]["bytes"] for x in patches),
                   "complete_native_test_files": sum(x["bytes"] for x in tested),
                   "all_retained_before_snapshot": sum(x["bytes"] for x in snapshots["before"]),
                   "all_retained_after_fixtures": sum(x["bytes"] for x in snapshots["after"] if not runtime(x["path"], roots)),
                   "review_unified_patch": sum(x["review_unified_diff"]["bytes"] for x in patches)},
               "existing_codec": {"catalog_already_bound": old,
                   "shape_scope": "Byte transport analysis only; no native evaluation or model call",
                   "output_raw_bytes_limit": 32768,
                   "new_project_interface_required": not old,
                   "pinned_codec_sha256": "e1147a8d02624ca87b4a1f2f3345b034664b11b074f29787cb4b34085d4058c3"}}
        name = f"materials/{len(all_materials):02d}.json"
        raw = canonical(row) + b"\n"
        dest = output / name
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(raw)
        all_materials.append({"path": name, "sha256": digest(raw), "bytes": len(raw), "source_id": source_id})
        print(project, row["context_bytes"], [(x["path"], x["shape"]) for x in patches], flush=True)
    (output / "MATERIAL_INDEX.json").write_bytes(canonical({"schema": "hepta.e5.lossless-material-index.v1",
        "prefix_sha256": digest((work / "SOURCE_PREFIX_FREEZE.json").read_bytes()), "materials": all_materials}) + b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.work.resolve(), args.output.resolve())
