"""Reconstruct initial-state controls and check paired input/RNG identities.

Training did not retain separate initial-weight snapshots. Initial equality
here is a deterministic reconstruction from the sealed constructor and seed,
not a claim to have observed extra historical initialization artifacts.
"""

import hashlib
import json

import numpy as np
import torch

from experiments.continuous_spiking_network.models import SequenceClassifier

from audit_training_checks import require


def tensor_mapping_digest(values):
    digest = hashlib.sha256()
    for name, value in sorted(values.items()):
        array = value.detach().cpu().contiguous().numpy()
        digest.update(json.dumps([name, array.dtype.str, list(array.shape)]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def input_digest(bundle):
    digest = hashlib.sha256()
    for split_name in ("train", "val", "test"):
        split = getattr(bundle, split_name)
        for field in ("x", "dt", "y"):
            array = np.ascontiguousarray(getattr(split, field))
            digest.update(
                json.dumps(
                    [split_name, field, array.dtype.str, list(array.shape)]
                ).encode()
            )
            digest.update(memoryview(array).cast("B"))
    return digest.hexdigest()


def initial_identity(config, cache):
    key = json.dumps(config, sort_keys=True)
    if key not in cache:
        rows = []
        for _ in range(2):
            torch.manual_seed(config["seed"])
            model = SequenceClassifier(**config)
            rows.append(
                {
                    "whole_state_sha256": tensor_mapping_digest(model.state_dict()),
                    "frontend_sha256": tensor_mapping_digest(
                        model.frontend.state_dict()
                    ),
                    "readout_sha256": tensor_mapping_digest(model.readout.state_dict()),
                }
            )
        require(rows[0] == rows[1], "two reconstructed LR initial states differ")
        cache[key] = {
            **rows[0],
            "two_reconstructed_initial_states_equal": True,
            "scope": "sealed model constructor/config/seed reconstruction; initial tensors were not separately checkpointed during training",
        }
    return cache[key]


def paired_identity(spec, config, data_sha, source_sha, bundle, batches, cache):
    initialized = initial_identity(config, cache.setdefault("initial_states", {}))
    rebuilt_sha = input_digest(bundle)
    data_key = json.dumps(
        {
            key: spec[key]
            for key in (
                "task",
                "train_size",
                "val_size",
                "test_size",
                "length",
                "data_seed",
            )
        },
        sort_keys=True,
    )
    data_groups = cache.setdefault("data_groups", {})
    if data_key not in data_groups:
        data_groups[data_key] = {
            "dataset": json.loads(data_key),
            "data_manifest_sha256": data_sha,
            "retained_source_manifest_sha256": source_sha,
            "reconstructed_inputs_sha256": rebuilt_sha,
            "job_ids": [],
        }
    require(
        data_groups[data_key]["data_manifest_sha256"] == data_sha,
        "same-data manifest differs across architectures/seeds",
    )
    require(
        data_groups[data_key]["retained_source_manifest_sha256"] == source_sha,
        "retained source manifest differs across architectures/seeds",
    )
    require(
        data_groups[data_key]["reconstructed_inputs_sha256"] == rebuilt_sha,
        "reconstructed input tensors differ across architectures/seeds",
    )
    data_groups[data_key]["job_ids"].append(spec["id"])
    key = json.dumps(
        [spec["stage"], spec.get("configuration", spec["task"]), spec["seed"]]
    )
    shared = cache.setdefault("paired_groups", {})
    common = min(len(values) for values in batches)
    require(
        np.array_equal(batches[0][:common], batches[1][:common]),
        "retained two-LR minibatch prefixes differ",
    )
    if key not in shared:
        shared[key] = {
            "stage": spec["stage"],
            "group": spec.get("configuration", spec["task"]),
            "seed": spec["seed"],
            "data_manifest_sha256": data_sha,
            "frontend_sha256": initialized["frontend_sha256"],
            "readout_sha256": initialized["readout_sha256"],
            "job_ids": [],
            "prefix": batches[0][:common].copy(),
        }
    group = shared[key]
    require(
        (
            group["data_manifest_sha256"],
            group["frontend_sha256"],
            group["readout_sha256"],
        )
        == (data_sha, initialized["frontend_sha256"], initialized["readout_sha256"]),
        "paired data/frontend/readout identity differs",
    )
    common = min(common, len(group["prefix"]))
    require(
        np.array_equal(group["prefix"][:common], batches[0][:common]),
        "paired architectures' actual minibatch prefixes differ",
    )
    group["prefix"] = group["prefix"][:common].copy()
    group["job_ids"].append(spec["id"])
    return {
        **initialized,
        "data_manifest_sha256": data_sha,
        "retained_source_manifest_sha256": source_sha,
        "reconstructed_inputs_sha256": rebuilt_sha,
        "two_lr_common_updates": min(len(values) for values in batches),
        "two_lr_retained_prefix_exact": True,
    }


def identity_summary(cache):
    groups = []
    for group in cache.get("paired_groups", {}).values():
        prefix = group["prefix"]
        groups.append(
            {
                **{key: value for key, value in group.items() if key != "prefix"},
                "common_prefix_updates": len(prefix),
                "common_prefix_shape": list(prefix.shape),
                "common_prefix_sha256": hashlib.sha256(prefix.tobytes()).hexdigest(),
                "retained_paired_prefix_exact": True,
            }
        )
    return {
        "data_groups": list(cache.get("data_groups", {}).values()),
        "paired_groups": groups,
        "unique_reconstructed_initial_configs": len(cache.get("initial_states", {})),
        "initialization_scope": "same-LR initial equality and common frontend/head are reconstructed under the sealed initialization code; retained minibatch/source identity equality is checked directly from artifacts",
        "input_scope": "full x/dt/y hashes describe reconstructed tensors from the frozen data generator, source cache and seed; training did not separately retain full runtime input snapshots",
    }
