"""V3 weighted learning, complete optimizer transactions, and actual hard outputs."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from ..v6.data import make_batch, render_tokens
from ..v6.observer import observe_tensors
from ..field_bridge_20261027.adapters import LocalAdapter, local_parameters, local_state, local_hash, frozen_base_hash
from ..field_bridge_20261027.adaptation import fixed_output
from .training_common import Costs, configuration, file_hash, object_hash, require


def make_model(original, seed, protocol):
    p = configuration(protocol)
    model = deepcopy(original).cpu().eval().requires_grad_(False)
    generator = torch.Generator().manual_seed(seed * 917 + p["init_seed_offset"])
    for name in p["adapter_modules"]:
        parent_name, _, leaf = name.rpartition(".")
        parent = model.get_submodule(parent_name) if parent_name else model
        base = parent.get_submodule(leaf)
        require(isinstance(base, torch.nn.Linear), f"Adapter location is not Linear: {name}")
        setattr(parent, leaf, LocalAdapter(base, p["adapter_rank"], generator))
    return model


def new_optimizer(model, protocol):
    p = configuration(protocol)
    return torch.optim.SGD(local_parameters(model), lr=p["learning_rate"], momentum=p["momentum"])


def optimizer_hash(optimizer):
    digest = hashlib.sha256()
    state = optimizer.state_dict()
    digest.update(json.dumps(state["param_groups"], sort_keys=True).encode())
    for index, fields in sorted(state["state"].items()):
        digest.update(str(index).encode())
        for name, value in sorted(fields.items()):
            digest.update(name.encode())
            digest.update(value.detach().cpu().contiguous().numpy().tobytes() if torch.is_tensor(value)
                          else repr(value).encode())
    return digest.hexdigest()


def state_identity(model, optimizer):
    return {"parameters": local_hash(model), "optimizer": optimizer_hash(optimizer)}


def snapshot(model, optimizer):
    return {"parameters": local_state(model), "optimizer": deepcopy(optimizer.state_dict()),
            "gradients": [None if p.grad is None else p.grad.detach().clone() for p in local_parameters(model)],
            "identity": state_identity(model, optimizer), "rng": torch.get_rng_state().clone()}


def restore(model, optimizer, saved):
    current = dict(model.named_parameters())
    require(set(saved["parameters"]) == set(local_state(model)), "Incomplete local-state inventory")
    with torch.no_grad():
        for name, value in saved["parameters"].items():
            current[name].copy_(value)
    optimizer.load_state_dict(deepcopy(saved["optimizer"]))
    for parameter, gradient in zip(local_parameters(model), saved["gradients"], strict=True):
        parameter.grad = None if gradient is None else gradient.clone()
    torch.set_rng_state(saved["rng"])
    require(state_identity(model, optimizer) == saved["identity"], "Complete optimizer rollback failed")


def clone_state(model, optimizer, protocol, costs=None):
    copied = deepcopy(model)
    copied_optimizer = new_optimizer(copied, protocol)
    copied_optimizer.load_state_dict(deepcopy(optimizer.state_dict()))
    for source, destination in zip(local_parameters(model), local_parameters(copied), strict=True):
        destination.grad = None if source.grad is None else source.grad.detach().clone()
    require(state_identity(copied, copied_optimizer) == state_identity(model, optimizer), "Complete clone failed")
    if costs is not None:
        costs.add("complete_model_optimizer_clones")
    return copied, copied_optimizer


def save_checkpoint(path, model, optimizer, protocol, metadata):
    path = Path(path)
    require(not path.exists(), f"Refusing checkpoint overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema": "hepta.field-bridge.v3.complete-adapter.1", "parameters": local_state(model),
              "optimizer": optimizer.state_dict(), "training_configuration": configuration(protocol),
              "identity": state_identity(model, optimizer), "frozen_base_sha256": frozen_base_hash(model),
              "metadata": metadata}
    torch.save(record, path)
    reread = torch.load(path, map_location="cpu", weights_only=True)
    require(all(torch.equal(tensor, reread["parameters"][name]) for name, tensor in record["parameters"].items()),
            "Checkpoint serialization changed parameters")
    return {"file_sha256": file_hash(path), **record["identity"], "metadata": metadata}


def load_checkpoint(path, original, seed, protocol):
    record = torch.load(path, map_location="cpu", weights_only=True)
    require(record["schema"] == "hepta.field-bridge.v3.complete-adapter.1"
            and record["training_configuration"] == configuration(protocol), "Checkpoint configuration differs")
    require(record["metadata"]["seed"] == seed, "Checkpoint seed differs")
    model = make_model(original, seed, protocol)
    optimizer = new_optimizer(model, protocol)
    saved = {"parameters": record["parameters"], "optimizer": record["optimizer"], "identity": record["identity"],
             "gradients": [None] * len(local_parameters(model)), "rng": torch.get_rng_state().clone()}
    restore(model, optimizer, saved)
    require(frozen_base_hash(model) == record["frozen_base_sha256"], "Checkpoint original-model identity differs")
    return model, optimizer, record


@dataclass(frozen=True)
class PanelBatch:
    condition: str
    batch: object
    noise_seed: int


def panels(corpus, role, seed, conditions, protocol):
    p, result = configuration(protocol), []
    count = len(corpus.splits[role]) // 2
    role_seed = int(hashlib.sha256(role.encode()).hexdigest()[:8], 16)
    for condition_index, condition in enumerate(conditions):
        for offset in range(0, count, p["panel_batch_size"]):
            pair_count = min(p["panel_batch_size"], count - offset)
            common = seed * 1009 + role_seed + condition_index * 1000003 + offset
            batch = make_batch(corpus, role, pair_count, p["panel_seed_offset"] + common,
                               corruption=condition, offset=offset)
            result.append(PanelBatch(condition, batch, p["hard_forward_seed_offset"] + common))
    return result


def forward(model, batch, action, noise_seed, teacher, costs, name):
    costs.forward(name, len(batch.source_ids), action)
    return fixed_output(model, batch, action, noise_seed, teacher=teacher)


@torch.inference_mode()
def hard_panel(model, panel, observers, action, protocol, costs, name, retain=False):
    p = configuration(protocol)
    values, hashes, captions, pixels, conditions, ids = {key: [] for key in observers}, [], [], [], [], []
    for part in panel:
        batch = part.batch
        output = forward(model, batch, action, part.noise_seed, False, costs, name + "_generator")
        quantized = (output.image_logits.sigmoid() * 255).round().to(torch.uint8)
        emitted = [render_tokens(row).encode("utf-8").decode("utf-8") for row in output.token_ids]
        for observer_name, observer in observers.items():
            costs.add(name + "_" + observer_name + "_observer_calls", 2)
            costs.add(name + "_" + observer_name + "_observer_digit_examples", 2 * len(batch.source_ids))
            scores = observe_tensors(observer, quantized.float() / 255, emitted, batch.target.pixels, batch.target.labels)
            values[observer_name].extend(row["utility"] - p["refinement_charge"] * (1 + (action != 0)) for row in scores)
        hashes.extend(hashlib.sha256(row.numpy().tobytes() + caption.encode("utf-8")).hexdigest()
                      for row, caption in zip(quantized, emitted, strict=True))
        conditions.extend([part.condition] * len(batch.source_ids))
        ids.extend(batch.source_ids)
        if retain:
            pixels.append(quantized.numpy())
            captions.extend(emitted)
    arrays = {key: np.asarray(value, dtype=np.float64) for key, value in values.items()}
    require(all(np.isfinite(value).all() for value in arrays.values()), "Nonfinite hard output utility")
    result = {"values": arrays, "means": {key: float(value.mean()) for key, value in arrays.items()},
              "output_sha256": hashes, "conditions": conditions, "source_ids": ids}
    if retain:
        result.update(pixels_u8=np.concatenate(pixels), captions_utf8=np.asarray(captions, dtype=str))
    return result


def save_hard(path, score):
    arrays = {"values_" + name: value for name, value in score["values"].items()}
    arrays.update(output_sha256=np.asarray(score["output_sha256"], dtype=str),
                  conditions=np.asarray(score["conditions"], dtype=str), source_ids=np.asarray(score["source_ids"], dtype=str))
    for name in ("pixels_u8", "captions_utf8"):
        if name in score:
            arrays[name] = score[name]
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    return {"file_sha256": file_hash(path), "means": score["means"], "rows": len(score["output_sha256"])}


def schedule(seed, schedule_id, start, count, protocol):
    p = configuration(protocol)
    return [{"step": step, "adapt_seed": seed * 100003 + p["batch_seed_offset"] + schedule_id * 1009 + step,
             "clean_seed": seed * 100003 + p["rehearsal_seed_offset"] + schedule_id * 1009 + step,
             "noise_seed": p["forward_seed_offset"] + step,
             "condition": p["conditions"][step % len(p["conditions"])]} for step in range(start, start + count)]


def anchor(output, original):
    image = (output.image_logits.sigmoid() - original.image_logits.sigmoid()).square().mean()
    text = F.kl_div(output.text_logits.log_softmax(-1), original.text_logits.softmax(-1), reduction="batchmean")
    return image + .1 * text


def objective(model, original, adapt, rehearsal, action, noise_seed, protocol, costs, name):
    p, losses = configuration(protocol), []
    for index, batch in enumerate((adapt, rehearsal)):
        output = forward(model, batch, action, noise_seed + index * 1000003, True, costs, name + "_generator")
        with torch.no_grad():
            reference = forward(original, batch, action, noise_seed + index * 1000003, True, costs, name + "_teacher")
        losses.append(model.loss(output, batch.target)["joint"].mean() + p["teacher_anchor"] * anchor(output, reference))
    return (losses[0] + p["clean_loss_weight"] * losses[1]) / (1 + p["clean_loss_weight"])


def update(model, original, optimizer, adapt, rehearsal, action, multiplier, noise_seed, protocol, costs, name="gradient"):
    p = configuration(protocol)
    loss = objective(model, original, adapt, rehearsal, action, noise_seed, protocol, costs, name)
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    costs.add(name + "_backward_calls")
    costs.add(name + "_backward_examples", len(adapt.source_ids) + len(rehearsal.source_ids))
    norm = torch.nn.utils.clip_grad_norm_(local_parameters(model), p["gradient_clip"])
    if not torch.isfinite(loss) or not torch.isfinite(norm):
        raise FloatingPointError("Nonfinite weighted training objective or gradient")
    if multiplier != 0:
        for group in optimizer.param_groups:
            group["lr"] = p["learning_rate"] * multiplier
        optimizer.step()
        costs.add("optimizer_steps")
    costs.add("scheduled_gradient_microsteps") if name == "gradient" else costs.add("directional_gradient_measurements")
    return {"loss": float(loss.detach()), "unclipped_gradient_norm": float(norm), "optimizer_advanced": multiplier != 0}


@dataclass
class Context:
    original: object
    corpus: object
    observers: dict
    seed: int
    group: str
    protocol: dict
    costs: Costs
    probe: list
    guard: list
    baseline_guard: dict

    @property
    def action(self):
        return configuration(self.protocol)["fixed_actions"][str(self.seed)]

    def batches(self, scheduled):
        p = configuration(self.protocol)
        adapt = make_batch(self.corpus, self.group + "_gradient", p["adapt_batch_size"],
                           scheduled["adapt_seed"], corruption=scheduled["condition"])
        clean = make_batch(self.corpus, self.group + "_rehearsal", p["rehearsal_batch_size"],
                           scheduled["clean_seed"], corruption="clean")
        return adapt, clean


def make_context(original, corpus, observers, seed, group, protocol, costs=None):
    p, ledger = configuration(protocol), costs if costs is not None else Costs()
    probe = panels(corpus, group + "_probe", seed, p["conditions"], protocol)
    guard = panels(corpus, group + "_guard", seed, ["clean"], protocol)
    baseline = hard_panel(original, guard, {"reward": observers["reward"]}, p["fixed_actions"][str(seed)],
                          protocol, ledger, "original_guard")
    return Context(original, corpus, observers, seed, group, protocol, ledger, probe, guard, baseline)


def guarded_block(context, model, optimizer, start, action_index, schedule_id):
    p, costs = configuration(context.protocol), context.costs
    require(0 <= action_index < 4 and start in range(0, p["steps"], p["macro_steps"]), "Invalid block/action")
    before_cost, saved, base = costs.snapshot(), snapshot(model, optimizer), frozen_base_hash(model)
    costs.add("transaction_snapshots")
    scheduled = schedule(context.seed, schedule_id, start, p["macro_steps"], context.protocol)
    information = []
    try:
        for row in scheduled:
            adapt, clean = context.batches(row)
            information.append(update(model, context.original, optimizer, adapt, clean, context.action,
                                      p["multipliers"][action_index], row["noise_seed"], context.protocol, costs))
        candidate = state_identity(model, optimizer)
        guard = hard_panel(model, context.guard, {"reward": context.observers["reward"]}, context.action,
                           context.protocol, costs, "candidate_guard")
        delta = float((guard["values"]["reward"] - context.baseline_guard["values"]["reward"]).mean())
        accepted = delta >= p["guard_min_delta"]
        if not accepted:
            restore(model, optimizer, saved)
            costs.add("rejected_blocks")
            costs.add("discarded_gradient_microsteps", p["macro_steps"])
        else:
            costs.add("accepted_blocks")
        require(frozen_base_hash(model) == base, "A frozen original-model parameter changed")
        if action_index == 0:
            require(state_identity(model, optimizer) == saved["identity"], "Zero action changed parameters or momentum")
    except BaseException:
        restore(model, optimizer, saved)
        raise
    return {"start": start, "end": start + p["macro_steps"], "action_index": action_index,
            "multiplier": p["multipliers"][action_index], "schedule_id": schedule_id,
            "schedule_sha256": object_hash(scheduled), "before": saved["identity"], "candidate": candidate,
            "after": state_identity(model, optimizer), "accepted": accepted, "guard_delta": delta,
            "guard_values": guard["values"]["reward"].tolist(), "guard_output_sha256": guard["output_sha256"],
            "first_gradient": information[0], "last_gradient": information[-1],
            "clock_advances_on_rejection": True, "resources": costs.since(before_cost)}
