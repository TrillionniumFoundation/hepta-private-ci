"""Small colour-card content training of the actual v4 encoder/core.

This is a bounded numerical reconstruction exercise, not natural-image or NDU
efficacy evidence. Terminal critics and the legacy action head stay frozen.
"""

import hashlib
import json
import random
import time
import torch

from scripts.joint_generation_v4_model import JointGeneratorV4
from .native import encode_input, load_generator, sha


def colour_card(seed):
    rng = random.Random(seed)
    colour = rng.randrange(3)
    pixels = bytes(
        rng.randrange(128, 256) if channel == colour else rng.randrange(32)
        for _ in range(256)
        for channel in range(3)
    )
    return ("red", "green", "blue")[colour], b"P6\n16 16\n255\n" + pixels


def train(seed=41, steps=12, scope="all-content-v1"):
    if scope not in {"all-content-v1", "private-text-image-adapters-v1"}:
        raise ValueError("Unsupported/future training scope")
    private_scope = scope == "private-text-image-adapters-v1"
    private_prefixes = ("adapters.text.", "adapters.image.")
    if type(steps) is not int or not 1 <= steps <= 128:
        raise ValueError("Content-training step bound")
    started = time.perf_counter()
    torch.set_num_threads(1)
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        model = JointGeneratorV4(
            width=32, depth=1, allow_initial_stop=True, suppress_redundant_verify=True
        )
    baseline = model.export_weights()
    frozen = ("critic.", "delivery_critic.", "actor.")
    trainable_names = []
    for name, parameter in model.named_parameters():
        trainable = (
            name.startswith(private_prefixes)
            if private_scope
            else not name.startswith(frozen)
        )
        parameter.requires_grad_(trainable)
        if trainable:
            trainable_names.append(name)
    if not trainable_names:
        raise AssertionError("No trainable private parameters")
    optimizer = torch.optim.Adam(
        [p for p in model.parameters() if p.requires_grad], lr=0.002
    )
    losses, source_ids = [], []
    for step in range(steps):
        target_text, image = colour_card(seed * 10000 + step)
        public = encode_input("describe colour", image)
        state = model.encode(public)
        for action in ("shared", "image", "text"):
            state = model.advance(state, action, public)
        image_loss = (
            (model.outputs(state)["image"].sigmoid() - public["image"].flatten(1))
            .square()
            .mean()
        )
        text_loss, _ = model.text_loss(state, target_text)
        loss = text_loss + image_loss
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        losses.append(
            {
                "step": step,
                "image_mse": float(image_loss.detach()),
                "text_nll": float(text_loss.detach()),
            }
        )
        source_ids.append(sha(image))
    candidate = model.export_weights()
    before, after = (
        load_generator(baseline).state_dict(),
        load_generator(candidate).state_dict(),
    )
    changed = [key for key in before if not torch.equal(before[key], after[key])]
    if not changed or any(key.startswith(frozen) for key in changed):
        raise AssertionError("Content-training/frozen terminal head contract failed")
    if private_scope and any(not key.startswith(private_prefixes) for key in changed):
        raise AssertionError("Frozen backbone or non-private parameter changed")
    report = {
        "schema": "hepta.bimodal.content-training.v1",
        "seed": seed,
        "steps": steps,
        "baseline_sha256": sha(baseline),
        "candidate_sha256": sha(candidate),
        "training_sources": source_ids,
        "changed_parameter_groups": sorted({k.split(".")[0] for k in changed}),
        "training_scope": scope,
        "private_adapter_trainable_names": (
            trainable_names if private_scope else []
        ),
        "frozen_shared_backbone_verified": private_scope,
        "terminal_heads_trained": False,
        "old_actor_trained": False,
        "losses": losses,
        "wall_seconds": time.perf_counter() - started,
        "scope": "generated colour-card content training; no semantic or NDU gain claim",
    }
    report["training_identity"] = hashlib.sha256(
        json.dumps(report, sort_keys=True).encode()
    ).hexdigest()
    return baseline, candidate, report
