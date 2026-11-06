"""Offline verifier: never execute a native runner, query a host or modify refs."""
import ast
import base64
import collections
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read(name):
    return (HERE / name).read_bytes()


def js(name):
    return json.loads(read(name))


def matches(raw, pin):
    assert all(pin[k] == v for k, v in identity(raw).items())


def main():
    manifest = js("manifest-DISABLED.json")
    report = js("verification.json")
    old_manifest = js("originals/ca1/manifest-DISABLED.json")
    original = js("originals/original-V3-request-DISABLED.json")
    assert identity(read("originals/original-V3-request-DISABLED.json"))["git_blob"] == "b9b98905a2a323b5edb6f54148fbecc55c8ed34b"
    assert original["execute"] is False and original["root_execution_guard"] is None
    frozen = original["runner"]["source"].encode()
    assert frozen == read("originals/original-V3-reference-runner.py")
    assert identity(frozen) == report["original_V3_runner_identity"]
    assert identity(frozen)["sha256"] == "1201a4a2fec8d508f781f8f55f31ef1e60fb67747d08c7ff66794404128e9ed0"
    env = original["inputs"]
    packed = base64.b64decode(env["gzip_base64"], validate=True)
    assert hashlib.sha256(packed).hexdigest() == env["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert len(raw) == env["bytes"] and hashlib.sha256(raw).hexdigest() == env["sha256"]
    assert identity(raw) == report["frozen_V3_input_identity"]
    inputs = json.loads(raw)
    assert inputs["full_roster"] == js("originals/original-default-full-roster.json")
    roster = inputs["full_roster"]
    assert len(roster) == len({(r["binary_id"], r["name"]) for r in roster}) == 19563
    assert sum(not r["ignored"] for r in roster) == 19506 and sum(r["ignored"] for r in roster) == 57
    assert all(type(r["ignored"]) is bool for r in roster)
    selected = [n for n in ast.parse(frozen).body if isinstance(n, ast.FunctionDef) and n.name in {"need", "tree_hash"}]
    ns = {"hashlib": hashlib}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "pure-original-tree-hash", "exec"), ns)
    th = ns["tree_hash"]
    initial = {r["path"]: r for r in inputs["product_leaves"]}
    assert len(initial) == 10580 and th(initial.values()) == "b26598d0d97d8d51e723bb5582137315f2174d35"
    for r in inputs["candidate_posts"]:
        b = base64.b64decode(r["base64"], validate=True)
        matches(b, r["identity"])
        initial[r["path"]] = {"path": r["path"], "mode": "100644", "type": "blob", "sha": r["identity"]["git_blob"], "size": len(b)}
    assert th(initial.values()) == report["initial_tree"] == "e78c819b8b1f435f8b37bea17b4ffdc724961aa2"

    old_stage = js("originals/ca1/candidate-stage-inputs.json")
    stage = js("candidate-stage-inputs.json")
    matches(read("originals/ca1/candidate-stage-inputs.json"), old_manifest["stage_inputs"])
    matches(read("candidate-stage-inputs.json"), manifest["stage_inputs"])
    assert stage["historical_graph_reference"] == old_stage["historical_graph_reference"]
    hist = stage["historical_graph_reference"]
    graw = (json.dumps(hist["graph"], sort_keys=True, separators=(",", ":")) + "\n").encode()
    matches(graw, hist["graph_identity"])
    assert identity(graw) == report["historical_graph"]["identity"]
    assert len(hist["graph"]["workspace_members"]) == 193 and len(hist["graph"]["nodes"]) == 1501
    for k, old_k in [("bytes", "bytes"), ("sha256", "sha256")]:
        assert hist["raw_metadata_identity"][k] == inputs["historical_full_metadata"][old_k]
    candidates = []
    for data, count in [(old_stage, 12), (stage, 14)]:
        assert data["initial_tree"] == report["initial_tree"]
        assert len(data["changes"]) == len({r["path"] for r in data["changes"]}) == count
        candidate = dict(initial)
        for row in data["changes"]:
            before = initial.get(row["path"])
            assert (before is None) == (row["before"] is None)
            if before:
                assert row["before"] == {k: before[k] for k in ("mode", "sha")}
            b = base64.b64decode(row["base64"], validate=True)
            matches(b, row["identity"])
            candidate[row["path"]] = {"path": row["path"], "mode": row["mode"], "type": "blob", "sha": row["identity"]["git_blob"], "size": len(b)}
        assert sum(r["before"] is None for r in data["changes"]) == 2
        assert len(candidate) == 10582 and th(candidate.values()) == data["candidate_tree"]
        candidates.append(candidate)
    old_candidate, candidate = candidates
    assert old_stage["candidate_tree"] == report["prior_candidate"]["tree"] == "ca1c4671ef6b2773280d01b5d76c6166252f5856"
    assert stage["candidate_tree"] == report["new_candidate"]["tree"] == "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
    current = js("current-complete-source-leaves.json")
    assert current["tree"] == stage["candidate_tree"] and {r["path"]: r for r in current["leaves"]} == candidate
    delta = sorted(p for p in candidate if candidate[p] != old_candidate[p])
    assert delta == report["candidate_delta_paths"] and len(delta) == 3
    source_map = js("originals/publication/source-map.json")
    assert sorted(r["path"] for r in source_map) == delta
    for row in source_map:
        before = read("originals/ca1-source-preimages/" + row["path"].replace("/", "__") + ".source.txt")
        after = read("source-postimages/" + row["path"].replace("/", "__") + ".source.txt")
        matches(before, row["preimage"])
        matches(after, row["postimage"])
        assert old_candidate[row["path"]]["sha"] == row["preimage"]["git_blob"]
        assert candidate[row["path"]]["sha"] == row["postimage"]["git_blob"]
    root = js("originals/publication/actual-tree-root.json")["response"]
    commit = js("originals/publication/commit-ref-actual.json")
    assert root["sha"] == stage["candidate_tree"] and root["truncated"] is False
    assert commit["commit_actual"]["sha"] == current["publication_commit"] == stage["publication_commit"] == "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
    assert commit["commit_actual"]["tree"]["sha"] == root["sha"] == th(candidate.values())

    old_runner = read("originals/ca1/run_candidate_default_full.py")
    new_runner = read("run_candidate_default_full.py")
    matches(old_runner, old_manifest["runner"])
    matches(new_runner, manifest["runner"])
    expected = old_runner.decode()
    assert len(report["runner_replacement_pairs"]) == 7
    for old, new in report["runner_replacement_pairs"]:
        assert expected.count(old) == 1
        expected = expected.replace(old, new)
    assert expected.encode() == new_runner
    tree = ast.parse(new_runner)
    constants = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
    assert constants["PHASE_FREE"] == 64000000000
    assert "BUILD_MEM = 32 * 1024**3" in expected
    assert "environment['CARGO_BUILD_JOBS'] == '4'" in expected
    old_req = js("originals/ca1/request-DISABLED.json")
    new_req = js("request-DISABLED.json")
    matches(read("originals/ca1/request-DISABLED.json"), old_manifest["request"])
    matches(read("request-DISABLED.json"), manifest["request"])
    assert new_req["execute"] is False and new_req["root_execution_guard"] is None
    assert new_req["idempotency_key"] == report["new_key"] == "hepta-ai395-core-candidate-67cc5c28-full-20261105-v1"
    assert new_req["idempotency_key"] != old_req["idempotency_key"] == report["old_key"]
    normalized = dict(new_req)
    normalized.pop("rebind_provenance")
    normalized["idempotency_key"] = old_req["idempotency_key"]
    normalized["candidate_inputs"] = old_req["candidate_inputs"]
    assert normalized == old_req
    for req, path in [(old_req, "originals/ca1/candidate-stage-inputs.json"), (new_req, "candidate-stage-inputs.json")]:
        env = req["candidate_inputs"]
        packed = base64.b64decode(env["gzip_base64"], validate=True)
        assert len(packed) == env["gzip_bytes"] and hashlib.sha256(packed).hexdigest() == env["gzip_sha256"]
        raw = gzip.decompress(packed)
        matches(raw, env["identity"])
        assert raw == read(path)
    process = js("process-start-DISABLED.json")
    matches(read("process-start-DISABLED.json"), manifest["process_start"])
    assert process["args"] == ["-I", "-B", "-c", new_runner.decode()]
    assert process["stdin"] == read("request-DISABLED.json").decode()
    assert process["host"] == "ai395" and process["executable"] == "/usr/bin/python3" and process["timeout_seconds"] == 21600
    assert process["cwd"] == "/" and process["env"] == {} and process["idempotency_key"] == report["new_key"]
    assert manifest["commands"] == old_manifest["commands"] == [original["plan"]["phases"][3]["commands"][0]] + original["plan"]["phases"][5]["commands"]
    assert manifest["resource_floors"] == old_manifest["resource_floors"]
    assert manifest["later_original_Agentd_scope_DISABLED"] == old_manifest["later_original_Agentd_scope_DISABLED"]
    assert manifest["not_automatic"] == old_manifest["not_automatic"]
    assert manifest["execute"] is False and manifest["root_execution_guard"] is None and manifest["native_actions_performed_by_preparation"] == 0
    stop = js("originals/ca1-stop/candidate-default-full-terminal.json")
    guard = js("originals/ca1-stop/candidate-default-full-final-source-guard.json")
    assert stop["final_source_guard"] == guard and guard["source_tree"] == report["initial_tree"]
    assert stop["source_mutations"] == stop["commands"] == stop["build_commands"] == []
    assert stop["controller_exit_code"] == 1 and "cold build memory prerequisite" in stop["error"]
    assert report["native_execution"] is False and report["host_resource_query"] is False and report["product_qualified"] is False
    print(json.dumps({"decision": "PREPARED_DISABLED_FOR_ROOT_REVIEW", "new_head": stage["publication_commit"], "new_tree": stage["candidate_tree"], "candidate_delta": 3, "transition_delta": 14, "leaf_count": 10582, "historical_graph_members": 193, "historical_graph_nodes": 1501, "full_roster": {"total": 19563, "eligible": 19506, "ignored": 57}, "new_key": new_req["idempotency_key"], "native_execution": False, "product_qualified": False}, sort_keys=True))


if __name__ == "__main__":
    main()
