"""Matched continuation that trains actual frozen-verifier feedback under autograd.

The caller must establish every Core fitting/retention gate before entry. Both
copies consume the identical fixed natural/paired replay plan and execute the
same three Reader/two independent verifier calls, including the zero control.
"""
import copy
import math
import time

import torch
from torch.nn import functional as F

from binding_continuation import validate_continuation_plan
from binding_training import pair_group_indices, paired_margin_loss
from group_loop import parameter_digest
from revision_execution import digest_json, rollout_revision, validate_verifier
from token_reader_training import parameter_digest as training_parameter_digest


class RevisionTrainingFailure(RuntimeError):
    """A failed fit retaining attempted costs and every completed update receipt."""

    def __init__(self, receipt):
        super().__init__(receipt["error_type"] + ": " + receipt["error"])
        self.receipt = receipt


def transition_counts(initial, final, targets):
    """Score already completed predictions; counts refer to exposure trials."""
    initial, final, targets = (list(v) for v in (initial, final, targets))
    if (not len(initial) == len(final) == len(targets)
            or any(v not in (0, 1) for values in (initial, final, targets) for v in values)):
        raise ValueError("aligned binary initial/final predictions and targets required")
    initial_correct = sum(a == y for a, y in zip(initial, targets))
    corrected = sum(a != y and b == y for a, b, y in zip(initial, final, targets))
    damaged = sum(a == y and b != y for a, b, y in zip(initial, final, targets))
    return dict(exposure_trials=len(targets), initial_correct=initial_correct,
        initial_wrong=len(targets) - initial_correct, wrong_to_correct=corrected,
        correct_to_wrong=damaged, net_corrections=corrected - damaged,
        final_correct=sum(b == y for b, y in zip(final, targets)))


def _update(model, verifier, optimizer, batch, *, mode, pairs, pair_weight, case_ids):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    optimizer.zero_grad(set_to_none=True)
    trace = rollout_revision(model, verifier, batch.features(), mode=mode, case_ids=case_ids,
                             source_sha256s=batch.source_groups)
    final_logits = trace["logits_trace"][-1]
    ce = F.cross_entropy(final_logits, batch.targets)
    pair = paired_margin_loss(final_logits, batch.targets, pairs) if pairs else ce * 0
    loss = ce + pair_weight * pair
    if not torch.isfinite(loss):
        raise FloatingPointError("nonfinite revision training loss")
    for state in trace["state_trace"]:
        state.retain_grad()
    loss.backward()
    gradients = [p.grad for p in model.parameters() if p.grad is not None]
    if not gradients or any(not torch.isfinite(g).all() for g in gradients):
        raise FloatingPointError("nonfinite or absent revision parameter gradient")
    feedback_gradients = [layer.weight.grad[:, -4:] for layer in (model.proposal, model.update_gate)]
    feedback_l2 = math.sqrt(sum(g.square().sum().item() for g in feedback_gradients))
    feedback_columns = [math.sqrt(sum(g[:, column].square().sum().item() for g in feedback_gradients))
                        for column in range(4)]
    initial, final = (value.detach().softmax(-1)[:, 1].gt(.5).to(torch.long).tolist()
                      for value in (trace["logits_trace"][0], final_logits))
    row = dict(mode=mode, case_ids=list(case_ids), targets=batch.targets.tolist(),
        initial_predictions=initial, final_predictions=final,
        transitions=transition_counts(initial, final, batch.targets.tolist()),
        binary_cross_entropy=ce.item(), pair_loss=pair.item(), pair_weight=pair_weight,
        loss=loss.item(), feedback_column_gradient_l2=feedback_l2,
        feedback_gradient_l2_by_column=feedback_columns,
        feedback_column_gradients_nonzero=feedback_l2 > 0,
        parameter_gradient_l2=math.sqrt(sum(g.square().sum().item() for g in gradients)),
        hop_state_gradient_l2=[None if s.grad is None else s.grad.norm().item() for s in trace["state_trace"]],
        events=trace["events"], verifier_observations=[v.tolist() for v in trace["verifier_observations"]],
        initial_reader_sha256=trace["reader_model_sha256"], verifier_sha256=trace["verifier_model_sha256"],
        input_feature_sha256s=trace["input_feature_sha256s"], forward_cost=trace["costs"])
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in model.parameters()):
        raise FloatingPointError("nonfinite revision parameters after update")
    if any(p.grad is not None for p in verifier.parameters()):
        raise RuntimeError("revision training propagated a verifier gradient")
    row.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
               updated_reader_sha256=parameter_digest(model))
    return row


def fit_revision_pair(core, verifier, natural_data, binding_data, binding_cases, *, plan,
                      verifier_provenance, learning_rate=.001, pair_weight=.5,
                      wall_time_ns=3_600_000_000_000, failure_receipt_fn=None, natural_cases=None):
    """Train real/zero copies from one gated Core; return ``(models, receipt)``.

    ``plan`` is the exact independently persisted continuation plan: each logical
    update performs natural then binding. This function does not open evaluation
    data, tune a threshold, or authorize a new holdout. There are no forced errors.
    """
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = dict(schema="hepta.revision-paired-fit.v1", status="started",
        plan_sha256=plan.get("plan_sha256"), requested_logical_updates=plan.get("updates"),
        completed_logical_updates=0, attempted_logical_update=None, attempted_stream=None,
        attempted_arm=None, updates=[], models={}, optimizer="Adam_foreach_false",
        learning_rate=learning_rate, pair_weight=pair_weight, depth_supervision="last_hop_CE_plus_binding_pair",
        feedback_schema="verifier_p0_p1_agreement_evidence_present.v1", forced_candidates=False,
        core_gate_enforced_by="caller_before_entry", final_evaluation_authorized=False,
        formula_flops=None, nested_costs_additive=False, actual_same_budget_not_assumed=True,
        verifier_synthetic_trained=False, verifier_provenance_sha256=digest_json(verifier_provenance))
    try:
        binding_cases = tuple(binding_cases)
        validate_continuation_plan(plan, natural_data, binding_data, binding_cases, core.input_dim,
                                   natural_cases=natural_cases)
        if (not 0 < learning_rate <= 1 or pair_weight != .5 or core.max_hops < 3
                or type(wall_time_ns) is not int or wall_time_ns <= 0):
            raise ValueError("bounded revision schedule, three hops and registered pair weight 0.5 required")
        if core.training or any(p.requires_grad for p in core.parameters()):
            raise ValueError("the common Core starting checkpoint must be frozen")
        if hasattr(natural_data, "cases") and [c.case_id for c in natural_data.cases] != plan["natural_case_ids"]:
            raise ValueError("natural case identity differs from frozen continuation plan")
        sources = (set(getattr(core, "training_source_groups", ())) | set(natural_data.source_groups)
                   | set(binding_data.source_groups))
        validate_verifier(core, verifier, verifier_provenance, sources)
        before_core, before_verifier = parameter_digest(core), parameter_digest(verifier)
        models = {arm: copy.deepcopy(core).train().requires_grad_(True) for arm in ("real", "zero")}
        optimizers = {arm: torch.optim.Adam(model.parameters(), lr=learning_rate, foreach=False)
                      for arm, model in models.items()}
        for arm in models:
            receipt["models"][arm] = dict(completed_updates=0, natural_updates=0, binding_updates=0,
                natural_exposures=0, binding_exposures=0, feedback_nonzero_gradient_updates=0,
                feedback_nonzero_updates_by_column=[0] * 4,
                transitions={}, actual_calls=dict(reader_prepare=0, reader_step=0, verifier_prepare=0, verifier_step=0))
        receipt.update(initial_core_sha256=before_core, initial_verifier_sha256=before_verifier,
            initial_models_equal=all(parameter_digest(m) == before_core for m in models.values()),
            natural_sequence_sha256=digest_json(plan["natural_batches"]),
            binding_sequence_sha256=digest_json(plan["binding_batches"]), batch_size=plan["batch_size"],
            reader_training_source_groups=sorted(sources), verifier_provenance=dict(verifier_provenance))
        status = "completed"
        for logical_step in range(plan["updates"]):
            if time.perf_counter_ns() - wall >= wall_time_ns:
                status = "budget_stopped"
                break
            receipt["attempted_logical_update"] = logical_step + 1
            for stream, data in (("natural", natural_data), ("binding", binding_data)):
                receipt["attempted_stream"] = stream
                indices = plan[stream + "_batches"][logical_step]
                batch = data.take(indices)
                ids = [plan[stream + "_case_ids"][i] for i in indices]
                pairs = pair_group_indices([binding_cases[i] for i in indices])[1] if stream == "binding" else ()
                paired_record = dict(logical_step=logical_step + 1, stream=stream,
                    indices=list(indices), sample_sha256=digest_json(ids), arms={})
                # Persist the record before either arm so an interruption cannot hide
                # a completed real update while the matched zero update was failing.
                receipt["updates"].append(paired_record)
                for arm in ("real", "zero"):
                    receipt["attempted_arm"] = arm
                    row = _update(models[arm], verifier, optimizers[arm], batch, mode=arm,
                        pairs=pairs, pair_weight=pair_weight if pairs else 0., case_ids=ids)
                    paired_record["arms"][arm] = row
                    summary = receipt["models"][arm]
                    summary["completed_updates"] += 1
                    summary[stream + "_updates"] += 1
                    summary[stream + "_exposures"] += len(indices)
                    summary["feedback_nonzero_gradient_updates"] += row["feedback_column_gradients_nonzero"]
                    summary["feedback_nonzero_updates_by_column"] = [old + int(norm > 0)
                        for old, norm in zip(summary["feedback_nonzero_updates_by_column"], row["feedback_gradient_l2_by_column"])]
                    summary["transitions"] = {key: summary["transitions"].get(key, 0) + value
                                              for key, value in row["transitions"].items()}
                    for name, calls in row["forward_cost"]["calls"].items():
                        summary["actual_calls"][name] += calls
                if (paired_record["arms"]["real"]["forward_cost"]["calls"]
                        != paired_record["arms"]["zero"]["forward_cost"]["calls"]):
                    raise RuntimeError("matched training arms executed different call counts")
                if (paired_record["arms"]["real"]["input_feature_sha256s"]
                        != paired_record["arms"]["zero"]["input_feature_sha256s"]):
                    raise RuntimeError("matched training arms received different public tensors")
            receipt["completed_logical_updates"] = logical_step + 1
        if parameter_digest(core) != before_core or parameter_digest(verifier) != before_verifier:
            raise RuntimeError("revision fitting mutated the common Core or frozen verifier")
        validate_verifier(core, verifier, verifier_provenance, sources)
        for arm, model in models.items():
            model.eval().requires_grad_(False)
            model.training_source_groups = tuple(sorted(sources))
            receipt["models"][arm].update(model_sha256=parameter_digest(model), frozen=True,
                execution_parameter_sha256=parameter_digest(model),
                training_parameter_sha256=training_parameter_digest(model),
                parameter_count=sum(p.numel() for p in model.parameters()),
                parameter_bytes=sum(p.numel() * p.element_size() for p in model.parameters()))
        receipt.update(status=status, original_core_unchanged=True, verifier_unchanged=True,
            feedback_training_verified=(receipt["models"]["real"]["feedback_nonzero_gradient_updates"] > 0
                and receipt["models"]["zero"]["feedback_nonzero_gradient_updates"] == 0),
            identical_source_and_call_schedules=True, wall_time_budget_ns=wall_time_ns,
            cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            timing_scope="complete_pair_fit_including_validation_copy_plan_materialization_forward_backward_freeze_receipts")
        return models, receipt
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error),
            cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            failed_attempt_time_included=True, failed_update_may_have_mutated_copy=True)
        if failure_receipt_fn is not None:
            try:
                failure_receipt_fn(receipt)
            except Exception as sink_error:
                error.add_note("Failure receipt sink also failed: " + str(sink_error))
        raise RevisionTrainingFailure(receipt) from error
