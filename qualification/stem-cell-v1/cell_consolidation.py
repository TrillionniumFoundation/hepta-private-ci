"""Candidate-only two-Cell consolidation on frozen features, not a live update.

All models use the existing bounded FiLM Head factory and the same eight-way
output schema. Tasks are training partitions only; inference receives no task ID.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import time

import torch
from torch.nn import functional as F

from development_study_data import digest
from development_tensors import checked_tensor, parameter_digest
from model_runner import build_head, train_head

ARMS = ("frozen", "new_only", "label_replay", "distilled", "all_old_replay", "teacher_mean")


@dataclass(frozen=True)
class ConsolidationConfig:
    classes: int = 8
    old_classes: tuple = (0, 1, 2, 3)
    steps: int = 200
    memory_per_class: int = 8
    seed: int = 7347
    temperature: float = 2.0
    maximum_old_accuracy_drop: float = 0.02
    maximum_old_brier_increase: float = 0.02

    def validate(self):
        for name, low, high in (("classes", 4, 16), ("steps", 1, 1000),
                               ("memory_per_class", 1, 32), ("seed", 0, 2**31-1)):
            v = getattr(self, name)
            if type(v) is not int or not low <= v <= high:
                raise ValueError(f"invalid consolidation {name}")
        if (type(self.old_classes) is not tuple or not 1 < len(self.old_classes) < self.classes
                or any(type(v) is not int or not 0 <= v < self.classes for v in self.old_classes)
                or tuple(sorted(set(self.old_classes))) != self.old_classes):
            raise ValueError("invalid fixed old/new class partition")
        for name, low, high in (("temperature", .1, 10.), ("maximum_old_accuracy_drop", 0., 1.),
                               ("maximum_old_brier_increase", 0., 2.)):
            v = getattr(self, name)
            if type(v) not in (float, int) or not math.isfinite(v) or not low <= v <= high:
                raise ValueError(f"invalid consolidation {name}")
        return self


def training_partition(inputs, truth, config):
    """Only base/adapt labels are admitted. Memory never comes from calibration."""
    config.validate()
    if (not isinstance(inputs, tuple) or not 1 <= len(inputs) <= 4096
            or len({r["sample_id"] for r in inputs}) != len(inputs)
            or set(truth) != {r["sample_id"] for r in inputs if r["phase"] in ("base", "adapt")}
            or any(type(y) is not int or not 0 <= y < config.classes for y in truth.values())):
        raise ValueError("consolidation training-label boundary mismatch")
    old = [i for i, r in enumerate(inputs) if r["phase"] == "base" and truth[r["sample_id"]] in config.old_classes]
    new = [i for i, r in enumerate(inputs) if r["phase"] == "adapt" and truth[r["sample_id"]] not in config.old_classes]
    memory = []
    for label in range(config.classes):
        pool = [i for i in (old if label in config.old_classes else new)
                if truth[inputs[i]["sample_id"]] == label]
        if len(pool) < (config.memory_per_class if label in config.old_classes else 2):
            raise ValueError("missing old/new training support")
        if label in config.old_classes:
            ordered = sorted(pool, key=lambda i: digest(inputs[i]["input_fingerprint"]))
            groups = set()
            for i in ordered:
                if inputs[i]["source_group"] not in groups:
                    groups.add(inputs[i]["source_group"])
                    memory.append(i)
                if len(groups) == config.memory_per_class:
                    break
            if len(groups) < config.memory_per_class:
                raise ValueError("insufficient distinct replay content groups")
    return old, new, memory


def fit_consolidation(inputs, truth, features, config):
    """New learning, label replay and two-teacher distillation from one parent.

    Label-replay and distillation use identical 16-old/16-new minibatch schedules,
    identical student initialization, optimizer, steps and parameter counts.
    Extra teacher preparation/work is measured separately, not declared free.
    """
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    old, new, memory = training_partition(inputs, truth, config)
    checked_tensor(features, 2, "consolidation source features")
    if features.dtype != torch.float32 or len(features) != len(inputs) or not 1 <= features.shape[1] <= 512:
        raise ValueError("invalid consolidation feature shape/dtype")
    mean, scale = features[old].mean(0), features[old].std(0, unbiased=False).clamp_min(1e-6)
    # Evaluation values are not even normalized until after fitting/selection.
    x = {key: (features[rows].detach().clone() - mean) / scale
         for key, rows in (("old", old), ("new", new), ("memory", memory))}
    for values in x.values():
        checked_tensor(values, 2, "normalized consolidation training")
    y = {key: torch.tensor([truth[inputs[i]["sample_id"]] for i in rows])
         for key, rows in (("old", old), ("new", new), ("memory", memory))}
    costs = {}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        parent, count = build_head(torch, features.shape[1], config.classes, "film", 16384)
        before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
        train_head(torch, parent, x["old"], y["old"], steps=config.steps, seed=config.seed)
        parent.requires_grad_(False).eval()
        costs["parent_training"] = {"cpu_ns": time.process_time_ns()-before_cpu,
            "wall_ns": time.perf_counter_ns()-before_wall, "steps": config.steps,
            "sample_presentations": config.steps*min(32, len(old))}
        models = {"frozen": parent, "new_only": deepcopy(parent).requires_grad_(True)}
        before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
        train_head(torch, models["new_only"], x["new"], y["new"], steps=config.steps, seed=config.seed+1)
        models["new_only"].requires_grad_(False).eval()
        costs["new_only"] = {"cpu_ns": time.process_time_ns()-before_cpu,
            "wall_ns": time.perf_counter_ns()-before_wall, "steps": config.steps,
            "sample_presentations": config.steps*min(32, len(new))}
        teacher_ids = {k: parameter_digest(m) for k, m in models.items()}
        before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
        with torch.no_grad():
            targets = torch.cat((parent(x["memory"]), models["new_only"](x["new"])))
            checked_tensor(targets, 2, "sealed teacher logits")
            target_probs = F.softmax(targets / config.temperature, -1)
        costs["teacher_preparation"] = {"cpu_ns": time.process_time_ns()-before_cpu,
            "wall_ns": time.perf_counter_ns()-before_wall, "forward_rows": len(targets),
            "probability_tensor_bytes": target_probs.numel()*target_probs.element_size(),
            "teacher_logits_sha256": digest(targets.tolist())}
        for name in ("label_replay", "distilled", "all_old_replay"):
            before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
            student = deepcopy(parent).requires_grad_(True)
            old_key = "old" if name == "all_old_replay" else "memory"
            xx, yy = torch.cat((x[old_key], x["new"])), torch.cat((y[old_key], y["new"]))
            n_old = len(x[old_key])
            optimizer = torch.optim.AdamW(student.parameters(), lr=1e-3, weight_decay=.01)
            rng = torch.Generator().manual_seed(config.seed+2)
            for _ in range(config.steps):
                indices = torch.cat((torch.randint(n_old, (16,), generator=rng),
                                     n_old+torch.randint(len(new), (16,), generator=rng)))
                logits = student(xx[indices])
                loss = (F.kl_div(F.log_softmax(logits/config.temperature, -1), target_probs[indices],
                                 reduction="batchmean")*config.temperature**2 if name == "distilled"
                        else F.cross_entropy(logits, yy[indices]))
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite consolidation loss")
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            student.requires_grad_(False).eval()
            if any(not torch.isfinite(t).all() for t in student.state_dict().values()):
                raise ValueError("nonfinite consolidated candidate")
            models[name] = student
            costs[name] = {"cpu_ns": time.process_time_ns()-before_cpu,
                "wall_ns": time.perf_counter_ns()-before_wall, "steps": config.steps,
                "sample_presentations": config.steps*32, "old_replay_rows": n_old,
                "replay_feature_bytes": x[old_key].numel()*x[old_key].element_size()}
        if any(parameter_digest(models[k]) != h for k, h in teacher_ids.items()):
            raise ValueError("teacher was mutated during consolidation")
    costs.update({"head_parameters": count, "single_head_weight_bytes": count*4,
        "two_teacher_weight_bytes": count*8, "current_encoder_calls": 0,
        "all_training_cpu_ns": time.process_time_ns()-start_cpu,
        "all_training_wall_ns": time.perf_counter_ns()-start_wall,
        "teacher_training_shared_once_not_free": True})
    return models, mean, scale, costs, {"old": old, "new": new, "memory": memory}


def outputs(models, x):
    with torch.no_grad():
        result = {name: model(x) for name, model in models.items()}
        # Task-agnostic probability ensemble; no oracle choosing the right teacher.
        result["teacher_mean"] = torch.logsumexp(torch.stack((
            F.log_softmax(result["frozen"], -1), F.log_softmax(result["new_only"], -1))), 0)-math.log(2)
    for value in result.values():
        checked_tensor(value, 2, "consolidated output")
    return result


def metrics(logits, labels, groups, config):
    """Report every class, then old/new macro means; repeated source rows weigh once."""
    if (logits.shape != (len(groups), config.classes) or labels.shape != (len(groups),)
            or labels.dtype != torch.long or labels.device.type != "cpu"
            or bool(((labels < 0) | (labels >= config.classes)).any())):
        raise ValueError("invalid consolidation evaluation census")
    checked_tensor(logits, 2, "metric logits")
    probs = F.softmax(logits, -1)
    brier = (probs-F.one_hot(labels, config.classes)).square().sum(-1).tolist()
    hits = (logits.argmax(-1) == labels).float().tolist()
    per_class = {}
    for label in range(config.classes):
        buckets = {}
        for i, group in enumerate(groups):
            if int(labels[i]) == label:
                buckets.setdefault(group, []).append((hits[i], brier[i]))
        if not buckets:
            raise ValueError("missing old/new evaluation class")
        a = [sum(v[j] for v in rows)/len(rows) for rows in buckets.values() for j in (0, 1)]
        per_class[str(label)] = {"groups": len(buckets), "accuracy": sum(a[::2])/len(buckets),
                                  "brier": sum(a[1::2])/len(buckets)}
    result = {"per_class": per_class}
    for name, keys in (("old", config.old_classes), ("new", tuple(i for i in range(config.classes) if i not in config.old_classes))):
        result[name] = {m: sum(per_class[str(i)][m] for i in keys)/len(keys) for m in ("accuracy", "brier")}
    return result


def select_retained(metrics_by_arm, config, *, extra_arms=()):
    """Empirical calibration floor, NOT a confidence guarantee or production gate."""
    if (type(extra_arms) is not tuple or len(extra_arms) > 8
            or any(type(n) is not str or not n or len(n) > 64 or not n.replace("_", "").isalnum() for n in extra_arms)
            or len(set(ARMS + extra_arms)) != len(ARMS + extra_arms)):
        raise ValueError("invalid explicit additional research controls")
    arms = ARMS + extra_arms
    if set(metrics_by_arm) != set(arms):
        raise ValueError("missing consolidation controls")
    config.validate()
    reference = metrics_by_arm["frozen"]
    eligible = ["frozen"]
    floors = {}
    for name in arms[1:]:
        score = metrics_by_arm[name]
        retained = all(score["per_class"][str(k)]["accuracy"] >= reference["per_class"][str(k)]["accuracy"]-config.maximum_old_accuracy_drop
                       and score["per_class"][str(k)]["brier"] <= reference["per_class"][str(k)]["brier"]+config.maximum_old_brier_increase
                       for k in config.old_classes)
        gain = score["new"]["accuracy"] > reference["new"]["accuracy"]
        floors[name] = {"per_old_class_floor_met": retained, "new_accuracy_improved": gain}
        if retained and gain:
            eligible.append(name)
    winner = min(eligible, key=lambda n: (metrics_by_arm[n]["old"]["brier"]+metrics_by_arm[n]["new"]["brier"])/2)
    return {"selected_arm": winner, "calibration_floors": floors,
            "statistical_superiority_established": False, "production_authorized": False}
