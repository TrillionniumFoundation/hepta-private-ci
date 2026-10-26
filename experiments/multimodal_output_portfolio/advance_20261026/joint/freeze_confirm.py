"""Freeze the actual local dependency closure before any prospective model input."""

import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_closure(entry):
    """Resolve static local imports, including imports inside function bodies."""
    root = Path(__file__).resolve().parents[4]
    pending, seen = [Path(entry).resolve()], set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        relative = path.relative_to(root).with_suffix("")
        parts = list(relative.parts)
        package = ".".join(parts[:-1] if parts[-1] != "__init__" else parts[:-1])
        modules = []
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = (importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                        if node.level else node.module or "")
                modules.extend([base, *[base + "." + item.name for item in node.names if item.name != "*"]])
        for module in modules:
            candidate = root.joinpath(*module.split("."))
            for local in (candidate.with_suffix(".py"), candidate / "__init__.py"):
                if local.is_file() and local not in seen:
                    pending.append(local)
        for parent in path.parents:
            if parent == root:
                break
            init = parent / "__init__.py"
            if init.is_file() and init not in seen:
                pending.append(init)
    return sorted(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("old_smoke", "confirmation"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--smoke-result", type=Path)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    workspace = directory.parents[4]
    raw = Path("/tmp/hepta-ndu-advance-joint")
    config, endpoints = directory / "INPUTS.json", raw / "endpoints-001/ENDPOINTS.json"
    settings = json.loads(config.read_text())
    brier = json.loads((raw / "training-001/RESULTS.json").read_text())
    nll = json.loads((raw / "nll-repair-001/RESULTS.json").read_text())
    if brier["learned_candidate_old_development_eligible"] or nll["selected_bound"] != 8 or not nll["native_seed17_old_development_eligible"]:
        raise ValueError("The prospectively selected and failed candidate identities changed")
    pins = {str(path): sha(path) for path in source_closure(directory / "confirm.py")}
    pins[str(Path(__file__).resolve())] = sha(__file__)
    for path in (config, endpoints, directory / "NLL_REPAIR_PROTOCOL_V2.json",
                 directory.parent / "REGISTRATION.json", raw / "training-001/RESULTS.json", raw / "nll-repair-001/RESULTS.json"):
        pins[str(path)] = sha(path)
    for path in (*settings["renderer_paths"].values(), settings["image_observer"], settings["event_cache"]):
        pins[str(Path(path).resolve())] = sha(path)
    cache = json.loads(Path(settings["event_cache"]).read_text())
    pins.update(cache["frozen_source_sha256"])
    for event in cache["events"]:
        pins[event["actual_wave_file"]] = event["actual_wave_file_sha256"]
    for name, expected in cache["component_manifest_sha256"].items():
        manifest = Path(settings["asr_assets"]) / ("whisper-" + name) / "manifest.json"
        if sha(manifest) != expected:
            raise ValueError("The actual observation model manifest changed")
        pins[str(manifest)] = expected
        pins.update({str(manifest.parent / row["path"]): row["sha256"] for row in json.loads(manifest.read_text())["sources"]})
    arms = [{"name": "unchanged_full_reference", "kind": "unchanged"},
            {"name": "canonical_no_training", "kind": "canonical"}]
    for kind, result in (("brier", brier), ("nll", nll)):
        for row in result["arms"].values():
            pins[row["checkpoint"]] = row["checkpoint_sha256"]
            pins[row["native_export"]] = row["native_export_sha256"]
        for seed in (17, 29, 43):
            row = result["arms"][f"{seed}/mean" if kind == "brier" else f"{seed}/8"]
            if kind == "brier" and row["final_sha256"] != result["arms"][f"{seed}/entropic"]["final_sha256"]:
                raise ValueError("Mean and entropic aliases no longer have identical trained parameters")
            arms.append({"name": f"{kind}-{seed}", "kind": kind, "seed": seed,
                         "checkpoint": row["checkpoint"], "parameter_sha256": row["final_sha256"],
                         "aliases": ["mean", "entropic"] if kind == "brier" else ["proper-log-score-bound8"]})
    for name in ("ffmpeg", "ffprobe"):
        path = Path(shutil.which(name)).resolve()
        pins[str(path)] = sha(path)
    python = Path(sys.executable).resolve()
    pins[str(python)] = sha(python)
    allocation = directory.parent / "SOURCE_ALLOCATION.json"
    spec = {"schema": "hepta.advance.joint-confirmation-protocol.v1", "mode": args.stage,
            "registered_unix_ns": time.time_ns(), "config": str(config), "endpoints": str(endpoints),
            "endpoint_sha256": sha(endpoints), "arms": arms,
            "source_roles": ["confirmation"] if args.stage == "confirmation" else [],
            "source_allocation": str(allocation), "source_allocation_sha256": sha(allocation),
            "image_cache": str(workspace / "ndu-next-assets/qmnist"),
            "new_audio_root": str(workspace / "ndu-advance-assets/speech-commands-v002-digits"),
            "pair_count": 170 if args.stage == "confirmation" else 16,
            "routes": ["image", "text", "audio", "video"] if args.stage == "confirmation" else ["image", "audio"],
            "task_seed": 240701, "view_rule": "v7.data.VIEWS[case % 8]; same source task in every arm",
            "physical_arm_order": "Rotate the fixed eight-arm list by (case + 2*index_in_image_text_audio_video) % 8; each arm occupies every execution position 85 times across the complete 680-task panel",
            "bootstrap_seed": 240809, "bootstrap_replicates": 10000,
            "familywise_alpha": .05, "primary_families": 3,
            "primary": "Mean of the three fixed seed CE values minus canonical_no_training CE; each CE=-log(mean(exp(-2*actual_U)))/2",
            "primary_gate": "Paired 85-cluster percentile CE interval lower>0 AND strict-success difference interval lower>=0 (zero noninferiority margin); intersection-union gate",
            "bootstrap_scope": "Resample writer/speaker groups; retain both pairs, four routes and all seeds/arms together. Cluster exchangeability is an assumption, not population certification.",
            "secondary": "All route, calibration, Brier, unchanged-renderer, regret and timing contrasts are descriptive; no replacement primary or post-outcome candidate change",
            "unchanged_definition": "Exactly the frozen five-component reference, zero encoder noise, existing two continuations and greedy decoder; render the soft encoded state without a canonical action projection",
            "canonical_definition": "Same public encoder; raw posterior finite decision; fixed canonical renderer; no learned adapter",
            "alias_rule": "Brier mean/risk final parameter identities are exactly equal for all seeds; physically execute each seed once and report both aliases, never double the output/sample count",
            "baseline_rule": "Unchanged and canonical are each physically generated once per task and paired to all three seeds; not three independent outputs",
            "binary_risk_scope": "Measured U and strict table are identity. No independent entropic-training superiority is identifiable at equal static action cost.",
            "input_scope": "Real independent recorded digit speech; source handwritten digits; literal text; synthetic source-digit twenty-frame video, not natural-video generalization",
            "output_observer_scope": "Actual codec readback, same frozen metric family used in endpoint learning; no independent observer-family claim",
            "cost_scope": "Actual whole process plus measured prepare/encode/decision/generation/codec/audit; BLAS/Torch and encoders fixed1, frozen output readback decoder uses existing defaults; exact PCM cache reuse explicit and cold ASR never fabricated",
            "new_confirmation_sources_opened": False,
            "runtime_versions": {name: importlib.metadata.version(name) for name in ("torch", "numpy", "Pillow")},
            "local_python_dependency_closure_count": len(source_closure(directory / "confirm.py")),
            "frozen_candidate_sha256": pins}
    if args.stage == "confirmation":
        if args.smoke_result is None:
            raise ValueError("A completed unchanged old-data technical smoke is required")
        smoke = json.loads(args.smoke_result.read_text())
        if smoke["status"] != "completed" or smoke["mode"] != "old_smoke" or smoke["actual_output_file_count"] != 1024:
            raise ValueError("Expected all 256 actual old-source bundles")
        spec["technical_smoke"] = {"path": str(args.smoke_result.resolve()), "sha256": sha(args.smoke_result),
                                   "not_an_efficacy_selection_rule": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(spec, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"protocol": str(args.output.resolve()), "sha256": sha(args.output),
                      "local_python_dependencies": spec["local_python_dependency_closure_count"], "pins": len(pins)}))


if __name__ == "__main__":
    main()
