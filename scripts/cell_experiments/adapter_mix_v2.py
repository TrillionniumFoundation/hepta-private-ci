"""Exact equal-weight LoRA delta composition for a same-base engineering control."""

import json
from pathlib import Path
import time

from . import coding_sft, data


def concatenate_pairs(pairs, scales, weights, np):
    """Concatenate low-rank factors; never average A and B independently."""
    if not pairs or len(pairs) != len(scales) or len(pairs) != len(weights):
        raise ValueError("adapter mixture is incomplete")
    if not np.isclose(sum(weights), 1.0) or any(w < 0 for w in weights):
        raise ValueError("mixture weights must form a probability vector")
    inputs, outputs = pairs[0][0].shape[1], pairs[0][1].shape[0]
    for a, b in pairs:
        if a.ndim != 2 or b.ndim != 2 or a.shape[0] != b.shape[1]:
            raise ValueError("adapter factor shape mismatch")
        if a.shape[1] != inputs or b.shape[0] != outputs:
            raise ValueError("adapter base shapes differ")
    return (
        np.concatenate([a for a, _ in pairs], axis=0),
        np.concatenate(
            [b * (s * w) for (_, b), s, w in zip(pairs, scales, weights)], axis=1
        ),
    )


def mix(manifests, root, output):
    """Materialize the exact mean of compatible deltas, disclosing doubled rank."""
    import numpy as np
    from safetensors.numpy import load_file, save_file

    started, cpu = time.perf_counter(), time.process_time()
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    identities = [coding_sft.verify_model(m, root) for m in manifests]
    if len(manifests) != 2 or manifests[0]["parent"] != manifests[1]["parent"]:
        raise ValueError("exactly two candidates from the same frozen base required")
    runtime = manifests[0]["runtime"]
    immutable_runtime = lambda m: {
        k: v for k, v in m["runtime"].items() if k != "adapter_directory"
    }
    if any(immutable_runtime(m) != immutable_runtime(manifests[0]) for m in manifests):
        raise ValueError("runtime or tokenizer differs")
    configs, tensors = [], []
    for manifest in manifests:
        directory = root / manifest["runtime"]["adapter_directory"]
        cfg = json.loads((directory / "adapter_config.json").read_text())
        if any(
            cfg.get(k)
            for k in (
                "rank_pattern",
                "alpha_pattern",
                "use_rslora",
                "use_dora",
                "modules_to_save",
            )
        ):
            raise ValueError("nonuniform or extended adapters are outside this control")
        if cfg.get("bias") != "none" or cfg.get("fan_in_fan_out"):
            raise ValueError("unsupported adapter layout")
        configs.append(cfg)
        tensors.append(load_file(str(directory / "adapter_model.safetensors")))
    if set(tensors[0]) != set(tensors[1]):
        raise ValueError("adapter target modules differ")
    result, ranks = {}, set()
    for key in sorted(tensors[0]):
        if ".lora_A." not in key:
            continue
        other = key.replace(".lora_A.", ".lora_B.")
        pairs = [(t[key], t[other]) for t in tensors]
        a, b = concatenate_pairs(
            pairs, [c["lora_alpha"] / c["r"] for c in configs], [0.5, 0.5], np
        )
        result[key], result[other] = a, b
        ranks.add(a.shape[0])
    if set(result) != set(tensors[0]) or len(ranks) != 1:
        raise ValueError("unaccounted adapter tensors or ranks")
    rank = ranks.pop()
    config = {**configs[0], "r": rank, "lora_alpha": rank, "lora_dropout": 0.0}
    coding_sft.write_new(output / "adapter_config.json", config)
    save_file(
        result, str(output / "adapter_model.safetensors"), metadata={"format": "pt"}
    )
    parent_files = [
        f
        for f in manifests[0]["files"]
        if not f["path"].startswith(runtime["adapter_directory"] + "/")
    ]
    manifest = {
        "schema": coding_sft.MODEL_SCHEMA,
        "family": coding_sft.FAMILY,
        "parent": manifests[0]["parent"],
        "files": parent_files
        + coding_sft.inventory(root, [output / "adapter_model.safetensors"], "adapter")
        + coding_sft.inventory(root, [output / "adapter_config.json"], "configuration"),
        "runtime": {**runtime, "adapter_directory": str(output.relative_to(root))},
    }
    identity = coding_sft.verify_model(manifest, root)
    coding_sft.write_new(output / "manifest.json", manifest)
    receipt = {
        "schema": "hepta.same-base-delta-mixture.v2",
        "status": "COMPLETE",
        "inputs": identities,
        "weights": [0.5, 0.5],
        "output": identity,
        "method": "concatenated factors with unit final scaling",
        "rank": rank,
        "adapter_parameters": sum(v.size for v in result.values()),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "gradient_updates": 0,
        "inference_cost_matches_rank4": False,
        "external_teacher_complementarity_qualified": False,
    }
    coding_sft.write_new(output / "mixture.json", receipt)
    return manifest, receipt
