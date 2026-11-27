"""Train-only paired-world fitting without changing the frozen V4 Reader.

Only six public feature tensors enter model calls. Labels select training losses;
world identities select complete minibatches and never enter the Reader.
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

from token_reader_training import parameter_digest


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False).encode()).hexdigest()


def binding_groups(cases):
    """Return complete four-row groups, rejecting changed world/candidate bindings."""
    cases = tuple(cases)
    groups = defaultdict(dict)
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("unique nonempty binding cases required")
    for index, case in enumerate(cases):
        prefix, separator, world = case.paragraph_id.rpartition("/world-")
        if (not separator or world not in ("0", "1") or case.answer_id not in ("0", "1")
                or case.segmentation != "synthetic-ownership-storage-v1"):
            raise ValueError("registered paired-world cases required")
        key = (world, case.answer_id)
        if key in groups[prefix]:
            raise ValueError("duplicate world/candidate binding")
        groups[prefix][key] = index
    result = []
    for members in groups.values():
        if set(members) != {(world, answer) for world in ("0", "1") for answer in ("0", "1")}:
            raise ValueError("complete worlds and both candidates required")
        for answer in ("0", "1"):
            a, b = (cases[members[(world, answer)]] for world in ("0", "1"))
            if (a.question != b.question or a.candidate != b.candidate or a.label == b.label
                    or a.facts == b.facts or Counter(" ".join(a.facts).split()) != Counter(" ".join(b.facts).split())):
                raise ValueError("opposite labels on equal-word-count evidence worlds required")
        for world in ("0", "1"):
            a, b = (cases[members[(world, answer)]] for answer in ("0", "1"))
            if a.facts != b.facts or a.question != b.question or a.candidate == b.candidate or a.label == b.label:
                raise ValueError("two opposing candidates on identical public evidence required")
        result.append(tuple(members[(world, answer)] for world in ("0", "1") for answer in ("0", "1")))
    return tuple(result)


def balanced_group_batches(cases, *, updates, batch_size=16, seed=41):
    """Shuffle whole groups once per epoch; never split or oversample an epoch."""
    groups = binding_groups(cases)
    if (type(updates) is not int or not 1 <= updates <= 10000 or type(batch_size) is not int
            or batch_size < 4 or batch_size % 4 or len(groups) % (batch_size // 4)):
        raise ValueError("bounded updates and a group-divisible batch size required")
    rng, result, position, order = random.Random(seed), [], len(groups), []
    width = batch_size // 4
    for _ in range(updates):
        if position == len(groups):
            order = list(range(len(groups)))
            rng.shuffle(order)
            position = 0
        selected = order[position:position + width]
        result.append([index for group in selected for index in groups[group]])
        position += width
    return result


def world_pairs(cases):
    return tuple((group[answer], group[2 + answer])
                 for group in binding_groups(cases) for answer in (0, 1))


def paired_loss(logits, targets, pairs, *, margin=1.):
    """Rank the positive evidence world above its same-question negative world."""
    if not pairs or logits.shape != (len(targets), 2):
        raise ValueError("aligned binary logits and complete pairs required")
    if any(type(i) is not int or not 0 <= i < len(targets) for pair in pairs for i in pair):
        raise ValueError("bounded world-pair indices required")
    left, right = (torch.tensor(values, dtype=torch.long) for values in zip(*pairs))
    if (len(set(left.tolist() + right.tolist())) != len(targets)
            or not torch.equal(targets[left], 1 - targets[right])):
        raise ValueError("each row must belong to one opposite-label world pair")
    scores = logits[:, 1] - logits[:, 0]
    signed_difference = (2 * targets[left] - 1) * (scores[left] - scores[right])
    return F.softplus(margin - signed_difference).mean()



def pair_group_indices(cases):
    """Return ``(complete_four_row_groups, once_only_world_pairs)`` in input order."""
    return binding_groups(cases), world_pairs(cases)


def paired_margin_loss(logits, targets, pairs):
    return paired_loss(logits, targets, pairs)


def _validate_data(data, cases, input_dim):
    data.validate(input_dim)
    if (data.targets.tolist() != [case.label for case in cases]
            or tuple(data.source_groups) != tuple(case.source_hash for case in cases)):
        raise ValueError("training labels and source order differ from bound cases")


def evaluate_reader(model, data, *, cases=None, depth=3, batch_size=16):
    """Measured complete training diagnostics; never used on an unseen partition."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    probabilities, predictions, loss_sum = [], [], 0.
    with torch.no_grad():
        for start in range(0, len(data.targets), batch_size):
            batch = data.take(list(range(start, min(start + batch_size, len(data.targets)))))
            logits = model(*batch.features(), steps=depth)
            if not torch.isfinite(logits).all():
                raise FloatingPointError("nonfinite diagnostic logits")
            loss_sum += F.cross_entropy(logits, batch.targets).item() * len(batch.targets)
            batch_probabilities = logits.softmax(-1)[:, 1].tolist()
            probabilities.extend(batch_probabilities)
            predictions.extend(int(value > .5) for value in batch_probabilities)
    targets = data.targets.tolist()
    result = dict(n=len(targets), accuracy=sum(a == b for a, b in zip(targets, predictions)) / len(targets),
        binary_cross_entropy=loss_sum / len(targets), predictions=predictions, probabilities=probabilities)
    if cases is not None:
        pairs = world_pairs(cases)
        result.update(paired_candidates=len(pairs), both_worlds_correct=sum(
            predictions[a] == targets[a] and predictions[b] == targets[b] for a, b in pairs) / len(pairs),
            evidence_switch_rate=sum(predictions[a] != predictions[b] for a, b in pairs) / len(pairs))
    result.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall)
    return result


def _train_copy(model):
    trained = copy.deepcopy(model).train()
    trained.requires_grad_(True)
    return trained


def _optimizer_step(model, optimizer, data, indices, *, depth, pair_weight, pairs, case_ids):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    batch = data.take(indices)
    optimizer.zero_grad(set_to_none=True)
    trace = model(*batch.features(), steps=depth, return_attention=True)
    ce = F.cross_entropy(trace["logits"], batch.targets)
    pair = paired_loss(trace["logits"], batch.targets, pairs) if pair_weight else ce * 0
    loss = ce + pair_weight * pair
    if not torch.isfinite(loss):
        raise FloatingPointError("nonfinite paired-world training loss")
    for state in trace["states"]:
        state.retain_grad()
    loss.backward()
    gradients = [p.grad for p in model.parameters() if p.grad is not None]
    if not gradients or any(not torch.isfinite(value).all() for value in gradients):
        raise FloatingPointError("nonfinite or absent Reader parameter gradient")
    if any(state.grad is not None and not torch.isfinite(state.grad).all() for state in trace["states"]):
        raise FloatingPointError("nonfinite Reader recurrent-state gradient")
    gradient_l2 = math.sqrt(sum(value.double().square().sum().item() for value in gradients))
    states = [state.detach() for state in trace["states"]]
    record = dict(indices=list(indices), case_ids=list(case_ids), sample_sha256=_digest(case_ids),
        exposures=len(indices), binary_cross_entropy=ce.item(), pair_loss=pair.item(),
        pair_weight=pair_weight, total_loss=loss.item(), parameter_gradient_l2=gradient_l2,
        hop_state_gradient_l2=[None if state.grad is None else state.grad.norm().item() for state in trace["states"]],
        hop_state_saturation_fraction=[state.abs().ge(.99).float().mean().item() for state in states],
        hop_state_max_abs=[state.abs().max().item() for state in states], depth=depth,
        finite_gradients=True, inference_feature_arguments=6)
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in model.parameters()):
        raise FloatingPointError("nonfinite Reader parameters after update")
    record.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall)
    return record



def _optimizer_storage(optimizer, model):
    result = dict(optimizer_tensor_bytes=sum(value.numel() * value.element_size()
        for state in optimizer.state.values() for value in state.values() if isinstance(value, torch.Tensor)),
        last_gradient_tensor_bytes=sum(p.grad.numel() * p.grad.element_size()
                                      for p in model.parameters() if p.grad is not None))
    optimizer.zero_grad(set_to_none=True)
    return result


def _finish(model, trained, data, initial_digest, receipt):
    if parameter_digest(model) != initial_digest:
        raise RuntimeError("input Reader mutated during fitting")
    trained.eval().requires_grad_(False)
    trained.training_source_groups = tuple(sorted(set(data.source_groups)))
    receipt.update(initial_model_sha256=initial_digest, model_sha256=parameter_digest(trained),
        original_model_unchanged=True, frozen=True, parameter_count=sum(p.numel() for p in trained.parameters()),
        parameter_bytes=sum(p.numel() * p.element_size() for p in trained.parameters()),
        training_source_groups=list(trained.training_source_groups), formula_flops=None,
        formula_reason="paired_alignment_and_autograd_formula_not_instrumented", strict_equal_compute=False,
        annotations_enter_inference=False, evidence_weight=0., depth_supervision="final_hop_only",
        official_validation_evaluated=False, generalization_established=False, nested_costs_additive=False)
    return trained, receipt


class BindingTrainingFailure(RuntimeError):
    """A failed attempt retaining partial updates and the whole attempted cost."""
    def __init__(self, receipt):
        super().__init__(receipt["error_type"] + ": " + receipt["error"])
        self.receipt = receipt


def _failed(error, receipt, wall, cpu, failure_receipt_fn):
    receipt.update(status="failed", error_type=type(error).__name__, error=str(error),
        cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
        failed_attempt_time_included=True, failed_update_may_have_mutated_copy=True,
        final_evaluation_authorized=False, formula_flops=None)
    if failure_receipt_fn is not None:
        try:
            failure_receipt_fn(receipt)
        except Exception as sink_error:
            error.add_note("Failure receipt sink also failed: " + str(sink_error))
    raise BindingTrainingFailure(receipt) from error


def fit_binding_reader(model, data, cases, *, steps=8000, seed=41, batch_size=16,
                       depth=3, learning_rate=.001, pair_weight=.5, diagnostic_interval=250,
                       wall_time_ns=3_600_000_000_000, failure_receipt_fn=None):
    """Pass the complete train-only fitting gate at the earliest scheduled check."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = dict(schema="hepta.binding.full-fit.v1", status="started", seed=seed,
        requested_steps=steps, completed_steps=0, actual_training_exposures=0,
        updates=[], diagnostics=[], optimizer="Adam_foreach_false", learning_rate=learning_rate,
        batch_size=batch_size, depth=depth, pair_weight=pair_weight,
        stop_rule=dict(accuracy=1., both_worlds_correct=1., maximum_binary_cross_entropy=.10,
                       diagnostic_interval=diagnostic_interval, selection_data="training_only"))
    try:
        cases = tuple(cases)
        _validate_data(data, cases, model.input_dim)
        if (not 0 < learning_rate <= 1 or not 0 <= pair_weight <= 100
                or type(depth) is not int or not 1 <= depth <= model.max_hops
                or type(diagnostic_interval) is not int or diagnostic_interval < 1
                or type(wall_time_ns) is not int or wall_time_ns <= 0):
            raise ValueError("bounded full fitting schedule required")
        batches = balanced_group_batches(cases, updates=steps, batch_size=batch_size, seed=seed)
        receipt.update(case_ids=[case.case_id for case in cases],
                       case_ids_sha256=_digest([case.case_id for case in cases]), schedule_sha256=_digest(batches))
        initial_digest = parameter_digest(model)
        receipt.update(initial_model_sha256=initial_digest, training_targets_sha256=_digest(data.targets.tolist()))
        trained = _train_copy(model)
        optimizer = torch.optim.Adam(trained.parameters(), lr=learning_rate, foreach=False)
        receipt["diagnostics"].append(dict(optimizer_step=0,
            binding=evaluate_reader(trained, data, cases=cases, depth=depth, batch_size=batch_size)))
        passed, status = False, "max_updates_reached"
        for step, indices in enumerate(batches, 1):
            if time.perf_counter_ns() - wall >= wall_time_ns:
                status = "budget_stopped"
                break
            receipt["attempted_step"] = step
            selected = [cases[index] for index in indices]
            record = _optimizer_step(trained, optimizer, data, indices, depth=depth,
                pair_weight=pair_weight, pairs=world_pairs(selected), case_ids=[case.case_id for case in selected])
            record["step"] = step
            receipt["updates"].append(record)
            receipt.update(completed_steps=step, actual_training_exposures=step * batch_size)
            if step % diagnostic_interval == 0 or step == steps:
                diagnostic = evaluate_reader(trained, data, cases=cases, depth=depth, batch_size=batch_size)
                receipt["diagnostics"].append(dict(optimizer_step=step, binding=diagnostic))
                passed = (diagnostic["accuracy"] == 1. and diagnostic["both_worlds_correct"] == 1.
                          and diagnostic["binary_cross_entropy"] <= .10)
                if passed:
                    status = "train_gate_passed"
                    break
        receipt.update(case_exposures=dict(Counter(case_id for row in receipt["updates"] for case_id in row["case_ids"])))
        receipt.update(status=status, train_gate_passed=passed,
            sampler="complete_four_case_groups_without_replacement_per_epoch",
            wall_time_budget_ns=wall_time_ns, final_evaluation_authorized=False)
        receipt.update(_optimizer_storage(optimizer, trained))
        trained, receipt = _finish(model, trained, data, initial_digest, receipt)
        receipt.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            timing_scope="complete_call_validation_copy_optimizer_materialization_updates_diagnostics_freeze_receipt")
        return trained, receipt
    except Exception as error:
        _failed(error, receipt, wall, cpu, failure_receipt_fn)
