"""Prospective development, independent fitting, and sealed-world confirmation.

Each worker retains its source identity, attempted arms, full actual decisions,
and process receipt. Shared preparation is counted once in the worker ledger.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

import numpy as np
import torch

from ..digital_read_before_20261031.data import cohort, prepare_fit
from ..digital_read_before_20261031.task import ContentAdapter, Oracle
from ..digital_mechanisms_20261101.execution import extend_behavior, run_episode
from .factors import FactorPolicy, FactorRuntime, candidates

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, compresslevel=6, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)
    return {"sha256": digest(path), "bytes": len(raw)}


def sources(protocol_path):
    upstream = read(HERE.parent / "digital_mechanisms_20261101/SOURCE_FREEZE.json")["source_sha256"]
    for path, expected in upstream.items():
        if digest(REPO / path) != expected:
            raise ValueError("Changed inherited source: " + path)
    result = dict(upstream)
    for path in sorted(HERE.glob("*.py")):
        result[str(path.relative_to(REPO))] = digest(path)
    result[str(protocol_path.resolve().relative_to(REPO))] = digest(protocol_path)
    return result


def public_map(records):
    return {r["id"]: read(Path(r["folder"]) / "public.json") for r in records}


def evaluate(models, records, adapter, confusion, protocol, fit, split, receipts):
    from .diagnostics import audit_episodes, build_support

    all_episodes, summaries, audits, runtime_cost = [], [], {}, []
    publics = public_map(records)
    oracles = {key: Oracle(public, confusion) for key, public in publics.items()}
    for identifier, policy in models.items():
        runtime = None if policy is None else FactorRuntime(policy)
        episodes = []
        for i, record in enumerate(records):
            seed = protocol["execution_seed_base"] + fit * 100000 + (20000 if "ood" in split else 10000) + i
            episode, _ = run_episode(runtime, record, adapter, confusion, "value", seed,
                                     diagnostic_oracle=oracles[record["id"]])
            # This is evaluator-only data appended strictly after termination.
            episode["label"] = read(Path(record["folder"]) / "evaluator.json")["label"]
            episode.update(fit=fit, split=split, candidate=identifier)
            episodes.append(episode)
        receipt = receipts.get(identifier, {})
        visit_rounds = {str(r["round_id"]): r.get("supervised_rows", [])
                        for r in receipt.get("visit_rounds", [])}
        support = build_support(receipt.get("behavior_rows_with_support", []), visit_rounds)
        audits[identifier] = audit_episodes(episodes, publics, support)
        metrics = {key: float(np.mean([e["metrics"][key] for e in episodes]))
                   for key in episodes[0]["metrics"]}
        valid = bool(receipt.get("training_valid", True) and receipt.get("cpu_compliant", True))
        summaries.append(dict(fit=fit, split=split, candidate=identifier, controller="value",
                              valid=valid, worlds=len(episodes), metrics=metrics))
        all_episodes.extend(episodes)
        runtime_cost.append(dict(candidate=identifier,
                                 lazy_preparation_cpu_seconds=0. if runtime is None else runtime.preparation_cpu,
                                 storage_bytes=0 if runtime is None else runtime.storage_bytes(),
                                 lazy_preparation_is_nested_in_episode=True))
    return all_episodes, summaries, audits, runtime_cost


def probe_pairs(policy, records, adapter, confusion, protocol, fit, split):
    from .diagnostics import extract_pairs

    runtime = FactorRuntime(policy)
    episodes = []
    for i, record in enumerate(records):
        seed = protocol["probe_seed_base"] + fit * 100000 + {
            "train": 0, "validation": 10000, "validation_ood": 20000,
            "iid": 30000, "ood": 40000,
        }[split] + i
        episode, _ = run_episode(runtime, record, adapter, confusion, "fixed", seed)
        episode.update(fit=fit, split=split, candidate="fpt_base_multi")
        episodes.append(episode)
    pairs = extract_pairs(runtime, episodes, public_map(records))
    return episodes, pairs


def train(root, fit, protocol, protocol_path, development):
    from .diagnostics import train_decoders
    from .training import fit_candidate
    from .quality import quality_audit

    root.mkdir(parents=True, exist_ok=False)
    cpu, wall = time.process_time(), time.perf_counter()
    identity = sources(protocol_path)
    write(root / "STARTED.json", dict(utc=datetime.now(timezone.utc).isoformat(), fit=fit,
          stage="development" if development else "formal_fit", source_sha256=identity,
          protocol=protocol, confirmation_generated=False, python=platform.python_version(),
          numpy=np.__version__, torch=torch.__version__))
    preparation = time.process_time()
    data = extend_behavior(prepare_fit(root / "data", fit, protocol))
    write(root / "training_data.json.gz", data)
    shared_preparation_cpu = time.process_time() - preparation
    adapter = ContentAdapter()
    models, receipts, attempts = {}, {}, []
    specs = candidates()
    order = np.random.default_rng(protocol["candidate_order_seed_base"] + fit).permutation(len(specs))
    for position in order:
        spec = specs[int(position)]
        before = time.process_time()
        try:
            policy, artifact, receipt = fit_candidate(spec, fit, data, adapter, protocol)
            models[spec["id"]] = policy
            receipts[spec["id"]] = receipt
            write(root / "models" / (spec["id"] + ".json"), artifact)
            write(root / "training" / (spec["id"] + ".json.gz"), receipt)
            attempt = dict(candidate=spec["id"], returned=True, valid=receipt["training_valid"],
                           cpu_compliant=receipt["cpu_compliant"],
                           call_and_persistence_cpu_seconds=time.process_time() - before)
        except Exception as error:
            attempt = dict(candidate=spec["id"], returned=False, valid=False,
                           error=repr(error), traceback=traceback.format_exc(),
                           call_and_persistence_cpu_seconds=time.process_time() - before)
        attempts.append(attempt)
        write(root / "attempts" / (spec["id"] + ".json"), attempt)
        print(json.dumps(dict(fit=fit, **attempt)), flush=True)
    if "fpt_base_multi" in models:
        episodes, extracted = probe_pairs(models["fpt_base_multi"], data["train_cohort"]["records"],
                                          adapter, data["confusion"], protocol, fit, "train")
        write(root / "probe_train.json.gz", dict(episodes=episodes, **extracted))
        decoder = train_decoders(extracted["pairs"], ridge=protocol["decoder_ridge"])
        write(root / "models" / "independent_decoders.json", decoder)
    if development:
        models["bayes"] = None
        summaries = []
        for split in ("validation", "validation_ood"):
            records = data["validation_cohort"]["records"] if split == "validation" else cohort(
                root / "development_ood", "ood", fit, protocol["validation_worlds"],
                dict(protocol, confirmation_seed_base=protocol["development_ood_seed_base"]))["records"]
            raw, summary, audits, costs = evaluate(models, records, adapter, data["confusion"],
                                                   protocol, fit, split, receipts)
            write(root / (split + "_episodes.json.gz"), raw)
            write(root / (split + "_audits.json.gz"), audits)
            write(root / (split + "_quality.json"), quality_audit(audits, protocol["quality_thresholds"]))
            write(root / (split + "_runtime.json"), costs)
            summaries.extend(summary)
        write(root / "summary.json", summaries)
    if sources(protocol_path) != identity:
        raise ValueError("Scientific source changed during fit")
    write(root / "FINISHED.json", dict(fit=fit, development=development, source_sha256=identity,
          whole_stage_cpu_seconds=time.process_time() - cpu,
          whole_stage_wall_seconds=time.perf_counter() - wall,
          shared_preparation_cpu_seconds=shared_preparation_cpu,
          all_candidates_returned=len(models) - int(development) == len(specs), attempts=attempts))


def confirm(root, training, seal_path, fit, protocol, protocol_path):
    from .diagnostics import evaluate_decoders
    from .quality import quality_audit

    seal = read(seal_path)
    if sources(protocol_path) != seal["source_sha256"] or protocol != seal["protocol"]:
        raise ValueError("Source/protocol changed after publication")
    if seal["fits"] != protocol["fits"] or fit not in seal["fits"]:
        raise ValueError("Incomplete or unregistered fit set")
    if any(set(seal[name]) != {str(f) for f in seal["fits"]}
           for name in ("training_files_sha256", "process_sha256")):
        raise ValueError("Incomplete all-fit custody map")
    for key in ("published_source_commit", "published_models_commit"):
        value = seal.get(key, "")
        if len(value) != 40 or set(value) - set("0123456789abcdef"):
            raise ValueError("Published source and all models required before confirmation")
    fitted = training / f"fit_{fit}"
    expected = seal["training_files_sha256"][str(fit)]
    if set(expected) != set(required_training_files()):
        raise ValueError("Seal omits or adds a required training artifact")
    for path, value in expected.items():
        if digest(fitted / path) != value:
            raise ValueError("Training artifact changed: " + path)
    for name in ("STARTED.json", "FINISHED.json"):
        if read(fitted / name)["source_sha256"] != seal["source_sha256"]:
            raise ValueError("Model was not trained on the sealed source")
    if digest(training / "process_receipts" / f"fit_{fit}.json") != seal["process_sha256"][str(fit)]:
        raise ValueError("Training process receipt changed")
    publication = seal_path.parent / seal["remote_verification_file"]
    if digest(publication) != seal["remote_verification_sha256"]:
        raise ValueError("Remote publication receipt changed")
    remote = read(publication)
    if (remote["commit"] != seal["published_models_commit"] or not remote["all_blob_hashes_verified"]
            or remote["model_manifest_sha256"] != seal["model_manifest_sha256"]):
        raise ValueError("Model publication has not been read back and verified")
    models, receipts = {}, {}
    for spec in candidates():
        identifier = spec["id"]
        path = fitted / "models" / (identifier + ".json")
        if not path.exists():
            raise ValueError("Missing attempted formal model: " + identifier)
        models[identifier] = FactorPolicy.from_export(read(path))
        receipts[identifier] = read(fitted / "training" / (identifier + ".json.gz"))
    models["bayes"] = None
    decoder = read(fitted / "models" / "independent_decoders.json")
    data = read(fitted / "training_data.json.gz")
    root.mkdir(parents=True, exist_ok=False)
    write(root / "STARTED.json", dict(fit=fit, utc=datetime.now(timezone.utc).isoformat(),
          seal_sha256=digest(seal_path), published_models_commit=seal["published_models_commit"],
          confirmation_preexisting=False))
    cpu, wall = time.process_time(), time.perf_counter()
    adapter = ContentAdapter()
    summaries = []
    for split in ("iid", "ood"):
        generated = cohort(root / "worlds", split, fit, protocol[f"{split}_worlds"], protocol)
        write(root / (split + "_cohort.json"), generated)
        raw, summary, audits, costs = evaluate(models, generated["records"], adapter,
            data["confusion"], protocol, fit, split, receipts)
        write(root / (split + "_episodes.json.gz"), raw)
        write(root / (split + "_audits.json.gz"), audits)
        write(root / (split + "_quality.json"), quality_audit(audits, protocol["quality_thresholds"]))
        write(root / (split + "_runtime.json"), costs)
        probe_episodes, extracted = probe_pairs(models["fpt_base_multi"], generated["records"],
            adapter, data["confusion"], protocol, fit, split)
        write(root / (split + "_probe.json.gz"), dict(episodes=probe_episodes, **extracted))
        write(root / (split + "_decoder.json"), evaluate_decoders(decoder, extracted["pairs"]))
        summaries.extend(summary)
        print(json.dumps(dict(fit=fit, split=split, evaluated=len(raw))), flush=True)
    write(root / "summary.json", summaries)
    write(root / "FINISHED.json", dict(fit=fit, whole_stage_cpu_seconds=time.process_time() - cpu,
          whole_stage_wall_seconds=time.perf_counter() - wall))


def required_training_files():
    paths = ["STARTED.json", "FINISHED.json", "training_data.json.gz", "probe_train.json.gz",
             "models/independent_decoders.json"]
    for spec in candidates():
        name = spec["id"]
        paths.extend([f"models/{name}.json", f"training/{name}.json.gz", f"attempts/{name}.json"])
    return sorted(paths)


def launch(args, protocol):
    """Own child CPU via wait4; no success-only aggregation or silent retries."""
    args.root.mkdir(parents=True, exist_ok=False)
    fits = protocol["development_fits" if args.stage == "development" else "fits"]
    write(args.root / "LAUNCH.json", dict(stage=args.stage, fits=fits, workers=args.workers,
          source_sha256=sources(args.protocol), utc=datetime.now(timezone.utc).isoformat()))
    pending, active = list(fits), {}
    while pending or active:
        while pending and len(active) < args.workers:
            fit = pending.pop(0)
            stdout = (args.root / f"fit_{fit}.stdout").open("xb")
            stderr = (args.root / f"fit_{fit}.stderr").open("xb")
            command = [sys.executable, "-m", "tools.hcsn.digital_feedback_20261101.study", args.stage,
                       "--root", str(args.root), "--fit", str(fit), "--protocol", str(args.protocol)]
            if args.training:
                command += ["--training", str(args.training)]
            if args.seal:
                command += ["--seal", str(args.seal)]
            child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=dict(os.environ,
                OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1"))
            active[child.pid] = (child, fit, stdout, stderr, time.perf_counter())
        for pid in list(active):
            ended, status, usage = os.wait4(pid, os.WNOHANG)
            if not ended:
                continue
            child, fit, stdout, stderr, started = active.pop(pid)
            child.returncode = os.waitstatus_to_exitcode(status)
            stdout.close()
            stderr.close()
            receipt = dict(fit=fit, returncode=child.returncode, cpu_seconds=usage.ru_utime + usage.ru_stime,
                           wall_seconds=time.perf_counter() - started, peak_rss_kib=usage.ru_maxrss)
            write(args.root / "process_receipts" / f"fit_{fit}.json", receipt)
            print(json.dumps(receipt), flush=True)
        if active:
            time.sleep(.1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("development", "train", "confirm"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--fit", type=int)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--seal", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    protocol = read(args.protocol)
    if args.fit is None:
        launch(args, protocol)
        return
    registered = protocol["development_fits" if args.stage == "development" else "fits"]
    if args.fit not in registered:
        raise ValueError("Fit is not registered")
    root = args.root / f"fit_{args.fit}"
    try:
        if args.stage == "confirm":
            confirm(root, args.training, args.seal, args.fit, protocol, args.protocol)
        else:
            train(root, args.fit, protocol, args.protocol, args.stage == "development")
    except BaseException as error:
        if root.exists() and not (root / "FAILED.json").exists():
            write(root / "FAILED.json", dict(error=repr(error), traceback=traceback.format_exc()))
        raise


if __name__ == "__main__":
    main()
