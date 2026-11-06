"""Derive a disabled 67cc full-gate request from the frozen ca1 preparation.

Cloud-only: reads local originals, recomputes identities and writes a new packet.
It neither imports nor invokes the native runner and performs no host query.
"""
import ast
import base64
import collections
import copy
import difflib
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
CORE = WORK / "ci-audit/core-wait-span-20261105"
OLD = CORE / "ai395-candidate-default-full-v1"
PUBLISHED = WORK / "hepta-audit-fifth/main-format-retention"
NEW_HEAD = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
NEW_TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
OLD_HEAD = "eed4d6bb61b789b19f60facc79f9e031765fa4c9"
OLD_TREE = "ca1c4671ef6b2773280d01b5d76c6166252f5856"
INITIAL = "e78c819b8b1f435f8b37bea17b4ffdc724961aa2"
OLD_KEY = "hepta-ai395-core-candidate-ca1-full-20261105-v1"
NEW_KEY = "hepta-ai395-core-candidate-67cc5c28-full-20261105-v1"
OLD_OUT = "/home/qq/work/hepta-core-musl-full-20261105/candidate-default-full-v1"
NEW_OUT = "/home/qq/work/hepta-core-musl-full-20261105/candidate-67cc5c28-default-full-v1"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def pin(path):
    return {"local_path": str(path), **identity(path.read_bytes())}


def put(name, raw):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, "frozen output changed: " + name
    else:
        path.write_bytes(raw)
    return pin(path)


def put_json(name, value):
    return put(name, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def leaf_signature(rows):
    return {r["path"]: (r["mode"], r["sha"], r["type"]) for r in rows}


def main():
    # The actual native request differs in enabled/guard fields. Its frozen V3
    # definitions and nested input bytes are shared with this disabled original.
    original_path = CORE / "native-project-request-DISABLED-v3.json"
    original_raw = original_path.read_bytes()
    assert identity(original_raw)["git_blob"] == "b9b98905a2a323b5edb6f54148fbecc55c8ed34b"
    original = json.loads(original_raw)
    assert original["execute"] is False and original["root_execution_guard"] is None
    frozen_source = original["runner"]["source"]
    assert identity(frozen_source.encode())["sha256"] == "1201a4a2fec8d508f781f8f55f31ef1e60fb67747d08c7ff66794404128e9ed0"
    envelope = original["inputs"]
    packed = base64.b64decode(envelope["gzip_base64"], validate=True)
    assert hashlib.sha256(packed).hexdigest() == envelope["gzip_sha256"]
    raw_inputs = gzip.decompress(packed)
    assert len(raw_inputs) == envelope["bytes"] == 5555376
    assert hashlib.sha256(raw_inputs).hexdigest() == envelope["sha256"] == "4a51c7ecb2288ea403f3f79e221459b1d6b31329fb6fa4a09b5df1937847f43a"
    inputs = json.loads(raw_inputs)
    pure_names = {"need", "tree_hash", "graph"}
    selected = [n for n in ast.parse(frozen_source).body if isinstance(n, ast.FunctionDef) and n.name in pure_names]
    assert {n.name for n in selected} == pure_names
    namespace = {"hashlib": hashlib}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "pure-original-source-map-functions", "exec"), namespace)
    tree_hash = namespace["tree_hash"]
    initial = {r["path"]: r for r in inputs["product_leaves"]}
    assert len(initial) == 10580 and tree_hash(initial.values()) == "b26598d0d97d8d51e723bb5582137315f2174d35"
    for post in inputs["candidate_posts"]:
        raw = base64.b64decode(post["base64"], validate=True)
        assert identity(raw) == post["identity"]
        initial[post["path"]] = {"path": post["path"], "mode": "100644", "type": "blob", "sha": post["identity"]["git_blob"], "size": len(raw)}
    assert len(inputs["candidate_posts"]) == 2 and tree_hash(initial.values()) == INITIAL

    old_manifest = json.loads((OLD / "manifest-DISABLED.json").read_bytes())
    old_stage_raw = (OLD / "candidate-stage-inputs.json").read_bytes()
    old_request_raw = (OLD / "request-DISABLED.json").read_bytes()
    old_runner_raw = (OLD / "run_candidate_default_full.py").read_bytes()
    for name, raw in [("stage_inputs", old_stage_raw), ("request", old_request_raw), ("runner", old_runner_raw)]:
        assert all(old_manifest[name][k] == v for k, v in identity(raw).items())
    stage = json.loads(old_stage_raw)
    assert stage["candidate_tree"] == OLD_TREE and stage["initial_tree"] == INITIAL and stage["publication_commit"] == OLD_HEAD
    assert len(stage["changes"]) == 12
    old_candidate = copy.deepcopy(initial)
    for row in stage["changes"]:
        previous = initial.get(row["path"])
        assert (previous is None) == (row["before"] is None)
        if previous:
            assert {k: previous[k] for k in ("mode", "sha")} == row["before"]
        raw = base64.b64decode(row["base64"], validate=True)
        assert identity(raw) == row["identity"]
        old_candidate[row["path"]] = {"path": row["path"], "mode": row["mode"], "type": "blob", "sha": row["identity"]["git_blob"], "size": len(raw)}
    assert len(old_candidate) == 10582 and tree_hash(old_candidate.values()) == OLD_TREE

    source_map = json.loads((PUBLISHED / "source-map.json").read_bytes())
    assert {r["path"] for r in source_map} == {"codex-rs/core/src/agent/control_tests.rs", "codex-rs/core/src/environment_selection.rs", ".github/scripts/collect_bazel_failed_test_logs.py"}
    final = copy.deepcopy(old_candidate)
    changes = {r["path"]: copy.deepcopy(r) for r in stage["changes"]}
    new_source_files = []
    for row in source_map:
        before = Path(row["preimage_file"]).read_bytes()
        after = Path(row["postimage_file"]).read_bytes()
        assert identity(before) == row["preimage"] and identity(after) == row["postimage"]
        assert old_candidate[row["path"]]["sha"] == row["preimage"]["git_blob"]
        previous = initial[row["path"]]
        changes[row["path"]] = {"path": row["path"], "mode": previous["mode"], "before": {k: previous[k] for k in ("mode", "sha")}, "identity": identity(after), "base64": base64.b64encode(after).decode()}
        final[row["path"]] = {"path": row["path"], "mode": previous["mode"], "type": "blob", "sha": row["postimage"]["git_blob"], "size": len(after)}
        new_source_files.append(put("source-postimages/" + row["path"].replace("/", "__") + ".source.txt", after))
    assert len(changes) == 14 and sum(r["before"] is None for r in changes.values()) == 2
    assert tree_hash(final.values()) == NEW_TREE and len(final) == 10582
    published = json.loads((PUBLISHED / "intended-full-tree.json").read_bytes())
    published_leaves = [r for r in published["tree"] if r["type"] != "tree"]
    assert published["sha"] == NEW_TREE and published["truncated"] is False
    assert leaf_signature(final.values()) == leaf_signature(published_leaves)
    actual_root = json.loads((PUBLISHED / "actual-tree-root.json").read_bytes())["response"]
    assert actual_root["sha"] == NEW_TREE and actual_root["truncated"] is False
    expected_root = [r for r in published["tree"] if "/" not in r["path"]]
    assert leaf_signature(expected_root) == leaf_signature(actual_root["tree"])
    publication = json.loads((PUBLISHED / "commit-ref-actual.json").read_bytes())
    assert publication["commit_actual"]["sha"] == NEW_HEAD
    assert publication["commit_actual"]["tree"]["sha"] == NEW_TREE
    assert publication["ref_actual"]["object"]["sha"] == NEW_HEAD
    actual_delta = sorted(p for p in final if (final[p]["mode"], final[p]["sha"]) != (old_candidate[p]["mode"], old_candidate[p]["sha"]))
    assert actual_delta == sorted(r["path"] for r in source_map)
    from_initial = sorted(p for p in final if p not in initial or (final[p]["mode"], final[p]["sha"]) != (initial[p]["mode"], initial[p]["sha"]))
    assert from_initial == sorted(changes)

    metadata_path = CORE / "project-nonpass-complete-v1/decoded-verified-v1/candidate-full-metadata.stdout"
    metadata_raw = metadata_path.read_bytes()
    historical = stage["historical_graph_reference"]
    assert identity(metadata_raw) == historical["raw_metadata_identity"]
    graph = namespace["graph"](json.loads(metadata_raw))
    graph_raw = (json.dumps(graph, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert graph == historical["graph"] and identity(graph_raw) == historical["graph_identity"]
    assert len(graph["workspace_members"]) == 193 and len(graph["nodes"]) == 1501
    assert len(inputs["full_roster"]) == 19563
    assert sum(not r["ignored"] for r in inputs["full_roster"]) == 19506
    assert sum(r["ignored"] for r in inputs["full_roster"]) == 57
    assert not any(p.endswith("Cargo.toml") or p.endswith("Cargo.lock") or p in ("MODULE.bazel.lock", "MODULE.bazel", ".cargo/config.toml", "codex-rs/.cargo/config.toml", "justfile") for p in from_initial)
    assert old_manifest["resource_floors"]["disk_bytes_before_after_every_command"] == 64000000000
    assert old_manifest["resource_floors"]["MemAvailable_bytes"] == 34359738368
    assert old_manifest["resource_floors"]["CARGO_BUILD_JOBS"] == 4

    old_stop_path = OLD / "native-first-start/native-originals/candidate-default-full-terminal.json"
    old_guard_path = OLD / "native-first-start/native-originals/candidate-default-full-final-source-guard.json"
    old_stop = json.loads(old_stop_path.read_bytes())
    old_guard = json.loads(old_guard_path.read_bytes())
    assert old_stop["source_mutations"] == old_stop["commands"] == old_stop["build_commands"] == []
    assert old_stop["tests_executed"] == old_stop["metadata_executed"] == old_stop["catalogs_executed"] == old_stop["hygiene_executed"] == 0
    assert old_stop["source_expected_at_stop"] == old_guard["source_tree"] == INITIAL
    assert old_stop["final_source_guard"] == old_guard
    assert old_stop["controller_exit_code"] == 1 and "cold build memory prerequisite" in old_stop["error"]
    assert old_guard["ordinary_index"]["sha256"] == old_manifest["ordinary_index_sha256"]

    stage["candidate_tree"], stage["publication_commit"] = NEW_TREE, NEW_HEAD
    stage["prior_composition_manifest"] = stage["composition_manifest"]
    stage["composition_manifest"] = pin(PUBLISHED / "root-tree-proof.json")
    stage["changes"] = list(changes.values())
    stage["rebind_provenance"] = {"prior_stage_inputs": pin(OLD / "candidate-stage-inputs.json"), "exact_ca1_to_current_paths": actual_delta, "publication_source_map": pin(PUBLISHED / "source-map.json"), "actual_publication": pin(PUBLISHED / "commit-ref-actual.json"), "actual_tree_root": pin(PUBLISHED / "actual-tree-root.json"), "proof_method": "Complete derived leaves and recomputed Merkle root match the actual published Git root; not a new recursive-tree GET."}
    stage_pin = put_json("candidate-stage-inputs.json", stage)
    stage_raw = (HERE / "candidate-stage-inputs.json").read_bytes()
    zipped = gzip.compress(stage_raw, mtime=0)
    new_envelope = {"identity": identity(stage_raw), "gzip_bytes": len(zipped), "gzip_sha256": hashlib.sha256(zipped).hexdigest(), "gzip_mtime": 0, "gzip_base64": base64.b64encode(zipped).decode()}
    assert gzip.decompress(base64.b64decode(new_envelope["gzip_base64"], validate=True)) == stage_raw

    source = old_runner_raw.decode()
    replacements = [
        ("Only the reviewed12-file e78-to-ca1 transition", "Only the reviewed14-file e78-to-3982 transition"),
        ("OUT = ROOT / 'candidate-default-full-v1'", "OUT = ROOT / 'candidate-67cc5c28-default-full-v1'"),
        ("FINAL_TREE = '" + OLD_TREE + "'", "FINAL_TREE = '" + NEW_TREE + "'"),
        ("PUBLICATION_COMMIT = '" + OLD_HEAD + "'", "PUBLICATION_COMMIT = '" + NEW_HEAD + "'"),
        ("len(changes) == 12 and len({row['path'] for row in changes}) == 12", "len(changes) == 14 and len({row['path'] for row in changes}) == 14"),
        ("'exact twelve changes from e78'", "'exact fourteen changes from e78'"),
        (OLD_KEY, NEW_KEY),
    ]
    for before, after in replacements:
        assert source.count(before) == 1, before
        source = source.replace(before, after)
    ast.parse(source)
    reverse = source
    for before, after in reversed(replacements):
        assert reverse.count(after) == 1
        reverse = reverse.replace(after, before)
    assert reverse.encode() == old_runner_raw
    old_functions = {n.name: ast.get_source_segment(old_runner_raw.decode(), n) for n in ast.parse(old_runner_raw).body if isinstance(n, ast.FunctionDef)}
    new_functions = {n.name: ast.get_source_segment(source, n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    equal_functions = [k for k in old_functions if old_functions[k] == new_functions[k]]
    assert set(old_functions) - set(equal_functions) == {"bind_candidate", "main"}
    assert old_functions["main"].replace(OLD_KEY, NEW_KEY) == new_functions["main"]
    assert old_functions["bind_candidate"].replace("== 12", "== 14").replace("exact twelve", "exact fourteen") == new_functions["bind_candidate"]
    runner_pin = put("run_candidate_default_full.py", source.encode())
    delta_pin = put("ca1-to-67cc-preparation.delta.patch", "".join(difflib.unified_diff(old_runner_raw.decode().splitlines(True), source.splitlines(True), fromfile="ca1/run_candidate_default_full.py", tofile="67cc/run_candidate_default_full.py")).encode())
    request = json.loads(old_request_raw)
    assert request["execute"] is False and request["root_execution_guard"] is None and request["idempotency_key"] == OLD_KEY
    request["idempotency_key"] = NEW_KEY
    request["candidate_inputs"] = new_envelope
    request["rebind_provenance"] = {"prior_request": pin(OLD / "request-DISABLED.json"), "prior_actual_ca1_resource_stop": pin(old_stop_path), "prior_actual_ca1_final_source_guard": pin(old_guard_path), "ordinary_native_source_remains": INITIAL, "new_output_directory": NEW_OUT, "admission": "DISABLED. No new host/resource query was performed. A concrete new capacity basis and root review are required before any first start; the original runtime capacity and source guards remain mandatory.", "native_execution_performed": False}
    request_pin = put_json("request-DISABLED.json", request)
    assert request_pin["bytes"] < 1048576
    old_process = json.loads((OLD / "process-start-DISABLED.json").read_bytes())
    process = copy.deepcopy(old_process)
    process["args"] = ["-I", "-B", "-c", source]
    process["stdin"] = (HERE / "request-DISABLED.json").read_text()
    process["idempotency_key"] = NEW_KEY
    assert process["host"] == "ai395" and process["executable"] == "/usr/bin/python3" and process["timeout_seconds"] == 21600
    assert process["cwd"] == "/" and process["env"] == {}
    process_pin = put_json("process-start-DISABLED.json", process)
    tree_pin = put_json("current-complete-source-leaves.json", {"schema": "complete-prepared-rebound-source-v1", "publication_commit": NEW_HEAD, "tree": NEW_TREE, "leaves": sorted(final.values(), key=lambda r: r["path"]), "actual_tree_root": pin(PUBLISHED / "actual-tree-root.json")})
    report = {"schema": "linux-full-67cc-cloud-rebind-verification-v1", "decision": "PREPARED_DISABLED_FOR_ROOT_REVIEW", "native_execution": False, "host_resource_query": False, "product_qualified": False, "source_ref_modified": False, "initial_tree": INITIAL, "prior_candidate": {"commit": OLD_HEAD, "tree": OLD_TREE}, "new_candidate": {"commit": NEW_HEAD, "tree": NEW_TREE}, "candidate_delta_paths": actual_delta, "candidate_delta_count": 3, "from_initial_changed_paths": from_initial, "from_initial_changed_count": 14, "new_files": 2, "leaves": 10582, "complete_derived_tree_equal_to_actual_published_root": True, "original_complete_default_roster": {"total": 19563, "eligible": 19506, "ignored": 57}, "historical_graph": {"identity": identity(graph_raw), "members": 193, "nodes": 1501, "current_native_comparison": "NOT_RUN; unchanged original runner requires fresh complete equality after only source-directory normalization"}, "frozen_V3_input_identity": identity(raw_inputs), "original_V3_runner_identity": identity(frozen_source.encode()), "runner_replacement_pairs": replacements, "all_other_runner_bytes_unchanged": True, "all_other_top_level_functions_byte_equal": equal_functions, "original_full_commands_byte_equal": True, "resource_floors": old_manifest["resource_floors"], "old_key": OLD_KEY, "new_key": NEW_KEY, "old_output_directory": OLD_OUT, "new_output_directory": NEW_OUT, "old_stop": {"terminal": pin(old_stop_path), "source_guard": pin(old_guard_path), "no_source_build_catalog_test_or_hygiene_before_stop": True}, "source_after_future_full": "Exact new published tree is required; prior source/index/lock/tool/physical guards unchanged.", "later_order": "Original default full first; root reviews actual results; original scoped fixes, then original fmt. This packet does not automatically run hygiene or any separate qualification feature scope.", "limitations": ["No current host memory/disk observation; old RAM stop is not admission evidence.", "No new compilation, metadata command, catalog command or test result.", "Old B16 UNKNOWN driver is not accessed or replayed.", "The ordinary checkout HEAD/index remain 5b and their original bytes; the qualified identity would be the exact controlled working tree 3982, not a fictitious checkout of 67cc.", "The original Agentd qualification feature scope remains a distinct subsequent root review; no default-scope count substitutes for it."], "preparation_observation": "Initial informal overlap estimate of 13 changes was corrected before generation: environment_selection was already in e78, so old12 + environment + collector =14; only control_tests replaces an existing old-stage row."}
    review_pin = put_json("verification.json", report)
    manifest = copy.deepcopy(old_manifest)
    manifest.update({"schema": "ai395-67cc-rebound-default-full-disabled-manifest-v1", "publication_commit": NEW_HEAD, "working_tree_after_transition": NEW_TREE, "runner": runner_pin, "request": request_pin, "process_start": process_pin, "delta": delta_pin, "runner_derivation": review_pin, "stage_inputs": stage_pin, "compressed_input_bytes": len(zipped), "new_idempotency_key": NEW_KEY, "new_output_directory": NEW_OUT, "source_transition": {"from": INITIAL, "to": NEW_TREE, "changed_from_e78": 14, "new_files": 2, "final_leaves": 10582, "changes": [{k: r[k] for k in ("path", "mode", "before", "identity")} for r in changes.values()]}, "previous_disabled_manifest": pin(OLD / "manifest-DISABLED.json"), "complete_prepared_source_identity": tree_pin, "source_postimages": new_source_files, "guard_reuse": "Original ca1 runner differs only in seven reviewed substitutions: description, output directory, final tree, publication commit, exact14 change count/label, and unique key. All other bytes including capacity/source/tool/catalog/program/JUnit/lock/index/no-retry controls remain unchanged.", "admission": request["rebind_provenance"]["admission"]})
    assert manifest["execute"] is False and manifest["root_execution_guard"] is None
    assert manifest["native_actions_performed_by_preparation"] == 0
    assert manifest["commands"] == [original["plan"]["phases"][3]["commands"][0]] + original["plan"]["phases"][5]["commands"]
    manifest_pin = put_json("manifest-DISABLED.json", manifest)
    print(json.dumps({"manifest": manifest_pin, "verification": review_pin, "stage_inputs": stage_pin, "runner": runner_pin, "request": request_pin, "process": process_pin, "new_key": NEW_KEY, "native_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
