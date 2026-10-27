"""One frozen DAVIS qualification of real frame quality and execution cost."""
import argparse
from pathlib import Path
import time

import cv2

from .common import freeze, read, save, sha, summarize_quality, verify_frozen
from .video_engine import render, score


def run(assets, model_path, old_model_path, output):
    source = Path(__file__).parent
    spec = read(source / "VIDEO_PROTOCOL.json")
    manifest, model, old = read(assets / "MANIFEST.json"), read(model_path), read(old_model_path)
    if manifest["protocol_sha256"] != sha(source / "VIDEO_PROTOCOL.json"):
        raise ValueError("Source protocol changed before qualification")
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Video source changed")
    output.mkdir(parents=True, exist_ok=False)
    configuration = model["configuration"]
    if configuration["solver"] == "farneback_original":
        raise ValueError("Efficient deployment was not selected on development")
    configurations = {"fixed_blend": {"solver": "blend", "alpha": 0.},
        "old_pure_flow": {"solver": "farneback_original", "alpha": 1.},
        "old_learned_mixer": {"solver": "farneback_original", "weights": old["weights"]},
        "efficient_initial": {"solver": configuration["solver"], "alpha": .5},
        "efficient_learned": configuration}
    registration = freeze(source, assets / "MANIFEST.json", output, spec,
        {"frozen_model_sha256": sha(model_path), "original_model_sha256": sha(old_model_path),
        "configurations": configurations, "opencv_version": cv2.__version__})
    save(output / "FROZEN_MODEL.json", model)
    save(output / "ORIGINAL_MODEL.json", old)
    cv2.setNumThreads(1)
    rows, batches = [], []
    for repetition in range(spec["timing_repetitions"]):
        for index, item in enumerate(manifest["samples"]):
            arms = spec["comparison_arms"]
            rotation = (index + repetition) % len(arms)
            for arm in arms[rotation:] + arms[:rotation]:
                public = render({key: item[key] for key in ("left", "right")}, configurations[arm],
                    output / "test" / f"repeat-{repetition}" / item["id"] / arm)
                rows.append({"id": item["id"], "source": item["source"], "arm": arm, "repetition": repetition,
                    **public, **score(item["private_target"], public["output_path"]), "scored_ns": time.time_ns()})
            if (index + 1) % spec["frames_per_source"] == 0:
                print({"video_repetition": repetition, "completed": index + 1}, flush=True)
    quality_keys = ["PSNR", "pixel_MSE", "cpu_seconds", "wall_seconds"]
    result = summarize_quality(rows, spec["comparison_arms"], quality_keys, "source",
        [("efficient_learned", arm) for arm in spec["comparison_arms"] if arm != "efficient_learned"])
    cost = result["comparisons"]["efficient_learned__minus__old_learned_mixer"]
    attribution = result["comparisons"]["efficient_learned__minus__efficient_initial"]
    result.update(schema="hepta.ndu.closure-v2.natural.video.result.v1", status="completed",
        quality_cost_gate_passed=bool(cost["PSNR"]["CI95"][0] >= -.25 and cost["cpu_seconds"]["CI95"][1] < 0
            and cost["wall_seconds"]["CI95"][1] < 0),
        training_attribution_gate_passed=bool(attribution["PSNR"]["CI95"][0] > 0),
        adaptive_allocation_superiority_established=False, semantic_video_synthesis=False,
        source_preparation_wall_seconds=manifest["source_preparation_wall_seconds"],
        actual_output_records=len(rows), independent_test_sources=len(manifest["clips"]))
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    verify_frozen(registration)
    print(result, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--old-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.model, args.old_model, args.output)
