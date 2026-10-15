"""Synchronized, equal-actual-update paired-world training of two Reader Heads.

No original V5 trainer or Encoder is mutated. Cross-fact and fact-local Heads
consume identical complete groups; the group stops *together* only when both
training-only fits pass at the same scheduled diagnostic. This is equal sampled
work, not equal arithmetic or model-selection approval.
"""
from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
import random
import time

import torch
from torch.nn import functional as F

ARMS = ("cross_fact", "local")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()).hexdigest()


def _model_digest(model):
    h = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        h.update(name.encode())
        h.update(str(tuple(tensor.shape)).encode())
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def _groups(cases):
    """Producer's own explicit complete-world registration and source checks."""
    cases = tuple(cases)
    groups = defaultdict(dict)
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("nonempty unique paired-world cases required")
    for idx, case in enumerate(cases):
        prefix, sep, world = case.paragraph_id.rpartition("/world-")
        if not sep or world not in ("0", "1") or case.answer_id not in ("0", "1"):
            raise ValueError("complete paired-world identifiers required")
        if getattr(case, "segmentation", None) != "synthetic-ownership-storage-v1":
            raise ValueError("unexpected paired-world data family")
        key = (world, case.answer_id)
        if key in groups[prefix]:
            raise ValueError("duplicate world/answer membership")
        groups[prefix][key] = idx
    ordered = []
    for group in groups.values():
        if set(group) != {(w, a) for w in ("0", "1") for a in ("0", "1")}:
            raise ValueError("missing complete paired-world member")
        members = tuple(group[w, a] for w in ("0", "1") for a in ("0", "1"))
        a, b, c, d = (cases[index] for index in members)
        if (a.facts != b.facts or c.facts != d.facts or a.facts == c.facts
                or a.question != b.question or a.question != c.question or a.question != d.question
                or a.candidate != c.candidate or b.candidate != d.candidate
                or a.candidate == b.candidate or a.label == b.label or c.label == d.label
                or a.label == c.label or b.label == d.label
                or Counter(" ".join(a.facts).split()) != Counter(" ".join(c.facts).split())):
            raise ValueError("semantic paired-world/candidate truth inconsistency")
        ordered.append(members)
    return tuple(ordered)


def _schedule(cases, steps, seed, batch_size):
    groups = _groups(cases)
    if (type(steps) is not int or not 1 <= steps <= 10000
            or type(batch_size) is not int or batch_size < 4 or batch_size % 4
            or len(groups) % (batch_size // 4) != 0
            or type(seed) is not int or not 0 <= seed < 2**32):
        raise ValueError("bounded complete-group training schedule required")
    rng = random.Random(seed)
    order, cursor = [], len(groups)
    batches = []
    for _ in range(steps):
        if cursor == len(groups):
            order = list(range(len(groups)))
            rng.shuffle(order)
            cursor = 0
        chosen = order[cursor:cursor + batch_size // 4]
        cursor += batch_size // 4
        batches.append([index for member in chosen for index in groups[member]])
    return batches


def _eval(model, data, cases, groups, depth, batch_size):
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    probabilities, predictions, loss = [], [], 0.
    with torch.no_grad():
        for start in range(0, len(cases), batch_size):
            idx = list(range(start, min(start + batch_size, len(cases))))
            batch = data.take(idx)
            logits = model(*batch.features(), steps=depth)
            if not torch.isfinite(logits).all():
                raise FloatingPointError("nonfinite paired fit diagnostics")
            loss += F.cross_entropy(logits, batch.targets).item() * len(idx)
            p = logits.softmax(-1)[:, 1].tolist()
            probabilities.extend(p)
            predictions.extend(int(v > .5) for v in p)
    correct = sum(p == c.label for p, c in zip(predictions, cases))
    pairs = [(members[i], members[2+i]) for members in groups for i in (0, 1)]
    both = sum(predictions[a] == cases[a].label and predictions[b] == cases[b].label
               for a, b in pairs)
    return dict(n=len(cases), accuracy=correct/len(cases),
                both_worlds_correct=both/len(pairs),
                binary_cross_entropy=loss/len(cases),
                probabilities=probabilities,
                predictions=predictions,
                cpu_ns=time.process_time_ns()-start_cpu,
                wall_ns=time.perf_counter_ns()-start_wall)


def _step(model, optimizer, batch, cases, indices, depth, pair_weight):
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    optimizer.zero_grad(set_to_none=True)
    trace = model(*batch.features(), steps=depth, return_attention=True)
    logits = trace["logits"]
    ce = F.cross_entropy(logits, batch.targets)
    if logits.shape != (len(indices), 2) or len(indices) % 4:
        raise ValueError("four-case group logits required")
    scores = logits[:, 1] - logits[:, 0]
    offsets = torch.arange(0, len(indices), 4)
    left = torch.stack((offsets, offsets+1), 1).reshape(-1)
    right = torch.stack((offsets+2, offsets+3), 1).reshape(-1)
    if not torch.equal(batch.targets[left], 1 - batch.targets[right]):
        raise ValueError("missing opposite-world truth in current training batch")
    diff = (2*batch.targets[left]-1) * (scores[left] - scores[right])
    pair_loss = F.softplus(1. - diff).mean()
    objective = ce + pair_weight * pair_loss
    if not torch.isfinite(objective):
        raise FloatingPointError("nonfinite paired Reader optimization loss")
    for state in trace["states"]:
        state.retain_grad()
    objective.backward()
    gradients = [p.grad for p in model.parameters() if p.grad is not None]
    if not gradients or any(not torch.isfinite(g).all() for g in gradients):
        raise FloatingPointError("nonfinite/absent Reader parameter gradient")
    if any(s.grad is not None and not torch.isfinite(s.grad).all() for s in trace["states"]):
        raise FloatingPointError("nonfinite Reader workspace gradient")
    cpu_l2 = math.sqrt(sum(g.double().square().sum().item() for g in gradients))
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in model.parameters()):
        raise FloatingPointError("nonfinite updated Reader parameter")
    ids = [cases[i].case_id for i in indices]
    return dict(indices=list(indices), case_ids=ids, sample_sha256=_digest(ids),
                exposures=len(indices), depth=depth, pair_weight=pair_weight,
                finite_gradients=True, inference_feature_arguments=6,
                binary_cross_entropy=ce.item(), pair_loss=pair_loss.item(),
                total_loss=objective.item(), parameter_gradient_l2=cpu_l2,
                cpu_ns=max(1, time.process_time_ns()-start_cpu),
                wall_ns=max(1, time.perf_counter_ns()-start_wall))


def _optimizer_tensor_bytes(optimizer):
    return sum(value.numel()*value.element_size() for state in optimizer.state.values()
               for value in state.values() if isinstance(value, torch.Tensor))


class JointFitFailure(RuntimeError):
    """Any interrupted pair fails closed, retaining partial observed work."""
    def __init__(self, receipt):
        super().__init__(receipt["error_type"] + ": " + receipt["error"])
        self.receipt = receipt


def fit_joint_reader_pair(models, data, cases, *, steps=8000, seed=41,
                          batch_size=16, depth=3, learning_rate=.001,
                          pair_weight=.5, diagnostic_interval=250,
                          wall_time_ns=1_800_000_000_000, failure_receipt_fn=None):
    """Returns frozen two Heads, original-compatible per-arm receipts, one joint cost.

    Stop together only when *both* arms meet the same TRAIN gate at the same
    scheduled diagnostic; no validation/fresh/feedback labels enter training.
    """
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = dict(schema="hepta.cross-fact.joint-fit.v1", status="started",
                   seed=seed, requested_steps=steps, completed_steps=0,
                   original_models_unchanged=False, arms=list(ARMS),
                   partial_attempts=[], equal_train_rows=True,
                   shared_input_batch_materializations=0,
                   stop_rule="both_fits_on_the_same_training_only_diagnostic",
                   final_evaluation_authorized=False, production_authorized=False)
    try:
        if not isinstance(models, dict) or set(models) != set(ARMS):
            raise ValueError("exact cross-fact and local model comparison required")
        if (type(depth) is not int or not 1 <= depth <= 32
                or type(diagnostic_interval) is not int or not 1 <= diagnostic_interval <= steps
                or not 0 < learning_rate <= 1 or not 0 <= pair_weight <= 100
                or type(wall_time_ns) is not int or wall_time_ns <= 0):
            raise ValueError("bounded joint training budget required")
        cases = tuple(cases)
        width = models[ARMS[0]].input_dim
        data.validate(width)
        if (any(model.input_dim != width or depth > model.max_hops
                or model.training or any(p.requires_grad for p in model.parameters())
                for model in models.values())
                or data.targets.tolist() != [c.label for c in cases]
                or tuple(data.source_groups) != tuple(c.source_hash for c in cases)):
            raise ValueError("frozen matched Reader and original bound TRAIN labels required")
        groups = _groups(cases)
        schedule = _schedule(cases, steps, seed, batch_size)
        shape = {arm: sum(p.numel() for p in model.parameters()) for arm,model in models.items()}
        initial = {arm: _model_digest(model) for arm,model in models.items()}
        if len(set(shape.values())) != 1 or len(set(initial.values())) != 1:
            raise ValueError("matched parameter count and exact initial weight bytes required")
        trained = {arm: copy.deepcopy(models[arm]).train().requires_grad_(True) for arm in ARMS}
        optimizers = {arm: torch.optim.Adam(trained[arm].parameters(), lr=learning_rate,
                                          foreach=False) for arm in ARMS}
        records = {arm: dict(schema="hepta.binding.full-fit.v1", status="started",
            seed=seed, requested_steps=steps, completed_steps=0,
            actual_training_exposures=0, initial_model_sha256=initial[arm],
            training_targets_sha256=_digest(data.targets.tolist()),
            case_ids=[c.case_id for c in cases], case_ids_sha256=_digest([c.case_id for c in cases]),
            schedule_sha256=_digest(schedule),
            updates=[], diagnostics=[], optimizer="Adam_foreach_false", learning_rate=learning_rate,
            batch_size=batch_size, depth=depth, pair_weight=pair_weight,
            stop_rule=dict(accuracy=1., both_worlds_correct=1., maximum_binary_cross_entropy=.10,
                           diagnostic_interval=diagnostic_interval, selection_data="training_only"),
            synchronized_early_stop=True, joint_cost_not_additive=True)
            for arm in ARMS}
        totals={arm:dict(cpu_ns=0,wall_ns=0) for arm in ARMS}
        def diagnostic(arm, step):
            report = _eval(trained[arm], data, cases, groups, depth, batch_size)
            records[arm]["diagnostics"].append(dict(optimizer_step=step, binding=report))
            totals[arm]["cpu_ns"] += report["cpu_ns"]
            totals[arm]["wall_ns"] += report["wall_ns"]
            return (report["accuracy"] == 1. and report["both_worlds_correct"] == 1.
                    and report["binary_cross_entropy"] <= .10)
        for arm in ARMS:
            diagnostic(arm, 0)
        last_fits = dict.fromkeys(ARMS, False)
        joint_status = "max_updates_reached"
        for step, indices in enumerate(schedule, 1):
            if time.perf_counter_ns()-start_wall >= wall_time_ns:
                joint_status="budget_stopped"
                break
            receipt["attempted_step"] = step
            pending={}
            # One detached TRAIN batch is borrowed by both Heads. This is a
            # physical input-copy saving, not two independent data forwards.
            batch = data.take(indices)
            receipt["shared_input_batch_materializations"] += 1
            for arm in ARMS:
                receipt["attempted_arm"] = arm
                row=_step(trained[arm], optimizers[arm], batch, cases, indices, depth, pair_weight)
                row["step"] = step
                pending[arm] = row
                totals[arm]["cpu_ns"] += row["cpu_ns"]
                totals[arm]["wall_ns"] += row["wall_ns"]
                # A failure during the second arm cannot hide the first
                # completed operation from the preserved terminal receipt.
                receipt["partial_attempts"] = list(pending)
            for arm in ARMS:
                records[arm]["updates"].append(pending[arm])
                records[arm]["completed_steps"] = step
                records[arm]["actual_training_exposures"] = step*batch_size
            receipt["completed_steps"] = step
            receipt["partial_attempts"] = []
            if step % diagnostic_interval == 0 or step == steps:
                last_fits = {arm: diagnostic(arm,step) for arm in ARMS}
                if all(last_fits.values()):
                    joint_status="train_gate_passed"
                    break
        if joint_status == "budget_stopped":
            last_fits = dict.fromkeys(ARMS, False)
        for arm in ARMS:
            selected=trained[arm].eval().requires_grad_(False)
            if _model_digest(models[arm]) != initial[arm]:
                raise RuntimeError("original shared starting Reader mutated during fitting")
            selected.training_source_groups=tuple(sorted({c.source_hash for c in cases}))
            rec=records[arm]
            counter=Counter(cid for update in rec["updates"] for cid in update["case_ids"])
            rec.update(case_exposures=dict(counter), status=("train_gate_passed" if last_fits[arm]
                       else joint_status if joint_status != "train_gate_passed"
                       else "max_updates_reached"), train_gate_passed=bool(last_fits[arm]),
                       sampler="complete_four_case_groups_without_replacement_per_epoch",
                       wall_time_budget_ns=wall_time_ns, final_evaluation_authorized=False,
                       frozen=True, parameter_count=shape[arm],
                       parameter_bytes=sum(p.numel()*p.element_size() for p in selected.parameters()),
                       optimizer_tensor_bytes=_optimizer_tensor_bytes(optimizers[arm]),
                       model_sha256=_model_digest(selected), original_model_unchanged=True,
                       training_source_groups=list(selected.training_source_groups),
                       formula_flops=None, strict_equal_compute=False,
                       annotations_enter_inference=False, evidence_weight=0.,
                       depth_supervision="final_hop_only", official_validation_evaluated=False,
                       generalization_established=False, nested_costs_additive=False,
                       cpu_ns=totals[arm]["cpu_ns"], wall_ns=totals[arm]["wall_ns"],
                       timing_scope="arm_updates_and_diagnostics_only_joint_owner_cost_separately_recorded")
        receipt.update(status=joint_status, training_arms_both_fit=all(last_fits.values()),
                       original_models_unchanged=True,
                       initial_parameter_sha256=initial[ARMS[0]],
                       matched_training_steps={arm: records[arm]["completed_steps"] for arm in ARMS},
                       matched_training_source_digest=_digest(schedule),
                       matched_parameter_count=shape[ARMS[0]],
                       cpu_ns=time.process_time_ns()-start_cpu,
                       wall_ns=time.perf_counter_ns()-start_wall,
                       timing_scope="joint_end_to_end_copy_train_evaluate_freeze", nested_arm_costs_additive=False)
        return trained, records, receipt
    except Exception as exc:
        receipt.update(status="failed", error_type=type(exc).__name__, error=str(exc),
                       cpu_ns=time.process_time_ns()-start_cpu,
                       wall_ns=time.perf_counter_ns()-start_wall,
                       incomplete_pair_may_have_mutated_candidate=True,
                       final_evaluation_authorized=False)
        if failure_receipt_fn is not None:
            try:
                failure_receipt_fn(receipt)
            except Exception as sink_error:
                exc.add_note("failed to persist joint failure: " + str(sink_error))
        raise JointFitFailure(receipt) from exc
