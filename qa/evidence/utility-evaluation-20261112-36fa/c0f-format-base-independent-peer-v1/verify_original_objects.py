#!/usr/bin/env python3
"""Offline identity/closure audit. Never imports an execution driver or invokes Git.

The native preparation directory supplies four immutable historical byte records.
All remote transport inputs are independently full-GET copies in --inputs. This
script verifies identities and snapshot closure, not current native availability.
"""
from __future__ import annotations

import argparse
import ast
import base64
import collections
import gzip
import hashlib
import json
from pathlib import Path

C0F = "c0f78493f815780f68b9bf5e390a21314d79311f"
C0F_TREE = "313ee34febc8ccc54c611ab56286e289518c63cb"
C0F_PARENTS = ["e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd", "b29869e856d08db1bfb066116a9c443376ccc57d"]
CC57 = "cc57c7198db6293ccca562253c42fffbe2a04633"
CC57_TREE = "b7b357c07b5539769a068c6b9b009629f5612d1e"
PARENT = "246d8cb614770252ee42029a5c014f2a4904176a"
PARENT_TREE = "d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087"
SOURCE_PINS = {
    "C0F_INVENTORY.json": (5474911, "cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57", "5ed18452e2e967281ac368f934b9e4358627b9d3"),
    "CC57_INVENTORY.json": (5611184, "13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9", "7f94788b70546a8b8030dfd2b9182a7d9287c537"),
    "TREE_AND_ANCHOR_RAW.json": (1987695, "8912bc39982001e1705ac027a197341fd9a722d75746a68e1da207fdcc4e19b8", "33de1f7a55eb040b9fe2cbace05e6bba401eb40e"),
    "MATERIALIZER_PACKET.original.json": (13764, "b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3", "06503652a2895120daf8b66e42b3a01cefeaf4fb"),
}
REMOTE_PINS = {
    "TRANSPORT_INPUT_MANIFEST.json": "828e7ee48826247d19068b706978689bebf630af",
    "FINAL_REVIEW_v2.json": "18773795962884bc4f9d5bda249866cfffa69a1c",
    "ENCODING_MANIFEST.json": "dd99fd9ccca77fab1765e8fae4f7172a8da666ac",
    "c0f.commit.raw": "81369bfd8e7bc48a9aea6ae8d2e60e10a6fbdc6b",
    "FORMAT.original.py": "d4eabe70b68605933240e9129245f7f4cccbde5d",
}


def require(condition, label):
    if not condition:
        raise ValueError(label)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def oid(kind, body):
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()


def identity(body):
    return {"bytes": len(body), "sha256": sha256(body), "git_blob": oid("blob", body)}


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique_pairs)


def check_identity(body, expected, label):
    actual = identity(body)
    for key in ("bytes", "sha256", "git_blob"):
        require(actual[key] == expected[key], f"{label}: {key} mismatch")
    return actual


def from_tuple(values):
    return dict(zip(("bytes", "sha256", "git_blob"), values))


def full_get_copy(inputs, name, expected_oid, receipts):
    body = (inputs / name).read_bytes()
    sdk_path = inputs / (name + ".GET.original.json")
    sdk = read_json(sdk_path)
    require(not sdk.get("isError", False), f"GET error: {name}")
    original_text = sdk["structuredContent"]["content"]
    require(isinstance(original_text, str), f"GET is not complete text: {name}")
    require(original_text.encode("utf-8") == body, f"GET content differs: {name}")
    require(oid("blob", body) == expected_oid, f"GET identity differs: {name}")
    receipts.append({"path": name, **identity(body), "actual_full_get_equal": True,
                     "local_original_sdk": {"path": str(sdk_path), **identity(sdk_path.read_bytes())}})
    return body


def unpack_bundle(inputs, bundle, receipts):
    chunks = []
    offset = 0
    for row in bundle["parts"]:
        body = full_get_copy(inputs, row["path"], row["git_blob"], receipts)
        check_identity(body, row, row["path"])
        require(body.endswith(b"\n") and body.count(b"\n") == 1, "base64 piece LF")
        chunk = base64.b64decode(body[:-1], validate=True)
        require(base64.b64encode(chunk) + b"\n" == body, "base64 not canonical")
        require(row["decoded_offset"] == offset, "noncontiguous transport")
        require(len(chunk) == row["decoded_bytes"], "decoded piece length")
        require(sha256(chunk) == row["decoded_sha256"], "decoded piece digest")
        chunks.append(chunk)
        offset += len(chunk)
    compressed = b"".join(chunks)
    check_identity(compressed, bundle["gzip"], "gzip")
    raw = gzip.decompress(compressed)
    check_identity(raw, bundle["raw"], "raw")
    require((inputs / bundle["gzip"]["path"]).read_bytes() == compressed, "recovered gzip file")
    require((inputs / bundle["raw"]["path"]).read_bytes() == raw, "recovered raw file")
    return {"parts": len(chunks), "gzip": identity(compressed), "raw": identity(raw)}


def object_meta(kind, object_id, body):
    return {"type": kind, "sha": object_id, "bytes": len(body), "sha256": sha256(body)}


def strict_object(row):
    kind = row["type"]
    require(kind in ("blob", "tree", "commit"), "unexpected object type")
    body = base64.b64decode(row["raw_base64"], validate=True)
    require(base64.b64encode(body).decode("ascii") == row["raw_base64"], "noncanonical object base64")
    require(object_meta(kind, oid(kind, body), body) == {key: row[key] for key in ("type", "sha", "bytes", "sha256")}, "object body/type/hash mismatch")
    return body


def add_object(mapping, row):
    key = row["sha"]
    if key in mapping:
        require(mapping[key] == row, f"same OID has conflicting metadata: {key}")
    else:
        mapping[key] = row


def parse_commit(body, commit, tree, parents):
    require(oid("commit", body) == commit, "raw commit object hash")
    header, message = body.split(b"\n\n", 1)
    lines = header.split(b"\n")
    require(lines[0] == b"tree " + tree.encode(), "raw commit tree")
    observed_parents = [line[7:].decode("ascii") for line in lines if line.startswith(b"parent ")]
    require(observed_parents == parents, "raw commit parents")
    require(len([line for line in lines if line.startswith(b"author ")]) == 1, "raw author")
    require(len([line for line in lines if line.startswith(b"committer ")]) == 1, "raw committer")
    require(bool(message), "empty commit message")
    return {"type": "commit", "sha": commit, "tree": tree, "parents": parents,
            "bytes": len(body), "sha256": sha256(body), "raw_file_git_blob": oid("blob", body),
            "ends_with_lf": body.endswith(b"\n")}


def inventory_rows(document, commit, tree, count):
    require(document["source"] == {"head": commit, "tree": tree, "status": ""}, "inventory source")
    require(document["tracked_entries"] == document["filesystem_entries"] == count, "inventory counts")
    rows = {}
    for row in document["files"]:
        path = row["path"]
        parts = path.split("/")
        require(path not in rows and all(part not in ("", ".", "..") for part in parts), "duplicate/unsafe path")
        require("\0" not in path and "\\" not in path, "unsafe path bytes")
        require(row["matches_index"] is True and row["stable"] is True, "historical inventory not clean/stable")
        require(row["index_blob"] == row["working_blob"], "index/working OID mismatch")
        require(row["index_mode"] in ("100644", "100755", "120000"), "unexpected leaf mode")
        require(row["kind"] == ("symlink" if row["index_mode"] == "120000" else "file"), "mode/kind mismatch")
        rows[path] = {"mode": row["index_mode"], "sha": row["working_blob"], "bytes": row["bytes"], "sha256": row["sha256"]}
    require(len(rows) == count, "inventory leaf count")
    return rows


def blob_metas(rows):
    result = {}
    paths = collections.defaultdict(list)
    for path, row in rows.items():
        add_object(result, {"type": "blob", "sha": row["sha"], "bytes": row["bytes"], "sha256": row["sha256"]})
        paths[row["sha"]].append(path)
    return result, {key: sorted(value) for key, value in paths.items()}


def parse_tree(body):
    entries = []
    offset = 0
    seen = set()
    while offset < len(body):
        space = body.index(b" ", offset)
        nul = body.index(b"\0", space + 1)
        require(nul + 21 <= len(body), "truncated tree entry")
        mode, name = body[offset:space], body[space + 1:nul]
        require(mode in (b"40000", b"100644", b"100755", b"120000"), "unsupported tree mode")
        require(name and name not in (b".", b"..") and b"/" not in name and b"\\" not in name, "unsafe tree entry")
        require(name not in seen, "duplicate tree name")
        seen.add(name)
        name.decode("utf-8", errors="strict")
        entries.append((mode, name, body[nul + 1:nul + 21].hex()))
        offset = nul + 21
    require(offset == len(body), "tree trailing data")
    keys = [name + (b"/" if mode == b"40000" else b"\0") for mode, name, _ in entries]
    require(keys == sorted(keys), "noncanonical Git tree ordering")
    return entries


def traverse_original_tree(root, raw_objects):
    leaves, reachable = {}, {}
    def walk(object_id, prefix, ancestors):
        require(object_id not in ancestors, "tree cycle")
        kind, body = raw_objects[object_id]
        require(kind == "tree", "tree edge to wrong object type")
        reachable[object_id] = body
        for mode, name, child in parse_tree(body):
            path = prefix + name.decode("utf-8")
            if mode == b"40000":
                walk(child, path + "/", ancestors | {object_id})
            else:
                require(path not in leaves, "duplicate flattened tree leaf")
                leaves[path] = {"mode": mode.decode("ascii"), "sha": child}
    walk(root, "", set())
    return leaves, reachable


def construct_trees(rows):
    trie = {}
    for path, row in rows.items():
        parts = path.split("/")
        node = trie
        for component in parts[:-1]:
            node = node.setdefault(component, {})
            require(isinstance(node, dict), "tree/leaf conflict")
        require(parts[-1] not in node, "duplicate reconstructed path")
        node[parts[-1]] = (row["mode"], row["sha"])
    trees = {}
    def visit(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                entries.append((b"40000", name.encode("utf-8"), visit(value)))
            else:
                mode, child = value
                entries.append((mode.encode("ascii"), name.encode("utf-8"), child))
        entries.sort(key=lambda entry: entry[1] + (b"/" if entry[0] == b"40000" else b"\0"))
        body = b"".join(mode + b" " + name + b"\0" + bytes.fromhex(child) for mode, name, child in entries)
        object_id = oid("tree", body)
        if object_id in trees:
            require(trees[object_id] == body, "tree content conflict")
        trees[object_id] = body
        return object_id
    return visit(trie), trees


def counts(objects):
    result = dict(collections.Counter(row["type"] for row in objects.values()))
    result["total"] = len(objects)
    return result


def rows_to_map(rows):
    result = {}
    for row in rows:
        require(row["sha"] not in result, "duplicate manifest object")
        result[row["sha"]] = {key: row[key] for key in ("type", "sha", "bytes", "sha256")}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--historical-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "create-only output already exists")
    receipts = []
    for name, expected in REMOTE_PINS.items():
        full_get_copy(args.inputs, name, expected, receipts)
    transport = read_json(args.inputs / "TRANSPORT_INPUT_MANIFEST.json")
    encoding = read_json(args.inputs / "ENCODING_MANIFEST.json")
    encoded_results = [unpack_bundle(args.inputs, transport, receipts)]
    encoded_results += [unpack_bundle(args.inputs, bundle, receipts) for bundle in encoding["bundles"][:2]]
    require(len(receipts) == 27 and len({row["path"] for row in receipts}) == 27, "full GET coverage")
    documents, historical_pins = {}, []
    for name, fixed in SOURCE_PINS.items():
        path = args.historical_records / name
        body = path.read_bytes()
        check_identity(body, from_tuple(fixed), name)
        historical_pins.append({"path": str(path), **identity(body), "meaning": "frozen historical bytes, not new native observation"})
        documents[name] = read_json(path)
    base_inventory = inventory_rows(documents["C0F_INVENTORY.json"], C0F, C0F_TREE, 14851)
    current_inventory = inventory_rows(documents["CC57_INVENTORY.json"], CC57, CC57_TREE, 15188)
    raw_objects, raw_record_count = {}, 0
    for group in documents["TREE_AND_ANCHOR_RAW.json"].values():
        for row in group:
            body = strict_object(row)
            original = (row["type"], body)
            if row["sha"] in raw_objects:
                require(raw_objects[row["sha"]] == original, "historical raw overlap conflict")
            raw_objects[row["sha"]] = original
            raw_record_count += 1
    leaves, base_trees = traverse_original_tree(C0F_TREE, raw_objects)
    require(leaves == {path: {"mode": row["mode"], "sha": row["sha"]} for path, row in base_inventory.items()}, "raw c0f tree does not match all original inventory leaves")
    base_blobs, base_paths = blob_metas(base_inventory)
    base = dict(base_blobs)
    for object_id, body in base_trees.items():
        add_object(base, object_meta("tree", object_id, body))
    base_commit = (args.inputs / "c0f.commit.raw").read_bytes()
    base_commit_review = parse_commit(base_commit, C0F, C0F_TREE, C0F_PARENTS)
    require(raw_objects[C0F] == ("commit", base_commit), "raw c0f commit does not equal original retained commit")
    add_object(base, object_meta("commit", C0F, base_commit))
    require(counts(base) == {"blob": 14315, "tree": 1778, "commit": 1, "total": 16094}, "base exact counts")
    closure = read_json(args.inputs / "C0F_CLOSURE_IDENTITIES.json")
    require(closure["commit"] == C0F and closure["tree"] == C0F_TREE and closure["parents"] == C0F_PARENTS, "closure anchors")
    require(closure["snapshot_only_not_ancestry"] is True and closure["leaves"] == 14851, "closure declared scope")
    require(rows_to_map(closure["objects"]) == base, "complete closure metadata differs from independent traversal")
    for row in closure["objects"]:
        if row["type"] == "blob":
            require(row["paths"] == base_paths[row["sha"]], "closure blob occurrence paths")
    prior_packet = documents["MATERIALIZER_PACKET.original.json"]
    require(prior_packet["current"]["commit"] == CC57 and prior_packet["current"]["tree"] == CC57_TREE, "current packet anchor")
    require(prior_packet["parent_snapshot"]["commit"] == PARENT and prior_packet["parent_snapshot"]["tree"] == PARENT_TREE, "parent packet anchor")
    require(prior_packet["current"]["inventory"] == from_tuple(SOURCE_PINS["CC57_INVENTORY.json"]), "current inventory packet pin")
    parent_inventory = {key: dict(value) for key, value in current_inventory.items()}
    substitutions = prior_packet["parent_snapshot"]["changes_from_current"]
    require(len(substitutions) == 5 and len({row["path"] for row in substitutions}) == 5, "exact five parent substitutions")
    for row in substitutions:
        require(current_inventory[row["path"]] == {"mode": row["mode"], "sha": row["current"]["git_blob"], "bytes": row["current"]["bytes"], "sha256": row["current"]["sha256"]}, "substitution before-image")
        parent_inventory[row["path"]] = {"mode": row["mode"], "sha": row["parent"]["git_blob"], "bytes": row["parent"]["bytes"], "sha256": row["parent"]["sha256"]}
    current_root, current_trees = construct_trees(current_inventory)
    parent_root, parent_trees = construct_trees(parent_inventory)
    require(current_root == CC57_TREE and parent_root == PARENT_TREE, "independent current/parent Merkle roots")
    existing = {}
    for rows in (current_inventory, parent_inventory):
        blobs, _ = blob_metas(rows)
        for row in blobs.values():
            add_object(existing, row)
    existing_trees = dict(current_trees)
    for object_id, body in parent_trees.items():
        if object_id in existing_trees:
            require(existing_trees[object_id] == body, "existing tree overlap")
        existing_trees[object_id] = body
    for object_id, body in existing_trees.items():
        add_object(existing, object_meta("tree", object_id, body))
    commits = {}
    for row in prior_packet["raw_commits"]:
        body = strict_object(row)
        require(row["type"] == "commit" and row["sha"] not in commits, "existing commits list")
        expected = prior_packet["current"] if row["sha"] == CC57 else prior_packet["parent_snapshot"]
        require(row["sha"] == expected["commit"], "unexpected existing commit")
        commits[row["sha"]] = parse_commit(body, expected["commit"], expected["tree"], expected["parents"])
        add_object(existing, object_meta("commit", row["sha"], body))
    require(set(commits) == {CC57, PARENT}, "two original commit bodies")
    require(counts(existing) == {"blob": 14615, "tree": 1832, "commit": 2, "total": 16449}, "two-snapshot exact counts")
    shared = set(base) & set(existing)
    provided_set = set(base) - set(existing)
    require(len(shared) == 16011 and len(provided_set) == 83 and len(set(base) | set(existing)) == 16532, "exact set counts")
    for object_id in shared:
        require(base[object_id] == existing[object_id], "shared metadata mismatch")
        if base[object_id]["type"] == "tree":
            require(base_trees[object_id] == existing_trees[object_id], "shared tree body mismatch")
    full_packet = read_json(args.inputs / "BASE_OBJECT_PACKET.json")
    compact = read_json(args.inputs / "BASE_OBJECT_INPUT.json")
    require(full_packet["base"] == compact["base"], "base anchors differ between packets")
    require(compact["base"] == {"commit": C0F, "tree": C0F_TREE, "parents": C0F_PARENTS, "leaves": 14851, "inventory": from_tuple(SOURCE_PINS["C0F_INVENTORY.json"])}, "base packet original identity")
    require(full_packet["provided_objects"] == compact["objects"], "full/compact provided rows differ")
    require(compact["provided_count"] == 83 and compact["required_existing_count"] == full_packet["required_existing_count"] == 16011, "packet counts")
    require(rows_to_map(full_packet["required_existing_objects"]) == {key: base[key] for key in shared}, "required-existing exact closed set differs")
    provided = rows_to_map(compact["objects"])
    require(provided == {key: base[key] for key in provided_set}, "83 provided objects are not exact base-only difference")
    byte_reviews = []
    for row in compact["objects"]:
        body = strict_object(row)
        if row["type"] == "tree":
            require(body == base_trees[row["sha"]], "provided tree differs from retained original bytes")
        elif row["type"] == "commit":
            require(body == base_commit, "provided commit bytes differ")
        else:
            require(row["paths"] == base_paths[row["sha"]], "provided blob occurrence paths")
        byte_reviews.append({**provided[row["sha"]], "raw_body_equal_to_its_declared_git_object": True,
                             "paths": row.get("paths", []), "membership": "base_only_exact_difference"})
    require(counts(provided) == {"blob": 72, "tree": 10, "commit": 1, "total": 83}, "provided type counts")
    shared_rows = {key: base[key] for key in shared}
    require(counts(shared_rows) == {"blob": 14243, "tree": 1768, "total": 16011}, "shared type counts")
    require(sum(row["bytes"] for row in provided.values() if row["type"] == "blob") == 2216414, "provided blob raw size")
    require(full_packet["comparison_scope"]["ancestry_complete"] is False, "improper ancestry claim")
    require(full_packet["comparison_scope"]["current_native_availability_observed_by_this_preparation"] is False, "improper availability claim")
    for document in (full_packet, compact):
        require(document["source_mutation"] is False and document["native_execution"] is False, "improper execution claim")
    format_source = (args.inputs / "FORMAT.original.py").read_text()
    syntax = ast.parse(format_source)
    functions = {node.name: node for node in syntax.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    format_git_arrays = []
    for node in ast.walk(syntax):
        if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "git":
            format_git_arrays.append(ast.get_source_segment(format_source, node))
    require(len(format_git_arrays) == 6, "unexpected formatter Git call inventory")
    git_functions = [name for name, function in functions.items() if any(
        isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "git" for node in ast.walk(function))]
    require(set(git_functions) == {"buildifier_formatter_group", "changed_paths", "formatting_configuration_changed", "rust_configuration_scope"}, "formatter Git function inventory")
    all_git_literals = [node.value for array in ast.walk(syntax) if isinstance(array, ast.List) and array.elts and isinstance(array.elts[0], ast.Constant) and array.elts[0].value == "git" for node in ast.walk(array) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    require(not {"merge-base", "rev-list", "log", "fsck", "fetch"} & set(all_git_literals), "formatter uses history/network command")
    part_bytes = sum(row["bytes"] for row in transport["parts"])
    report = {
        "schema": "hepta-c0f-format-base-independent-byte-audit-v1",
        "status": "STATIC_OBJECTS_AND_SNAPSHOT_CLOSURES_VERIFIED_EXECUTION_HOLD",
        "method": "Parse original c0f raw trees recursively; independently build cc57/246d Merkle trees from two frozen inventories and five exact substitutions; compare every object metadata and shared tree body; verify all 83 provided raw object bodies. No native driver imported or executed.",
        "remote_complete_gets": receipts,
        "remote_complete_get_count": len(receipts),
        "encoded_bundles": encoded_results,
        "historical_byte_inputs": historical_pins,
        "historical_raw_records_checked": raw_record_count,
        "historical_unique_raw_objects_checked": len(raw_objects),
        "base_commit": base_commit_review,
        "base": {"counts": counts(base), "leaves": len(leaves), "full_raw_tree_traversal_matches_original_inventory": True, "all_manifest_objects_equal": True},
        "existing": {"counts": counts(existing), "commits": list(commits.values()), "current_tree": current_root, "parent_tree": parent_root, "current_leaves": len(current_inventory), "parent_leaves": len(parent_inventory), "exact_parent_substitutions": [row["path"] for row in substitutions]},
        "shared": {"counts": counts(shared_rows), "all_metadata_equal": True, "all_1768_shared_tree_bodies_equal": True, "exact_sorted_metadata_sha256": sha256(json_bytes(sorted(shared_rows.values(), key=lambda row: row["sha"])))},
        "provided": {"counts": counts(provided), "blob_raw_bytes": 2216414, "exact_set_difference": True, "rows": byte_reviews},
        "expected_object_union": len(set(base) | set(existing)),
        "format_source": {"git_blob": REMOTE_PINS["FORMAT.original.py"], "git_argv_source_expressions": format_git_arrays, "functions_read": git_functions, "ancestry_traversal_required_by_these_git_calls": False},
        "request_size": {"unchanged_limit_bytes": 1048576, "four_encoded_parts_total_bytes": part_bytes, "arithmetic_remaining_before_any_wrapper_or_other_payload": 1048576 - part_bytes, "final_typed_request_supplied": False, "final_serialized_request_size_verified": False},
        "scope_limits": [
            "Snapshot closure excludes recursive parent history. Original parent OIDs, authors, time zones, messages and raw bytes remain intact; no shallow/grafts/replace/alternates fabrication.",
            "Shared blob bytes are constrained by the historical full inventory identities; this audit is not a new native read of the 16011 shared objects and does not establish present availability.",
            "All 83 supplied raw bodies are independently content-address verified. Neither the author recovery script nor any formatter, materializer, gate or H command was executed.",
            "Original format base and just fmt --base c0f budget remain unchanged. Future current worktree/index, source closure, runtime tools and source gate results still require their own actual proof.",
            "A successor loader, approved destination/current packet and complete typed request have not been supplied. Old-source/index/ref/object-store read-only enforcement and final 1 MiB request size remain explicit execution HOLD conditions.",
        ],
        "execution": {"H": 0, "native": 0, "formatter": 0, "Rust_or_QA_tests": 0, "source_or_ref_mutations": 0, "pure_offline_audit_only": True},
    }
    with args.output.open("xb") as output:
        output.write(json_bytes(report))
    print(json.dumps({"status": report["status"], "base": report["base"]["counts"], "existing": report["existing"]["counts"], "provided": report["provided"]["counts"], "shared": report["shared"]["counts"], "union": report["expected_object_union"], "full_gets": len(receipts), "output": identity(args.output.read_bytes())}, sort_keys=True))


if __name__ == "__main__":
    main()
