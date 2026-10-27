"""Develop efficient flow reconstruction only on the old development clips."""
import argparse
from pathlib import Path
import time

import cv2
import numpy as np

from .common import freeze, read, save, sha, verify_frozen
from .video_engine import fit, render, score


def run(assets, output):
    source = Path(__file__).parent
    manifest = read(assets / "MANIFEST.json")
    rows = [r for r in manifest["samples"] if r["role"] in {"train", "validation"}]
    if {r["source"] for r in rows} != {"david", "dudek", "faceocc2"}:
        raise ValueError("Unexpected development sources")
    output.mkdir(parents=True, exist_ok=False)
    spec = {"training": "Only existing development train-role targets", "validation": "Only existing development validation-role targets",
        "solvers": ["dis_ultrafast", "dis_fast", "dis_medium"],
        "selection": "Lowest measured validation CPU among candidates with mean PSNR >= original flow minus 0.25 dB; ties by higher PSNR then solver name",
        "test_not_received": True}
    registration = freeze(source, assets / "MANIFEST.json", output, spec)
    cv2.setNumThreads(1)
    training = [r for r in rows if r["role"] == "train"]
    validation = [r for r in rows if r["role"] == "validation"]
    models = {solver: fit(training, solver) for solver in spec["solvers"]}
    configurations = {"original_flow": {"solver": "farneback_original", "alpha": 1.}}
    for solver, model in models.items():
        configurations[solver + "_learned"] = {"solver": solver, "alpha": model["alpha"]}
        configurations[solver + "_initial"] = {"solver": solver, "alpha": .5}
    results = []
    for i, item in enumerate(validation):
        arms = list(configurations)
        arms = arms[i % len(arms):] + arms[:i % len(arms)]
        for arm in arms:
            public = render(item, configurations[arm], output / "validation" / item["id"] / arm)
            results.append({"id": item["id"], "source": item["source"], "arm": arm, **public,
                **score(item["private_target"], public["output_path"])})
    summaries = {arm: {key: float(np.mean([r[key] for r in results if r["arm"] == arm]))
        for key in ("PSNR", "pixel_MSE", "cpu_seconds", "wall_seconds")} for arm in configurations}
    feasible = [arm for arm in configurations if summaries[arm]["PSNR"] >= summaries["original_flow"]["PSNR"] - .25]
    selected = min(feasible, key=lambda arm: (summaries[arm]["cpu_seconds"], -summaries[arm]["PSNR"], arm))
    frozen = {"selected_arm": selected, "configuration": configurations[selected], "validation_summaries": summaries,
        "models": models, "frozen_ns": time.time_ns(), "heldout_generation_not_started": True,
        "source_manifest_sha256": sha(assets / "MANIFEST.json")}
    save(output / "VALIDATION_ROWS.json", results)
    save(output / "FROZEN_MODEL.json", frozen)
    verify_frozen(registration)
    print(frozen, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.output)
