"""Frozen, replayable four-type tasks with strong generic replacement readers."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np

from factorized import FactorizedAddress
from learned import canonical
from network import calibrate
from typed import TYPES, TypedMemory, build_tasks, build_typed_corpus, sha


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def artifact(path, value):
    raw = canonical(value)
    path.write_bytes(gzip.compress(raw, mtime=0))
    return dict(path=path.name, bytes=path.stat().st_size, decoded_bytes=len(raw),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def evaluate(reader, tasks, scores, threshold, budget):
    traces, counts = [], dict(evidence_reads=0, read_bytes=0, parse_calls=0, parse_bytes=0,
                             event_rows_examined=0, wall_seconds=0.)
    for task, row in zip(tasks, scores, strict=True):
        output, receipt = reader.solve(task, row, threshold, budget)
        exact = output == task["expected"]
        addressed = set(task["target_ids"]).issubset(receipt["addressed"]) if task["target_ids"] else not receipt["addressed"]
        for key in counts:
            counts[key] += receipt[key]
        if receipt["evidence_reads"] > budget:
            raise AssertionError("evidence budget exceeded")
        traces.append(dict(query_id=task["id"], operation=task["operation"], cut=task["cut"],
                           answerable=task["expected"] is not None, success=exact,
                           address_coverage=addressed, output=output, receipt=receipt))
    def mean(rows, field="success"):
        return float(np.mean([row[field] for row in rows])) if rows else None
    metrics = dict(queries=len(traces), success=mean(traces),
        answerable_success=mean([row for row in traces if row["answerable"]]),
        unavailable_rejection=mean([row for row in traces if not row["answerable"]]),
        address_coverage=mean(traces, "address_coverage"),
        correct_given_address=mean([row for row in traces if row["address_coverage"]]),
        threshold=threshold, work=counts,
        by_operation={op: dict(count=sum(row["operation"] == op for row in traces),
                              success=mean([row for row in traces if row["operation"] == op]))
                      for op in ("lookup", "checklist", "compose")},
        by_procedure_state={str(cut): dict(count=sum(row["cut"] == cut and row["operation"] != "lookup" for row in traces),
                              success=mean([row for row in traces if row["cut"] == cut and row["operation"] != "lookup"]))
                            for cut in (0, 1, 2)})
    return dict(metrics=metrics, trace=traces, reader_resources=reader.costs)


def run(repo, output, protocol):
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    source = Path(__file__).parent
    names = ["typed.py", "typed_experiment.py", "typed_tests.py", "TYPED_PROTOCOL.json",
             "factorized.py", "learned.py", "categorical.py", "corpus.py", "network.py"]
    identities = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}
    corpus = build_typed_corpus(repo)
    data = build_tasks(corpus)
    write(output / "CORPUS.json", corpus)
    write(output / "TASKS.json", data)
    write(output / "FREEZE.json", dict(protocol=protocol, source_sha256=identities,
        corpus_sha256=corpus["corpus_sha256"], tasks_sha256=sha(data), commitment="local before fitting",
        runtime=dict(python=sys.version, numpy=np.__version__, platform=platform.platform())))
    (output / "EXECUTED_SOURCE").mkdir()
    for name in names:
        (output / "EXECUTED_SOURCE" / name).write_bytes((source / name).read_bytes())
    for row in corpus["provenance"]:
        destination = output / "sources" / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repo / row["path"]).read_bytes())
    records, tasks = corpus["records"], data["tasks"]
    lookup = {row["id"]: i for i, row in enumerate(records)}
    arms = {"full_typed": ("learned", TYPES),
            **{"without_" + kind: ("bm25" if kind == "meta" else "learned", TYPES - {kind}) for kind in sorted(TYPES)},
            "bm25_generic": ("bm25", frozenset()), "history_generic": ("history", frozenset()),
            "single_generic": ("single", frozenset())}
    runs = []
    for seed in protocol["seeds"]:
        for phase in (0, 1, 2):
            directory = output / f"seed-{seed}" / f"phase-{phase}"
            directory.mkdir(parents=True)
            history = [row for row in corpus["queries"] + tasks
                       if (row["phase"] < phase and row["split"] != "calibration")
                       or (phase == 0 and row["phase"] == 0 and row["split"] == "train")]
            calibration = [row for row in tasks if row["split"] == "calibration" and row["phase"] <= max(phase - 1, 0)]
            testing = [row for row in tasks if row["split"] == "test" and row["phase"] == phase]
            # The address learner receives only text and source labels, never
            # task answers, procedural state, or a held query's type/target.
            address_history = [{key: row[key] for key in ("id", "text", "target_ids")} for row in history]
            engine = FactorizedAddress(records, phase, protocol["dimension"]).fit(address_history,
                seed=seed, hidden=protocol["hidden"], steps=protocol["steps"])
            model_artifact = artifact(directory / "address.json.gz", engine.export())
            engine = FactorizedAddress.from_export(json.loads(gzip.decompress((directory / "address.json.gz").read_bytes())), records)
            thresholds, address_times, scores = {}, {}, {}
            targets = [[lookup[key] for key in row["target_ids"]] for row in calibration]
            for mode in ("learned", "bm25", "history", "single"):
                start = time.perf_counter()
                past = engine.score([row["text"] for row in calibration], mode)
                thresholds[mode] = calibrate(past, engine.active, targets, protocol["evidence_limit"])
                address_times[mode] = dict(calibration_seconds=time.perf_counter() - start)
            write(directory / "PRE_TEST.json", dict(thresholds=thresholds, history_ids=[row["id"] for row in history],
                calibration_ids=[row["id"] for row in calibration], address_artifact=model_artifact,
                training_receipts=engine.costs["models"], future_labels_used=False))
            for mode in thresholds:
                start = time.perf_counter()
                scores[mode] = engine.score([row["text"] for row in testing], mode)
                address_times[mode]["test_address_seconds"] = time.perf_counter() - start
            results, trace_by_arm = {}, {}
            for name, (mode, enabled) in arms.items():
                reader = TypedMemory(records, data["events"], enabled, engine.active)
                result = evaluate(reader, testing, scores[mode], thresholds[mode], protocol["evidence_limit"])
                result["address_runtime"] = address_times[mode]
                result["address_mode"] = mode
                result["enabled_types"] = sorted(enabled)
                write(directory / f"test-{name}.json", result)
                results[name] = {key: value for key, value in result.items() if key != "trace"}
                trace_by_arm[name] = result["trace"]
            pairs = {}
            for name in arms:
                if name == "full_typed":
                    continue
                differences = [int(a["success"]) - int(b["success"])
                               for a, b in zip(trace_by_arm["full_typed"], trace_by_arm[name], strict=True)]
                pairs[name] = dict(full_minus_control=float(np.mean(differences)),
                                   full_only=sum(value == 1 for value in differences),
                                   control_only=sum(value == -1 for value in differences), count=len(differences))
            result = dict(seed=seed, phase=phase, test_queries=len(testing), results=results,
                          paired= pairs, shared_address_resources=engine.costs, address_artifact=model_artifact,
                          scope="initial within-phase diagnostic" if phase == 0 else "future document-arrival tasks")
            write(directory / "RESULT.json", result)
            runs.append(result)
            print(json.dumps(dict(seed=seed, phase=phase, success={name: value["metrics"]["success"]
                                                                 for name, value in results.items()})), flush=True)
    after = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in identities}
    if after != identities:
        raise RuntimeError("executed sources changed during typed experiment")
    result = dict(schema="hepta.memory.typed-results.v12", runs=runs, source_identity=identities,
        corpus_sha256=corpus["corpus_sha256"], tasks_sha256=sha(data),
        documents=len(corpus["provenance"]), records=len(records), tasks=len(tasks),
        real_procedure_blocks=len(data["procedure_source_spans"]),
        wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        evidence_bytes_before_summary=sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        limitations=data["limitations"] + [protocol["interpretation"],
            "All raw sources retained; typed cache timings do not establish a general capability advantage."])
    write(output / "SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("TYPED_PROTOCOL.json"))
    args = parser.parse_args()
    try:
        run(args.repo, args.output, json.loads(args.protocol.read_text()))
    except Exception as error:
        if args.output.is_dir():
            write(args.output / "FAILED.json", dict(type=type(error).__name__, error=str(error)))
        raise
