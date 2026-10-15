"""Real learned Cell callbacks in the existing bounded System2 executor."""

import time

import torch

from execution_meter import WorkLedger, TRANSFORMER_POLICY_SCHEMA
from group_critic import row_features
from group_encoder import digest_json
from group_features import BoundedWorkspace, content_digest
from group_tasks import feedback_vector, verify
from ndu_continuation import (PROFILE, ContinuationBranch, ContinuationEstimate,
                              freeze_policy)
from paired_execution import PHASES
from system2_execution import PublicTask, Verification, run_reasoning
from transformer_work import PROFILE as WORK_PROFILE


def parameter_digest(model):
    from hashlib import sha256
    result = sha256()
    for name, value in sorted(model.state_dict().items()):
        result.update(name.encode())
        result.update(str(tuple(value.shape)).encode())
        result.update(str(value.dtype).encode())
        result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def execute_group(task, model, snapshot, critic, *, mode="ndu", max_steps=4,
                  cost_per_work=1e-10, cost_per_ns=1e-11):
    """Inference never consumes task.target; final scoring belongs to caller.

    The verifier uses public evidence as an executable checker. It can reveal
    candidate correctness, so its time and calls are included and ablated.
    Critic intervals are empirical calibration envelopes, not certified support.
    """
    modes = {"static", "wide", "fixed", "adaptive", "ndu", "no_verifier", "reset_state"}
    if mode not in modes or type(max_steps) is not int or not 1 <= max_steps <= 8:
        raise ValueError("registered mode and bounded recurrence required")
    if snapshot.identity.source_digest != content_digest(task.text.encode()):
        raise ValueError("snapshot does not bind the actual public task")
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("selected inference model must be frozen")
    critic.assert_frozen()
    model_sha = parameter_digest(model)
    tokens = torch.tensor(snapshot.tokens, dtype=torch.float32).unsqueeze(0)
    mask = torch.tensor(snapshot.mask, dtype=torch.bool).unsqueeze(0)
    rounds = 1 if mode in {"static", "wide"} else max_steps
    workspace = BoundedWorkspace(snapshot.identity.scope, snapshot.identity.generation,
                                 slots=1, width=model.hidden_dim, max_steps=rounds)
    state, logits, statuses, bindings, pending_state = None, None, [], [], None
    meter_policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=WORK_PROFILE,
        mode="strict", wall_time_ns=30_000_000_000, max_process_rss_bytes=None,
        rapl_zone=None, rapl_max_power_watts=None)
    caps = dict.fromkeys(PHASES, 10**10)
    meter = WorkLedger(meter_policy, caps)
    now = time.time_ns()
    cutoff = critic.metadata["cutoff_ns"]
    if cutoff >= now:
        raise ValueError("critic must be fitted before this inference task")
    calls = rounds * 3
    policy = freeze_policy(objective_sha256=digest_json({"task": "evidence-correct-class-v1"}),
        subject_id="agent:group-reasoning-research", critic_sha256=critic.params_sha256,
        critic_cutoff_ns=cutoff, expires_at_ns=now + 60_000_000_000,
        discount_rate_per_second=0., cost_per_formula_flop=cost_per_work,
        cost_per_latency_ns=cost_per_ns, minimum_margin=0.,
        max_estimate_age_ns=60_000_000_000,
        execution=dict(max_calls=calls, max_rounds=rounds, meter_policy=meter_policy, phase_caps=caps))

    def propose(public, previous, feedback):
        nonlocal state, logits, pending_state
        current = digest_json(workspace.state)
        if pending_state is not None and current != pending_state:
            raise ValueError("workspace changed after continuation valuation")
        f = feedback_vector(feedback == "supported", feedback) if feedback else (0., 0., 0., 0.)
        with torch.no_grad():
            state, logits = model.step(tokens, None if mode == "reset_state" else state,
                                        torch.tensor([f]), mask)
        workspace.write(workspace.step + 1, state, scope=snapshot.identity.scope,
                        generation=snapshot.identity.generation)
        bindings.append(dict(step=workspace.step, state_sha256=digest_json(workspace.state),
                             feature_sha256=snapshot.digest, model_sha256=model_sha))
        return chr(65 + logits.argmax(dim=1).item())

    def check(public, candidate):
        if mode == "no_verifier":
            statuses.append("disabled")
            return Verification(False, "verifier_disabled")
        checked = verify(task, candidate)
        statuses.append(checked.feedback)
        # Fixed-depth controls compute all registered steps, including any
        # temporarily correct intermediate prediction. Feedback is still paid.
        if mode in {"fixed", "reset_state"} and workspace.step < rounds:
            return Verification(False, checked.feedback)
        return checked

    def value(public, candidate, feedback, context):
        nonlocal pending_state
        pending_state = digest_json(workspace.state)
        if mode != "ndu":
            if mode == "adaptive":
                predicted = critic.predict(row_features(state, logits, workspace.step, rounds))
                return predicted["continue_probability"], predicted["stop_probability"]
            return 1., 0.
        predicted = critic.predict(row_features(state, logits, workspace.step, rounds))
        binding = dict(context_id=context.context_id, feature_sha256=snapshot.digest,
                       workspace_sha256=pending_state, model_sha256=model_sha,
                       critic_sha256=critic.params_sha256)
        bindings[-1]["valuation_binding"] = binding
        return ContinuationEstimate(context.context_id, critic.params_sha256, digest_json(binding),
            context.as_of_ns, policy["expires_at_ns"], predicted["stop_upper"],
            (ContinuationBranch(1_000_000, predicted["continue_lower"], 1.,
                                1_000_000_000, 100_000_000),))

    public = PublicTask(task.text, now)
    # Legacy fixed-depth/gate controls still use the same executor; wrapping
    # the whole call would nest scopes, so meter each callback separately.
    if mode == "ndu":
        result = run_reasoning(public, propose=propose, verify=check, continue_values=value,
            value_profile=PROFILE, max_rounds=rounds, max_calls=calls, ndu_policy=policy, meter=meter)
    else:
        def measured(kind, function):
            def callback(*args):
                with meter.scope("search", kind):
                    return function(*args)
            return callback
        result = run_reasoning(public, propose=measured("proposer", propose),
            verify=measured("verifier", check), continue_values=measured("value", value),
            value_profile="registered-research-fixed-or-empirical-gate.v1",
            max_rounds=rounds, max_calls=calls)
        result["work_observation"] = meter.report()
    critic.assert_frozen()
    if parameter_digest(model) != model_sha:
        raise ValueError("inference changed selected model weights")
    result.update(mode=mode, feature_sha256=snapshot.digest, model_sha256=model_sha,
        critic_sha256=critic.params_sha256, workspace_bindings=bindings,
        workspace_steps=workspace.step, verifier_statuses=statuses,
        empirical_intervals_are_certified_support=False,
        native_production_owner_integrated=False,
        shared_encoder_work_accounted_by_campaign=True)
    return result
