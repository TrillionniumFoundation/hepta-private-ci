"""Paired, post-codec continuations from one frozen public generation prefix.

These are development diagnostics, not a replacement for the registered research
gate. An empirical best action is a retrospective comparison, never a policy
input or an exact dynamic-programming oracle.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from ..model import ACTIONS, tensor_digest
from .critic_calibration import fit_validate_critics


GAMMA = 2.0


def _clone_tree(value):
    """Evaluation snapshots must not share storage or retain training graphs."""
    if torch.is_tensor(value):
        return value.detach().clone()
    if is_dataclass(value):
        return replace(value, **{item.name: _clone_tree(getattr(value, item.name)) for item in fields(value)})
    if isinstance(value, dict):
        return {key: _clone_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_clone_tree(item) for item in value)
    return deepcopy(value)


def _vector(values, name):
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise ValueError(f"{name} must be a nonempty finite vector")
    return array


def certainty_equivalent(returns, weights=None):
    """Frozen gamma=2; logarithm after the weighted population expectation."""
    values = _vector(returns, "returns")
    mass = np.ones(len(values)) if weights is None else _vector(weights, "weights")
    if mass.shape != values.shape or (mass < 0).any() or mass.sum() <= 0:
        raise ValueError("Weights must align with returns and have positive mass")
    active = mass > 0
    logs = -GAMMA * values[active] + np.log(mass[active])
    top = logs.max()
    return float(-(top + np.log(np.exp(logs - top).sum()) - np.log(mass.sum())) / GAMMA)


def paired_ce_difference(left, right, *, source_ids=None, bootstrap=400, seed=1729):
    """Difference of CEs, never the CE of paired differences.

    With source IDs, every original source has equal population mass, retaining
    all its paired draws when resampled. Without IDs, resample paired future
    draws of a single frozen prefix; that interval does not cover new tasks.
    """
    left, right = _vector(left, "left returns"), _vector(right, "right returns")
    if left.shape != right.shape or type(bootstrap) is not int or bootstrap < 0:
        raise ValueError("Paired vectors must align and bootstrap must be nonnegative")
    ids = list(range(len(left))) if source_ids is None else list(source_ids)
    if len(ids) != len(left):
        raise ValueError("Source identities must align with paired outcomes")
    counts = Counter(ids)
    weights = np.asarray([1 / counts[key] for key in ids], dtype=np.float64)
    unique = list(counts)
    indices = {key: np.asarray([i for i, value in enumerate(ids) if value == key]) for key in unique}
    result = {
        "ce_left": certainty_equivalent(left, weights),
        "ce_right": certainty_equivalent(right, weights),
        "mean_paired_return_delta": float(np.average(left - right, weights=weights)),
        "paired_draws": len(left), "independent_units": len(unique),
        "bootstrap_unit": "original_source" if source_ids is not None else "future_draw_within_frozen_prefix",
        "finite_sample_ce_bias": True, "confirmation": False,
    }
    result["ce_delta"] = result["ce_left"] - result["ce_right"]
    rng, estimates = np.random.default_rng(seed), []
    if len(unique) > 1:
        for _ in range(bootstrap):
            sampled = rng.integers(len(unique), size=len(unique))
            blocks = [indices[unique[i]] for i in sampled]
            selected = np.concatenate(blocks)
            mass = np.concatenate([np.full(len(block), 1 / len(block)) for block in blocks])
            estimates.append(certainty_equivalent(left[selected], mass) - certainty_equivalent(right[selected], mass))
    result["ce_delta_percentile_95"] = np.quantile(estimates, [.025, .975]).tolist() if estimates else None
    result["bootstrap_replicates"] = len(estimates)
    return result


def critic_calibration(rows):
    """Compare a pre-outcome log-moment prediction with its matching suffix.

    Conditioning groups must be identical source/prefix/action/continuation
    contracts. A moment loss is used; regressing a realized log return would
    target a different conditional statistic.
    """
    if not rows:
        raise ValueError("Calibration needs executed continuations")
    predictions = _vector([r["predicted_suffix_log_moment"] for r in rows], "predictions")
    returns = _vector([r["suffix_return"] for r in rows], "suffix returns")
    observed_ce = certainty_equivalent(returns)
    predicted_ce = certainty_equivalent(-predictions / GAMMA)
    predicted_moment, actual_moment = np.exp(predictions), np.exp(-GAMMA * returns)
    if not np.isfinite(predicted_moment).all() or not np.isfinite(actual_moment).all():
        raise ValueError("Calibration moment overflow; no clipping is permitted")
    return {
        "observed_conditional_ce_plugin": observed_ce,
        "predicted_ce_from_mean_moment": predicted_ce,
        "ce_error": predicted_ce - observed_ce,
        "observed_log_moment_plugin": -GAMMA * observed_ce,
        "predicted_log_moment_range": [float(predictions.min()), float(predictions.max())],
        "proper_moment_loss": float(np.mean(predicted_moment - actual_moment * predictions)),
        "moment_bias": float(np.mean(predicted_moment - actual_moment)),
        "samples": len(rows), "empirical_target_has_sampling_error": True,
    }


def summarize_prefix(rows, *, bootstrap=400, seed=1729):
    """Aggregate complete paired arms without selecting a deployable winner."""
    arms = defaultdict(list)
    seen = set()
    for row in rows:
        identity = (row["arm"], row["draw"])
        if identity in seen:
            raise ValueError("Duplicate arm/draw would fabricate precision")
        seen.add(identity)
        arms[row["arm"]].append(row)
    if "stop" not in arms:
        raise ValueError("The legal immediate STOP reference is required")
    for values in arms.values():
        values.sort(key=lambda r: r["draw"])
    draws = [r["draw"] for r in arms["stop"]]
    if any([r["draw"] for r in values] != draws for values in arms.values()):
        raise ValueError("Every arm must retain the same independent draw identities")
    prefixes = {r["frozen_prefix_sha256"] for r in rows}
    if len(prefixes) != 1:
        raise ValueError("Conditional calibration mixed different frozen prefixes")
    for draw in draws:
        noise = {r["future_randomness_sha256"] for r in rows if r["draw"] == draw}
        if len(noise) != 1:
            raise ValueError("Candidate arms did not use paired future randomness")
    baseline = [r["complete_return"] for r in arms["stop"]]
    results = {}
    for index, (arm, values) in enumerate(arms.items()):
        results[arm] = {
            "paired_vs_stop": paired_ce_difference([r["complete_return"] for r in values], baseline,
                bootstrap=bootstrap, seed=seed + index),
            "critic": critic_calibration(values),
            "mean_utility": float(np.mean([r["utility"] for r in values])),
            "mean_suffix_cost": float(np.mean([r["suffix_cost"] for r in values])),
            "mean_complete_cost": float(np.mean([r["complete_cost"] for r in values])),
            "failures": sum(r["failure"] is not None for r in values),
        }
    ranked = {a: v for a, v in results.items() if a in ACTIONS}
    predicted = {a: v["critic"]["predicted_ce_from_mean_moment"] for a, v in ranked.items()}
    actual = {a: v["critic"]["observed_conditional_ce_plugin"] for a, v in ranked.items()}
    predicted_choice, empirical_choice = max(predicted, key=predicted.get), max(actual, key=actual.get)
    pairs = [(a, b) for i, a in enumerate(ranked) for b in list(ranked)[i + 1:]
             if abs(actual[a] - actual[b]) > 1e-12]
    concordant = sum((predicted[a] - predicted[b]) * (actual[a] - actual[b]) > 0 for a, b in pairs)
    return {
        "arms": results,
        "critic_ranking": {
            "predicted_best_action": predicted_choice, "empirical_best_action": empirical_choice,
            "empirical_ce_gap_of_predicted_choice": actual[empirical_choice] - actual[predicted_choice],
            "strict_pairwise_concordance": concordant / len(pairs) if pairs else None,
            "non_tied_empirical_pairs": len(pairs),
            "best_action_is_retrospective_not_oracle_or_policy_input": True,
        },
        "prefix_count": 1, "draws_per_arm": len(draws), "research_effect_qualified": False,
    }


def verify_information(model, state, public, remaining, *, horizon=6):
    """Inspect actual public feedback; never infer uselessness from content alone.

    The fixed-clock actor comparison isolates the feedback channel from elapsed
    steps. Repeated feedback means no *new* observation in this verifier, not
    that the initial verification cannot have downstream decision value.
    """
    with torch.no_grad():
        first, _ = model.advance(_clone_tree(state), "verify", public)
        second, _ = model.advance(_clone_tree(first), "verify", public)
        aligned = replace(first, steps=state.steps)
        before_logits = model.actor(model.features(state, remaining))
        after_logits = model.actor(model.features(aligned, remaining))
        content = lambda s: tensor_digest({"shared": s.shared, "slots": s.slots, "core": s.core})
        law_before, _ = model.policy(state, remaining, horizon)
        law_first, _ = model.policy(first, remaining, horizon)
        return {
            "first_content_changed": content(state) != content(first),
            "first_feedback_changed": not torch.equal(state.feedback, first.feedback),
            "first_feedback_l2": float((first.feedback - state.feedback).square().sum().sqrt()),
            "repeated_content_changed": content(first) != content(second),
            "repeated_feedback_changed": not torch.equal(first.feedback, second.feedback),
            "repeated_feedback_l2": float((second.feedback - first.feedback).square().sum().sqrt()),
            "fixed_clock_actor_probability_l1": float((before_logits.softmax(-1) - after_logits.softmax(-1)).abs().sum()),
            "feedback_before": state.feedback.detach().tolist(),
            "feedback_first": first.feedback.detach().tolist(),
            "feedback_repeated": second.feedback.detach().tolist(),
            "first_verify_policy_legal": bool(torch.isfinite(law_before[0, ACTIONS.index("verify")])),
            "repeated_verify_policy_legal": bool(torch.isfinite(law_first[0, ACTIONS.index("verify")])),
            "targets_accessed": False,
            "transition_probe_is_not_a_delivered_outcome": True,
        }


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _save_tensors(path, tree):
    arrays = {}
    def visit(value, key):
        if torch.is_tensor(value):
            arrays[key] = value.detach().cpu().numpy()
        elif isinstance(value, dict):
            for child, item in value.items():
                visit(item, f"{key}/{child}")
        elif isinstance(value, (list, tuple)):
            for child, item in enumerate(value):
                visit(item, f"{key}/{child}")
        elif isinstance(value, (int, float, bool)):
            arrays[key] = np.asarray(value)
    visit(tree, "state")
    np.savez_compressed(path, **arrays)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fork(snapshot, seed):
    """Same conditioning state; independent future tape, paired across arms."""
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("A nonnegative signed-64 future seed is required")
    result = _clone_tree(snapshot)
    for field, stream_seed in (("actor_rng", seed), ("emission_rng", seed ^ 0x5EED1234)):
        value = getattr(result, field)
        if isinstance(value, torch.Generator):
            value.manual_seed(stream_seed)
        else:
            result = replace(result, **{field: torch.Generator().manual_seed(stream_seed).get_state()})
    return result


def _rng_digest(snapshot):
    return tensor_digest({key: value.get_state() if isinstance(value, torch.Generator) else value
                          for key in ("actor_rng", "emission_rng") for value in (getattr(snapshot, key),)})


def _prediction(model, snapshot, public, plan, continuation, backend, profile):
    """Planner's current approximation; actual physical future cost is unknown."""
    state, budget, tariff_cost = _clone_tree(snapshot.state), snapshot.budget, 0.0
    actions = tuple(plan) + (("stop",) if continuation == "stop" and plan[-1] != "stop" else ())
    with torch.no_grad():
        for action in actions:
            law, _ = model.policy(state, budget / profile.initial_budget, profile.horizon)
            reserve = backend.TARIFF["delivery"] + backend.TARIFF["stop"]
            if (not torch.isfinite(law[0, ACTIONS.index(action)])
                    or action != "stop" and budget < backend.TARIFF[action] + reserve):
                return None
            if action == "stop":
                # v3 trains this critic at the pre-STOP boundary, including
                # the STOP transition and the subsequent physical delivery.
                features = model.features(state, budget / profile.initial_budget).detach()
                return float(model.delivery_critic(features)[0, 0]) + GAMMA * tariff_cost
            state, _ = model.advance(state, action, public)
            tariff_cost += backend.TARIFF[action]
            budget -= backend.TARIFF[action]
        features = model.features(state, budget / profile.initial_budget).detach()
        value = model.critic(features)[0, 0]
        return float(value) + GAMMA * tariff_cost


def _critic_observation(model, snapshot, public, plan, continuation, record, profile):
    """A public pre-critic state paired with its actual subsequently observed suffix."""
    state, budget, incurred = _clone_tree(snapshot.state), snapshot.budget, 0.0
    with torch.no_grad():
        for index, action in enumerate(plan):
            if action == "stop":
                break
            if index >= len(record["actions"]) or record["actions"][index]["action"] != action:
                return {"critic_fit_available": False, "critic_fit_exclusion": "forced_transition_not_completed"}
            event = record["actions"][index]
            state, _ = model.advance(state, action, public)
            if tensor_digest(state.tensors()) != event["after_sha256"]:
                raise ValueError("Public reconstruction differs from the executed critic prefix")
            incurred += event["amount"]
            budget -= event["amount"]
        head = "delivery_critic" if plan[-1] == "stop" or continuation == "stop" else "critic"
        features = model.features(state, budget / profile.initial_budget).detach()
        target = record["outcome"]["delivered_utility"] - (record["actual_cost"] - snapshot.prefix_cost - incurred)
        return {"critic_fit_available": True, "critic_fit_head": head,
                "critic_fit_features": features[0].cpu().tolist(),
                "critic_fit_suffix_return": target,
                "critic_fit_initial_prediction": float(getattr(model, head)(features)[0, 0]),
                "critic_fit_origin_cost": snapshot.prefix_cost + incurred,
                "critic_fit_state_sha256": tensor_digest(state.tensors())}


def evaluate_prefix(model, public, score, directory, *, source_id, context_id=None,
                    prefix=(), draws=16, seed=1729, profile=None, continuation="dynamic",
                    bootstrap=400, backend=None, actions=ACTIONS, critic_continuation="dynamic"):
    """Run actual PNG/WAV/GIF/text continuations from one frozen snapshot.

    ``score`` is an external post-readback observer. Neither it nor its closed-
    over targets is passed to encode/advance/policy/critic. Raw emitted files,
    independent readback tensors and each numerical observer result are kept.
    The runtime backend owns accounting and snapshot resumption.
    """
    if backend is None:
        from . import runtime as backend
    if continuation not in {"dynamic", "greedy", "stop"} or type(draws) is not int or draws < 1:
        raise ValueError("Use a registered continuation and positive future draw count")
    if len(public["image"]) != 1 or "stop" not in actions or any(a not in ACTIONS for a in actions):
        raise ValueError("One public source and legal candidate actions including STOP are required")
    if len(set(actions)) != len(actions) or any(a == "stop" or a not in ACTIONS for a in prefix):
        raise ValueError("Candidate actions must be unique and the conditioning prefix must be nonterminal")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    profile = profile or backend.make_profile()
    context_id = context_id or source_id
    started = time.perf_counter()
    model_hash, input_hash = tensor_digest(model.state_dict()), tensor_digest(public)
    with torch.no_grad():
        snapshot = backend.start_snapshot(model, public, seed=seed, context_id=context_id,
                                          source_id=source_id, profile=profile)
        for action in prefix:
            snapshot = backend.advance_snapshot(model, public, snapshot, action, profile=profile)
    frozen_hash = tensor_digest({"state": snapshot.state.tensors(), "budget": snapshot.budget,
                                 "prefix_cost": snapshot.prefix_cost})
    prefix_payload = _save_tensors(directory / "PREFIX_STATE.npz", snapshot.state.tensors())
    input_payload = _save_tensors(directory / "PUBLIC_INPUT.npz", public)
    info = verify_information(model, snapshot.state, public, snapshot.budget / profile.initial_budget,
                              horizon=profile.horizon)
    plans = {a: (a,) for a in actions}
    if "verify" in actions:
        plans["verify_twice"] = ("verify", "verify")
    predictions, skipped = {}, {}
    for arm, plan in plans.items():
        value = _prediction(model, snapshot, public, plan, continuation, backend, profile)
        if value is None:
            skipped[arm] = "intervention_is_illegal_under_horizon_or_policy_mask"
        else:
            predictions[arm] = value
    if "stop" not in predictions:
        raise ValueError("Initial STOP is not legal in this v3 model")
    _write_json(directory / "PREFIX.json", {
        "model_sha256": model_hash, "input_sha256": input_hash, "profile_sha256": profile.digest,
        "frozen_prefix_sha256": frozen_hash, "prefix": list(prefix), "budget": snapshot.budget,
        "prefix_cost": snapshot.prefix_cost, "state_payload_sha256": prefix_payload,
        "public_payload_sha256": input_payload, "source_id": source_id, "seed": seed,
        "verify_information": info, "skipped": skipped,
    })
    rows = []
    for draw in range(draws):
        paired = _fork(snapshot, seed + draw * 7919)
        noise_hash = _rng_digest(paired)
        for arm in predictions:
            branch_dir = directory / f"draw-{draw:04d}" / arm
            observed = []
            def observe(readback):
                value = float(score(readback))
                if not math.isfinite(value):
                    raise ValueError("External observer returned nonfinite utility")
                payload = _save_tensors(branch_dir / "READBACK.npz", readback)
                receipt = {"utility": value, "readback_sha256": tensor_digest(readback),
                           "payload_sha256": payload, "source_id": source_id,
                           "model_sha256": model_hash, "targets_are_observer_only": True}
                _write_json(branch_dir / "READBACK_SCORE.json", receipt)
                observed.append(receipt)
                return value
            with torch.no_grad():
                episode = backend.execute(model, public, observe, branch_dir,
                    seed=seed + draw * 7919, context_id=context_id, source_id=source_id,
                    profile=profile, strategy=continuation, prefix=plans[arm], initial_snapshot=_clone_tree(paired))
            record = episode.record
            cost, failure = float(record["actual_cost"]), record.get("failure")
            utility = float(record["outcome"]["delivered_utility"])
            if failure is None and len(observed) != 1:
                raise ValueError("A successful branch needs exactly one independent readback")
            suffix_cost = cost - snapshot.prefix_cost
            if suffix_cost < -1e-12 or abs(utility - cost - float(episode.net_return)) > 1e-8:
                raise ValueError("Resumed accounting does not reconstruct the complete return")
            row = {
                "source_id": source_id, "arm": arm, "draw": draw, "prefix": list(prefix),
                "continuation": continuation, "frozen_prefix_sha256": frozen_hash,
                "future_randomness_sha256": noise_hash, "utility": utility,
                "complete_cost": cost, "prefix_cost": snapshot.prefix_cost, "suffix_cost": suffix_cost,
                "complete_return": float(episode.net_return), "suffix_return": utility - suffix_cost,
                "predicted_suffix_log_moment": predictions[arm], "failure": failure,
                "readback": observed[0] if observed else None,
                "trajectory_file": str(branch_dir / "TRAJECTORY.json"),
                "executed_actions": [entry["action"] for entry in record["actions"]],
                "net_with_audit_close": record.get("net_with_audit_close"),
                **_critic_observation(model, snapshot, public, plans[arm], continuation, record, profile),
            }
            rows.append(row)
            _write_json(branch_dir / "PAIRED_OUTCOME.json", row)
    if tensor_digest(model.state_dict()) != model_hash or tensor_digest(public) != input_hash:
        raise ValueError("Frozen model or public conditioning inputs changed during diagnostics")
    if tensor_digest({"state": snapshot.state.tensors(), "budget": snapshot.budget,
                      "prefix_cost": snapshot.prefix_cost}) != frozen_hash:
        raise ValueError("A continuation mutated the shared prefix snapshot")
    result = {
        "schema": "hepta.joint-generation.frozen-prefix-diagnostics.v3",
        "source_id": source_id, "input_sha256": input_hash, "model_sha256": model_hash, "profile_sha256": profile.digest,
        "diagnostic_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seed": seed, "future_seed_rule": "seed+7919*draw; actor_seed; emission_seed_xor_0x5eed1234",
        "prefix": list(prefix), "rows": rows, "summary": summarize_prefix(rows, bootstrap=bootstrap, seed=seed),
        "verify_information": info, "skipped": skipped,
        "continuation": continuation, "critic_trained_continuation": critic_continuation,
        "continuation_critic_policy_match": continuation in {"stop", critic_continuation},
        "critic_action_cost_prediction": "registered_service_tariff; unknown_future_physical_cost_is_a_prediction_error",
        "prefix_work": "executed_once; same_sunk_cost_in_all_counterfactual_complete_returns",
        "raw_readback_storage_cost": "inside_observer_and_charged_to_each_branch",
        "diagnostic_total_wall_seconds": time.perf_counter() - started,
        "research_effect_qualified": False, "semantic_qualification": False,
    }
    _write_json(directory / "DIAGNOSTICS.json", result)
    return result
