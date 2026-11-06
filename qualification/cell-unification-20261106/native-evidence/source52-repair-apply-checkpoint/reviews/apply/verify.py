#!/usr/bin/env python3
"""Offline, read-only verification of source52 input and binding-only runners.

Never imports or executes an application runner, invokes Git/Rust, or accesses
the network. Writes only a new review JSON in this independent directory.
"""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

BASE = Path("/workspace/scratch/08f5efd48967")
PREP = BASE / "source52-preparation"
OUT = BASE / "source52-apply-input-independent-review"
LEAF = "codex-rs/network-proxy/src/runtime.rs"
SOURCE51_COMMIT = "e28b0f385ee882f842911044958b2810f62f6379"
SOURCE51_TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
SOURCE52_COMMIT = "1e0910becc37383e6d17ecf861ea844fd07d8862"
SOURCE52_TREE = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
KEYS = {
    "EXPECTED_COMMIT", "EXPECTED_TREE", "EXPECTED_CHANGED_COUNT",
    "INPUT_BYTES", "INPUT_SHA256", "SOURCE52_MANIFEST_PIN",
    "DELTA_MANIFEST_PIN", "CANDIDATE_PINS",
}
FIXED = {
    "ROOT-APPLY-BINDINGS.json": (1190, "f3a7460cac3da6f7253fb2a1b573dbeff5d0da6f6829e2f578ebab7fdd7ac6f7"),
    "ROOT-APPLY-INPUT-FREEZE.json": (2271, "5220643a8d20eabe4029b7d6084c2316225574685698ef9de136038c22f63a8e"),
    "CREATED-COMMIT-API-ORIGINAL.json": (1540, "3ac246001a16f30a430135bf4eabd0c979612329b73f5ed1052b9f22a5cb38ed"),
    "source52-apply-input.tar.gz": (43267, "9c7a414899bd05d1e70b9a6cbac64eef9dda552f8e56c904ee9f8e21ab37d6cb"),
    "input/source51-actual-manifest.json": (55418, "74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a"),
}
TEMPLATE = BASE / "source52-apply-preparation/native-source52-apply-template.py"
TEMPLATE_SHA = "9510eed8daa3f2e749971bfbd0c33f8e98d5f0524deb36005892766288c9b3a5"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def object_hash(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": object_hash("blob", raw)}


def read_fixed(name):
    raw = (PREP / name).read_bytes()
    expected_size, expected_sha = FIXED[name]
    require((len(raw), hashlib.sha256(raw).hexdigest()) == (expected_size, expected_sha), "fixed pin mismatch: " + name)
    return raw


def safe(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and "\\" not in name and all(x not in ("", ".", "..") for x in name.split("/")), "unsafe archive path")
    return p


def patch_image(patch, image, reverse=False):
    lines = patch.splitlines(keepends=True)
    require(lines[:2] == [
        ("--- a/" + LEAF + "\n").encode(),
        ("+++ b/" + LEAF + "\n").encode(),
    ], "patch must declare the one existing leaf")
    source = image.splitlines(keepends=True)
    result = []
    cursor = 0
    i = 2
    hunks = 0
    while i < len(lines):
        header = re.fullmatch(rb"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[i])
        require(header is not None, "invalid hunk header")
        old_start = int(header[1])
        old_count = int(header[2] or b"1")
        new_start = int(header[3])
        new_count = int(header[4] or b"1")
        if reverse:
            old_start, new_start, old_count, new_count = new_start, old_start, new_count, old_count
        offset = old_start - 1 if old_start else 0
        require(cursor <= offset <= len(source), "overlapping/out-of-range hunk")
        result.extend(source[cursor:offset])
        cursor = offset
        require(len(result) == (new_start - 1 if new_start else 0), "new hunk coordinate mismatch")
        consumed = produced = 0
        i += 1
        while i < len(lines) and not lines[i].startswith(b"@@ "):
            line = lines[i]
            op, body = line[:1], line[1:]
            require(op in (b" ", b"-", b"+"), "unsupported hunk record")
            if reverse:
                op = {b"+": b"-", b"-": b"+", b" ": b" "}[op]
            if op in (b" ", b"-"):
                require(cursor < len(source) and source[cursor] == body, "original hunk bytes mismatch")
                cursor += 1
                consumed += 1
            if op in (b" ", b"+"):
                result.append(body)
                produced += 1
            i += 1
        require((consumed, produced) == (old_count, new_count), "hunk length mismatch")
        hunks += 1
    result.extend(source[cursor:])
    return b"".join(result), hunks


def tree_hash(entries):
    require(len({x["path"] for x in entries}) == len(entries), "duplicate direct tree entry")
    body = bytearray()
    ordered = sorted(entries, key=lambda x: (x["path"] + ("/" if x["type"] == "tree" else "")).encode())
    for row in ordered:
        require("/" not in row["path"] and row["path"] not in ("", ".", ".."), "not a direct tree")
        mode = row["mode"].lstrip("0")
        body.extend(mode.encode() + b" " + row["path"].encode() + b"\0" + bytes.fromhex(row["sha"]))
    return object_hash("tree", bytes(body))


def verify_tree(before_blob, after_blob):
    names = ("root", "codex", "network", "network_src")
    source = {}
    pins = {}
    for name in names:
        p = PREP / "input/original-trees" / (name + ".json")
        raw = p.read_bytes()
        obj = json.loads(raw)
        require(obj["truncated"] is False and tree_hash(obj["tree"]) == obj["sha"], "original direct tree failed: " + name)
        source[name] = obj
        pins[str(p.relative_to(BASE))] = pin(raw)
    require(source["root"]["sha"] == SOURCE51_TREE, "original source51 root")
    chain = (("root", "codex-rs", "codex"), ("codex", "network-proxy", "network"), ("network", "src", "network_src"))
    for parent, entry, child in chain:
        row = next(x for x in source[parent]["tree"] if x["path"] == entry)
        require(row["type"] == "tree" and row["sha"] == source[child]["sha"], "original direct tree chain mismatch")
    result = {}
    changed = after_blob
    for name, entry, expected_old in (
        ("network_src", "runtime.rs", before_blob),
        ("network", "src", source["network_src"]["sha"]),
        ("codex", "network-proxy", source["network"]["sha"]),
        ("root", "codex-rs", source["codex"]["sha"]),
    ):
        rows = [dict(x) for x in source[name]["tree"]]
        row = next(x for x in rows if x["path"] == entry)
        require(row["sha"] == expected_old, "before leaf/tree mismatch")
        row["sha"] = changed
        changed = tree_hash(rows)
        result[name] = changed
    require(changed == SOURCE52_TREE, "independent one-leaf tree overlay mismatch")
    return {"original_direct_tree_inputs": pins, "derived_trees": result, "only_changed_repository_leaf": LEAF}


def assignment_nodes(raw):
    tree = ast.parse(raw.decode("utf-8"))
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            require(name not in result, "duplicate top-level assignment: " + name)
            result[name] = node
    return result


def span(raw, node):
    lines = raw.splitlines(keepends=True)
    start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
    end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
    return start, end


def verify_runner(bound_path, final_path, bindings):
    template = TEMPLATE.read_bytes()
    require(len(template) == 35669 and pin(template)["sha256"] == TEMPLATE_SHA, "template changed")
    nodes = assignment_nodes(template)
    require(ast.literal_eval(nodes["FROZEN"].value) is False, "template not inert")
    require({name for name, node in nodes.items() if isinstance(node.value, ast.Constant) and node.value.value is None} == KEYS, "template None set")
    if bound_path is None:
        require(final_path is None, "final verification requires a bound input")
        return {"template": {"path": str(TEMPLATE.relative_to(BASE)), **pin(template)}, "bound": None, "final": None}
    bound = bound_path.read_bytes()
    bn = assignment_nodes(bound)
    require(ast.literal_eval(bn["FROZEN"].value) is False, "bound file must remain inert")
    replacements = []
    for name in KEYS:
        require(ast.literal_eval(bn[name].value) == bindings[name], "bound literal mismatch: " + name)
        a, b = span(bound, bn[name])
        x, y = span(template, nodes[name])
        replacements.append((a, b, template[x:y]))
    restored = bound
    for a, b, original in sorted(replacements, reverse=True):
        restored = restored[:a] + original + restored[b:]
    require(restored == template, "binding changed more than eight literal assignments")
    result = {
        "template": {"path": str(TEMPLATE.relative_to(BASE)), **pin(template)},
        "bound": {"path": str(bound_path.relative_to(BASE)), **pin(bound)},
        "eight_literal_values_match_root_input": True,
        "eight_assignment_inverse_restores_entire_template": True,
        "final": None,
    }
    if final_path is not None:
        final = final_path.read_bytes()
        require(bound.count(b"FROZEN = False") == 1, "ambiguous frozen literal")
        require(final == bound.replace(b"FROZEN = False", b"FROZEN = True", 1), "final changed more than FROZEN")
        fn = assignment_nodes(final)
        require(ast.literal_eval(fn["FROZEN"].value) is True, "final FROZEN is not true")
        result["final"] = {"path": str(final_path.relative_to(BASE)), **pin(final)}
        result["final_only_frozen_flip"] = True
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bound", type=Path)
    parser.add_argument("--final", type=Path)
    parser.add_argument("--output", default="INPUT-REVIEW.json")
    args = parser.parse_args()
    originals = {name: read_fixed(name) for name in FIXED}
    bindings = json.loads(originals["ROOT-APPLY-BINDINGS.json"])
    freeze = json.loads(originals["ROOT-APPLY-INPUT-FREEZE.json"])
    commit = json.loads(originals["CREATED-COMMIT-API-ORIGINAL.json"])
    require(set(bindings) == KEYS, "exact eight root bindings required")
    require(bindings["EXPECTED_COMMIT"] == SOURCE52_COMMIT and bindings["EXPECTED_TREE"] == SOURCE52_TREE and bindings["EXPECTED_CHANGED_COUNT"] == 195, "registered identity/count")
    require(commit["sha"] == SOURCE52_COMMIT and commit["tree"]["sha"] == SOURCE52_TREE and [x["sha"] for x in commit["parents"]] == [SOURCE51_COMMIT], "pinned original commit API identity/parent mismatch")
    require(freeze["source_commit"] == SOURCE52_COMMIT and freeze["source_tree"] == SOURCE52_TREE and freeze["parent"] == SOURCE51_COMMIT, "freeze identity mismatch")
    archive_raw = originals["source52-apply-input.tar.gz"]
    require(pin(archive_raw) == {k: freeze["archive"][k] for k in ("bytes", "sha256", "git_blob")}, "archive full pin")
    require(len(archive_raw) == bindings["INPUT_BYTES"] and pin(archive_raw)["sha256"] == bindings["INPUT_SHA256"], "archive binding")
    expected = {
        "source52-manifest.json", "delta-manifest.json", "candidate.patch",
        "before/" + LEAF, "after/" + LEAF,
    }
    members = {}
    modes = {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as tar:
        for item in tar.getmembers():
            safe(item.name)
            require(item.isfile() and not item.issym() and not item.islnk() and item.name not in members and item.name in expected, "unexpected/unsafe tar member")
            stream = tar.extractfile(item)
            require(stream is not None, "missing tar stream")
            data = stream.read()
            require(len(data) == item.size, "tar truncated")
            members[item.name] = data
            modes[item.name] = oct(item.mode)
    require(set(members) == expected and len(members) == 5, "not exact five members")
    actual_members = [{"path": name, **pin(members[name])} for name in sorted(members)]
    require(actual_members == freeze["members"], "freeze member pins mismatch")
    source = json.loads(members["source52-manifest.json"])
    old = json.loads(originals["input/source51-actual-manifest.json"])
    delta = json.loads(members["delta-manifest.json"])
    require(pin(members["source52-manifest.json"]) == bindings["SOURCE52_MANIFEST_PIN"], "full manifest pin")
    require(pin(members["delta-manifest.json"]) == bindings["DELTA_MANIFEST_PIN"], "delta pin")
    require(source["source_commit"] == SOURCE52_COMMIT and source["source_tree"] == SOURCE52_TREE and source["source_parent_commit"] == SOURCE51_COMMIT, "manifest identity")
    require(old["source_commit"] == SOURCE51_COMMIT and old["source_tree"] == SOURCE51_TREE, "original manifest identity")
    old_rows = {x["path"]: x for x in old["changed_files"]}
    new_rows = {x["path"]: x for x in source["changed_files"]}
    require(len(old_rows) == len(old["changed_files"]) == 194 and len(new_rows) == len(source["changed_files"]) == 195, "manifest duplicates/count")
    require(LEAF not in old_rows and set(new_rows) == set(old_rows) | {LEAF}, "one newly changed existing leaf")
    require(all(new_rows[path] == row for path, row in old_rows.items()), "an original194 row changed")
    require(sum(path.endswith(".rs") for path in new_rows) == 181, "Rust scope count")
    for key in ("cargo_lock_sha256", "bazel_lock_sha256"):
        require(source[key] == old[key], "dual-lock declaration changed")
    require(source["native_applied"] is False and source["rust_qualification"] == "PENDING" and source["final_fix_fmt_executed"] is False, "input overclaims native qualification")
    require(source["science"] == "HOLD" and source["authority"] == "DENY_ALL", "scientific boundary changed")
    require(delta["schema"] == "hepta.source52-apply-delta.v1" and delta["source_before_tree"] == SOURCE51_TREE and delta["source_before_commit"] == SOURCE51_COMMIT and delta["source_tree"] == SOURCE52_TREE and delta["source_commit"] == SOURCE52_COMMIT, "delta schema/identity")
    require(delta["patch"] == {"path": "candidate.patch", **pin(members["candidate.patch"])}, "patch delta pin")
    require(len(delta["files"]) == 1 and delta["files"][0]["path"] == LEAF, "delta path count")
    pair = {side: delta["files"][0][side] for side in ("before", "after")}
    require(bindings["CANDIDATE_PINS"] == {LEAF: pair}, "bound leaf mismatch")
    for side in ("before", "after"):
        require(pair[side] == {"mode": "100644", **pin(members[side + "/" + LEAF])}, "leaf bytes/blob/mode mismatch")
    require(new_rows[LEAF] == {"path": LEAF, **pair["after"]}, "new manifest leaf")
    forward, hunks = patch_image(members["candidate.patch"], members["before/" + LEAF])
    reverse, reverse_hunks = patch_image(members["candidate.patch"], members["after/" + LEAF], True)
    require(forward == members["after/" + LEAF] and reverse == members["before/" + LEAF] and hunks == reverse_hunks, "independent patch roundtrip")
    tree_result = verify_tree(pair["before"]["git_blob"], pair["after"]["git_blob"])
    runner_result = verify_runner(args.bound, args.final, bindings)
    report = {
        "schema": "hepta.source52-apply-input-independent-review.v1",
        "conclusion": "STATIC_INPUT_AND_BINDING_CLEAR" if args.bound else "STATIC_INPUT_CLEAR_BINDING_PENDING",
        "input_pins": {name: pin(raw) for name, raw in originals.items()},
        "source": {"commit": SOURCE52_COMMIT, "tree": SOURCE52_TREE, "parent": SOURCE51_COMMIT,
                   "prior_changed_count": 194, "changed_count": 195, "rust_count": 181, "other_count": 14},
        "archive_members": actual_members,
        "archive_transport_modes_observed": modes,
        "independent_four_direct_tree_overlay": tree_result,
        "original194_manifest_rows_unchanged": True,
        "runtime_preexisting_repository_leaf_and_new_to_changed_manifest": True,
        "independent_patch_forward_inverse_exact": True,
        "patch_hunk_count": hunks,
        "runner": runner_result,
        "api_identity_provenance": "Pinned original Git API JSON supplied in source52-preparation; no new network query by this verifier.",
        "source_application_executed": False,
        "runner_imported_or_executed": False,
        "rust_or_test_execution": False,
        "native_apply_result": None,
        "qualification": "PENDING",
        "science": "HOLD",
        "authority": "DENY_ALL",
    }
    OUT.mkdir(exist_ok=True)
    target = OUT / args.output
    require(target.parent == OUT and not target.exists(), "create-only local review required")
    data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    with target.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"path": str(target.relative_to(BASE)), **pin(data)}))


if __name__ == "__main__":
    main()

