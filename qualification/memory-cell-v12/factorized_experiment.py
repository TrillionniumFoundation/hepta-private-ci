"""Address-factorization development study with real bounded source reads."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from corpus import build_corpus
from factorized import FactorizedAddress
from learned import canonical
from network import calibrate, select


def write(path, value):
    Path(path).write_bytes(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")


def serial_scores(engine, rows, mode):
    started, cpu = time.perf_counter(), time.process_time()
    scores = np.vstack([engine.score([row["text"]], mode)[0] for row in rows])
    return scores, dict(wall_seconds=time.perf_counter() - started,
                        cpu_seconds=time.process_time() - cpu, actual_model_or_index_calls=len(rows))


def read_sources(engine, scores, threshold, strategy):
    """Both plans spend at most two actual source reads; neither receives labels."""
    if strategy not in ("top2", "top1_twice"):
        raise ValueError("unknown read policy")
    chosen, receipt = [], []
    if strategy == "top2":
        plan = tuple(select(scores[None], engine.active, threshold, limit=2)[0])
        steps = [plan]
    else:
        # Fixed scores are reused, so this tests equal-budget staged execution,
        # not an extra claim of adaptive inference after observing source content.
        first = select(scores[None], engine.active, threshold, limit=1)[0]
        remaining = engine.active.copy()
        remaining[first] = False
        second = select(scores[None], remaining, 0., limit=1)[0] if first else []
        steps = [tuple(first), tuple(second)]
    for step, indices in enumerate(steps):
        for i in indices:
            if not engine.active[i] or i in chosen:
                raise ValueError("source not current or read twice")
            record = engine.records[i]
            body = record["text"].encode()
            receipt.append(dict(step=step, index=i, record_id=record["id"], source_id=record["source_id"],
                                version=record["version"], bytes=len(body),
                                body_sha256=hashlib.sha256(body).hexdigest()))
            chosen.append(i)
    return chosen, receipt


def evaluate(engine, rows, mode, strategy, threshold):
    scores, scoring = serial_scores(engine, rows, mode)
    started, cpu = time.perf_counter(), time.process_time()
    outcomes, raw, unknown, precision, traces = [], [], [], [], []
    reachable, scope_correct, reads, read_bytes = 0, 0, 0, 0
    arity = {}
    for row, score in zip(rows, scores, strict=True):
        target = [engine.lookup[key] for key in row["target_ids"]]
        chosen, receipt = read_sources(engine, score, threshold, strategy)
        raw_choices = select(score[None], engine.active, 0., limit=2)[0]
        successful = set(target).issubset(chosen) if target else not chosen
        raw_successful = set(target).issubset(raw_choices) if target else not raw_choices
        outcomes.append(int(successful))
        arity.setdefault(str(len(target)), []).append(int(successful))
        if target:
            raw.append(int(raw_successful))
            reachable += int(len(target) <= 2 and all(engine.active[i] for i in target))
            scope_correct += int(all(engine.records[i]["module"] == engine.resolve_module(row["text"]) for i in target))
            precision.append(len(set(target) & set(chosen)) / len(chosen) if chosen else 0.)
        else:
            unknown.append(int(not chosen))
        reads += len(receipt)
        read_bytes += sum(item["bytes"] for item in receipt)
        traces.append(dict(query_id=row["id"], target_indices=target, prediction_indices=chosen,
                           raw_top2=raw_choices, confidence=float(score.max()), success=int(successful),
                           module=engine.resolve_module(row["text"]), reads=receipt))
    known = sum(bool(row["target_ids"]) for row in rows)
    metrics = dict(queries=len(rows), known=known, unsupported=len(unknown),
                   success=float(np.mean(outcomes)),
                   known_accepted_correct=float(np.mean([t["success"] for t in traces if t["target_indices"]])) if known else None,
                   raw_known_top2=float(np.mean(raw)) if raw else None,
                   unsupported_rejection=float(np.mean(unknown)) if unknown else None,
                   known_evidence_precision=float(np.mean(precision)) if precision else None,
                   known_reachable_under_two_reads=reachable, known_literal_module_correct=scope_correct,
                   by_target_count={key: dict(count=len(values), success=float(np.mean(values))) for key, values in arity.items()},
                   actual_source_reads=reads, source_read_bytes=read_bytes, threshold=threshold,
                   scoring=scoring, read_wall_seconds=time.perf_counter() - started,
                   read_cpu_seconds=time.process_time() - cpu,
                   score_sha256=hashlib.sha256(scores.astype("<f4").tobytes()).hexdigest())
    return dict(mode=mode, strategy=strategy, metrics=metrics, trace=traces)


def run(repo, destination, protocol_path):
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    completed, failure = [], None
    try:
        protocol = json.loads(Path(protocol_path).read_text())
        source = Path(__file__).parent
        names = ["factorized.py", "factorized_experiment.py", "FACTOR_PROTOCOL.json", "categorical.py",
                 "learned.py", "corpus.py", "network.py"]
        identity = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}
        data = build_corpus(repo)
        write(output / "CORPUS.json", data)
        write(output / "FREEZE.json", dict(protocol=protocol, source_sha256=identity,
                    corpus_sha256=data["corpus_sha256"], scope="local pre-fit commitment; same-corpus development"))
        (output / "EXECUTED_SOURCE").mkdir()
        for name in names:
            (output / "EXECUTED_SOURCE" / name).write_bytes((source / name).read_bytes())
        for seed in protocol["seeds"]:
            for phase in (0, 1, 2):
                directory = output / f"seed-{seed}" / f"phase-{phase}"
                directory.mkdir(parents=True)
                history = [q for q in data["queries"] if (q["phase"] < phase and q["split"] != "calibration")
                           or (phase == 0 and q["phase"] == 0 and q["split"] == "train")]
                calibration = [q for q in data["queries"] if q["split"] == "calibration" and q["phase"] <= max(phase - 1, 0)]
                held = [q for q in data["queries"] if q["split"] == "test" and q["phase"] == phase]
                engine = FactorizedAddress(data["records"], phase, protocol["dimension"]).fit(
                    history, seed=seed + 100 * phase, hidden=protocol["hidden"], steps=protocol["steps"])
                with gzip.open(directory / "address-checkpoint.json.gz", "wb") as stream:
                    stream.write(canonical(engine.export()))
                with gzip.open(directory / "address-checkpoint.json.gz", "rb") as stream:
                    engine = FactorizedAddress.from_export(json.load(stream), data["records"])
                targets = [[engine.lookup[key] for key in row["target_ids"]] for row in calibration]
                thresholds, calibration_cost = {}, {}
                for mode in protocol["modes"]:
                    scores, cost = serial_scores(engine, calibration, mode)
                    thresholds[mode] = calibrate(scores, engine.active, targets, limit=2)
                    calibration_cost[mode] = cost
                    write(directory / f"calibration-{mode}.json", dict(query_ids=[q["id"] for q in calibration],
                          target_indices=targets, score_sha256=hashlib.sha256(scores.astype("<f4").tobytes()).hexdigest(),
                          threshold=thresholds[mode], costs=cost))
                write(directory / "PRE_TEST.json", dict(thresholds=thresholds, history_ids=[q["id"] for q in history],
                      calibration_ids=[q["id"] for q in calibration], future_labels_used_for_selection=False))
                order = [(mode, strategy) for mode in protocol["modes"] for strategy in protocol["read_policies"]]
                np.random.default_rng(seed + phase).shuffle(order)
                results = {}
                for mode, strategy in order:
                    result = evaluate(engine, held, mode, strategy, thresholds[mode])
                    write(directory / f"test-{mode}-{strategy}.json", result)
                    results[mode + "/" + strategy] = result["metrics"]
                for mode in protocol["modes"]:
                    a = json.loads((directory / f"test-{mode}-top2.json").read_text())
                    b = json.loads((directory / f"test-{mode}-top1_twice.json").read_text())
                    if [r["prediction_indices"] for r in a["trace"]] != [r["prediction_indices"] for r in b["trace"]]:
                        raise AssertionError("equal-score two-read policies disagree")
                    if a["metrics"]["actual_source_reads"] != b["metrics"]["actual_source_reads"]:
                        raise AssertionError("two-read budget accounting differs")
                phase_result = dict(seed=seed, phase=phase, active_records=len(engine.indices),
                    heading_classes=len(engine.headings), query_scope="future module curriculum" if phase else "in-phase diagnostic",
                    results=results, fit_and_shared_index_costs=engine.costs, calibration_costs=calibration_cost,
                    checkpoint_bytes=(directory / "address-checkpoint.json.gz").stat().st_size,
                    equal_budget_read_plans_equal=True)
                write(directory / "RESULT.json", phase_result)
                completed.append(phase_result)
                print(json.dumps(dict(seed=seed, phase=phase, known_correct={mode:results[mode + "/top2"]["known_accepted_correct"]
                                                                       for mode in protocol["modes"]})), flush=True)
        if {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names} != identity:
            raise RuntimeError("executed source changed during run")
        write(output / "SUMMARY.json", dict(schema="hepta.memory.factorized-results.v12", runs=completed,
                   corpus_sha256=data["corpus_sha256"], source_sha256=identity,
                   limits=protocol["limits"], source_metadata_is_shared_by_all_modes=True))
    except BaseException as error:
        failure = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        receipt = dict(schema="hepta.memory.factorized-execution.v12", completed_phases=len(completed),
                       failure=failure, wall_seconds=time.perf_counter() - start,
                       cpu_seconds=time.process_time() - cpu, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       retained_bytes_before_receipt=sum(p.stat().st_size for p in output.rglob("*") if p.is_file()))
        print(json.dumps(dict(execution_receipt=receipt)), flush=True)
        write(output / "EXECUTION_RECEIPT.json", receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("FACTOR_PROTOCOL.json"))
    args = parser.parse_args()
    run(args.repo, args.output, args.protocol)
