#!/usr/bin/env python3
"""Explicit original-model rounds with the existing owned-exit observer.

The original round and parent-step owners retain training, controls, evaluation,
budgets, completion and unqualified hold decisions. No installation is issued.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_smollm_three_rounds_v2 as rounds

PROFILE = "hepta-original-model-observed-execution-v1"
CHAIN_COMMIT = "ad490ed4b1132a333159fd76702809fd248a4462"
ASSESSMENT = "hepta-controlled-real-round-assessment-observed-v1"
LOOP = "hepta-controlled-public-initial-three-round-loop-observed-v1"
ROLES = (
    "candidate",
    "current-backbone",
    "fresh-budget-matched-lora",
    "budget-matched-full-tune",
    "randomized-rank-matched-lora",
)


def validate_request(args):
    rounds.require(
        args.observation_profile == PROFILE
        and getattr(args, "research_profile", None) is None
        and getattr(args, "proposal_parent", None) is None
        and args.round in (1, 2, 3),
        "explicit original-parent observation request required",
    )


def validate_loop_context(loop):
    """Accept only the explicitly versioned observation loop at the research gate."""
    rounds.require(
        loop["schema"] == LOOP and loop["execution_profile"] == PROFILE,
        "exact observation loop namespace required",
    )
    for result in loop["rounds"]:
        context = result["observation_execution"]
        rounds.require(
            result["schema"] == ASSESSMENT
            and result["execution_profile"] == PROFILE
            and result["model_plan_profile"] == "strict-v1"
            and context["profile"]
            == "canonical-parent-original-task-observed-execution-v1",
            "original model plan and explicit observer round required",
        )
        rounds.require(
            [phase["name"] for phase in result["phases"]]
            == [prefix + role for prefix in ("train-", "evaluate-") for role in ROLES],
            "all original five train and five evaluation phases required",
        )
        for phase in result["phases"]:
            policy = phase["exit_observation_profile"]
            policy_id = hashlib.sha256(
                json.dumps(
                    policy,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            expected_budget = (
                dict(wall_seconds=1800, rss_bytes=16 * 1024**3)
                if phase["name"].startswith("train-")
                else dict(wall_seconds=600, rss_bytes=8 * 1024**3)
            )
            rounds.require(
                policy["profile"] == "linux-owned-exit-worker-pidfd-v4"
                and policy["maximum_drain_ns"] == 100000000
                and policy_id == context["observer"]
                and phase["terminal_reconciliation_profile"]
                == "explicit-linux-owned-exit-worker-pidfd-v4"
                and phase["outcome"] == "success"
                and type(phase["exit_code"]) is int
                and phase["exit_code"] == 0
                and phase["stop_reason"] is None
                and phase["budget"] == expected_budget
                and phase["waited_child_reaped"] is True
                and phase["owned_child_reap_resolved"] is True
                and phase["owned_child_echild_observed"] is False
                and phase["waited_child_observation_error"] is None,
                "exact original budget and owned completion for every observed phase required",
            )


def freeze_plan(args, runtime, parent_step, parent, plan_path):
    import llm_initial_trainable_setup_v2 as setup
    import llm_runtime_observed_execution_v1 as observed

    value = dict(
        files=dict(plan=str(plan_path)),
        parent={key: parent[key] for key in ("contract", "adapter", "file_sha256")},
        source=parent_step.sources(observed.PROFILE),
        initial_setup=dict(
            recipe=dict(setup.RECIPE),
            parent_material=dict(path=str(args.parent), sha256=args.parent_sha256),
        ),
    )
    path = args.output / "observation-plan-v1.json"
    runtime.save(path, observed.plan_record(value))
    value["initial_setup"]["observation_plan"] = dict(
        path=str(path), sha256=runtime.file_sha(path)
    )
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("chain", "materials", "parent", "output", "ordinary-readback"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--parent-sha256", required=True)
    parser.add_argument("--round", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    rounds.require(
        all(
            getattr(args, name).is_absolute()
            for name in ("chain", "materials", "parent", "output", "ordinary_readback")
        ),
        "absolute original paths required",
    )
    rounds.require(
        os.environ.get("HEPTA_PUBLIC_INITIAL_EXECUTION_PROFILE") == PROFILE,
        "observed execution requires explicit owner profile",
    )
    original = subprocess.check_output(
        ["git", "-C", str(args.chain), "rev-parse", "HEAD"], text=True
    ).strip()
    rounds.require(
        original == rounds.CHAIN_COMMIT,
        "original native material source must be unchanged",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(args.chain),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "formal",
            "config",
        ],
        check=True,
    )
    args.chain = Path(os.environ["HEPTA_PUBLIC_INITIAL_OBSERVATION_CHAIN"])
    rounds.require(
        args.chain.is_absolute(), "absolute exact observation checkout required"
    )
    args.observation_profile = PROFILE
    rounds.run(args)


if __name__ == "__main__":
    main()
