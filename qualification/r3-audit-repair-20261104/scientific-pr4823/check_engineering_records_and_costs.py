#!/usr/bin/env python3
"""Read frozen JSON/gzip records only; never import or execute experiment code."""
from datetime import datetime, timezone
from hashlib import sha1, sha256
from pathlib import Path
import gzip
import json
import math
import re
import time

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "package"
INPUTS = {}


def raw(name):
    path = PACKAGE / name
    assert path.is_file() and not path.is_symlink()
    data = path.read_bytes()
    INPUTS[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest(),
                    "git_blob": sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
    return data


def unique(pairs):
    out = {}
    for k, v in pairs:
        assert k not in out, k
        out[k] = v
    return out


def parse(data):
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def read(name):
    return parse(raw(name))


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def rows(name):
    # gzip.decompress validates CRC and complete uncompressed body.
    if (PACKAGE / name).is_file():
        payload = raw(name)
    else:
        parts = read(name + ".parts.json")
        chunks = []
        for item in parts["parts"]:
            assert Path(item["name"]).name == item["name"]
            chunk = raw(str(Path(name).parent / item["name"]))
            assert len(chunk) == item["bytes"] and sha256(chunk).hexdigest() == item["sha256"]
            chunks.append(chunk)
        payload = b"".join(chunks)
        assert len(payload) == parts["bytes"] and sha256(payload).hexdigest() == parts["sha256"]
    return [parse(line) for line in gzip.decompress(payload).splitlines()]


def main():
    cpu_start, wall_start = time.process_time(), time.monotonic()
    manifest = read("PAYLOAD_MANIFEST.json")
    index = json.loads((ROOT / "package-file-index.json").read_text())
    indexed = {x["path"]: x for x in index}
    listed = {x["path"]: x for x in manifest["files"]}
    assert len(indexed) == len(index) == 452
    assert len(listed) == len(manifest["files"]) == 451
    assert set(indexed) == set(listed) | {"PAYLOAD_MANIFEST.json"}
    for name, item in indexed.items():
        data = raw(name)
        assert len(data) == item["size"] and INPUTS[name]["git_blob"] == item["sha"]
        if name in listed:
            assert len(data) == listed[name]["bytes"]
            assert INPUTS[name]["sha256"] == listed[name]["sha256"]
    assert sum(x["bytes"] for x in listed.values()) == manifest["bytes_excluding_manifest"] == 39340003
    assert {p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob("*") if p.is_file()} == set(indexed)

    native_prefix = "native_bellman_replay/"
    counts = {"worlds": 0, "nodes": 0, "legal_q": 0, "exact_values": 0,
              "exact_actions": 0, "exact_masks": 0, "saved_J_utilities_equal": 0}
    world_ids, request_ids = set(), set()
    for fit in (11, 23, 37, 53, 71):
        for domain in ("iid", "ood"):
            tail = f"fit_{fit}_{domain}.jsonl.gz"
            requested = rows(native_prefix + "export_r1/run/requests/" + tail)
            references = rows(native_prefix + "export_r1/run/references/" + tail)
            responses = rows(native_prefix + "native_corpus/" + tail)
            comparisons = rows(native_prefix + "replay_r1/run/comparisons/" + tail)
            replay = rows(native_prefix + "replay_r1/run/replay/" + tail)
            assert len(requested) == len(references) == len(responses) == len(comparisons) == len(replay) == 32
            for req, ref, response, comp, rep in zip(requested, references, responses, comparisons, replay):
                identifier = req["request_id"]
                assert identifier not in request_ids
                request_ids.add(identifier)
                assert all(x["request_id"] == identifier for x in (ref, response, comp, rep))
                metadata, result = ref["metadata"], response["response"]
                assert metadata["fit"] == rep["fit"] == fit and metadata["domain"] == rep["domain"] == domain
                wid = metadata["world_id"]
                assert wid not in world_ids and rep["world_id"] == comp["world_id"] == ref["public"]["id"] == wid
                world_ids.add(wid)
                assert digest(req["params"]) == metadata["graph_params_sha256"] == response["graph_params_sha256"] == comp["graph_params_sha256"]
                assert digest(response) == comp["native_response_sha256"]
                assert digest(ref["public"]) == metadata["public_sha256"]
                assert result["request_sha256"] == comp["native_typed_serde_request_sha256"]
                assert response["rpc_error"] is None and comp["passed"] and comp["errors"] == []
                assert all(result[k] is False for k in ("checkpoint_verified", "environment_law_verified",
                           "independent_holdout_verified", "production_eligible", "real_arithmetic_optimality_certified"))
                assert result["state_count"] == metadata["nodes"] == comp["nodes"] == len(ref["states"]) == len(result["states"]) == len(req["params"]["states"])
                legal_count = 0
                for original, actual, graph in zip(ref["states"], result["states"], req["params"]["states"]):
                    assert original["action"] == actual["action"]
                    assert original["value"] == actual["value"]
                    assert original["legal"] == [a is not None for a in graph["actions"]] == [q is not None for q in actual["q"]]
                    for i, legal in enumerate(original["legal"]):
                        if legal:
                            assert original["q"][i] == actual["q"][i]
                            legal_count += 1
                    counts["exact_actions"] += 1
                    counts["exact_values"] += 1
                    counts["exact_masks"] += 1
                assert legal_count == comp["legal_Q_count"] == result["legal_action_count"]
                assert all(comp[k] == 0 for k in ("max_reference_Q_absolute_error", "max_reference_value_absolute_error", "max_scalar_graph_Q_absolute_error"))
                assert rep["utility_passed"] and rep["native_J"]["utility"] == rep["scientific_J_utility"] and rep["utility_absolute_error"] == 0
                counts["worlds"] += 1
                counts["nodes"] += len(ref["states"])
                counts["legal_q"] += legal_count
                counts["saved_J_utilities_equal"] += 1
    assert counts["worlds"] == 320 and counts["nodes"] == 246160 and counts["legal_q"] == 928200

    q = read("qwen_cache/receipt.json")
    protocol, pins = read("qwen_cache/protocol.json"), read("qwen_cache/runtime_pins.json")
    assert q["protocol"] == protocol
    assert q["protocol_sha256"] == INPUTS["qwen_cache/protocol.json"]["sha256"]
    assert q["runtime_pins_sha256"] == INPUTS["qwen_cache/runtime_pins.json"]["sha256"]
    assert q["source_sha256"] == INPUTS["qwen_cache/qualify_cache.py"]["sha256"]
    assert q["runtime_identity"]["dependencies"] == pins["dependencies"]
    assert q["runtime_identity"]["transformers_sources"] == pins["transformers_sources"]
    assert protocol["comparator"]["atol"] == protocol["comparator"]["rtol"] == .001
    q_summary = {"recorded_forwards": 0, "recorded_comparisons": 0, "recorded_appended_tokens": 0, "variants": []}
    for variant in protocol["variants"]:
        v = read(f"qwen_cache/{variant}.json")
        assert v == q["variants"][variant]
        assert v["forwards"] == {"cached_prefill": 1, "incremental_cached": 8, "full_prefix_reference": 9}
        assert [x["prefix_tokens"] for x in v["comparisons"]] == list(range(7, 16))
        assert v["appended_tokens"] == [x["cached_argmax"] for x in v["comparisons"][:-1]]
        assert v["execution"]["device"] == "cpu" and v["execution"]["learned_dtype"] == "torch.float32"
        for i, x in enumerate(v["comparisons"]):
            assert x["step"] == i and x["cache_sequence_length"] == x["prefix_tokens"]
            assert x["finite"] and x["allclose"] and x["greedy_equal"]
            assert x["cached_argmax"] == x["reference_argmax"]
            assert math.isfinite(x["maximum_ratio_to_fixed_tolerance"]) and 0 <= x["maximum_ratio_to_fixed_tolerance"] <= 1
            assert all(re.fullmatch("[0-9a-f]{64}", x[k]) for k in ("cached_f32_logits_sha256", "reference_f32_logits_sha256"))
        q_summary["recorded_forwards"] += sum(v["forwards"].values())
        q_summary["recorded_comparisons"] += len(v["comparisons"])
        q_summary["recorded_appended_tokens"] += len(v["appended_tokens"])
        q_summary["variants"].append({"variant": variant, "max_recorded_absolute_logit_difference": max(x["maximum_absolute_logit_difference"] for x in v["comparisons"])})
    assert (q_summary["recorded_forwards"], q_summary["recorded_comparisons"], q_summary["recorded_appended_tokens"]) == (36, 18, 16)
    q_summary.update({"logit_arrays_available_for_recalculation": False, "new_model_load_or_forward": False,
                     "original_bf16_vllm_or_capability_qualification": False})

    snap = read("pocket4/session_end_snapshot/public_snapshot.json")
    capture = read("pocket4/session_end_snapshot/capture_receipt.json")
    assert capture["public_snapshot_sha256"] == INPUTS["pocket4/session_end_snapshot/public_snapshot.json"]["sha256"]
    assert capture["public_snapshot_bytes"] == INPUTS["pocket4/session_end_snapshot/public_snapshot.json"]["bytes"]
    assert all(snap[k] is False for k in ("atomic_cross_file_snapshot", "base_weight_content_refreshed", "model_forward_executed", "performance_qualified", "training_started"))
    assert snap["read_only"] is True and snap["orders_sent"] == snap["broker_queries_sent"] == 0
    assert snap["adapter"]["parameter_count"] == sum(x["parameters"] for x in snap["adapter"]["tensors"]) == 2379
    assert snap["adapter"]["tensor_count"] == len(snap["adapter"]["tensors"]) == 6

    ledger = []
    def cost(stage, path, cpu, wall, scope, overlap=None, exit_code=None):
        ledger.append({"stage": stage, "path": path, "source_identity": INPUTS[path],
                       "reported_cpu_seconds": cpu, "reported_wall_seconds": wall,
                       "scope": scope, "overlap": overlap, "exit_code": exit_code})
    for stage, path in (("primary_worker", "ndu_policy/execution_r1/PROCESS_RECEIPT.json"),
                        ("replay_failed_invocation", "independent_replay/attempt_1/PROCESS_RECEIPT.json"),
                        ("replay_worker", "independent_replay/attempt_2/PROCESS_RECEIPT.json")):
        rec = read(path)
        assert math.isclose(rec["child_total_cpu_seconds"], rec["child_user_cpu_seconds"] + rec["child_system_cpu_seconds"], abs_tol=1e-10)
        cost(stage, path, rec["child_total_cpu_seconds"], rec["elapsed_wall_seconds"],
             "complete waited worker; separate controller window not included", exit_code=rec["exit_code"])
    p = "ndu_policy/execution_r1/VERIFICATION_PROCESS_RECEIPT.json"; v = read(p)
    cost("primary_record_verifier", p, v["child_user_cpu_seconds"]+v["child_system_cpu_seconds"], v["wall_seconds"], "waited verifier child", exit_code=v["exit_code"])
    p = "independent_replay/attempt_2/ACCEPTANCE_PROCESS_RECEIPT.json"; v = read(p)
    cost("replay_acceptance_two_children", p, sum(x["full_child_cpu_seconds"] for x in v["stages"]),
         sum(x["full_child_wall_seconds"] for x in v["stages"]), "two sequential verifier children; controller windows separate")
    p = "train_margin_certificate/execution_r1/PROCESS_RECEIPT.json"; v = read(p)
    cost("train_certificate_pipeline", p, v["whole_pipeline_cpu_seconds"], v["wall_seconds"], v["scope"],
         "producer/verifier children are nested and must not be added", v["exit_code"])
    p = "ROOT_TRAIN_CERTIFICATE_VERIFICATION.json"; v = read(p)
    cost("archived_root_records_only_certificate_verifier", p, v["full_child_cpu_seconds"], v["full_child_wall_seconds"], v["scope"], exit_code=v["exit_code"])
    for stage, p in (("native_graph_export", "native_bellman_replay/export_r1/PROCESS_RECEIPT.json"),
                     ("native_verifier_and_J_replay", "native_bellman_replay/replay_r1/PROCESS_RECEIPT.json")):
        v = read(p)
        cost(stage, p, v["child_total_cpu_seconds"], v["wall_seconds"], "complete waited child; separate controller window excluded", exit_code=v["exit_code"])
    p = "native_bellman_replay/native_corpus/WHOLE_PROCESS_RECEIPT.json"; v = read(p)
    cost("native_mcp_driver_and_descendants", p, v["driver_and_descendants_user_cpu_seconds"]+v["driver_and_descendants_system_cpu_seconds"],
         v["wall_seconds"], v["measurement"], v["scope_limit"], v["exit_code"])
    p = "native_bellman_replay/native_corpus/LOCAL_QUALIFICATION.json"; local = read(p)
    cost("native_six_build_and_qualification_commands", p,
         sum(x["child_user_cpu_seconds"]+x["child_system_cpu_seconds"] for x in local["commands"]),
         sum(x["wall_seconds"] for x in local["commands"]),
         "six waited command records; overlay source qualifies exact recorded manifest, not declared base head alone")
    ledger[-1]["reported_outer_qualification_wall_seconds"] = local["total_wall_seconds"]
    ledger[-1]["outer_minus_command_wall_seconds"] = local["total_wall_seconds"] - ledger[-1]["reported_wall_seconds"]
    assert ledger[-1]["outer_minus_command_wall_seconds"] >= 0
    p = "qwen_cache/receipt.json"
    cost("qwen_measured_supervisor_window_and_waited_children", p,
         q["measurement"]["owned_child_cpu_seconds"]+q["measurement"]["supervisor_cpu_seconds"],
         q["measurement"]["wall_seconds"], "not complete supervisor lifetime; imports/argument parsing/final publication excluded",
         "per-variant worker internal CPU is nested; RSS is not a tree sum")
    for stage,p in (("preparation_1", "ndu_policy/PREPARATION_CHECK.json"),
                    ("preparation_2", "ndu_policy/PREPARATION_CHECK_FINAL.json"),
                    ("input_acquisition_receipt", "ndu_policy/INPUT_ACQUISITION_RECEIPT.json")):
        v=read(p);cost(stage,p,v["cpu_seconds"],v["wall_seconds"],"in-process recorded measurement; not entire author workflow")
    stage_map = {x["stage"]:x for x in ledger}
    native_sum = sum(stage_map[k]["reported_cpu_seconds"] for k in ("native_graph_export", "native_mcp_driver_and_descendants", "native_verifier_and_J_replay"))
    assert math.isclose(native_sum, 228.943315, abs_tol=1e-8)
    costs = {"schema":"hepta.audit.pr4823.cost-record-review.v1", "complete_cost_accounting":False,
             "records":ledger, "native_three_nonoverlapping_stages_cpu_seconds":native_sum,
             "total_not_provided":"No complete additive total: nested alternative columns and unmetered/unsupported components remain.",
             "gaps":["All agent tokens, source editing, complete environment setup, network transfer, energy and monetary costs are not accounted.",
                     "First native journal compile failure CPU is unknown; official runtime CI runner CPU is unknown.",
                     "Prior trust compatibility/journal-contract CPU appear in summary sources; their original process receipts are outside this 452-file package.",
                     "README public-input recovery 2.702490917 remote + 0.184370975 local is not the 1.438252137 CPU in the packaged acquisition receipt; the extra components lack separately matched receipts here.",
                     "D/G inclusive construction costs share charges and are nested in primary worker; neither sum is a completed equal-quality speedup."]}
    costs["native_local_source_scope"]={k:local[k] for k in ("checkout_head","declared_public_baseline_commit","checkout_identity_note","binary","source_unchanged_after_format")}
    result = {"schema":"hepta.audit.pr4823.engineering-record-consistency.v1", "observed_at":datetime.now(timezone.utc).isoformat(),
              "passed":True, "package_files":452, "package_bytes":sum(x["bytes"] for x in INPUTS.values()),
              "payload_manifest_entries":451, "payload_manifest_hashes_verified":True,
              "native_saved_record_comparison":counts,
              "native_scope":"Exact saved request/reference/response/mask/action/value and stored utility equality; no Bellman recurrence, feature, trajectory, Rust or MCP execution by this audit; typed serde commitment only cross-linked, not reserialized by Rust.",
              "qwen":q_summary,
              "pocket4":{"finished_utc":snap["finished_utc"],"tensor_count":6,"parameter_count":2379,
                          "snapshot_sha256":INPUTS["pocket4/session_end_snapshot/public_snapshot.json"]["sha256"],
                          "private_raw_stdout_published":False,"current_live_state_rechecked":False,
                          "scope":"Frozen sanitized read-only observation, no new model/forward/training or task efficacy acceptance."},
              "new_experiment_or_native_execution":False,"input_identities":INPUTS,
              "audit_cpu_seconds":time.process_time()-cpu_start,"audit_wall_seconds":time.monotonic()-wall_start}
    (ROOT/"independent-engineering-records.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    (ROOT/"independent-cost-ledger.json").write_text(json.dumps(costs,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"passed":True,"native_counts":counts,"qwen":q_summary,"cost_records":len(ledger),"complete_cost_accounting":False}))


if __name__ == "__main__":
    main()
