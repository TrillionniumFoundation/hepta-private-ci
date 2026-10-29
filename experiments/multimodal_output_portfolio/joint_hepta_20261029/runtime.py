"""Executed joint trajectories: public-state policy, actual files and one ledger.

The physical meter covers encoding through independent terminal readback and
observer execution, including in-process planning and terminated owner children.
Closing the audit JSON is separately reported; it cannot charge its own write
recursively. Training/setup and cold model loading are reported by the runner.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import torch

from .contract import (CostEvent, DecisionEvent, DeliveredOutcome, GenerationState,
                       JointGenerationProfile, NduProfile, digest, validate_episode,
                       validate_runtime_features)
from .media import write_read
from .model import ACTIONS, MODALITIES, tensor_digest


TARIFF = {"cpu_second": 0.02, "wall_second": 0.001, "encode": 0.001,
          "shared": 0.004, "image": 0.0025, "audio": 0.0025, "video": 0.0025,
          "text": 0.0025, "verify": 0.003, "stop": 0.0005, "delivery": 0.005}
HORIZON = 6
INITIAL_BUDGET = 100.0


def cpu_seconds():
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime


def make_profile(dataset="mechanism", *, audio_rate=2048, frame_ms=120):
    """The same frozen object is passed into learning, deployment and scoring."""
    if dataset not in {"mechanism", "natural_context"}:
        raise ValueError("Unregistered task")
    source = lambda name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    ndu = NduProfile(
        objective_sha256=digest({"metric": "joint_restore_v1", "dataset": dataset,
                                 "media": "0.65*exp(-4*sum(MSE))", "text": "0.35*mean(label_correct)"}),
        observer_sha256=digest({"observer": "fixed_post_codec_restoration_v1",
                                "observer_source_sha256": source("media.py"),
                                "semantic_observer_qualified": False}),
        continuation_sha256=digest({"executor": "joint_runtime_v1", "actions": ACTIONS,
                                     "executor_source_sha256": source("runtime.py"),
                                     "horizon": HORIZON, "stop": "buffered_actual_four_file_delivery"}),
        utility_bounds=(-1.0, 1.0), required_modalities=("text", "image", "audio", "video"))
    return JointGenerationProfile(
        ndu, input_contract_sha256=digest({"dataset": dataset, "public": ["image", "image_mask",
            "audio", "audio_mask", "video", "video_mask", "tokens"], "audio_rate": audio_rate,
            "frame_ms": frame_ms, "natural_feedback": "context_consistency_not_target_mask_error"}),
        randomness_contract_sha256=digest({"actor": "joint_categorical", "emission": "latent_normal_sigma_0.035",
            "text": "two_categorical_heads", "diagnostic_argmax": "separate_degenerate_law",
            "seed": "independent_named_actor_and_emission_cpu_generators"}),
        resource_accounting_sha256=digest({"tariff": TARIFF, "meter": "cpu_plus_wall_and_action_service",
            "boundary": "encode_to_observed_delivery_including_validated_audit_draft", "final_audit_seal": "separate_sensitivity",
            "training_setup_and_cold_load": "runner_separate_report"}),
        model_port_sha256=digest({"state": "encoder_shared_modality_HCSN", "actions": ACTIONS,
                                  "model_source": source("model.py"), "core_source": source("hepta_core.py"),
                                  "outputs": ["png", "wav", "gif", "utf8"], "horizon": HORIZON}),
        max_events=HORIZON + 3)


@dataclass
class Episode:
    record: dict
    net_return: float
    log_probability: torch.Tensor
    critic_values: list
    suffix_returns: list
    terminal_state: object
    teacher_examples: list


def _probabilities(log_law):
    values = log_law.detach().double().exp()[0].tolist()
    total = sum(values)
    return tuple((a, p / total) for a, p in zip(ACTIONS, values))


def _snapshot(profile, state, *, context, input_sha, model_sha, policy_sha, index, elapsed, budget,
              generation, artifacts=None):
    artifacts = artifacts or {}
    return GenerationState(profile.digest, context, input_sha, model_sha, policy_sha,
        tensor_digest({"shared": state.shared, "core": state.core, "feedback": state.feedback}),
        tuple((m, tensor_digest(state.slots[:, i])) for i, m in enumerate(MODALITIES)),
        tuple(sorted(artifacts.items())), tuple(sorted(generation.items())),
        tuple(sorted({m: (2 if m == "text" else 1024 if m == "audio" else 4 if m == "video" else 0)
                      if artifacts else 0 for m in MODALITIES}.items())), index, elapsed, budget)


def planner_action(model, state, public, remaining, profile):
    """One-step public rollout plus learned suffix moment, never target scoring.

    This is an approximate critic planner, not an exact HJB solution. All seven
    trial transitions are physically metered by the caller. It is a deterministic
    policy and must not be trained with the actor's categorical score.
    """
    legal, _ = model.policy(state, remaining, HORIZON)
    candidates = []
    with torch.no_grad():
        for i, action in enumerate(ACTIONS):
            if not torch.isfinite(legal[0, i]):
                continue
            child, _ = model.advance(state, action, public)
            next_remaining = remaining - TARIFF[action] / INITIAL_BUDGET
            if action == "stop":
                value = model.delivery_critic(model.features(child, next_remaining).detach())[:, 0]
            else:
                _, value = model.policy(child, next_remaining, HORIZON)
            candidates.append((profile.ndu.gamma * TARIFF[action] + value.item(), i))
    return min(candidates)[1]


def execute(model, public, observe, directory, *, seed, context_id, source_id,
            profile=None, strategy="dynamic", fixed_actions=("shared", "image", "audio", "video", "text", "stop"),
            prefix=(), feedback_override=None, deterministic_emission=False,
            native_factory=None, native_reopen_at=None, audio_rate=2048, frame_ms=120):
    """Execute a frozen parameter snapshot; ``observe`` runs only after STOP.

    ``observe`` is the external readback observer. It may close over labels; the
    generator, verifier, planner and actor are never passed that closure or labels.
    Stochastic policy/emission scores use sampled, detached choices; there is no
    additional pathwise reward derivative in the registered score estimator.
    """
    if strategy not in {"dynamic", "greedy", "fixed", "planner"}:
        raise ValueError("Unknown policy")
    if len(public["image"]) != 1:
        raise ValueError("Physical delivered episodes are single-context draws")
    profile = profile or make_profile()
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    begun, cpu_start = time.perf_counter(), cpu_seconds()
    rng = torch.Generator(device="cpu").manual_seed(seed)
    emission_rng = torch.Generator(device="cpu").manual_seed(int(digest({"seed": seed, "stream": "emission"})[:15], 16))
    model_sha, input_sha = tensor_digest(model.state_dict()), tensor_digest(public)
    policy_sha = digest({"model": model_sha, "strategy": strategy, "fixed_actions": fixed_actions,
                         "prefix": prefix, "horizon": HORIZON,
                         "feedback_intervention": tensor_digest(feedback_override) if feedback_override is not None else None})
    state = model.encode(public)
    native = native_factory(model_sha, profile.digest, directory / "native") if native_factory else None
    generation = {m: 0 for m in MODALITIES}
    budget, costs, events, states, action_log, critics, teacher = INITIAL_BUDGET, [], [], [], [], [], []
    tensor_checkpoints = []
    episode_anchor = {"schema": "hepta.joint-generation.episode-anchor.v1",
                      "parameter_snapshot_sha256": model_sha, "input_sha256": input_sha,
                      "profile_sha256": profile.digest}
    previous_wall, previous_cpu = begun, cpu_start
    states.append(_snapshot(profile, state, context=context_id, input_sha=input_sha, model_sha=model_sha,
                            policy_sha=policy_sha, index=0, elapsed=0, budget=budget, generation=generation))
    failure = None
    artifacts, observed, raw_observed, total_log_probability = {}, -1.0, None, state.shared.sum() * 0

    def record(action, law, *, terminal="ongoing", artifacts=None):
        nonlocal budget, previous_wall, previous_cpu
        wall, cpu = time.perf_counter(), cpu_seconds()
        usage = {"wall_seconds": wall - previous_wall, "cpu_seconds": max(0.0, cpu - previous_cpu)}
        amount = (TARIFF.get(action, 0) + TARIFF["cpu_second"] * usage["cpu_seconds"]
                  + TARIFF["wall_second"] * usage["wall_seconds"] + (TARIFF["encode"] if not events else 0))
        cost = CostEvent(f"{context_id}.{seed}.{len(events)}", amount, kind=action)
        costs.append(cost); budget -= amount
        if budget < 0:
            raise RuntimeError("Executed physical cost exceeded declared finite research budget")
        next_state = _snapshot(profile, state, context=context_id, input_sha=input_sha, model_sha=model_sha,
            policy_sha=policy_sha, index=len(events) + 1, elapsed=round((wall - begun) * 1e6), budget=budget,
            generation=generation, artifacts=artifacts)
        events.append(DecisionEvent(f"event.{len(events)}", profile.digest, states[-1].digest,
            next_state.digest, action, law, tensor_digest({"actor": rng.get_state(), "emission": emission_rng.get_state()}), (cost,), terminal))
        states.append(next_state)
        previous_wall, previous_cpu = wall, cpu
        return usage

    for index in range(HORIZON + 1):
        validate_runtime_features(profile, {"encoded_input": state.context, "latent_state": state.shared,
            "committed_prefix": {}, "remaining_budget": budget, "remaining_steps": HORIZON-index,
            "clocks": state.steps, "uncertainty": state.feedback})
        log_law, critic = model.policy(state, budget / INITIAL_BUDGET, HORIZON)
        critics.append(critic[0])
        features = model.features(state, budget / INITIAL_BUDGET).detach()
        forced = index < len(prefix) or strategy == "fixed" or index == HORIZON
        if index == HORIZON:
            selected = ACTIONS.index("stop")
        elif index < len(prefix):
            selected = ACTIONS.index(prefix[index])
        elif strategy == "fixed":
            selected = ACTIONS.index(fixed_actions[min(index, len(fixed_actions)-1)])
        elif strategy == "planner":
            selected = planner_action(model, state, public, budget / INITIAL_BUDGET, profile)
        elif strategy == "greedy":
            selected = int(log_law.argmax(-1).item())
        else:
            selected = int(torch.multinomial(log_law.detach().exp(), 1, generator=rng).item())
        action = ACTIONS[selected]
        if not torch.isfinite(log_law[0, selected]):
            raise ValueError("Selected action violates the registered horizon/STOP mask")
        stochastic = strategy == "dynamic" and not forced
        law = _probabilities(log_law) if stochastic else tuple((a, float(i == selected)) for i, a in enumerate(ACTIONS))
        if stochastic:
            total_log_probability = total_log_probability + log_law[0, selected]
        teacher.append((features, selected))
        before = tensor_digest(state.tensors())
        trace = {"step": index, "profile_sha256": profile.digest, "model_sha256": model_sha,
                 "state_sha256": before, "action": action, "joint_action_probabilities": law}
        if tensor_checkpoints:
            trace["tensor_checkpoint_sha256"] = tensor_checkpoints[-1]["payload_sha256"]
        dispatched = []

        def dispatch():
            nonlocal state
            state, _ = model.advance(state, action, public, feedback_override=feedback_override)
            dispatched.append(True)
            return {"artifact_refs": {}, "artifact_sha256": {}, "public_feedback": 0.0,
                    "final_state_digest": tensor_digest(state.tensors())}

        try:
            if native is not None and action != "stop":
                native.perform(action, trace, dispatch)
                if not dispatched or native.finished:
                    failure = "native_abstention"
                if native_reopen_at == index and not native.finished:
                    native.reopen()
            else:
                dispatch()
        except Exception as exc:
            failure = f"execution_failed: {type(exc).__name__}: {exc}"
            if native is not None:
                native.abort(reason=failure)
        if action in MODALITIES:
            generation[action] += bool(dispatched)
        elif action == "shared" and dispatched:
            generation = {m: n+1 for m, n in generation.items()}
        usage = record(action, law)
        action_log.append({**trace, "after_sha256": tensor_digest(state.tensors()),
                           "feedback": state.feedback.detach().tolist(), **usage,
                           "dispatched": bool(dispatched)})
        if native is not None and native_reopen_at == index and not failure and action != "stop":
            from .checkpoint import load_checkpoint, restore_named_rngs, save_checkpoint
            checkpoint_path = directory / "TENSOR_CONTINUATION.pt"
            anchored = {**episode_anchor, "remaining_budget": budget, "generation_steps": generation,
                        "policy_snapshot_sha256": policy_sha, "strategy": strategy,
                        "audio_rate": audio_rate, "frame_ms": frame_ms,
                        "event_prefix": [asdict(e) for e in events], "state_prefix": [asdict(s) for s in states]}
            identity = save_checkpoint(checkpoint_path, model, state, rng, profile, public,
                metadata=anchored, named_rngs={"actor": rng, "emission": emission_rng})
            restored, resumed, _, info = load_checkpoint(checkpoint_path, profile=profile, public=public)
            if tensor_digest(resumed.tensors()) != tensor_digest(state.tensors()):
                raise ValueError("Actual native episode tensor restore changed its continuation")
            model, state = restored, resumed
            streams = restore_named_rngs(info); rng, emission_rng = streams["actor"], streams["emission"]
            tensor_checkpoints.append({**identity, "restored_in_this_process": True,
                                       "separate_OS_process_equivalence": "independently_tested"})
        if failure or action == "stop":
            break

    terminal_kind = "failed" if failure and failure.startswith("execution_failed") else "refused" if failure else "delivered"
    critics.append(model.delivery_critic(model.features(state, budget / INITIAL_BUDGET).detach())[0, 0])
    if not failure:
        try:
            sampled, _, emission_score = model.sample(state, emission_rng, deterministic=deterministic_emission)
            if not deterministic_emission:
                total_log_probability = total_log_probability + emission_score[0]

            def deliver():
                nonlocal artifacts, observed, raw_observed
                readback, artifacts = write_read(sampled, directory / "outputs", audio_rate, frame_ms)
                observed = float(observe(readback))
                if not math.isfinite(observed) or not profile.ndu.utility_bounds[0] <= observed <= profile.ndu.utility_bounds[1]:
                    raise ValueError("Observer returned nonfinite or out-of-contract utility")
                raw_observed = observed
                names = {"text": "text.txt", "image": "image.png", "audio": "audio.wav", "video": "video.gif"}
                return {"artifact_refs": {m: str(directory / "outputs" / n) for m, n in names.items()},
                        "artifact_sha256": artifacts, "public_feedback": 0.0,
                        "final_state_digest": tensor_digest(state.tensors())}

            if native is None:
                deliver()
            else:
                result = native.perform("delivery", {"profile_sha256": profile.digest,
                    "model_sha256": model_sha, "terminal_state_sha256": tensor_digest(state.tensors())}, deliver)
                if not result.get("executed") or result.get("native_abstain_after_dispatch"):
                    terminal_kind, failure, observed = "refused", "native_delivery_refused", -1.0
        except Exception as exc:
            terminal_kind, failure, observed = "failed", f"{type(exc).__name__}: {exc}", -1.0
    if native is not None and not native.finished:
        try:
            native.perform("stop", {"profile_sha256": profile.digest, "artifact_sha256": artifacts})
        except Exception as exc:
            terminal_kind, failure, observed = "failed", f"native_close_failed: {exc}", -1.0
            native.abort(reason=failure)
    if tensor_digest(model.state_dict()) != model_sha:
        raise ValueError("Selected parameters changed during execution")
    validate_episode(profile, tuple(states), tuple(events))
    # Write a genuine draft before the terminal meter closes. This charges
    # hashing, prefix validation and receipt serialization to every arm.
    draft = {"states": [asdict(s) for s in states], "events": [asdict(e) for e in events],
             "artifacts": artifacts, "observed_utility": observed, "terminal_kind": terminal_kind}
    (directory / "AUDIT_DRAFT.json").write_text(json.dumps(draft, sort_keys=True, allow_nan=False))
    record("delivery", (("delivery", 1.0),), terminal=terminal_kind, artifacts=artifacts)
    outcome = DeliveredOutcome(context_id, str(seed), source_id, observed, tuple(costs),
        tuple(sorted(artifacts.items())), profile.ndu.observer_sha256, profile.ndu.objective_sha256,
        profile.ndu.continuation_sha256, terminal_kind)
    net = validate_episode(profile, tuple(states), tuple(events), outcome)
    suffix = [observed - sum(c.amount for c in costs[i:]) for i in range(len(critics))]
    data = {"schema": "hepta.joint-output.actual-trajectory.v1", "profile": profile.to_dict(),
            "profile_sha256": profile.digest, "state_chain": [asdict(s) for s in states],
            "events": [asdict(e) for e in events], "outcome": asdict(outcome), "actions": action_log,
            "net_return": net, "actual_cost": sum(c.amount for c in costs), "failure": failure,
            "raw_observed_utility_before_native_refusal": raw_observed,
            "parameter_snapshot_sha256": model_sha, "source_id": source_id, "seed": seed,
            "policy_snapshot_sha256": policy_sha,
            "strategy": strategy, "emission_law": "degenerate_mean_argmax" if deterministic_emission else "stochastic",
            "contract_validated": True, "native_receipt": native.receipt() if native else None,
            "tensor_checkpoint_restores": tensor_checkpoints,
            "native_integration_executed": native is not None,
            "suffix_return_convention": "terminal_utility_minus_costs_from_current_decision_including_first_encoder",
            "semantic_qualification": False}
    (directory / "TRAJECTORY.json").write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n")
    # Start exactly where the final ledger meter stopped: includes final state
    # hashing, contract validation, receipt construction and actual JSON write.
    audit_wall, audit_cpu = time.perf_counter() - previous_wall, cpu_seconds() - previous_cpu
    data["audit_close_wall_seconds"], data["audit_close_cpu_seconds"] = audit_wall, audit_cpu
    data["net_with_audit_close"] = net - TARIFF["cpu_second"] * audit_cpu - TARIFF["wall_second"] * audit_wall
    return Episode(data, net, total_log_probability, critics, suffix, state, teacher)
