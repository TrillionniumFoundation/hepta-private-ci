"""Actual first-choice critic consumption; all later choices use the original actor."""

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import torch

from ...mechanism_data import batch
from ...media import utility
from ...model import ACTIONS, tensor_digest
from .. import runtime
from ..diagnostics import (_fork, _prediction, _rng_digest, _save_tensors,
                           _write_json, paired_ce_difference)
from ..model import JointGenerator
from ..profile import TARIFF, make_profile


ARMS = ("actor", "original_critic_first", "calibrated_critic_first", "stop")


def content_actor_hash(model):
    return tensor_digest({name: value for name, value in model.state_dict().items()
                          if not name.startswith(("critic.", "delivery_critic."))})


def choose_first(critic_model, snapshot, public, profile):
    """Use approximate action moments, with no target/observer in this call."""
    predictions = {}
    with torch.no_grad():
        for action in ACTIONS:
            value = _prediction(critic_model, snapshot, public, (action,), "dynamic", runtime, profile)
            if value is not None:
                if not math.isfinite(value):
                    raise ValueError("Nonfinite critic first-choice prediction")
                predictions[action] = value
    if "stop" not in predictions:
        raise ValueError("A first-choice consumer must retain legal STOP")
    return min(predictions, key=predictions.get), predictions


def evaluate_draw(original, calibrated, public, score, snapshot, directory, *, source_id,
                  draw, seed, profile, arm_order=ARMS):
    """All four arms share the encoded prefix and initial named random tape.

    Planning is a real control operation that reduces the planner's successor
    budget. Generation always uses `original`, including its unchanged actor;
    calibrated content tensors never enter execution.
    """
    if set(arm_order) != set(ARMS) or len(arm_order) != len(ARMS):
        raise ValueError("Each declared arm must be executed exactly once")
    if original.config != calibrated.config or content_actor_hash(original) != content_actor_hash(calibrated):
        raise ValueError("The calibrated candidate changed content, actor, or generation configuration")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    common = _fork(snapshot, seed)
    origin, noise = common.digest, _rng_digest(common)
    rows = []
    for arm in arm_order:
        started = runtime._clock()
        branch = runtime.clone_snapshot(common)
        choice, predictions, planning = None, {}, None
        if arm.endswith("_critic_first"):
            critic = calibrated if arm == "calibrated_critic_first" else original
            choice, predictions = choose_first(critic, branch, public, profile)
            planning = {"action": "critic_first_choice", "selected_action": choice,
                        "candidate_log_moments": predictions,
                        "critic_parameters_sha256": tensor_digest({name: value for name, value in critic.state_dict().items()
                            if name.startswith(("critic.", "delivery_critic."))}),
                        **runtime._charge(started, "control")}
            branch = replace(branch, budget=branch.budget-planning["amount"],
                prefix_cost=branch.prefix_cost+planning["amount"], events=branch.events+(planning,))
        branch_dir = directory / arm
        readbacks = []
        def observe(readback):
            value = float(score(readback))
            payload_sha = _save_tensors(branch_dir / "READBACK.npz", readback)
            receipt = {"readback_sha256": tensor_digest(readback), "payload_sha256": payload_sha,
                       "utility": value, "source_id": source_id, "targets_are_observer_only": True}
            _write_json(branch_dir / "READBACK_SCORE.json", receipt)
            readbacks.append(receipt)
            return value
        with torch.no_grad():
            episode = runtime.execute(original, public, observe, branch_dir,
                seed=seed, context_id=source_id, source_id=source_id, profile=profile,
                strategy="stop" if arm == "stop" else "dynamic",
                prefix=(choice,) if choice is not None else (), initial_snapshot=branch)
        record = episode.record
        events = record["events"]
        if record["failure"] is None and len(readbacks) != 1:
            raise ValueError("Successful first-choice execution lacks an independent readback")
        # Close gaps between the external planner/caller and the runtime's
        # contiguous through-seal meter. Only the final consumer receipt write
        # remains in the outer study cost, avoiding recursive self-billing.
        ended = runtime._clock()
        future = events[len(snapshot.events):]
        cpu_gap = ended[0]-started[0]-sum(e["cpu_seconds"] for e in future)
        wall_gap = ended[1]-started[1]-sum(e["wall_seconds"] for e in future)
        if cpu_gap < -1e-6 or wall_gap < -1e-6:
            raise ValueError("Nested first-choice accounting double-counted physical time")
        close = {"action": "consumer_close", "cpu_seconds": max(0.0, cpu_gap),
                 "wall_seconds": max(0.0, wall_gap), "service_fee": 0.0}
        close["amount"] = TARIFF["cpu_second"]*close["cpu_seconds"] + TARIFF["wall_second"]*close["wall_seconds"]
        total = record["actual_cost"] + close["amount"]
        observed = record["outcome"]["delivered_utility"]
        row = {"source_id": source_id, "draw": draw, "seed": seed, "arm": arm,
            "common_prefix_snapshot_sha256": origin, "common_future_randomness_sha256": noise,
            "selected_first_action": record["actions"][0]["action"] if record["actions"] else None,
            "planned_first_action": choice, "predicted_action_log_moments": predictions,
            "planning_cost": planning["amount"] if planning else 0.0,
            "actual_cost": total, "utility": observed, "net_return": observed-total,
            "runtime_net_return_through_seal": episode.net_return, "caller_close": close,
            "events": events + [close], "failure": record["failure"],
            "readback": readbacks[0] if readbacks else None,
            "actions": [event["action"] for event in record["actions"]],
            "runtime_trajectory": str(branch_dir / "TRAJECTORY.json")}
        if abs(sum(e["amount"] for e in row["events"])-total) > 1e-9:
            raise ValueError("First-choice outcome does not reconcile with its entire cost ledger")
        _write_json(branch_dir / "CONSUMER_OUTCOME.json", row)
        rows.append(row)
    if common.digest != origin:
        raise ValueError("An arm mutated the common encoded prefix or random tape")
    return rows


def run(original_checkpoint, calibrated_checkpoint, output):
    original_checkpoint, calibrated_checkpoint, output = map(Path, (original_checkpoint, calibrated_checkpoint, output))
    loaded = [torch.load(path, map_location="cpu", weights_only=True)
              for path in (original_checkpoint, calibrated_checkpoint)]
    models = []
    for value in loaded:
        model = JointGenerator(**value["config"]).eval()
        model.load_state_dict(value["state_dict"], strict=True)
        models.append(model)
    original, calibrated = models
    if original.config != calibrated.config or content_actor_hash(original) != content_actor_hash(calibrated):
        raise ValueError("Calibrated model cannot alter content or the continuing actor")
    torch.set_num_threads(1); torch.use_deterministic_algorithms(True)
    output.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    profile = make_profile()
    profile = replace(profile, implementation=profile.implementation+(("critic_choice/run.py", source_hash),))
    namespace = "joint-v3-critic-choice.fresh-analysis.20261030"
    hashes = [tensor_digest(model.state_dict()) for model in models]
    protocol = {"schema": "hepta.joint-generation.critic-first-choice.development.v3",
        "source_namespace": namespace, "sources": 16, "draws_per_source": 4, "arms": ARMS,
        "original_checkpoint_sha256": hashlib.sha256(original_checkpoint.read_bytes()).hexdigest(),
        "calibrated_checkpoint_sha256": hashlib.sha256(calibrated_checkpoint.read_bytes()).hexdigest(),
        "content_actor_sha256": content_actor_hash(original), "model_hashes": hashes,
        "profile": profile.to_dict(), "consumer_source_sha256": source_hash,
        "seed_rule": "31000000+source*10000+draw*997", "arm_order": "cyclic rotate by (source*4+draw)%4",
        "critic_rule": "min(service_tariff*gamma + conditional_dynamic_suffix_log_moment); preSTOP head includes STOP cost",
        "planning_budget": "shared origin; measured planning reduces successor budget before forced action",
        "continuation": "original actor after one selected action; no replanning or policy updates",
        "randomness_coupling": "same initial named tape; forced choices consume no actor draw; emission stream independent",
        "bootstrap_replicates": 1000, "evaluation_gamma": 2.0,
        "reference_arms": ("actor", "stop", "original_critic_first"),
        "cost_boundary": "shared encoded prefix plus all branch work through runtime seal and caller close; final receipt write outer",
        "calibration_training_cost": "retained in preceding calibration study, not amortized into this per-request comparison",
        "runtime": {"python": platform.python_version(), "torch": str(torch.__version__), "threads": 1},
        "confirmation_sources_consumed": 0, "research_effect_qualified": False, "global_optimum_claim": False}
    _write_json(output / "FROZEN_PROTOCOL.json", protocol)
    started = runtime._clock()
    rows = []
    for source in range(16):
        public, target = batch([source], namespace)
        with torch.no_grad():
            snapshot = runtime.start_snapshot(original, public, seed=31000000+source*10000,
                context_id=f"{namespace}.{source}", source_id=f"{namespace}.{source}", profile=profile)
        source_dir = output / f"source-{source:03d}"
        source_dir.mkdir(parents=True, exist_ok=False)
        _save_tensors(source_dir / "PUBLIC_INPUT.npz", public)
        _save_tensors(source_dir / "PREFIX_STATE.npz", snapshot.state.tensors())
        _write_json(source_dir / "PREFIX.json", {"snapshot_sha256": snapshot.digest,
            "budget": snapshot.budget, "prefix_cost": snapshot.prefix_cost,
            "state_hash": snapshot.state_hash, "input_hash": snapshot.input_hash})
        for draw in range(4):
            rotate = (source*4+draw) % len(ARMS)
            order = ARMS[rotate:]+ARMS[:rotate]
            rows.extend(evaluate_draw(original, calibrated, public,
                lambda readback: utility(readback, target).item(), snapshot, source_dir / f"draw-{draw}",
                source_id=f"{namespace}.{source}", draw=draw, seed=31000000+source*10000+draw*997,
                profile=profile, arm_order=order))
        print(json.dumps({"critic_choice_source": source+1, "sources": 16, "actual_continuations": len(rows)}), flush=True)
    by_arm = {arm: sorted([r for r in rows if r["arm"] == arm], key=lambda r: (r["source_id"], r["draw"])) for arm in ARMS}
    comparisons = {}
    for arm in ARMS:
        for reference in ("actor", "stop", "original_critic_first"):
            values, baseline = by_arm[arm], by_arm[reference]
            comparisons[f"{arm}__minus__{reference}"] = paired_ce_difference(
                [r["net_return"] for r in values], [r["net_return"] for r in baseline],
                source_ids=[r["source_id"] for r in values], bootstrap=1000, seed=31)
    if [tensor_digest(model.state_dict()) for model in models] != hashes:
        raise ValueError("Frozen inference/critic parameters changed during consumer evaluation")
    ended = runtime._clock()
    result = {"schema": protocol["schema"], "protocol": protocol, "rows": rows,
        "comparisons": comparisons, "actual_continuations": len(rows),
        "arms": {arm: {"first_choices": dict(Counter(r["selected_first_action"] for r in values)),
                       "mean_cost": float(np.mean([r["actual_cost"] for r in values])),
                       "mean_planning_cost": float(np.mean([r["planning_cost"] for r in values])),
                       "mean_utility": float(np.mean([r["utility"] for r in values])),
                       "failures": sum(r["failure"] is not None for r in values)} for arm, values in by_arm.items()},
        "outer_cpu_seconds": ended[0]-started[0], "outer_wall_seconds": ended[1]-started[1],
        "model_parameters_unchanged": True, "research_effect_qualified": False,
        "semantic_qualification": False, "confirmation_sources_consumed": 0,
        "scope": "first choice only; approximate learned conditional values; original actor afterward"}
    _write_json(output / "RESULT.json", result)
    print(json.dumps({"actual_continuations": len(rows), "output": str(output), "arms": result["arms"]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-checkpoint", type=Path, required=True)
    parser.add_argument("--calibrated-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.original_checkpoint, args.calibrated_checkpoint, args.output)
