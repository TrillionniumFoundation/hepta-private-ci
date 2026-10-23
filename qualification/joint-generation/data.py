"""Controlled RGB scene transformation task and independent decoded-output observer.

The renderer produces training targets, never inference outputs. Splits separate
source-scene/instruction groups; all image and text output classes occur in train.
This closed vocabulary is deliberately not a natural-image capability claim.
"""

import hashlib
import itertools
import json

import numpy as np

COLORS = ("red", "green", "blue")
SHAPES = ("square", "cross")
POSITIONS = ("left", "right")
SIDE, CLASSES = 8, 12
SPLIT_SEEDS = {"train": 101, "validation": 202, "test": 303}


def attributes(scene):
    if not isinstance(scene, (int, np.integer)) or not 0 <= scene < CLASSES:
        raise ValueError("unknown scene")
    return scene // 4, (scene // 2) % 2, scene % 2


def caption(scene):
    color, shape, position = attributes(scene)
    return f"{COLORS[color]} {SHAPES[shape]} {POSITIONS[position]}"


def parse_caption(text):
    words = text.split()
    if len(words) != 3:
        raise ValueError("invalid generated text")
    return (COLORS.index(words[0]) * 2 + SHAPES.index(words[1])) * 2 + POSITIONS.index(words[2])


def render(scene):
    color, shape, position = attributes(scene)
    image = np.zeros((SIDE, SIDE, 3), dtype=np.float64)
    center = 2 if position == 0 else 5
    mask = np.zeros((SIDE, SIDE), dtype=bool)
    mask[2:6, center - 1:center + 2] = True
    if shape == 1:
        mask[:] = False
        mask[2:6, center] = True
        mask[3:5, center - 1:center + 2] = True
    image[mask, color] = 1.0
    return image


def templates():
    return np.stack([render(i).reshape(-1) for i in range(CLASSES)])


def _groups():
    groups = list(itertools.product(range(CLASSES), range(4), range(3), range(3)))
    order = np.random.default_rng(771).permutation(len(groups))
    return {"train": [groups[i] for i in order[:260]],
            "validation": [groups[i] for i in order[260:346]],
            "test": [groups[i] for i in order[346:]]}


def dataset(split, variants=6):
    if split not in SPLIT_SEEDS or not 1 <= variants <= 64:
        raise ValueError("invalid dataset request")
    rng = np.random.default_rng(SPLIT_SEEDS[split])
    low, full, targets, group_ids, hashes = [], [], [], [], []
    for scene, color_cmd, shape_cmd, position_cmd in _groups()[split]:
        color, shape, position = attributes(scene)
        target = ((color if color_cmd == 0 else color_cmd - 1) * 2
                  + (shape if shape_cmd == 0 else shape_cmd - 1)) * 2
        target += position if position_cmd == 0 else position_cmd - 1
        # Instruction features encode words, not the target scene.
        instruction = np.concatenate((np.eye(4)[color_cmd], np.eye(3)[shape_cmd],
                                      np.eye(3)[position_cmd]))
        group = f"{scene}:{color_cmd}:{shape_cmd}:{position_cmd}"
        for _ in range(variants):
            noise = rng.uniform(0.03, 0.25)
            observed = np.clip(render(scene) + rng.normal(0, noise, (SIDE, SIDE, 3)), 0, 1)
            thumbnail = observed.reshape(4, 2, 4, 2, 3).mean(axis=(1, 3))
            thumbnail = thumbnail.repeat(2, axis=0).repeat(2, axis=1)
            full.append(np.concatenate((observed.reshape(-1), instruction)))
            low.append(np.concatenate((thumbnail.reshape(-1), instruction)))
            targets.append(target)
            group_ids.append(group)
            hashes.append(hashlib.sha256(full[-1].astype("<f8").tobytes()).hexdigest())
    return {"low": np.asarray(low), "full": np.asarray(full),
            "labels": np.asarray(targets), "groups": group_ids, "input_hashes": hashes}


def manifest(data):
    content = {"groups": sorted(set(data["groups"])), "input_hashes": data["input_hashes"]}
    return {"rows": len(data["labels"]), "group_count": len(content["groups"]),
            "groups_sha256": hashlib.sha256(json.dumps(content["groups"]).encode()).hexdigest(),
            "inputs_sha256": hashlib.sha256("".join(content["input_hashes"]).encode()).hexdigest()}


def decoded_observations(model):
    """Observe actual generated strings and learned RGB pixels; never trust IDs."""
    text_ids = np.asarray([parse_caption(caption(i)) for i in range(CLASSES)])
    pixels = model.decode_images(np.arange(CLASSES))
    reference = templates()
    distances = np.mean((pixels[:, None, :] - reference[None, :, :]) ** 2, axis=2)
    image_ids = distances.argmin(axis=1)
    return text_ids, image_ids, pixels, distances


def outcome_table(model):
    """Frozen external task semantics applied to decoded outputs, not proposals.

    Reward includes factual correctness, successful joint delivery, contradiction
    and actual pixel reconstruction quality. Values are bounded in [-0.35, 1].
    """
    text, image, _, distances = decoded_observations(model)
    target = np.arange(CLASSES)[:, None, None]
    correct_text = text[None, :, None] == target
    correct_image = image[None, None, :] == target
    quality = np.maximum(0.0, 1.0 - 4 * distances.T[:, None, :])
    return (0.3 * correct_text + 0.3 * correct_image
            + 0.3 * (correct_text & correct_image) + 0.1 * quality
            - 0.35 * (text[:, None] != image[None, :])[None, :, :])


def decoded_metrics(model, p, q, labels):
    text, image, pixels, distances = decoded_observations(model)
    target = np.asarray(labels)
    pt = p[np.arange(len(p)), target]
    image_correct = image[None, :] == target[:, None]
    qi = np.sum(q * image_correct, axis=1)
    agreement = (text[:, None] == image[None, :]).astype(float)
    joint_success = pt * qi
    greedy_text = text[p.argmax(axis=1)]
    greedy_image = image[q.argmax(axis=1)]
    pixel_mse = np.sum(q * distances.T[target], axis=1)
    return {"joint_success": joint_success,
            "greedy_joint_success": ((greedy_text == target) & (greedy_image == target)).astype(float),
            "consistency": np.einsum("ni,ij,nj->n", p, agreement, q),
            "pixel_mse": pixel_mse}
