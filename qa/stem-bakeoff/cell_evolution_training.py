"""Real offline warm-start split and teacher-distilled merge, with fixed caps.

Partitions are explicit source-group-separated research inputs. This module does
not claim an independently accepted automatic split trigger or memory benefit.
"""

from dataclasses import asdict, dataclass, replace
import copy
import hashlib
import math
import re

import torch
from torch import nn

from cell_head_training import (HeadTrainingConfigV1, TrainedCellHeadV1, TEMPERATURES,
                                TRAINED_PREFIXES, _cohort, _json_bytes, _state_digest, task_metrics)
from cell_router_training import RouterCellV1, RouterTrainingConfigV1, train_cell_router
from cell_evolution_snapshot import (EvolutionError, check_budget, check_sources, digest,
                                     group_digest, load_snapshot, _persist_snapshot, tensor_bytes)
from multimodal_bridge import _verify_optimizer_lifecycle


@dataclass(frozen=True)
class EvolutionTrainingConfigV1:
    steps: int = 100
    learning_rate: float = 0.1
    distillation_weight: float = 0.5

    def validate(self):
        if (type(self.steps) is not int or not 1 <= self.steps <= 5000
                or type(self.learning_rate) not in (int, float)
                or not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= 1
                or type(self.distillation_weight) not in (int, float)
                or not math.isfinite(self.distillation_weight) or not 0 <= self.distillation_weight <= 1):
            raise EvolutionError("invalid bounded descendant training configuration")


def _views(parent, trains, calibration, holdouts, router_train=None, router_calibration=None):
    if (not isinstance(holdouts, dict) or not 1 <= len(holdouts) <= 6
            or any(not isinstance(k, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", k)
                   or k in ("train", "calibration", "router_train", "router_calibration") for k in holdouts)):
        raise EvolutionError("named separate evolution holdouts required")
    cohorts = {**{f"child_{i}": c for i, c in enumerate(trains)}, "calibration": calibration,
               **{f"holdout:{name}": c for name, c in holdouts.items()}}
    if router_train is not None:
        cohorts.update(router_train=router_train, router_calibration=router_calibration)
    task_count = parent.cells[0].head.report["config"]["task_count"]
    width = parent.cells[0].head.report["feature_width"]
    views = {name: _cohort(cohort, task_count) for name, cohort in cohorts.items()}
    if sum(len(v["rows"]) for v in views.values()) > 2048:
        raise EvolutionError("evolution replay row budget exceeded")
    prior = set(parent.report["source_closure"])
    protected = set(parent.report["protected_evaluation_sources"])
    seen = set()
    for name, view in views.items():
        sources = set(view["rows"]) | {group_digest(g) for g in view["groups"]}
        if view["identity"] != parent.identity or view["features"].shape[1] != width or sources & seen:
            raise EvolutionError("evolution split identity mismatch or source record/group leakage")
        seen.update(sources)
        forbidden = set(protected) if name.startswith("child_") else set(prior)
        if name in ("calibration", "router_train", "router_calibration"):
            forbidden |= protected
        if sources & forbidden:
            raise EvolutionError("ancestor learning/evaluation source leakage")
        if name.startswith("child_") and len(view["labels"].unique()) < 2:
            raise EvolutionError("each descendant replay requires two observed classes")
    return views, seen


def _trainable(head):
    prefixes = TRAINED_PREFIXES if head.report["config"]["mode"] == "gated" else ("task_head.",)
    return [(name, parameter) for name, parameter in head._head.named_parameters() if name.startswith(prefixes)]


def _reservation(parent, template, views, child_count, config, router_config, budget):
    check_budget({"inference_cost_units_per_row": template.cost_units}, budget)
    head_bytes = tensor_bytes([template.head._head])
    parameters = sum(p.numel() for _, p in _trainable(template.head))
    train_rows = [len(v["rows"]) for key, v in views.items() if key.startswith("child_")]
    evaluation_rows = len(views["calibration"]["rows"]) + sum(len(v["rows"])
        for key, v in views.items() if key.startswith("holdout:"))
    # Every student update is an actual Head forward; frozen teachers execute once.
    calls = sum(train_rows) * (config.steps + 1) + child_count * evaluation_rows
    if child_count == 1:
        calls += len(parent.cells) * train_rows[0]
    router_bytes = router_parameters = router_steps = 0
    if router_config is not None:
        router_config.validate()
        if template.cost_units > router_config.budget_units:
            raise EvolutionError("no legal descendant within Router budget")
        width = template.head.report["feature_width"]
        hidden = router_config.hidden_width
        router_parameters = ((width + 1) * hidden + (hidden + 1) * child_count if hidden
                             else (width + 1) * child_count)
        router_bytes = 4 * (router_parameters + 2 * width)
        rows, cal_rows = len(views["router_train"]["rows"]), len(views["router_calibration"]["rows"])
        held_rows = evaluation_rows - len(views["calibration"]["rows"])
        calls += rows * child_count + cal_rows * (2 * router_config.top_k + child_count)
        calls += 2 * router_config.top_k * (rows + cal_rows + held_rows)
        router_steps = rows * router_config.steps
        check_budget({"inference_cells_per_row": router_config.top_k,
                      "inference_cost_units_per_row": router_config.budget_units}, budget)
    candidate_bytes = child_count * head_bytes + router_bytes
    gradient = 4 * max(parameters, router_parameters)
    feature_bytes = sum(v["features"].numel() * v["features"].element_size() for v in views.values())
    largest = max(len(v["rows"]) for v in views.values())
    width, classes = template.head.report["feature_width"], template.head.report["config"]["task_count"]
    scratch = 8 * feature_bytes + largest * (width * 16 + classes * 16 + 256) * 4
    usage = {"cells": child_count, "resident_tensor_bytes": candidate_bytes,
        "transition_tensor_bytes": 2 * parent.report["resident_tensor_bytes"] + 3 * candidate_bytes + gradient + scratch,
        "gradient_bytes": gradient, "optimizer_state_bytes": 0, "head_example_calls": calls,
        "parameter_example_updates": sum(train_rows) * config.steps * parameters + router_steps * router_parameters,
        "router_example_steps": router_steps}
    check_budget(usage, budget)
    return usage


def _fit(template, train, calibration, holdouts, config, parent, teachers=()):
    head_config = replace(HeadTrainingConfigV1(**template.head.report["config"]),
                         steps=config.steps, learning_rate=config.learning_rate)
    child = copy.deepcopy(template.head._head)
    initial = {name: value.detach().clone() for name, value in child.state_dict().items()}
    initial_digest = _state_digest(child)
    if initial_digest != template.head.report["trained_tensor_sha256"]:
        raise EvolutionError("warm start did not reproduce persisted parent tensors")
    parent_storages = {p.untyped_storage().data_ptr() for c in parent.cells for p in c.head._head.parameters()}
    if any(p.untyped_storage().data_ptr() in parent_storages for p in child.parameters()):
        raise EvolutionError("descendant shares writable parent storage")
    names = {name for name, _ in _trainable(template.head)}
    for name, parameter in child.named_parameters():
        parameter.requires_grad_(name in names)
    parameters = tuple(p for p in child.parameters() if p.requires_grad)
    owner_ids = tuple(id(p) for p in parameters)
    optimizer = torch.optim.SGD(parameters, lr=config.learning_rate)
    _verify_optimizer_lifecycle(optimizer)
    targets, teacher_receipts = None, []
    if teachers:
        matrices = []
        for cell in teachers:
            with torch.inference_mode():
                states = torch.zeros((len(train["rows"]), cell.head._head.state_width), dtype=torch.float32)
                logits = cell.head._head(train["features"], states)["task_logits"]
                probabilities = (logits / cell.head.report["temperature"]).softmax(-1)
            matrices.append(probabilities)
            teacher_receipts.append({"cell_id": cell.cell_id, "head_tensor_sha256": cell.head.report["trained_tensor_sha256"],
                "head_example_calls": len(train["rows"]), "head_module_invocations": 1,
                "probabilities_sha256": hashlib.sha256(probabilities.numpy().tobytes()).hexdigest(),
                "observed_nll": float(-probabilities.gather(1, train["labels"][:, None]).clamp_min(1e-12).log().mean())})
        targets = torch.stack(matrices).mean(0).detach()
    state = torch.zeros((len(train["rows"]), child.state_width), dtype=torch.float32)
    losses, gradient_bytes = [], 0
    for _ in range(config.steps):
        _verify_optimizer_lifecycle(optimizer)
        if tuple(id(p) for group in optimizer.param_groups for p in group["params"]) != owner_ids:
            raise EvolutionError("optimizer crossed descendant parameter boundary")
        optimizer.zero_grad(set_to_none=True)
        logits = child(train["features"], state)["task_logits"]
        loss = nn.functional.cross_entropy(logits, train["labels"])
        if targets is not None:
            soft_loss = -(targets * logits.log_softmax(-1)).sum(-1).mean()
            loss = (1 - config.distillation_weight) * loss + config.distillation_weight * soft_loss
        if not bool(torch.isfinite(loss)):
            raise EvolutionError("nonfinite descendant loss")
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):
            raise EvolutionError("missing/nonfinite descendant gradient")
        gradient_bytes = max(gradient_bytes, sum(p.grad.numel() * p.grad.element_size() for p in parameters))
        nn.utils.clip_grad_norm_(parameters, 5.0, error_if_nonfinite=True)
        _verify_optimizer_lifecycle(optimizer)
        optimizer.step()
        if any(not bool(torch.isfinite(p).all()) for p in parameters):
            raise EvolutionError("nonfinite descendant parameters")
        losses.append(float(loss.detach()))
    for parameter in child.parameters():
        parameter.grad = None
    child.eval().requires_grad_(False)
    changed = [name for name, value in child.state_dict().items() if not torch.equal(value, initial[name])]
    if not changed or not set(changed) <= names:
        raise EvolutionError("descendant did not update private allowed parameters")
    cohorts = {"train": train, "calibration": calibration, **holdouts}
    with torch.inference_mode():
        outputs = {name: child(view["features"], torch.zeros((len(view["rows"]), child.state_width),
            dtype=torch.float32))["task_logits"] for name, view in cohorts.items()}
    temperature = min(TEMPERATURES, key=lambda t: (float(nn.functional.cross_entropy(
        outputs["calibration"].double() / t, calibration["labels"])), abs(math.log(t)), t))
    splits = {name: {"bundle_digests": view["bundle_digests"], "source_record_digests": list(view["rows"]),
        "source_group_sha256": hashlib.sha256(_json_bytes(view["groups"])).hexdigest(),
        "labels_sha256": hashlib.sha256(view["labels"].numpy().tobytes()).hexdigest(),
        "unique_source_groups": len(set(view["groups"])), "metrics": {"calibrated": task_metrics(
            outputs[name], view["labels"], temperature=temperature, confidence_threshold=head_config.confidence_threshold)}}
        for name, view in cohorts.items()}
    report = {"schema": "hepta.trained-cell-task-head.v1", "config": asdict(head_config),
        "feature_identity": asdict(template.head.identity), "feature_width": template.head.report["feature_width"],
        "initial_tensor_sha256": initial_digest, "trained_tensor_sha256": _state_digest(child),
        "optimizer": "torch.optim.SGD", "optimizer_steps": config.steps, "optimizer_state_bytes": 0,
        "optimizer_owned_parameter_names": sorted(names), "changed_parameter_names": changed,
        "trainable_parameter_count": sum(p.numel() for p in parameters),
        "resident_parameter_count": sum(p.numel() for p in child.parameters()),
        "initial_train_loss": losses[0], "last_train_loss_before_step": losses[-1],
        "temperature": temperature, "calibration_split": "calibration", "encoder_training_steps": 0,
        "local_state_training": "zero_state_only", "source_groups_disjoint": True,
        "action_head_status": "inherited_frozen", "value_head_status": "inherited_frozen",
        "uncertainty_head_status": "inherited_not_calibrated", "temporal_provenance_verified": False,
        "splits": splits, "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False,
        "evolution": {"requires_evolution_snapshot": True, "parent_snapshot_sha256": parent.manifest_sha256,
            "parent_cell_id": template.cell_id, "parent_source_closure_sha256": digest(parent.report["source_closure"]),
            "teacher_observations": teacher_receipts, "distillation_weight": config.distillation_weight if teachers else 0,
            "training_objective": "supervised_plus_teacher_probability_cross_entropy" if teachers else "supervised",
            "gradient_bytes": gradient_bytes,
            "head_example_calls": len(train["rows"]) * config.steps + sum(len(v["rows"]) for v in cohorts.values())
                + len(teachers) * len(train["rows"]),
            "head_module_invocations": config.steps + len(cohorts) + len(teachers)}}
    return TrainedCellHeadV1(child, template.head.identity, report)


def _prepare(parent, config, views, sources, reservation, budget, withdrawal_provider):
    if torch.get_default_dtype() != torch.float32:
        raise EvolutionError("existing Head inference ABI requires default float32")
    check_budget(reservation, budget)
    before = check_sources(set(parent.report["source_closure"]) | sources, parent.identity,
                           withdrawal_provider, parent.report["withdrawal_view"])
    loaded = load_snapshot(parent.directory, expected_manifest_sha256=parent.manifest_sha256,
                           budget=budget, withdrawal_provider=withdrawal_provider)
    return loaded, before


def _finish(parent, cells, router, router_groups, directory, budget, provider, before,
            reservation, operation, details):
    # Check actual work against the preflight reservation and the caller's cap.
    head_reports = [c.head.report for c in cells]
    calls = sum(r["evolution"]["head_example_calls"] for r in head_reports)
    router_calls = router.report["execution_accounting"]["total"]["head_example_calls"] if router else 0
    router_steps = (len(router.report["splits"]["train"]["source_record_digests"])
                    * router.report["config"]["steps"]) if router else 0
    updates = sum(len(r["splits"]["train"]["source_record_digests"]) * r["optimizer_steps"]
                  * r["trainable_parameter_count"] for r in head_reports)
    actual = {"cells": len(cells), "head_example_calls": calls + router_calls,
        "resident_tensor_bytes": tensor_bytes([c.head._head for c in cells] + ([router._net] if router else [])),
        "optimizer_state_bytes": 0, "router_example_steps": router_steps,
        "parameter_example_updates": updates + (router_steps * router.report["trainable_parameter_count"] if router else 0)}
    check_budget(actual, budget)
    if any(value > reservation[key] for key, value in actual.items()):
        raise EvolutionError("actual work exceeded preflight reservation")
    if parent.require_current(provider) != before:
        raise EvolutionError("withdrawal view changed during evolution")
    receipt = {"reservation": reservation, "actual_usage": actual,
        "transition_tensor_bytes_status": "conservative_explicit_tensor_reservation_not_measured_peak_RSS",
        "gradient_bytes_status": "reserved_upper_bound; measured_Head_gradients_in_training_reports",
        "shared_encoder_bytes_included": False, "optimizer_state_bytes": 0,
        "teacher_head_example_calls": sum(sum(t["head_example_calls"] for t in r["evolution"]["teacher_observations"])
                                         for r in head_reports),
        "head_training_reports": {c.cell_id: c.head.report["evolution"] for c in cells},
        "router_training_accounting": router.report["execution_accounting"] if router else None, **details}
    return _persist_snapshot(cells, router, router_groups, directory, budget, provider,
                            parent=parent, operation=operation, receipt=receipt)


def _two_slot_update(parent, parent_ids, children, calibration, holdouts, router_train,
                     router_calibration, directory, budget, withdrawal_provider,
                     training_config, router_config, operation):
    if type(training_config) is not EvolutionTrainingConfigV1:
        raise EvolutionError("typed evolution training configuration required")
    training_config.validate()
    parent.require_current(withdrawal_provider)
    templates = {c.cell_id: c for c in parent.cells}
    if any(cell_id not in templates for cell_id in parent_ids.values()):
        raise EvolutionError("unknown split parent")
    selected = [templates[parent_ids[key]] for key in sorted(children)]
    signatures = {(c.cost_units, c.head.report["config"]["mode"],
                   tuple((k, tuple(v.shape)) for k, v in c.head._head.state_dict().items())) for c in selected}
    if len(signatures) != 1:
        raise EvolutionError("matched two-slot training requires identical Head shapes and cost")
    template = selected[0]
    entries = sorted(children.items())
    views, sources = _views(parent, [c for _, c in entries], calibration, holdouts, router_train, router_calibration)
    reservation = _reservation(parent, template, views, 2, training_config, router_config, budget)
    loaded, before = _prepare(parent, training_config, views, sources, reservation, budget, withdrawal_provider)
    templates = {c.cell_id: c for c in loaded.cells}
    frozen = {c.cell_id: c.head.report["trained_tensor_sha256"] for c in loaded.cells}
    held = {name: views[f"holdout:{name}"] for name in holdouts}
    cells = []
    for index, (cell_id, cohort) in enumerate(entries):
        template = templates[parent_ids[cell_id]]
        head = _fit(template, views[f"child_{index}"], views["calibration"], held, training_config, loaded)
        groups = {"train": cohort.source_group_ids, "calibration": calibration.source_group_ids,
                  **{name: c.source_group_ids for name, c in holdouts.items()}}
        cells.append(RouterCellV1(cell_id, head, template.cost_units, groups))
    if any(_state_digest(c.head._head) != frozen[c.cell_id] for c in loaded.cells):
        raise EvolutionError("parent tensors changed during two-slot training")
    pointers = [{p.untyped_storage().data_ptr() for p in c.head._head.parameters()} for c in cells]
    if pointers[0] & pointers[1]:
        raise EvolutionError("children share writable storage")
    router = train_cell_router(router_train, router_calibration, holdouts, cells, router_config)
    groups = {"train": router_train.source_group_ids, "calibration": router_calibration.source_group_ids,
              **{name: c.source_group_ids for name, c in holdouts.items()}}
    return _finish(parent, cells, router, groups, directory, budget, withdrawal_provider, before,
        reservation, operation, {"warm_start_parent_ids": parent_ids, "structure_changed": operation == "split",
            "retired_cell_ids": [c.cell_id for c in parent.cells] if operation == "split" else [],
            "child_cell_ids": [c.cell_id for c in cells],
            "partition_sha256": digest({k: list(c.source_group_ids) for k, c in entries}),
            "partition_selection": "caller_precommitted_source_groups_not_holdout_optimized"})


def split_snapshot(parent, parent_cell_id, children, calibration, holdouts, router_train,
                   router_calibration, directory, budget, withdrawal_provider, *,
                   training_config=EvolutionTrainingConfigV1(), router_config=RouterTrainingConfigV1()):
    """Replace the roster with two privately trained children within two slots."""
    if (not isinstance(children, dict) or len(children) != 2
            or any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", k)
                   or k in parent.report["cell_generation_fences"] for k in children)):
        raise EvolutionError("two fresh child IDs required")
    return _two_slot_update(parent, {key: parent_cell_id for key in children}, children,
        calibration, holdouts, router_train, router_calibration, directory, budget,
        withdrawal_provider, training_config, router_config, "split")


def continue_snapshot(parent, replays, calibration, holdouts, router_train, router_calibration,
                      directory, budget, withdrawal_provider, *,
                      training_config=EvolutionTrainingConfigV1(), router_config=RouterTrainingConfigV1()):
    """Keep two Cell IDs; each warm-starts its own parent with the same update path."""
    if not isinstance(replays, dict) or len(replays) != 2 or set(replays) != {c.cell_id for c in parent.cells}:
        raise EvolutionError("static continuation requires exactly the unchanged two-Cell roster")
    return _two_slot_update(parent, {key: key for key in replays}, replays, calibration, holdouts,
        router_train, router_calibration, directory, budget, withdrawal_provider,
        training_config, router_config, "continue")


def merge_snapshot(parent, new_cell_id, train, calibration, holdouts, directory, budget,
                   withdrawal_provider, *, training_config=EvolutionTrainingConfigV1()):
    """Distill both actual parent Heads into one private warm-start student."""
    if type(training_config) is not EvolutionTrainingConfigV1:
        raise EvolutionError("typed evolution training configuration required")
    training_config.validate()
    parent.require_current(withdrawal_provider)
    if (len(parent.cells) != 2 or training_config.distillation_weight <= 0
            or not isinstance(new_cell_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", new_cell_id)
            or new_cell_id in parent.report["cell_generation_fences"]):
        raise EvolutionError("merge requires two teachers, a fresh ID and positive distillation")
    views, sources = _views(parent, [train], calibration, holdouts)
    template = parent.cells[0]
    reservation = _reservation(parent, template, views, 1, training_config, None, budget)
    loaded, before = _prepare(parent, training_config, views, sources, reservation, budget, withdrawal_provider)
    frozen = {c.cell_id: c.head.report["trained_tensor_sha256"] for c in loaded.cells}
    head = _fit(loaded.cells[0], views["child_0"], views["calibration"],
                {name: views[f"holdout:{name}"] for name in holdouts}, training_config, loaded, loaded.cells)
    if any(_state_digest(c.head._head) != frozen[c.cell_id] for c in loaded.cells):
        raise EvolutionError("teacher tensors changed during merge")
    groups = {"train": train.source_group_ids, "calibration": calibration.source_group_ids,
              **{name: c.source_group_ids for name, c in holdouts.items()}}
    cell = RouterCellV1(new_cell_id, head, template.cost_units, groups)
    return _finish(parent, [cell], None, {}, directory, budget, withdrawal_provider, before,
        reservation, "merge", {"retired_cell_ids": [c.cell_id for c in parent.cells],
                                "merged_cell_id": new_cell_id, "teacher_cell_ids": [c.cell_id for c in loaded.cells]})
