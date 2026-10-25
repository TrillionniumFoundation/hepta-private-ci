"""Prospective two-observer qualification on an isolated source census.

This command opens the registered qualification outcomes. Run it only after the
study protocol has been published and the root investigator authorizes execution.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

from .base_recovery import (AREA, EXPECTED, MANIFEST_SHA, ROOT, file_sha,
                            fit_observer_progress, ids_sha, legacy_audit_ids,
                            legacy_audit_split, source_pins as recovery_pins, write_json)


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.qualification"
PRIMARY_PARAMETER_SHA = "8d2b16722e9da2f23313d5d9f42bec4d60c28f4e52bfb37204e875456e2e36a3"
VIEWS = ("original", "bernoulli_0", "bernoulli_1")


def source_pins():
    paths = [Path(__file__), Path(__file__).with_name("qualification_tests.py"),
             AREA / "v7/evaluation.py"]
    return {**recovery_pins(), **{str(path.relative_to(ROOT)): file_sha(path) for path in paths}}


def qualification_ids(manifest, protocol):
    """Bind individual images to the exact fresh pair interval and its exclusions."""
    role = protocol["roles"]["observer_qualification"]
    if role != {"role": "development", "pair_start": 768, "pair_count": 128}:
        raise ValueError("Qualification role boundary differs from the registered experiment")
    start, end = 2 * role["pair_start"], 2 * (role["pair_start"] + role["pair_count"])
    q = protocol["observer_qualification"]
    if q["individual_source_interval"] != [start, end]:
        raise ValueError("Pair and individual source boundaries disagree")
    exclusions = [protocol["known_previous_development_pair_interval"]]
    for name in ("evaluation", "static_tuning"):
        other = protocol["roles"][name]
        if other["role"] != "development":
            raise ValueError("Unexpected task role")
        exclusions.append([other["pair_start"], other["pair_start"] + other["pair_count"]])
    if any(max(start, 2 * left) < min(end, 2 * right) for left, right in exclusions):
        raise ValueError("Qualification sources overlap task or historical sources")
    all_ids = manifest["roles"]["development"]["source_ids"]
    selected = tuple(all_ids[start:end])
    if len(selected) != 256 or len(set(selected)) != 256:
        raise ValueError("Qualification requires exactly 256 independent sources")
    forbidden = {identity for name, info in manifest["roles"].items() if name != "development"
                 for identity in info["source_ids"]}
    if forbidden.intersection(selected) or set(selected).intersection(all_ids[:start] + all_ids[end:]):
        raise ValueError("Qualification identities overlap another source allocation")
    return selected


def select_qualification(corpus, protocol):
    from ..v6.data import SourceSplit
    if set(corpus.splits) != {"development"}:
        raise ValueError("Only the development role may be materialized here")
    selected = qualification_ids(corpus.manifest, protocol)
    pool = corpus.splits["development"]
    if tuple(pool.ids) != tuple(corpus.manifest["roles"]["development"]["source_ids"]):
        raise ValueError("Materialized source order differs from registration")
    start, end = protocol["observer_qualification"]["individual_source_interval"]
    images, labels, hashes = pool.images[start:end].clone(), pool.labels[start:end].clone(), pool.pixel_hashes[start:end]
    if any(hashlib.sha256(image.numpy().tobytes()).hexdigest() != expected
           for image, expected in zip(images, hashes)):
        raise ValueError("Original qualification pixels differ from their source hashes")
    return SourceSplit(images, labels, selected, tuple(hashes))


def validate_policy(policy):
    expected = {"primary_steps": 1000, "primary_seed": 314159,
                "new_secondary_steps": 1000, "new_secondary_seed": 161803,
                "original_images_min_accuracy": 0.95, "bernoulli_original_images_min_accuracy": 0.90,
                "bernoulli_scenarios": 2, "bernoulli_seeds": [9022001, 9022002],
                "individual_source_interval": [1536, 1792],
                "bernoulli_gate": "each_registered_scenario_and_pooled"}
    if any(policy.get(key) != value for key, value in expected.items()):
        raise ValueError("Qualification policy differs from the prospective registration")


def save_inputs(source, policy, path):
    """Persist the shared actual inputs before either observer sees them."""
    import torch
    original = source.images
    if original.dtype != torch.uint8 or tuple(original.shape[1:]) != (1, 28, 28):
        raise ValueError("Expected original uint8 MNIST images")
    samples = [original.clone()]
    for seed in policy["bernoulli_seeds"]:
        generator = torch.Generator().manual_seed(seed)
        samples.append(torch.bernoulli(original.float() / 255, generator=generator).to(torch.uint8) * 255)
    record = {"schema": "hepta.ndu-abc.observer-qualification-inputs.v1",
              "source_ids": tuple(source.ids), "labels": source.labels.clone(),
              "source_hashes": tuple(source.pixel_hashes), "views": VIEWS,
              "bernoulli_seeds": policy["bernoulli_seeds"], "pixels": torch.stack(samples),
              "individual_start": policy["individual_source_interval"][0]}
    with Path(path).open("xb") as stream:
        torch.save(record, stream)
    return file_sha(path)


def read_inputs(path, expected_sha):
    import torch
    if file_sha(path) != expected_sha:
        raise ValueError("Actual qualification input artifact changed")
    record = torch.load(path, map_location="cpu", weights_only=True)
    pixels, labels, ids = record["pixels"], record["labels"], record["source_ids"]
    if (record["schema"] != "hepta.ndu-abc.observer-qualification-inputs.v1"
            or tuple(record["views"]) != VIEWS or len(set(ids)) != len(ids)
            or pixels.dtype != torch.uint8 or tuple(pixels.shape) != (3, len(ids), 1, 28, 28)
            or labels.dtype != torch.long or tuple(labels.shape) != (len(ids),)
            or not bool(((labels >= 0) & (labels < 10)).all())):
        raise ValueError("Invalid actual input census")
    if len(record["bernoulli_seeds"]) != 2 or len(record["source_hashes"]) != len(ids):
        raise ValueError("Actual input metadata census mismatch")
    for image, expected in zip(pixels[0], record["source_hashes"]):
        if hashlib.sha256(image.numpy().tobytes()).hexdigest() != expected:
            raise ValueError("Original source hash differs")
    for scenario, seed in enumerate(record["bernoulli_seeds"]):
        generator = torch.Generator().manual_seed(seed)
        expected = torch.bernoulli(pixels[0].float() / 255, generator=generator).to(torch.uint8) * 255
        if not torch.equal(expected, pixels[scenario + 1]):
            raise ValueError("Persisted Bernoulli pixels differ from the registered draw")
    return record


def score_inputs(models, record, policy):
    """Score every retained input with both frozen observers; never select one."""
    import torch
    from ..v6.neural import parameter_hash
    if set(models) != {"primary", "secondary"}:
        raise ValueError("Both registered observers are required")
    before = {name: parameter_hash(model) for name, model in models.items()}
    logits = {}
    with torch.inference_mode():
        for name, model in models.items():
            logits[name] = torch.stack([torch.cat([model(block) for block in view.float().div(255).split(256)])
                                        for view in record["pixels"]])
    rows, summaries = [], {}
    for view_index, view in enumerate(VIEWS):
        for i, identity in enumerate(record["source_ids"]):
            index = record["individual_start"] + i
            rows.append({"source_id": identity, "individual_index": index, "pair_index": index // 2,
                         "pair_slot": index % 2, "view": view,
                         "scenario": None if view_index == 0 else view_index - 1,
                         "generation_seed": None if view_index == 0 else record["bernoulli_seeds"][view_index - 1],
                         "pixel_sha256": hashlib.sha256(record["pixels"][view_index, i].numpy().tobytes()).hexdigest(),
                         "label": int(record["labels"][i]),
                         "predictions": {name: {"class": int(values[view_index, i].argmax()),
                                                "logits": values[view_index, i].tolist()}
                                         for name, values in logits.items()}})
    for name in models:
        per_view = {}
        for view_index, view in enumerate(VIEWS):
            correct = int((logits[name][view_index].argmax(1) == record["labels"]).sum())
            n = len(record["source_ids"])
            threshold = policy["original_images_min_accuracy" if view_index == 0 else
                               "bernoulli_original_images_min_accuracy"]
            per_view[view] = {"correct": correct, "n": n, "independent_sources": n,
                              "accuracy": correct / n, "threshold": threshold, "passed": correct / n >= threshold}
        total = sum(item["correct"] for key, item in per_view.items() if key != "original")
        pooled = {"correct": total, "n": 2 * n, "independent_sources": n,
                  "scenarios_per_source": 2, "accuracy": total / (2 * n),
                  "threshold": policy["bernoulli_original_images_min_accuracy"],
                  "passed": total / (2 * n) >= policy["bernoulli_original_images_min_accuracy"]}
        summaries[name] = {"parameter_sha256": before[name], "per_view": per_view, "bernoulli_pooled": pooled,
                           "all_view_census": {"correct": total + per_view["original"]["correct"], "n": 3 * n,
                                               "independent_sources": n, "accuracy": (total + per_view["original"]["correct"]) / (3 * n)},
                           "qualified": all(item["passed"] for item in per_view.values()) and pooled["passed"]}
    if {name: parameter_hash(model) for name, model in models.items()} != before:
        raise RuntimeError("Qualification changed observer parameters")
    return rows, summaries


def freeze(args):
    protocol = json.loads(args.protocol.read_text())
    validate_policy(protocol["observer_qualification"])
    if file_sha(args.manifest) != MANIFEST_SHA or protocol["source_manifest_file_sha256"] != MANIFEST_SHA:
        raise ValueError("Exact source registration required")
    manifest = json.loads(args.manifest.read_text())
    selected = qualification_ids(manifest, protocol)
    old = json.loads((AREA / "v6/results/full-002/protocol.json").read_text())
    summary = json.loads((AREA / "v6/results/full-002/summary.json").read_text())
    audit = legacy_audit_ids(manifest, old, summary["observer"]["audit"]["source_ids_sha256"])
    registration = {"schema": "hepta.ndu-abc.observer-qualification-registration.v1",
                    "registered_unix_ns": time.time_ns(), "source_sha256": source_pins(),
                    "cache": str(args.cache.resolve()), "manifest": str(args.manifest.resolve()),
                    "manifest_file_sha256": MANIFEST_SHA, "output": str(args.output.resolve()),
                    "protocol": str(args.protocol.resolve()), "protocol_file_sha256": file_sha(args.protocol),
                    "primary": str(args.primary.resolve()), "primary_file_sha256": file_sha(args.primary),
                    "primary_parameter_sha256": PRIMARY_PARAMETER_SHA,
                    "qualification_source_ids": selected, "qualification_source_ids_sha256": ids_sha(selected),
                    "secondary_training_source_ids_sha256": ids_sha(audit),
                    "legacy_secondary_file_sha256": EXPECTED["audit-observer.pt"],
                    "legacy_secondary_qualification": "Original-image accuracy .949 failed .95; retained unchanged.",
                    "new_secondary_identity": True, "deterministic_algorithms": True,
                    "selection_rule": "Report primary, secondary and their conjunction; never choose a winner.",
                    "formal_audit_retention_test_outcomes_opened": False}
    with (args.output / "protocol.json").open("xb") as stream:
        stream.write(args.protocol.read_bytes())
    write_json(args.output / "qualification-registration.json", registration)
    return registration


def execute(registration_path):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    registration = json.loads(Path(registration_path).read_text())
    output = Path(registration["output"])
    try:
        if (source_pins() != registration["source_sha256"]
                or file_sha(registration["protocol"]) != registration["protocol_file_sha256"]
                or file_sha(output / "protocol.json") != registration["protocol_file_sha256"]
                or file_sha(registration["manifest"]) != registration["manifest_file_sha256"]):
            raise ValueError("Frozen qualification inputs changed")
        import torch
        from ..v6.neural import parameter_hash
        from ..v6.observer import METRIC_DIGEST
        from ..v7.evaluation import load_reward
        from ..v7.sources import load_roles, read_manifest
        protocol = json.loads((output / "protocol.json").read_text())
        policy = protocol["observer_qualification"]
        validate_policy(policy)
        torch.set_num_threads(protocol["threads"])
        torch.use_deterministic_algorithms(registration["deterministic_algorithms"])
        manifest = read_manifest(registration["manifest"])
        primary, record = load_reward(registration["primary"], registration["primary_file_sha256"])
        if (parameter_hash(primary) != registration["primary_parameter_sha256"]
                or record["source_manifest_sha256"] != manifest["manifest_sha256"]
                or record["report"]["steps"] != policy["primary_steps"]
                or record["report"]["seed"] != policy["primary_seed"]
                or record["report"]["source_ids_sha256"] != manifest["roles"]["reward"]["identity_sha256"]):
            raise ValueError("Primary observer identity or training provenance differs")
        legacy = json.loads((AREA / "v6/results/full-002/protocol.json").read_text())
        pool = legacy_audit_split(registration["cache"], manifest, legacy,
                                  registration["secondary_training_source_ids_sha256"])

        def progress(step):
            item = {"stage": "new-secondary-training", "step": step, "elapsed_wall_ns": time.perf_counter_ns() - wall}
            with (output / "progress.jsonl").open("a") as stream:
                stream.write(json.dumps(item, sort_keys=True) + "\n")
            print(json.dumps(item, sort_keys=True), flush=True)

        secondary, training = fit_observer_progress(pool, policy["new_secondary_steps"], policy["new_secondary_seed"], progress)
        record = {"schema": "hepta.ndu-v7.reward-observer.v1", "state_dict": secondary.state_dict(),
                  "parameter_sha256": parameter_hash(secondary), "metric_sha256": METRIC_DIGEST,
                  "source_manifest_sha256": manifest["manifest_sha256"], "report": training,
                  "provenance": "New 1000-step secondary; does not replace the recovered 300-step historical observer."}
        path = output / "secondary-observer.pt"
        with path.open("xb") as stream:
            torch.save(record, stream)
        secondary_sha = file_sha(path)
        secondary, _ = load_reward(path, secondary_sha)
        write_json(output / "secondary-training.json", {**training, "file_sha256": secondary_sha,
                                                       "parameter_sha256": parameter_hash(secondary)})
        qualification_started = time.perf_counter_ns()
        corpus = load_roles(registration["cache"], registration["manifest"], roles=("development",))
        source = select_qualification(corpus, protocol)
        if ids_sha(source.ids) != registration["qualification_source_ids_sha256"]:
            raise ValueError("Fresh qualification source identity changed")
        artifact = output / "qualification-inputs.pt"
        input_sha = save_inputs(source, policy, artifact)
        reopened = read_inputs(artifact, input_sha)
        rows, observers = score_inputs({"primary": primary, "secondary": secondary}, reopened, policy)
        with (output / "raw-predictions.jsonl").open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        if (source_pins() != registration["source_sha256"]
                or file_sha(registration["protocol"]) != registration["protocol_file_sha256"]
                or file_sha(registration["primary"]) != registration["primary_file_sha256"]):
            raise RuntimeError("Frozen source or observer changed during qualification")
        result = {"schema": "hepta.ndu-abc.observer-qualification-result.v1", "status": "completed",
                  "registration_sha256": file_sha(registration_path), "protocol_sha256": registration["protocol_file_sha256"],
                  "source_ids_sha256": ids_sha(source.ids), "independent_sources": len(source),
                  "input_rows": len(rows), "observer_prediction_rows": len(rows) * 2,
                  "source_pair_interval": [768, 896], "individual_source_interval": [1536, 1792],
                  "observers": observers, "both_qualified": all(item["qualified"] for item in observers.values()),
                  "observer_selection_performed": False, "parameters_unchanged": True,
                  "primary_file_sha256": registration["primary_file_sha256"], "secondary_file_sha256": secondary_sha,
                  "actual_inputs_file_sha256": input_sha, "predictions_file_sha256": file_sha(output / "raw-predictions.jsonl"),
                  "secondary_training_report": training, "qualification_wall_ns": time.perf_counter_ns() - qualification_started,
                  "execution_wall_ns": time.perf_counter_ns() - wall, "execution_cpu_ns": time.process_time_ns() - cpu,
                  "formal_audit_retention_test_outcomes_opened": False, "task_evaluation_or_tuning_outcomes_opened": False,
                  "interpretation": "Bounded source-image observer qualification; not a generated-output or general reliability guarantee."}
        write_json(output / "result.json", result)
        print(json.dumps({"completed": str(output), "observers": observers, "both_qualified": result["both_qualified"]}, sort_keys=True), flush=True)
    except BaseException as error:
        write_json(output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "manifest", "primary", "output", "protocol", "execute"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.execute:
        execute(args.execute)
        return
    if not all((args.cache, args.manifest, args.primary, args.output, args.protocol)):
        parser.error("--cache, --manifest, --primary, --output and --protocol are required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.output.mkdir(parents=True, exist_ok=False)
    code, command = 1, []
    try:
        registration = freeze(args)
        output = Path(registration["output"])
        command = [sys.executable, "-B", "-m", MODULE, "--execute", str(output / "qualification-registration.json")]
        write_json(output / "process-start.json", {"argv": command, "cwd": str(ROOT),
                   "registered_before_child_start": True, "started_unix_ns": time.time_ns()})
        with (output / "process.log").open("x") as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in child.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            code = child.wait()
    except BaseException as error:
        write_json(args.output / "wrapper-failure.json", {"error": repr(error), "traceback": traceback.format_exc()})
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write_json(args.output / "whole-process-cost.json", {"schema": "hepta.ndu-abc.qualification-process-cost.v1",
                   "argv": command, "exit_code": code, "wrapper_and_child_wall_ns": time.perf_counter_ns() - wall,
                   "wrapper_cpu_ns": time.process_time_ns() - cpu,
                   "child_cpu_ns": round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9),
                   "child_peak_rss_bytes": after.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                   "includes": "registration, loading, secondary training, qualification, raw IO, report/log writes and child exit"})
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
