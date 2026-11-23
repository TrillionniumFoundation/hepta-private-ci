"""Verify shared tensors and the fitted objectives after loading the saved heads."""

import argparse
import json

from pathlib import Path

import torch
from safetensors.torch import load_file
from cell_experiments import coding_sft
from compare_heads import REGULARIZATION, load_case, make_features, verify_source


def check(case_dir, parquet, output):
    torch.set_num_threads(1)
    case = load_case(case_dir)
    prompt, answer, _ = case.read_source(parquet)
    material, parent = verify_source(case_dir)
    source = load_file(
        material / parent["runtime"]["base_directory"] / "model.safetensors"
    )
    fits = json.loads((output / "fits.json").read_bytes())
    predictor = coding_sft.load_predictor(parent, material)
    try:
        x, y, base = make_features(predictor, [(prompt, answer), (case.OLD_TRAIN, "0")])
    finally:
        predictor.close()
    results = {}
    for arm in ("direct", "bp"):
        manifest = json.loads((output / (arm + ".json")).read_bytes())
        coding_sft.verify_model(manifest, output)
        tensors = load_file(output / arm / "model.safetensors")
        if tensors.keys() - {"lm_head.weight"} != source.keys() or not all(
            torch.equal(tensors[k], v) for k, v in source.items()
        ):
            raise ValueError("Frozen backbone changed")
        loaded = coding_sft.load_predictor(manifest, output)
        try:
            weight = loaded.model.lm_head.weight.detach().double().T
            if not torch.equal(weight.T, tensors["lm_head.weight"].double()):
                raise ValueError("Loaded head differs from saved tensor")
            delta = weight - base
            observed = (
                (x @ delta - y).square().sum() + REGULARIZATION * delta.square().sum()
            ).item()
        finally:
            loaded.close()
        if abs(observed - fits["arms"][arm]["objective"]) > 1e-5 or torch.equal(
            base, weight
        ):
            raise ValueError("Objective or edited coordinates differ after reload")
        results[arm] = {
            "unchanged_tensor_count": len(source),
            "cold_loaded_objective": observed,
        }
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    check(args.case_dir, args.parquet, args.output)
