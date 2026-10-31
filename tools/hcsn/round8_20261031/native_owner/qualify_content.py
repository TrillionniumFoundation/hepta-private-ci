"""Full content cost on the frozen native owner, with an ordinary event baseline.

All backends decode once per public endpoint. Dense schedules perform extra
native control commits only; this cannot manufacture redundant decoder work.
Content is the existing marked-symbol memory task, not open-language quality.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
from tools.hcsn.task_value_factorial_20261030.task import ContentAdapter, packet
from qualify import Client, FAMILIES, PARAMETERS, ZERO, save


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish(path, value):
    """Publish an acknowledged completed-effect checkpoint durably."""
    temporary = path.with_suffix(".pending")
    with temporary.open("x") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_one(binary, output, data, family, seed, dense, missing):
    name = f"{family}-{seed}-{'dense' if dense else 'event'}-{'missing' if missing else 'normal'}"
    root = output / name
    root.mkdir()
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    schedule = json.loads((data / f"schedule-{seed}.json").read_text())
    model = root / "model.json"
    save(model, dict(parameters=PARAMETERS, family=family, seed_hex=f"{seed:016x}"))
    adapter = ContentAdapter()
    model_digest = adapter.setup["checkpoint_sha256"]
    sequence, pair, child_cpu, durable, decoder_calls, failed = 0, ZERO, 0., 0, 0, 0
    endpoints, content_rows = [], []
    content_path, frontier = root / "content.jsonl", root / "completed.json"
    with (root / "receipts.jsonl").open("x") as log, content_path.open("x") as content:
        client = Client(binary, model, root, pair, log)
        try:
            for index, step in enumerate(schedule):
                subdivisions = 16 if dense else 1
                for part in range(subdivisions):
                    sequence += 1
                    request = dict(sequence=sequence, pair_before=pair, driver=step["driver"],
                        duration_micros=step["duration_micros"] // subdivisions,
                        horizon_micros=step["horizon_micros"], reset=step["reset"] and part+1 == subdivisions)
                    receipt = client.step(request)
                    pair = receipt["pair_after"]
                    durable += receipt["durable_bytes_written"]
                payload = data / step["packet"]
                if missing and index == 4:
                    payload = data / "declared-missing-packet.json"
                cpu, wall = time.process_time(), time.perf_counter()
                try:
                    decoded = adapter.read(payload)
                    decoder_calls += 1
                    row = dict(index=index, status="decoded", **decoded)
                except FileNotFoundError as error:
                    failed += 1
                    row = dict(index=index, status="failed_read", error=type(error).__name__)
                row.update(attempt_cpu_seconds=time.process_time()-cpu, attempt_wall_seconds=time.perf_counter()-wall,
                           native_pair=pair, signals_q24=receipt["signals_q24"])
                content.write(json.dumps(row, sort_keys=True, allow_nan=False)+"\n")
                content.flush()
                os.fsync(content.fileno())
                publish(frontier, dict(last_index=index, pair=pair, output_sha256=digest(content_path),
                    content_model_sha256=model_digest, completed_decoder_calls=decoder_calls, failed_reads=failed))
                content_rows.append(row)
                endpoints.append(dict(features=receipt["features"], signals_q24=receipt["signals_q24"]))
                if index == 5:
                    cost, _ = client.close()
                    child_cpu += cost
                    checkpoint = json.loads(frontier.read_text())
                    if checkpoint["last_index"] != index or checkpoint["output_sha256"] != digest(content_path):
                        raise ValueError("completed content frontier mismatch")
                    adapter = ContentAdapter()
                    if adapter.setup["checkpoint_sha256"] != checkpoint["content_model_sha256"]:
                        raise ValueError("content model changed on restart")
                    client = Client(binary, model, root, checkpoint["pair"], log)
        finally:
            cost, _ = client.close()
            child_cpu += cost
    complete_cpu = time.process_time()-start_cpu+child_cpu
    complete_wall = time.perf_counter()-start_wall
    labels = json.loads((data / f"evaluator-labels-{seed}.json").read_text())
    correct = sum(row["status"] == "decoded" and row["observation"] == labels[row["index"]] for row in content_rows)
    result = dict(family=family, seed=seed, dense=dense, missing=missing, intervals=sequence,
        packet_read_attempts=len(content_rows), decoder_calls=decoder_calls, failed_reads=failed,
        correct=correct, scored=len(labels), accuracy=correct/len(labels), endpoints=endpoints,
        content=[{k: row[k] for k in ("index", "status", "observation", "logits", "payload_sha256") if k in row} for row in content_rows],
        complete_cpu_seconds=complete_cpu, complete_wall_seconds=complete_wall, child_cpu_seconds=child_cpu,
        native_durable_bytes=durable, content_bytes=content_path.stat().st_size,
        content_checkpoint_bytes=frontier.stat().st_size, restarts=1, content_model_sha256=model_digest)
    save(root / "RESULT.json", result)
    return result


def main(args):
    args.out.mkdir(parents=True, exist_ok=False)
    data = args.out / "data"
    data.mkdir()
    protocol = dict(schema="hcsn.native-content-cost.protocol.v1", seeds=[173,271,419,587],
        parameters=PARAMETERS, intervals=12, duration_micros=2_000_000, horizon_micros=750_000,
        dense_subdivisions=16, packet_length=32, decoded_per_endpoint=1,
        source_sha256=digest(Path(__file__)), native_binary_sha256=digest(args.binary),
        numeric_tolerance=2e-10, input_generation_seed=181031,
        content_source="Frozen FullHX marked-first-symbol memory model; no retraining or open-language claim",
        hypothesis="Omitting redundant control commits preserves endpoint outputs and reduces full measured lifecycle cost",
        strong_ordinary_baseline="Ordinary gates receive exactly the same event-aware public schedule",
        authority="DENY_ALL", production_activation=False)
    save(args.out / "PROTOCOL.json", protocol)
    for seed in protocol["seeds"]:
        rng = np.random.default_rng(9000+seed)
        schedule, labels = [], []
        for index in range(protocol["intervals"]):
            symbol = (index+seed) % 2
            filename = f"packet-{seed}-{index}.json"
            save(data / filename, packet(symbol, 181031+seed*100+index, length=32))
            labels.append(symbol)
            schedule.append(dict(driver=float(rng.uniform(-.9,.9)), duration_micros=2_000_000,
                horizon_micros=750_000, reset=index in (3,8), packet=filename))
        save(data / f"schedule-{seed}.json", schedule)
        save(data / f"evaluator-labels-{seed}.json", labels)
    save(args.out / "DATA_IDENTITY.json", {p.name: digest(p) for p in sorted(data.iterdir())})
    jobs = [(f,s,d,False) for f in FAMILIES for s in protocol["seeds"] for d in (False,True)]
    jobs += [(f,173,d,True) for f in FAMILIES for d in (False,True)]
    random.Random(821031).shuffle(jobs)
    rows = [run_one(args.binary,args.out,data,*job) for job in jobs]
    pairs = []
    for event in (r for r in rows if not r["dense"]):
        dense = next(r for r in rows if r["dense"] and all(r[k] == event[k] for k in ("family","seed","missing")))
        error = max(float(np.max(np.abs(np.array(a["features"])-b["features"]))) for a,b in zip(event["endpoints"],dense["endpoints"]))
        equal = event["content"] == dense["content"] and all(a["signals_q24"] == b["signals_q24"] for a,b in zip(event["endpoints"],dense["endpoints"]))
        pairs.append(dict(family=event["family"],seed=event["seed"],missing=event["missing"],
            outputs_equal=equal,feature_error=error,cpu_saved=dense["complete_cpu_seconds"]-event["complete_cpu_seconds"]))
    passed = all(p["outputs_equal"] and p["feature_error"] < 2e-10 for p in pairs)
    passed = passed and all(r["decoder_calls"] == (11 if r["missing"] else 12) and r["failed_reads"] == int(r["missing"]) for r in rows)
    means = {f+('/dense' if d else '/event'): {name: float(np.mean([r[name] for r in rows if r["family"]==f and r["dense"]==d and not r["missing"]])) for name in ("complete_cpu_seconds","complete_wall_seconds","accuracy")} for f in FAMILIES for d in (False,True)}
    save(args.out / "REPORT.json", dict(protocol=protocol, passed=passed, pairs=pairs, means=means,
        runs=[{k:v for k,v in row.items() if k not in ("endpoints","content")} for row in rows],
        intrinsic_analytic_advantage_established=False, open_content_quality_established=False,
        source_build_sha256=args.build_sha, source_sha256=digest(Path(__file__)),
        restart_scope="acknowledged completed effects only; no arbitrary-crash two-file atomicity claim",
        cost_scope="native startup, physics/query/readout, IPC, journal/witness/checkpoint, actual content reads/features/FullHX inference, output fsync, one model/native restart, shutdown",
        excluded_per_run="Shared input generation, evaluator scoring, experiment summary; external PROCESS receipt charges whole campaign",
        production_activation=False,authority="DENY_ALL"))
    print(json.dumps(dict(passed=passed,means=means)))
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--build-sha",required=True)
    raise SystemExit(0 if main(parser.parse_args()) else 1)
