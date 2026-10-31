"""Freeze-separated fitting and evaluation of the raw-evidence controller."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

try:
    from . import policy, policy_audit
    from .content import Model
    from .content_tasks import multimodal_support
except ImportError:
    import policy
    import policy_audit
    from content import Model
    from content_tasks import multimodal_support


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def identity(model_path):
    folder = Path(__file__).resolve().parent
    sources = ("policy.py", "policy_audit.py", "policy_run.py", "POLICY_CONTRACT.md",
               "content.py", "content_tasks.py", "renewal.py")
    return {"model_sha256": digest(model_path),
            "sources": {name: digest(folder / name) for name in sources}}


def commit(value):
    if not re.fullmatch("[0-9a-f]{40}", value):
        raise ValueError("A real, previously published 40-hex commit is required")
    return value


def controller_from(payload):
    if payload["kind"] == "ridge_value":
        return policy.RidgeValue(payload["mean"], payload["scale"],
                                 payload["weights"], payload["ridge"])
    return policy.Lightweight(payload["kind"], payload["parameter"])


def build_graph(model, config):
    graph = policy.TeacherGraph(model, config, multimodal_support)
    graph.solve()
    return graph


def graph_records(path, graphs):
    with gzip.open(path, "xt", encoding="utf-8") as stream:
        for graph in graphs:
            for node in graph.records():
                stream.write(json.dumps({"config": graph.config.name, **node},
                                        allow_nan=False, separators=(",", ":")) + "\n")


def fit(model_path, output, freeze_commit):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    model = Model.load(model_path)
    assert model.input_dim == 12 and model.classes == 2 and model.width == 16
    source = identity(model_path)
    splits = policy.configurations()
    training = [build_graph(model, config) for config in splits["train"]]
    fitted = policy.RidgeValue.fit(training, ridge=1.)
    development = [build_graph(model, config) for config in splits["dev"]]
    selected, candidates = policy.select_lightweight(model, development)
    best_fixed = max((row for row in candidates if row["controller"]["kind"] == "fixed"),
                     key=lambda row: row["mean_return"])["controller"]
    best_confidence = max((row for row in candidates if row["controller"]["kind"] == "confidence"),
                          key=lambda row: row["mean_return"])["controller"]
    payload = {"schema": "hcsn.public-controller.v1", "source": source,
               "protocol_freeze_commit": commit(freeze_commit),
               "model_family": model.family, "model_seed": model.seed,
               "model_path": str(Path(model_path)), "model_width": model.width,
               "value": fitted.payload(), "best_lightweight": selected.payload(),
               "best_fixed": best_fixed, "best_confidence": best_confidence,
               "training_configs": [c.payload() for c in splits["train"]],
               "dev_configs": [c.payload() for c in splits["dev"]]}
    write_json(output / "controller.json", payload)
    graph_records(output / "training_teacher.jsonl.gz", training)
    graph_records(output / "development_teacher.jsonl.gz", development)
    checks = policy_audit.contract_checks(model, splits["dev"][0], multimodal_support)
    counts = {action: sum(action in n["q"] for g in training for n in g.nodes.values())
              for action in policy.ACTIONS}
    summary = {"schema": "hcsn.policy-fit.v1", "source": source,
               "protocol_freeze_commit": freeze_commit,
               "controller_sha256": digest(output / "controller.json"),
               "training_histories": sum(len(g.nodes) for g in training),
               "legal_training_labels": counts, "dev_candidates": candidates,
               "selected_lightweight": selected.payload(), "negative_controls": checks,
               "train_calibration": {g.config.name: policy.calibration(g, fitted) for g in training},
               "dev_calibration": {g.config.name: policy.calibration(g, fitted) for g in development},
               "scope": "Fit and dev only; no heldout graph, sample or metric was read.",
               "cpu_before_final_receipt": time.process_time() - started_cpu,
               "wall_before_final_receipt": time.perf_counter() - started_wall}
    assert identity(model_path) == source
    write_json(output / "FIT.json", summary)
    return summary


def paired_execution(model, config, controllers, graph, path, count, seed):
    values = {name: [] for name in controllers}
    phases_cpu, phases_wall = {}, {}
    failures, maximum = 0, 0.
    with gzip.open(path, "xt", encoding="utf-8") as stream:
        for original in policy_audit.sampled_worlds(config, multimodal_support, count, seed):
            manifest = original.manifest()
            for name, controller in controllers.items():
                world = policy_audit.World(manifest["world_id"],
                    manifest["hidden_label_evaluator_only"], manifest["outcomes_evaluator_only"],
                    config, multimodal_support)
                result = policy_audit.execute(model, config, multimodal_support,
                                               controller, world, graph)
                values[name].append(result["return"])
                maximum = max(maximum, result["max_graph_state_error"])
                failures += sum(step["guard_rejected"] for step in result["steps"])
                for key, value in result["phase_cpu_seconds"].items():
                    phases_cpu[key] = phases_cpu.get(key, 0.) + value
                for key, value in result["phase_wall_seconds"].items():
                    phases_wall[key] = phases_wall.get(key, 0.) + value
                stream.write(json.dumps({"controller": name, "source": manifest,
                                        "execution": result}, separators=(",", ":"),
                                        allow_nan=False) + "\n")
    assert failures == 0 and maximum < 2e-10
    comparisons = {}
    for baseline in ("stop", "fixed", "confidence"):
        differences = np.array(values["value"]) - np.array(values[baseline])
        comparisons["value_minus_" + baseline] = {
            "mean": float(differences.mean()),
            "conditional_world_standard_error": float(differences.std(ddof=1) / np.sqrt(count)),
            "paired_differences": differences.tolist()}
    return {"world_seed": seed, "worlds_per_controller": count,
            "actual_executions": count * len(controllers), "guard_fallbacks": failures,
            "mean_returns": {name: float(np.mean(v)) for name, v in values.items()},
            "comparisons": comparisons, "max_graph_state_error": maximum,
            "exclusive_phase_cpu_seconds": phases_cpu, "exclusive_phase_wall_seconds": phases_wall,
            "scope": "128 paired worlds diagnose execution, not a replacement for exact expectations."}


def evaluate(model_path, controller_path, output, candidate_commit):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    payload = json.loads(Path(controller_path).read_text())
    assert payload["schema"] == "hcsn.public-controller.v1"
    source = identity(model_path)
    assert payload["source"] == source, "Source or content checkpoint changed after controller freeze"
    model = Model.load(model_path)
    controllers = {"stop": policy.Lightweight("stop"),
                   "fixed": controller_from(payload["best_fixed"]),
                   "confidence": controller_from(payload["best_confidence"]),
                   "value": controller_from(payload["value"]), "oracle": policy_audit.Oracle()}
    lightweight = controller_from(payload["best_lightweight"])
    rows, independent = [], {}
    for index, config in enumerate(policy.configurations()["heldout"]):
        graph = build_graph(model, config)
        graph_records(output / f"{config.name}_teacher.jsonl.gz", [graph])
        exact = {name: graph.exact_policy(controller) for name, controller in controllers.items()
                 if name != "oracle"}
        exact["selected_lightweight"] = graph.exact_policy(lightweight)
        exact["oracle"] = {"return": graph.nodes[()]["value"]}
        assert max(item.get("performance_identity_error", 0.) for item in exact.values()) < 2e-10
        paired = paired_execution(model, config, controllers, graph,
                                  output / f"{config.name}_paired.jsonl.gz", 128,
                                  730000 + model.seed * 100 + index)
        boundaries = policy.boundary_diagnostic(graph, controller=controllers["value"])
        rows.append({"config": config.payload(), "histories": len(graph.nodes), "exact": exact,
                     "value_calibration": policy.calibration(graph, controllers["value"]),
                     "paired_execution": paired, "task_value_boundaries": boundaries})
        if index == 0:
            with gzip.open(output / "independent_exhaustive_execution.jsonl.gz", "xt",
                           encoding="utf-8") as stream:
                for name, controller in controllers.items():
                    def sink(record):
                        stream.write(json.dumps({"controller": name, **record},
                            separators=(",", ":"), allow_nan=False) + "\n")
                    independent[name] = policy_audit.independent_expectation(
                        model, config, multimodal_support, controller, graph, sink)
            with gzip.open(output / "boundary_exhaustive_execution.jsonl.gz", "xt",
                           encoding="utf-8") as stream:
                def boundary_sink(record):
                    stream.write(json.dumps(record, separators=(",", ":"),
                                            allow_nan=False) + "\n")
                independent["boundary_sides"] = policy_audit.boundary_execution_check(
                    model, graph, multimodal_support, controllers["value"], boundaries[0], boundary_sink)
    value_mean = float(np.mean([row["exact"]["value"]["return"] for row in rows]))
    base_mean = float(np.mean([row["exact"]["selected_lightweight"]["return"] for row in rows]))
    summary = {"schema": "hcsn.policy-evaluation.v1", "candidate_commit": commit(candidate_commit),
               "protocol_freeze_commit": payload["protocol_freeze_commit"], "source": source,
               "controller_sha256": digest(controller_path), "model_family": model.family,
               "model_seed": model.seed, "model_width": model.width,
               "selected_lightweight": payload["best_lightweight"], "heldout": rows,
               "independent_exhaustive_execution": independent,
               "mean_exact_value_return": value_mean, "mean_exact_lightweight_return": base_mean,
               "value_minus_lightweight": value_mean - base_mean,
               "cpu_before_final_receipt": time.process_time() - started_cpu,
               "wall_before_final_receipt": time.perf_counter() - started_wall,
               "scope": "Finite synthetic raw evidence with known likelihoods; descriptive 2x2, no scaling claim.",
               "cost_scope": "Abstract READ/SKIP tariffs plus separately measured real CPU/wall; no energy claim."}
    assert identity(model_path) == source
    write_json(output / "EVALUATION.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("fit", "evaluate"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--freeze-commit")
    parser.add_argument("--controller")
    parser.add_argument("--candidate-commit")
    args = parser.parse_args()
    if args.stage == "fit":
        if not args.freeze_commit:
            parser.error("fit requires --freeze-commit")
        commit(args.freeze_commit)
        result = fit(args.model, args.output, args.freeze_commit)
    else:
        if not args.controller or not args.candidate_commit:
            parser.error("evaluate requires --controller and --candidate-commit")
        commit(args.candidate_commit)
        result = evaluate(args.model, args.controller, args.output, args.candidate_commit)
    print(json.dumps({"stage": args.stage, "output": args.output,
                      "source": result["source"], "completed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
