"""Measured, label-free three-step revision with an independently frozen verifier.

The low-level rollout retains autograd for Reader training. The inference wrapper
accepts exactly six public tensors and checks artifact/source bindings. A verifier
predicts answers; its feedback does not constitute independently certified truth.
"""
import hashlib
import json
from pathlib import Path
import time

import torch

from group_loop import parameter_digest

ARMS = ("real", "zero", "shuffle", "reset", "late_fusion", "verifier_only")
CHEAP_ARMS = ("cheap_fixed1", "cheap_verifier")


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def tensor_digest(value):
    result = hashlib.sha256(str((str(value.dtype), tuple(value.shape))).encode())
    result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def validate_verifier(model, verifier, provenance=None, reader_sources=()):
    """Check frozen, independent storage and optionally a frozen file manifest."""
    if verifier is None or verifier is model or verifier.training:
        raise ValueError("independent eval-mode verifier required")
    if any(p.requires_grad for p in verifier.parameters()):
        raise ValueError("verifier must be frozen before revision")
    if {p.data_ptr() for p in model.parameters()} & {p.data_ptr() for p in verifier.parameters()}:
        raise ValueError("Reader and verifier parameter storage must be independent")
    if provenance is None:
        return
    required = {"file_path", "file_sha256", "model_sha256", "training_source_groups", "synthetic_trained"}
    if not isinstance(provenance, dict) or not required <= set(provenance):
        raise ValueError("explicit verifier file, model and source binding required")
    sources = tuple(provenance["training_source_groups"])
    if (not sources or len(set(sources)) != len(sources)
            or any(not isinstance(g, str) or not g for g in sources)
            or set(sources) != set(getattr(verifier, "training_source_groups", ()))
            or set(sources) & (set(reader_sources) | set(getattr(model, "training_source_groups", ())))
            or provenance["synthetic_trained"] is not False):
        raise ValueError("declared independent verifier sources and synthetic-untrained status required")
    actual_file = hashlib.sha256(Path(provenance["file_path"]).read_bytes()).hexdigest()
    if actual_file != provenance["file_sha256"] or parameter_digest(verifier) != provenance["model_sha256"]:
        raise ValueError("verifier file or parameter digest differs from frozen manifest")


def _features(features, model):
    if not isinstance(features, (tuple, list)) or len(features) != 6:
        raise ValueError("exactly six public tensors required; no outcome fields")
    if (any(not isinstance(t, torch.Tensor) or t.device.type != "cpu" or t.requires_grad for t in features)
            or any(t.dtype != torch.float32 or not torch.isfinite(t).all() for t in features[:3])
            or any(t.dtype != torch.bool for t in features[3:])):
        raise ValueError("detached finite CPU FP32 features and boolean masks required")
    model._validate(*features)


def _external(value, batch):
    if (not isinstance(value, torch.Tensor) or value.shape != (2, batch, 4)
            or value.dtype != torch.float32 or value.device.type != "cpu" or value.requires_grad
            or not torch.isfinite(value).all() or (value < 0).any() or (value > 1).any()
            or not torch.allclose(value[:, :, :2].sum(-1), torch.ones(2, batch))
            or not ((value[:, :, 2:] == 0) | (value[:, :, 2:] == 1)).all()):
        raise ValueError("two detached public feedback batches with valid probabilities/status required")
    return value.detach().clone()


def rollout_revision(model, verifier, features, *, mode="real", external_feedback=None, shuffle_indices=None,
                     case_ids=(), source_sha256s=()):
    """Unroll with gradients through Reader states, never through the verifier.

    Matching arms always execute three Reader and two verifier steps. A shuffle
    uses a predeclared within-batch derangement of actual observations, or an
    external pool whose generation costs belong to the caller.
    """
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    if mode not in ARMS + CHEAP_ARMS:
        raise ValueError("registered revision arm required")
    _features(features, model)
    verifier._validate(*features)
    validate_verifier(model, verifier)
    batch = features[0].shape[0]
    if any(values and len(values) != batch for values in (case_ids, source_sha256s)):
        raise ValueError("public identifiers must align with the physical batch")
    if mode == "shuffle":
        if (external_feedback is None) == (shuffle_indices is None):
            raise ValueError("choose exactly one public feedback source: external or deranged indices")
        if external_feedback is not None:
            external_feedback = _external(external_feedback, batch)
        elif (not isinstance(shuffle_indices, (tuple, list)) or batch < 2
                or len(shuffle_indices) != batch or any(type(i) is not int for i in shuffle_indices)
                or set(shuffle_indices) != set(range(batch))
                or any(i == donor for i, donor in enumerate(shuffle_indices))):
            raise ValueError("a complete within-batch derangement without fixed points is required")
    elif external_feedback is not None or shuffle_indices is not None:
        raise ValueError("feedback injection is only allowed in the shuffle control")
    if model.max_hops < (1 if mode in CHEAP_ARMS else 3):
        raise ValueError("three Reader hops required for matched revision arms")
    model_sha, verifier_sha = parameter_digest(model), parameter_digest(verifier)
    feature_shas = [tensor_digest(t) for t in features]
    callbacks, calls = [], dict(reader_prepare=0, reader_step=0, verifier_prepare=0, verifier_step=0)

    def invoke(name, callback):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        calls[name] += 1
        try:
            return callback()
        finally:
            callbacks.append(dict(component=name, cpu_ns=time.process_time_ns() - cpu,
                                  wall_ns=time.perf_counter_ns() - wall))

    state = feedback = prepared = verifier_prepared = None
    logits_trace, states, feedbacks, observations, events = [], [], [], [], []
    rounds = 0 if mode == "cheap_verifier" else 1 if mode == "cheap_fixed1" else 3
    for hop in range(rounds):
        if prepared is None:
            prepared = invoke("reader_prepare", lambda: model.prepare(*features))
        input_feedback = feedback
        state, logits, _, _ = invoke("reader_step", lambda: model.step_prepared(
            prepared, None if mode == "reset" else state, input_feedback))
        if (not torch.isfinite(state).all() or state.abs().max().item() > 1.000001
                or not torch.isfinite(logits).all()):
            raise FloatingPointError("revision state/logits must remain finite and bounded")
        states.append(state)
        logits_trace.append(logits)
        probabilities = logits.detach().softmax(-1)
        predictions = probabilities[:, 1].gt(.5).to(torch.long)
        for row in range(batch):
            events.append(dict(step=hop + 1, batch_row=row,
                case_id=case_ids[row] if case_ids else str(row),
                source_sha256=source_sha256s[row] if source_sha256s else None,
                prediction=int(predictions[row]), probabilities=probabilities[row].tolist(),
                state_sha256=tensor_digest(state[row]), feedback=None if input_feedback is None else input_feedback[row].tolist(),
                feedback_sha256=None if input_feedback is None else tensor_digest(input_feedback[row]),
                feedback_donor_batch_row=shuffle_indices[row] if input_feedback is not None and shuffle_indices is not None else None,
                feedback_donor_case_id=(case_ids[shuffle_indices[row]] if case_ids else str(shuffle_indices[row]))
                    if input_feedback is not None and shuffle_indices is not None else None,
                reader_model_sha256=model_sha, verifier_model_sha256=verifier_sha))
        if hop >= 2 or mode == "cheap_fixed1":
            continue
        with torch.no_grad():
            if verifier_prepared is None:
                verifier_prepared = invoke("verifier_prepare", lambda: verifier.prepare(*features))
            _, verifier_logits, _, _ = invoke("verifier_step", lambda: verifier.step_prepared(verifier_prepared))
            if verifier_logits.shape != (batch, 2) or not torch.isfinite(verifier_logits).all():
                raise FloatingPointError("finite aligned verifier logits required")
            observed_probs = verifier_logits.softmax(-1).detach().clone()
            present = features[3].any(-1).any(-1).to(torch.float32)
            observed = torch.cat((observed_probs,
                observed_probs[:, 1].gt(.5).to(torch.long).eq(predictions).to(torch.float32).unsqueeze(-1), present.unsqueeze(-1)), -1)
            observations.append(observed)
            if mode == "shuffle":
                feedback = (external_feedback[hop] if external_feedback is not None
                            else observed[torch.tensor(shuffle_indices, dtype=torch.long)])
            else:
                feedback = observed if mode in ("real", "reset") else torch.zeros_like(observed)
            feedback = feedback.detach().clone()
            feedbacks.append(feedback)
    if mode == "cheap_verifier":
        with torch.no_grad():
            verifier_prepared = invoke("verifier_prepare", lambda: verifier.prepare(*features))
            _, verifier_logits, _, _ = invoke("verifier_step", lambda: verifier.step_prepared(verifier_prepared))
            if verifier_logits.shape != (batch, 2) or not torch.isfinite(verifier_logits).all():
                raise FloatingPointError("finite aligned verifier logits required")
            probabilities = verifier_logits.softmax(-1).detach()
    else:
        probabilities = logits_trace[-1].softmax(-1)
        if mode == "late_fusion":
            probabilities = (probabilities + observations[-1][:, :2]) * .5
        elif mode == "verifier_only":
            probabilities = observations[-1][:, :2]
    return dict(logits_trace=logits_trace, state_trace=states, feedback_trace=feedbacks,
        verifier_observations=observations, events=events, output_probabilities=probabilities,
        output_predictions=probabilities[:, 1].gt(.5).to(torch.long), reader_model_sha256=model_sha,
        verifier_model_sha256=verifier_sha, input_feature_sha256s=feature_shas,
        costs=dict(cpu_ns=time.process_time_ns() - started_cpu, wall_ns=time.perf_counter_ns() - started_wall,
            calls=calls, callbacks=callbacks, physical_batch_size=batch, formula_flops=None,
            scope="physical_batch_including_validation_hashes_and_event_preparation",
            callback_costs_are_nested=True, shared_encoder_included=False,
            external_shuffle_feedback_preparation_included=False,
            external_shuffle_feedback_required=external_feedback is not None,
            per_case_attribution="singleton_only"))


def execute_revision(features, model, verifier, *, mode="real", verifier_provenance,
                     external_feedback=None, shuffle_indices=None, case_ids=(), source_sha256s=()):
    """Return JSON-compatible inference observations without reading any labels."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("inference Reader must be frozen in eval mode")
    validate_verifier(model, verifier, verifier_provenance)
    _features(features, model)
    snapshot = tuple(t.detach().clone() for t in features)
    with torch.no_grad():
        result = rollout_revision(model, verifier, snapshot, mode=mode,
            external_feedback=external_feedback, shuffle_indices=shuffle_indices,
            case_ids=case_ids, source_sha256s=source_sha256s)
    if (parameter_digest(model) != result["reader_model_sha256"]
            or parameter_digest(verifier) != result["verifier_model_sha256"]
            or [tensor_digest(t) for t in snapshot] != result["input_feature_sha256s"]):
        raise ValueError("revision inference mutated frozen model/verifier or public snapshot")
    initial = result["events"][:len(snapshot[0])] if result["events"] else []
    output = dict(schema="hepta.revision-execution.v1", mode=mode,
        prediction_rule="raw_probability_strictly_greater_than_0.5", probabilities=result["output_probabilities"].tolist(),
        predictions=result["output_predictions"].tolist(), initial_proposals=initial, events=result["events"],
        verifier_observations=[v.tolist() for v in result["verifier_observations"]],
        reader_model_sha256=result["reader_model_sha256"], verifier_model_sha256=result["verifier_model_sha256"],
        verifier_artifact_sha256=verifier_provenance["file_sha256"],
        verifier_provenance_sha256=digest_json(verifier_provenance),
        input_feature_sha256s=result["input_feature_sha256s"],
        external_feedback_sha256=None if external_feedback is None else tensor_digest(external_feedback),
        shuffle_indices=None if shuffle_indices is None else list(shuffle_indices),
        shuffle_uses_current_observations=mode == "shuffle" and shuffle_indices is not None,
        late_fusion_rule="0.5_reader_probability_plus_0.5_last_verifier_probability",
        verifier_synthetic_trained=False, verifier_acceptance_is_semantic_truth=False,
        cost=result["costs"], labels_read=False)
    output["cost"].update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
        scope="complete_inference_call_including_artifact_checks_snapshot_and_serializable_result")
    return output
