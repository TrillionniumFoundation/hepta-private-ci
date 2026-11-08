"""Verify frozen CTRL-1 identities, selection evidence and original trajectories.

Hashes establish retained-file consistency, not an independent execution
attestation. Scientific promotion remains HOLD even after this audit passes.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from .evaluation import METRICS, paired_summary
from .learning import COST_UNIT, Learner, _sha, adoption_decision
from .model import (
    ACTIONS,
    Profile,
    Scenario,
    State,
    initial_state,
    legal_actions,
    transitions,
)
from .policies import Decision, after_compute
from .routing import Router, _sources as router_sources
from .run import BASE_COMMIT, CONTRACT_COMMIT, controller_for, digest, source_manifest

MAX_FILE_BYTES, MAX_LINE_BYTES = 512_000, 128_000
METHODS = {"actor_critic": "fitted_actor_critic", "distillation": "distilled"}
CONTROLLERS = {
    "fixed",
    "fast_actor_critic",
    "voi",
    "mpc",
    "mean_mpc",
    "hybrid",
    "distilled_candidate",
    "selected_fast",
    "learned_router",
}


def _decode(raw):
    def reject(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    def finite(value):
        number = float(value)
        return number if math.isfinite(number) else reject(value)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        raw, parse_constant=reject, parse_float=finite, object_pairs_hook=unique
    )


def load_json(path):
    if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("JSON artifact is a symlink or exceeds its size bound")
    with path.open("rb") as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("JSON artifact exceeds its bounded size")
    return _decode(content)


def _lines(path, cap, compressed=False):
    opener = gzip.open if compressed else open
    with opener(path, "rb") as handle:
        for index in range(cap + 1):
            raw = handle.readline(MAX_LINE_BYTES + 1)
            if not raw:
                return
            if index == cap or len(raw) > MAX_LINE_BYTES:
                raise ValueError("Original log exceeds its frozen count or line bound")
            yield _decode(raw)


def _number(value, lower=-math.inf, upper=math.inf):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not lower <= value <= upper
    ):
        raise ValueError("Invalid finite evidence number")
    return value


def _close(actual, expected):
    if not math.isclose(
        _number(actual), _number(expected), rel_tol=1e-10, abs_tol=1e-10
    ):
        raise ValueError("Derived evidence does not reconcile to its originals")


def _inventory(directory):
    manifest = load_json(directory / "ARTIFACTS.json")
    inventory = manifest["files"]
    paths = list(directory.rglob("*"))
    if len(paths) > 4096 or any(path.is_symlink() for path in paths):
        raise ValueError("Artifact symlinks or unbounded inventories are not accepted")
    actual = {str(path.relative_to(directory)) for path in paths if path.is_file()}
    if actual != set(inventory) | {"ARTIFACTS.json"}:
        raise ValueError("Artifact inventory is incomplete or has undeclared files")
    for relative, declared in inventory.items():
        part, path = Path(relative), directory / relative
        if (
            part.is_absolute()
            or ".." in part.parts
            or str(part) != relative
            or path.resolve() != path
        ):
            raise ValueError("Artifact path escapes its retained run")
        if (
            type(declared["bytes"]) is not int
            or not 0 <= declared["bytes"] <= MAX_FILE_BYTES
        ):
            raise ValueError("Invalid artifact size declaration")
        with path.open("rb") as handle:
            content = handle.read(MAX_FILE_BYTES + 1)
        if (
            len(content) != declared["bytes"]
            or hashlib.sha256(content).hexdigest() != declared["sha256"]
        ):
            raise ValueError(f"Artifact identity mismatch: {relative}")
    return manifest


def _scenario(record):
    values = {key: value for key, value in record.items() if key != "id"}
    for key in ("prior", "signal_accuracy", "repair_success"):
        value = Fraction(values[key])
        if str(value) != values[key]:
            raise ValueError("Noncanonical rational scenario probability")
        values[key] = value
    return Scenario(**values)


def _rosters(plan):
    profiles, scenarios, scenario_digests = {}, {}, set()
    for record in plan["profiles"]:
        profile = Profile(
            **{key: value for key, value in record.items() if key != "digest"}
        )
        identity = digest(asdict(profile))
        if record["digest"] != identity or identity in profiles:
            raise ValueError("Duplicate or mismatched profile digest")
        profiles[identity] = profile
    if not 1 <= len(profiles) <= 32 or set(plan["scenarios"]) != {
        "train",
        "development",
        "confirmation",
    }:
        raise ValueError("Invalid frozen profile or split roster")
    for split, records in plan["scenarios"].items():
        scenarios[split] = {}
        for record in records:
            scenario = _scenario(record)
            identity = digest(asdict(scenario))
            if (
                record["id"] != f"{split}-{identity[:16]}"
                or identity in scenario_digests
                or record["id"] in scenarios[split]
            ):
                raise ValueError(
                    "Scenario identity mismatch, duplicate, or cross-split leakage"
                )
            scenarios[split][record["id"]] = scenario
            scenario_digests.add(identity)
        if not 1 <= len(scenarios[split]) <= 64:
            raise ValueError("Invalid bounded scenario roster")
    seeds, controllers = plan["training_seeds"], plan["controller_roster"]
    if (
        not isinstance(seeds, list)
        or not 1 <= len(seeds) <= 32
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**64 for seed in seeds)
        or not controllers
        or len(set(controllers)) != len(controllers)
        or not set(controllers) <= CONTROLLERS
    ):
        raise ValueError("Duplicate or invalid seed/controller roster")
    if (
        type(plan["sampled_episodes_per_case"]) is not int
        or not 1 <= plan["sampled_episodes_per_case"] <= 1000
    ):
        raise ValueError("Invalid bounded sampled-episode denominator")
    return profiles, scenarios, seeds, controllers


def _result(row, scenario, profile):
    if row["evaluation"] != "exact_environment" or row["budget_violations"] != 0:
        raise ValueError("Invalid exact policy result")
    for key in (
        *METRICS,
        "value",
        "oracle_value",
        "policy_gap",
        "net_terminal_utility",
    ):
        _number(row[key])
    for key in METRICS:
        _number(row[key], 0)
    _number(row["terminal_payoff"], 0, 1 + 1e-10)
    _number(row["policy_gap"], -1e-10)
    _close(row["oracle_value"] - row["value"], row["policy_gap"])
    costs = row["environment_cost"] + row["controller_cost"]
    duration = row["environment_seconds"] + row["controller_seconds"]
    if costs > scenario.budget + 1e-10 or duration > scenario.deadline + 1e-10:
        raise ValueError("Expected charges exceed the frozen hard budget")
    _close(
        row["net_terminal_utility"],
        row["terminal_payoff"]
        - profile.resource_weight * costs
        - profile.latency_weight * duration,
    )
    if set(row["actions"]) != set(ACTIONS):
        raise ValueError("Unknown action metric")
    _close(
        sum(_number(count, 0) for count in row["actions"].values()),
        row["decision_calls"],
    )


def _sample(episode, scenario, controller):
    if episode["status"] != "Completed" or episode["budget_violations"] != 0:
        raise ValueError("A sampled original failed or violated budget")
    parts, state = episode["path"], initial_state(scenario)
    if not 1 <= len(parts) <= scenario.horizon + 1:
        raise ValueError("Invalid bounded original path")
    for step, part in enumerate(parts):
        if state is None or part["step"] != step or part["belief"] != str(state.belief):
            raise ValueError("Original path breaks its public-state sequence")
        for field in (
            "controller_cost",
            "controller_seconds",
            "environment_cost",
            "environment_seconds",
            "expanded_nodes",
        ):
            if type(part[field]) is not int or not 0 <= part[field] <= 512:
                raise ValueError("Invalid path resource or work charge")
        if type(part["fallback"]) is not bool:
            raise ValueError("Invalid fallback receipt")
        charge = controller.compute_charge(state)
        if (part["controller_cost"], part["controller_seconds"], part["route"]) != (
            charge.cost,
            charge.duration,
            charge.route,
        ):
            raise ValueError(
                "Original computation charge differs from the frozen controller"
            )
        admitted = after_compute(
            state, Decision(part["action"], charge.cost, charge.duration)
        )
        matches = [
            outcome
            for outcome in transitions(scenario, admitted, part["action"])
            if (
                outcome.duration,
                outcome.cost,
                outcome.observation,
                outcome.reward,
                str(outcome.probability),
            )
            == (
                part["environment_seconds"],
                part["environment_cost"],
                part["observation"],
                part["reward"],
                part["probability"],
            )
        ]
        if len(matches) != 1:
            raise ValueError(
                "Original observation does not belong to the frozen joint kernel"
            )
        if part["route"] == "emergency_stop" and (
            part["action"] != "stop" or part["expanded_nodes"]
        ):
            raise ValueError("An emergency terminal performed unsupported work")
        if part["route"] == "slow" and part["expanded_nodes"] > controller.node_limit:
            raise ValueError("Original planning exceeds its declared work cap")
        state = matches[0].next_state
    if state is not None:
        raise ValueError("Original path has no observed terminal outcome")
    environment = sum(part["environment_cost"] for part in parts)
    control = sum(part["controller_cost"] for part in parts)
    duration = sum(
        part["environment_seconds"] + part["controller_seconds"] for part in parts
    )
    if (
        environment != episode["environment_cost"]
        or control != episode["controller_cost"]
        or duration != episode["duration_seconds"]
        or environment + control > scenario.budget
        or duration > scenario.deadline
        or parts[-1]["reward"] != episode["terminal_payoff"]
    ):
        raise ValueError(
            "Original path does not reconcile to its result or hard budget"
        )


def _verify(directory, check_source):
    manifest = _inventory(directory)
    plan, report = (
        load_json(directory / "PLAN.json"),
        load_json(directory / "REPORT.json"),
    )
    if digest(plan) != report["plan_sha256"] or digest(plan) != manifest["plan_sha256"]:
        raise ValueError("Report or artifact manifest is bound to a different plan")
    if (
        plan["schema"] != "hepta.ctrl1.experiment.v1"
        or report["schema"] != "hepta.ctrl1.report.v1"
        or report["status"] != "COMPLETED_ENGINEERING_PILOT"
        or report["promotion"] != "HOLD"
        or report["production_authority"] != "none"
    ):
        raise ValueError("Invalid research evidence schema or promotion claim")
    if check_source and (
        plan["sources"] != source_manifest()
        or plan["base_commit"] != BASE_COMMIT
        or plan["contract_commit"] != CONTRACT_COMMIT
    ):
        raise ValueError(
            "Current source differs from the exact executed source manifest"
        )
    profiles, scenarios, seeds, controllers = _rosters(plan)
    runs = {
        f"{identity[:12]}-{seed}": (identity, seed)
        for identity in profiles
        for seed in seeds
    }
    if len(runs) != len(profiles) * len(seeds):
        raise ValueError("Run identifier collision")
    attempts = {}
    expected_phases, learners, checkpoint_ids, routers = {}, {}, {}, {}
    expected_training = {f"{run_id}-{method}" for run_id in runs for method in METHODS}
    checkpoints = list((directory / "checkpoints").glob("*.json"))
    if {path.stem for path in checkpoints} != expected_training or report[
        "training_runs"
    ] != len(expected_training):
        raise ValueError("Checkpoint identities differ from the training roster")
    router_paths = list((directory / "routers").glob("*.json"))
    if (
        {path.stem for path in router_paths} != set(runs)
        or report["router_training_runs"] != len(runs)
        or plan["expected_router_training_runs"] != len(runs)
    ):
        raise ValueError("Router training denominator differs from the frozen roster")
    for run_id, (identity, seed) in runs.items():
        public = load_json(directory / f"training-roster-{identity[:12]}.json")
        examples = []
        for item in public:
            scenario = _scenario(item["scenario"])
            values = dict(item["public_post_base_state"])
            values["belief"] = Fraction(values["belief"])
            state = State(**values)
            if scenario not in scenarios["train"].values():
                raise ValueError("Training roster contains a held-out scenario")
            legal_actions(scenario, state)
            examples.append((scenario, state))
        if not examples or len(set(examples)) != len(examples):
            raise ValueError("Empty or duplicated training examples")
        counts = Counter(scenario for scenario, _ in examples)
        if set(counts) != set(scenarios["train"].values()) or any(
            count > plan["examples_per_train_scenario"] for count in counts.values()
        ):
            raise ValueError(
                "Training examples do not cover their frozen source roster"
            )
        for method, method_name in METHODS.items():
            key = f"{run_id}-{method}"
            record = load_json(directory / "checkpoints" / f"{key}.json")
            learner = Learner.from_record(record)
            training = record["training"]
            expected_updates = plan["epochs"] * len(examples)
            if (
                learner.method != method_name
                or digest(asdict(learner.profile)) != identity
                or training["seed"] != seed
                or training["epochs"] != plan["epochs"]
                or training["examples"] != len(examples)
                or training["examples_sha256"] != _sha(examples)
                or training["completed_epochs"] != plan["epochs"]
                or training["actual_actor_updates"] != expected_updates
                or training["retained_actor_updates"] != expected_updates
                or training["counts"]["actor_updates"] != expected_updates
                or not training["teacher_complete"]
                or training["budget_stop_stage"] is not None
                or training["elapsed_cpu_seconds"]
                > plan["training_cpu_eligibility_ceiling_seconds_each"]
                or not training.get("candidate_available", True)
            ):
                raise ValueError(
                    "Checkpoint is not bound to its frozen training identity"
                )
            learners[(run_id, method)], checkpoint_ids[(run_id, method)] = (
                learner,
                record["checkpoint_sha256"],
            )
            expected_phases[key] = "training"
        pair = [learners[(run_id, method)].training for method in METHODS]
        if any(
            pair[0][key] != pair[1][key]
            for key in (
                "initial_parameters_sha256",
                "examples_sha256",
                "update_order_sha256",
                "retained_update_order_sha256",
            )
        ):
            raise ValueError("Claimed matched initial training conditions differ")
        measured = load_json(directory / f"training-{run_id}.json")
        if (
            len(measured) != len(METHODS)
            or {item["method"] for item in measured} != set(METHODS)
            or any(
                item["id"] != f"{run_id}-{item['method']}"
                or item["training"] != learners[(run_id, item["method"])].training
                for item in measured
            )
        ):
            raise ValueError("Training work receipts differ from checkpoint originals")
        record = load_json(directory / "routers" / f"{run_id}.json")
        router = Router.from_record(record)
        training = router.training
        fast = learners[(run_id, "actor_critic")].record()
        if (
            router.fast_checkpoint_sha256 != fast["checkpoint_sha256"]
            or router.fast_parameters_sha256 != fast["parameters_sha256"]
            or digest(asdict(router.profile)) != identity
            or training["seed"] != seed
            or training["epochs"] != plan["epochs"]
            or training["examples"] != len(examples)
            or training["updates"] != plan["epochs"] * len(examples)
            or training["examples_sha256"] != _sha(examples)
            or training["sources"]
            != {
                path: plan["sources"].get(path, {}).get("sha256")
                for path in router_sources()
            }
            or len(training["pairs"]) != len(examples)
        ):
            raise ValueError(
                "Router is not bound to its frozen source, roster and fast policy"
            )
        for index, (pair, (scenario, state)) in enumerate(
            zip(training["pairs"], examples)
        ):
            if (
                pair["example"] != index
                or pair["scenario_sha256"] != _sha(scenario)
                or pair["state_sha256"] != _sha(state)
                or pair["source_sha256"] != training["source_sha256"]
            ):
                raise ValueError(
                    "Router's downstream-value label has a different input identity"
                )
            _close(pair["delta"], pair["one_slow_value"] - pair["fast_value"])
        routers[run_id], expected_phases[f"{run_id}-router_train"] = (
            router,
            "router_training",
        )
    selections = {selection["id"]: selection for selection in report["selections"]}
    if len(selections) != len(report["selections"]) or set(selections) != set(runs):
        raise ValueError("Selection denominator differs from profile/seed roster")
    development_count = 0
    for run_id, (identity, _) in runs.items():
        raw = load_json(directory / f"development-{run_id}.json")
        indexed = {}
        for row in raw:
            key = (row["scenario_id"], row["method"])
            wanted = f"{run_id}-{key[0]}-{key[1]}"
            if (
                key in indexed
                or key[0] not in scenarios["development"]
                or key[1] not in METHODS
            ):
                raise ValueError("Duplicate or held-out development evidence")
            if (
                row["id"] != wanted
                or row["profile_id"] != identity
                or row["checkpoint_sha256"] != checkpoint_ids[(run_id, key[1])]
            ):
                raise ValueError(
                    "Development result has the wrong checkpoint or identity"
                )
            _result(row, scenarios["development"][key[0]], profiles[identity])
            indexed[key], expected_phases[wanted] = row, "development"
        if set(indexed) != {
            (scenario, method)
            for scenario in scenarios["development"]
            for method in METHODS
        }:
            raise ValueError("Original development denominator is incomplete")
        evidence = []
        for method in METHODS:
            ordered = [
                indexed[(scenario, method)] for scenario in scenarios["development"]
            ]
            evidence.append(
                {
                    "scenario_ids": list(scenarios["development"]),
                    "values": [row["value"] for row in ordered],
                    "costs": [row["controller_cost"] for row in ordered],
                    "budget_violations": 0,
                    "profile_sha256": identity,
                    "cost_unit": COST_UNIT,
                    "evaluation": "exact_environment",
                }
            )
        decision = adoption_decision(*evidence, split="development")
        wanted = {
            "id": run_id,
            **decision,
            "baseline": evidence[0],
            "candidate": evidence[1],
            "baseline_checkpoint_sha256": checkpoint_ids[(run_id, "actor_critic")],
            "candidate_checkpoint_sha256": checkpoint_ids[(run_id, "distillation")],
            "selected_checkpoint_sha256": checkpoint_ids[
                (
                    run_id,
                    "distillation"
                    if decision["decision"] == "Candidate"
                    else "actor_critic",
                )
            ],
        }
        if selections[run_id] != wanted:
            raise ValueError(
                "Selection is not the recomputed development-only decision"
            )
        development_count += len(raw)
    if development_count != plan["expected_development_rows"]:
        raise ValueError("Development denominator differs from the frozen plan")
    rows, row_controllers = {}, {}
    for run_id, (identity, seed) in runs.items():
        fast, distilled = (learners[(run_id, method)] for method in METHODS)
        selected = distilled if selections[run_id]["decision"] == "Candidate" else fast
        for row in _lines(
            directory / f"results-{run_id}.jsonl",
            len(scenarios["confirmation"]) * len(controllers),
        ):
            key = f"{run_id}-{row['scenario_id']}-{row['controller']}"
            if (
                row["id"] != key
                or key in rows
                or row["profile_id"] != identity
                or row["training_seed"] != seed
                or row["controller"] not in controllers
                or row["scenario_id"] not in scenarios["confirmation"]
            ):
                raise ValueError("Duplicate or mismatched comparison identity")
            scenario = scenarios["confirmation"][row["scenario_id"]]
            controller = controller_for(
                row["controller"],
                profiles[identity],
                fast,
                distilled,
                selected,
                scenario,
                routers[run_id],
            )
            checkpoint = (
                None
                if controller.learner is None
                else controller.learner.record()["checkpoint_sha256"]
            )
            if (
                row["checkpoint_sha256"] != checkpoint
                or row["variable_time"] != scenario.variable_time
                or row["outcome_correlation"] != scenario.outcome_correlation
            ):
                raise ValueError(
                    "Comparison used a different selected checkpoint or scenario"
                )
            expected_router = (
                routers[run_id].record()["checkpoint_sha256"]
                if row["controller"] == "learned_router"
                else None
            )
            if row["router_checkpoint_sha256"] != expected_router:
                raise ValueError("Comparison used a different routing checkpoint")
            _result(row, scenario, profiles[identity])
            rows[key], row_controllers[key], expected_phases[key] = (
                row,
                controller,
                "confirmation",
            )
    expected_cases = {
        f"{run_id}-{scenario}-{controller}"
        for run_id in runs
        for scenario in scenarios["confirmation"]
        for controller in controllers
    }
    if (
        set(rows) != expected_cases
        or len(rows) != report["comparisons"]
        or len(rows) != plan["expected_comparison_rows"]
    ):
        raise ValueError("Comparison denominator differs from the frozen roster")
    for position, event in enumerate(
        _lines(directory / "attempts.jsonl", 2 * len(expected_phases))
    ):
        key = event["id"]
        if key not in expected_phases or event["phase"] != expected_phases[key]:
            raise ValueError("Unknown attempt identity or phase")
        attempts.setdefault(key, []).append((position, event))
    if set(attempts) != set(expected_phases) or any(
        [item[1]["status"] for item in events] != ["Started", "Completed"]
        for events in attempts.values()
    ):
        raise ValueError(
            "An attempt is missing, retried, failed, or lacks a terminal result"
        )
    for run_id in runs:
        stages = {
            phase: [
                events
                for key, events in attempts.items()
                if key.startswith(run_id + "-") and expected_phases[key] == phase
            ]
            for phase in ("training", "router_training", "development", "confirmation")
        }
        phases = list(stages)
        if any(
            max(events[-1][0] for events in stages[first])
            >= min(events[0][0] for events in stages[second])
            for first, second in zip(phases, phases[1:])
        ):
            raise ValueError(
                "Attempt order violates training/development/confirmation isolation"
            )
        for method in METHODS:
            completed = attempts[f"{run_id}-{method}"][-1][1]
            record = learners[(run_id, method)].record()
            if (
                completed["checkpoint_sha256"] != record["checkpoint_sha256"]
                or completed["parameters_sha256"] != record["parameters_sha256"]
            ):
                raise ValueError(
                    "Training completion is bound to a different checkpoint"
                )
        completed, record = (
            attempts[f"{run_id}-router_train"][-1][1],
            routers[run_id].record(),
        )
        if (
            completed["checkpoint_sha256"] != record["checkpoint_sha256"]
            or completed["parameters_sha256"] != record["parameters_sha256"]
        ):
            raise ValueError("Router completion is bound to a different checkpoint")
    episode_ids, samples = set(), {key: [] for key in rows}
    for run_id, (_, seed) in runs.items():
        cap = (
            len(scenarios["confirmation"])
            * len(controllers)
            * plan["sampled_episodes_per_case"]
        )
        for episode in _lines(
            directory / f"rollouts-{run_id}.jsonl.gz", cap, compressed=True
        ):
            key = (episode["case_id"], episode["seed"])
            if (
                key[0] not in rows
                or not key[0].startswith(run_id + "-")
                or key in episode_ids
                or episode["seed"]
                not in range(
                    seed * 1000, seed * 1000 + plan["sampled_episodes_per_case"]
                )
            ):
                raise ValueError("Unknown or duplicate original sampled episode")
            row = rows[key[0]]
            _sample(
                episode,
                scenarios["confirmation"][row["scenario_id"]],
                row_controllers[key[0]],
            )
            episode_ids.add(key)
            samples[key[0]].append(episode)
    for key, originals in samples.items():
        receipt = rows[key]["sampled_execution"]
        if (
            len(originals) != plan["sampled_episodes_per_case"]
            or receipt["episodes"] != len(originals)
            or receipt["budget_violations"] != 0
        ):
            raise ValueError("Sampled originals do not cover the frozen denominator")
        _close(
            receipt["mean_terminal_payoff"],
            statistics.mean(item["terminal_payoff"] for item in originals),
        )
        _close(
            receipt["controller_meter"]["calls"],
            sum(len(item["path"]) for item in originals),
        )
    if (
        len(episode_ids) != report["sampled_episodes"]
        or report["independent_training_seeds"] != len(seeds)
        or report["exact_budget_violations"] != 0
        or report["sampled_budget_violations"] != 0
    ):
        raise ValueError(
            "Report denominators or violation totals differ from originals"
        )
    if report["paired_descriptive"] != paired_summary(list(rows.values())):
        raise ValueError("Paired report differs from the complete comparison roster")
    grouped = {}
    for row in rows.values():
        grouped.setdefault((row["profile_id"], row["controller"]), []).append(row)
    summary = [
        {
            "profile_id": key[0],
            "controller": key[1],
            "cases": len(values),
            **{
                metric: statistics.mean(value[metric] for value in values)
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
    if report["summary"] != summary:
        raise ValueError("Report summary differs from original comparison rows")
    return {
        "verified": True,
        "files": len(manifest["files"]),
        "comparisons": len(rows),
        "development_originals": development_count,
        "training_runs": len(checkpoints),
        "router_training_runs": len(routers),
        "sampled_originals": len(episode_ids),
        "attempt_identities": len(attempts),
        "plan_sha256": digest(plan),
        "source_checked": check_source,
        "scientific_promotion": "HOLD",
    }


def verify(directory, check_source=True):
    try:
        return _verify(Path(directory).resolve(strict=True), check_source)
    except (KeyError, TypeError, IndexError, OverflowError, OSError) as error:
        raise ValueError(f"Malformed or missing original evidence: {error}") from error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--historical-source",
        action="store_true",
        help="Audit artifacts without claiming current-source execution",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.directory, check_source=not args.historical_source),
            sort_keys=True,
        )
    )
