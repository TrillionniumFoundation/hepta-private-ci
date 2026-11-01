"""Reproducible development assay on the recovered v3 renewal model.

The new AV confirmation remains blocked. These new worlds test two mechanisms
and learned substitutes in a declared synthetic, perfect-sensor task only.
"""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT if (ROOT / "experiments/hcsn_mechanism_content_v2/renewal.py").is_file() else ROOT / "recovered/v3"
sys.path.insert(0, str(LEGACY))

import numpy as np
import torch

from experiments.hcsn_mechanism_content_v2 import mechanism as legacy
from experiments.hcsn_causal_execution_v3.mechanism_followup import rollout
from .count_interventions import IntervenedRenewal
from .recurrent_counts import fit_models, load_core


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def sources():
    here = Path(__file__).parent
    paths = [here / name for name in ("campaign.py", "count_interventions.py", "recurrent_counts.py")]
    result = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    paths = [LEGACY / "experiments" / name for name in (
        "hcsn_mechanism_content_v2/renewal.py", "hcsn_mechanism_content_v2/mechanism.py",
        "hcsn_causal_execution_v3/mechanism_followup.py")]
    result.update({"legacy/" + str(p.relative_to(LEGACY)): sha(p) for p in paths})
    return result


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hcsn-v8-reachable-mechanism-development.v1", "created_unix": time.time(),
        "source_sha256": sources(), "fit_seeds": [81101, 81103, 81107, 81109, 81113],
        "training": {"train_size": 8192, "validation_size": 1024, "epochs": 80},
        "conditions": ["matched", "hidden_refractory_mismatch"], "episodes_per_condition": 24,
        "world_seed_namespace": [20261101, 83019], "config": asdict(legacy.Config()),
        "ordinary_families": ["gru", "ssm"],
        "ordinary_selection": "Per fit, choose lower sampled-count validation NLL; retain both families",
        "analytic_fitting": "Inherited common 512-sample physical calibration; no learned analytic parameters",
        "interventions": ["mean_two_point", "single_transition"],
        "paired_modes": ["own closed loop", "original analytic task-value actions fixed"],
        "replacement_scope": "Newly fitted ordinary count propagators; same physical packet and count labels",
        "recurrence_scope": "Four internal forecast-time nodes, not persistent AV observation memory",
        "risk_intervention": "Not tested: inherited task has no external deadline service-risk term",
        "primary_questions": ["reachable multiple-event mass", "count-shape vs count-mean effect",
                              "action vs fixed-action content effect", "retrained ordinary replacement"],
        "evidence_role": "development_only_known_renewal_model",
        "real_AV_confirmation": False, "v6_recovered": False, "architecture_acceptance": False,
        "limitations": ["perfect sensor", "known renewal-law prior", "finite task",
                        "legacy one-planned-read heuristic", "no calibrated-v7 common-head controller",
                        "CPU shared host", "no physical device energy", "no new real recording"],
        "cost_rule": "Enclosing fresh workers charged once; internal arm timers are nested diagnostics",
        "python": sys.executable, "torch": torch.__version__, "threads": 1,
    }
    write(output / "PLAN.json", plan)
    print(json.dumps({"plan": str(output / "PLAN.json"), "sha256": sha(output / "PLAN.json")}))


def read_plan(output):
    plan = json.loads((output / "PLAN.json").read_text())
    current = sources()
    if plan["source_sha256"] != current:
        raise RuntimeError("Development source changed after plan freeze")
    return plan


def fit(output, seed):
    plan = read_plan(output)
    if seed not in plan["fit_seeds"]:
        raise ValueError("Unregistered fit seed")
    dest = output / f"fit_{seed}"
    dest.mkdir(exist_ok=False)
    models, reports, data, generation_cpu = fit_models(seed, **plan["training"])
    torch.save(models, dest / "models.pt")
    np.savez_compressed(dest / "sampled_data.npz", **data)
    selected = min(plan["ordinary_families"], key=lambda family: (reports[family]["validation_nll"], family))
    write(dest / "FIT.json", {"reports": reports, "selected_family": selected,
          "data_generation_cpu_seconds": generation_cpu, "models_sha256": sha(dest / "models.pt"),
          "sampled_data_sha256": sha(dest / "sampled_data.npz")})
    print(json.dumps({"seed": seed, "selected": selected,
                      "validation_nll": {f: r["validation_nll"] for f, r in reports.items()}}), flush=True)


def evaluate(output):
    plan = read_plan(output)
    selected, models, identities = {}, {}, {}
    for seed in plan["fit_seeds"]:
        p = output / f"fit_{seed}"
        report = json.loads((p / "FIT.json").read_text())
        if sha(p / "models.pt") != report["models_sha256"]:
            raise ValueError("Fitted checkpoint changed")
        selected[str(seed)] = report["selected_family"]
        identities[str(seed)] = report["models_sha256"]
        checkpoint = torch.load(p / "models.pt", map_location="cpu", weights_only=False)
        models[seed] = {f: load_core(checkpoint, f) for f in plan["ordinary_families"]}
    dest = output / "evaluation"
    dest.mkdir(exist_ok=False)
    write(dest / "FROZEN_INPUTS.json", {"plan_sha256": sha(output / "PLAN.json"),
          "models": identities, "selected": selected, "before_world_generation": True})
    count = 0
    with gzip.open(dest / "worlds.jsonl.gz", "xt") as worlds, gzip.open(dest / "runs.jsonl.gz", "xt") as records:
        for condition_index, condition in enumerate(plan["conditions"]):
            config = legacy.Config(**{**plan["config"], "condition": condition})
            for index in range(plan["episodes_per_condition"]):
                seed = int(np.random.SeedSequence(plan["world_seed_namespace"] + [condition_index, index]).generate_state(1)[0])
                episode = legacy.make_episode(seed, config)
                worlds.write(json.dumps({"condition": condition, "index": index, "episode": episode}) + "\n")
                reference = rollout(IntervenedRenewal(), "task_value", episode, config)
                schedule = {r["tick"]: r["executed_action"] for r in reference["trace"]}

                def emit(name, run, fit_seed=None, family=None):
                    nonlocal count
                    records.write(json.dumps({"condition": condition, "index": index, "world_seed": seed,
                        "arm": name, "fit_seed": fit_seed, "family": family, **run}, allow_nan=False) + "\n")
                    count += 1

                emit("D", reference)
                emit("C", rollout(IntervenedRenewal(), "lightweight", episode, config))
                for intervention in plan["interventions"]:
                    emit(intervention + "_closed", rollout(IntervenedRenewal(intervention), "task_value", episode, config))
                    emit(intervention + "_fixed_D", rollout(IntervenedRenewal(intervention), "fixed_action_replay",
                                                          episode, config, forced=schedule))
                for fit_seed in plan["fit_seeds"]:
                    for family in plan["ordinary_families"]:
                        core = models[fit_seed][family]
                        for arm, controller in (("A", "lightweight"), ("B", "task_value")):
                            emit(arm, rollout(core, controller, episode, config), fit_seed, family)
                        emit("ordinary_fixed_D", rollout(core, "fixed_action_replay", episode, config,
                                                        forced=schedule), fit_seed, family)
                records.flush()
                print(json.dumps({"condition": condition, "completed_worlds": index + 1, "runs": count}), flush=True)
    write(dest / "COMPLETE.json", {"runs": count, "worlds": len(plan["conditions"]) * plan["episodes_per_condition"],
          "raw_sha256": sha(dest / "runs.jsonl.gz"), "worlds_sha256": sha(dest / "worlds.jsonl.gz"),
          "science_role": plan["evidence_role"], "real_AV_confirmation": False})


def action_map(run):
    return {row["tick"]: row["executed_action"] for row in run["trace"]}


def aggregate(output):
    plan = read_plan(output)
    with gzip.open(output / "evaluation/runs.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    indexed = {(r["condition"], r["index"], r["arm"], r["fit_seed"], r["family"]): r for r in rows}
    selected = json.loads((output / "evaluation/FROZEN_INPUTS.json").read_text())["selected"]
    report = {"scope": plan["evidence_role"], "real_AV_confirmation": False,
              "architecture_acceptance": False, "conditions": {}, "fits": selected}
    for condition in plan["conditions"]:
        details, effects = {}, {}
        for name in ("mean_two_point", "single_transition"):
            total = {"action_changed_worlds": 0, "fixed_action_predicted_class_changes": 0,
                     "fixed_action_distribution_changes": 0, "fixed_actions_identical": True,
                     "paired_worlds": plan["episodes_per_condition"]}
            diffs = {"closed_net_reward": [], "fixed_net_reward": [], "fixed_brier": []}
            for index in range(plan["episodes_per_condition"]):
                d = indexed[(condition, index, "D", None, None)]
                closed = indexed[(condition, index, name + "_closed", None, None)]
                fixed = indexed[(condition, index, name + "_fixed_D", None, None)]
                total["action_changed_worlds"] += int(action_map(d) != action_map(closed))
                total["fixed_actions_identical"] &= action_map(d) == action_map(fixed)
                for a, b in zip(d["predictions"], fixed["predictions"]):
                    total["fixed_action_predicted_class_changes"] += int(np.argmax(a["probabilities"]) != np.argmax(b["probabilities"]))
                    total["fixed_action_distribution_changes"] += int(not np.allclose(a["probabilities"], b["probabilities"], atol=1e-12, rtol=0))
                for key, lhs, field in (("closed_net_reward", closed, "net_reward"),
                                        ("fixed_net_reward", fixed, "net_reward"), ("fixed_brier", fixed, "brier")):
                    diffs[key].append(lhs["summary"][field] - d["summary"][field])
            effects[name] = {**total, "intervention_minus_original_means": {k: float(np.mean(v)) for k, v in diffs.items()},
                             "paired_differences": diffs}
        support = []
        for index in range(plan["episodes_per_condition"]):
            for p in indexed[(condition, index, "D", None, None)]["predictions"]:
                if p["observed_state"]["has_read"]:
                    support.append(sum(p["count_probabilities"][2:]))
        for fit_seed in plan["fit_seeds"]:
            family_results = {}
            for family in plan["ordinary_families"]:
                means = {arm: float(np.mean([indexed[(condition, i, arm, fit_seed if arm in ("A", "B", "ordinary_fixed_D") else None,
                            family if arm in ("A", "B", "ordinary_fixed_D") else None)]["summary"]["net_reward"]
                            for i in range(plan["episodes_per_condition"])]))
                         for arm in ("A", "B", "C", "D", "ordinary_fixed_D")}
                family_results[family] = {**means, "B-A": means["B"]-means["A"], "D-C": means["D"]-means["C"],
                    "C-A": means["C"]-means["A"], "D-B": means["D"]-means["B"],
                    "interaction": (means["D"]-means["C"])-(means["B"]-means["A"])}
            details[str(fit_seed)] = family_results
        chosen = [details[str(s)][selected[str(s)]] for s in plan["fit_seeds"]]
        report["conditions"][condition] = {"mechanism_effects": effects, "all_fit_results": details,
            "validation_selected_ordinary_mean_contrasts": {k: float(np.mean([x[k] for x in chosen])) for k in chosen[0]},
            "reachable_support": {"post_READ_output_states": len(support),
                "multiple_event_probability_mean": float(np.mean(support)) if support else None,
                "multiple_event_probability_max": max(support, default=None),
                "states_with_multi_probability_over_01": sum(x > .01 for x in support)}}
    write(output / "SUMMARY.json", report)
    print(json.dumps({c: r["validation_selected_ordinary_mean_contrasts"] for c, r in report["conditions"].items()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "fit", "evaluate", "aggregate"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if args.command == "prepare":
        prepare(args.output)
    elif args.command == "fit":
        fit(args.output, args.seed)
    elif args.command == "evaluate":
        evaluate(args.output)
    else:
        aggregate(args.output)


if __name__ == "__main__":
    main()
