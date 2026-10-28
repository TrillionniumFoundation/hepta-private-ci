"""Registered CPU-dispatch diagnosis on already consumed frozen development data.

All outputs are new diagnostic evidence. Historical scientific FAIL, admission
and raw-custody status remain unchanged, even if a configuration reproduces old
numbers. This file must be committed with PROTOCOL.json before execution.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
PORTFOLIO = HERE.parent.parent
REPOSITORY = PORTFOLIO.parent.parent
CASES = ("unset_before", "default", "avx2", "avx512", "unset_after")
FIELDS = ("text_fact", "relation", "image_fact", "crossmodal_disagreement", "pixel_mse")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def registration(commit):
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "A registered full commit is required")
    result = {}
    for path in (HERE / "PROTOCOL.json", Path(__file__).resolve()):
        name, raw = path.relative_to(REPOSITORY).as_posix(), path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        row = subprocess.check_output(["git", "ls-tree", commit, "--", name], cwd=REPOSITORY,
                                      env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, text=True).strip()
        require(row == "100644 blob " + blob + "\t" + name, "Unregistered source: " + name)
        result[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "git_blob": blob}
    return {"commit": commit, "files": result}


def verify_inputs(protocol, args):
    roots = {"repository": REPOSITORY, "run": args.run_root, "assets": args.assets,
             "runtime": Path(sys.prefix)}
    found = {}
    for name, item in protocol["inputs"].items():
        path = (roots[item["root"]] / item["path"]).resolve()
        require(path.is_relative_to(roots[item["root"]].resolve()) and path.is_file(), "Invalid input: " + name)
        require(path.stat().st_size == item["bytes"] and sha(path) == item["sha256"], "Input differs: " + name)
        found[name] = path
    freeze = read(found["scientific_source_freeze"])
    for name, expected in freeze["files"].items():
        require(sha(PORTFOLIO / name) == expected, "Frozen dependency differs: " + name)
    require(read(found["original_failed_audit"])["integrity_status"] == "FAIL", "Original FAIL changed")
    historical = {row["path"]: row for row in read(found["historical_archive_integrity"])["members"]}
    for panel, identity in protocol["historical_raw_identities"].items():
        require(panel in ("task", "clean") and identity == historical["run/development/17/original-" + panel + ".npz"],
                "Historical raw-file target differs from the recorded archive member")
    require(set(protocol["historical_raw_identities"]) == {"task", "clean"}, "Missing historical raw target")
    require(protocol["cases"] == list(CASES) and protocol["seed"] == 17
            and protocol["source_roles"] == ["development_task", "development_clean"]
            and not protocol["new_holdout_access"] and not protocol["admission"], "Scope differs")
    require(sys.version_info[:3] == (3, 12, 14) and sys.flags.isolated and sys.dont_write_bytecode,
            "Pinned isolated Python with -B is required")
    return found, freeze


def compare(left, right):
    import numpy as np

    require(left.dtype == right.dtype and left.shape == right.shape, "Array type/shape differs")
    require(np.isfinite(left).all() and np.isfinite(right).all(), "Nonfinite diagnostic value")
    mask, delta = left != right, left - right
    return {"exact": bool(np.array_equal(left, right)), "shape": list(left.shape),
            "dtype": str(left.dtype), "different_values": int(mask.sum()),
            "max_abs_difference": float(np.abs(delta).max()), "mean_difference": float(delta.mean()),
            "indices": np.argwhere(mask).tolist(), "left": left[mask].tolist(),
            "right": right[mask].tolist(), "delta": delta[mask].tolist(),
            "convention": "left minus right", "tolerance": None}


def imports_receipt(freeze):
    result = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("experiments."):
            continue
        location = getattr(module, "__file__", None)
        if location is None:
            continue
        path = Path(location).resolve()
        require(path.is_relative_to(PORTFOLIO), "Research import escaped frozen portfolio")
        relative = path.relative_to(PORTFOLIO).as_posix()
        require(relative in freeze["files"] and sha(path) == freeze["files"][relative],
                "Research import was not frozen: " + relative)
        result[name] = {"path": str(path), "sha256": freeze["files"][relative]}
    return result


def score_panel(model, panel, observers, protocol, costs, name, destination, fixed_raw):
    """Preserve the frozen hard_panel operation order; retain all score primitives."""
    import numpy as np
    import torch
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.learning import forward, save_hard
    from experiments.multimodal_output_portfolio.v6.data import render_tokens
    from experiments.multimodal_output_portfolio.v6.observer import observe_tensors

    values = {key: [] for key in observers}
    pixels, captions, hashes, conditions, ids, primitives, internals, fixed_mse = [], [], [], [], [], [], [], []
    charge, offset = protocol["training"]["refinement_charge"], 0
    with np.load(fixed_raw, allow_pickle=False) as saved:
        existing_pixels = saved["pixels_u8"].copy()
    with torch.inference_mode():
        for batch_index, part in enumerate(panel):
            batch, count = part.batch, len(part.batch.source_ids)
            output = forward(model, batch, 0, part.noise_seed, False, costs, name + "_generator")
            probability = output.image_logits.sigmoid()
            quantized = (probability * 255).round().to(torch.uint8)
            emitted = [render_tokens(row).encode("utf-8").decode("utf-8") for row in output.token_ids]
            by_observer = {}
            for observer_name, observer in observers.items():
                costs.add(name + "_" + observer_name + "_observer_calls", 2)
                costs.add(name + "_" + observer_name + "_observer_digit_examples", 2 * count)
                scored = observe_tensors(observer, quantized.float() / 255, emitted,
                                         batch.target.pixels, batch.target.labels)
                by_observer[observer_name] = scored
                values[observer_name].extend(row["utility"] - charge for row in scored)
            for index, (row, caption) in enumerate(zip(quantized, emitted, strict=True)):
                pixel_bytes, caption_bytes = row.numpy().tobytes(), caption.encode("utf-8")
                hashes.append(hashlib.sha256(pixel_bytes + caption_bytes).hexdigest())
                internals.append({"pixel_sha256": hashlib.sha256(pixel_bytes).hexdigest(),
                    "caption_utf8_sha256": hashlib.sha256(caption_bytes).hexdigest(),
                    "image_logits_sha256": hashlib.sha256(output.image_logits[index].numpy().tobytes()).hexdigest(),
                    "image_probability_sha256": hashlib.sha256(probability[index].numpy().tobytes()).hexdigest()})
                primitives.append({"row": len(primitives), "batch": batch_index,
                    "condition": part.condition, "noise_seed": part.noise_seed, "refinement_charge": charge,
                    "observers": {key: {**scored[index], "charged_utility": scored[index]["utility"] - charge}
                                  for key, scored in by_observer.items()}})
            fixed_image = torch.from_numpy(existing_pixels[offset:offset + count]).float() / 255
            fixed_mse.extend((fixed_image - batch.target.pixels).square().flatten(1).mean(1).double().tolist())
            offset += count
            pixels.append(quantized.numpy())
            captions.extend(emitted)
            conditions.extend([part.condition] * count)
            ids.extend(batch.source_ids)
    require(offset == len(existing_pixels), "Fixed raw pixel panel length differs")
    arrays = {key: np.asarray(value, dtype=np.float64) for key, value in values.items()}
    score = {"values": arrays, "means": {key: float(value.mean()) for key, value in arrays.items()},
             "output_sha256": hashes, "conditions": conditions, "source_ids": ids,
             "pixels_u8": np.concatenate(pixels), "captions_utf8": np.asarray(captions, dtype=str)}
    raw, details = destination / (name + ".npz"), destination / (name + "_components.json.gz")
    save_hard(raw, score)
    with details.open("xb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as stream:
            stream.write(json.dumps({"rows": primitives, "hashes": internals, "fixed_v5_raw_mse": fixed_mse},
                                    sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    return score, {"raw": {"path": raw.name, "sha256": sha(raw), "bytes": raw.stat().st_size},
                   "components": {"path": details.name, "sha256": sha(details), "bytes": details.stat().st_size}}


def child(args, protocol, sources):
    import numpy as np
    import torch
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.source_roles import load_corpus_roles
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.learning import panels
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.training_common import Costs
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.training_stages import panel_identity
    from experiments.multimodal_output_portfolio.v6.neural import parameter_hash
    from experiments.multimodal_output_portfolio.v6.observer import METRIC

    inputs, freeze = verify_inputs(protocol, args)
    require(torch.__version__ == "2.8.0+cpu" and np.__version__ == "2.3.5", "Runtime version mismatch")
    require(protocol["utility_weights"] == METRIC["weights"] and tuple(METRIC["weights"]) == FIELDS,
            "Utility decomposition differs from frozen observer")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    capability = torch.backends.cpu.get_cpu_capability()
    requested = None if args.child_case.startswith("unset_") else args.child_case
    require(os.environ.get("ATEN_CPU_CAPABILITY") == requested, "Dispatch environment differs")
    require(capability in protocol["expected_capabilities"][args.child_case], "Requested capability not observed")
    require(all(os.environ.get(k) == v for k, v in protocol["fixed_environment"].items()), "Other CPU environment changed")
    destination = args.output / args.child_case
    destination.mkdir(exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    report = {"case": args.child_case, "status": "FAIL", "seed": 17, "source_registration": sources,
              "requested_capability": requested, "observed_capability": capability,
              "torch_build_configuration": torch.__config__.show(), "new_holdout_access": False,
              "admission": False, "historical_audit_status": "FAIL", "historical_raw_file_recovered": False}
    write(destination / "START.json", report)
    costs, violations = Costs(), []

    def profile(frame, event, unused):
        module, function = frame.f_globals.get("__name__", ""), frame.f_code.co_name
        if event == "call" and ((module.startswith("torch.optim.") and function in ("__init__", "step"))
                or (module.startswith("torch.autograd") and function in ("backward", "_engine_run_backward"))
                or (module.startswith("experiments.") and function in ("make_context", "make_model", "new_optimizer", "rollout", "update"))):
            violations.append({"module": module, "function": function})
            raise RuntimeError("Diagnostic attempted training/optimizer execution")

    sys.setprofile(profile)
    try:
        v3 = read(inputs["v3_protocol"])
        models, observers, assets = load_assets(args.assets, [17], ["reward", "audit"])
        identities = {"model": parameter_hash(models[17]), **{k: parameter_hash(v) for k, v in observers.items()}}
        require(identities == protocol["parameter_identities"], "Loaded parameters differ")
        require(v3["training"]["fixed_actions"]["17"] == 0, "Frozen deployment action differs")
        corpus = load_corpus_roles(args.assets / "ndu-data", protocol["source_roles"])
        endpoint = {"task": panels(corpus, "development_task", 17, v3["training"]["conditions"], v3),
                    "clean": panels(corpus, "development_clean", 17, ["clean"], v3)}
        identities_panel = {name: panel_identity(panel) for name, panel in endpoint.items()}
        require(json.loads(json.dumps(identities_panel)) == read(inputs["current_panel_identities"]),
                "Reconstructed inputs changed")
        with np.load(inputs["old_endpoint_arrays"], allow_pickle=False) as old, np.load(inputs["current_endpoint_arrays"], allow_pickle=False) as current:
            results = {}
            for name, panel in endpoint.items():
                score, files = score_panel(models[17], panel, observers, v3, costs, name, destination, inputs["current_" + name + "_raw"])
                observed = np.stack([score["values"][key] for key in ("reward", "audit")])
                require(observed.shape == (2, protocol["panel_rows"][name]), "Panel cardinality changed")
                with np.load(inputs["current_" + name + "_raw"], allow_pickle=False) as raw:
                    require(np.array_equal(np.asarray(score["source_ids"]), raw["source_ids"])
                            and np.array_equal(np.asarray(score["conditions"]), raw["conditions"]), "Source ordering changed")
                    identity = protocol["historical_raw_identities"][name]
                    byte_match = (files["raw"]["sha256"] == identity["sha256"] and files["raw"]["bytes"] == identity["bytes"])
                    results[name] = {**files, "vs_historical_raw": {"recorded_identity": identity,
                            "full_sha256_and_bytes_exact": byte_match,
                            "interpretation": ("Newly reconstructed bytes match historical recorded identity" if byte_match
                                               else "New raw bytes do not match the recorded historical file"),
                            "original_storage_copy_recovered": False},
                        "vs_old_v3": compare(observed, old["original_" + name]),
                        "vs_current_v5": compare(observed, current["frozen_" + name]),
                        "vs_current_raw": {"changed_pixel_rows": np.flatnonzero(np.any(score["pixels_u8"] != raw["pixels_u8"], axis=(1, 2, 3))).tolist(),
                            "changed_caption_rows": np.flatnonzero(score["captions_utf8"] != raw["captions_utf8"]).tolist(),
                            "changed_output_hash_rows": np.flatnonzero(np.asarray(score["output_sha256"]) != raw["output_sha256"]).tolist()}}
        require({"model": parameter_hash(models[17]), **{k: parameter_hash(v) for k, v in observers.items()}} == identities,
                "Parameter state changed")
        require({name: panel_identity(panel) for name, panel in endpoint.items()} == identities_panel, "Panel mutation")
        require(sum(v for k, v in costs.snapshot().items() if k.endswith("generator_calls")) == 20, "Generator count differs")
        require(sum(v for k, v in costs.snapshot().items() if k.endswith("observer_calls")) == 80, "Observer count differs")
        report.update(status="COMPLETE", panels=results, parameter_identities=identities, assets=assets,
                      panel_identities=identities_panel, imported_sources=imports_receipt(freeze))
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        sys.setprofile(None)
        report.update(resources=costs.snapshot(), forbidden_training_calls=violations,
                      cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - started)
        write(destination / "RESULT.json", report)


def scoring_only_comparison(directory, inputs, protocol):
    """Keep baseline discrete primitives; substitute only each fixed-pixel MSE."""
    import numpy as np

    results = {}
    with np.load(inputs["old_endpoint_arrays"], allow_pickle=False) as old, np.load(inputs["current_endpoint_arrays"], allow_pickle=False) as current:
        for panel in ("task", "clean"):
            with gzip.open(directory / "unset_before" / (panel + "_components.json.gz"), "rt") as stream:
                baseline = json.load(stream)
            results[panel] = {}
            for case in CASES:
                with gzip.open(directory / case / (panel + "_components.json.gz"), "rt") as stream:
                    case_mse = json.load(stream)["fixed_v5_raw_mse"]
                values = []
                for observer in ("reward", "audit"):
                    column = []
                    for row, mse in zip(baseline["rows"], case_mse, strict=True):
                        fields = {**row["observers"][observer], "pixel_mse": mse}
                        loss = sum(protocol["utility_weights"][key] * fields[key] for key in FIELDS)
                        column.append(1 - 2 * loss - row["refinement_charge"])
                    values.append(column)
                values = np.asarray(values, dtype=np.float64)
                if case == "unset_before":
                    require(np.array_equal(values, current["frozen_" + panel]), "Baseline primitive reconstruction differs")
                results[panel][case] = {"vs_old_v3": compare(values, old["original_" + panel]),
                    "vs_current_v5": compare(values, current["frozen_" + panel])}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registered-commit", required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child-case", choices=CASES)
    args = parser.parse_args()
    args.assets, args.run_root, args.output = [p.resolve() for p in (args.assets, args.run_root, args.output)]
    require(not any(args.output.is_relative_to(p) or p.is_relative_to(args.output)
                    for p in (args.assets, args.run_root, REPOSITORY)), "Output overlaps protected inputs")
    protocol, sources = read(HERE / "PROTOCOL.json"), registration(args.registered_commit)
    inputs, unused = verify_inputs(protocol, args)
    sys.path.insert(0, str(REPOSITORY))
    if args.child_case:
        require(read(args.output / "START.json")["source_registration"] == sources, "Parent registration differs")
        child(args, protocol, sources)
        return
    require(all(os.environ.get(k) == v for k, v in protocol["fixed_environment"].items()), "Unregistered CPU environment")
    cpuinfo = Path("/proc/cpuinfo").read_text()
    flags = [set(line.split(":", 1)[1].split()) for line in cpuinfo.splitlines() if line.startswith("flags")]
    require(flags and all(set(protocol["required_host_flags"]) <= value for value in flags), "Unsupported host ISA")
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "CPUINFO.txt").open("x") as stream:
        stream.write(cpuinfo)
    write(args.output / "START.json", {"source_registration": sources, "protocol_sha256": sha(HERE / "PROTOCOL.json"),
        "cases": list(CASES), "cpuinfo_sha256": hashlib.sha256(cpuinfo.encode()).hexdigest(),
        "scientific_status": "FAIL", "admission": False, "historical_raw_file_recovered": False})
    results = []
    for name in CASES:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        environment.pop("ATEN_CPU_CAPABILITY", None)
        if not name.startswith("unset_"):
            environment["ATEN_CPU_CAPABILITY"] = name
        command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
            "--registered-commit", args.registered_commit, "--assets", str(args.assets),
            "--run-root", str(args.run_root), "--output", str(args.output), "--child-case", name]
        with (args.output / (name + ".stdout")).open("xb") as stdout, (args.output / (name + ".stderr")).open("xb") as stderr:
            result = subprocess.run(command, env=environment, cwd=REPOSITORY, stdout=stdout, stderr=stderr)
        path = args.output / name / "RESULT.json"
        results.append({"case": name, "exit_code": result.returncode,
                        "stdout_sha256": sha(args.output / (name + ".stdout")),
                        "stderr_sha256": sha(args.output / (name + ".stderr")),
                        "result_sha256": sha(path) if path.exists() else None,
                        "result": read(path) if path.exists() else None})
    verify_inputs(protocol, args)
    require(registration(args.registered_commit) == sources, "Diagnostic source changed")
    complete = all(r["exit_code"] == 0 and r["result"] and r["result"]["status"] == "COMPLETE" for r in results)
    controls_exact, baseline_exact, scoring_only, analysis_error = None, None, None, None
    if complete:
        controls_exact = all(sha(args.output / "unset_before" / (p + suffix)) == sha(args.output / "unset_after" / (p + suffix))
                            for p in ("task", "clean") for suffix in (".npz", "_components.json.gz"))
        baseline_exact = all(results[0]["result"]["panels"][p]["vs_current_v5"]["exact"]
                             and not any(results[0]["result"]["panels"][p]["vs_current_raw"].values()) for p in ("task", "clean"))
        if controls_exact and baseline_exact:
            try:
                scoring_only = scoring_only_comparison(args.output, inputs, protocol)
            except Exception as error:
                analysis_error = {"type": type(error).__name__, "message": str(error)}
    exact_raw_cases = {panel: [item["case"] for item in results if item["result"] and
        item["result"].get("panels", {}).get(panel, {}).get("vs_historical_raw", {}).get("full_sha256_and_bytes_exact", False)]
        for panel in ("task", "clean")}
    write(args.output / "SUMMARY.json", {"source_registration": sources, "execution_complete": complete,
        "unset_replicates_byte_exact": controls_exact, "unset_reproduces_current_v5": baseline_exact,
        "diagnostic_interpretable": bool(complete and controls_exact and baseline_exact and not analysis_error),
        "analysis_error": analysis_error, "cases": results,
        "fixed_raw_mse_only_arithmetic": scoring_only, "scientific_status": "FAIL", "admission": False,
        "new_holdout_authorized": False, "historical_raw_file_recovered": False, "selected_capability": None,
        "newly_reconstructed_historical_raw_matching_cases": exact_raw_cases,
        "interpretation": "Exact reproduction is compatibility evidence, not proof of historical CPU/ISA or full training equivalence."})
    require(complete and controls_exact and baseline_exact and not analysis_error,
            "Incomplete or unstable diagnosis; see preserved SUMMARY.json")


if __name__ == "__main__":
    main()
