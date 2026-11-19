"""Label-free learned Reader callbacks in the existing bounded System2 loop.

Verifier acceptance is model agreement, never independent semantic truth.
Native control consumes prospective empirical support, not realized outcomes.
"""

import copy
import hashlib
import json
import math
import re
import time
from dataclasses import fields, is_dataclass

import torch

from execution_meter import WorkLedger
from group_critic import row_features
from group_loop import parameter_digest
from next_round_matrix import _digest
from paired_execution import PHASES
from system2_execution import PublicTask, Verification, run_reasoning

NATIVE_PROFILE = "native_q32_prospective_empirical_reader_continuation.v1"
MODES = {"static", "static1", "fixed", "fixed3", "adaptive", "native_ndu",
         "no_verifier", "reset_state"}
_FEATURE_FIELDS = {"facts", "query", "mask", "feature_sha256", "source_sha256"}


def _tensor_digest(*values):
    result = hashlib.sha256()
    for value in values:
        result.update(str(tuple(value.shape)).encode())
        result.update(str(value.dtype).encode())
        result.update(value.detach().contiguous().numpy().tobytes())
    return result.hexdigest()


def observed_verifier_feedback(logits, candidate, has_evidence, threshold=.9):
    """Four observable features: verifier p0/p1, agreement, evidence present."""
    if (not isinstance(logits, torch.Tensor) or logits.shape != (1, 2)
            or logits.dtype != torch.float32 or logits.device.type != "cpu"
            or not torch.isfinite(logits).all() or type(candidate) is not int
            or candidate not in (0, 1) or type(has_evidence) is not bool
            or type(threshold) not in (int, float) or not .5 <= threshold <= 1):
        raise ValueError("finite binary verifier and public candidate required")
    probabilities = logits.detach().softmax(-1)
    prediction = probabilities.argmax(-1).item()
    confidence = probabilities.max().item()
    agreement = prediction == candidate
    feedback = torch.cat((probabilities, logits.new_tensor(
        [[float(agreement), float(has_evidence)]])), dim=1)
    return dict(prediction=prediction, confidence=confidence, agreement=agreement,
                accepted=has_evidence and agreement and confidence >= threshold,
                feedback=feedback)


def _features(public_features, model):
    if is_dataclass(public_features) and not isinstance(public_features, type):
        if {f.name for f in fields(public_features)} != _FEATURE_FIELDS:
            raise ValueError("public feature dataclass must contain no outcome fields")
        public_features = {k: getattr(public_features, k) for k in _FEATURE_FIELDS}
    if not isinstance(public_features, dict) or set(public_features) != _FEATURE_FIELDS:
        raise ValueError("exact public feature whitelist required; no labels or targets")
    for key in ("feature_sha256", "source_sha256"):
        if not isinstance(public_features[key], str) or not re.fullmatch("[0-9a-f]{64}", public_features[key]):
            raise ValueError("source and feature manifest SHA256 required")
    facts, query, mask = (public_features[k] for k in ("facts", "query", "mask"))
    if (not all(isinstance(v, torch.Tensor) for v in (facts, query, mask))
            or facts.ndim != 3 or facts.shape[0] != 1 or not 1 <= facts.shape[1] <= 256
            or facts.shape[2] != model.input_dim or query.shape != (1, model.input_dim)
            or mask.shape != facts.shape[:2] or mask.dtype != torch.bool
            or any(v.device.type != "cpu" for v in (facts, query, mask))
            or any(v.dtype != torch.float32 or not torch.isfinite(v).all() for v in (facts, query))):
        raise ValueError("bounded finite CPU fact/query tensors and boolean mask required")
    # Own a snapshot: caller mutation cannot alter the running evidence boundary.
    return {**public_features, "facts": facts.detach().clone(),
            "query": query.detach().clone(), "mask": mask.detach().clone()}


def _frozen(model):
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("selected model and verifier must be frozen")
    return parameter_digest(model)


def execute_reader(public_features, model, verifier, critic, *, mode="native_ndu",
                   max_steps=3, native_binary=None, profile_bounds, ledger=None):
    """Execute recurrent binary evidence reading without a case or target input.

    Caller supplies disjoint reader/verifier training groups. Their declaration
    is bound and checked for overlap, not authenticated here. Strict ATen work
    covers callbacks; native child work remains explicitly outside its formula.
    """
    if mode not in MODES or type(max_steps) is not int or not 1 <= max_steps <= 8:
        raise ValueError("registered mode and bounded recurrence required")
    mode = {"static1": "static", "fixed3": "fixed"}.get(mode, mode)
    rounds = 1 if mode == "static" else max_steps
    if rounds > model.max_hops or not isinstance(profile_bounds, dict):
        raise ValueError("reader hop and declared profile required")
    bounds = copy.deepcopy(profile_bounds)
    threshold = bounds.get("verifier_threshold", .9)
    if threshold != .9:
        raise ValueError("this registered study uses verifier threshold 0.9")
    source_sets = []
    for key in ("reader_source_groups", "verifier_source_groups"):
        groups = bounds.get(key)
        if (not isinstance(groups, (list, tuple)) or not groups or len(groups) > 16384
                or any(not isinstance(g, str) or not 1 <= len(g.encode()) <= 256 for g in groups)
                or len(set(groups)) != len(groups)):
            raise ValueError("explicit bounded reader/verifier training source groups required")
        source_sets.append(set(groups))
    if source_sets[0] & source_sets[1]:
        raise ValueError("reader and verifier training sources overlap")
    if verifier is None or verifier is model:
        raise ValueError("a separately frozen verifier is required, including its ablation")
    model_sha, verifier_sha = _frozen(model), _frozen(verifier)
    if {p.data_ptr() for p in model.parameters()} & {p.data_ptr() for p in verifier.parameters()}:
        raise ValueError("reader and verifier cannot share parameter storage")
    critic.assert_frozen()
    critic_sha, critic_metadata_sha = critic.params_sha256, _digest(critic.metadata)
    public = _features(public_features, model)
    facts, query, mask = (public[k] for k in ("facts", "query", "mask"))
    evidence_digest = _tensor_digest(facts, query, mask)
    has_evidence = bool(mask.any().item())
    for key, default in (("duration_upper_ns", 1_000_000_000), ("formula_work_upper", 100_000_000),
                         ("wall_time_ns", 30_000_000_000), ("formula_work_cap", 10**10),
                         ("request_ttl_ns", 60_000_000_000)):
        bounds.setdefault(key, default)
        if type(bounds[key]) is not int or bounds[key] <= 0:
            raise ValueError("positive integer resource profile required")
    for key, default in (("cost_per_formula_flop", 1e-10), ("cost_per_latency_ns", 1e-11),
                         ("discount_rate_per_second", 0.), ("minimum_margin", 0.)):
        bounds.setdefault(key, default)
        if type(bounds[key]) not in (int, float) or not math.isfinite(bounds[key]) or bounds[key] < 0:
            raise ValueError("finite nonnegative cost profile required")
    if mode == "native_ndu" and native_binary is None:
        raise ValueError("native control requires the explicitly selected binary")
    policy = dict(schema="hepta.execution-meter-policy.v1", mode="strict",
                  wall_time_ns=bounds["wall_time_ns"], max_process_rss_bytes=None,
                  rapl_zone=None, rapl_max_power_watts=None)
    meter = ledger if ledger is not None else WorkLedger(policy, dict.fromkeys(PHASES, bounds["formula_work_cap"]))
    now = time.time_ns()
    cutoff = critic.metadata["cutoff_ns"]
    if type(cutoff) is not int or not 0 < cutoff < now:
        raise ValueError("critic fit must precede inference")
    expires = now + bounds["request_ttl_ns"]
    profile_sha = _digest(dict(bounds=bounds, model_sha256=model_sha, verifier_sha256=verifier_sha,
                               critic_sha256=critic_sha, critic_metadata_sha256=critic_metadata_sha,
                               actual_meter_policy=meter.policy, actual_phase_caps=meter.caps))
    task = PublicTask("MultiRC public feature boundary " + public["source_sha256"], now)
    state, logits, feedback_tensor = None, None, None
    step_records, checks, decisions = [], [], []
    expected_state, pending_segment, support_violated = None, None, False

    def propose(_task, _previous, _feedback):
        nonlocal state, logits
        if expected_state is not None and _tensor_digest(state) != expected_state:
            raise ValueError("reader state changed across continuation boundary")
        with torch.no_grad():
            state, logits = model.step(facts, query,
                None if mode == "reset_state" else state, feedback_tensor, mask)
        if (state.shape != (1, model.hidden_dim) or logits.shape != (1, 2)
                or state.requires_grad or logits.requires_grad or not torch.isfinite(state).all()
                or not torch.isfinite(logits).all() or state.abs().max().item() > 1.000001):
            raise ValueError("bounded finite reader state and binary logits required")
        state, logits = state.detach().clone(), logits.detach().clone()
        probabilities = logits.softmax(-1)[0].tolist()
        record = dict(step=len(step_records) + 1, prediction=int(logits.argmax(-1).item()),
                      probabilities=probabilities, state_sha256=_tensor_digest(state),
                      feature_sha256=public["feature_sha256"], tensor_sha256=evidence_digest)
        step_records.append(record)
        return json.dumps(record, sort_keys=True, separators=(",", ":"))

    def check(_task, candidate):
        nonlocal feedback_tensor
        if json.loads(candidate) != step_records[-1]:
            raise ValueError("candidate no longer binds the current reader state")
        if mode == "no_verifier":
            feedback_tensor = facts.new_zeros(1, 4)
            checks.append(dict(step=len(step_records), enabled=False, accepted=False))
            return Verification(False, "verifier_disabled")
        with torch.no_grad():
            _, verifier_logits = verifier.step(facts, query, state=None, feedback=None, mask=mask)
            observed = observed_verifier_feedback(verifier_logits, step_records[-1]["prediction"],
                                                   has_evidence, threshold)
        feedback_tensor = observed.pop("feedback").detach().clone()
        checks.append(dict(step=len(step_records), enabled=True, **observed))
        accepted = observed["accepted"] and (mode not in {"fixed", "reset_state"} or len(step_records) == rounds)
        return Verification(accepted, json.dumps(observed, sort_keys=True))

    def measured(component, callback):
        def invoke(*args):
            nonlocal pending_segment, support_violated
            with meter.scope("search", component):
                result = callback(*args)
            if component == "verifier" and pending_segment is not None:
                remaining = meter.budget_state("search")
                before, decision = pending_segment
                work = (before["remaining_formula_work"] - remaining["remaining_formula_work"]
                        if remaining["remaining_formula_work"] is not None else None)
                duration = before["remaining_wall_ns"] - remaining["remaining_wall_ns"]
                support_violated = (work is None or work < 0 or work > bounds["formula_work_upper"]
                                    or duration < 0 or duration > bounds["duration_upper_ns"])
                decision.update(observed_next_formula_work=work, observed_next_wall_ns=duration,
                                realized_support_bounds_satisfied=not support_violated)
                pending_segment = None
                if support_violated:
                    result = Verification(False, "native_continuation_support_violated")
            return result
        return invoke

    def value(_task, _candidate, _feedback, rounds_left):
        nonlocal expected_state, pending_segment
        with meter.scope("search", "value"):
            expected_state = _tensor_digest(state)
            if support_violated:
                return 0., 1.
            if mode not in {"adaptive", "native_ndu"}:
                return 1., 0.
            prediction = critic.predict(row_features(state, logits, len(step_records), rounds))
            if mode == "adaptive":
                return prediction["continue_probability"], prediction["stop_probability"]
        # This boundary follows the real critic cost. Native has its own scope;
        # no nested wall timer is added to the total ledger elapsed time.
        resources = meter.budget_state("search")
        if resources["remaining_formula_work"] is None:
            decisions.append(dict(continue_computation=False, reason="incomplete_formula_coverage"))
            return 0., 1.
        from native_group_control import build_control_request, run_native_control
        boundary = time.time_ns()
        context = dict(task_sha256=_digest(task.prompt), source_sha256=public["source_sha256"],
                       feature_sha256=public["feature_sha256"], tensor_sha256=evidence_digest,
                       verifier_sha256=verifier_sha, step=len(step_records), rounds_left=rounds_left,
                       candidate=step_records[-1], feedback=checks[-1], resources=resources,
                       as_of_ns=boundary)
        bindings = dict(objective_sha256=_digest("multirc-candidate-correctness-fixed-v1"),
                        subject_sha256=_digest("agent:multirc-reader-research"),
                        context_sha256=_digest(context), model_sha256=model_sha,
                        critic_sha256=critic_sha, feature_sha256=public["feature_sha256"],
                        workspace_sha256=expected_state, policy_sha256=profile_sha,
                        support_sha256=_digest(dict(prediction=prediction, critic_metadata_sha256=critic_metadata_sha)))
        duration, work = bounds["duration_upper_ns"], bounds["formula_work_upper"]
        scenario = dict(probability=1., continue_lower=prediction["continue_lower"],
                        discount=math.exp(-bounds["discount_rate_per_second"] * duration / 1e9),
                        compute_cost=work * bounds["cost_per_formula_flop"],
                        time_cost=duration * bounds["cost_per_latency_ns"],
                        formula_work_upper=work, duration_upper_ns=duration)
        with meter.scope("search", "value"):
            request = build_control_request(bindings=bindings, generation=1, as_of_ns=boundary,
                critic_cutoff_ns=cutoff, observed_through_ns=boundary, expires_at_ns=expires,
                stop_upper=prediction["stop_upper"], minimum_margin=bounds["minimum_margin"],
                scenarios=[scenario], remaining_formula_work=resources["remaining_formula_work"],
                remaining_wall_ns=resources["remaining_wall_ns"])
            decision = run_native_control(request, native_binary,
                timeout_seconds=max(.001, min(5., resources["remaining_wall_ns"] / 1e9)))
        decision.update(context=context, bindings=bindings, critic_forecast=prediction,
                        request=request, empirical_support_not_confidence_bounds=True)
        decisions.append(decision)
        if decision["continue_computation"]:
            pending_segment = meter.budget_state("search"), decision
            return 1., 0.
        return 0., 1.

    result = run_reasoning(task, propose=measured("proposer", propose), verify=measured("verifier", check),
        continue_values=value, value_profile=NATIVE_PROFILE if mode == "native_ndu" else "reader-fixed-or-empirical-gate.v1",
        max_rounds=rounds, max_calls=rounds * 3)
    after = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier),
                 critic_sha256=critic.params_sha256, critic_metadata_sha256=_digest(critic.metadata))
    before = dict(model_sha256=model_sha, verifier_sha256=verifier_sha,
                  critic_sha256=critic_sha, critic_metadata_sha256=critic_metadata_sha)
    critic.assert_frozen()
    if before != after or _tensor_digest(facts, query, mask) != evidence_digest:
        raise ValueError("inference mutated a frozen artifact or public feature snapshot")
    work = meter.report()
    child_cpu = (None if any(d.get("child_cpu_ns") is None for d in decisions)
                 else sum(d["child_cpu_ns"] for d in decisions))
    child_wall = (None if any(d.get("child_wall_ns") is None for d in decisions)
                  else sum(d["child_wall_ns"] for d in decisions))
    wrapper_wall = (None if any(d.get("native_subprocess_elapsed_ns") is None for d in decisions)
                    else sum(d["native_subprocess_elapsed_ns"] for d in decisions))
    complete_formula = None if decisions else work["phase_flops"]["search"]
    native_qualified = bool(decisions) and all(d.get("native_executed") and d.get("reference_match")
                                              and "error_type" not in d for d in decisions)
    request_costs = dict(self_cpu_ns=work["cpu_ns"], native_child_cpu_ns=child_cpu,
        accounted_cpu_ns=None if child_cpu is None else work["cpu_ns"] + child_cpu,
        wall_ns=work["elapsed_ns"], native_child_wall_ns=child_wall,
        native_wrapper_wall_ns=wrapper_wall, wall_includes_native_subprocess=True,
        known_aten_formula_flops=sum(row["formula_flops"] for row in work["scopes"]),
        complete_formula_flops=complete_formula, shared_encoder_included=False,
        training_and_calibration_included=False,
        child_cpu_attribution="process_reaped_children_delta_may_include_concurrent_children")
    result.update(mode=mode, prediction=step_records[-1]["prediction"] if step_records else None,
        probabilities=step_records[-1]["probabilities"] if step_records else None,
        steps=len(step_records), step_records=step_records, verifier_observations=checks,
        native_control_decisions=decisions, artifact_digests_before=before, artifact_digests_after=after,
        model_sha256=model_sha, verifier_sha256=verifier_sha, critic_sha256=critic_sha,
        feature_sha256=public["feature_sha256"], source_sha256=public["source_sha256"],
        tensor_sha256=evidence_digest, profile_sha256=profile_sha, work_observation=work,
        native_child_cpu_ns=child_cpu, native_child_wall_ns=child_wall, request_costs=request_costs,
        native_wall_already_in_ledger=True, native_child_formula_work=None if decisions else 0,
        end_to_end_formula_flops=complete_formula,
        reader_callbacks_completed=result["status"] != "callback_failed",
        native_controller_execution_qualified=native_qualified,
        native_controller_failed_closed=bool(decisions) and not native_qualified,
        native_support_violated=support_violated, verifier_acceptance_is_semantic_truth=False,
        verifier_training_disjointness_declared=True, training_provenance_authenticated=False,
        empirical_intervals_are_certified_support=False, native_production_owner_integrated=False,
        shared_encoder_work_accounted_by_campaign=True, production_authorized=False)
    return result
