"""Frozen nine-case engineering pilot and strictly offline human-reference scoring.

The public VizWiz training sources are six pilot-training and three development
cases. They are not independent confirmation clusters, five task families, or a
retention panel. Human answers are read only by this offline scorer, never by
the action controller, public encoder, or learned planning model.
"""

from dataclasses import asdict
import json
from pathlib import Path
import time

from .real_predictor import Opportunity, digest
from .real_execution import _sha


MANIFEST_SHA = "bfdc06b75f8c0f1fbefd2aa1c868dcf214dbc093554e21a067d470a7dfe1add0"
HISTORY_SHA = "7247a0d306aee50204e9c15cc5daa841191fd5ea8f520cbe8159474f04af39e5"
CASE_IDS = tuple(f"vizwiz:VizWiz_train_{i:08d}.jpg" for i in range(9))
SCHEDULES = (("text", "stop"), ("perceive", "text", "stop"))
STRATEGIES = ("initial", "light", "ndu", "tuned_fixed", "voi", "mpc")
SUCCESS = "candidate_complete_pending_native_owner"


def code_binding():
    from ndu_semantic_state import materials, source_pool, state

    root = Path(__file__).parent
    result = {
        p.name: _sha(p)
        for p in sorted(root.glob("*.py"))
        if p.name.startswith(("real_", "pilot_"))
    }
    result.update(
        {
            module.__name__: _sha(module.__file__)
            for module in (materials, source_pool, state)
        }
    )
    return result


def load_pool(root):
    from ndu_semantic_state.source_pool import admit_candidate_pool

    root = Path(root)
    if _sha(root / "CANDIDATES.json") != MANIFEST_SHA:
        raise ValueError("This pilot requires the frozen nine-case candidate pool")
    admission = admit_candidate_pool(
        root, "CANDIDATES.json", "HISTORY.json", expected_history_sha256=HISTORY_SHA
    )
    cases = json.loads((root / "CANDIDATES.json").read_text())["cases"]
    if tuple(c["id"] for c in cases) != CASE_IDS or any(
        c["project_split"] != ("development" if i < 3 else "train")
        for i, c in enumerate(cases)
    ):
        raise ValueError("Frozen train/development membership changed")
    return cases, admission


def make_plan(source_sha, profile):
    """Register explicit numerical/cost settings before collection or grading."""
    fields = {
        "device",
        "dtype",
        "threads",
        "cpu_tariff",
        "wall_tariff",
        "cost_weight",
        "episode_wall_seconds",
        "episode_cost",
        "phase_wall_seconds",
    }
    if (
        set(profile) != fields
        or len(source_sha) != 40
        or any(c not in "0123456789abcdef" for c in source_sha)
    ):
        raise ValueError("Explicit source and complete numerical/cost profile required")
    if (
        profile["device"] not in ("cpu", "cuda:0")
        or profile["dtype"] not in ("float16", "bfloat16", "float32")
        or (profile["device"] == "cpu" and profile["dtype"] == "float16")
        or type(profile["threads"]) is not int
        or not 1 <= profile["threads"] <= 16
    ):
        raise ValueError("Unsupported explicit engineering device/dtype profile")
    for key in fields - {"device", "dtype", "threads"}:
        value = profile[key]
        if type(value) not in (int, float) or not 0 <= value < float("inf"):
            raise ValueError(
                "Finite nonnegative registered costs and ceilings required"
            )
    if (
        profile["cpu_tariff"] + profile["wall_tariff"] <= 0
        or not 0
        < profile["episode_wall_seconds"]
        <= profile["phase_wall_seconds"]
        <= 7200
        or profile["episode_cost"] <= 0
    ):
        raise ValueError("Positive bounded physical opportunities required")
    return {
        "schema": "hepta.real-controller-pilot.v1",
        "source_sha": source_sha,
        "code_sha256": code_binding(),
        "manifest_sha256": MANIFEST_SHA,
        "history_sha256": HISTORY_SHA,
        "case_ids": list(CASE_IDS),
        "claim_status": "HOLD",
        "scope": "public_training_source_engineering_pilot",
        "profile": dict(profile),
        "gamma": 2.0,
        "discount": 1.0,
        "failure_score": 0.0,
        "allowed_actions": ["perceive", "text", "stop"],
        "horizon": 4,
        "schedules": [list(s) for s in SCHEDULES],
        "strategies": list(STRATEGIES),
        "fit_seeds": [17, 29, 43],
        "cores": ["ordinary", "hepta"],
        "regimes": ["frozen", "joint"],
        "predictor": {"width": 16, "members": 2, "gamma": 2.0},
        "opportunity": asdict(Opportunity(200000, 64, 32, 2, 120, 10000)),
        "counts": {
            "collection_episodes": 18,
            "physical_fits": 12,
            "development_policy_episodes": 216,
        },
        "collection_features": "train_only; development_fixed_trials_pay_no_unused_encoder_cost",
        "cache_policy": "common_resident_vlm; setup_inclusive_in_phase_and_worker_budget; amortization_unregistered",
        "tuning": "two_development_fixed_schedules_shared_by_all_policies; no_heldout_claim",
        "evaluation": "human_consensus_casefold_whitespace.v1; text_only; offline",
        "independent_cluster_count": None,
        "task_families_verified": [],
        "retention_verified": False,
        "native_owner_verified": False,
        "generator_joint_training": False,
        "unknown_costs": [
            "energy",
            "accelerator_charge",
            "prior_acquisition",
            "native_owner_operations",
        ],
    }


def read_plan(path, expected_sha256):
    if _sha(path) != expected_sha256:
        raise ValueError("Pilot plan differs from its external pin")
    plan = json.loads(Path(path).read_text())
    if plan != make_plan(plan["source_sha"], plan["profile"]):
        raise ValueError("Plan/code/roster changed since registration")
    return plan


def bound_file(root, item, limit=16 * 1024**2):
    from ndu_semantic_state.materials import check_file

    return check_file(root, item, limit=limit)


def score_episode(pool, case, episode_dir, expected_episode_sha256):
    """Grade actual immutable text artifacts after execution; no learned evaluator."""
    from ndu_semantic_state.source_pool import score_vizwiz_reference

    start = time.process_time(), time.perf_counter()
    episode_dir = Path(episode_dir)
    if _sha(episode_dir / "episode.json") != expected_episode_sha256:
        raise ValueError("Execution trace differs from its separately pinned index")
    report = json.loads((episode_dir / "episode.json").read_text())
    if (
        report["binding"]["task_id"] != case["id"]
        or report["binding"]["source_group"] != case["source_group_id"]
        or report["binding"]["episode_group"] != case["episode_group_id"]
    ):
        raise ValueError("Scorer source binding differs from the executed public case")
    reference = json.loads(bound_file(pool, case["reference"]))

    def grade(item):
        if item is None:
            return {
                "score": 0.0,
                "reason": "no_current_text",
                "delivery_text_sha256": None,
            }
        binding = {key: item[key] for key in ("path", "sha256", "bytes")}
        text = bound_file(episode_dir, binding).decode("utf-8")
        return score_vizwiz_reference(reference, text)

    prefixes = [
        grade(row["current_artifacts"].get("text")) for row in report["observations"]
    ]
    selected = next((x for x in report["selected"] if x["kind"] == "text"), None)
    terminal = (
        grade(selected)
        if report["status"] == SUCCESS
        else {
            "score": 0.0,
            "reason": "execution_not_complete",
            "execution_status": report["status"],
        }
    )
    result = {
        "episode_sha256": expected_episode_sha256,
        "reference_sha256": case["reference"]["sha256"],
        "prefixes": prefixes,
        "terminal": terminal,
        "claim_status": "HOLD",
        "independent_domain_evaluator_verified": False,
        "image_quality": None,
        "cpu_seconds": time.process_time() - start[0],
        "wall_seconds": time.perf_counter() - start[1],
        "unknown_costs": ["energy", "outer_process_and_final_write"],
    }
    return report, result


def training_rows(case, report, grade):
    if case["project_split"] != "train" or report["status"] != SUCCESS:
        raise ValueError(
            "Only completed registered training-source trajectories can fit"
        )
    observations = report["observations"]
    if not report["feature_collection_only"] or any(
        not row["suitable_for_predictive_fitting"] for row in observations
    ):
        raise ValueError("Actual public encoder features required")
    rows = []
    for i, (before, after) in enumerate(zip(observations, observations[1:])):
        if (
            after["step"] != before["step"] + 1
            or before["encoding_digest"] != after["encoding_digest"]
        ):
            raise ValueError(
                "Transition is not a contiguous same-encoder physical step"
            )
        start, stop = before["event_cursor"], after["event_cursor"]
        events = report["events"][start:stop]
        action = report["history"][before["step"]]
        if (
            not events
            or start >= stop
            or not any(
                e["action"] == action and e["status"] == "completed" for e in events
            )
        ):
            raise ValueError("Missing actual transition execution and full event costs")
        rows.append(
            {
                "split": "train",
                "source_group": case["source_group_id"],
                "episode_group": case["episode_group_id"],
                "observation": before["public"],
                "next_observation": after["public"],
                "action": action,
                "utility": grade["prefixes"][i]["score"],
                "next_utility": grade["prefixes"][i + 1]["score"],
                "cost": sum(e["cost"] for e in events),
                "seconds": sum(e["wall_seconds"] for e in events),
                "execution_receipt": digest(
                    {"episode": grade["episode_sha256"], "events": events}
                ),
                "evaluator_receipt": digest(
                    {"evaluation": grade, "prefix_pair": [i, i + 1]}
                ),
                "encoding_digest": before["encoding_digest"],
            }
        )
    if not rows:
        raise ValueError("No actual transitions collected")
    return rows


def tune_fixed(plan, collection, scores):
    """Finite, recorded development selection; all candidates remain in the ledger."""
    import math

    candidates = []
    for index in range(len(SCHEDULES)):
        values, evidence = [], []
        for case_id in CASE_IDS[:3]:
            entry = next(
                e
                for e in collection["episodes"]
                if e["case_id"] == case_id and e["schedule_index"] == index
            )
            grade = scores[entry["key"]]
            if entry["status"] != SUCCESS:
                raise ValueError(
                    "Incomplete fixed-policy trial roster cannot supply tuning"
                )
            values.append(
                grade["terminal"]["score"]
                - plan["profile"]["cost_weight"] * entry["total_cost"]
            )
            evidence.append(
                {"execution": entry["episode_sha256"], "evaluation": digest(grade)}
            )
        exponents = [-plan["gamma"] * v for v in values]
        peak = max(exponents)
        ce = (
            -(peak + math.log(sum(math.exp(x - peak) for x in exponents) / len(values)))
            / plan["gamma"]
        )
        candidates.append(
            {"schedule_index": index, "development_ce": ce, "evidence": evidence}
        )
    selected = max(
        candidates, key=lambda x: (x["development_ce"], -x["schedule_index"])
    )
    return {
        "selected_index": selected["schedule_index"],
        "candidates": candidates,
        "selection_scope": "reused_development_only_not_confirmation",
        "claim_status": "HOLD",
    }
