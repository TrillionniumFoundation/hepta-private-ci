"""Independent physical-source splits for the finite RGB/instruction task.

All instructions and sensor variants of a physical source stay together. This
module never reuses an r1 checkpoint or opens its data. Test construction is an
explicit evaluator-only action after the enclosing protocol has been frozen.
"""

import hashlib
import json

import numpy as np

from data import CLASSES, SIDE, attributes, render


SCHEMA = "hepta.joint-generation.independent-data.v1"
SPLITS = ("train", "validation", "test")


def default_profile():
    return {
        "schema": SCHEMA,
        "seeds": {"train": 130101, "validation": 130202, "test": 130303},
        "sources_per_class": {"train": 16, "validation": 6, "test": 6},
        "instructions_per_source": 8,
        "variants": 2,
        "vertical_shifts": [-1, 0, 1],
        "foreground_range": [0.75, 1.0],
        "background_range": [0.0, 0.04],
        "noise_range": [0.03, 0.12],
    }


def _json_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_profile(profile):
    expected = set(default_profile())
    if not isinstance(profile, dict) or set(profile) != expected or profile["schema"] != SCHEMA:
        raise ValueError("unsupported or incomplete independent data profile")
    for key in ("seeds", "sources_per_class"):
        values = profile[key]
        if not isinstance(values, dict) or set(values) != set(SPLITS):
            raise ValueError("all independent splits must be declared")
        upper = 2**32 - 1 if key == "seeds" else 256
        if any(type(value) is not int or not 1 <= value <= upper for value in values.values()):
            raise ValueError("invalid split seed or source count")
    if len(set(profile["seeds"].values())) != len(SPLITS):
        raise ValueError("independent splits require different source seeds")
    for key, upper in (("instructions_per_source", 36), ("variants", 64)):
        if type(profile[key]) is not int or not 1 <= profile[key] <= upper:
            raise ValueError("independent task multiplicity exceeds bounds")
    if any(CLASSES * value * profile["instructions_per_source"] * profile["variants"] > 65536
           for value in profile["sources_per_class"].values()):
        raise ValueError("independent split exceeds bounded model batch profile")
    shifts = profile["vertical_shifts"]
    if (not isinstance(shifts, list) or not shifts or len(shifts) > 3
            or any(type(value) is not int or value not in (-1, 0, 1) for value in shifts)
            or len(set(shifts)) != len(shifts)):
        raise ValueError("invalid physical vertical shifts")
    for key in ("foreground_range", "background_range", "noise_range"):
        interval = profile[key]
        if (not isinstance(interval, list) or len(interval) != 2
                or any(type(value) not in (int, float) for value in interval)
                or not np.isfinite(interval).all() or not 0 <= interval[0] < interval[1] <= 1):
            raise ValueError("invalid physical-source range")


def dataset(split, profile, *, allow_test=False):
    """Construct one declared split, never silently authorizing held-out use.

    ``allow_test`` is an accidental-use guard, not an access-control authority.
    The evaluator must first acquire its exclusive experiment-wide opening marker.
    Merely importing this module or validating a profile constructs no split.
    """
    if split not in SPLITS or type(allow_test) is not bool:
        raise ValueError("invalid independent split request")
    if split == "test" and not allow_test:
        raise ValueError("independent test split sealed; evaluator opening required")
    _validate_profile(profile)
    count = profile["sources_per_class"][split]
    seed = profile["seeds"][split]
    full, low, labels, groups, hashes, source_ids, scenes, commands = ([] for _ in range(8))
    sources = {}
    for scene in range(CLASSES):
        source_color, source_shape, source_position = attributes(scene)
        for index in range(count):
            # Separate RNG streams keep physical images independent of the number
            # of instructions/variants and their iteration order.
            source_rng = np.random.default_rng(np.random.SeedSequence([seed, scene, index, 0]))
            instruction_rng = np.random.default_rng(np.random.SeedSequence([seed, scene, index, 1]))
            noise_rng = np.random.default_rng(np.random.SeedSequence([seed, scene, index, 2]))
            shift = int(source_rng.choice(profile["vertical_shifts"]))
            brightness = float(source_rng.uniform(*profile["foreground_range"]))
            background = source_rng.uniform(*profile["background_range"], size=3)
            clean = np.clip(background + brightness * np.roll(render(scene), shift, axis=0), 0, 1)
            source_hash = hashlib.sha256(clean.astype("<f8").tobytes()).hexdigest()
            source_id = "physical-v2:" + source_hash
            if source_id in sources:
                raise ValueError("duplicate physical source in declared split")
            sources[source_id] = {
                "scene": scene, "index": index, "vertical_shift": shift,
                "brightness": brightness, "background": background.tolist(),
                "image_sha256": source_hash,
            }
            chosen = instruction_rng.choice(36, size=profile["instructions_per_source"], replace=False)
            for choice in chosen:
                color, shape, position = (int(value) for value in np.unravel_index(choice, (4, 3, 3)))
                target = ((source_color if color == 0 else color - 1) * 2
                          + (source_shape if shape == 0 else shape - 1)) * 2
                target += source_position if position == 0 else position - 1
                instruction = np.concatenate((np.eye(4)[color], np.eye(3)[shape], np.eye(3)[position]))
                for _ in range(profile["variants"]):
                    noise = noise_rng.uniform(*profile["noise_range"])
                    observed = np.clip(clean + noise_rng.normal(0, noise, (SIDE, SIDE, 3)), 0, 1)
                    thumbnail = observed.reshape(4, 2, 4, 2, 3).mean(axis=(1, 3))
                    thumbnail = thumbnail.repeat(2, axis=0).repeat(2, axis=1)
                    full.append(np.concatenate((observed.reshape(-1), instruction)))
                    low.append(np.concatenate((thumbnail.reshape(-1), instruction)))
                    labels.append(target)
                    # Bootstrap and leakage checks group the physical source,
                    # rather than treating its instructions as independent units.
                    groups.append(source_id)
                    source_ids.append(source_id)
                    scenes.append(scene)
                    commands.append((color, shape, position))
                    hashes.append(hashlib.sha256(full[-1].astype("<f8").tobytes()).hexdigest())
    return {
        "low": np.asarray(low), "full": np.asarray(full), "labels": np.asarray(labels),
        "groups": groups, "input_hashes": hashes, "source_ids": source_ids,
        "source_scenes": np.asarray(scenes), "commands": np.asarray(commands),
        "sources": sources, "split": split, "profile_sha256": _json_hash(profile),
    }


def manifest(data):
    """Bind physical sources, group assignment and every observed input byte."""
    unique = sorted(set(data["source_ids"]))
    return {
        "schema": SCHEMA, "split": data["split"], "rows": len(data["labels"]),
        "source_count": len(unique), "group_count": len(set(data["groups"])),
        "sources_sha256": _json_hash({key: data["sources"][key] for key in unique}),
        "source_ids_sha256": _json_hash(unique),
        "groups_sha256": _json_hash(data["groups"]),
        "inputs_sha256": hashlib.sha256("".join(data["input_hashes"]).encode()).hexdigest(),
        "profile_sha256": data["profile_sha256"],
    }
