"""Freeze, train, exit, then evaluate once using independent held expressions."""

import argparse
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from corpus import CALIBRATION, TRAIN, canonical_key, memory_rows, query_rows
from owner import create
from runtime_contract import canonical, digest
from score import aggregate, score


HELD_SHA256 = "adb6e49064917de92eb32c799c3331a5ee0050b4331417ebe9134dfeefe8ecd2"
ARMS = ("learned/parameter", "deterministic/parameter", "oracle/parameter",
        "learned/retrieval", "deterministic/retrieval", "oracle/retrieval",
        "zero/oracle", "headonly/oracle", "joint/oracle")


def save(path, value):
    path.write_bytes(canonical(value))


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": digest(raw)}


def command(argv, log, executions, *, request=None, timeout=600):
    began, cpu = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    with subprocess.Popen(argv, stdin=subprocess.PIPE if request is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}) as child:
        pid = child.pid
        try:
            out, errors = child.communicate(request, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            out, errors = child.communicate()
    ended = time.monotonic_ns()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    log.with_suffix(".stdout").write_bytes(out)
    log.with_suffix(".stderr").write_bytes(errors)
    receipt = {"command": argv, "pid": pid, "started_ns": began, "exited_ns": ended,
               "exit_code": child.returncode, "wall_ns": ended-began,
               "cpu_seconds": after.ru_utime+after.ru_stime-cpu.ru_utime-cpu.ru_stime,
               "stdout": identity(log.with_suffix(".stdout")), "stderr": identity(log.with_suffix(".stderr")),
               "request_bytes": len(request) if request else 0, "timed_out": timed_out}
    executions.append(receipt)
    save(log.with_suffix(".process.json"), receipt)
    if child.returncode or timed_out:
        raise RuntimeError(f"command failed ({child.returncode}): {argv}; original stdout/stderr preserved")
    return out


def encode(args, output, stem, texts, executions):
    source = output / f"{stem}-texts.json"
    save(source, texts)
    command([args.encoder_python, "-I", "-B", str(ROOT / "encoder.py"), "--model-dir", args.encoder_dir,
             "--input", str(source), "--output", str(output / f"{stem}-encoded.npz"),
             "--receipt", str(output / f"{stem}-encoder.json")], output / f"{stem}-encoder", executions)
    with np.load(output / f"{stem}-encoded.npz", allow_pickle=False) as values:
        return values["features"].copy()


def run(args):
    began = time.monotonic_ns()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    executions = []
    protocol = json.loads((ROOT / "PROTOCOL.json").read_bytes())
    source = {p.name: identity(p) for p in sorted(ROOT.iterdir()) if p.is_file() and p.suffix in (".py", ".json")}
    if source["held_prompts.json"]["sha256"] != HELD_SHA256:
        raise ValueError("independent held input changed")
    freeze = {"schema": "hepta.memory.adapter-freeze.v1", "created_ns": time.monotonic_ns(), "source_files": source,
              "protocol": protocol, "held_content_opened_for_training": False,
              "held_hash_read_only_before_training": True, "training_models_exist": False}
    save(args.output / "FREEZE.json", freeze)
    development = {"train": query_rows(TRAIN, "train"), "calibration": query_rows(CALIBRATION, "calibration")}
    save(args.output / "development.json", development)
    save(args.output / "sources.json", memory_rows())
    texts = [canonical_key(kind, i) for kind in ("semantic", "skill") for i in range(8)]
    texts += [r["text"] for r in development["train"] + development["calibration"]]
    features = encode(args, args.output, "development", texts, executions)
    split_at = 16+len(development["train"])
    np.savez_compressed(args.output / "development_features.npz", semantic=features[:8], skill=features[8:16],
                        train=features[16:split_at], calibration=features[split_at:])
    np.savez_compressed(args.output / "canonical.npz", semantic=features[:8], skill=features[8:16])
    command([args.training_python, "-I", "-B", str(ROOT / "train.py"),
             "--development", str(args.output / "development.json"), "--features", str(args.output / "development_features.npz"),
             "--protocol", str(ROOT / "PROTOCOL.json"), "--encoder-receipt", str(args.output / "development-encoder.json"),
             "--output", str(args.output / "models")], args.output / "training", executions, timeout=1200)
    trainer_exited = executions[-1]["exited_ns"]
    training = json.loads((args.output / "models/TRAINING.json").read_bytes())
    # Only after the trainer has exited do we parse the independent held file.
    held_opened = time.monotonic_ns()
    held_data = json.loads((ROOT / "held_prompts.json").read_bytes())
    held = query_rows(held_data["prompts"], "held")
    save(args.output / "held-evaluator-rows.json", held)
    held_features = encode(args, args.output, "held", [r["text"] for r in held], executions)
    encoder = json.loads((args.output / "held-encoder.json").read_bytes())
    if training["encoder_sha"] != encoder["base_encoder_sha"]:
        raise ValueError("training and held encoder contracts differ")
    queries = [{"id": row["id"], "text": row["text"], "feature": held_features[i].tolist(),
                "oracle_route": {key: row[key] for key in ("role", "entity", "workflow")}}
               for i, row in enumerate(held)]
    results = []
    lifecycle_results = []
    structure_readouts = []
    for seed in protocol["seeds"]:
        structure_request = {"model_root": str(args.output / "models" / f"seed-{seed}"),
                             "encoder_sha": encoder["base_encoder_sha"],
                             "canonical_features_path": str(args.output / "canonical.npz")}
        structure_raw = command([args.training_python, "-I", "-B", str(ROOT / "structure_reader.py")],
                                args.output / f"structure-{seed}", executions, request=canonical(structure_request))
        structure_report = json.loads(structure_raw)
        if structure_report["training_modules_loaded"] or not structure_report["shared_head_restored"]:
            raise ValueError("fresh structure parameter read violated its contract")
        shifted = next(s["structure"]["shifted_policies"] for s in training["seeds"] if s["seed"] == seed)
        observed = {name: {"correct": sum(row["value"] == shifted[row["entity"]] for row in entry["rows"]),
                           "count": len(entry["rows"]), "parameter_counts": entry["parameter_counts"]}
                    for name, entry in structure_report["candidates"].items()}
        structure_readouts.append({"seed": seed, "fresh_process_results": observed,
                                   "response_sha256": digest(structure_raw)})
        lifecycle_database = args.output / f"lifecycle-{seed}.sqlite"
        create(lifecycle_database, memory_rows())
        lifecycle_raw = command([args.training_python, "-I", "-B", str(ROOT / "lifecycle.py"),
                                 "--model-root", str(args.output / "models" / f"seed-{seed}"),
                                 "--database", str(lifecycle_database), "--features", str(args.output / "canonical.npz"),
                                 "--encoder-sha", encoder["base_encoder_sha"]], args.output / f"lifecycle-{seed}", executions)
        lifecycle_results.append(json.loads(lifecycle_raw))
        for event_shift in (0, 7, 11):
            name = f"read-seed-{seed}-event-{event_shift}"
            database = args.output / f"{name}.sqlite"
            create(database, memory_rows())
            db = sqlite3.connect(database)
            for entity in range(8):
                db.execute("UPDATE events SET value=? WHERE entity=? AND sequence=1",
                           ((3*entity+5+event_shift) % 17, entity))
            db.commit()
            db.close()
            request = {"model_root": str(args.output / "models" / f"seed-{seed}"), "seed": seed,
                       "encoder_sha": encoder["base_encoder_sha"], "database": str(database),
                       "canonical_features_path": str(args.output / "canonical.npz"), "queries": queries, "arms": list(ARMS)}
            save(args.output / f"{name}.request.json", request)
            raw = command([args.training_python, "-I", "-B", str(ROOT / "reader.py")],
                          args.output / name, executions, request=canonical(request), timeout=600)
            report = json.loads(raw)
            if report.get("training_modules_loaded"):
                raise ValueError("reader imported a training/target module")
            scored = score(report, held, event_shift, ARMS)
            entry = {"seed": seed, "event_shift": event_shift, "scores": scored,
                     "reader_started_after_trainer_exited": executions[-1]["started_ns"] > trainer_exited,
                     "request_sha256": digest(canonical(request)), "response_sha256": digest(raw)}
            save(args.output / f"{name}.score.json", entry)
            results.append(entry)
    final_source = {p.name: identity(p) for p in sorted(ROOT.iterdir()) if p.is_file() and p.suffix in (".py", ".json")}
    if final_source != source:
        raise ValueError("study source changed after freeze")
    aggregate_scores = aggregate(results)
    summary = {"schema": "hepta.memory.adapter-study-result.v1", "scope": protocol["scope"],
               "protocol_sha256": source["PROTOCOL.json"]["sha256"], "held_sha256": HELD_SHA256,
               "trainer_pid": training["pid"], "trainer_exited_ns": trainer_exited,
               "held_first_parsed_ns": held_opened, "causal_order_verified": trainer_exited < held_opened,
               "seeds": protocol["seeds"], "held_rows_per_context": len(held), "independent_wording_groups": 32,
               "event_contexts": [0, 7, 11], "rows_are_not_independent_trials": True,
               "all_candidate_fits": sum(len(x["fits"]) for x in training["seeds"]),
               "sample_presentations": sum(f["sample_presentations"] for s in training["seeds"] for f in s["fits"]),
               "aggregate_scores": aggregate_scores,
               "structure": [{"seed": s["seed"], **s["structure"]} for s in training["seeds"]],
               "maintenance": [{"seed": s["seed"], **s["maintenance"]} for s in training["seeds"]],
               "owner_lifecycle": lifecycle_results,
               "fresh_structure_readouts": structure_readouts,
               "cost": {"lifecycle_wall_ns_before_summary": time.monotonic_ns()-began,
                        "executions": executions, "training_wall_seconds": training["wall_seconds"],
                        "training_cpu_seconds": training["cpu_seconds"], "training_peak_rss_kib": training["peak_rss_kib"],
                        "encoder_base_bytes": encoder["base_bytes"],
                        "stock_bytes_before_summary": sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file()),
                        "full_cost_superiority_established": False,
                        "resident_memory_byte_seconds": None,
                        "missing_measurement": "No per-arm RSS integral or native embedding transport measurement"},
               "native_tensor_profile_integrated": False, "passed_execution_integrity": True,
               "research_advantage_implied_by_execution_success": False}
    save(args.output / "RESULT.json", summary)
    print(json.dumps({"passed_execution_integrity": True, "rows": len(held), "fits": summary["all_candidate_fits"],
                      "aggregate_scores": aggregate_scores, "output": str(args.output)}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    for name in ("encoder-python", "training-python", "encoder-dir"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except BaseException as error:
        if args.output.exists():
            save(args.output / "FAILED.json", {"error": f"{type(error).__name__}: {error}", "held_was_not_used_to_retune": True})
        raise


if __name__ == "__main__":
    main()
