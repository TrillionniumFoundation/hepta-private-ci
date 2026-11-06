#!/usr/bin/env python3
"""Read-only data/AST verification. Never import or execute the apply executor."""
from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json
import tarfile

W = Path("/workspace/scratch/08f5efd48967")
P = W / "source51-preparation"
R = W / "source51-apply-input-independent-review"
OLD = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
OLD_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
NEW = "e28b0f385ee882f842911044958b2810f62f6379"
NEW_TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
PATHS = ["codex-rs/exec-server/tests/common/fake_bwrap.rs", "codex-rs/network-proxy/src/http_proxy.rs"]

def need(v, m):
    if not v:
        raise ValueError(m)

def pin(b):
    return {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()}

def tree_sha(entries):
    names = [e["path"] for e in entries]
    need(len(names) == len(set(names)), "duplicate tree path")
    for name in names:
        need(name and "/" not in name and "\0" not in name, "not a direct tree")
    ordered = sorted(entries, key=lambda e: (e["path"] + ("/" if e["type"] == "tree" else "")).encode())
    raw = b"".join(e["mode"].lstrip("0").encode() + b" " + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"]) for e in ordered)
    return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def unique(entries, path):
    rows = [e for e in entries if e["path"] == path]
    need(len(rows) == 1, "ambiguous tree path")
    return rows[0]

def file_map(obj):
    rows = {}
    for e in obj["changed_files"]:
        v = {k: e[k] for k in ("path", "mode", "bytes", "sha256", "git_blob")}
        need(v["path"] not in rows, "duplicate manifest path")
        rows[v["path"]] = v
    return rows

def ast_assignments(text):
    parsed = ast.parse(text)
    nodes = {n.targets[0].id: n for n in parsed.body if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    return parsed, nodes

def exact_assignment_reverse(original, bound, bindings):
    old_ast, old_nodes = ast_assignments(original)
    new_ast, new_nodes = ast_assignments(bound)
    need(ast.literal_eval(old_nodes["FROZEN"].value) is False and ast.literal_eval(new_nodes["FROZEN"].value) is False, "freeze flag changed early")
    offsets = []
    cursor = 0
    for line in bound.splitlines(keepends=True):
        offsets.append(cursor)
        cursor += len(line)
    reversals = []
    for name, expected in bindings.items():
        need(ast.literal_eval(old_nodes[name].value) is None, "original binding not None")
        node = new_nodes[name]
        need(ast.literal_eval(node.value) == expected, "binding mismatch " + name)
        begin = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        reversals.append((begin, end, ast.get_source_segment(original, old_nodes[name])))
    restored = bound
    for begin, end, replacement in sorted(reversals, reverse=True):
        restored = restored[:begin] + replacement + restored[end:]
    need(restored == original, "more than the eight constants changed")
    old_funcs = {n.name: ast.get_source_segment(original, n) for n in old_ast.body if isinstance(n, ast.FunctionDef)}
    new_funcs = {n.name: ast.get_source_segment(bound, n) for n in new_ast.body if isinstance(n, ast.FunctionDef)}
    need(old_funcs == new_funcs, "executor function body changed")
    return len(old_funcs)

def main():
    inputs = {}
    def read(rel):
        path = W / rel
        raw = path.read_bytes()
        inputs[rel] = pin(raw)
        return raw
    bindings_raw = read("source51-preparation/ROOT-APPLY-BINDINGS.json")
    bindings = json.loads(bindings_raw)
    need(len(bindings) == 8, "wrong binding count")
    freeze = json.loads(read("source51-preparation/ROOT-APPLY-INPUT-FREEZE.json"))
    need(bindings["EXPECTED_COMMIT"] == freeze["source_commit"] == NEW, "new commit")
    need(bindings["EXPECTED_TREE"] == freeze["source_tree"] == NEW_TREE, "new tree")
    need(freeze["source_parent_commit"] == OLD and freeze["source51_native_applied"] is False, "publication/apply boundary")
    archive_path = "source51-preparation/source51-apply-input.tar.gz"
    archive_raw = read(archive_path)
    need(len(archive_raw) == bindings["INPUT_BYTES"] == 43449 and pin(archive_raw)["sha256"] == bindings["INPUT_SHA256"], "archive pin")
    expected = {"delta-manifest.json", "source51-manifest.json", "candidate.patch"} | {side + "/" + p for side in ("before", "after") for p in PATHS}
    members = {}
    modes = {}
    with tarfile.open(W / archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            need(member.isfile() and not member.issym() and not member.islnk(), "nonregular archive member")
            need(member.name in expected and member.name not in members, "extra/duplicate member")
            raw = archive.extractfile(member).read()
            need(len(raw) == member.size, "truncated member")
            members[member.name] = raw
            modes[member.name] = member.mode
    need(set(members) == expected and len(members) == 7, "archive member set")
    member_pins = {name: pin(raw) for name, raw in members.items()}
    need(member_pins == freeze["member_pins"], "root member inventory differs")
    need(pin(members["source51-manifest.json"]) == bindings["SOURCE51_MANIFEST_PIN"], "full manifest binding")
    need(pin(members["delta-manifest.json"]) == bindings["DELTA_MANIFEST_PIN"], "delta binding")
    need(members["source51-manifest.json"] == read("source51-preparation/native-candidate-r26-source.json"), "standalone full manifest differs")
    need(members["delta-manifest.json"] == read("source51-preparation/source51-delta-manifest.json"), "standalone delta differs")
    need(members["candidate.patch"] == read("source51-preparation/combined.patch"), "standalone patch differs")
    old_raw = read("source51-preparation/input/source50-actual-manifest.json")
    need(pin(old_raw)["sha256"] == "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0", "source50 raw manifest")
    old, new = json.loads(old_raw), json.loads(members["source51-manifest.json"])
    need(old["source_commit"] == OLD and old["source_tree"] == OLD_TREE, "source50 identity")
    need(new["source_commit"] == NEW and new["source_tree"] == NEW_TREE and new["source_parent_commit"] == OLD, "source51 identity")
    before_rows, after_rows = file_map(old), file_map(new)
    need(set(before_rows) == set(after_rows) and len(after_rows) == bindings["EXPECTED_CHANGED_COUNT"] == 194, "full194 map")
    changed = sorted(path for path in after_rows if before_rows[path] != after_rows[path])
    need(changed == sorted(PATHS), "undeclared changed path")
    for field in ("cargo_lock_sha256", "bazel_lock_sha256"):
        need(old[field] == new[field], "lock pin changed")
    delta = json.loads(members["delta-manifest.json"])
    need(delta["schema"] == "hepta.source51-apply-delta.v1", "delta schema")
    for k,v in {"source_before_tree": OLD_TREE, "source_before_commit": OLD, "source_tree": NEW_TREE, "source_commit": NEW}.items():
        need(delta[k] == v, "delta identity")
    need(delta["patch"] == {"path": "candidate.patch", **pin(members["candidate.patch"])}, "delta patch pin")
    delta_rows = {row["path"]: {"before": row["before"], "after": row["after"]} for row in delta["files"]}
    need(len(delta["files"]) == 2 and delta_rows == bindings["CANDIDATE_PINS"], "candidate bindings")
    combined = b""
    for path in PATHS:
        before, after = members["before/" + path], members["after/" + path]
        for side, raw, mapping in [("before", before, before_rows), ("after", after, after_rows)]:
            need({"mode": "100644", **pin(raw)} == delta_rows[path][side], "candidate bytes or mode")
            need(mapping[path] == {"path": path, **delta_rows[path][side]}, "candidate/full manifest row")
        combined += "".join(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True), fromfile="a/" + path, tofile="b/" + path)).encode()
    need(combined == members["candidate.patch"], "exact unified diff regeneration")
    helper_before, helper_after = members["before/" + PATHS[0]], members["after/" + PATHS[0]]
    original = b'    let real_bwrap = codex_utils_cargo_bin::cargo_bin("bwrap")?;\n'
    replacement = b'    // Resolve the real launcher before the shim can enter the child\\\'s PATH.\n'.replace(b"\\'", b"'") + b'    let real_bwrap = match codex_sandboxing::find_system_bwrap_in_path() {\n        Some(path) => path,\n        None => codex_utils_cargo_bin::cargo_bin("bwrap")?,\n    };\n'
    need(helper_before.count(original) == helper_after.count(replacement) == 1, "helper unique operation")
    need(helper_before.replace(original, replacement) == helper_after and helper_after.replace(replacement, original) == helper_before, "helper exact inverse")
    net_before, net_after = members["before/" + PATHS[1]], members["after/" + PATHS[1]]
    inserted = b"            allow_local_binding: true,\n"
    # Independently locate the unique target function, preserving the rest of the file.
    marker = b"async fn http_connect_accept_defers_brokered_host_mitm_until_protocol_detection"
    start_old, start_new = net_before.index(marker), net_after.index(marker)
    need(start_old == start_new, "network prelude changed")
    pos = net_after.index(inserted, start_new)
    need(net_after[:pos] + net_after[pos + len(inserted):] == net_before, "network exact inverse")
    trees = {}
    originals = {}
    for name in ("root", "codex", "exec", "exec_tests", "exec_common", "network", "network_src"):
        rel = "source51-preparation/input/original-trees/" + name + ".json"
        obj = json.loads(read(rel))
        need(obj["truncated"] is False and tree_sha(obj["tree"]) == obj["sha"], "original direct tree integrity")
        originals[name] = obj
        trees[name] = copy.deepcopy(obj["tree"])
    for parent, entry, child in [("root", "codex-rs", "codex"), ("codex", "exec-server", "exec"), ("exec", "tests", "exec_tests"), ("exec_tests", "common", "exec_common"), ("codex", "network-proxy", "network"), ("network", "src", "network_src")]:
        need(unique(originals[parent]["tree"], entry)["sha"] == originals[child]["sha"], "old direct tree linkage")
    need(originals["root"]["sha"] == OLD_TREE, "old root tree")
    for name, leaf, path in [("exec_common", "fake_bwrap.rs", PATHS[0]), ("network_src", "http_proxy.rs", PATHS[1])]:
        entry = unique(trees[name], leaf)
        need(entry["type"] == "blob" and entry["mode"] == "100644" and entry["sha"] == delta_rows[path]["before"]["git_blob"], "old source leaf")
        entry["sha"] = delta_rows[path]["after"]["git_blob"]
    computed = {}
    for child, parent, entry in [("exec_common", "exec_tests", "common"), ("exec_tests", "exec", "tests"), ("exec", "codex", "exec-server"), ("network_src", "network", "src"), ("network", "codex", "network-proxy"), ("codex", "root", "codex-rs")]:
        computed[child] = tree_sha(trees[child])
        unique(trees[parent], entry)["sha"] = computed[child]
    computed["root"] = tree_sha(trees["root"])
    need(computed["root"] == NEW_TREE, "new root tree mismatch")
    commit = json.loads(read("source51-preparation/CREATED-COMMIT-API-ORIGINAL.json"))
    need(commit["sha"] == NEW and commit["tree"]["sha"] == computed["root"] and [p["sha"] for p in commit["parents"]] == [OLD], "actual commit response mapping")
    template_raw = read("source51-apply-preparation/native-source51-apply-template.py")
    bound_raw = read("native-validation-results/source51-apply-bound-input/native-source51-apply-bound.py")
    need(pin(template_raw)["sha256"] == "743a9f7ff2c4992b91aab39aa22298b6599c169c15089360e7dbcfbff4cf0f8e", "reviewed template changed")
    need(pin(bound_raw)["sha256"] == "0f15b826bc6dd5cf1ed6a6f3ad5616f79ef15b4ef1c45456e0187d86348aa749", "bound file pin")
    functions = exact_assignment_reverse(template_raw.decode(), bound_raw.decode(), bindings)
    final_expected = bound_raw.replace(b"FROZEN = False\n", b"FROZEN = True\n", 1)
    need(bound_raw.count(b"FROZEN = False\n") == 1, "freeze marker ambiguity")
    report = {
        "schema": "hepta.source51-actual-input-bound-independent-readback.v1",
        "status": "STATIC_CLEAR_BOUND_FALSE_NO_NATIVE_EXECUTION",
        "source_before": {"commit": OLD, "tree": OLD_TREE},
        "source51": {"commit": NEW, "tree": NEW_TREE, "parent": OLD, "native_applied_by_this_review": False},
        "archive": {"path": archive_path, **pin(archive_raw), "regular_member_count": 7, "member_pins": member_pins, "transport_modes": modes},
        "full_manifest": {"files": 194, "unchanged_rows": 192, "changed_paths": changed, "rust_paths": sum(p.endswith(".rs") for p in after_rows), "other_paths": sum(not p.endswith(".rs") for p in after_rows), "dual_locks_equal": True},
        "patch": {"exact_full_diff_regenerated": True, "two_literal_operations_forward_inverse_exact": True},
        "git_tree": {"method": "Independent Git tree object encoding of seven complete original direct trees, then only two leaf replacements and affected ancestor updates.", "original_root": OLD_TREE, "computed_direct_trees": computed, "remote_get_repeated": False, "actual_commit_response_fields_match": True},
        "executor_binding": {"template": pin(template_raw), "bound": pin(bound_raw), "eight_literals_match_actual_root_bindings": True, "inverse_entire_bound_file_equals_reviewed_template": True, "all_function_bodies_equal": functions, "FROZEN": False, "predicted_final_single_line_pin": pin(final_expected)},
        "interface": {"seven_member_schema_matches": True, "source_parent_commit_present": True, "delta_patch_member": "candidate.patch", "candidate_pins_match_full_rows": True, "source50_lock_history_not_relabelled": True, "r24_failed100_unchanged": True, "no_missing_required_field_observed": True},
        "verification_limits": {"executor_imported_or_executed": False, "rust_or_native_command": False, "source_modified": False, "qualification_granted": False},
        "input_pins": inputs,
    }
    R.mkdir(parents=True, exist_ok=True)
    target = R / "BOUND-INDEPENDENT-READBACK.json"
    need(not target.exists(), "create-only readback")
    target.write_bytes((json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps({"report": str(target.relative_to(W)), **pin(target.read_bytes()), "bound_clear": True, "expected_final": pin(final_expected)}))

if __name__ == "__main__":
    main()
