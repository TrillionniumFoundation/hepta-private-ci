"""Run the frozen CTRL-1 engineering pilot and retain all original attempts.

Usage: PYTHONPATH=scripts python3 -m ndu_ctrl1.run --output <absent-directory>
The source-bound plan is written before training. No test outcome selects a
checkpoint, adjusts a threshold, or authorizes a production update.
"""

import argparse
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import gzip
import json
from pathlib import Path
import random
import statistics
import platform
import sys
import time

from .evaluation import evaluate, paired_summary, sample_episode
from .learning import (
    Learner,
    TeacherLabel,
    adoption_decision,
    train_actor_critic,
    train_distilled,
)
from .model import Profile, Scenario, initial_state, legal_actions, transitions
from .oracle import Oracle
from .policies import Controller, Decision, after_compute
from .routing import Router, RoutedController, train_router

BASE_COMMIT = "9c6c18cec8c56260d633de5a6adf321de2a4e3d4"
CONTRACT_COMMIT = "732e934ba496d90fbe042b8d41d479ef901643e5"
SEEDS = (17, 23, 41)
EPOCHS, EXAMPLES_PER_SCENARIO, EPISODES = 32, 32, 16
TRAINING_CPU_LIMIT = 60.0
ROSTER = (
    "fixed",
    "fast_actor_critic",
    "voi",
    "mpc",
    "mean_mpc",
    "hybrid",
    "learned_router",
    "distilled_candidate",
    "selected_fast",
)


def serial(value):
    if isinstance(value, Fraction):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def encode(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=serial, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(encode(value) + b"\n")


def scenarios(split):
    priors = {
        "train": (Fraction(1, 4), Fraction(3, 4)),
        "development": (Fraction(3, 8), Fraction(5, 8)),
        "confirmation": (Fraction(1, 3), Fraction(2, 3)),
    }[split]
    accuracy = {
        "train": Fraction(3, 4),
        "development": Fraction(2, 3),
        "confirmation": Fraction(4, 5),
    }[split]
    correlations = (-1, 1) if split == "confirmation" else (1,)
    result = []
    for prior in priors:
        for variable in (False, True):
            for correlation in correlations:
                scenario = Scenario(
                    prior=prior,
                    deadline=8,
                    budget=10,
                    horizon=3,
                    variable_time=variable,
                    signal_accuracy=accuracy,
                    repair_success=Fraction(1, 2)
                    if split != "confirmation"
                    else Fraction(2, 3),
                    outcome_correlation=correlation,
                )
                result.append((f"{split}-{digest(asdict(scenario))[:16]}", scenario))
    return result


def profiles():
    return [
        Profile(
            risk=risk,
            latency_weight=0.01 if priced else 0.0,
            resource_weight=0.02 if priced else 0.0,
        )
        for risk in (0.0, 0.25)
        for priced in (False, True)
    ]


def source_manifest():
    root = Path(__file__).resolve().parents[2]
    paths = sorted(Path(__file__).parent.glob("*.py"))
    paths += [
        root / "scripts/ndu_real_runtime/objective.py",
        root / "scripts/ndu_real_runtime/finite_entropic_golden.json",
    ]
    return {
        str(path.relative_to(root)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in paths
    }


def examples_for_training(profile):
    examples, costs = [], []
    for scenario_id, scenario in scenarios("train"):
        wall, cpu = time.perf_counter(), time.process_time()
        oracle = Oracle(scenario, profile)
        oracle.value(initial_state(scenario))
        # Only the public reachable state roster is shared, never oracle Q or
        # policy labels. The known transition model is equally available.
        states = sorted(
            oracle.states,
            key=lambda s: (
                -s.steps_left,
                str(s.belief),
                s.time_left,
                s.budget_left,
                s.used_mask,
            ),
        )
        public = sorted(
            {
                after_compute(s, Decision("stop", 1, 0))
                if s.budget_left and s.steps_left
                else s
                for s in states
            },
            key=lambda s: (
                -s.steps_left,
                str(s.belief),
                s.time_left,
                s.budget_left,
                s.used_mask,
            ),
        )
        random.Random(108).shuffle(public)
        initial = after_compute(initial_state(scenario), Decision("stop", 1, 0))
        selected = [initial] + [s for s in public if s != initial][
            : EXAMPLES_PER_SCENARIO - 1
        ]
        examples.extend((scenario, s) for s in selected)
        costs.append(
            {
                "scenario_id": scenario_id,
                "public_states": len(public),
                "selected": len(selected),
                "oracle_stats": oracle.stats,
                "wall_seconds": time.perf_counter() - wall,
                "cpu_seconds": time.process_time() - cpu,
            }
        )
    return examples, costs


class Teacher:
    def __init__(self, profile):
        self.controller = Controller("mpc", profile)

    def __call__(self, scenario, state):
        if (
            not state.steps_left
            or not state.budget_left
            or legal_actions(scenario, state) == ("stop",)
        ):
            return TeacherLabel("stop", 0, 0)
        # Learner inputs are post-base-charge. Restore that one credit before
        # invoking the actual slow teacher so it is charged exactly once.
        before = (
            replace(state, budget_left=state.budget_left + 1)
            if (state.steps_left and state.budget_left < scenario.budget)
            else state
        )
        decision = self.controller.choose(scenario, before)
        return TeacherLabel(
            decision.action, decision.forecast_calls, decision.expanded_nodes
        )


def dev_evidence(profile, learner, run_id, method, attempt):
    rows = []
    for scenario_id, scenario in scenarios("development"):
        key = f"{run_id}-{scenario_id}-{method}"
        attempt(key, "development", "Started")
        controller = Controller("fast", profile, learner)
        row = {
            "id": key,
            "scenario_id": scenario_id,
            "method": method,
            "profile_id": digest(asdict(profile)),
            "checkpoint_sha256": learner.record()["checkpoint_sha256"],
            **evaluate(scenario, profile, controller),
            "controller_meter": dict(controller.counters),
        }
        rows.append(row)
        attempt(key, "development", "Completed")
    return {
        "scenario_ids": [row["scenario_id"] for row in rows],
        "values": [row["value"] for row in rows],
        "costs": [row["controller_cost"] for row in rows],
        "budget_violations": 0
        if all(row["budget_violations"] == 0 for row in rows)
        else 1,
        "profile_sha256": digest(asdict(profile)),
        "cost_unit": "ctrl1.simulated_resource_credit.v1",
        "evaluation": "exact_environment",
    }, rows


def controller_for(
    name, profile, fast, distilled, selected, scenario=None, router=None
):
    if name == "learned_router":
        return RoutedController(scenario, profile, fast, router)
    if name == "fast_actor_critic":
        return Controller("fast", profile, fast)
    if name == "distilled_candidate":
        return Controller("fast", profile, distilled)
    if name == "selected_fast":
        return Controller("fast", profile, selected)
    return Controller(name, profile, fast if name == "hybrid" else None)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    sources = source_manifest()
    profile_roster = [(digest(asdict(p)), p) for p in profiles()]
    plan = {
        "schema": "hepta.ctrl1.experiment.v1",
        "base_commit": BASE_COMMIT,
        "contract_commit": CONTRACT_COMMIT,
        "sources": sources,
        "runtime": {
            "python": sys.version,
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "profiles": [{"digest": key, **asdict(p)} for key, p in profile_roster],
        "scenarios": {
            split: [{"id": key, **asdict(s)} for key, s in scenarios(split)]
            for split in ("train", "development", "confirmation")
        },
        "training_seeds": SEEDS,
        "epochs": EPOCHS,
        "examples_per_train_scenario": EXAMPLES_PER_SCENARIO,
        "training_cpu_eligibility_ceiling_seconds_each": TRAINING_CPU_LIMIT,
        "controller_roster": ROSTER,
        "sampled_episodes_per_case": EPISODES,
        "expected_comparison_rows": len(profile_roster)
        * len(SEEDS)
        * len(scenarios("confirmation"))
        * len(ROSTER),
        "expected_development_rows": len(profile_roster)
        * len(SEEDS)
        * len(scenarios("development"))
        * 2,
        "expected_router_training_runs": len(profile_roster) * len(SEEDS),
        "known_model_information": "identical full public joint kernel; no sampled latent bit",
        "training_match": "same examples, initial actor, seeds, update order, actor-update allowance; teacher/critic costs separate",
        "planning_price": "base 1 credit; slow fixed nonrefundable ceil(96/32) extra credits and 1 simulated second",
        "cost_ablation": "zero explicit latency/resource weights; hard budgets and temporal discount remain active",
        "adoption": "development only; strictly positive mean NDU gain and no extra expected controller credits",
        "confirmation_access": "held-out synthetic parameter scenarios; no post-result tuning",
        "scope": "engineering pilot; finite exact search with FP64 CE; not real-task confirmation",
    }
    write_json(output / "PLAN.json", plan)
    attempt_file = (output / "attempts.jsonl").open("xb")
    rows, selections, training_records, router_records = [], [], [], []

    def attempt(key, phase, status, **extra):
        attempt_file.write(
            encode({"id": key, "phase": phase, "status": status, **extra}) + b"\n"
        )
        attempt_file.flush()

    try:
        for profile_id, profile in profile_roster:
            examples, roster_costs = examples_for_training(profile)
            write_json(
                output / f"training-roster-{profile_id[:12]}.json",
                [
                    {"scenario": asdict(s), "public_post_base_state": asdict(state)}
                    for s, state in examples
                ],
            )
            for seed in SEEDS:
                run_id = f"{profile_id[:12]}-{seed}"
                learners, learner_ids = [], []
                for method in ("actor_critic", "distillation"):
                    key = f"{run_id}-{method}"
                    attempt(key, "training", "Started")
                    attempt_wall, attempt_cpu = time.perf_counter(), time.process_time()
                    transitions.cache_clear()
                    legal_actions.cache_clear()
                    teacher = Teacher(profile)
                    model = (
                        train_actor_critic(examples, profile, seed, EPOCHS)
                        if method == "actor_critic"
                        else train_distilled(examples, teacher, profile, seed, EPOCHS)
                    )
                    record = model.record()
                    if record["training"]["elapsed_cpu_seconds"] > TRAINING_CPU_LIMIT:
                        write_json(
                            output / "checkpoints" / f"{key}-over-budget.json", record
                        )
                        raise RuntimeError(
                            "Training CPU allowance exceeded; candidate ineligible"
                        )
                    write_json(output / "checkpoints" / f"{key}.json", record)
                    learners.append(Learner.from_record(record))
                    learner_ids.append(record["checkpoint_sha256"])
                    attempt(
                        key,
                        "training",
                        "Completed",
                        parameters_sha256=record["parameters_sha256"],
                        checkpoint_sha256=record["checkpoint_sha256"],
                        elapsed_wall_seconds=time.perf_counter() - attempt_wall,
                        elapsed_cpu_seconds=time.process_time() - attempt_cpu,
                    )
                    training_records.append(
                        {
                            "id": key,
                            "method": method,
                            "training": record["training"],
                            "shared_roster_costs": roster_costs,
                            "teacher_meter": teacher.controller.counters
                            if method == "distillation"
                            else None,
                        }
                    )
                fast, distilled = learners
                router_key = f"{run_id}-router_train"
                attempt(router_key, "router_training", "Started")
                router = train_router(examples, profile, fast, seed=seed, epochs=EPOCHS)
                router_record = router.record()
                write_json(output / "routers" / f"{run_id}.json", router_record)
                router = Router.from_record(router_record)
                router_records.append(router_record["checkpoint_sha256"])
                attempt(
                    router_key,
                    "router_training",
                    "Completed",
                    checkpoint_sha256=router_record["checkpoint_sha256"],
                    parameters_sha256=router_record["parameters_sha256"],
                )
                baseline, baseline_rows = dev_evidence(
                    profile, fast, run_id, "actor_critic", attempt
                )
                candidate, candidate_rows = dev_evidence(
                    profile, distilled, run_id, "distillation", attempt
                )
                write_json(
                    output / f"development-{run_id}.json",
                    baseline_rows + candidate_rows,
                )
                selection = adoption_decision(baseline, candidate, split="development")
                selected = distilled if selection["decision"] == "Candidate" else fast
                selected_id = (
                    learner_ids[1]
                    if selection["decision"] == "Candidate"
                    else learner_ids[0]
                )
                selections.append(
                    {
                        "id": run_id,
                        **selection,
                        "baseline": baseline,
                        "candidate": candidate,
                        "baseline_checkpoint_sha256": learner_ids[0],
                        "candidate_checkpoint_sha256": learner_ids[1],
                        "selected_checkpoint_sha256": selected_id,
                    }
                )
                with (
                    (output / f"results-{run_id}.jsonl").open("xb") as result_file,
                    (output / f"rollouts-{run_id}.jsonl.gz").open("xb") as raw_file,
                    gzip.GzipFile(
                        filename="", mode="wb", fileobj=raw_file, mtime=0
                    ) as rollout_file,
                ):
                    for scenario_id, scenario in scenarios("confirmation"):
                        for name in ROSTER:
                            key = f"{run_id}-{scenario_id}-{name}"
                            attempt(key, "confirmation", "Started")
                            ctrl = controller_for(
                                name,
                                profile,
                                fast,
                                distilled,
                                selected,
                                scenario,
                                router,
                            )
                            row = {
                                "id": key,
                                "profile_id": profile_id,
                                "scenario_id": scenario_id,
                                "training_seed": seed,
                                "controller": name,
                                "checkpoint_sha256": (
                                    learner_ids[0]
                                    if name
                                    in ("fast_actor_critic", "hybrid", "learned_router")
                                    else learner_ids[1]
                                    if name == "distilled_candidate"
                                    else selected_id
                                    if name == "selected_fast"
                                    else None
                                ),
                                "router_checkpoint_sha256": router_record[
                                    "checkpoint_sha256"
                                ]
                                if name == "learned_router"
                                else None,
                                "variable_time": scenario.variable_time,
                                "outcome_correlation": scenario.outcome_correlation,
                                **evaluate(scenario, profile, ctrl),
                            }
                            transitions.cache_clear()
                            legal_actions.cache_clear()
                            ctrl = controller_for(
                                name,
                                profile,
                                fast,
                                distilled,
                                selected,
                                scenario,
                                router,
                            )
                            samples = [
                                sample_episode(scenario, profile, ctrl, seed * 1000 + n)
                                for n in range(EPISODES)
                            ]
                            row["sampled_execution"] = {
                                "episodes": len(samples),
                                "budget_violations": sum(
                                    s["budget_violations"] for s in samples
                                ),
                                "mean_terminal_payoff": statistics.mean(
                                    s["terminal_payoff"] for s in samples
                                ),
                                "controller_meter": ctrl.counters,
                                "cache_condition": "cold once per controller/scenario batch; subsequent episodes reuse bounded caches",
                            }
                            for sample in samples:
                                rollout_file.write(
                                    encode({"case_id": key, **sample}) + b"\n"
                                )
                            result_file.write(encode(row) + b"\n")
                            rows.append(row)
                            attempt(key, "confirmation", "Completed")
                write_json(output / f"training-{run_id}.json", training_records[-2:])
                print(
                    json.dumps(
                        {
                            "completed": run_id,
                            "comparisons": len(rows),
                            "selection": selection["decision"],
                        }
                    ),
                    flush=True,
                )
        grouped = {}
        for row in rows:
            grouped.setdefault((row["profile_id"], row["controller"]), []).append(row)
        summary = [
            {
                "profile_id": key[0],
                "controller": key[1],
                "cases": len(values),
                **{
                    metric: statistics.mean(v[metric] for v in values)
                    for metric in (
                        "value",
                        "policy_gap",
                        "net_terminal_utility",
                        "controller_cost",
                        "stop_regret",
                        "compute_and_stop_regret",
                        "continuation_regret",
                        "expanded_nodes",
                    )
                },
            }
            for key, values in sorted(grouped.items())
        ]
        report = {
            "schema": "hepta.ctrl1.report.v1",
            "plan_sha256": digest(plan),
            "status": "COMPLETED_ENGINEERING_PILOT",
            "comparisons": len(rows),
            "sampled_episodes": len(rows) * EPISODES,
            "training_runs": len(training_records),
            "router_training_runs": len(router_records),
            "independent_training_seeds": len(SEEDS),
            "summary": summary,
            "paired_descriptive": paired_summary(rows),
            "selections": selections,
            "exact_budget_violations": sum(r["budget_violations"] for r in rows),
            "sampled_budget_violations": sum(
                r["sampled_execution"]["budget_violations"] for r in rows
            ),
            "promotion": "HOLD",
            "production_authority": "none",
            "remaining": [
                "matched consumed total physical cost",
                "independent external outcome evaluator",
                "real document/tool/GUI tasks",
                "native owner adoption integration",
            ],
            "measurement": "modeled credits/seconds separate from measured wall/CPU; energy/money unknown; nested timers not additive",
        }
        if len(rows) != plan["expected_comparison_rows"]:
            raise AssertionError("The frozen comparison roster is incomplete")
        if sources != source_manifest():
            raise RuntimeError(
                "Source changed during execution; refusing a completion receipt"
            )
        write_json(output / "REPORT.json", report)
    except Exception as error:
        attempt(
            "campaign",
            "execution",
            "Failed",
            error_type=type(error).__name__,
            message=str(error),
        )
        raise
    finally:
        attempt_file.close()
    files = {
        str(path.relative_to(output)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    write_json(output / "ARTIFACTS.json", {"plan_sha256": digest(plan), "files": files})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "comparisons", "sampled_episodes", "promotion")
            }
        )
    )
