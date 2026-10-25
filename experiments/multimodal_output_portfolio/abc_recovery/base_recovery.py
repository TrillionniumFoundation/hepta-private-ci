"""Rebuild pinned historical inputs without opening new task outcomes.

Exact recovery requires the old file digest. New timers, reports and observer
qualification probes retain new identities even when the recipe is unchanged.
"""

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[3]
AREA = ROOT / "experiments/multimodal_output_portfolio"
MODULE = "experiments.multimodal_output_portfolio.abc_recovery.base_recovery"
MANIFEST_SHA = "60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058"
EXPECTED = {
    "supervised.pt": "12cd2560b03acd23cdf52d56aedc025bbc2663d58d6b7979fffd26a1fbc7c464",
    "terminal_entropic_ndu.pt": "2b95156f6848a82ce985b5ab1b31624c2e2f8bd4cf7296358f680e39fdd83d6c",
    "reward-observer.pt": "dc5813185707586f54877f2172f79d7bc3675b4ee41b3e93d19b8b598228aac0",
    "audit-observer.pt": "cd560d4ec2f45cef6a0f4db9809b902ea68833c8693798f7597135a83a6e3589",
    "training.json": "fbe31e19780acacd8cbad23d20bb25d8832a4a7d6bbb8e6e80c3706a705e46e4",
}


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def ids_sha(ids):
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def source_pins():
    files = [AREA / "v7" / (name + ".py") for name in
             ("sources", "data", "model", "snapshot", "training", "development")]
    files += [AREA / "v6" / (name + ".py") for name in ("data", "neural", "observer", "run")]
    files += [AREA / "v7/development_spec.json", AREA / "v6/results/full-002/protocol.json",
              AREA / "v6/results/full-002/summary.json", Path(__file__).resolve(),
              Path(__file__).with_name("base_recovery_tests.py")]
    return {str(path.relative_to(ROOT)): file_sha(path) for path in files}


def legacy_audit_ids(manifest, protocol, expected_audit_identity):
    """Resolve the old evaluator half from excluded identities, not new roles."""
    old = protocol["dataset_manifest"]
    if old["split_seed"] != manifest["split_seed"]:
        raise ValueError("Historical split seed differs")
    start = old["splits"]["train"]["count"] + old["splits"]["validation"]["count"]
    count = old["splits"]["evaluator"]["count"]
    if count != protocol["observer_sources"] or count % 2:
        raise ValueError("Invalid historical evaluator census")
    excluded = manifest["roles"]["excluded_v6_train"]["source_ids"]
    evaluator = tuple(excluded[start:start + count])
    if len(evaluator) != count or ids_sha(evaluator) != old["splits"]["evaluator"]["identity_sha256"]:
        raise ValueError("Historical evaluator source identity differs")
    selected = evaluator[count // 2:]
    if ids_sha(selected) != expected_audit_identity:
        raise ValueError("Historical audit half identity differs")
    forbidden = {identity for name, role in manifest["roles"].items()
                 if not name.startswith("excluded_") for identity in role["source_ids"]}
    if forbidden.intersection(selected):
        raise ValueError("Historical observer overlaps a new role")
    return selected


def freeze(cache, manifest_path, output):
    if file_sha(manifest_path) != MANIFEST_SHA:
        raise ValueError("Exact recovered source manifest required")
    spec = json.loads((AREA / "v7/development_spec.json").read_text())
    old = json.loads((AREA / "v6/results/full-002/protocol.json").read_text())
    summary = json.loads((AREA / "v6/results/full-002/summary.json").read_text())
    manifest = json.loads(Path(manifest_path).read_text())
    audit_ids = legacy_audit_ids(manifest, old, summary["observer"]["audit"]["source_ids_sha256"])
    pins = source_pins()
    for name in ("data", "neural", "observer"):
        path = f"experiments/multimodal_output_portfolio/v6/{name}.py"
        if pins[path] != old["source"]["files"][path]:
            raise ValueError("Original observer implementation changed: " + path)
    registration = {
        "schema": "hepta.ndu-abc.base-recovery-registration.v1",
        "cache": str(Path(cache).resolve()), "manifest": str(Path(manifest_path).resolve()),
        "manifest_file_sha256": MANIFEST_SHA, "output": str(Path(output).resolve()),
        "registered_unix_ns": time.time_ns(), "source_sha256": pins,
        "expected_original_file_sha256": EXPECTED,
        "base_config": {"seed": spec["development_seed"], "steps": spec["base_steps"],
                        "batch_size": spec["batch_size"], "scenarios": spec["latent_scenarios"],
                        "learning_rate": spec["learning_rate"], "risk_aversion": spec["risk_aversion"],
                        "noise_scale": spec["noise_scale"], "horizon": spec["control_horizon"],
                        "threads": spec["threads"]},
        "base_roles": ["train"], "base_deterministic_algorithms": False,
        "reward_observer": spec["reward_observer"],
        "legacy_observer": {"seed": old["observer_seeds"]["audit"],
                            "steps": old["observer_steps"], "sources": len(audit_ids),
                            "source_ids_sha256": ids_sha(audit_ids),
                            "full_evaluator_identity_sha256": old["dataset_manifest"]["splits"]["evaluator"]["identity_sha256"],
                            "deterministic_algorithms": True},
        "qualification": {"scope": "own observer pool's untouched final 20 percent only",
                          "original_accuracy_min": 0.95, "bernoulli_accuracy_min": 0.90,
                          "bernoulli_seeds": {"reward": 9021001, "audit": 9021002},
                          "sampler": "torch.bernoulli(original_uint8_pixels.float()/255)",
                          "images_per_observer": 1000, "changes_training_or_selection": False},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        **{name: importlib.metadata.version(name) for name in ("torch", "numpy", "Pillow")}},
        "formal_v7_outcomes_opened": False,
        "historical_training_timers_recoverable": False,
        "observer_progress": "Trace only the original fit_observer loop; no source or training-rule changes.",
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "rebuild-registration.json", registration)
    return registration


def fit_observer_progress(source, steps, seed, progress, interval=100):
    """Observe completed iterations without changing the pinned fitter."""
    from ..v6.observer import fit_observer
    lines, first = inspect.getsourcelines(fit_observer)
    loop = first + next(i for i, line in enumerate(lines) if "for _ in range(steps):" in line)
    previous = sys.gettrace()
    if previous is not None:
        raise RuntimeError("Cannot replace an existing trace hook")
    emitted = set()

    def trace_loop(frame, event, arg):
        if event == "line" and frame.f_lineno == loop and "_" in frame.f_locals:
            completed = frame.f_locals["_"] + 1
            if completed % interval == 0 and completed not in emitted:
                emitted.add(completed)
                progress(completed)
        return trace_loop

    def trace_call(frame, event, arg):
        return trace_loop if frame.f_code is fit_observer.__code__ else None

    try:
        sys.settrace(trace_call)
        return fit_observer(source, steps=steps, seed=seed)
    finally:
        sys.settrace(previous)


def legacy_audit_split(cache, manifest, protocol, identity):
    import torch
    from ..v6.data import SourceSplit
    from ..v7.sources import _read_cache
    selected = legacy_audit_ids(manifest, protocol, identity)
    pixels, labels, hashes = _read_cache(cache)["train"]
    indices = [int(identity.split(":")[2]) for identity in selected]
    if any(identity != f"mnist:train:{i}:{hashes[i]}" for i, identity in zip(indices, selected)):
        raise ValueError("Historical source pixels differ")
    images = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(-1, 1, 28, 28)
    labels = torch.tensor(list(labels), dtype=torch.long)
    return SourceSplit(images[indices].clone(), labels[indices].clone(), selected,
                       tuple(hashes[i] for i in indices))


def diagnose_observer(model, source, name, registration, output):
    import torch
    from ..v6.neural import parameter_hash
    before = parameter_hash(model)
    boundary = len(source) * 4 // 5
    pixels = source.images[boundary:].float() / 255
    labels, identities = source.labels[boundary:], source.ids[boundary:]
    policy = registration["qualification"]
    if len(pixels) != policy["images_per_observer"]:
        raise ValueError("Observer diagnostic census mismatch")
    generator = torch.Generator().manual_seed(policy["bernoulli_seeds"][name])
    sampled = torch.bernoulli(pixels, generator=generator)
    with torch.inference_mode():
        original = torch.cat([model(block).argmax(1) for block in pixels.split(256)])
        bernoulli = torch.cat([model(block).argmax(1) for block in sampled.split(256)])
    torch.save({"pixels": sampled.to(torch.uint8), "labels": labels, "source_ids": identities},
               output / f"{name}-bernoulli-probe.pt")
    records = [{"source_id": identity, "label": int(labels[i]), "original_prediction": int(original[i]),
                "bernoulli_prediction": int(bernoulli[i])} for i, identity in enumerate(identities)]
    with (output / f"{name}-diagnostic-rows.jsonl").open("x") as stream:
        for row in records:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    original_correct = int((original == labels).sum())
    bernoulli_correct = int((bernoulli == labels).sum())
    unchanged = parameter_hash(model) == before
    if not unchanged:
        raise RuntimeError("Observer diagnostic changed parameters")
    return {"sources": len(pixels), "source_ids_sha256": ids_sha(identities),
            "original_correct": original_correct, "bernoulli_correct": bernoulli_correct,
            "original_accuracy": original_correct / len(pixels),
            "bernoulli_accuracy": bernoulli_correct / len(pixels),
            "original_gate": original_correct / len(pixels) >= policy["original_accuracy_min"],
            "bernoulli_gate": bernoulli_correct / len(pixels) >= policy["bernoulli_accuracy_min"],
            "observer_parameter_sha256": before, "parameters_unchanged": unchanged,
            "sampled_pixels_artifact_sha256": file_sha(output / f"{name}-bernoulli-probe.pt"),
            "rows_sha256": file_sha(output / f"{name}-diagnostic-rows.jsonl"),
            "scope": "New bounded observer diagnostic; not a new generation result or general certification."}


def execute(registration_path):
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    registration = json.loads(Path(registration_path).read_text())
    output = Path(registration["output"])
    if source_pins() != registration["source_sha256"] or file_sha(registration["manifest"]) != MANIFEST_SHA:
        raise ValueError("Frozen execution inputs changed")
    try:
        import torch
        from ..v6.neural import parameter_hash
        from ..v6.observer import METRIC_DIGEST
        from ..v7.sources import load_roles, read_manifest
        from ..v7.snapshot import Snapshot
        from ..v7.training import TrainConfig, train_profiles
        torch.set_num_threads(registration["base_config"]["threads"])
        torch.use_deterministic_algorithms(registration["base_deterministic_algorithms"])

        def progress(stage, row):
            record = {"stage": stage, **row, "elapsed_wall_ns": time.perf_counter_ns() - started_wall}
            with (output / "progress.jsonl").open("a") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
            print(json.dumps(record, sort_keys=True), flush=True)

        corpus = load_roles(registration["cache"], registration["manifest"], roles=("train",))
        config = TrainConfig(**registration["base_config"])
        if asdict(config) != registration["base_config"]:
            raise ValueError("Base configuration drift")
        snapshots, reports = train_profiles(corpus, config, lambda name, row: progress(name, row))
        bases = {}
        for profile, snapshot in snapshots.items():
            path = output / (profile + ".pt")
            actual = snapshot.save(path)
            restored = Snapshot.load(path, expected_file_sha256=actual)
            if restored.fingerprint != snapshot.fingerprint:
                raise ValueError("Checkpoint reload differs")
            reports[profile]["checkpoint_file_sha256"] = actual
            bases[profile] = {"file_sha256": actual, "expected_original_file_sha256": EXPECTED[path.name],
                              "exact_original_file_recovered": actual == EXPECTED[path.name],
                              "parameter_sha256": snapshot.parameter_sha256,
                              "snapshot_sha256": snapshot.fingerprint}
        write_json(output / "training.json", reports)
        del corpus, snapshots
        observers = {}
        manifest = read_manifest(registration["manifest"])
        legacy_protocol = json.loads((AREA / "v6/results/full-002/protocol.json").read_text())
        for name in ("reward", "audit"):
            if name == "reward":
                pool = load_roles(registration["cache"], registration["manifest"], roles=("reward",)).splits["reward"]
                recipe = registration["reward_observer"]
            else:
                recipe = registration["legacy_observer"]
                torch.use_deterministic_algorithms(recipe["deterministic_algorithms"])
                pool = legacy_audit_split(registration["cache"], manifest, legacy_protocol, recipe["source_ids_sha256"])
            model, report = fit_observer_progress(pool, recipe["steps"], recipe["seed"],
                                                  lambda step: progress(name + "-observer", {"step": step}))
            params = parameter_hash(model)
            record = ({"schema": "hepta.ndu-v7.reward-observer.v1", "state_dict": model.state_dict(),
                       "parameter_sha256": params, "metric_sha256": METRIC_DIGEST,
                       "source_manifest_sha256": manifest["manifest_sha256"], "report": report}
                      if name == "reward" else model.state_dict())
            path = output / (name + "-observer.pt")
            torch.save(record, path)
            actual = file_sha(path)
            observers[name] = {"file_sha256": actual, "parameter_sha256": params,
                               "expected_original_file_sha256": EXPECTED[path.name],
                               "exact_original_file_recovered": actual == EXPECTED[path.name],
                               "training_report": report,
                               "diagnostic": diagnose_observer(model, pool, name, registration, output)}
            if name == "reward":
                observers[name]["new_wrapper_identity_reason"] = "Embedded wall_ns is a new measurement; no historical-byte equivalence is asserted."
                write_json(output / "reward-observer.json", {**report, "file_sha256": actual,
                           "parameter_sha256": params, "source_manifest_sha256": manifest["manifest_sha256"]})
        if source_pins() != registration["source_sha256"]:
            raise RuntimeError("Execution source changed during rebuild")
        result = {"schema": "hepta.ndu-abc.base-recovery-result.v1", "status": "completed",
                  "registration_sha256": file_sha(registration_path), "bases": bases, "observers": observers,
                  "training_history_file_sha256": file_sha(output / "training.json"),
                  "original_training_history_recovered": False,
                  "original_training_history_expected_sha256": EXPECTED["training.json"],
                  "original_training_timers": "Unavailable; all recorded CPU/wall values belong to this new rebuild.",
                  "formal_v7_outcomes_opened": False, "new_task_outcomes_opened": False,
                  "materialized_source_roles": {"v7_train": 12000, "v7_reward": 5000,
                                                "historical_v6_audit_within_excluded_v6_train": 5000},
                  "execution_wall_ns": time.perf_counter_ns() - started_wall,
                  "execution_cpu_ns": time.process_time_ns() - started_cpu}
        write_json(output / "result.json", result)
        print(json.dumps({"completed": str(output), "bases": bases,
                          "observer_gates": {k: v["diagnostic"] for k, v in observers.items()}}, sort_keys=True), flush=True)
    except BaseException as error:
        write_json(output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                   "wall_ns": time.perf_counter_ns() - started_wall, "cpu_ns": time.process_time_ns() - started_cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", type=Path)
    args = parser.parse_args()
    if args.execute:
        execute(args.execute)
        return
    if not all((args.cache, args.manifest, args.output)):
        parser.error("--cache, --manifest and --output are required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    registration = freeze(args.cache, args.manifest, args.output)
    output = Path(registration["output"])
    command = [sys.executable, "-B", "-m", MODULE, "--execute", str(output / "rebuild-registration.json")]
    write_json(output / "process-start.json", {"argv": command, "cwd": str(ROOT),
               "registered_before_child_start": True, "started_unix_ns": time.time_ns()})
    with (output / "process.log").open("x") as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(output / "whole-process-cost.json", {"schema": "hepta.ndu-abc.rebuild-process-cost.v1",
               "argv": command, "exit_code": code, "wrapper_and_child_wall_ns": time.perf_counter_ns() - wall,
               "wrapper_cpu_ns": time.process_time_ns() - cpu,
               "child_cpu_ns": round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9),
               "child_peak_rss_bytes": after.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
               "includes": "registration, loading, training, diagnostics, checkpoint/report/log writes and child exit",
               "historical_cost_recovered": False})
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
