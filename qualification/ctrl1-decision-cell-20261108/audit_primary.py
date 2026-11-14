"""Replay preserved CTRL-1 primary results with the exact frozen implementation.

Usage: python3 qualification/ctrl1-decision-cell-20261108/audit_primary.py RUN_DIR
Redirect stdout outside RUN_DIR, whose exact inventory must stay unchanged.
This independent replay invocation is not external evaluator attestation. It
does not retrain, tune, change selection rules, or grant promotion authority.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# Standalone imports require the repository path bootstrap above.
from ndu_ctrl1.evaluation import evaluate, sample_episode  # noqa: E402
from ndu_ctrl1.learning import COST_UNIT, Learner, adoption_decision  # noqa: E402
from ndu_ctrl1.model import legal_actions, transitions  # noqa: E402
from ndu_ctrl1.policies import Controller  # noqa: E402
from ndu_ctrl1.routing import Router  # noqa: E402
from ndu_ctrl1.run import controller_for, digest, source_manifest  # noqa: E402
from ndu_ctrl1.verify import _inventory, _lines, _rosters, load_json, verify  # noqa: E402

MAX_ROWS, MAX_DEVELOPMENT, MAX_RUNS, MAX_EPISODES = 864, 96, 12, 13_824
TIMINGS = {"wall_ns", "cpu_ns"}
METHODS = ("actor_critic", "distillation")


def deterministic(value):
    """Keep every field except the measured clocks inside evaluation receipts."""
    if isinstance(value, dict):
        return {
            key: deterministic(item)
            for key, item in value.items()
            if key not in TIMINGS
        }
    if isinstance(value, list):
        return [deterministic(item) for item in value]
    return value


def compare(actual, expected, label, report):
    """Bound diagnostic output, while counting every observed mismatch."""
    if (
        isinstance(expected, dict)
        and isinstance(actual, dict)
        and set(actual) == set(expected)
    ):
        for key in expected:
            compare(actual[key], expected[key], f"{label}.{key}", report)
        return
    if (
        isinstance(expected, list)
        and isinstance(actual, list)
        and len(actual) == len(expected)
    ):
        for index, (left, right) in enumerate(zip(actual, expected)):
            compare(left, right, f"{label}[{index}]", report)
        return
    if type(expected) is float:
        equal = (
            type(actual) in (int, float)
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
        )
    else:
        equal = type(actual) is type(expected) and actual == expected
    if not equal:
        report["mismatch_count"] += 1
        if len(report["mismatches"]) < 20:
            report["mismatches"].append(
                {
                    "field": label,
                    "original": repr(actual)[:240],
                    "replayed": repr(expected)[:240],
                }
            )


def replay_row(original, scenario, profile, controller, report, phase):
    fresh = evaluate(scenario, profile, controller)
    before = report["mismatch_count"]
    compare(
        deterministic({key: original.get(key) for key in fresh}),
        deterministic(fresh),
        original["id"],
        report,
    )
    if phase == "development":
        compare(
            deterministic(original["controller_meter"]),
            deterministic(controller.counters),
            f"{original['id']}.controller_meter",
            report,
        )
    report[f"{phase}_rows_replayed"] += 1
    report[f"{phase}_rows_verified"] += int(report["mismatch_count"] == before)
    return fresh


def audit(directory, replay_trajectories=True):
    auditor_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = {
        "schema": "hepta.ctrl1.primary-replay-audit.v1",
        "verified": False,
        "scope": "independent replay invocation using frozen code; not external evaluator attestation",
        "excluded": [
            "measured wall/CPU timings",
            "training reproduction",
            "external task outcomes",
        ],
        "promotion": "HOLD",
        "production_authority": "none",
        "auditor_sha256": auditor_hash,
        "source_manifest_sha256": None,
        "plan_sha256": None,
        "artifact_manifest_sha256": None,
        "strict_source_inventory_verified": False,
        "learners_reconstructed": 0,
        "routers_reconstructed": 0,
        "selections_verified": 0,
        "development_rows_replayed": 0,
        "development_rows_verified": 0,
        "confirmation_rows_replayed": 0,
        "confirmation_rows_verified": 0,
        "sampled_episodes_replayed": 0,
        "sampled_episodes_verified": 0,
        "trajectories_requested": replay_trajectories,
        "mismatch_count": 0,
        "mismatches": [],
        "errors": [],
    }
    stage = "bounded preflight"
    try:
        directory = Path(directory).resolve(strict=True)
        plan = load_json(directory / "PLAN.json")
        profiles, scenarios, seeds, controllers = _rosters(plan)
        runs = len(profiles) * len(seeds)
        expected = runs * len(scenarios["confirmation"]) * len(controllers)
        development = runs * len(scenarios["development"]) * len(METHODS)
        episodes = expected * plan["sampled_episodes_per_case"]
        if not (
            1 <= runs <= MAX_RUNS
            and 1 <= expected <= MAX_ROWS
            and 1 <= development <= MAX_DEVELOPMENT
            and 1 <= episodes <= MAX_EPISODES
        ):
            raise ValueError("Replay exceeds the bounded primary campaign dimensions")
        stage = "strict source/inventory verification"
        verified = verify(directory, check_source=True)
        report.update(
            {
                "strict_source_inventory_verified": True,
                "source_manifest_sha256": digest(plan["sources"]),
                "plan_sha256": digest(plan),
                "artifact_manifest_sha256": hashlib.sha256(
                    (directory / "ARTIFACTS.json").read_bytes()
                ).hexdigest(),
                "expected_confirmation_rows": expected,
                "expected_development_rows": development,
                "expected_sampled_episodes": episodes,
                "originals_verified": verified,
            }
        )
        selections = {
            item["id"]: item
            for item in load_json(directory / "REPORT.json")["selections"]
        }
        for profile_id, profile in profiles.items():
            for seed in seeds:
                run_id = f"{profile_id[:12]}-{seed}"
                stage = f"reconstruct {run_id}"
                records = [
                    load_json(directory / "checkpoints" / f"{run_id}-{method}.json")
                    for method in METHODS
                ]
                fast, distilled = [Learner.from_record(record) for record in records]
                router = Router.from_record(
                    load_json(directory / "routers" / f"{run_id}.json")
                )
                report["learners_reconstructed"] += 2
                report["routers_reconstructed"] += 1
                original_dev = {
                    (row["scenario_id"], row["method"]): row
                    for row in load_json(directory / f"development-{run_id}.json")
                }
                evidence = []
                for method, learner in zip(METHODS, (fast, distilled)):
                    values = []
                    for scenario_id, scenario in scenarios["development"].items():
                        original = original_dev[(scenario_id, method)]
                        stage = original["id"]
                        values.append(
                            replay_row(
                                original,
                                scenario,
                                profile,
                                Controller("fast", profile, learner),
                                report,
                                "development",
                            )
                        )
                    evidence.append(
                        {
                            "scenario_ids": list(scenarios["development"]),
                            "values": [row["value"] for row in values],
                            "costs": [row["controller_cost"] for row in values],
                            "budget_violations": int(
                                any(row["budget_violations"] for row in values)
                            ),
                            "profile_sha256": profile_id,
                            "cost_unit": COST_UNIT,
                            "evaluation": "exact_environment",
                        }
                    )
                decision = adoption_decision(*evidence, split="development")
                chosen = int(decision["decision"] == "Candidate")
                selection = {
                    "id": run_id,
                    **decision,
                    "baseline": evidence[0],
                    "candidate": evidence[1],
                    "baseline_checkpoint_sha256": records[0]["checkpoint_sha256"],
                    "candidate_checkpoint_sha256": records[1]["checkpoint_sha256"],
                    "selected_checkpoint_sha256": records[chosen]["checkpoint_sha256"],
                }
                before = report["mismatch_count"]
                compare(selections[run_id], selection, f"selection.{run_id}", report)
                report["selections_verified"] += int(before == report["mismatch_count"])
                selected = (fast, distilled)[chosen]
                originals = {}
                cap = len(scenarios["confirmation"]) * len(controllers)
                if replay_trajectories:
                    for episode in _lines(
                        directory / f"rollouts-{run_id}.jsonl.gz",
                        cap * plan["sampled_episodes_per_case"],
                        compressed=True,
                    ):
                        originals.setdefault(episode["case_id"], {})[
                            episode["seed"]
                        ] = episode
                for original in _lines(directory / f"results-{run_id}.jsonl", cap):
                    stage = original["id"]
                    scenario = scenarios["confirmation"][original["scenario_id"]]
                    arguments = (
                        original["controller"],
                        profile,
                        fast,
                        distilled,
                        selected,
                        scenario,
                        router,
                    )
                    replay_row(
                        original,
                        scenario,
                        profile,
                        controller_for(*arguments),
                        report,
                        "confirmation",
                    )
                    if not replay_trajectories:
                        continue
                    transitions.cache_clear()
                    legal_actions.cache_clear()
                    controller, payoffs = controller_for(*arguments), []
                    for sample_seed in range(
                        seed * 1000, seed * 1000 + plan["sampled_episodes_per_case"]
                    ):
                        fresh = sample_episode(
                            scenario, profile, controller, sample_seed
                        )
                        episode = originals[original["id"]][sample_seed]
                        before = report["mismatch_count"]
                        compare(
                            deterministic(episode),
                            {"case_id": original["id"], **deterministic(fresh)},
                            f"{original['id']}.episode[{sample_seed}]",
                            report,
                        )
                        report["sampled_episodes_replayed"] += 1
                        report["sampled_episodes_verified"] += int(
                            before == report["mismatch_count"]
                        )
                        payoffs.append(fresh["terminal_payoff"])
                    compare(
                        deterministic(
                            original["sampled_execution"]["controller_meter"]
                        ),
                        deterministic(controller.counters),
                        f"{original['id']}.sampled_controller_meter",
                        report,
                    )
                    compare(
                        original["sampled_execution"]["mean_terminal_payoff"],
                        math.fsum(payoffs) / len(payoffs),
                        f"{original['id']}.sampled_mean_payoff",
                        report,
                    )
        stage = "final source/inventory reconciliation"
        _inventory(directory)
        if (
            source_manifest() != plan["sources"]
            or hashlib.sha256((directory / "ARTIFACTS.json").read_bytes()).hexdigest()
            != report["artifact_manifest_sha256"]
            or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != auditor_hash
        ):
            raise ValueError(
                "Sources, auditor, or retained inventory changed during replay"
            )
        if (
            report["confirmation_rows_replayed"] != expected
            or report["development_rows_replayed"] != development
            or replay_trajectories
            and report["sampled_episodes_replayed"] != episodes
        ):
            raise ValueError("Replay denominator is incomplete")
        report["verified"] = report["mismatch_count"] == 0
    except Exception as error:
        report["errors"].append(
            {"stage": stage, "type": type(error).__name__, "message": str(error)[:500]}
        )
    report["rows_verified"] = report["confirmation_rows_verified"]
    report["status"] = (
        "PASSED_PRIMARY_REPLAY" if report["verified"] else "FAILED_PRIMARY_REPLAY"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--skip-trajectories",
        action="store_true",
        help="Replay exact rows and development selection only",
    )
    args = parser.parse_args()
    result = audit(args.directory, replay_trajectories=not args.skip_trajectories)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    sys.exit(0 if result["verified"] else 1)
