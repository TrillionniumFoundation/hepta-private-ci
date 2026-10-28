"""Read-only, independent audit of a frozen memory adapter study.

This evaluator imports no study implementation and performs no model inference,
training, threshold selection, or held rerun. It scores preserved reader output
using source records and a separately implemented arithmetic interpreter.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np


ARMS = (
    "learned/parameter", "deterministic/parameter", "oracle/parameter",
    "learned/retrieval", "deterministic/retrieval", "oracle/retrieval",
    "zero/oracle", "headonly/oracle", "joint/oracle",
)
METRICS = ("correct", "count", "address_correct", "accepted", "unsupported_accept")
OPCODES = ("keep", "reserve_gap", "pack", "cap", "add_reserve", "halve", "stop")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return {"bytes": path.stat().st_size, "sha256": hasher.hexdigest()}


def load(path):
    return json.loads(path.read_bytes())


def new_counts():
    return dict.fromkeys(METRICS, 0)


def arithmetic_reference(entity, workflow, event_shift, policies, programs):
    if entity == 7:
        return {"status": "exception_stop", "value": None, "trace": []}
    value = (3 * entity + 5 + event_shift) % 17
    reserve, pack, limit = policies[entity]
    trace = []
    for opcode in programs[workflow]:
        before = value
        if opcode == 0:
            pass
        elif opcode == 1:
            value = max(0, reserve - value)
        elif opcode == 2:
            value *= pack
        elif opcode == 3:
            value = min(value, limit)
        elif opcode == 4:
            value += reserve
        elif opcode == 5:
            value //= 2
        elif opcode != 6:
            raise ValueError("Invalid source opcode")
        trace.append({"op": OPCODES[opcode], "before": before, "after": value})
        if opcode == 6:
            return {"status": "completed", "value": value, "trace": trace}
    raise ValueError("Source program has no stop")


def target_for(row, event_shift, policies, programs):
    role = row["role"]
    if role == "unknown":
        return {"status": "abstain", "value": None}
    if role == "semantic":
        return {"status": "read", "value": policies[row["entity"]]}
    if role == "skill":
        return {"status": "read", "value": programs[row["workflow"]]}
    if role == "compose":
        return arithmetic_reference(row["entity"], row["workflow"], event_shift, policies, programs)
    raise ValueError("Unexpected role")


def result_without_timing(value):
    if isinstance(value, dict):
        return {k: result_without_timing(v) for k, v in value.items()
                if k not in ("wall_ns", "cpu_ns")}
    if isinstance(value, list):
        return [result_without_timing(v) for v in value]
    return value


def summarize_values(values):
    return {"count": len(values), "min": min(values), "median": statistics.median(values),
            "max": max(values), "sum": sum(values)}


def audit(run_root, source_root, encoder_root):
    checks = {}
    identities = {}

    def check(name, condition):
        if name in checks:
            raise ValueError("Duplicate audit check: " + name)
        checks[name] = bool(condition)

    def recorded(path):
        identities[str(path.relative_to(run_root))] = file_identity(path)
        return load(path)

    result = recorded(run_root / "RESULT.json")
    freeze = recorded(run_root / "FREEZE.json")
    training = recorded(run_root / "models/TRAINING.json")
    sources = recorded(run_root / "sources.json")
    evaluator_rows = recorded(run_root / "held-evaluator-rows.json")
    # Never parse or reopen the original held_prompts.json during this audit.
    rows = [{k: r[k] for k in ("id", "role", "entity", "workflow", "wording_group")}
            for r in evaluator_rows]
    text_count = len({r["text"] for r in evaluator_rows})
    text_hashes = {r["id"]: sha(r["text"].encode()) for r in evaluator_rows}
    text_groups = defaultdict(list)
    unique_texts_by_role = {}
    for row in evaluator_rows:
        text_groups[sha(row["text"].encode())].append((row["role"], row["entity"], row["workflow"]))
    for role in ("semantic", "skill", "compose", "unknown"):
        unique_texts_by_role[role] = len({r["text"] for r in evaluator_rows if r["role"] == role})
    del evaluator_rows
    by_id = {r["id"]: r for r in rows}
    policies = {s["index"]: s["value"] for s in sources if s["kind"] == "semantic"}
    programs = {s["index"]: s["value"] for s in sources if s["kind"] == "skill"}
    check("source_inventory_8_policies_and_8_programs", len(policies) == len(programs) == 8)
    check("held_row_inventory_unique", len(by_id) == len(rows) == result["held_rows_per_context"])
    check("duplicate_texts_have_consistent_labels", all(len(set(labels)) == 1 for labels in text_groups.values()))
    check("held_hash_consistent_without_reopening_original",
          freeze["source_files"]["held_prompts.json"]["sha256"] == result["held_sha256"])
    for name, expected in freeze["source_files"].items():
        if name != "held_prompts.json":
            check("frozen_source:" + name, file_identity(source_root / name) == expected)
    check("trainer_exit_before_held_parse",
          freeze["created_ns"] < result["trainer_exited_ns"] < result["held_first_parsed_ns"])
    check("trainer_receipt_denies_held_access", training["held_file_opened"] is False)
    development = recorded(run_root / "development.json")
    calibration_roles = Counter(row["role"] for row in development["calibration"])
    train_pairs = {(row["entity"], row["workflow"]) for row in development["train"] if row["role"] == "compose"}
    held_pairs = {(row["entity"], row["workflow"]) for row in rows if row["role"] == "compose"}
    check("train_and_held_composition_pairs_disjoint", not train_pairs & held_pairs)
    check("calibration_unknown_inventory", calibration_roles["unknown"] == 16)
    with np.load(run_root / "held-encoded.npz", allow_pickle=False) as data:
        held_features = data["features"].copy()
    with np.load(run_root / "canonical.npz", allow_pickle=False) as data:
        canonical_features = {k: data[k].copy() for k in data.files}
    check("declared_feature_shapes", held_features.shape == (len(rows), 384)
          and all(v.shape == (8, 384) for v in canonical_features.values()))

    processes = []
    for path in sorted(run_root.glob("*.process.json")):
        process = recorded(path)
        stem = path.name.removesuffix(".process.json")
        for suffix in ("stdout", "stderr"):
            check(f"process_output:{stem}:{suffix}",
                  file_identity(run_root / (stem + "." + suffix)) == process[suffix])
        check("process_success:" + stem, process["exit_code"] == 0 and not process["timed_out"])
        check("process_clock:" + stem,
              process["wall_ns"] == process["exited_ns"] - process["started_ns"])
        if stem.startswith(("read-", "structure-", "lifecycle-")):
            check("process_after_training:" + stem, process["started_ns"] > result["trainer_exited_ns"])
        processes.append(process)
    check("process_receipts_match_result",
          sorted(processes, key=lambda p: p["started_ns"]) == result["cost"]["executions"])
    training_process = load(run_root / "training.process.json")
    check("trainer_pid_binding", training_process["pid"] == training["pid"] == result["trainer_pid"])

    checkpoints = {}
    arrays_by_checkpoint = {}
    for path in sorted((run_root / "models").rglob("manifest.json")):
        manifest = recorded(path)
        key = str(path.parent.relative_to(run_root / "models"))
        arrays = {}
        checksums = hashlib.sha256()
        check("checkpoint_tensor_inventory:" + key,
              set(manifest["tensors"]) == {"A", "B", "head.weight", "head.bias"})
        for name, spec in sorted(manifest["tensors"].items()):
            pieces = []
            for part in spec["parts"]:
                part_path = path.parent / part["file"]
                check("tensor_blob:" + key + "/" + part["file"],
                      file_identity(part_path) == {"bytes": part["bytes"], "sha256": part["sha256"]}
                      and part["bytes"] <= 512000)
                with np.load(part_path, allow_pickle=False) as data:
                    check("tensor_key:" + key + "/" + part["file"], data.files == ["values"])
                    pieces.append(data["values"].copy())
            array = np.concatenate(pieces).reshape(spec["shape"])
            check("tensor_dtype_finite:" + key + "/" + name,
                  array.dtype == np.dtype("float32") and np.isfinite(array).all())
            arrays[name] = array
            checksums.update(wire([name, list(array.shape), "float32"]))
            checksums.update(array.astype("<f4", copy=False).tobytes())
        check("parameter_digest:" + key, checksums.hexdigest() == manifest["parameter_sha256"])
        check("encoder_binding:" + key, manifest["base_encoder_sha"] == training["encoder_sha"])
        rank, dimension = manifest["config"]["rank"], manifest["config"]["input_dim"]
        check("adapter_shape:" + key,
              arrays["A"].shape == (rank, dimension) and arrays["B"].shape == (dimension, rank))
        head = arrays["head.weight"].size + arrays["head.bias"].size
        adapter = arrays["A"].size + arrays["B"].size
        checkpoints[key] = {
            "parameters": head + adapter, "adapter_parameters": adapter, "head_parameters": head,
            "float32_parameter_bytes": 4 * (head + adapter),
            "stored_bytes": sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file()),
            "parameter_sha256": manifest["parameter_sha256"],
            "manifest_sha256": sha(path.read_bytes()), "source_ids": manifest["source_ids"],
            "head_trainable": manifest["head_trainable"], "config": manifest["config"],
        }
        arrays_by_checkpoint[key] = arrays

    aggregate = defaultdict(lambda: defaultdict(new_counts))
    compose_subsets = defaultdict(lambda: defaultdict(lambda: {
        "correct": 0, "count": 0, "full_intermediate_trace_correct": 0, "status_counts": Counter()}))
    per_seed = defaultdict(lambda: defaultdict(lambda: defaultdict(new_counts)))
    pair_counts = {route: {"pairs": 0, "route_equal": 0, "result_equal": 0,
                          "source_event_status_reads_equal": 0} for route in ("learned", "deterministic", "oracle")}
    head_ablation = defaultdict(Counter)
    model_calls = defaultdict(Counter)
    read_counts = defaultdict(Counter)
    timing_slices = defaultdict(list)
    raw_records = skipped_records = 0
    raw_contexts = []
    zero_success_statuses = Counter()
    zero_success_entities = Counter()
    for seed in result["seeds"]:
        for event_shift in result["event_contexts"]:
            stem = f"read-seed-{seed}-event-{event_shift}"
            report = recorded(run_root / (stem + ".stdout"))
            saved_score = recorded(run_root / (stem + ".score.json"))
            process = load(run_root / (stem + ".process.json"))
            request_path = run_root / (stem + ".request.json")
            request = recorded(request_path)
            check("reader_response_hash:" + stem, sha((run_root / (stem + ".stdout")).read_bytes())
                  == saved_score["response_sha256"] == process["stdout"]["sha256"])
            check("reader_request_hash:" + stem, sha(request_path.read_bytes()) == report["request_wire_sha256"]
                  == report["request_sha256"] == saved_score["request_sha256"])
            check("request_query_contract:" + stem,
                  all(set(q) == {"id", "text", "feature", "oracle_route"} for q in request["queries"]))
            check("request_routes_contain_only_address_labels:" + stem,
                  all(set(q["oracle_route"]) == {"role", "entity", "workflow"} for q in request["queries"]))
            check("request_matches_saved_queries_and_embeddings:" + stem,
                  len(request["queries"]) == len(rows) and all(
                      q["id"] == rows[i]["id"] and sha(q["text"].encode()) == text_hashes[q["id"]]
                      and q["oracle_route"] == {k: rows[i][k] for k in ("role", "entity", "workflow")}
                      and np.array_equal(np.asarray(q["feature"], dtype=np.float32), held_features[i])
                      for i, q in enumerate(request["queries"])))
            check("reader_canonical_feature_binding:" + stem,
                  report["canonical_features"]["sha256"] == file_identity(run_root / "canonical.npz")["sha256"]
                  and report["canonical_features"]["f32_sha256"] == {
                      k: sha(v.astype("<f4", copy=False).tobytes()) for k, v in canonical_features.items()})
            check("reader_arm_inventory:" + stem, tuple(report["arms"]) == ARMS)
            check("reader_no_training_modules:" + stem,
                  not report["training_modules_loaded"] and not report["training_module_import_audit"])
            check("reader_no_gradient_or_native_claim:" + stem,
                  report["boundaries"]["gradient_steps"] == 0 and report["native_runtime_executed"] is False)
            context_score = defaultdict(lambda: {"roles": {}, "wording_groups": {}})
            index = {}
            correctness = {}
            for record in report["rows"]:
                raw_records += 1
                key = (record["arm"], record["query_id"])
                if key in index or key[0] not in ARMS or key[1] not in by_id:
                    raise ValueError("Reader inventory corruption: " + stem)
                index[key] = record
                row = by_id[key[1]]
                arm, role = key[0], row["role"]
                inapplicable = arm == "joint/oracle" and role != "compose"
                if bool(record.get("skipped")) != inapplicable:
                    raise ValueError("Unplanned reader skip: " + stem)
                if inapplicable:
                    skipped_records += 1
                    continue
                target = target_for(row, event_shift, policies, programs)
                actual = record["result"]
                address_correct = all(record["route"][k] == row[k] for k in ("role", "entity", "workflow"))
                correct = (actual["status"] == target["status"] and actual.get("value") == target["value"]
                           and (role == "unknown" or address_correct))
                if role == "compose":
                    correct = correct and ([x["op"] for x in actual.get("trace", [])]
                                           == [x["op"] for x in target["trace"]])
                    group = "exception" if row["entity"] == 7 else "nonexception"
                    detail = compose_subsets[arm][group]
                    detail["correct"] += int(correct)
                    detail["count"] += 1
                    detail["status_counts"][actual["status"]] += 1
                    detail["full_intermediate_trace_correct"] += int(correct and actual.get("trace", []) == target["trace"])
                    if arm == "zero/oracle" and correct:
                        zero_success_statuses[actual["status"]] += 1
                        zero_success_entities[str(row["entity"])] += 1
                correctness[key] = bool(correct)
                increments = {"correct": int(correct), "count": 1, "address_correct": int(address_correct),
                              "accepted": int(actual["status"] not in ("abstain", "not_applicable")),
                              "unsupported_accept": int(role == "unknown" and actual["status"] != "abstain")}
                for container, label in ((context_score[arm]["roles"], role),
                                         (context_score[arm]["wording_groups"], row["wording_group"])):
                    counts = container.setdefault(label, new_counts())
                    for metric, increment in increments.items():
                        counts[metric] += increment
                for metric, increment in increments.items():
                    aggregate[arm][role][metric] += increment
                    per_seed[str(seed)][arm][role][metric] += increment
            check("reader_cartesian_product:" + stem,
                  set(index) == {(arm, identity) for arm in ARMS for identity in by_id})
            check("independent_scores_match_saved:" + stem, dict(context_score) == saved_score["scores"])
            for route in pair_counts:
                for identity in by_id:
                    parameter = index[(route + "/parameter", identity)]
                    retrieval = index[(route + "/retrieval", identity)]
                    pair = pair_counts[route]
                    pair["pairs"] += 1
                    pair["route_equal"] += int(parameter["route"] == retrieval["route"])
                    pair["result_equal"] += int(result_without_timing(parameter["result"])
                                                == result_without_timing(retrieval["result"]))
                    pair["source_event_status_reads_equal"] += int(all(
                        parameter["reads"][name] == retrieval["reads"][name]
                        for name in ("events", "exceptions", "source_status")))
            for identity, row in by_id.items():
                full = correctness[("oracle/parameter", identity)]
                ablated = correctness[("headonly/oracle", identity)]
                name = ("both_correct" if full and ablated else "adapter_only_correct" if full else
                        "head_only_correct" if ablated else "both_wrong")
                head_ablation[row["role"]][name] += 1
            receipts = report["arm_receipts"]
            check("same_owner_snapshot:" + stem, len({r["owner_snapshot_sha256"] for r in receipts}) == 1)
            for receipt in receipts:
                arm = receipt["arm"]
                timing_slices[arm].append(receipt["wall_ns_through_stop"])
                read_counts[arm].update(receipt["reads"])
                for model, counts in receipt["model_reads"].items():
                    model_calls[arm][model] += counts["calls"]
                if receipt["value_access"] == "parameter-only":
                    check("no_source_payload_access:" + stem + ":" + arm,
                          receipt["reads"]["explicit_values"] == 0
                          and receipt["sql_audit"]["source_payload_column_authorizations"] == 0)
            for name, metadata in report["modelsha"].items():
                checkpoint = checkpoints[f"seed-{seed}/{name}"]
                check("reader_checkpoint_binding:" + stem + ":" + name,
                      all(metadata[k] == checkpoint[k] for k in ("parameter_sha256", "manifest_sha256", "stored_bytes"))
                      and metadata["parameter_counts"]["total"] == checkpoint["parameters"])
            check("reader_checkpoint_bytes:" + stem,
                  report["cost"]["checkpoint_stored_bytes"] == sum(v["stored_bytes"] for v in report["modelsha"].values()))
            raw_contexts.append({"seed": seed, "event_shift": event_shift, "rows": len(report["rows"]),
                                 "body_wall_ns": report["cost"]["wall_ns_before_response"],
                                 "process_wall_ns": process["wall_ns"], "peak_rss_kib": report["cost"]["peak_rss"]})
    check("independent_aggregate_matches_result", aggregate == result["aggregate_scores"])
    for route, counts in pair_counts.items():
        check("same_router_same_outcomes:" + route, len(set(counts.values())) == 1)
    check("zero_successes_are_exact_exception_stops",
          set(zero_success_statuses) == {"exception_stop"} and set(zero_success_entities) == {"7"}
          and compose_subsets["zero/oracle"]["nonexception"]["correct"] == 0)

    router_diagnosis, budgets, structure, maintenance = [], [], [], []
    presentations = fits_count = 0
    for summary in training["seeds"]:
        seed = summary["seed"]
        root = run_root / "models" / f"seed-{seed}"
        selection = recorded(root / "route-selection.json")
        allowed = [t for t in selection["trials"] if t["unknown_false_accept"] == 0]
        prescribed = max(allowed, key=lambda t: (t["known_correct"], t["threshold"]))["threshold"] if allowed else 1.1
        check("router_prescribed_calibration_choice:" + str(seed),
              prescribed == selection["threshold"] and not selection["selection_used_held"])
        check("router_training_receipt_binding:" + str(seed), selection == summary["router_selection"])
        router_diagnosis.append({"seed": seed, **selection,
                                 "explanation": "Every candidate has calibration false accepts; fixed fallback rejects all."})
        fits = summary["fits"]
        for number, fit in enumerate(fits):
            fits_count += 1
            presentations += fit["sample_presentations"]
            check(f"real_parameter_update:{seed}:{number}",
                  fit["initial_parameter_sha256"] != fit["final_parameter_sha256"]
                  and fit["max_gradient_norm"]["A"] > 0 and fit["max_gradient_norm"]["B"] > 0)
            check(f"fit_exposure:{seed}:{number}",
                  fit["steps"] * fit["batch_size"] == fit["sample_presentations"])
        first_fits = {}
        for fit in fits:
            first_fits.setdefault(fit["cell_id"], fit)
        def cp(name):
            return checkpoints[f"seed-{seed}/{name}"]
        def arr(name):
            return arrays_by_checkpoint[f"seed-{seed}/{name}"]
        pair_parameters = cp("semantic")["parameters"] + cp("skill")["parameters"]
        joint = cp("joint")
        check("joint_equal_total_parameters:" + str(seed), pair_parameters == joint["parameters"] == 21544)
        weights = {o["name"]: o["weight"] for o in joint["config"]["outputs"]}
        check("joint_equal_task_loss_weight:" + str(seed), weights["bits"] == sum(weights[k] for k in weights if k != "bits"))
        exposures = {name: first_fits[name]["sample_presentations"] for name in ("semantic", "skill", "joint")}
        check("joint_equal_per_task_supervision:" + str(seed), len(set(exposures.values())) == 1)
        for name in ("semantic", "skill"):
            check("zero_is_initial_checkpoint:" + str(seed) + ":" + name,
                  cp(name + "-zero")["parameter_sha256"] == first_fits[name]["initial_parameter_sha256"])
            check("head_ablation_preserves_head:" + str(seed) + ":" + name,
                  all(np.array_equal(arr(name)[key], arr(name + "-head-only")[key])
                      for key in ("head.weight", "head.bias")) and not np.any(arr(name + "-head-only")["B"]))
        structure_receipt = recorded(root / "structure.json")
        routing = recorded(root / "structure-routing.json")
        cal, canon = structure_receipt["calibration"], structure_receipt["canonical"]
        split_gate = (cal["dynamic"]["correct"] > max(cal[k]["correct"] for k in ("static", "rank8"))
                      and canon["dynamic"]["correct"] >= max(canon[k]["correct"] for k in ("static", "rank8")))
        merge_gate = (structure_receipt["merge_calibration"]["correct"] >= cal["dynamic"]["correct"]
                      and structure_receipt["merge_canonical"]["correct"] >= canon["dynamic"]["correct"])
        check("structure_gate_decisions:" + str(seed),
              split_gate == structure_receipt["split_admitted"] == routing["split_admitted"]
              and merge_gate == structure_receipt["merge_admitted"] == routing["merge_admitted"])
        check("structure_no_held_selection:" + str(seed),
              structure_receipt["held_results_used"] is False and structure_receipt["selection"]["held_access"] is False)
        shared_head = cp("semantic")["head_parameters"]
        counts = {"dynamic": shared_head + sum(cp("dynamic-" + str(i))["adapter_parameters"] for i in range(2)),
                  "static": shared_head + sum(cp("static-" + str(i))["adapter_parameters"] for i in range(2)),
                  "rank8": cp("rank-8")["parameters"]}
        check("structure_equal_total_parameters:" + str(seed), len(set(counts.values())) == 1)
        structure_exposures = {
            "dynamic": sum(first_fits["dynamic-" + str(i)]["sample_presentations"] for i in range(2)),
            "static": sum(first_fits["static-" + str(i)]["sample_presentations"] for i in range(2)),
            "rank8": first_fits["rank-8"]["sample_presentations"],
        }
        check("structure_equal_presentations:" + str(seed), len(set(structure_exposures.values())) == 1)
        expected_per_row = first_fits["rank-8"]["sample_presentations"] / first_fits["rank-8"]["available_rows"]
        check("structure_equal_expected_exposure_per_row:" + str(seed),
              all(first_fits[name]["sample_presentations"] / first_fits[name]["available_rows"] == expected_per_row
                  for name in ("dynamic-0", "dynamic-1", "static-0", "static-1")))
        for name in ("dynamic-0", "dynamic-1", "static-0", "static-1", "rank-8", "merged"):
            check("structure_shared_frozen_head:" + str(seed) + ":" + name,
                  not cp(name)["head_trainable"] and all(np.array_equal(arr("semantic")[key], arr(name)[key])
                                                        for key in ("head.weight", "head.bias")))
        fresh = recorded(run_root / f"structure-{seed}.stdout")
        shifted = {i: [(p[0] + 3) % 16, p[1], p[2]] if i < 4 else p for i, p in policies.items()}
        fresh_scores = {}
        for name, candidate in fresh["candidates"].items():
            correct = sum(row["value"] == shifted[row["entity"]] for row in candidate["rows"])
            fresh_scores[name] = {"correct": correct, "count": len(candidate["rows"])}
            check("fresh_structure_actual_calls:" + str(seed) + ":" + name,
                  candidate["model_calls"] == len(candidate["rows"]) == 8)
            check("fresh_structure_bits_decode:" + str(seed) + ":" + name,
                  all([sum(row["bits"][4 * n + b] * (1 << b) for b in range(4)) for n in range(3)] == row["value"]
                      for row in candidate["rows"]))
        for name, value in fresh["parameter_sha256"].items():
            check("fresh_structure_parameter_binding:" + str(seed) + ":" + name, value == cp(name)["parameter_sha256"])
        check("fresh_structure_no_training_import:" + str(seed), fresh["training_modules_loaded"] == [])
        check("fresh_structure_quality_matches_receipt:" + str(seed),
              all(fresh_scores[name] == canon[name] for name in ("dynamic", "static", "rank8"))
              and fresh_scores["merged"] == structure_receipt["merge_canonical"])
        structure.append({"seed": seed, "calibration": cal, "canonical": canon,
                          "merge_calibration": structure_receipt["merge_calibration"],
                          "fresh_canonical": fresh_scores, "split_admitted": split_gate, "merge_admitted": merge_gate,
                          "total_parameters": counts, "sample_presentations": structure_exposures,
                          "expected_presentations_per_row": expected_per_row})
        upkeep = recorded(root / "maintenance.json")
        check("deletion_clean_counterfactual_parameter_identity:" + str(seed),
              cp("semantic-rebuilt")["parameter_sha256"] == cp("semantic-independent-clean")["parameter_sha256"])
        check("deletion_source_absent:" + str(seed),
              upkeep["deletion"]["deleted_source"] not in cp("semantic-rebuilt")["source_ids"])
        lifecycle = recorded(run_root / f"lifecycle-{seed}.stdout")
        events = {e["operation"]: e for e in lifecycle["events"]}
        check("lifecycle_original_value:" + str(seed), events["read_original"]["result"]["value"] == policies[0])
        check("lifecycle_corrected_value:" + str(seed),
              events["read_corrected"]["result"]["value"] == upkeep["correction"]["new_policy"])
        retained = [policies[i] for i in range(1, 8)]
        rebuilt = [upkeep["correction"]["new_policy"]] + [policies[i] for i in range(2, 8)]
        check("lifecycle_retained_values:" + str(seed), [r["value"] for r in events["read_retained"]["result"]] == retained
              and [r["value"] for r in events["read_rebuilt_retained"]["result"]] == rebuilt)
        for name, status in (("reject_stale_parameters", "stale_source"), ("revoked_composition", "missing_or_stale_input"),
                             ("read_sleeping", "cell_sleeping"), ("stopped_execute", "owner_stopped"),
                             ("stopped_direct_read", "owner_stopped")):
            event = events[name]
            check("lifecycle_no_content_reads:" + str(seed) + ":" + name,
                  event["result"]["status"] == status and all(event["reads_after"][key] == event["reads_before"][key]
                                                            for key in ("model", "events", "explicit_values")))
        check("lifecycle_wake_identity:" + str(seed), events["before_sleep"]["result"] == events["after_wake"]["result"]
              and events["reject_wrong_wake"]["rejected"] is True)
        check("lifecycle_bounded_execution:" + str(seed),
              events["bounded_execution"]["result"]["status"] == "budget_stop"
              and len(events["bounded_execution"]["result"]["trace"]) == 1)
        maintenance.append({"seed": seed, "receipt": upkeep, "lifecycle_explicit_fact_reads": lifecycle["explicit_fact_value_reads"],
                            "scope": "Exact clean rebuild on retained data, not a general machine-unlearning guarantee."})
        budgets.append({"seed": seed, "separate_parameters": pair_parameters, "joint_parameters": joint["parameters"],
                        "task_supervision_presentations": exposures,
                        "separate_total_feature_presentations": exposures["semantic"] + exposures["skill"],
                        "joint_total_feature_presentations": exposures["joint"], "joint_output_loss_weights": weights,
                        "semantic_plus_skill_checkpoint_bytes": cp("semantic")["stored_bytes"] + cp("skill")["stored_bytes"],
                        "semantic_plus_skill_plus_router_checkpoint_bytes": cp("semantic")["stored_bytes"] + cp("skill")["stored_bytes"] + cp("router")["stored_bytes"],
                        "joint_checkpoint_bytes": joint["stored_bytes"]})
    check("total_candidate_fit_count", fits_count == result["all_candidate_fits"] == 39)
    check("total_training_presentations", presentations == result["sample_presentations"] == 1171200)

    encoder = recorded(run_root / "development-encoder.json")
    held_encoder = recorded(run_root / "held-encoder.json")
    check("encoder_receipts_same_identity", encoder["identity"] == held_encoder["identity"])
    for name, expected in encoder["identity"]["files"].items():
        check("encoder_asset:" + name, file_identity(encoder_root / name) == expected)
    encoder_bytes = sum(v["bytes"] for v in encoder["identity"]["files"].values())
    check("encoder_base_bytes", encoder_bytes == encoder["base_bytes"] == result["cost"]["encoder_base_bytes"])
    model_stock = sum(p.stat().st_size for p in (run_root / "models").rglob("*") if p.is_file())
    check("training_model_inventory_bytes",
          model_stock - (run_root / "models/TRAINING.json").stat().st_size == training["model_files_bytes"])
    # Root attached already-completed unit-run logs after RESULT was written.
    # Keep this explicitly named attachment inventory separate from the study's
    # original stock measurement, rather than silently absorbing the difference.
    attachments = {str(p.relative_to(run_root)): file_identity(p)
                   for p in sorted((run_root / "unit-verification").rglob("*")) if p.is_file()}
    current_stock = sum(p.stat().st_size for p in run_root.rglob("*") if p.is_file() and p.name != "RESULT.json")
    original_stock = current_stock - sum(v["bytes"] for v in attachments.values())
    check("evidence_stock_before_summary", original_stock == result["cost"]["stock_bytes_before_summary"])
    caches = {p.name: p.stat().st_size for p in sorted(run_root.glob("*.npz"))}
    databases = {p.name: p.stat().st_size for p in sorted(run_root.glob("*.sqlite"))}
    source_payload = [{"kind": s["kind"], "index": s["index"], "value": s["value"]} for s in sources]
    distinct_groups = len({r["wording_group"] for r in rows})
    limits = [
        "Authored finite inventory: 8 entities, 8 workflows, four-bit numeric fields; no naturalistic or universal-memory evidence.",
        "The 320 held queries and 32 wording groups recur across 3 optimizer seeds and 3 deterministic event shifts; rows are correlated, not independent trials.",
        "Wording groups are distinct templates, not statistically established independent samples; no IID confidence interval is justified.",
        "Same-router retrieval is exact typed SQLite lookup, not a general free-form RAG system. Parameter and retrieval results are identical here.",
        "Oracle routing supplies the address; canonical cached address vectors are content inputs. This isolates finite memory readout from language understanding.",
        "Learned routing rejects all because calibration fails the predefined zero-false-accept rule, not because addressed parameter memory cannot return its facts.",
        "Head-only is post-training removal of B with the trained head retained, not a separately optimized head-only baseline; zero is the untrained initial checkpoint.",
        "The parent readout has no intervening nonlinearity: W_head(I+BA)x+b is affine in the frozen embedding. A separately trained dense linear head has sufficient expressivity to represent that solution; the ablation does not prove adapter superiority. Frozen shared heads constrain later child updates.",
        "The joint model matches parameters and per-task supervision presentations; the separate pair sees twice as many feature presentations and has an easier factored input contract.",
        "The composition score checks route, status, final value and opcode sequence; equal outputs may mask wrong policies. The extra full-intermediate-trace diagnostic is not a replacement endpoint.",
        "Split/merge quality gates use direct paraphrase calibration; fresh runtime uses canonical address features. Neither rejected candidate was promoted into the active memory graph.",
        "Topology and interpreter are fixed by the experiment; autonomous graph formation and generic neuron derivation are not demonstrated.",
        "Deletion is retained-data clean rebuilding; lifecycle sleep evicts the owner reference and does not guarantee physical RSS reclamation.",
        "The reader is a Python adapter owner; the new tensor model profile is not integrated into the native Hepta owner.",
        "Sequential arms share process/model loads and receive precomputed embeddings; arm timing slices are not independent deployment or end-to-end latencies.",
        "Full encoder extraction, training, data/feature/source storage and candidate search costs must be counted; neither storage compression nor full-cost superiority is established.",
        "The 127 MB encoder is a lifecycle asset, not a measured per-cell resident allocation. A canonical-only reader can reuse stored address embeddings; learned or joint routing/readout requires query embeddings, precomputed in this study.",
        "Hash and instrumentation checks verify preserved evidence and the declared execution path, not a hostile-process confidentiality boundary or an independent physical replication.",
    ]
    return {
        "schema": "hepta.memory.independent-postrun-audit.v1", "run_root": str(run_root),
        "read_only_original_evidence": True, "inference_or_training_executed": False,
        "thresholds_changed": False, "original_held_prompts_reopened": False,
        "passed": all(checks.values()), "checks_count": len(checks),
        "failed_checks": [name for name, passed in checks.items() if not passed], "checks": checks,
        "independent_aggregate_scores": aggregate, "per_seed_scores": per_seed,
        "composition_subsets": compose_subsets, "head_ablation_paired_outcomes": head_ablation,
        "same_router_parameter_retrieval_pairs": pair_counts,
        "zero_successes": {"status_counts": zero_success_statuses, "entity_counts": zero_success_entities},
        "router_calibration_diagnosis": router_diagnosis, "joint_budget_comparison": budgets,
        "structure": structure, "maintenance": maintenance,
        "sample_dependence": {"unique_query_ids": len(rows), "unique_query_texts": text_count,
                              "unique_query_texts_by_role": unique_texts_by_role,
                              "duplicated_text_group_multiplicities": Counter(len(v) for v in text_groups.values() if len(v) > 1),
                              "distinct_wording_groups": distinct_groups,
                              "role_counts_per_context": Counter(r["role"] for r in rows),
                              "calibration_role_counts": calibration_roles,
                              "distinct_training_composition_pairs": len(train_pairs),
                              "distinct_held_composition_pairs": len(held_pairs),
                              "seeds": result["seeds"], "event_shifts": result["event_contexts"],
                              "raw_arm_records": raw_records, "predeclared_joint_skips": skipped_records,
                              "scored_arm_records": raw_records - skipped_records, "iid_trials": False},
        "cost": {"encoder_asset_bytes": encoder_bytes, "encoder_decimal_MB": encoder_bytes / 1000000,
                 "encoder_MiB": encoder_bytes / (1024 * 1024), "model_archive_bytes": model_stock,
                 "all_checkpoint_directories_bytes": sum(c["stored_bytes"] for c in checkpoints.values()),
                 "checkpoint_count": len(checkpoints), "checkpoints": checkpoints,
                 "source_json_bytes": (run_root / "sources.json").stat().st_size,
                 "compact_typed_source_values_json_bytes": len(wire(source_payload)),
                 "sources_value_arrays_only_json_bytes": len(wire([s["value"] for s in sources])),
                 "feature_cache_files": caches, "feature_cache_total_bytes": sum(caches.values()),
                 "sqlite_files": databases, "sqlite_total_bytes": sum(databases.values()),
                 "preserved_evidence_bytes_excluding_result": original_stock,
                 "post_result_attachments": attachments,
                 "post_result_attachment_bytes": sum(v["bytes"] for v in attachments.values()),
                 "current_evidence_bytes_excluding_result": current_stock,
                 "candidate_fits": fits_count, "sample_presentations": presentations,
                 "process_wall_ns_sum": sum(p["wall_ns"] for p in processes),
                 "process_cpu_seconds_sum": sum(p["cpu_seconds"] for p in processes),
                 "total_study_wall_ns": result["cost"]["lifecycle_wall_ns_before_summary"],
                 "training_body_cpu_seconds": training["cpu_seconds"],
                 "training_body_wall_seconds": training["wall_seconds"],
                 "development_encoder_inference_seconds": encoder["inference_wall_seconds"],
                 "held_encoder_inference_seconds": held_encoder["inference_wall_seconds"],
                 "reader_contexts": raw_contexts,
                 "sequential_arm_slice_wall_ns_not_deployment_latency": {k: summarize_values(v) for k, v in timing_slices.items()},
                 "model_actual_forward_calls": model_calls, "owner_logical_read_counts": read_counts,
                 "full_cost_superiority_established": False},
        "limitations": limits, "input_file_identities": identities,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--encoder-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.run_root.resolve()):
        raise ValueError("Write the audit outside the preserved formal evidence directory")
    report = audit(args.run_root, args.source_root, args.encoder_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"passed": report["passed"], "checks_count": report["checks_count"],
                      "failed_checks": report["failed_checks"], "output": str(args.output)}, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
