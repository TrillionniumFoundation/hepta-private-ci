"""Fresh-process evaluation of saved parameters and fixed strong controls."""

import argparse
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

from corpus import interpret, pairs
from export_native import canonical
from maintenance_evaluate import evaluate_maintenance, evaluate_structure
from reference import decode, forward, load_checkpoint
from routing import accepted, deterministic, expected_route, learned_routes, nearest_routes, same_route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    fit = json.loads((args.models / "FIT.json").read_text())
    population = json.loads((args.data / "sources.json").read_text())
    queries = json.loads((args.data / "held-queries.json").read_text())
    train_rows = json.loads((args.data / "train-queries.json").read_text())
    with np.load(args.data / "canonical.npz", allow_pickle=False) as archive:
        canonical_x = {kind: archive[kind] for kind in ("semantic", "procedure")}
    with np.load(args.data / "held-features.npz", allow_pickle=False) as archive:
        query_x = archive["features"]
    with np.load(args.data / "train-features.npz", allow_pickle=False) as archive:
        train_x = archive["features"]
    rows = {kind: [row for row in population["records"] if row["kind"] == kind] for kind in canonical_x}
    expected = [expected_route(row) for row in queries]
    models, setups = {}, {}
    for name in fit["models"]:
        started = time.perf_counter()
        if name.startswith("composition"):
            models[name] = [load_checkpoint(args.models / f"{name}-{i}") for i in range(len(fit["models"][name]["checkpoints"]))]
        else:
            models[name] = [load_checkpoint(args.models / name)]
        setups[name] = time.perf_counter() - started
    connection = sqlite3.connect(f"file:{args.data / 'exact.sqlite'}?mode=ro", uri=True)
    report = {"schema": "hepta.memory.v10.evaluation.v1", "seed": fit["seed"], "capacity": fit["capacity"],
              "fitting_process_already_exited": True, "content": {}, "composition": {}, "routing": {},
              "pipeline": {}, "checkpoint_load_seconds": setups,
              "performance_scope": "measured local Python/SQLite evaluation; complete installation/host/native cost is separate"}
    for kind in ("semantic", "procedure"):
        positions = [i for i, row in enumerate(queries) if row["role"] == ("semantic" if kind == "semantic" else "skill")]
        indices = [queries[i]["entity" if kind == "semantic" else "workflow"] for i in positions]
        for arm in ("linear", "residual", "untrained"):
            arrays, manifest = models[f"content-{kind}-{arm}"][0]
            canonical_predictions = decode(forward(arrays, canonical_x[kind]), kind)
            direct_predictions = decode(forward(arrays, query_x[positions]), kind)
            report["content"][f"{kind}-{arm}"] = {
                "canonical_correct": sum(pred["value"] == row["value"] for pred, row in zip(canonical_predictions, rows[kind], strict=True)),
                "canonical_count": len(rows[kind]), "direct_unseen_wording_correct": sum(pred["value"] == rows[kind][index]["value"] for pred, index in zip(direct_predictions, indices, strict=True)),
                "direct_unseen_wording_count": len(indices), "parameter_sha256": manifest["parameter_sha256"],
                "canonical_predictions": canonical_predictions, "direct_unseen_predictions": direct_predictions}
        # Score actual database reads, including their key and source bindings.
        sql_started, sql_rows = time.perf_counter(), []
        for row in rows[kind]:
            observed = connection.execute("SELECT key,value,source_id FROM memory WHERE kind=? AND idx=?",
                                          (kind, row["index"])).fetchone()
            key, value, source = (observed[0], json.loads(observed[1]), observed[2]) if observed is not None else (None, None, None)
            sql_rows.append({"index": row["index"], "key": key, "value": value, "source_id": source,
                             "found": observed is not None, "value_exact": value == row["value"],
                             "key_exact": key == row["key"], "source_id_exact": source == row["source_id"]})
        report["content"][f"{kind}-exact_sql"] = {
            "canonical_correct": sum(row["value_exact"] and row["key_exact"] and row["source_id_exact"] for row in sql_rows),
            "canonical_count": len(rows[kind]), "canonical_value_correct": sum(row["value_exact"] for row in sql_rows),
            "canonical_key_correct": sum(row["key_exact"] for row in sql_rows),
            "canonical_source_correct": sum(row["source_id_exact"] for row in sql_rows), "rows": sql_rows,
            "sql_select_count": len(sql_rows), "sql_read_wall_seconds": time.perf_counter() - sql_started,
            "direct_unseen_wording": "addressing is measured separately below"}

    def values_for(arm, entity, workflow, operation):
        if arm == "exact_sql":
            policy = json.loads(connection.execute("SELECT value FROM memory WHERE kind='semantic' AND idx=?", (entity,)).fetchone()[0]) if operation != "procedure" else None
            program = json.loads(connection.execute("SELECT value FROM memory WHERE kind='procedure' AND idx=?", (workflow,)).fetchone()[0]) if operation != "semantic" else None
            return policy, program
        if arm in ("linear", "residual"):
            policy = decode(forward(models[f"content-semantic-{arm}"][0][0], canonical_x["semantic"][entity:entity + 1]), "semantic")[0]["value"] if operation != "procedure" else None
            program = decode(forward(models[f"content-procedure-{arm}"][0][0], canonical_x["procedure"][workflow:workflow + 1]), "procedure")[0]["value"] if operation != "semantic" else None
            return policy, program
        cells = models["composition-" + arm]
        # Typed/joint models all consume the same pair, including for one-type reads.
        left, right = entity if entity is not None else 0, workflow if workflow is not None else 0
        x = np.concatenate((canonical_x["semantic"][left], canonical_x["procedure"][right]))[None, :]
        if arm == "typed":
            raw = np.concatenate((forward(cells[0][0], x[:, :384]), forward(cells[1][0], x[:, 384:])), axis=1)
        else:
            raw = forward(cells[0][0], x, operator=cells[0][1]["operator"])
        return decode(raw[:, :12], "semantic")[0]["value"], decode(raw[:, 12:], "procedure")[0]["value"]

    def execute(arm, route):
        operation, entity, workflow = route["operation"], route.get("entity"), route.get("workflow")
        policy, program = values_for(arm, entity, workflow, operation)
        if operation == "semantic":
            return {"status": "ok" if policy is not None else "abstained", "value": policy}, [rows["semantic"][entity]["source_id"]]
        if operation == "procedure":
            return {"status": "ok" if program is not None else "abstained", "value": program}, [rows["procedure"][workflow]["source_id"]]
        event, event_source = connection.execute("SELECT value,source_id FROM episode WHERE idx=? AND at<=20 ORDER BY at DESC LIMIT 1", (entity,)).fetchone()
        held, hold_source = connection.execute("SELECT held,source_id FROM exception WHERE idx=?", (entity,)).fetchone()
        sources = [rows["semantic"][entity]["source_id"], rows["procedure"][workflow]["source_id"], event_source, hold_source]
        if held:
            return interpret(event, [0, 0, 0], [6], hold=True), sources
        if policy is None or program is None:
            return {"status": "abstained", "value": None, "trace": []}, sources
        return interpret(event, policy, program), sources

    held_pairs = pairs(fit["capacity"], "held")
    for arm in ("typed", "joint", "dense_joint", "exact_sql"):
        observations, started = [], time.perf_counter()
        for entity, workflow in held_pairs:
            route = {"operation": "apply", "entity": entity, "workflow": workflow}
            prediction, sources = execute(arm, route)
            truth, _ = execute("exact_sql", route)
            policy, program = values_for(arm, entity, workflow, "apply")
            observations.append({"entity": entity, "workflow": workflow, "prediction": prediction, "truth": truth,
                                 "source_ids": sources, "exact": prediction == truth,
                                 "policy_exact": policy == rows["semantic"][entity]["value"],
                                 "program_exact": program == rows["procedure"][workflow]["value"]})
        report["composition"][arm] = {"exact": sum(row["exact"] for row in observations), "count": len(observations),
                                      "nonheld_exact": sum(row["exact"] for row in observations if row["truth"]["status"] != "held"),
                                      "nonheld_count": sum(row["truth"]["status"] != "held" for row in observations),
                                      "both_parameter_values_exact": sum(row["policy_exact"] and row["program_exact"] for row in observations),
                                      "read_and_reference_wall_seconds": time.perf_counter() - started, "rows": observations}
    entities = [{"key": row["key"]} for row in rows["semantic"]]
    workflows = [{"key": row["key"]} for row in rows["procedure"]]
    router_arrays, _ = load_checkpoint(args.models / "router")
    route_arms = {
        "oracle": [{**row, "score": 1.0, "margin": 1.0} for row in expected],
        "deterministic": [deterministic(row["text"], entities, workflows) for row in queries],
        "learned": learned_routes(forward(router_arrays, query_x), fit["capacity"]),
        "nearest": nearest_routes(query_x, train_x, train_rows)}
    thresholds = {"oracle": 0, "deterministic": 0, "learned": fit["routing"]["learned_selection"]["threshold"],
                  "nearest": fit["routing"]["nearest_selection"]["threshold"]}
    for name, routes in route_arms.items():
        records = [{"query_id": query["id"], "prediction": route, "truth": truth,
                    "accepted": accepted(route, thresholds[name]), "exact_address": same_route(route, truth)}
                   for query, route, truth in zip(queries, routes, expected, strict=True)]
        known = [row for row in records if row["truth"]["operation"] != "reject"]
        unknown = [row for row in records if row["truth"]["operation"] == "reject"]
        known_accepted = sum(row["accepted"] for row in known)
        known_correct = sum(row["accepted"] and row["exact_address"] for row in known)
        report["routing"][name] = {"known_correct_accepted": known_correct, "known_accepted": known_accepted,
                                   "known_coverage": known_accepted / len(known) if known else None,
                                   "accepted_known_precision": known_correct / known_accepted if known_accepted else None,
                                   "correct_known_acceptance": known_correct / len(known) if known else None,
                                   "known_count": len(known), "unknown_accepted": sum(row["accepted"] for row in unknown),
                                   "unknown_count": len(unknown), "threshold": thresholds[name], "rows": records}
    read_arms = ["linear", "residual", "typed", "joint", "dense_joint", "exact_sql"]
    rotation = (fit["seed"] - 1741) % len(read_arms)
    read_arms = read_arms[rotation:] + read_arms[:rotation]
    report["read_arm_order"] = read_arms
    with (args.output / "pipeline.jsonl").open("wb") as evidence:
        for routing_name, routes in route_arms.items():
            for arm in read_arms:
                started, cpu = time.perf_counter(), time.process_time()
                correct, known_correct, false_accept, reads = 0, 0, 0, 0
                for query, route, truth in zip(queries, routes, expected, strict=True):
                    allow = accepted(route, thresholds[routing_name])
                    if allow:
                        prediction, sources = execute(arm, route)
                        reads += 1
                    else:
                        prediction, sources = {"status": "rejected", "value": None}, []
                    target = execute("exact_sql", truth)[0] if truth["operation"] != "reject" else {"status": "rejected", "value": None}
                    exact = ((not allow and truth["operation"] == "reject") or
                             (allow and same_route(route, truth) and prediction == target))
                    correct += exact
                    known_correct += exact and truth["operation"] != "reject"
                    false_accept += allow and truth["operation"] == "reject"
                    evidence.write(canonical({"query_id": query["id"], "routing": routing_name, "arm": arm,
                                               "prediction": prediction, "source_ids": sources, "exact": exact,
                                               "exact_address": same_route(route, truth), "accepted": allow}) + b"\n")
                report["pipeline"][f"{routing_name}/{arm}"] = {"correct": correct, "count": len(queries),
                                                               "known_correct": known_correct, "known_count": sum(row["operation"] != "reject" for row in expected),
                                                               "unknown_accepted": false_accept, "model_or_sql_reads": reads,
                                                               "wall_seconds_including_reference_and_evidence": time.perf_counter() - started,
                                                               "cpu_seconds_including_reference_and_evidence": time.process_time() - cpu}
    semantic_positions = [i for i, row in enumerate(queries) if row["role"] == "semantic"]
    calibration_queries = json.loads((args.data / "calibration-queries.json").read_text())
    with np.load(args.data / "calibration-features.npz", allow_pickle=False) as archive:
        calibration_x = archive["features"]
    calibration_positions = [i for i, row in enumerate(calibration_queries) if row["role"] == "semantic"]
    report["structure_calibration"] = evaluate_structure(args.models / "structure", canonical_x["semantic"],
                                                          calibration_x[calibration_positions],
                                                          [calibration_queries[i]["entity"] for i in calibration_positions],
                                                          args.output / "STRUCTURE_CALIBRATION.json", phase="calibration")
    report["structure"] = evaluate_structure(args.models / "structure", canonical_x["semantic"], query_x[semantic_positions],
                                               [queries[i]["entity"] for i in semantic_positions], args.output / "STRUCTURE.json")
    if (args.models / "maintenance").exists():
        maintenance = evaluate_maintenance(args.models / "maintenance", canonical_x["semantic"], args.output / "MAINTENANCE.json")
        report["maintenance_final"] = maintenance["cycles"][-1]
    connection.close()
    (args.output / "RESULTS.json").write_bytes(canonical(report))
    print(json.dumps({"seed": fit["seed"], "capacity": fit["capacity"], "held_queries": len(queries), "fresh_reader": True}))


if __name__ == "__main__":
    main()
