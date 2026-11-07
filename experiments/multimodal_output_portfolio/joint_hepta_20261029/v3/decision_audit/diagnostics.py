"""Six real VLM interventions; fresh model per call, no semantic acceptance.

Three actual pixel inputs by two neutral instructions separate input binding
from copying the common plan. Spies observe the existing describe() path and
never replace its neural output. Costs include tracing and fresh model loads.
"""

import argparse
import gc
import hashlib
import json
from pathlib import Path
import re
import resource
import sys
import time

from .acquire_models import digest_file
from .local_models import LocalModels


PROMPTS = {
    "caption": "Describe the visible content in one short sentence. Do not refer to previous text.",
    "object": "What is the main animal or object visible? Answer in at most five words.",
}


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _tensor(value):
    import torch
    value = value.detach().cpu().contiguous()
    result = {"shape": list(value.shape), "dtype": str(value.dtype),
              "sha256": hashlib.sha256(value.view(torch.uint8).numpy().tobytes()).hexdigest()}
    if value.is_floating_point():
        result["finite"] = bool(torch.isfinite(value).all())
    return result


def _peak_rss_bytes():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)


def execute(models, original, generated, output, source_sha, threads=2, max_tokens=80):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not 1 <= max_tokens <= 256:
        raise ValueError("Immutable source identity and bounded token limit required")
    from PIL import Image
    root, output = Path(models), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time(), time.perf_counter()
    blank = output / "blank-white.png"
    Image.new("RGB", (512, 512), "white").save(blank)
    images = {"original": Path(original), "generated": Path(generated), "blank": blank}
    order = [(name, prompt) for prompt, names in (("caption", images), ("object", reversed(images)))
             for name in names]
    plan = {"schema": "hepta.vlm-input-intervention.v1", "source_sha": source_sha,
            "order": order, "prompts": PROMPTS, "max_new_tokens": max_tokens, "threads": threads,
            "fresh_model_per_case": True, "reuse_generated_image_without_new_diffusion": True,
            "images": {name: {"source_path": str(path), "sha256": digest_file(path)}
                       for name, path in images.items()},
            "runtime_sources": {name: digest_file(Path(__file__).with_name(name))
                                for name in ("diagnostics.py", "local_models.py", "acquire_models.py")},
            "semantic_acceptance": "not_inferred", "training_performed": False}
    _write(output / "PLAN.json", plan)
    rows, cancelled = [], False
    for index, (name, prompt_key) in enumerate(order):
        case = output / f"{index:02d}-{name}-{prompt_key}"
        case.mkdir()
        row = {"index": index, "image": name, "instruction": prompt_key,
               "image_sha256": plan["images"][name]["sha256"], "prompt": PROMPTS[prompt_key],
               "status": "not_started", "model_generate_calls": 0, "vision_outputs": []}
        before = time.process_time(), time.perf_counter()
        backend = template_method = generate_method = hook = None
        try:
            if cancelled:
                row["status"] = "not_run_after_cancellation"
                continue
            row["status"] = "started"; _write(case / "TRACE.json", row)
            backend = LocalModels(root / "vlm", root / "sd", threads)
            backend._activate("vlm")
            template_method = backend.processor.apply_chat_template
            generate_method = backend.model.generate

            def template_spy(*args, **kwargs):
                rendered = template_method(*args, **kwargs)
                row["rendered_prompt"] = rendered
                row["rendered_prompt_sha256"] = hashlib.sha256(rendered.encode()).hexdigest()
                return rendered

            def generation_spy(**kwargs):
                import torch
                row["model_generate_calls"] += 1
                row["inputs"] = {key: _tensor(value) for key, value in kwargs.items() if torch.is_tensor(value)}
                row["input_token_ids"] = kwargs["input_ids"][0].tolist()
                row["input_tokens"] = len(row["input_token_ids"])
                result = generate_method(**kwargs)
                new = result[0, row["input_tokens"]:].tolist()
                eos = backend.model.generation_config.eos_token_id
                eos = eos if isinstance(eos, list) else [eos]
                hit_eos, hit_limit = bool(new and new[-1] in eos), len(new) >= kwargs["max_new_tokens"]
                row.update(output_token_ids=new, output_tokens=len(new), eos_token_ids=eos,
                           last_token_is_eos=hit_eos, hit_max_new_tokens=hit_limit,
                           stop_reason="eos_and_length" if hit_eos and hit_limit else
                           "eos" if hit_eos else "max_new_tokens" if hit_limit else "other")
                return result

            vision = getattr(getattr(backend.model, "model", None), "vision_model", None)
            if vision is not None:
                def vision_spy(module, args, result):
                    hidden = getattr(result, "last_hidden_state", None)
                    if hidden is not None:
                        row["vision_outputs"].append(_tensor(hidden))
                hook = vision.register_forward_hook(vision_spy)
            backend.processor.apply_chat_template = template_spy
            backend.model.generate = generation_spy
            text = backend.describe(images[name], PROMPTS[prompt_key], max_tokens=max_tokens)
            (case / "output.txt").write_text(text)
            row.update(status="completed", output=text, output_sha256=digest_file(case / "output.txt"),
                       backend=backend.identity())
        except (Exception, KeyboardInterrupt) as error:
            cancelled = isinstance(error, KeyboardInterrupt)
            row.update(status="cancelled" if cancelled else "failed",
                       error={"type": type(error).__name__, "message": str(error)})
        finally:
            if hook is not None:
                hook.remove()
            if backend is not None and template_method is not None:
                backend.processor.apply_chat_template = template_method
            if backend is not None and generate_method is not None:
                backend.model.generate = generate_method
            row["cpu_seconds"] = time.process_time() - before[0]
            row["wall_seconds"] = time.perf_counter() - before[1]
            row["cumulative_process_peak_rss_bytes"] = _peak_rss_bytes()
            _write(case / "TRACE.json", row); rows.append(row)
            backend = template_method = generate_method = hook = vision = None
            gc.collect()
    completed = [row for row in rows if row["status"] == "completed"]
    comparisons = {
        "distinct_pixel_inputs": len({r["inputs"]["pixel_values"]["sha256"] for r in completed}),
        "distinct_token_inputs": len({r["inputs"]["input_ids"]["sha256"] for r in completed}),
        "distinct_outputs": len({r["output_sha256"] for r in completed}),
        "distinct_vision_outputs": len({v["sha256"] for r in completed for v in r["vision_outputs"]}),
        "by_instruction": {p: len({r["output_sha256"] for r in completed if r["instruction"] == p}) for p in PROMPTS},
        "by_image": {name: len({r["output_sha256"] for r in completed if r["image"] == name}) for name in images},
    }
    summary = {"source_sha": source_sha, "registered_cases": len(order), "completed_cases": len(completed),
               "actual_generate_calls": sum(r["model_generate_calls"] for r in rows),
               "comparisons": comparisons, "statuses": [r["status"] for r in rows],
               "cpu_seconds": time.process_time() - start[0], "wall_seconds": time.perf_counter() - start[1],
               "cumulative_process_peak_rss_bytes": _peak_rss_bytes(),
               "cost_scope": "inclusive_fresh_loads_tracing_cleanup_and_case_writes_before_summary_write",
               "semantic_acceptance": "not_inferred", "production_qualified": False,
               "training_performed": False}
    _write(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("models", "original", "generated", "output", "source-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=80)
    args = parser.parse_args()
    result = execute(args.models, args.original, args.generated, args.output, args.source_sha,
                     args.threads, args.max_tokens)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["completed_cases"] != 6 or result["actual_generate_calls"] != 6:
        raise SystemExit(1)
