"""Execute the frozen MEM-3 mechanism pilot after candidate-retention evidence exists."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from actor import Reader, compose
from evaluate import evaluate
from fixture import ARMS, PHASES, SEEDS, encoded, fixture, metadata


def dump(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--first-experiment-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.fixture.read_text())
    if encoded(data) != encoded(fixture()):
        raise ValueError("fixture differs from the fixed registered generator")
    prior = args.first_experiment_evidence.read_bytes()
    if not prior:
        raise ValueError("candidate-retention evidence is empty")
    args.output.mkdir(parents=True, exist_ok=False)
    roster = [
        {"seed": s, "phase": p, "arm": a, "status": "not_started"}
        for s in SEEDS
        for p in PHASES
        for a in ARMS
    ]
    sources = list(Path(__file__).parent.glob("*.py")) + [
        Path(__file__).parents[1] / "memory_cell_mem1" / n
        for n in ("native.py", "environment.py")
    ]
    manifest = {
        "schema": "hepta-mem3-campaign-v1",
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "native_sha256": hashlib.sha256(args.native.read_bytes()).hexdigest(),
        "first_experiment_evidence_sha256": hashlib.sha256(prior).hexdigest(),
        "source_sha256": {
            str(p.relative_to(Path(__file__).parents[1])): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sources
        },
        "planned_trials": len(roster),
        "planned_tasks": len(roster) * len(data["tasks"]),
        "planned_transition_requests": 10,
        "python": sys.version,
        "scientific_qualification": "HOLD",
        "production_adoption": "NoUpdate",
    }
    dump(args.output / "manifest.json", manifest)
    dump(args.output / "roster.json", roster)
    for stream in data["streams"]:
        for stage in stream["stages"]:
            for arm in ARMS:
                record = next(
                    r
                    for r in roster
                    if (r["seed"], r["phase"], r["arm"])
                    == (stream["seed"], stage["phase"], arm)
                )
                record["status"] = "running"
                dump(args.output / "roster.json", roster)
                directory = (
                    args.output / f"seed-{stream['seed']}-{stage['phase']}-{arm}"
                )
                directory.mkdir()
                reader, started, rows = None, time.perf_counter_ns(), []
                task_roster = [
                    {"task_id": task["task_id"], "status": "not_started"}
                    for task in data["tasks"]
                ]
                dump(directory / "task-roster.json", task_roster)
                try:
                    # Retain the partially initialized owner if native training fails.
                    reader = object.__new__(Reader)
                    reader.cost, reader.memory, reader.trace = {}, None, None
                    Reader.__init__(
                        reader,
                        arm,
                        stage,
                        stream["features"],
                        stream["seed"],
                        args.native,
                        directory,
                    )
                    with (directory / "tasks.jsonl").open("w") as log:
                        for task, task_record in zip(data["tasks"], task_roster):
                            task_record["status"] = "running"
                            dump(directory / "task-roster.json", task_roster)
                            answer = compose(
                                reader, metadata(stage["facts"]), task, stage["tick"]
                            )
                            rows.append(answer)
                            log.write(json.dumps(answer, sort_keys=True) + "\n")
                            log.flush()
                            task_record["status"] = "completed"
                            dump(directory / "task-roster.json", task_roster)
                    if arm == "native" and stage["phase"] == "base":
                        diagnosis = reader.transition_diagnostic()
                        dump(directory / "transition.json", diagnosis)
                        if not diagnosis["checkpoint_unchanged"] or not all(
                            r["rejected"] for r in diagnosis["records"]
                        ):
                            raise ValueError("unexpected cross-cut native transition")
                    evaluation = evaluate(stage, data["tasks"], rows)
                    reader.close()
                    result = {
                        "seed": stream["seed"],
                        "phase": stage["phase"],
                        "arm": arm,
                        "evaluation": evaluation,
                        "cost": dict(reader.cost),
                        "wall_ns": time.perf_counter_ns() - started,
                    }
                    dump(directory / "result.json", result)
                    record["status"] = "completed"
                except Exception as error:
                    record.update(status="failed", error=repr(error))
                    if reader is not None:
                        reader.close()
                    for task_record in task_roster:
                        if task_record["status"] == "running":
                            task_record.update(status="failed", outcome="unknown")
                    dump(directory / "task-roster.json", task_roster)
                    dump(
                        directory / "failure.json",
                        {
                            **record,
                            "planned_task_count": len(task_roster),
                            "completed_task_ids": [
                                r["task_id"]
                                for r in task_roster
                                if r["status"] == "completed"
                            ],
                            "missing_task_ids": [
                                r["task_id"]
                                for r in task_roster
                                if r["status"] != "completed"
                            ],
                            "retained_task_count": len(rows),
                            "wall_ns": time.perf_counter_ns() - started,
                            "partial_cost": dict(reader.cost)
                            if reader is not None
                            else None,
                            "cost_scope": "observed client counters; unacknowledged native work remains UNKNOWN",
                        },
                    )
                finally:
                    if reader is not None:
                        reader.close()
                    dump(args.output / "roster.json", roster)
                print(json.dumps(record), flush=True)
    if any(r["status"] != "completed" for r in roster):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
