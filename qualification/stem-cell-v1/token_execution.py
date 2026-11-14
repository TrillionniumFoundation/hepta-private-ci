"""Public token Reader execution with prospective, empirical native control.

The verifier reports learned agreement, not semantic truth. The frozen critic's
one-step residual bounds are empirical and do not establish future support.
"""
import copy
import math
import re
import time

import torch

from execution_meter import WorkLedger
from group_critic import row_features
from next_round_matrix import _digest
from paired_execution import PHASES
from reader_execution import _frozen, _tensor_digest, observed_verifier_feedback
from system2_execution import PublicTask, Verification, run_reasoning
from transformer_work import PROFILE as ARITHMETIC_PROFILE

TENSORS = ("facts", "question", "candidate", "fact_mask", "question_mask", "candidate_mask", "sentence_indices")
FIELDS = {*TENSORS, "feature_sha256", "source_sha256"}
MODES = {"fixed1", "fixed3", "reset3", "native_ndu", "no_verifier"}


def public_snapshot(public, model):
    """Own an exact, bounded snapshot; outcome fields cannot cross this boundary."""
    if not isinstance(public, dict) or set(public) != FIELDS:
        raise ValueError("exact public token fields required; no labels or annotations")
    if any(not isinstance(public[key], str) or not re.fullmatch("[0-9a-f]{64}", public[key])
           for key in ("feature_sha256", "source_sha256")):
        raise ValueError("source and feature SHA256 required")
    values = [public[key] for key in TENSORS]
    if (any(not isinstance(value, torch.Tensor) or value.device.type != "cpu" for value in values)
            or sum(value.numel() for value in values) > 16_777_216
            or any(value.dtype != torch.float32 or not torch.isfinite(value).all() for value in values[:3])
            or any(value.dtype != torch.bool for value in values[3:6])
            or values[0].ndim != 4 or values[0].shape[0] != 1
            or values[6].shape != values[0].shape[:2] or values[6].dtype != torch.int64
            or values[6].min().item() < 0 or values[6].max().item() > 4095):
        raise ValueError("bounded finite CPU float32 tokens and boolean masks required")
    model._validate(*values[:6])
    return {**public, **{key: value.detach().clone() for key, value in zip(TENSORS, values)}}


def _profile(profile, model, verifier, critic, native):
    bounds = copy.deepcopy(profile)
    groups = []
    for key in ("reader_source_groups", "verifier_source_groups"):
        values = bounds.get(key)
        if (not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 16384
                or len(set(values)) != len(values)
                or any(not isinstance(v, str) or not 1 <= len(v.encode()) <= 256 for v in values)):
            raise ValueError("explicit bounded reader and verifier training sources required")
        groups.append(set(values))
    if groups[0] & groups[1] or model is verifier:
        raise ValueError("separately trained independent verifier required")
    if {p.data_ptr() for p in model.parameters()} & {p.data_ptr() for p in verifier.parameters()}:
        raise ValueError("reader and verifier parameter storage must be independent")
    if native:
        critic.assert_frozen()
        critic_groups = [set(critic.metadata["source_groups"][key]) for key in ("fit", "calibration")]
        if (not all(critic_groups) or critic_groups[0] & critic_groups[1]
                or any(group & trained for group in critic_groups for trained in groups)):
            raise ValueError("critic fit/calibration and reader/verifier sources must be disjoint")
    for key, default in (("wall_time_ns", 30_000_000_000), ("formula_work_cap", 10**12),
                         ("duration_upper_ns", 1_000_000_000), ("formula_work_upper", 10**9),
                         ("request_ttl_ns", 60_000_000_000)):
        bounds.setdefault(key, default)
        if type(bounds[key]) is not int or bounds[key] < 1:
            raise ValueError("positive integer resource bounds required")
    for key, default in (("cost_per_formula_flop", 1e-10), ("cost_per_latency_ns", 1e-11),
                         ("minimum_margin", 0.), ("discount_rate_per_second", 0.)):
        bounds.setdefault(key, default)
        if type(bounds[key]) not in (int, float) or not math.isfinite(bounds[key]) or bounds[key] < 0:
            raise ValueError("finite nonnegative utility costs required")
    return bounds


def execute_token_reader(public, model, verifier, critic=None, *, mode="fixed3",
                         profile_bounds, native_binary=None, collect_critic_features=False):
    """Execute real callbacks; native decisions precede the next proposal.

    Optional critic features expose only state/logit observables. An offline
    caller may score complete trajectories afterward using inner training labels.
    Training source declarations are checked and bound, not authenticated here.
    """
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    if mode not in MODES or not isinstance(profile_bounds, dict) or type(collect_critic_features) is not bool:
        raise ValueError("registered mode, resource profile and typed collection flag required")
    native = mode == "native_ndu"
    if verifier is None or native and (critic is None or native_binary is None):
        raise ValueError("independent verifier and explicitly selected native artifacts required")
    rounds = 1 if mode == "fixed1" else 3
    if rounds > model.max_hops or verifier.max_hops < 1:
        raise ValueError("bounded model recurrence required")
    bounds = _profile(profile_bounds, model, verifier, critic, native)
    before = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier))
    if native:
        before.update(critic_sha256=critic.params_sha256, critic_metadata_sha256=_digest(critic.metadata))
    public = public_snapshot(public, model)
    values = tuple(public[key] for key in TENSORS)
    features = values[:6]
    verifier._validate(*features)
    tensor_sha = _tensor_digest(*values)
    has_evidence = bool(public["fact_mask"].any().item())
    policy = dict(schema="hepta.execution-meter-policy.v2", arithmetic_profile=ARITHMETIC_PROFILE, mode="strict",
                  wall_time_ns=bounds["wall_time_ns"], max_process_rss_bytes=None,
                  rapl_zone=None, rapl_max_power_watts=None)
    meter = WorkLedger(policy, dict.fromkeys(PHASES, bounds["formula_work_cap"]))
    now = time.time_ns()
    if native and not 0 < critic.metadata["cutoff_ns"] < now:
        raise ValueError("critic fit must precede inference")
    task = PublicTask("MultiRC public token boundary " + public["source_sha256"], now)
    profile_sha = _digest(dict(bounds=bounds, artifacts=before, mode=mode,
                               collect_critic_features=collect_critic_features, meter_policy=policy))
    state = logits = feedback = prepared = verifier_prepared = expected_state = None
    pending = None
    support_violated = False
    records, observations, decisions = [], [], []

    def propose(_task, _previous, _feedback):
        nonlocal state, logits, prepared
        if expected_state is not None and _tensor_digest(state) != expected_state:
            raise ValueError("state changed across prospective continuation boundary")
        with torch.no_grad():
            if prepared is None:
                prepared = model.prepare(*features)
            state, logits, _, _ = model.step_prepared(prepared, None if mode == "reset3" else state, feedback)
            if (state.shape != (1, model.hidden_dim) or logits.shape != (1, 2)
                    or state.requires_grad or logits.requires_grad or not torch.isfinite(state).all()
                    or not torch.isfinite(logits).all() or state.abs().max().item() > 1.000001):
                raise ValueError("bounded finite state and binary logits required")
            state, logits = state.detach().clone(), logits.detach().clone()
            record = dict(step=len(records) + 1, prediction=int(logits.argmax(-1).item()),
                          probabilities=logits.softmax(-1)[0].tolist(), state_sha256=_tensor_digest(state))
            if collect_critic_features and record["step"] < rounds:
                record["critic_features"] = row_features(state, logits, record["step"], rounds)
            record["candidate_sha256"] = _digest(record)
            records.append(record)
        return record["candidate_sha256"]

    def check(_task, candidate):
        nonlocal feedback, verifier_prepared
        if candidate != records[-1]["candidate_sha256"]:
            raise ValueError("candidate no longer binds the current state")
        if mode == "no_verifier":
            feedback = values[0].new_zeros(1, 4)
            observations.append(dict(step=len(records), enabled=False, accepted=False))
            return Verification(False, "verifier_disabled")
        with torch.no_grad():
            if verifier_prepared is None:
                verifier_prepared = verifier.prepare(*features)
            _, verifier_logits, _, _ = verifier.step_prepared(verifier_prepared)
            observed = observed_verifier_feedback(verifier_logits, records[-1]["prediction"], has_evidence)
            feedback = observed.pop("feedback").detach().clone()
        observations.append(dict(step=len(records), enabled=True, **observed))
        return Verification(observed["accepted"] and (native or len(records) == rounds), _digest(observed))

    def measured(component, callback, own_scopes=False):
        def invoke(*args):
            nonlocal pending, support_violated
            key = "search:" + component
            previous = dict(meter.rows.get(key, {}))
            if own_scopes:
                result = callback(*args)
            else:
                with meter.scope("search", component):
                    result = callback(*args)
            current_cost = meter.rows[key]
            records[-1].setdefault("callback_costs", {})[component] = {
                output: current_cost[source] - previous.get(source, 0)
                for output, source in (("formula_flops", "formula_flops"), ("cpu_ns", "cpu_ns"), ("wall_ns", "elapsed_ns"))}
            if component == "verifier" and pending is not None:
                prior, decision = pending
                current = meter.budget_state("search")
                work = (prior["remaining_formula_work"] - current["remaining_formula_work"]
                        if current["remaining_formula_work"] is not None else None)
                duration = prior["remaining_wall_ns"] - current["remaining_wall_ns"]
                support_violated = (work is None or not 0 <= work <= bounds["formula_work_upper"]
                                    or not 0 <= duration <= bounds["duration_upper_ns"])
                decision.update(observed_next_formula_work=work, observed_next_wall_ns=duration,
                                realized_support_bounds_satisfied=not support_violated)
                pending = None
                if support_violated:
                    return Verification(False, "native_continuation_support_violated")
            return result
        return invoke

    def value(_task, _candidate, _feedback, rounds_left):
        nonlocal expected_state, pending
        with meter.scope("search", "value"):
            expected_state = _tensor_digest(state)
            if support_violated:
                return 0., 1.
            if not native:
                return 1., 0.
            prediction = critic.predict(row_features(state, logits, len(records), rounds))
        from native_group_control import build_control_request, run_native_control
        resources, boundary = meter.budget_state("search"), time.time_ns()
        context = dict(source_sha256=public["source_sha256"], tensor_sha256=tensor_sha,
                       candidate=records[-1], feedback=observations[-1], resources=resources,
                       step=len(records), rounds_left=rounds_left, as_of_ns=boundary)
        bindings = dict(objective_sha256=_digest("multirc-candidate-correctness-fixed-v1"),
            subject_sha256=_digest("agent:multirc-token-reader-research"), context_sha256=_digest(context),
            model_sha256=before["model_sha256"], critic_sha256=before["critic_sha256"],
            feature_sha256=public["feature_sha256"], workspace_sha256=expected_state,
            policy_sha256=profile_sha, support_sha256=_digest(dict(prediction=prediction,
                critic_metadata_sha256=before["critic_metadata_sha256"])))
        duration, work = bounds["duration_upper_ns"], bounds["formula_work_upper"]
        scenario = dict(probability=1., continue_lower=prediction["continue_lower"],
            discount=math.exp(-bounds["discount_rate_per_second"] * duration / 1e9),
            compute_cost=work * bounds["cost_per_formula_flop"], time_cost=duration * bounds["cost_per_latency_ns"],
            formula_work_upper=work, duration_upper_ns=duration)
        with meter.scope("search", "value"):
            request = build_control_request(bindings=bindings, generation=1, as_of_ns=boundary,
                critic_cutoff_ns=critic.metadata["cutoff_ns"], observed_through_ns=boundary,
                expires_at_ns=now + bounds["request_ttl_ns"], stop_upper=prediction["stop_upper"],
                minimum_margin=bounds["minimum_margin"], scenarios=[scenario],
                remaining_formula_work=resources["remaining_formula_work"], remaining_wall_ns=resources["remaining_wall_ns"])
            decision = run_native_control(request, native_binary,
                timeout_seconds=max(.001, min(5., resources["remaining_wall_ns"] / 1e9)))
        decision.update(context=context, bindings=bindings, request=request, critic_forecast=prediction,
                        empirical_support_not_confidence_bounds=True)
        decisions.append(decision)
        if decision["continue_computation"]:
            pending = meter.budget_state("search"), decision
            return 1., 0.
        return 0., 1.

    result = run_reasoning(task, propose=measured("proposer", propose), verify=measured("verifier", check),
        continue_values=measured("value", value, own_scopes=True), value_profile="token-reader-prospective-empirical-native.v1" if native else "token-reader-fixed.v1",
        max_rounds=rounds, max_calls=rounds * 3)
    after = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier))
    if native:
        critic.assert_frozen()
        after.update(critic_sha256=critic.params_sha256, critic_metadata_sha256=_digest(critic.metadata))
    if before != after or _tensor_digest(*values) != tensor_sha:
        raise ValueError("inference mutated frozen artifacts or its public snapshot")
    work = meter.report()
    child_cpu = None if any(d.get("child_cpu_ns") is None for d in decisions) else sum(d["child_cpu_ns"] for d in decisions)
    child_wall = None if any(d.get("child_wall_ns") is None for d in decisions) else sum(d["child_wall_ns"] for d in decisions)
    qualified = bool(decisions) and all(d.get("native_executed") and d.get("reference_match") and "error_type" not in d for d in decisions)
    request_cpu, request_wall = time.process_time_ns() - started_cpu, time.perf_counter_ns() - started_wall
    result.update(mode=mode, prediction=records[-1]["prediction"] if records else None,
        steps=len(records), step_records=records, verifier_observations=observations,
        native_control_decisions=decisions, artifact_digests_before=before, artifact_digests_after=after,
        feature_sha256=public["feature_sha256"], source_sha256=public["source_sha256"], tensor_sha256=tensor_sha,
        profile_sha256=profile_sha, work_observation=work, native_support_violated=support_violated,
        native_controller_execution_qualified=qualified, native_controller_failed_closed=bool(decisions) and not qualified,
        request_costs=dict(self_cpu_ns=request_cpu, native_child_cpu_ns=child_cpu,
            accounted_cpu_ns=None if child_cpu is None else request_cpu + child_cpu,
            wall_ns=request_wall, native_child_wall_ns=child_wall,
            scope="entry_through_frozen_artifact_and_snapshot_reverification_including_meter_overhead",
            wall_includes_native_subprocess=True, complete_formula_flops=None if decisions else work["phase_flops"]["search"],
            shared_encoder_included=False, training_and_calibration_included=False,
            child_cpu_attribution="process_reaped_children_delta_may_include_concurrent_children"),
        verifier_acceptance_is_semantic_truth=False, empirical_intervals_are_certified_support=False,
        training_provenance_authenticated=False, native_production_owner_integrated=False)
    return result
