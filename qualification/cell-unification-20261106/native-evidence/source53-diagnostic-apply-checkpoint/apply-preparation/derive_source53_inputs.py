#!/usr/bin/env python3
"""Build root-reviewable source53 inputs from exact local immutable Git replies.

This script performs only local reads, hashing and new isolated output writes.
It does not execute the apply template, Git, Cargo, a native command or a gate.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(__file__).resolve().parent
OUT = DEST / "derived"
CANDIDATE = ROOT / "app-server-bedrock-r29-diagnostic-preparation"
GIT_INPUT = ROOT / "source53-root-preparation"
BASE_COMMIT = "1e0910becc37383e6d17ecf861ea844fd07d8862"
BASE_TREE = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
ACTUAL_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
ACTUAL_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
BASE_MANIFEST_SHA = "3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898"
CANDIDATE_MANIFEST_SHA = "35e8d23122dc0a706af7168607cf1ba937bc23d91b3004e12964b728c4026205"
PATHS = (
    "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
    "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs",
)


def need(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def jb(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def put(relative, raw):
    p = DEST / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        need(p.read_bytes() == raw, "refuse overwrite: " + relative)
    else:
        with p.open("xb") as stream:
            stream.write(raw)
    return pin(raw)


def row_slices(raw):
    text = raw.decode("utf-8")
    matches = list(re.finditer(r'"changed_files"\s*:\s*\[', text))
    need(len(matches) == 1, "changed_files array missing/ambiguous")
    position = matches[0].end()
    decoder = json.JSONDecoder()
    rows = {}
    while True:
        while text[position].isspace():
            position += 1
        if text[position] == "]":
            return rows
        value, end = decoder.raw_decode(text, position)
        need(value["path"] not in rows, "duplicate manifest row")
        rows[value["path"]] = text[position:end].encode()
        position = end
        while text[position].isspace():
            position += 1
        need(text[position] in ",]", "manifest delimiter differs")
        if text[position] == ",":
            position += 1


def tree_hash(entries):
    seen = set()
    for entry in entries:
        path = entry["path"]
        need(path not in seen and path not in ("", ".", "..") and "/" not in path
             and "\0" not in path, "unsafe or duplicate direct tree entry")
        seen.add(path)
        need((entry["type"], entry["mode"]) in {("tree", "040000"), ("blob", "100644"),
             ("blob", "100755"), ("blob", "120000"), ("commit", "160000")}, "tree mode/type differs")
        need(re.fullmatch(r"[0-9a-f]{40}", entry["sha"]) is not None, "invalid tree child digest")
    ordered = sorted(entries, key=lambda e: (e["path"] + ("/" if e["type"] == "tree" else "")).encode())
    body = b"".join(e["mode"].lstrip("0").encode() + b" " + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"])
                    for e in ordered)
    return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()


def decoded_api(raw):
    obj = json.loads(raw)
    if "structuredContent" in obj:
        return json.loads(obj["structuredContent"]["content"])
    return obj


def main():
    base_raw = (ROOT / "source52-preparation/native-candidate-r28-source.json").read_bytes()
    need(pin(base_raw)["sha256"] == BASE_MANIFEST_SHA, "source52 manifest differs")
    base = json.loads(base_raw)
    need(base["source_commit"] == BASE_COMMIT and base["source_tree"] == BASE_TREE, "source52 identity differs")
    old_rows = base["changed_files"]
    need(len(old_rows) == len({r["path"] for r in old_rows}) == 195, "prior195 path set differs")
    need(set(PATHS).isdisjoint(r["path"] for r in old_rows), "candidate leaf already in prior manifest")
    need(sum(r["path"].endswith(".rs") for r in old_rows) == 181, "prior Rust count differs")
    put("references/source52-actual-manifest.json", base_raw)
    candidate_raw = (CANDIDATE / "source-manifest.json").read_bytes()
    need(pin(candidate_raw)["sha256"] == CANDIDATE_MANIFEST_SHA, "diagnostic candidate manifest changed")
    candidate = json.loads(candidate_raw)
    need(candidate["source_before_commit"] == BASE_COMMIT and candidate["source_before_tree"] == BASE_TREE,
         "candidate baseline differs")
    need(candidate["classification"] == "DIAGNOSTIC_ONLY_NOT_A_REPAIR_OR_QUALIFICATION", "candidate classification differs")
    candidates = {r["path"]: r for r in candidate["files"]}
    need(len(candidates) == 2 and set(candidates) == set(PATHS), "candidate paths differ")
    patch = (CANDIDATE / "diagnostic.patch").read_bytes()
    need(pin(patch) == {k: candidate["patch"][k] for k in ("bytes", "sha256", "git_blob")}, "patch differs")
    before, after = {}, {}
    for path in PATHS:
        need(candidates[path]["mode"] == "100644", "candidate mode differs")
        for side, directory, target in (("before", "original", before), ("after", "source", after)):
            raw = (CANDIDATE / directory / path).read_bytes()
            need(pin(raw) == candidates[path][side], "candidate raw bytes differ: " + side + " " + path)
            target[path] = raw
            put("derived/" + side + "/" + path, raw)
    put("derived/candidate.patch", patch)
    for index, path in enumerate(PATHS):
        original_api_raw = (GIT_INPUT / ("original-github-" + str(index) + ".json")).read_bytes()
        api = json.loads(original_api_raw)
        need(api["structuredContent"]["content"].encode() == before[path], "actual Git before bytes differ")
        put("references/source53-git/original-github-" + str(index) + ".json", original_api_raw)

    commit_raw = (GIT_INPUT / "ACTUAL-COMMIT-API-RESPONSE.json").read_bytes()
    commit = decoded_api(commit_raw)
    need(commit["sha"] == ACTUAL_COMMIT and commit["tree"]["sha"] == ACTUAL_TREE
         and [p["sha"] for p in commit["parents"]] == [BASE_COMMIT], "actual Git commit/tree/parent differs")
    put("references/source53-git/ACTUAL-COMMIT-API-RESPONSE.json", commit_raw)
    directories = {""}
    for path in PATHS:
        directories.update(str(p) for p in PurePosixPath(path).parents if str(p) != ".")
    need(len(directories) == 9, "two-leaf ancestor set differs")
    trees = {"before": {}, "after": {}}
    tree_pins = []
    for directory in sorted(directories):
        key = directory.replace("/", "__") or "ROOT"
        for side in ("before", "after"):
            name = key + "-" + side + ".json"
            raw = (GIT_INPUT / "actual-tree-reads" / name).read_bytes()
            obj = json.loads(raw)
            need(obj["truncated"] is False and tree_hash(obj["tree"]) == obj["sha"], "actual tree payload hash differs")
            trees[side][directory] = obj
            put("references/source53-git/actual-tree-reads/" + name, raw)
            tree_pins.append({"directory": directory, "side": side, "git_tree": obj["sha"], "file": name, **pin(raw)})
    need(trees["before"][""]["sha"] == BASE_TREE and trees["after"][""]["sha"] == ACTUAL_TREE, "actual root trees differ")
    for side in ("before", "after"):
        for directory in directories - {""}:
            parent, _, name = directory.rpartition("/")
            entry = next(e for e in trees[side][parent]["tree"] if e["path"] == name)
            need(entry["type"] == "tree" and entry["sha"] == trees[side][directory]["sha"], "parent/child tree link differs")
    leaf_changes = []
    for directory in directories:
        old = {e["path"]: e for e in trees["before"][directory]["tree"]}
        new = {e["path"]: e for e in trees["after"][directory]["tree"]}
        need(set(old) == set(new), "Git directory entry added/deleted")
        for name in old:
            a, b = old[name], new[name]
            need((a["mode"], a["type"]) == (b["mode"], b["type"]), "Git type/mode changed")
            if a["sha"] == b["sha"]:
                continue
            full = "/".join(x for x in (directory, name) if x)
            if a["type"] == "tree":
                need(full in directories, "undeclared changed subtree")
            else:
                need(full in PATHS and a["mode"] == "100644" and a["type"] == "blob", "undeclared changed leaf")
                need(a["sha"] == pin(before[full])["git_blob"] and b["sha"] == pin(after[full])["git_blob"], "actual leaf differs")
                need(a["size"] == len(before[full]) and b["size"] == len(after[full]), "actual leaf size differs")
                leaf_changes.append(full)
    need(set(leaf_changes) == set(PATHS) and len(leaf_changes) == 2, "actual tree delta differs")
    rebuilt = {}
    for directory in sorted(directories, key=lambda x: (x.count("/"), len(x)), reverse=True):
        entries = []
        for original in trees["before"][directory]["tree"]:
            entry = {k: original[k] for k in ("path", "mode", "type", "sha")}
            full = "/".join(x for x in (directory, entry["path"]) if x)
            if full in rebuilt:
                entry["sha"] = rebuilt[full]
            elif full in after:
                entry["sha"] = pin(after[full])["git_blob"]
            entries.append(entry)
        rebuilt[directory] = tree_hash(entries)
        need(rebuilt[directory] == trees["after"][directory]["sha"], "independent source52 overlay differs")

    scope_raw = (ROOT / "source52-final-scope-preparation/EXPECTED-SELECTION.json").read_bytes()
    scope = json.loads(scope_raw)
    metadata_gz = (ROOT / "source52-final-scope-preparation/input/native-workspace-r29-metadata.json.gz").read_bytes()
    metadata_raw = gzip.decompress(metadata_gz)
    need(pin(metadata_raw)["sha256"] == "b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d", "actual prior metadata differs")
    metadata = json.loads(metadata_raw)
    need(len(metadata["workspace_members"]) == len(metadata["workspace_default_members"]) == 193
         and set(metadata["workspace_members"]) == set(metadata["workspace_default_members"]), "193/default metadata differs")
    native_source = "/home/alex/work/hepta-cell-unified-20261106-a/source/"
    package_roots = []
    for package in metadata["packages"]:
        if package["id"] in metadata["workspace_members"]:
            manifest_path = package["manifest_path"]
            need(manifest_path.startswith(native_source) and manifest_path.endswith("/Cargo.toml"), "metadata root differs")
            package_roots.append((manifest_path[len(native_source):-len("/Cargo.toml")], package["name"], package["id"]))
    new_rows = sorted(old_rows + [{"path": p, "mode": "100644", **pin(after[p])} for p in PATHS], key=lambda r: r["path"])
    owners = {}
    for row in new_rows:
        if row["path"].endswith(".rs"):
            matches = [(directory, name, package_id) for directory, name, package_id in package_roots
                       if row["path"].startswith(directory + "/")]
            need(matches, "Rust owner absent from actual metadata")
            directory, name, package_id = max(matches, key=lambda x: len(x[0]))
            owners[row["path"]] = {"package": name, "package_id": package_id, "package_directory": directory}
    owner_names = sorted({o["package"] for o in owners.values()})
    need(len(owners) == 183 and len(owner_names) == 26
         and owner_names == sorted(o["package"] for o in scope["owners"]), "owning scope changed")
    need(all(owners[p]["package"] == "codex-app-server" for p in PATHS), "new source owners differ")
    workflow_path = ".github/workflows/hepta-cell-framework-native.yml"
    workflow = (ROOT / "native-validation-results/r29-archive-closed/original/source" / workflow_path).read_bytes()
    expected_workflow = next(r for r in old_rows if r["path"] == workflow_path)
    need(pin(workflow) == {k: expected_workflow[k] for k in ("bytes", "sha256", "git_blob")}, "CI workflow bytes differ")
    selectors = re.findall(r"-p ((?:codex-|core_)[A-Za-z0-9_-]+)", workflow.decode())
    need(selectors == scope["ci_selectors"] and len(selectors) == len(set(selectors)) == 27, "CI selectors changed")
    put("references/source52-EXPECTED-SELECTION.json", scope_raw)
    put("references/native-workspace-r29-metadata.json.gz", metadata_gz)
    put("references/hepta-cell-framework-native.yml", workflow)
    changes = [{"path": p, "mode": "100644", "before": pin(before[p]), "after": pin(after[p])} for p in PATHS]
    manifest = {
        "schema": "hepta.registered-source53-manifest.v1", "stage": 53,
        "status": "ROOT_REVIEW_CANDIDATE_REGISTERED_GITDATA_NOT_NATIVE_APPLIED_OR_QUALIFIED",
        "classification": "DIAGNOSTIC_ONLY_NOT_BEHAVIOR_REPAIR",
        "source_commit": ACTUAL_COMMIT, "source_tree": ACTUAL_TREE,
        "source_parent_commit": BASE_COMMIT, "source_before_tree": BASE_TREE,
        "source_tree_is_offline_expected_identity": False, "native_checkout_or_execution_not_claimed": True,
        "cargo_lock_sha256": base["cargo_lock_sha256"], "bazel_lock_sha256": base["bazel_lock_sha256"],
        "changed_files": new_rows,
        "base_source_manifest": {"path": "references/source52-actual-manifest.json", **pin(base_raw)},
        "source_changes_from_parent": changes,
        "source52_original_manifest_rows_retained": 195, "original_row_json_bytes_retained": True,
        "changed_file_count": 197, "rust_file_count": 183, "other_file_count": 14,
        "owner_count_unchanged": 26, "ci_selector_count_unchanged": 27,
        "dependency_inputs_changed": [], "lock_changes": [],
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "rust_qualification": "PENDING", "native_applied": False, "final_fix_fmt_executed": False,
        "science": "HOLD", "authority": "DENY_ALL",
        "source_identity_bound_from_actual_git_api": {
            "commit": ACTUAL_COMMIT, "tree": ACTUAL_TREE, "parent": BASE_COMMIT,
            "original": {"path": "references/source53-git/ACTUAL-COMMIT-API-RESPONSE.json", **pin(commit_raw)},
            "native_checkout_claimed": False},
        "diagnostic_project_gate_boundary": "A future actual source53 project PASS would qualify only that engineering project execution. It would not prove the original Bedrock failure repaired or substitute for the complete workspace or scientific gates.",
    }
    manifest_raw = jb(manifest)
    need(len(new_rows) == 197 and sum(r["path"].endswith(".rs") for r in new_rows) == 183, "197/183 count differs")
    old_slices, new_slices = row_slices(base_raw), row_slices(manifest_raw)
    need(set(new_slices) == set(old_slices) | set(PATHS)
         and all(old_slices[p] == new_slices[p] for p in old_slices), "old195 JSON slices changed")
    put("derived/native-candidate-r30-source.json", manifest_raw)
    delta = {"schema": "hepta.source53-apply-delta.v1", "source_before_tree": BASE_TREE, "source_before_commit": BASE_COMMIT,
             "source_tree": ACTUAL_TREE, "source_commit": ACTUAL_COMMIT,
             "patch": {"path": "candidate.patch", **pin(patch)},
             "files": [{"path": p, "before": {"mode": "100644", **pin(before[p])},
                        "after": {"mode": "100644", **pin(after[p])}} for p in PATHS],
             "identity_status": "REGISTERED_GITDATA_NOT_NATIVE_APPLIED",
             "diagnostic_only": True, "behavior_repair_claimed": False}
    delta_raw = jb(delta)
    put("derived/delta-manifest.json", delta_raw)
    members = {"source53-manifest.json": manifest_raw, "delta-manifest.json": delta_raw, "candidate.patch": patch}
    for side, values in (("before", before), ("after", after)):
        members.update({side + "/" + p: raw for p, raw in values.items()})
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(members):
            raw = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o600
            info.mtime = info.uid = info.gid = 0
            archive.addfile(info, io.BytesIO(raw))
    archive_raw = gzip.compress(tar_buffer.getvalue(), compresslevel=9, mtime=0)
    put("derived/source53-apply-input.tar.gz", archive_raw)
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
        extracted = {m.name: archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
        need(len(archive.getmembers()) == len(extracted) == 7 and extracted == members, "seven-member archive roundtrip differs")
    report = {"schema": "hepta.source53-actual-input-derivation.v1", "status": "ROOT_REVIEW_REQUIRED_NOT_NATIVE_EXECUTED",
              "source_commit": ACTUAL_COMMIT, "source_tree": ACTUAL_TREE, "source_parent_commit": BASE_COMMIT,
              "source_before_tree": BASE_TREE, "actual_Git_payloads_rehashed": 18, "actual_parent_child_links_verified": 16,
              "independent_base_overlay_recomputed_tree": rebuilt[""], "changed_leaves": list(PATHS),
              "all_other_tree_entries_and_modes_unchanged": True, "tree_inputs": tree_pins,
              "original195_manifest_object_values_and_json_slices_identical": True,
              "source_count": 197, "rust_count": 183, "other_count": 14,
              "owner_count": 26, "owners": owner_names, "new_leaf_owners": {p: owners[p] for p in PATHS},
              "owner_mapping_source": {"prior_actual_r29_metadata": pin(metadata_raw), "reused_only_because_dependency_inputs_unchanged": True,
                                        "fresh_source53_metadata_execution_claimed": False},
              "ci_selector_count": 27, "ci_selectors": selectors,
              "dual_locks_unchanged": True, "dependency_inputs_changed": [],
              "manifest": {"path": "derived/native-candidate-r30-source.json", **pin(manifest_raw)},
              "delta": {"path": "derived/delta-manifest.json", **pin(delta_raw)},
              "archive": {"path": "derived/source53-apply-input.tar.gz", **pin(archive_raw)},
              "archive_members": [{"path": name, **pin(raw)} for name, raw in sorted(members.items())],
              "diagnostic_only": True, "behavior_repair_claimed": False, "native_apply_executed": False,
              "native_gate_executed": False, "root_final_freeze_required": True}
    put("MANIFEST-DERIVATION-READBACK.json", jb(report))
    put("ROW-PRESERVATION.json", jb({"schema": "hepta.source53-original-row-preservation.v1",
        "source52_manifest": pin(base_raw), "source53_manifest": pin(manifest_raw), "old_rows": 195, "new_rows": 197,
        "all_original_values_identical": True, "all_original_object_json_slices_byte_identical": True,
        "old_row_slice_pins": [{"path": p, **pin(old_slices[p])} for p in old_slices]}))
    print(json.dumps({"manifest": pin(manifest_raw), "delta": pin(delta_raw), "archive": pin(archive_raw),
                      "members": 7, "count": 197, "rust": 183, "owners": 26, "CI": 27,
                      "tree": rebuilt[""], "actual_commit": ACTUAL_COMMIT, "applied": False}, indent=2))


if __name__ == "__main__":
    main()
