"""Independent evidence audit. No trainer, encoder or model inference is imported."""

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3

import numpy as np

ROOT = Path("/workspace/scratch/76e2020e4b36/memory-v10-formal-01")
SOURCE = Path("/workspace/scratch/76e2020e4b36/hepta-memory-v10/qualification/memory-cell-v10")
OUT = Path(__file__).resolve().parent
ISSUES = []
CHECKS = 0


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def check(value, message, context=""):
    global CHECKS
    CHECKS += 1
    if not value:
        ISSUES.append({"message": message, "context": str(context)})


def equal_fields(actual, expected, context):
    for key, value in expected.items():
        check(actual.get(key) == value, key + " differs", context)


def source_id(index, version):
    return sha(canonical(["memory-v10-authored", "semantic", index, version]))


def targets(values, kind):
    if kind == "semantic":
        return np.asarray([[(value >> bit) & 1 for value in row for bit in range(4)]
                           for row in values], dtype=np.float32)
    output = np.zeros((len(values), 28), dtype=np.float32)
    for row, values in enumerate(values):
        for position, value in enumerate(values):
            output[row, 7 * position + value] = 1
    return output


def route(row):
    role = {"skill": "procedure", "compose": "apply", "unknown": "reject"}.get(row["role"], row["role"])
    return {"operation": role, "entity": row["entity"], "workflow": row["workflow"]}


def same_route(left, right):
    return all(left.get(key) == right.get(key) for key in ("operation", "entity", "workflow"))


def expected_execution(event, policy, program, held):
    # Independent replay of the bounded source program, never model inference.
    if held:
        return {"status": "held", "value": None, "trace": []}
    reserve, pack, limit = policy
    names = ["keep", "reserve_gap", "pack", "cap", "add_reserve", "halve", "stop"]
    trace, value = [], event
    for opcode in program:
        before = value
        if opcode == 1:
            value = max(0, reserve - value)
        elif opcode == 2:
            value *= pack
        elif opcode == 3:
            value = min(value, limit)
        elif opcode == 4:
            value += reserve
        elif opcode == 5:
            value //= 2
        trace.append({"op": names[opcode], "before": before, "after": value})
        if opcode == 6:
            return {"status": "completed", "value": value, "trace": trace}
    return {"status": "missing_stop", "value": None, "trace": trace}


def actual_schedule(path, receipt, context):
    values = np.load(path, allow_pickle=False)
    equal_fields(receipt, {
        "schedule_sha256": sha(values.astype("<i8").tobytes()),
        "steps": len(values), "batch_size": values.shape[1],
        "sample_presentations": values.size,
    }, context)
    return values


def main():
    protocol = read(ROOT / "PROTOCOL.json")
    frozen = read(ROOT / "SOURCE_MANIFEST.json")
    run = read(ROOT / "RUN_FREEZE.json")
    original_inventory = read(ROOT / "ARTIFACTS.json")
    files = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            files.append({"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": sha(raw)})
    inventory = {row["path"]: row for row in files}
    expected = {row["path"]: row["bytes"] for row in original_inventory}
    check(len(expected) == len(original_inventory) == 2214, "artifact inventory must have 2214 unique rows")
    check(len(files) == 2215, "actual file count must be 2215")
    check(set(expected) == set(inventory) - {"ARTIFACTS.json"}, "inventory coverage differs")
    for name, size in expected.items():
        check(inventory.get(name, {}).get("bytes") == size, "artifact size mismatch", name)
    check(sha((ROOT / "SOURCE_MANIFEST.json").read_bytes()) == run["source_manifest_sha256"], "run/source manifest hash")
    check(sha((ROOT / "PROTOCOL.json").read_bytes()) == run["protocol_sha256"], "run/protocol hash")
    check((ROOT / "SOURCE_MANIFEST.json").read_bytes() == (SOURCE / "SOURCE_MANIFEST.json").read_bytes(), "source manifest changed")
    for name, digest in frozen["files"].items():
        check(sha((SOURCE / name).read_bytes()) == digest, "frozen source hash changed", name)
    manifest_raw = (ROOT / "SOURCE_MANIFEST.json").read_bytes()
    git_blob = hashlib.sha1(b"blob " + str(len(manifest_raw)).encode() + b"\0" + manifest_raw).hexdigest()
    check(git_blob == "7649c85137709d4e1e2844f79d526e212f5e871f", "published source manifest blob mismatch")
    (OUT / "FILE_HASHES.json").write_bytes(canonical(files))

    checkpoints = {}
    for path in sorted((ROOT / "models").rglob("manifest.json")):
        manifest = read(path)
        check(manifest["schema"] == "hepta.memory.v10.numpy-checkpoint.v1", "checkpoint schema", path)
        hasher, scalars = hashlib.sha256(), 0
        for name, entry in sorted(manifest["arrays"].items()):
            raw = (path.parent / entry["file"]).read_bytes()
            count = math.prod(entry["shape"])
            check(entry["file"] == f"{name}.f32", "tensor filename", path)
            check(len(raw) == entry["bytes"] == count * 4, "tensor shape/size", path)
            check(sha(raw) == entry["sha256"], "tensor hash", path)
            check(bool(np.isfinite(np.frombuffer(raw, dtype="<f4")).all()), "nonfinite tensor", path)
            hasher.update(canonical([name, entry["shape"], "float32"]))
            hasher.update(raw)
            scalars += count
        check(hasher.hexdigest() == manifest["parameter_sha256"], "combined parameter hash", path)
        checkpoints[path.parent.relative_to(ROOT).as_posix()] = {
            "parameter_sha256": hasher.hexdigest(), "scalars": scalars,
            "head_scalars": sum(math.prod(e["shape"]) for n, e in manifest["arrays"].items() if n.startswith("head.")),
        }

    pooled_content, pooled_composition, pooled_routing, pooled_pipeline = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    fairness, structure_rows, maintenance_rows, data_storage = [], [], [], []
    for capacity in protocol["capacities"]:
        data = ROOT / "data" / f"capacity-{capacity}"
        population = read(data / "sources.json")
        rows = {kind: [r for r in population["records"] if r["kind"] == kind] for kind in ("semantic", "procedure")}
        held = read(data / "held-queries.json")
        calibration = read(data / "calibration-queries.json")
        with np.load(data / "canonical.npz", allow_pickle=False) as archive:
            features = {kind: archive[kind] for kind in rows}
        gold = {kind: targets([r["value"] for r in rows[kind]], kind) for kind in rows}
        connection = sqlite3.connect(f"file:{data / 'exact.sqlite'}?mode=ro&immutable=1", uri=True)
        sql = {(kind, index): (key, json.loads(value), source)
               for kind, index, key, value, source in connection.execute("SELECT kind,idx,key,value,source_id FROM memory")}
        for kind in rows:
            for row in rows[kind]:
                check(sql[(kind, row["index"])] == (row["key"], row["value"], row["source_id"]), "SQL/source mismatch", (capacity, kind, row["index"]))
        connection.close()
        events = {row["index"]: row for row in population["event_records"] if row["effective_at"] == 20}
        holds = {row["index"]: row for row in population["hold_records"]}
        truths = {}
        for entity in range(capacity):
            for workflow in range(capacity):
                truths[(entity, workflow)] = expected_execution(events[entity]["value"], rows["semantic"][entity]["value"], rows["procedure"][workflow]["value"], holds[entity]["value"])
        data_storage.append({"capacity": capacity, "source_json_bytes": (data / "sources.json").stat().st_size,
                             "sql_bytes": (data / "exact.sqlite").stat().st_size,
                             "canonical_cache_file_bytes": (data / "canonical.npz").stat().st_size,
                             "decoded_canonical_feature_bytes": sum(a.nbytes for a in features.values()),
                             "active_two_type_residual_parameter_bytes": (7692 + 13852) * 4})
        for seed in protocol["seeds"]:
            label = f"capacity-{capacity}-seed-{seed}"
            model_root, evaluation = ROOT / "models" / label, ROOT / "evaluation" / label
            fit, result = read(model_root / "FIT.json"), read(evaluation / "RESULTS.json")
            equal_fields(result, {"capacity": capacity, "seed": seed, "fitting_process_already_exited": True}, label)
            check(fit["data_sha256"] == sha((data / "sources.json").read_bytes()), "fit source data digest", label)
            for kind in rows:
                schedule_path = model_root / f"content-{kind}-schedule.npy"
                observations = [q for q in held if q["role"] == ("semantic" if kind == "semantic" else "skill")]
                column = "entity" if kind == "semantic" else "workflow"
                for arm in ("linear", "residual", "untrained"):
                    key = f"{kind}-{arm}"
                    scored = result["content"][key]
                    canonical_count = sum(p["value"] == r["value"] for p, r in zip(scored["canonical_predictions"], rows[kind], strict=True))
                    direct = sum(p["value"] == rows[kind][q[column]]["value"] for p, q in zip(scored["direct_unseen_predictions"], observations, strict=True))
                    counts = {"canonical_correct": canonical_count, "canonical_count": len(rows[kind]),
                              "direct_unseen_wording_correct": direct, "direct_unseen_wording_count": len(observations)}
                    equal_fields(scored, counts, (label, key))
                    pooled_content[f"{capacity}/{key}"].update(counts)
                    receipt = fit["models"]["content-" + key]["fit"]
                    manifest = read(model_root / ("content-" + key) / "manifest.json")
                    check(scored["parameter_sha256"] == manifest["parameter_sha256"], "content parameter identity", (label, key))
                    if receipt:
                        actual_schedule(schedule_path, receipt, (label, key))
                        equal_fields(receipt, {"features_sha256": sha(features[kind].astype("<f4").tobytes()),
                                              "targets_sha256": sha(gold[kind].astype("<f4").tobytes()),
                                              "trainable_parameter_count": checkpoints[f"models/{label}/content-{key}"]["scalars"],
                                              "steps": 1200, "sample_presentations": 38400}, (label, key))
                sql_result = result["content"][f"{kind}-exact_sql"]
                correct = sum(row["found"] and row["key"] == rows[kind][row["index"]]["key"]
                              and row["value"] == rows[kind][row["index"]]["value"]
                              and row["source_id"] == rows[kind][row["index"]]["source_id"] for row in sql_result["rows"])
                equal_fields(sql_result, {"canonical_correct": correct, "canonical_count": capacity, "sql_select_count": capacity}, (label, kind, "sql"))
                pooled_content[f"{capacity}/{kind}-exact_sql"].update(canonical_correct=correct, canonical_count=capacity)
            with np.load(model_root / "composition-training.npz", allow_pickle=False) as pair_data:
                pair_features, pair_targets, pair_indices = pair_data["features"], pair_data["targets"], pair_data["pairs"]
            check(bool(np.array_equal(pair_features, np.asarray([np.concatenate([features["semantic"][i], features["procedure"][j]]) for i, j in pair_indices]))), "composition actual feature pairing", label)
            check(bool(np.array_equal(pair_targets, np.asarray([np.concatenate([gold["semantic"][i], gold["procedure"][j]]) for i, j in pair_indices]))), "composition actual target pairing", label)
            pair_receipts = {}
            for arm, expected_count in (("typed", 21544), ("joint", 21544), ("dense_joint", 36904)):
                receipt = fit["models"][f"composition-{arm}"]["fit"]
                actual_schedule(model_root / "composition-schedule.npy", receipt, (label, arm))
                equal_fields(receipt, {"features_sha256": sha(pair_features.astype("<f4").tobytes()),
                                      "targets_sha256": sha(pair_targets.astype("<f4").tobytes()),
                                      "trainable_parameter_count": expected_count, "steps": 1200,
                                      "sample_presentations": 38400, "input_feature_coordinates_per_presentation": 768}, (label, arm))
                actual_count = sum(info["scalars"] for key, info in checkpoints.items() if key.startswith(f"models/{label}/composition-{arm}-"))
                check(actual_count == expected_count, "composition stored parameter count", (label, arm))
                pair_receipts[arm] = {k: receipt[k] for k in ("schedule_sha256", "features_sha256", "targets_sha256", "source_ids_sha256", "trainable_parameter_count", "initial_loss", "final_loss")}
            for field in ("schedule_sha256", "features_sha256", "targets_sha256", "source_ids_sha256"):
                check(len({v[field] for v in pair_receipts.values()}) == 1, "composition arm fairness differs: " + field, label)
            fairness.append({"experiment": label, "composition": pair_receipts})
            for arm in ("typed", "joint", "dense_joint", "exact_sql"):
                scored = result["composition"][arm]
                observed_pairs = set()
                counts = Counter()
                for row in scored["rows"]:
                    pair = row["entity"], row["workflow"]
                    observed_pairs.add(pair)
                    truth = truths[pair]
                    check(row["truth"] == truth, "composition truth differs from independently replayed sources", (label, arm, pair))
                    exact = row["prediction"] == truth
                    check(row["exact"] == exact, "composition exact flag", (label, arm, pair))
                    check(row["source_ids"] == [rows["semantic"][pair[0]]["source_id"], rows["procedure"][pair[1]]["source_id"], events[pair[0]]["source_id"], holds[pair[0]]["source_id"]], "composition dependencies", (label, arm, pair))
                    counts.update(count=1, exact=int(exact), nonheld_count=int(truth["status"] != "held"),
                                  nonheld_exact=int(exact and truth["status"] != "held"),
                                  both_parameter_values_exact=int(row["policy_exact"] and row["program_exact"]))
                check(len(observed_pairs) == 2 * capacity, "composition pair coverage", (label, arm))
                check(not observed_pairs.intersection(map(tuple, pair_indices)), "composition pair train/held overlap", (label, arm))
                equal_fields(scored, counts, (label, arm))
                pooled_composition[f"{capacity}/{arm}"].update(counts)
            route_maps = {}
            for arm, scored in result["routing"].items():
                counts, by_id = Counter(), {}
                for query, row in zip(held, scored["rows"], strict=True):
                    truth, prediction = route(query), row["prediction"]
                    accepts = prediction["operation"] != "reject" and prediction["score"] >= scored["threshold"] and prediction["margin"] >= 0.05
                    exact = same_route(prediction, truth)
                    check(row["truth"] == truth and row["query_id"] == query["id"], "route gold/input binding", (label, arm))
                    check(row["accepted"] == accepts and row["exact_address"] == exact, "routing event flags", (label, arm, query["id"]))
                    known = truth["operation"] != "reject"
                    counts.update(known_count=int(known), known_accepted=int(known and accepts),
                                  known_correct_accepted=int(known and accepts and exact),
                                  unknown_count=int(not known), unknown_accepted=int(not known and accepts))
                    by_id[query["id"]] = row
                equal_fields(scored, counts, (label, arm))
                pooled_routing[f"{capacity}/{arm}"].update(counts)
                route_maps[arm] = by_id
                if arm in ("learned", "nearest"):
                    selection = fit["routing"][arm + "_selection"]
                    eligible = [c for c in selection["candidates"] if c["accepted_unknown"] == 0]
                    threshold = max(eligible, key=lambda c: (c["correct_known"], c["threshold"]))["threshold"] if eligible else 1.01
                    check(threshold == selection["threshold"] == scored["threshold"], "calibration threshold choice drift", (label, arm))
            pipeline_counts = defaultdict(Counter)
            query_lookup = {q["id"]: q for q in held}
            with (evaluation / "pipeline.jsonl").open() as stream:
                for line in stream:
                    row = json.loads(line)
                    identity = row["routing"] + "/" + row["arm"]
                    routing = route_maps[row["routing"]][row["query_id"]]
                    truth = route(query_lookup[row["query_id"]])
                    known, allow = truth["operation"] != "reject", routing["accepted"]
                    if truth["operation"] == "apply":
                        expected_value = truths[(truth["entity"], truth["workflow"])]
                    elif known:
                        index = truth["entity"] if truth["operation"] == "semantic" else truth["workflow"]
                        expected_value = {"status": "ok", "value": rows[truth["operation"]][index]["value"]}
                    else:
                        expected_value = {"status": "rejected", "value": None}
                    exact = (not allow and not known) or (allow and routing["exact_address"] and row["prediction"] == expected_value)
                    check(row["exact"] == exact and row["accepted"] == allow, "pipeline event flags", (label, identity, row["query_id"]))
                    pipeline_counts[identity].update(correct=int(exact), count=1, known_correct=int(exact and known),
                                                     known_count=int(known), unknown_accepted=int(allow and not known), model_or_sql_reads=int(allow))
            for arm, counts in pipeline_counts.items():
                equal_fields(result["pipeline"][arm], counts, (label, arm))
                pooled_pipeline[f"{capacity}/{arm}"].update(counts)

            structural = read(model_root / "structure/STRUCTURE.json")
            original = np.asarray([r["value"] for r in rows["semantic"]])
            changed = original.copy()
            changed[::7] = (changed[::7] + [5, 3, 7]) % 16
            check(structural["values"] == changed.tolist(), "structure preregistered correction", label)
            for arm, arm_data in structural["arms"].items():
                receipt = arm_data["fit"]
                actual_schedule(model_root / "structure/schedule.npy", receipt, (label, "structure", arm))
                equal_fields(receipt, {"trainable_parameter_count": 6144, "steps": 600, "sample_presentations": 19200,
                                      "targets_sha256": sha(targets(changed.tolist(), "semantic").astype("<f4").tobytes())}, (label, arm))
                for i in range(len(arm_data["checkpoints"])):
                    manifest = read(model_root / "structure" / f"{arm}-{i}" / "manifest.json")
                    parent = read(model_root / "content-semantic-residual/manifest.json")
                    check(manifest["head_frozen"], "structure head must be frozen", (label, arm, i))
                    for name in ("head.weight", "head.bias"):
                        check(manifest["arrays"][name]["sha256"] == parent["arrays"][name]["sha256"], "structure frozen head differs from parent", (label, arm, i))
            structural_scores = {}
            for phase, filename, queries in [("calibration", "STRUCTURE_CALIBRATION.json", calibration), ("held", "STRUCTURE.json", held)]:
                report = read(evaluation / filename)
                semantic_queries = [q for q in queries if q["role"] == "semantic"]
                for arm, scored in report["arms"].items():
                    recomputed = {"canonical_count": capacity, "canonical_correct": sum(p["value"] == target for p, target in zip(scored["canonical_predictions"], structural["values"], strict=True)),
                                  "worded_count": len(semantic_queries), "worded_correct": sum(p["value"] == structural["values"][q["entity"]] for p, q in zip(scored["worded_predictions"], semantic_queries, strict=True))}
                    equal_fields(scored, recomputed, (label, phase, arm))
                if report["proposal_valid"]:
                    dynamic = report["arms"]["dynamic_children"]
                    controls = [report["arms"][name] for name in ("rank8", "fixed_experts")]
                    gate = {"strict_worded_gain_over_both_controls": all(dynamic["worded_correct"] > c["worded_correct"] for c in controls),
                            "no_canonical_regression": all(dynamic["canonical_correct"] >= c["canonical_correct"] for c in controls),
                            "used_for_admission": phase == "calibration"}
                    check(report["quality_gate"] == gate, "structure gate", (label, phase))
                    merge = report["merge"]
                    check(merge["no_quality_regression"] == (merge["canonical_correct"] >= dynamic["canonical_correct"] and merge["worded_correct"] >= dynamic["worded_correct"]), "merge quality gate", (label, phase))
                check(not report["split_admitted"] and not report["merge_admitted"], "unexpected structural promotion", (label, phase))
                structural_scores[phase] = {"arms": {name: {k: v[k] for k in ("canonical_correct", "canonical_count", "worded_correct", "worded_count")} for name, v in report["arms"].items()},
                                            "quality_gate": report.get("quality_gate"), "merge_no_quality_regression": report.get("merge", {}).get("no_quality_regression")}
            structure_rows.append({"experiment": label, **structural_scores})
            if capacity == 64:
                maintenance = read(evaluation / "MAINTENANCE.json")
                parent = read(model_root / "content-semantic-residual/manifest.json")
                lineage = {arm: set(parent["source_ids"]) for arm in ("full_replay", "reservoir16")}
                previous_parameters = {arm: parent["parameter_sha256"] for arm in lineage}
                for scored_cycle in maintenance["cycles"]:
                    number = scored_cycle["cycle"]
                    cycle_root = model_root / "maintenance" / f"cycle-{number:02d}"
                    cycle = read(cycle_root / "CYCLE.json")
                    deleted = cycle["event"] == "delete_clean_rebuild"
                    equal_fields(scored_cycle, {"cycle": number, "event": cycle["event"], "index": cycle["index"]}, (label, number))
                    for arm, scored in scored_cycle["arms"].items():
                        candidate, fit_receipt = cycle["arms"][arm], cycle["arms"][arm]["fit"]
                        schedule = actual_schedule(cycle_root / f"{arm}-schedule.npy", fit_receipt, (label, number, arm))
                        manifest = read(cycle_root / arm / "manifest.json")
                        selected, active = candidate["replay_indices"], cycle["active_indices"]
                        if deleted or arm == "full_replay":
                            check(selected == active, "full retained replay membership", (label, number, arm))
                        else:
                            check(len(selected) == 16 and cycle["index"] in selected and set(selected) <= set(active), "16-row replay membership", (label, number, arm))
                        if deleted:
                            lineage[arm] = set()
                            expected_initial = fit["models"]["content-semantic-residual"]["fit"]["initial_parameter_sha256"]
                            check(fit_receipt["initial_parameter_sha256"] == expected_initial == candidate["rebuild_initialization_sha256"], "clean initialization identity", (label, number, arm))
                        else:
                            check(fit_receipt["initial_parameter_sha256"] == previous_parameters[arm], "maintenance parameter continuity", (label, number, arm))
                        expected_sources = [source_id(i, cycle["versions"][i]) for i in selected]
                        lineage[arm].update(expected_sources[int(i)] for i in np.unique(schedule))
                        check(set(manifest["source_ids"]) == lineage[arm], "maintenance complete historical lineage", (label, number, arm))
                        check(manifest["extra"]["active_source_ids"] == [source_id(i, cycle["versions"][i]) for i in active], "maintenance live-source metadata", (label, number, arm))
                        equal_fields(fit_receipt, {"source_ids_sha256": sha(canonical(expected_sources)), "steps": 600,
                                                  "sample_presentations": 19200, "trainable_parameter_count": 7692,
                                                  "features_sha256": sha(features["semantic"][selected].astype("<f4").tobytes()),
                                                  "targets_sha256": sha(targets([cycle["values"][i] for i in selected], "semantic").astype("<f4").tobytes())}, (label, number, arm))
                        if deleted:
                            check(not any(source_id(cycle["index"], version) in manifest["source_ids"] for version in range(cycle["versions"][cycle["index"]] + 1)), "deleted source remains in rebuilt lineage", (label, number, arm))
                            check(scored["deleted_read"] == {"status": "deleted", "value": None}, "deleted guard result", (label, number, arm))
                        previous_parameters[arm] = manifest["parameter_sha256"]
                        correct = {i: scored["predictions"][i]["value"] == cycle["values"][i] for i in active}
                        retained = [i for i in active if i != cycle["index"]]
                        recomputed = {"canonical_correct": sum(correct.values()), "active_count": len(active),
                                      "retained_correct": sum(correct[i] for i in retained), "retained_count": len(retained),
                                      "changed_record_correct": correct.get(cycle["index"])}
                        equal_fields(scored, recomputed, (label, number, arm))
                        check(scored["model_reads_during_denials"] == 0 and scored["stopped_read"] == {"status": "owner_stopped", "value": None}, "guard observation", (label, number, arm))
                        maintenance_rows.append({"seed": seed, "cycle": number, "event": cycle["event"], "arm": arm,
                                                 "parameter_sha256": manifest["parameter_sha256"], **recomputed})
                    if deleted:
                        check(previous_parameters["full_replay"] == previous_parameters["reservoir16"], "common clean rebuild arms unexpectedly differ", (label, number))
    processes = read(ROOT / "PROCESSES.json")
    labels = [row["label"] for row in processes]
    check(len(processes) == 21 and all(row["exit_code"] == 0 for row in processes), "process completeness/success")
    check(max(i for i, label in enumerate(labels) if label.startswith("fit-")) < labels.index("prepare-held-after-all-fits")
          < min(i for i, label in enumerate(labels) if label.startswith("read-")), "fit/held/read process ordering")
    output = {
        "schema": "hepta.memory.v10.independent-audit.v1", "audit_scope": "Raw-byte hashing, source-only interpreter replay, saved prediction/count and receipt checks; no model/encoder/training execution",
        "input_root": str(ROOT), "source_freeze_commit": run["declared_published_source_commit"],
        "source_manifest_sha256": run["source_manifest_sha256"], "source_manifest_git_blob": git_blob,
        "artifact_inventory": {"declared_rows": len(original_inventory), "actual_files_with_self": len(files), "total_bytes": sum(row["bytes"] for row in files),
                               "original_inventory_has_hashes": False, "independent_hash_manifest_sha256": sha((OUT / "FILE_HASHES.json").read_bytes()),
                               "checkpoint_count": len(checkpoints)},
        "checks": CHECKS, "issues": ISSUES, "content": dict(pooled_content), "composition": dict(pooled_composition),
        "routing": dict(pooled_routing), "pipeline": dict(pooled_pipeline), "fairness": fairness,
        "structure": structure_rows, "maintenance": maintenance_rows, "data_storage": data_storage,
        "composition_parameter_metric_scope": "Pooled retained policy_exact/program_exact flags. Per-pair decoded parameter values are not retained, so those flags cannot be independently re-scored without model execution.",
        "calibration_threshold_scope": "Selection recomputed from saved candidate counts; calibration prediction rows are not retained.",
        "processes": {"count": len(processes), "wall_seconds": sum(r["wall_seconds"] for r in processes),
                      "cpu_seconds": sum(r["child_user_cpu_seconds"] + r["child_system_cpu_seconds"] for r in processes),
                      "cumulative_maxrss_kib": max(r["cumulative_child_maxrss_kib"] for r in processes)},
        "encoder": read(ROOT / "data/TRAIN_ENCODER.json"),
    }
    (OUT / "AUDIT.json").write_bytes(canonical(output))
    print(json.dumps({"checks": CHECKS, "issues": ISSUES[:20], "files": len(files), "checkpoints": len(checkpoints),
                      "total_bytes": output["artifact_inventory"]["total_bytes"], "report": str(OUT / "AUDIT.json")}, indent=2))


if __name__ == "__main__":
    main()
