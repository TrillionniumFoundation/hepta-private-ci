"""Explicit admission of the two frozen matched-information adapters for E4.

The original pool constructor still admits only its original research schema.
Training-source custody and current execution-source custody remain separate.
"""

import copy
import importlib
import json
import math
from pathlib import Path
import time

from .. import causal_probe_v3 as probe, data, matched_info_sft_v4 as matched
from ..coding_sft import file_hash
from .onpolicy_contract import require
from .shared_pool_v4 import SharedAdapterPool, verified_entries

MODELS = {
    "F": (
        "final_only",
        "46c1a35887fc0639050210a19ec2a3a421e1bdb3d5e58cff394a1e54879f29f2",
    ),
    "T": (
        "all_actions",
        "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786",
    ),
}
RUNTIME_MODULES = (
    "matched_info_sft_v4",
    "causal_probe_v3",
    "causal_train_v3",
    "causal_training_contract_v3",
    "chat_protocol",
    "data",
    "coding_sft",
)


def runtime_sources(manifest):
    """Pin the actual shared numerical and prompt code to its training version."""
    actual = {}
    for name in RUNTIME_MODULES:
        module = importlib.import_module("cell_experiments." + name)
        key = "scripts/cell_experiments/" + name + ".py"
        actual[key] = file_hash(module.__file__)
        require(
            actual[key] == manifest["source_inventory"].get(key),
            "actual matched inference dependency differs: " + name,
        )
    return actual


def saved_parameter_count(directory):
    """Count the hash-admitted saved FP32 LoRA tensor shapes without loading a base."""
    with (directory / "adapter_model.safetensors").open("rb") as stream:
        size = int.from_bytes(stream.read(8), "little")
        require(0 < size <= 65_536, "bounded adapter tensor header required")
        header = json.loads(stream.read(size))
    tensors = {key: value for key, value in header.items() if key != "__metadata__"}
    require(bool(tensors), "saved adapter tensor shapes absent")
    for name, tensor in tensors.items():
        require(
            (".lora_A." in name or ".lora_B." in name)
            and tensor["dtype"] == "F32"
            and len(tensor["shape"]) == 2
            and all(type(value) is int and value > 0 for value in tensor["shape"]),
            "saved matched adapter must contain only FP32 LoRA matrices",
        )
    return sum(math.prod(tensor["shape"]) for tensor in tensors.values())


def admit_matched(manifests, original_manifests, artifact_root, training_source):
    """Verify original C and both preselected E1 artifacts before loading tensors."""
    require(
        set(manifests) == set(original_manifests) == {"F", "T", "C"},
        "fixed F/T/C required",
    )
    require(manifests["C"] == original_manifests["C"], "secondary C changed")
    root, training_source = Path(artifact_root), Path(training_source)
    entries, base = verified_entries(original_manifests, root)
    receipts = {}
    for cell, (objective, expected_identity) in MODELS.items():
        manifest = manifests[cell]
        identity = matched.verify_manifest(manifest, root, training_source)
        require(
            identity == expected_identity
            and manifest["objective"] == objective
            and manifest["base_manifest"] == base,
            "preselected matched Cell identity/objective/base differs",
        )
        dependencies = runtime_sources(manifest)
        directory = probe._base(root, manifest["adapter_directory"])
        path = directory.parent / "TRAINING.json"
        require(
            path.is_file() and not path.is_symlink(),
            "original matched training receipt required",
        )
        receipt = probe._json(path)
        require(
            receipt.get("status") == "COMPLETE"
            and receipt.get("model_digest") == identity
            and receipt.get("objective") == objective
            and receipt.get("steps") == matched.SETTINGS["steps"]
            and all(
                receipt.get(key) == manifest[key]
                for key in (
                    "parameter_before",
                    "parameter_after",
                    "train_records_digest",
                    "encoded_groups_digest",
                )
            ),
            "completed matched training receipt differs",
        )
        entries[cell] = {
            "manifest": copy.deepcopy(manifest),
            "model_digest": identity,
            "adapter_label": entries[cell]["adapter_label"],
            "training": {
                "path": path.relative_to(root).as_posix(),
                "sha256": file_hash(path),
                "bytes": path.stat().st_size,
                "parameter_after": manifest["parameter_after"],
                "trainable_parameters": saved_parameter_count(directory),
                "parameter_count_source": "hash-admitted saved FP32 tensor shapes; checked again against actual loaded tensors",
                "original_source_inventory_digest": data.digest(
                    manifest["source_inventory"]
                ),
                "actual_runtime_sources": dependencies,
                "admission_source_sha256": file_hash(__file__),
                "scope": "same-input same-fixed-compute F/T; C remains an unmatched secondary control",
            },
        }
        receipts[cell] = receipt
    for key in (
        "freeze_digest",
        "train_records_digest",
        "encoded_groups_digest",
        "parameter_before",
        "training_settings",
        "source_inventory",
    ):
        require(
            manifests["F"][key] == manifests["T"][key],
            "F/T training inputs or configuration differ: " + key,
        )
    for key in (
        "model_forwards",
        "model_backwards",
        "head_positions",
        "input_tokens",
        "padded_positions",
    ):
        require(
            receipts["F"]["cost"][key] == receipts["T"]["cost"][key],
            "F/T fixed compute differs: " + key,
        )
    require(
        len({entry["model_digest"] for entry in entries.values()}) == 3,
        "three distinct candidate identities required",
    )
    return entries, base


class MatchedAdapterPool(SharedAdapterPool):
    """Use unchanged loading, activation, FP32 checks and receipts after admission."""

    def __init__(self, manifests, original_manifests, artifact_root, training_source):
        started, cpu = time.perf_counter(), time.process_time()
        root = Path(artifact_root)
        entries, base = admit_matched(
            manifests, original_manifests, root, training_source
        )
        self._initialize(entries, base, root, started, cpu)
