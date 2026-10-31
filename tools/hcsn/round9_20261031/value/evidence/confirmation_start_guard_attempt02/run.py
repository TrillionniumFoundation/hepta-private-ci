"""Immutable expanded-domain training, then fixed-model and paired blind replay."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import t

from tools.hcsn.round8_20261031.value_calibration import finite
from tools.hcsn.round8_20261031.value_calibration.frozen import FrozenR7
from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead
from tools.hcsn.round8_20261031.value_calibration.run import checkpoint, digest, episode_run, metrics, write
from .head import CostFactoredHead, PreservedNominalHead, fit_continuation
from .protocol import MODES, SEEDS, contracts, record


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
EVIDENCE = HERE / "evidence"
OLD = REPO / "tools/hcsn/round8_20261031/value_calibration/evidence/prepared02"


def sources():
    paths = list(HERE.glob("*.py")) + list((OLD.parents[1]).glob("*.py"))
    paths += list((REPO / "experiments/analytic_event_neuron/round7").glob("*.py"))
    return {str(p.relative_to(REPO)): digest(p) for p in sorted(paths)}


def register():
    EVIDENCE.mkdir(exist_ok=False)
    write(EVIDENCE / "PROTOCOL.json", record())
    manifest = {"utc": datetime.now(timezone.utc).isoformat(), "sources": sources(),
        "protocol_sha256": digest(EVIDENCE / "PROTOCOL.json"),
        "r8_freeze_sha256": digest(OLD / "FREEZE.json"),
        "checkpoints": {str(checkpoint(m, s).relative_to(REPO)): digest(checkpoint(m, s)) for m in MODES for s in SEEDS},
        "baseline_heads": {f"{m}_{s}.json": digest(OLD / f"{m}_{s}.json") for m in MODES for s in SEEDS}}
    write(EVIDENCE / "REGISTERED.json", manifest)
    print(json.dumps({"registered_sha256": digest(EVIDENCE / "REGISTERED.json"), "holdout_evaluated": False}), flush=True)


def verify_registration():
    frozen = json.loads((EVIDENCE / "REGISTERED.json").read_text())
    amendment_path = EVIDENCE / "AMENDMENT.json"
    amendment = json.loads(amendment_path.read_text()) if amendment_path.exists() else None
    if amendment:
        assert amendment["registration_sha256"] == digest(EVIDENCE / "REGISTERED.json")
    assert (amendment["sources"] if amendment else frozen["sources"]) == sources(), "source changed after registration/amendment"
    assert frozen["protocol_sha256"] == digest(EVIDENCE / "PROTOCOL.json")
    assert frozen["r8_freeze_sha256"] == digest(OLD / "FREEZE.json")
    for name, sha in frozen["baseline_heads"].items():
        assert digest(OLD / name) == sha
    for name, sha in frozen["checkpoints"].items():
        assert digest(REPO / name) == sha
    return json.loads((EVIDENCE / "PROTOCOL.json").read_text())


def train():
    design = verify_registration()
    wall, cpu = time.perf_counter(), time.process_time()
    output = EVIDENCE / "heads"; output.mkdir(exist_ok=False)
    graph = finite.build_graph(contracts("training"))
    counts = Counter(s.parameters for s in graph["states"])
    weights = np.array([1 / (len(counts) * counts[s.parameters]) for s in graph["states"]])
    setup = time.process_time() - cpu
    rows = []
    for mode in MODES:
        for seed in SEEDS:
            start = time.process_time()
            model = FrozenR7(checkpoint(mode, seed))
            matrix, events = model.kernels(graph["x"])
            target, _ = finite.targets(graph, matrix, events)
            joined = model.inputs(graph["x"])
            head, metadata = fit_continuation(joined, target, graph["legal"], weights,
                seed + design["head_seed_offset"], hidden=design["hidden"],
                iterations=design["iteration_cap"], direct=mode == "direct")
            path = output / f"{mode}_{seed}.json"; head.save(path, metadata)
            after, _ = metrics(head.predict(joined, target[..., 3]), target, graph)
            inclusive = time.process_time() - start
            row = {"mode": mode, "seed": seed, "training": {k: v for k, v in metadata.items() if k != "curve"},
                "training_metrics": after, "inclusive_cpu_seconds": inclusive,
                "standalone_training_cpu_seconds": inclusive + setup, "head_sha256": digest(path)}
            rows.append(row); print(json.dumps(row), flush=True)
            write(EVIDENCE / "TRAIN_PROGRESS.json", {"fits": rows, "holdout_evaluated": False})
    write(EVIDENCE / "TRAIN.json", {"fits": rows, "public_states": len(graph["states"]), "setup_cpu_seconds": setup,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
        "holdout_evaluated": False})
    write(EVIDENCE / "HEADS_FROZEN.json", {"utc": datetime.now(timezone.utc).isoformat(),
        "registration_sha256": digest(EVIDENCE / "REGISTERED.json"), "train_sha256": digest(EVIDENCE / "TRAIN.json"),
        "heads": {p.name: digest(p) for p in sorted(output.glob("*.json"))}})


def independent_graph(configs, graph):
    other = finite.build_graph(configs, independent=True)
    alignment = np.array([other["ids"][s] for s in graph["states"]])
    maximum = 0.
    for (i, a), edges in graph["edges"].items():
        actual = other["edges"][alignment[i], a]
        law, ref = Counter(), Counter()
        for p, j, _ in edges:
            law[-1 if j < 0 else int(alignment[j])] += p
        for p, j, _ in actual:
            ref[j] += p
        maximum = max(maximum, abs(sum(p * r for p, _, r in edges) - sum(p * r for p, _, r in actual)),
                      max(abs(law[k] - ref[k]) for k in law.keys() | ref.keys()))
    assert maximum < 1e-12, maximum
    return other, alignment, maximum


def occupancy(graph, matrix, events, actions, target, initial_latent):
    """Forward probability flow using the independent task.step world law."""
    mass = np.zeros(matrix.shape[:2])
    for start in graph["starts"]:
        mass[start, initial_latent] += 1 / len(graph["starts"])
    result = dict(quality=0., task_cost=0., decisions=0., events=0., action_regret_sum=0.)
    for i in reversed(graph["order"]):
        incoming = mass[i]
        if not incoming.any():
            continue
        after = incoming @ matrix[i]
        result["decisions"] += float(incoming.sum())
        result["events"] += float(incoming @ events[i])
        result["action_regret_sum"] += float(after @ (target[i].max(-1) - target[i, np.arange(len(after)), actions[i]]))
        for a in np.flatnonzero(graph["legal"][i]):
            routed = after * (actions[i] == a)
            result["task_cost"] += float(routed.sum()) * graph["x"][i, 13 + a]
            if a == 3:
                result["quality"] += float(routed.sum()) * abs(2 * graph["x"][i, 0] - 1)
            for probability, j, _ in graph["edges"][i, a]:
                if j >= 0:
                    mass[j] += probability * routed
    result["utility"] = result["quality"] - result["task_cost"] - finite.COMPUTE * result["decisions"] - finite.EVENT * result["events"]
    result["correct"] = (1 + result["quality"]) / 2
    result["mean_action_regret_visited"] = result["action_regret_sum"] / result["decisions"]
    return result


def interval(values):
    values = np.asarray(values)
    mean = float(values.mean())
    half = float(t.ppf(1 - .05 / (2 * 3), 4) * values.std(ddof=1) / np.sqrt(5))
    return {"mean": mean, "lower": mean - half, "upper": mean + half}


def confirm():
    design = verify_registration()
    frozen = json.loads((EVIDENCE / "HEADS_FROZEN.json").read_text())
    assert frozen["registration_sha256"] == digest(EVIDENCE / "REGISTERED.json")
    assert frozen["train_sha256"] == digest(EVIDENCE / "TRAIN.json")
    for name, sha in frozen["heads"].items():
        assert digest(EVIDENCE / "heads" / name) == sha
    assert not (EVIDENCE / "CONFIRM_START.json").exists(), "confirmation is single-use"
    write(EVIDENCE / "CONFIRM_START.json", {"utc": datetime.now(timezone.utc).isoformat(),
        "heads_frozen_sha256": digest(EVIDENCE / "HEADS_FROZEN.json"),
        "amendment_sha256": digest(EVIDENCE / "AMENDMENT.json") if (EVIDENCE / "AMENDMENT.json").exists() else None})
    wall, cpu = time.perf_counter(), time.process_time()
    training = {(r["mode"], r["seed"]): r for r in json.loads((EVIDENCE / "TRAIN.json").read_text())["fits"]}
    graphs = {}
    for regime in design["regimes"]:
        graph = finite.build_graph(contracts(regime))
        graphs[regime] = (graph, *independent_graph(contracts(regime), graph))
    support = graphs["nominal"][0]["x"]
    records = []
    with gzip.open(EVIDENCE / "PAIRED.jsonl.gz", "wt", compresslevel=6) as stream:
        for mode in MODES:
            for seed in SEEDS:
                model = FrozenR7(checkpoint(mode, seed))
                old = CalibratedHead.load(OLD / f"{mode}_{seed}.json")
                new = CostFactoredHead.load(EVIDENCE / "heads" / f"{mode}_{seed}.json")
                routed = PreservedNominalHead(old, new, support)
                for r, regime in enumerate(design["regimes"]):
                    graph, independent, alignment, branch_error = graphs[regime]
                    matrix, events = model.kernels(graph["x"])
                    target, _ = finite.targets(graph, matrix, events)
                    joined = model.inputs(graph["x"])
                    exact = {}
                    for label, q in (("r7", model.old_q(graph["x"])), ("r8", old.predict(joined, target[..., 3])),
                                     ("new_unrouted", new.predict(joined, target[..., 3])), ("r9", routed.predict(joined, target[..., 3]))):
                        errors, actions = metrics(q, target, graph)
                        _, values = finite.targets(graph, matrix, events, actions)
                        inverse = np.argsort(alignment)
                        flow = occupancy(independent, matrix[inverse], events[inverse], actions[inverse], target[inverse], model.n // 2)
                        check = abs(flow["utility"] - values[graph["starts"], model.n // 2].mean())
                        assert check < 1e-11, (mode, seed, regime, label, check)
                        exact[label] = flow | errors | {"independent_value_error": float(check)}
                    paired = []
                    for c, config in enumerate(contracts(regime)):
                        for n in range(design["episodes_per_contract_fit"]):
                            key = design["episode_seed_start"] + (seed - 11) * 100000 + r * 10000 + c * 1000 + n
                            episode = finite.task.generate_episode(key, config)
                            runs = {}
                            for label in (("r8", "r9") if key % 2 else ("r9", "r8")):
                                run = episode_run(model, old if label == "r8" else routed, episode, key + design["latent_seed_offset"])
                                regret = 0.
                                for step in run["steps"]:
                                    assert not step["guard_fallback"]
                                    state = finite.canonical(finite.task.State.from_dict(step["state"]))
                                    qstar = target[graph["ids"][state], step["latent_after"]]
                                    regret += qstar.max() - qstar[finite.ACTIONS.index(step["action"])]
                                runs[label] = {k: v for k, v in run.items() if k != "steps"}
                                runs[label]["action_regret_sum"] = float(regret)
                            stream.write(json.dumps({"mode": mode, "seed": seed, "regime": regime, "contract": c,
                                "episode_seed": key, "runs": runs}, separators=(",", ":"), allow_nan=False) + "\n")
                            paired.append({k: runs["r9"][k] - runs["r8"][k] for k in runs["r8"]})
                    delta = {k: float(np.mean([row[k] for row in paired])) for k in paired[0]}
                    charged = training[mode, seed]["standalone_training_cpu_seconds"] / design["primary_gates"]["training_amortization_sessions"]
                    delta["cpu_priced_utility"] = delta["utility"] - delta["cpu_seconds"] - charged
                    item = {"mode": mode, "seed": seed, "regime": regime, "exact": exact, "paired_delta": delta,
                        "paired_episodes": len(paired), "independent_branch_max_error": branch_error,
                        "training_charge_per_session": charged}
                    records.append(item); print(json.dumps(item), flush=True)
                    write(EVIDENCE / "CONFIRM_PROGRESS.json", {"records": records})
    aggregate = []
    for mode in MODES:
        for regime in design["regimes"]:
            rows = [r for r in records if r["mode"] == mode and r["regime"] == regime]
            intervals = {k: interval([r["paired_delta"][k] for r in rows]) for k in rows[0]["paired_delta"]}
            exact_delta = {k: interval([r["exact"]["r9"][k] - r["exact"]["r8"][k] for r in rows])
                           for k in ("utility", "mean_action_regret_all_states", "mean_action_regret_visited", "correct", "events", "decisions")}
            gates = {"utility": intervals["utility"]["lower"] > 0,
                     "regret": exact_delta["mean_action_regret_all_states"]["upper"] < 0,
                     "quality": intervals["correct"]["lower"] >= -.02,
                     "cpu_priced": intervals["cpu_priced_utility"]["lower"] > 0}
            aggregate.append({"mode": mode, "regime": regime, "paired_intervals": intervals,
                "exact_delta_intervals": exact_delta, "gates": gates, "all_gates_pass": all(gates.values())})
    write(EVIDENCE / "RESULTS.json", {"records": records, "aggregate": aggregate,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
        "heads_frozen_sha256": digest(EVIDENCE / "HEADS_FROZEN.json"), "energy_measured": False,
        "raw_columns": "Seed and frozen files fully determine trajectory; compact raw retains all per-run returns, CPU, calls, events and regret, without private trajectory duplication."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("stage", choices=("register", "train", "confirm"))
    {"register": register, "train": train, "confirm": confirm}[parser.parse_args().stage]()
