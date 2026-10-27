"""Local actuator, complete optimizer snapshots, and hard development outputs."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from ..v6.data import make_batch, render_tokens, SourceCorpus
from ..v6.observer import observe_tensors
from ..field_bridge_20261027.adapters import LocalAdapter, local_parameters, local_state, local_hash
from ..field_bridge_20261027.adaptation import fixed_output

P = json.loads(Path(__file__).with_name("PILOT_PROTOCOL.json").read_text())


def make_model(original, seed, recipe):
    model = deepcopy(original).cpu().eval().requires_grad_(False)
    generator = torch.Generator().manual_seed(seed * 917 + 271027)
    for name in P[recipe["modules"] + "_modules"]:
        parent_name, _, leaf = name.rpartition(".")
        parent = model.get_submodule(parent_name) if parent_name else model
        setattr(parent, leaf, LocalAdapter(parent.get_submodule(leaf), recipe["rank"], generator))
    return model


def new_optimizer(model, recipe):
    return torch.optim.SGD(local_parameters(model), lr=recipe["learning_rate"], momentum=P["momentum"])


def gradient_corpus(corpus):
    source, n = corpus.splits["train"], P["gradient_source_count"]
    return SourceCorpus({**corpus.splits, "train": replace(source, images=source.images[:n],
        labels=source.labels[:n], ids=source.ids[:n], pixel_hashes=source.pixel_hashes[:n])}, corpus.manifest)


def panel(corpus, specification, seed):
    return [(condition, make_batch(corpus, specification["split"], specification["pairs"],
             812027 + seed * 71 + index, offset=specification["offset"], corruption=condition))
            for index, condition in enumerate(specification["conditions"])]


@torch.inference_mode()
def hard_outputs(model, batches, observer, action):
    values, semantics, hashes = [], [], []
    by_condition = {}
    for index, (condition, batch) in enumerate(batches):
        output = fixed_output(model, batch, action, 91027 + index)
        pixels = (output.image_logits.sigmoid() * 255).round().to(torch.uint8)
        captions = [render_tokens(row) for row in output.token_ids]
        scores = observe_tensors(observer, pixels.float() / 255, captions, batch.target.pixels, batch.target.labels)
        current = [row["utility"] - P["charge"] * (1 + (action != 0)) for row in scores]
        values.extend(current)
        by_condition[condition] = float(np.mean(current))
        for i, row in enumerate(scores):
            semantics.append([captions[i], *row["image_digits"]])
            hashes.append(hashlib.sha256(pixels[i].numpy().tobytes() + captions[i].encode()).hexdigest())
    return {"value": float(np.mean(values)), "values": values, "by_condition": by_condition,
            "decisions": semantics, "output_sha256": hashes}


def update(model, original, optimizer, batch, action, multiplier, noise_seed, recipe):
    output = fixed_output(model, batch, action, noise_seed, teacher=True)
    with torch.no_grad():
        reference = fixed_output(original, batch, action, noise_seed, teacher=True)
    supervised = model.loss(output, batch.target)["joint"].mean()
    anchor = (output.image_logits.sigmoid() - reference.image_logits.sigmoid()).square().mean()
    anchor = anchor + .1 * F.kl_div(output.text_logits.log_softmax(-1), reference.text_logits.softmax(-1), reduction="batchmean")
    objective = supervised + P["teacher_anchor"] * anchor
    optimizer.zero_grad(set_to_none=True)
    objective.backward()
    norm = torch.nn.utils.clip_grad_norm_(local_parameters(model), P["gradient_clip"])
    if not torch.isfinite(objective) or not torch.isfinite(norm):
        raise FloatingPointError("Nonfinite local training objective/gradient")
    if multiplier:
        for group in optimizer.param_groups:
            group["lr"] = recipe["learning_rate"] * multiplier
        optimizer.step()
    return {"loss": float(objective.detach()), "gradient_norm": float(norm), "advanced": bool(multiplier)}


def train_steps(model, original, optimizer, data, action, recipe, seed, trajectory, start, count, multiplier=1.):
    for step in range(start, start + count):
        batch_seed = seed * 100003 + 600000 + trajectory * 1009 + step
        batch = make_batch(data, "train", P["batch_size"], batch_seed,
                           corruption=P["conditions"][step % 4])
        update(model, original, optimizer, batch, action, multiplier, 107 + step, recipe)


def displacement(model, recipe):
    return [float((m.up @ m.down).norm() / m.base.weight.norm().clamp_min(1e-12))
            for m in [model.get_submodule(name) for name in P[recipe["modules"] + "_modules"]]]


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


def clone_optimizer_model(model, optimizer, recipe):
    copied = deepcopy(model)
    copied_optimizer = new_optimizer(copied, recipe)
    copied_optimizer.load_state_dict(deepcopy(optimizer.state_dict()))
    if local_hash(copied) != local_hash(model) or optimizer_hash(copied_optimizer) != optimizer_hash(optimizer):
        raise RuntimeError("Complete local state clone failed")
    return copied, copied_optimizer


def save_model(path, model, optimizer, recipe, metadata):
    record = {"schema": "hepta.field-bridge.v2.adapter", "parameters": local_state(model),
              "optimizer": optimizer.state_dict(), "recipe": recipe, "metadata": metadata,
              "local_sha256": local_hash(model), "optimizer_sha256": optimizer_hash(optimizer)}
    torch.save(record, path)
    reread = torch.load(path, map_location="cpu", weights_only=True)
    if any(not torch.equal(value, reread["parameters"][name]) for name, value in record["parameters"].items()):
        raise RuntimeError("Serialized local parameters changed")


@torch.no_grad()
def observe_field(model, optimizer, recipe, response, clean, action, step, current_value):
    losses = []
    for index, (_, batch) in enumerate(response):
        output = fixed_output(model, batch, action, 71027 + index, teacher=True)
        losses.append(model.loss(output, batch.target))
    adapt_image = float(torch.stack([x["image_bce"].mean() for x in losses]).mean())
    adapt_text = float(torch.stack([x["text_ce"].mean() for x in losses]).mean())
    adapt_digit = float(torch.stack([x["digit_ce"].mean() for x in losses]).mean())
    out_c = fixed_output(model, clean[0][1], action, 81027, teacher=True)
    loss_c = model.loss(out_c, clean[0][1].target)
    buffers = [fields["momentum_buffer"] for fields in optimizer.state.values() if "momentum_buffer" in fields]
    mom = (sum(float(b.square().sum()) for b in buffers) / max(sum(b.numel() for b in buffers), 1)) ** .5
    delta = displacement(model, recipe)
    field = [current_value, adapt_image, adapt_text, float(loss_c["joint"].mean()),
             float(np.sqrt(np.mean(np.square(delta)))), mom, step / recipe["steps"]]
    rich = field + [adapt_digit, float(loss_c["image_bce"].mean()), float(loss_c["text_ce"].mean()),
                    float(loss_c["digit_ce"].mean()), *delta]
    if not np.isfinite(rich).all():
        raise FloatingPointError("Nonfinite field state")
    return rich
