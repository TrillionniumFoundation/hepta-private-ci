"""Controlled lifecycle probes over real files; no production or learning claim."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import tarfile
import tempfile
import time

import numpy as np

from diagnose import guard_action, read_archive, require
from models import Model
from operational_metrics import summarize
from qualify_families import tasks
from run import OPTIONS, compressed_jsonl, encode, macro
from skill_lifecycle import LifecycleDestination, SkillContract
from sqlite_destination import BudgetExhausted


SCHEDULES = ("running", "pause_resume", "expired", "no_repair")


def episode(task, arm, model, path, schedule):
    contract = SkillContract(
        task_id=task["id"],
        version=task["version"],
        goals_digest=hashlib.sha256(
            json.dumps(task["goals"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        deadline_ns=time.monotonic_ns()
        + (-1 if schedule == "expired" else 60_000_000_000),
        max_retries=0 if schedule == "no_repair" else 1,
    )
    destination = LifecycleDestination(path, task, contract)
    state = np.zeros(12) if model is not None and model.kind == "gru" else None
    decisions, selection_ns, overrides = [], 0, 0
    claimed = False
    try:
        if schedule == "pause_resume":
            destination.inspect()
            before = len(destination.owner.calls)
            destination.pause()
            destination.ensure()
            require(
                len(destination.owner.calls) == before, "paused skill contacted owner"
            )
            destination.resume()
        try:
            for _ in range(2 * destination.budget):
                if destination.state in ("DEADLINE", "RETRY_EXHAUSTED"):
                    destination.inspect()
                    claimed = bool(destination.view and destination.view["complete"])
                    break
                feature = encode(destination)
                started = time.perf_counter_ns()
                if model is None:
                    proposed = macro(destination)
                else:
                    choice, state = model.choose(feature, state)
                    proposed = OPTIONS[choice]
                selected, overridden = guard_action(destination, proposed)
                selection_ns += time.perf_counter_ns() - started
                overrides += int(overridden)
                decisions.append(
                    {"feature": feature, "proposed": proposed, "selected": selected}
                )
                if selected == "stop":
                    current = destination.inspect()
                    claimed = bool(current and current["complete"])
                    break
                getattr(destination, selected)()
        except BudgetExhausted:
            pass
        return {
            **destination.score(claimed),
            "task_id": task["id"],
            "arm": arm,
            "schedule": schedule,
            "selection_ns": selection_ns,
            "guard_overrides": overrides,
            "decisions": decisions,
            "contract": asdict(contract),
        }
    finally:
        destination.close()


def qualify(archive, output):
    require(not output.exists(), "output already exists")
    _, _, inputs = read_archive(archive)
    names = (
        "qualify_operational.py",
        "skill_lifecycle.py",
        "operational_metrics.py",
        "file_family.py",
        "models.py",
        "run.py",
        "diagnose.py",
        "qualify_families.py",
        "sqlite_destination.py",
    )
    sources = {
        n: hashlib.sha256((Path(__file__).parent / n).read_bytes()).hexdigest()
        for n in names
    }
    cohort = []
    for original in tasks(["filesystem"]):
        for schedule in SCHEDULES:
            cohort.append(
                ({**original, "id": original["id"] + "/" + schedule}, schedule)
            )
    output.mkdir(parents=True)
    frozen = {
        "tasks": cohort,
        "seeds": list(range(700, 708)),
        "arms": ["fixed", "head", "gru"],
        "source_sha256": sources,
        "archive_inputs_sha256": inputs,
        "deadline_window_ns": 60_000_000_000,
        "scope": "repeated controlled filesystem probes; same ACT2 observations",
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
        "base_probes": 16,
        "schedule_conditions": 64,
        "new_independent_real_tasks": 0,
        "training_performed": False,
    }
    (output / "FROZEN_MANIFEST.json").write_text(json.dumps(frozen, indent=2) + "\n")
    rows, started = [], time.perf_counter_ns()
    with tempfile.TemporaryDirectory(prefix="act3-operational-") as folder:
        work = Path(folder)
        try:
            for seed in frozen["seeds"]:
                models = {}
                for kind, label in (("head", "B3_head"), ("gru", "B4_gru")):
                    model = Model(kind, seed)
                    with np.load(
                        archive / f"{label}-seed-{seed}.npz", allow_pickle=False
                    ) as saved:
                        require(set(saved.files) == set(model.p), "model parameters")
                        for key, value in model.p.items():
                            require(
                                saved[key].shape == value.shape
                                and np.isfinite(saved[key]).all(),
                                "model values",
                            )
                            model.p[key] = saved[key].copy()
                    models[kind] = model
                for index, (task, schedule) in enumerate(cohort):
                    offset = (seed + index) % 3
                    arms = frozen["arms"][offset:] + frozen["arms"][:offset]
                    for arm in arms:
                        path = work / str(seed) / str(index) / arm
                        row = episode(task, arm, models.get(arm), path, schedule)
                        row.update(
                            seed=seed, destination_member=str(path.relative_to(work))
                        )
                        rows.append(row)
        finally:
            compressed_jsonl(output / "episodes.jsonl.gz", rows)
            with tarfile.open(output / "destination-bytes.tar.xz", "w:xz") as retained:
                retained.add(work, arcname="destinations")
            (output / "EXECUTION.json").write_text(
                json.dumps(
                    {
                        "recorded_episodes": len(rows),
                        "campaign_wall_ns": time.perf_counter_ns() - started,
                        "expected_episodes": len(cohort) * 8 * 3,
                        "production_adoption": False,
                        "status": "EXECUTION_RECORDED"
                        if len(rows) == len(cohort) * 8 * 3
                        else "PARTIAL_EXECUTION",
                    },
                    indent=2,
                )
                + "\n"
            )
    expected = {
        (task["id"], seed, arm)
        for task, _ in cohort
        for seed in frozen["seeds"]
        for arm in frozen["arms"]
    }
    observed = [(row["task_id"], row["seed"], row["arm"]) for row in rows]
    require(
        len(observed) == len(expected) and set(observed) == expected,
        "incomplete or duplicate panel",
    )
    require(
        all(
            hashlib.sha256((Path(__file__).parent / n).read_bytes()).hexdigest() == h
            for n, h in sources.items()
        ),
        "source drift",
    )
    read_archive(archive)
    result = summarize(rows)
    unsafe = any(
        r["false_success"]
        or r["duplicate_effects"]
        or (r["schedule"] == "expired" and r["effect_count"])
        for r in rows
    )
    result.update(
        production_adoption=False,
        learning_gain_qualified=False,
        fixed_reference_retained=True,
        new_independent_real_tasks=0,
        async_wait_qualified=False,
        cross_process_lifecycle_qualified=False,
        status="ENGINEERING_FAIL"
        if unsafe
        else "CONTROLLED_LIFECYCLE_PROBES_COMPLETED",
        base_probes=16,
        schedule_conditions=64,
        deadline_semantics="fence new mutations; allow reconciliation after expiry",
        measurement_window="owner initialization through score audit; excludes model load, close and archive",
        by_schedule={
            s: summarize([r for r in rows if r["schedule"] == s]) for s in SCHEDULES
        },
    )
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    require(
        not any(r["false_success"] or r["duplicate_effects"] for r in rows),
        "unsafe outcomes",
    )
    require(
        not any(r["effect_count"] for r in rows if r["schedule"] == "expired"),
        "expired dispatch",
    )
    print(json.dumps({"episodes": len(rows), "promotion": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    qualify(args.archive.resolve(), args.output.resolve())
