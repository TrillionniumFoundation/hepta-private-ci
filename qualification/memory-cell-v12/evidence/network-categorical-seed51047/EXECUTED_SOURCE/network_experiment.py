"""Run V12 fixed types, learned sparse routing, and a future-tested evolution cycle."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np
from sklearn.cluster import KMeans

from corpus import build_corpus
from learned import features
from network import (Cell, Network, Retrieval, active_mask, calibrate, digest,
                     fit_cell, lower_gain, rewards, select, write_json)


def save_network(path, network):
    raw = json.dumps(network.export(), sort_keys=True, separators=(",", ":")).encode()
    with gzip.open(path, "wb") as stream:
        stream.write(raw)
    return dict(path=Path(path).name, bytes=Path(path).stat().st_size,
                raw_serialized_bytes=len(raw), sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def load_network(path):
    with gzip.open(path, "rb") as stream:
        state = json.load(stream)
    for cell in state["cells"]:
        if cell.get("sleeping"):
            cell["sleeping"]["path"] = str(Path(path).parent / Path(cell["sleeping"]["path"]).name)
    return Network.restore(state)


def target_indices(rows, lookup):
    return [[lookup[key] for key in row["target_ids"]] for row in rows]


def targets_matrix(targets, width):
    result = np.zeros((len(targets), width), np.float32)
    for i, target in enumerate(targets):
        result[i, target] = 1
    return result


def evaluate(name, operator, rows, x, mask, targets, threshold=None):
    start, cpu = time.perf_counter(), time.process_time()
    encoding_started = time.perf_counter()
    if isinstance(operator, Network) or operator.mode == "dense":
        actual_x = features([row["text"] for row in rows], dimension=x.shape[1])
        if not np.array_equal(actual_x, x):
            raise AssertionError("fresh query encoder differs from frozen features")
        x = actual_x
    encoding_seconds = time.perf_counter() - encoding_started
    if isinstance(operator, Network):
        for cell in operator.cells:
            cell.calls = 0
        scores, routes = operator.scores(x, mask)
        reads = sum(cell.calls for cell in operator.cells)
    else:
        scores = operator.scores([row["text"] for row in rows], x)
        routes, reads = [[] for _ in rows], 0
    if threshold is None:
        threshold = calibrate(scores, mask, targets)
    choices = select(scores, mask, threshold)
    outcomes = rewards(choices, targets)
    wall, cpu = time.perf_counter() - start, time.process_time() - cpu
    known = np.array([bool(target) for target in targets])
    rank = []
    for score, target in zip(scores, targets, strict=True):
        order = np.argsort(-score, kind="stable")
        rank.append(min((int(np.flatnonzero(order == item)[0]) + 1 for item in target), default=0))
    metrics = dict(queries=len(rows), known=int(known.sum()), unsupported=int((~known).sum()),
                   success=float(outcomes.mean()) if len(rows) else None,
                   known_success=float(outcomes[known].mean()) if known.any() else None,
                   unsupported_rejection=float(outcomes[~known].mean()) if (~known).any() else None,
                   known_mrr=float(np.mean([1 / r for r in rank if r])) if known.any() else None,
                   threshold=threshold, wall_seconds=wall, cpu_seconds=cpu,
                   feature_seconds=encoding_seconds,
                   selected_cell_reads=reads, score_sha256=hashlib.sha256(scores.astype("<f4").tobytes()).hexdigest())
    trace = [dict(query_id=row["id"], targets=target, prediction=choice, selected_cells=route,
                  success=int(outcome), first_relevant_rank=ranking,
                  confidence=float(scores[i].max())) for i, (row, target, choice, route, outcome, ranking)
             in enumerate(zip(rows, targets, choices, routes, outcomes, rank, strict=True))]
    return dict(name=name, metrics=metrics, trace=trace), outcomes


def utility_cost(network, evaluation, prices, checkpoint_bytes):
    usage = network.resource()
    return (prices["active_weight_mib"] * (usage["parameter_bytes"] + usage["router_bytes"]) / 2**20
            + prices["checkpoint_mib"] * checkpoint_bytes / 2**20
            + prices["training_second_per_1000_queries"] * usage["fit_wall_seconds"] / 1000
            + prices["decision_second"] * evaluation["metrics"]["wall_seconds"]
            / max(1, evaluation["metrics"]["queries"]))


def refresh(previous, x, y, mask, dependencies, seed, protocol):
    hidden, steps = protocol["hidden"], protocol["steps"]
    if previous is None:
        cell = fit_cell("parent", "universal", x, y, np.arange(len(mask)), dependencies,
                        hidden=hidden, steps=steps, seed=seed, objective=protocol.get("objective", "binary"))
        return Network([cell], len(mask))
    refreshed = []
    _, routes = previous.scores(x, mask)
    for i, old in enumerate(previous.cells):
        if old.model is None:
            refreshed.append(Cell.restore(old.export()))
            continue
        assigned = np.array([old.name in route for route in routes])
        if not assigned.any():
            refreshed.append(Cell.restore(old.export()))
            continue
        cell = fit_cell(old.name, old.kind, x[assigned], y[assigned], old.allowed,
                        old.dependencies + dependencies, hidden=hidden, steps=steps,
                        seed=seed + i, initial=old.model, objective=protocol.get("objective", "binary"))
        cell.receipts = old.receipts + cell.receipts
        refreshed.append(cell)
    result = Network(refreshed, len(mask), previous.top_k)
    if len(refreshed) > 1:
        result.fit_router(x, y)
    return result


def typed_network(records, mask, x, y, dependencies, seed, protocol):
    cells = []
    for i, kind in enumerate(sorted({row["kind"] for row in records})):
        allowed = [j for j, row in enumerate(records) if row["kind"] == kind]
        rows = y[:, allowed].sum(axis=1) > 0
        if rows.any():
            cells.append(fit_cell(kind, kind, x[rows], y[rows], allowed, dependencies,
                                  hidden=protocol["hidden"], steps=protocol["steps"], seed=seed + i,
                                  objective=protocol.get("objective", "binary")))
    return Network(cells, len(records))


def structure(parent, x, y, mask, dependencies, calibration, calibration_x,
              calibration_targets, output, seed, protocol):
    """One prespecified proposal cycle; subsequent-phase outcomes do not select it."""
    started = time.perf_counter()
    hidden, steps = protocol["hidden"], protocol["steps"]
    if len(parent.cells) != 1 or parent.cells[0].model is None:
        raise ValueError("this declared experiment starts its evolution cycle from one awake parent")
    original = parent.cells[0]
    partition = KMeans(n_clusters=2, random_state=seed, n_init=5).fit_predict(x)
    prior_steps = parent.resource()["presentations"] // protocol["batch_size"]
    total_steps = prior_steps + steps
    children, fixed = [], []
    action_costs = {}
    for i in range(2):
        selected = partition == i
        child = fit_cell(f"child-{i}", "specialist", x[selected], y[selected], original.allowed,
                         original.dependencies + dependencies, hidden=hidden, steps=steps // 2,
                         seed=seed + i, initial=original.model, objective=protocol.get("objective", "binary"))
        child.receipts = original.receipts + child.receipts
        children.append(child)
        fixed.append(fit_cell(f"fixed-{i}", "specialist", x[selected], y[selected], original.allowed,
                              dependencies, hidden=hidden, steps=total_steps // 2, seed=seed + 20 + i,
                              objective=protocol.get("objective", "binary")))
    split, fixed_network = Network(children, len(mask), 1), Network(fixed, len(mask), 1)
    split.fit_router(x, y)
    fixed_network.fit_router(x, y)
    continued = refresh(parent, x, y, mask, dependencies, seed + 30, protocol)
    capacity = Network([fit_cell("capacity", "universal", x, y, original.allowed, dependencies,
                                 hidden=2 * hidden, steps=total_steps, seed=seed + 40,
                                 objective=protocol.get("objective", "binary"))], len(mask))
    controls = dict(incumbent=parent, continued_parent=continued,
                    equal_capacity_single=capacity, same_partition_fixed_experts=fixed_network)
    candidates = dict(split=split)
    action_costs["split"] = dict(fit_seconds=sum(c.receipts[-1]["fit_wall_seconds"] for c in children),
                                inherited_dependencies_retained=True)
    # Distillation is actual training on observed inputs; no future labels are used.
    teacher, _ = split.scores(x, mask)
    merged = fit_cell("merged", "universal", x, teacher, original.allowed,
                      original.dependencies + dependencies, hidden=hidden, steps=steps, seed=seed + 50,
                      objective=protocol.get("objective", "binary"))
    merged.receipts = list({digest(r): r for child in children for r in child.receipts}.values()) + merged.receipts
    candidates["merge"] = Network([merged], len(mask))
    action_costs["merge"] = dict(fit_seconds=merged.receipts[-1]["fit_wall_seconds"],
                                teacher_rows=len(x), inherited_dependencies_retained=True)
    sleeping = Network.restore(split.export())
    before = time.perf_counter()
    sleeping.cells[0].sleep(output / "sleeping-cell.json")
    candidates["sleep"] = sleeping
    action_costs["sleep"] = dict(wall_seconds=time.perf_counter() - before,
                                checkpoint=sleeping.cells[0].sleeping, model_unloaded=True)
    waking = Network.restore(sleeping.export())
    before = time.perf_counter()
    waking.cells[0].wake()
    restored, _ = waking.scores(x, mask)
    if not np.array_equal(restored, teacher):
        raise AssertionError("wake must restore the actual split outputs bit-for-bit")
    candidates["wake"] = waking
    action_costs["wake"] = dict(wall_seconds=time.perf_counter() - before,
                               bitwise_outputs_restored=True, comparison="original awake systems")
    validation, artifacts = {}, {}
    for name, operator in {**controls, **candidates}.items():
        artifacts[name] = save_network(output / f"network-{name}.json.gz", operator)
        result, outcome = evaluate(name, operator, calibration, calibration_x, mask, calibration_targets)
        validation[name] = result, outcome
        write_json(output / f"validation-{name}.json", result)
    exploration_seconds = time.perf_counter() - started
    exploration_bytes = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    decisions, accepted = [], []
    limits, prices = protocol["structure"], protocol["prices"]
    for name, candidate in candidates.items():
        resource_use = candidate.resource()
        result, outcome = validation[name]
        extra_files = {c.sleeping["path"]: c.sleeping["bytes"] for c in candidate.cells if c.sleeping}
        artifact_bytes = artifacts[name]["bytes"] + sum(extra_files.values())
        resource_use["stored_checkpoint_bytes"] = artifact_bytes
        overlap_seconds = max(0, resource_use["fit_wall_seconds"] - parent.resource()["fit_wall_seconds"])
        exploration_cost = (prices["training_second_per_1000_queries"]
                            * max(0, exploration_seconds - overlap_seconds) / 1000
                            + prices["checkpoint_mib"] * max(0, exploration_bytes - artifact_bytes) / 2**20)
        cost = utility_cost(candidate, result, prices, artifact_bytes) + exploration_cost
        comparisons = {control: lower_gain(outcome, validation[control][1], cost,
                                           utility_cost(model, validation[control][0], prices, artifacts[control]["bytes"]),
                                           z=limits["normal_lower_bound_z"])
                       for control, model in controls.items()}
        reasons = []
        for field, limit in (("active_cells", "max_active_cells"), ("parameter_bytes", "max_parameter_bytes"),
                             ("stored_checkpoint_bytes", "max_checkpoint_bytes")):
            if resource_use[field] > limits[limit]:
                reasons.append(limit)
        if action_costs[name].get("fit_seconds", action_costs[name].get("wall_seconds", 0)) > limits["max_candidate_wall_seconds"]:
            reasons.append("candidate_wall_budget")
        admitted = not reasons and all(value["admitted"] for value in comparisons.values())
        if admitted:
            accepted.append((min(value["lower"] for value in comparisons.values()), name))
        decisions.append(dict(action=name, admitted=admitted, reasons=reasons, comparisons=comparisons,
                              resources=resource_use, action_cost=action_costs[name], artifact=artifacts[name],
                              all_exploration_penalty=exploration_cost))
    selected_name = max(accepted)[1] if accepted else "incumbent"
    selected = candidates.get(selected_name, parent)
    artifact = save_network(output / "selected.json.gz", selected)
    write_json(output / "DECISIONS.json", dict(decisions=decisions, selected=selected_name, artifact=artifact,
               controls={name: model.resource() for name, model in controls.items()},
               exploration_seconds=exploration_seconds, exploration_bytes_before_decisions=exploration_bytes,
               elapsed_seconds=time.perf_counter() - started,
               held_used_for_selection=False, prices=prices))
    # Serving next tasks consumes the persisted selected artifact, not a shadow.
    return load_network(output / "selected.json.gz"), decisions, controls, candidates


def diagnostics(network, x, y, canonical_count, mask, directory):
    """Training-only representation/optimization controls; no future-query targets."""
    started = time.perf_counter()
    positive = y.sum(axis=1) > 0
    design = np.column_stack([x[positive], np.ones(positive.sum())]).astype(np.float64)
    singular = np.linalg.svd(design, compute_uv=False)
    tolerance = singular[0] * max(design.shape) * np.finfo(float).eps
    target = y[positive] / y[positive].sum(axis=1, keepdims=True)
    coefficients = np.linalg.solve(design.T @ design + 1e-3 * np.eye(design.shape[1]), design.T @ target)
    np.savez_compressed(directory / "linear-positive-control.npz", coefficients=coefficients)
    linear = np.column_stack([x, np.ones(len(x))]) @ coefficients
    learned, _ = network.scores(x, mask)
    prototype = np.zeros_like(learned)
    prototype[:, np.flatnonzero(mask)] = x @ x[:canonical_count].T
    result = dict(affine_rank=int((singular > tolerance).sum()), design_shape=list(design.shape),
                  nonzero_condition=float(singular[0] / singular[singular > tolerance][-1]),
                  ridge=1e-3, source="training/canonical rows only", groups={})
    for group, indices in (("canonical", np.arange(canonical_count)),
                           ("historical_queries", np.arange(canonical_count, len(x)))):
        valid = indices[positive[indices]]
        truth = [list(np.flatnonzero(y[i])) for i in valid]
        values = {}
        for name, scores in (("learned", learned), ("closed_form_linear", linear), ("canonical_prototype", prototype)):
            safe = scores[valid].copy()
            safe[:, ~mask] = -np.inf
            order = np.argsort(-safe, axis=1, kind="stable")
            values[name] = dict(rows=len(valid),
                all_required_top3=float(np.mean([set(t).issubset(row[:3]) for t, row in zip(truth, order, strict=True)])) if len(valid) else None,
                first_relevant_mrr=float(np.mean([1 / min(int(np.flatnonzero(row == k)[0]) + 1 for k in t)
                                                 for t, row in zip(truth, order, strict=True)])) if len(valid) else None)
        result["groups"][group] = values
    result["wall_seconds"] = time.perf_counter() - started
    write_json(directory / "TRAINING_DIAGNOSIS.json", result)
    return result


def run(repo, destination, protocol):
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    data = build_corpus(repo)
    write_json(output / "CORPUS.json", data)
    source = Path(__file__).parent
    source_names = ["network.py", "network_experiment.py", "learned.py", "corpus.py", "NETWORK_PROTOCOL.json"]
    if protocol.get("objective") == "categorical":
        source_names += ["categorical.py", "NETWORK_FOLLOWUP_PROTOCOL.json"]
    identities = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in source_names}
    write_json(output / "FREEZE.json", dict(protocol=protocol, source_sha256=identities,
               corpus_sha256=data["corpus_sha256"], scope="local commitment before fitting"))
    (output / "EXECUTED_SOURCE").mkdir()
    for name in source_names:
        (output / "EXECUTED_SOURCE" / name).write_bytes((source / name).read_bytes())
    records, queries = data["records"], data["queries"]
    lookup = {row["id"]: i for i, row in enumerate(records)}
    if len(lookup) != len(records) or any(key not in lookup for row in queries for key in row["target_ids"]):
        raise ValueError("source/query index mapping is not complete and unique")
    dimension = protocol["dimension"]
    feature_started = time.perf_counter()
    source_x = features([row["text"] for row in records], dimension=dimension)
    query_x = features([row["text"] for row in queries], dimension=dimension)
    feature_seconds = time.perf_counter() - feature_started
    query_lookup = {row["id"]: i for i, row in enumerate(queries)}
    summary = []
    for seed in protocol["seeds"]:
        previous_single, previous_evolution_path = None, None
        for phase in sorted({int(row["available_phase"]) for row in records}):
            directory = output / f"seed-{seed}" / f"phase-{phase}"
            directory.mkdir(parents=True)
            mask = active_mask(records, phase)
            active = np.flatnonzero(mask)
            history = [row for row in queries if (row["phase"] < phase and row["split"] != "calibration")
                       or (phase == 0 and row["phase"] == 0 and row["split"] == "train")]
            calibration = [row for row in queries if row["split"] == "calibration"
                           and row["phase"] <= max(phase - 1, 0)]
            testing = [row for row in queries if row["split"] == "test" and row["phase"] == phase]
            x = np.vstack([source_x[active], query_x[[query_lookup[row["id"]] for row in history]]])
            y = targets_matrix([[int(i)] for i in active] + target_indices(history, lookup), len(records))
            calibration_x = query_x[[query_lookup[row["id"]] for row in calibration]]
            testing_x = query_x[[query_lookup[row["id"]] for row in testing]]
            calibration_targets, testing_targets = target_indices(calibration, lookup), target_indices(testing, lookup)
            dependencies = [records[i]["source_id"] for i in active]
            parent = refresh(previous_single, x, y, mask, dependencies, seed + phase * 100, protocol)
            previous_single = parent
            parent_artifact = None
            if previous_evolution_path is not None:
                loaded_parent = load_network(previous_evolution_path)
                parent_artifact = dict(path=previous_evolution_path.relative_to(output).as_posix(),
                                       sha256=hashlib.sha256(previous_evolution_path.read_bytes()).hexdigest(),
                                       parameters=[c.model.export()["parameter_sha256"] for c in loaded_parent.cells if c.model is not None])
                evolution_parent = refresh(loaded_parent, x, y, mask, dependencies, seed + phase * 100, protocol)
                continued_digests = [c.receipts[-1]["initial_parameter_sha256"] for c in evolution_parent.cells if c.model is not None]
                if continued_digests != parent_artifact["parameters"]:
                    raise AssertionError("evolution did not continue the persisted selected parameters")
            else:
                evolution_parent = parent
            diagnosis = diagnostics(parent, x, y, len(active), mask, directory) if protocol.get("training_diagnostics") else None
            fixed = typed_network(records, mask, x, y, dependencies, seed + phase * 100 + 10, protocol)
            sparse = Network.restore(fixed.export())
            sparse.top_k = min(protocol["sparse_top_k"], len(sparse.cells))
            sparse.fit_router(x, y)
            arms = dict(single_mlp=parent, fixed_typed=fixed, learned_sparse=sparse,
                        full_text_bm25=Retrieval(records, mask, dimension=dimension),
                        dense_source_retrieval=Retrieval(records, mask, "dense", dimension))
            decisions = []
            if phase == protocol["structure"]["proposal_phase"]:
                previous_evolution, decisions, controls, candidates = structure(evolution_parent, x, y, mask, dependencies,
                    calibration, calibration_x, calibration_targets, directory, seed, protocol)
                arms.update({k: v for k, v in controls.items() if k != "incumbent"})
                arms["selected_evolution"] = previous_evolution
            else:
                previous_evolution = evolution_parent
                arms["selected_evolution"] = previous_evolution
            # Threshold and topology decisions end here, before future labels score a model.
            thresholds = {}
            for name, operator in arms.items():
                result, _ = evaluate(name, operator, calibration, calibration_x, mask, calibration_targets)
                write_json(directory / f"calibration-{name}.json", result)
                thresholds[name] = result["metrics"]["threshold"]
            write_json(directory / "PRE_TEST.json", dict(thresholds=thresholds, training_query_ids=[r["id"] for r in history],
                       calibration_query_ids=[r["id"] for r in calibration],
                       evolution_parent_artifact=parent_artifact,
                       source_ids=[records[i]["id"] for i in active], future_labels_used=False))
            phase_results = {}
            for name, operator in arms.items():
                if isinstance(operator, Network):
                    checkpoint = save_network(directory / f"arm-{name}.json.gz", operator)
                    operator = load_network(directory / f"arm-{name}.json.gz")
                    usage = operator.resource()
                    usage["artifact"] = checkpoint
                else:
                    usage = dict(index_bytes=operator.index_bytes, fit_wall_seconds=operator.fit_seconds)
                result, _ = evaluate(name, operator, testing, testing_x, mask, testing_targets, thresholds[name])
                grouped = {}
                for trace in result["trace"]:
                    kinds = sorted({records[i]["kind"] for i in trace["targets"]})
                    key = "+".join(kinds) if kinds else "unsupported"
                    grouped.setdefault(key, []).append(trace["success"])
                result["metrics"]["by_kind"] = {key: dict(count=len(values), success=float(np.mean(values)))
                                               for key, values in grouped.items()}
                result["resources"] = usage
                write_json(directory / f"test-{name}.json", result)
                phase_results[name] = result["metrics"] | {"resources": usage}
            previous_evolution_path = directory / "arm-selected_evolution.json.gz"
            write_json(directory / "RESULT.json", dict(seed=seed, phase=phase, current_records=int(mask.sum()),
                       train_examples=len(x), results=phase_results, structural_decisions=decisions,
                       training_diagnosis=diagnosis,
                       scope="future module-arrival queries" if phase else "initial within-phase diagnostic"))
            summary.append(dict(seed=seed, phase=phase, records=int(mask.sum()), results=phase_results,
                                admitted=[d["action"] for d in decisions if d["admitted"]]))
            print(json.dumps(dict(seed=seed, phase=phase, completed=True,
                             success={k: v["success"] for k, v in phase_results.items()})), flush=True)
    after = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in identities}
    if after != identities:
        raise RuntimeError("executed sources changed during formal run")
    files = [path for path in output.rglob("*") if path.is_file()]
    result = dict(schema="hepta.memory.network-results.v12", runs=summary, source_identity=identities,
                  corpus_sha256=data["corpus_sha256"], feature_seconds=feature_seconds,
                  feature_bytes=source_x.nbytes + query_x.nbytes,
                  source_text_bytes=sum(len(row["text"].encode()) for row in records),
                  elapsed_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  evidence_bytes_before_summary=sum(path.stat().st_size for path in files),
                  limitations=data["limitations"] + ["lexical hash features; no pretrained language semantics",
                    "single prespecified evolution cycle at phase 1; phase 2 measures later use",
                    "all source evidence retained; no parametric compression claim",
                    "research snapshot filtering, not native Rust source authority"])
    write_json(output / "SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("NETWORK_PROTOCOL.json"))
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    try:
        run(args.repo, args.output, protocol)
    except Exception as error:
        if args.output.is_dir():
            write_json(args.output / "FAILED.json", dict(type=type(error).__name__, error=str(error)))
        raise
