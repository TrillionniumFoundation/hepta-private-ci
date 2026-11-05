"""Independently verify the retained six-case CI archive; no model execution."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile


SOURCE = "975e1a264c14ed3da02dcee23a64327825387e42"
ARCHIVE_SHA256 = "d84b6451b4b70e2dcc25b01c72ed5553357c0a9081c96d2f8ebd5248a0cca7aa"
MODEL_REVISION = "067788b187b95ebe7b2e040b3e4299e342e5b8fd"
WEIGHT_SHA256 = "dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def verify(archive, sources):
    raw = Path(archive).read_bytes()
    require(len(raw) == 396825 and sha(raw) == ARCHIVE_SHA256, "CI archive identity differs")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.namelist()
        require(len(members) == len(set(members)), "Duplicate ZIP member")
        require(bundle.read("SOURCE_SHA.txt").decode().strip() == SOURCE, "Source identity differs")
        plan = json.loads(bundle.read("diagnostics/PLAN.json"))
        summary = json.loads(bundle.read("diagnostics/SUMMARY.json"))
        manifest_bytes = bundle.read("acquisition/vlm/MANIFEST.json")
        manifest = json.loads(manifest_bytes)
        require(plan["source_sha"] == summary["source_sha"] == SOURCE, "Plan/summary source differs")
        require(plan["fresh_model_per_case"] and plan["max_new_tokens"] == 80, "Protocol differs")
        require(not plan["training_performed"] and not summary["training_performed"], "Training claim differs")
        require(manifest["complete"] and manifest["revision"] == MODEL_REVISION, "Model pin differs")
        weight = next(row for row in manifest["files"] if row["path"] == "model.safetensors")
        require(weight["sha256"] == WEIGHT_SHA256 and weight["size"] == 1025998224, "Weight pin differs")
        for name, expected in plan["runtime_sources"].items():
            require(sha((Path(sources) / name).read_bytes()) == expected, "Runtime source bytes differ: " + name)
        image_paths = {"original": "input.png", "generated": "direct.png", "blank": "diagnostics/blank-white.png"}
        for name, path in image_paths.items():
            require(sha(bundle.read(path)) == plan["images"][name]["sha256"], "Raw image bytes differ: " + name)
        trace_paths = sorted(name for name in members if name.startswith("diagnostics/") and name.endswith("/TRACE.json"))
        rows = [json.loads(bundle.read(name)) for name in trace_paths]
        expected_cells = {(image, prompt) for image in image_paths for prompt in plan["prompts"]}
        require(len(rows) == 6 and {(r["image"], r["instruction"]) for r in rows} == expected_cells, "Case census differs")
        require([[r["image"], r["instruction"]] for r in rows] == plan["order"], "Execution order differs")
        versions = rows[0]["backend"]["versions"]
        for index, (path, row) in enumerate(zip(trace_paths, rows)):
            require(row["index"] == index and row["status"] == "completed", "Incomplete case")
            require(row["model_generate_calls"] == 1, "Generate call census differs")
            require(row["image_sha256"] == plan["images"][row["image"]]["sha256"], "Case raw image differs")
            require(row["prompt"] == plan["prompts"][row["instruction"]], "Case instruction differs")
            text = bundle.read(path.replace("TRACE.json", "output.txt"))
            require(text.decode() == row["output"] and sha(text) == row["output_sha256"], "Output byte identity differs")
            require(sha(row["rendered_prompt"].encode()) == row["rendered_prompt_sha256"], "Template hash differs")
            require(row["prompt"] in row["rendered_prompt"] and row["rendered_prompt"].count("<image>") == 1, "Template binding differs")
            tokens = row["input_token_ids"]
            encoded = struct.pack("<" + "q" * len(tokens), *tokens)
            require(len(tokens) == row["input_tokens"] == 91, "Input token length differs")
            require(sha(encoded) == row["inputs"]["input_ids"]["sha256"], "Recorded input int64 token hash differs")
            require(row["inputs"]["input_ids"]["shape"] == [1, len(tokens)], "Token shape differs")
            require(row["inputs"]["pixel_values"]["shape"] == [1, 1, 3, 512, 512], "Pixel shape differs")
            require(row["inputs"]["pixel_values"]["finite"], "Nonfinite pixel trace")
            require(len(row["vision_outputs"]) == 1, "Vision forward census differs")
            vision = row["vision_outputs"][0]
            require(vision["shape"] == [1, 1024, 768] and vision["finite"], "Vision trace differs")
            output_tokens = row["output_token_ids"]
            eos = bool(output_tokens and output_tokens[-1] in row["eos_token_ids"])
            limit = len(output_tokens) >= plan["max_new_tokens"]
            require(len(output_tokens) == row["output_tokens"] and eos and not limit, "Stopping rule differs")
            require(row["last_token_is_eos"] == eos and row["hit_max_new_tokens"] == limit and row["stop_reason"] == "eos", "Stop trace differs")
            actual_model = row["backend"]["models"]["vlm"]
            require(actual_model == {"model": manifest["model"], "revision": manifest["revision"],
                                     "files": manifest["files"], "manifest_sha256": sha(manifest_bytes)}, "Backend model identity differs")
            require(row["backend"]["versions"] == versions and row["backend"]["threads"] == 2, "Backend environment differs")
            require([load["model"] for load in row["backend"]["loads"]] == ["vlm"], "Fresh load census differs")
            require(all(math.isfinite(row[key]) and row[key] > 0 for key in ("cpu_seconds", "wall_seconds")), "Invalid measured cost")
        comparisons = {
            "distinct_pixel_inputs": len({r["inputs"]["pixel_values"]["sha256"] for r in rows}),
            "distinct_token_inputs": len({r["inputs"]["input_ids"]["sha256"] for r in rows}),
            "distinct_outputs": len({r["output_sha256"] for r in rows}),
            "distinct_vision_outputs": len({r["vision_outputs"][0]["sha256"] for r in rows}),
            "by_instruction": {p: len({r["output_sha256"] for r in rows if r["instruction"] == p}) for p in plan["prompts"]},
            "by_image": {name: len({r["output_sha256"] for r in rows if r["image"] == name}) for name in image_paths},
        }
        require(comparisons == summary["comparisons"], "Summary distinct-count arithmetic differs")
        for name in image_paths:
            pair = [r for r in rows if r["image"] == name]
            require(len({r["inputs"]["pixel_values"]["sha256"] for r in pair}) == 1, "Same-image preprocessing differs by prompt")
            require(len({r["vision_outputs"][0]["sha256"] for r in pair}) == 1, "Same-image vision output differs by prompt")
        for prompt in plan["prompts"]:
            group = [r for r in rows if r["instruction"] == prompt]
            require(len({r["inputs"]["input_ids"]["sha256"] for r in group}) == 1, "Same-prompt tokens differ by image")
            require(len({r["rendered_prompt_sha256"] for r in group}) == 1, "Same-prompt template differs by image")
        require(summary["actual_generate_calls"] == sum(r["model_generate_calls"] for r in rows) == 6, "Summary generate census differs")
        require(summary["completed_cases"] == summary["registered_cases"] == 6, "Summary completion census differs")
        require(summary["statuses"] == [r["status"] for r in rows], "Summary status census differs")
        costs = {key: {"inclusive": summary[key], "case_sum": math.fsum(r[key] for r in rows)}
                 for key in ("cpu_seconds", "wall_seconds")}
        require(all(c["inclusive"] >= c["case_sum"] for c in costs.values()), "Inclusive cost below measured case sum")
        require(summary["cumulative_process_peak_rss_bytes"] == max(r["cumulative_process_peak_rss_bytes"] for r in rows), "Peak RSS differs")
        selected = ("image", "instruction", "output", "input_tokens", "output_tokens", "stop_reason",
                    "cpu_seconds", "wall_seconds")
        return {
            "schema": "hepta.ndu.input-diagnostic-byte-review.v1", "verification_passed": True,
            "run_id": 41973374316, "artifact_id": 13393254163, "source_sha": SOURCE,
            "archive": {"bytes": len(raw), "sha256": sha(raw), "members": len(members)},
            "runtime_sources": plan["runtime_sources"], "model_revision": MODEL_REVISION,
            "model_weight_sha256": WEIGHT_SHA256, "model_manifest_sha256": sha(manifest_bytes),
            "versions": versions, "comparisons": comparisons,
            "same_image_same_pixel_and_vision_hashes": True, "same_instruction_same_template_and_token_hashes": True,
            "actual_generate_calls": 6, "eos_stops": 6, "token_limit_stops": 0,
            "cases": [{key: row[key] for key in selected} for row in rows], "costs": costs,
            "peak_rss_bytes": summary["cumulative_process_peak_rss_bytes"],
            "raw_input_hashes": {name: plan["images"][name]["sha256"] for name in image_paths},
            "tensor_scope": "pixel and vision hashes are runtime traces; raw tensor arrays are not archived or recomputed here",
            "weights_scope": "manifest and source verification are checked; this review does not reload neural weights",
            "semantic_acceptance": False, "old_constant_output_root_cause_resolved": False,
            "new_diffusion_execution": False, "new_training": False, "production_qualified": False,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(__file__).with_name("raw-ci.zip"))
    parser.add_argument("--source-directory", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.archive, args.source_directory)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"verification_passed": result["verification_passed"], "comparisons": result["comparisons"]}))
