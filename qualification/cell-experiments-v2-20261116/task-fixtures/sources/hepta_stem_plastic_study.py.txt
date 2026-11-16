"""Pre-action differentiation pilot on frozen retained CORD experience.

Only the initial observation is visible. Task IDs route the same three requested
ROI outcomes in every arm. Reused development sources never become confirmation.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .lifecycle import Budget, CellOwner, Partition
from .plastic_bank import ARMS, PlasticBank
from .semantic import CallableFeatureBackend, SemanticBinding, SemanticCell
from .semantic import SharedSemanticPool, _digest
from .semantic_component import SemanticComponent, semantic_bundle


TASKS = ("upper", "middle", "lower")


def write(root, name, value):
    with (root / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def event(root, value):
    with (root / "EVENTS.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def prepare(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data["schema"] != "hepta.cell.cord-retained-replay.v1":
        raise ValueError("frozen retained CORD dataset required")
    rows = data["records"]
    if (
        len(rows) != 96
        or data["feature_dim"] != 64
        or data.get("fresh_confirmation") != 0
        or data.get("source_independence_verified") is not False
    ):
        raise ValueError("the frozen 32-source, 96-row protocol is required")
    seen, groups, documents = set(), {"train": set(), "dev": set()}, {}
    for row in rows:
        key = row["source_group"], row["candidate_id"]
        if key in seen or key[1] not in TASKS or row["split"] not in groups:
            raise ValueError("duplicate/unknown source route")
        seen.add(key)
        groups[row["split"]].add(key[0])
        if documents.setdefault(row["document_sha256"], key[0]) != key[0]:
            raise ValueError("document reused under a different source group")
        if row["target"] not in (0, 1):
            raise ValueError("unknown outcomes cannot be replaced by zero")
    if (
        len(groups["train"]) != 24
        or len(groups["dev"]) != 8
        or groups["train"] & groups["dev"]
    ):
        raise ValueError("source groups differ from the fixed protocol")
    roster = {
        (source, task)
        for split in groups.values()
        for source in split
        for task in TASKS
    }
    if seen != roster:
        raise ValueError("incomplete planned routes")
    lookup = {(r["source_group"], r["candidate_id"]): r for r in rows}
    for source in groups["train"] | groups["dev"]:
        bindings = [
            [
                lookup[(source, task)][k]
                for k in ("initial_latent", "document_sha256", "feature_profile_sha256")
            ]
            + [lookup[(source, task)]["receipt_sha256s"][0]]
            for task in TASKS
        ]
        if bindings[0] != bindings[1] or bindings[0] != bindings[2]:
            raise ValueError("task routes received different initial information")
    train = np.asarray(
        [lookup[(s, TASKS[0])]["initial_latent"] for s in sorted(groups["train"])]
    )
    mean, scale = train.mean(axis=0), np.maximum(train.std(axis=0), 1e-6)
    panels = {}
    for split in groups:
        for task in TASKS:
            records = [lookup[(s, task)] for s in sorted(groups[split])]
            x = np.asarray([r["initial_latent"] for r in records], dtype=np.float64)
            if x.shape != (len(records), 64) or not np.isfinite(x).all():
                raise ValueError("invalid retained initial feature vector")
            panels[(split, task)] = (
                (x - mean) / scale,
                np.asarray([[r["target"]] for r in records], dtype=np.float64),
            )
    return panels, dict(
        dataset_sha256=hashlib.sha256(raw).hexdigest(),
        mean=mean.tolist(),
        scale=scale.tolist(),
        source_groups={k: sorted(v) for k, v in groups.items()},
    )


def metrics(prediction, targets):
    probability = np.clip(prediction, 0, 1)
    return dict(
        raw_mse=float(np.mean((prediction - targets) ** 2)),
        brier=float(np.mean((probability - targets) ** 2)),
        correct=int(np.sum((probability >= 0.5) == targets)),
        source_groups=len(targets),
        positives=int(targets.sum()),
    )


def serve(
    owner, bank, task, features, identity, run, *, create=True, request_id="predict"
):
    pool = SharedSemanticPool()
    pin = _digest("retained-CORD-feature-cache-v1", identity)
    binding = SemanticBinding(*(pin for _ in range(5)))
    pool.register_backend(
        CallableFeatureBackend(binding, 64, lambda x: np.asarray(x), lambda: pin)
    )
    cell = SemanticCell(task, binding, bank.head(task), bank.objective)
    component = SemanticComponent(pool, cell, semantic_bundle(cell, bank.digest))
    partition = Partition("retained-CORD-development", identity, task, run)
    if create:
        owner.create(
            partition,
            component,
            budget=Budget(max_elapsed_ms=60000, max_work_units=1_000_000),
            total_work_units=1_000_000_000,
        )
    receipt = owner.step(
        partition, component, request_id, {"inputs": features.tolist()}
    )
    if receipt["status"] != "committed":
        raise RuntimeError("candidate serving did not commit")
    return np.asarray(receipt["output"]["logits"]), receipt


def cold(root):
    root = Path(root)
    plan = json.loads((root / "COLD.json").read_text())
    bank, cursor = PlasticBank.restore(
        root / "candidate.npz",
        expected_sha256=plan["checkpoint"],
        plan_sha256=plan["plan_sha256"],
    )
    owner = CellOwner(root / "owner.sqlite")
    try:
        result = {}
        for task in TASKS:
            prediction, receipt = serve(
                owner,
                bank,
                task,
                np.asarray(plan["features"][task]),
                plan["identity"],
                "final",
                create=False,
            )
            fresh, fresh_receipt = serve(
                owner,
                bank,
                task,
                np.asarray(plan["features"][task]),
                plan["identity"],
                "final",
                create=False,
                request_id="cold-next-prediction",
            )
            result[task] = dict(
                predictions=prediction.tolist(),
                receipt=receipt,
                fresh_predictions=fresh.tolist(),
                fresh_receipt=fresh_receipt,
            )
        return dict(cursor=cursor, digest=bank.digest, tasks=result)
    finally:
        owner.close()


def run(dataset, output, *, seeds=(1101, 1102, 1103), ranks=(2, 4), updates=40):
    if (
        not 1 <= len(seeds) <= 8
        or len(set(seeds)) != len(seeds)
        or any(type(s) is not int or not 0 <= s < 2**64 for s in seeds)
    ):
        raise ValueError("bounded distinct seeds required")
    if (
        not 1 <= len(ranks) <= 4
        or any(type(r) is not int or not 1 <= r <= 32 for r in ranks)
        or type(updates) is not int
        or not 1 <= updates <= 60
    ):
        raise ValueError("bounded budget roster required")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    panels, provenance = prepare(dataset)
    plan = dict(
        schema="hepta.cell.shared-plastic-plan.v1",
        seeds=list(seeds),
        private_ranks=list(ranks),
        updates_per_task=updates,
        learning_rate=0.03,
        curriculum=list(TASKS) * 2,
        normalization=provenance,
        information="same pre-action initial64 and named task route; no later ROI features",
        matching="nearest total deployed parameter count; active rank, plastic count and MAC differ",
        source_file_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        development_only=True,
        fresh_confirmation_sources=0,
        promotion="NoUpdate",
        source_independence_verified=False,
    )
    write(root, "PLAN.json", plan)
    plan_sha = hashlib.sha256((root / "PLAN.json").read_bytes()).hexdigest()
    baselines = {}
    for task in TASKS:
        baseline_start = time.perf_counter_ns()
        tx, ty = panels[("train", task)]
        dx, dy = panels[("dev", task)]
        nearest = np.argmin(np.sum((dx[:, None] - tx[None]) ** 2, axis=2), axis=1)
        baselines[task] = dict(
            constant_zero=metrics(np.zeros_like(dy), dy),
            train_prevalence=metrics(np.full_like(dy, ty.mean()), dy),
            exact_nearest_record=metrics(ty[nearest], dy),
            retrieval_storage_bytes=tx.nbytes + ty.nbytes,
            three_baselines_wall_ns=time.perf_counter_ns() - baseline_start,
        )
    write(root, "BASELINES.json", baselines)
    outcomes = []
    for seed in seeds:
        for private_rank in ranks:
            target = 3 * ((64 + 1) * private_rank + 1)
            shared_rank = min(range(1, 129), key=lambda r: abs(67 * r + 3 - target))
            for arm in ARMS:
                name = f"{seed}-r{private_rank}-{arm}"
                directory = root / name
                directory.mkdir()
                started, started_cpu = time.perf_counter_ns(), time.process_time_ns()
                bank = PlasticBank(
                    arm,
                    64,
                    private_rank if arm == "independent" else shared_rank,
                    TASKS,
                    seed,
                )
                owner = CellOwner(directory / "owner.sqlite")
                curves, fits, changes, last = [], [], [], {}
                try:
                    for phase, task in enumerate(plan["curriculum"]):
                        old = {
                            t: bank.head(t).predict(panels[("dev", t)][0])
                            for t in TASKS
                        }
                        for step in range(0, updates, 10):
                            if arm != "frozen":
                                event(
                                    root,
                                    dict(
                                        status="started",
                                        run=name,
                                        phase=phase,
                                        update=step,
                                    ),
                                )
                                try:
                                    candidate, receipt = bank.propose(
                                        task,
                                        *panels[("train", task)],
                                        updates=min(10, updates - step),
                                        learning_rate=0.03,
                                    )
                                except Exception as error:
                                    event(
                                        root,
                                        dict(
                                            run=name,
                                            phase=phase,
                                            training=getattr(
                                                error,
                                                "receipt",
                                                {
                                                    "status": "failed",
                                                    "error": str(error),
                                                },
                                            ),
                                        ),
                                    )
                                    raise
                                event(
                                    root, dict(run=name, phase=phase, training=receipt)
                                )
                                fits.append(receipt)
                                bank = candidate
                            for measured in TASKS:
                                x, y = panels[("dev", measured)]
                                prediction, receipt = serve(
                                    owner,
                                    bank,
                                    measured,
                                    x,
                                    provenance["dataset_sha256"],
                                    f"{phase}:{step}",
                                )
                                curves.append(
                                    dict(
                                        phase=phase,
                                        trained_task=task,
                                        updates=step + min(10, updates - step),
                                        task=measured,
                                        predictions=prediction.tolist(),
                                        metrics=metrics(prediction, y),
                                        receipt=receipt,
                                    )
                                )
                        changes.append(
                            dict(
                                phase=phase,
                                trained_task=task,
                                other_task_max_change={
                                    t: float(
                                        np.max(
                                            np.abs(
                                                bank.head(t).predict(
                                                    panels[("dev", t)][0]
                                                )
                                                - old[t]
                                            )
                                        )
                                    )
                                    for t in TASKS
                                    if t != task
                                },
                            )
                        )
                    for task in TASKS:
                        prediction, receipt = serve(
                            owner,
                            bank,
                            task,
                            panels[("dev", task)][0],
                            provenance["dataset_sha256"],
                            "final",
                        )
                        last[task] = dict(
                            predictions=prediction.tolist(), receipt=receipt
                        )
                    checkpoint = bank.checkpoint(
                        directory / "candidate.npz",
                        cursor=len(plan["curriculum"]),
                        plan_sha256=plan_sha,
                    )
                    write(
                        directory,
                        "COLD.json",
                        dict(
                            checkpoint=checkpoint,
                            plan_sha256=plan_sha,
                            identity=provenance["dataset_sha256"],
                            features={t: panels[("dev", t)][0].tolist() for t in TASKS},
                        ),
                    )
                finally:
                    owner.close()
                cold_start = time.perf_counter_ns()
                process = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "hepta_cells.stem_plastic_study",
                        "--cold",
                        str(directory.resolve()),
                    ],
                    cwd=Path(__file__).parents[1],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                write(
                    directory,
                    "COLD_PROCESS.json",
                    dict(
                        returncode=process.returncode,
                        stdout=process.stdout,
                        stderr=process.stderr,
                        wall_ns=time.perf_counter_ns() - cold_start,
                    ),
                )
                if process.returncode != 0:
                    raise RuntimeError("cold process failed; original output retained")
                readback = json.loads(process.stdout)
                replay = {
                    t: {k: readback["tasks"][t][k] for k in ("predictions", "receipt")}
                    for t in TASKS
                }
                if dict(
                    cursor=readback["cursor"], digest=readback["digest"], tasks=replay
                ) != dict(cursor=6, digest=bank.digest, tasks=last):
                    raise RuntimeError("cold owner receipt or prediction differs")
                if any(
                    readback["tasks"][t]["fresh_predictions"] != last[t]["predictions"]
                    or readback["tasks"][t]["fresh_receipt"] == last[t]["receipt"]
                    for t in TASKS
                ):
                    raise RuntimeError(
                        "fresh post-recovery inference differs or did not execute"
                    )
                report = dict(
                    run=name,
                    config=bank.config,
                    resources=bank.resources(),
                    phase_interference=changes,
                    learning_curves=curves,
                    training=fits,
                    checkpoint=checkpoint,
                    cold_process_equal=True,
                    fresh_post_recovery_inference_equal=True,
                    wall_ns=time.perf_counter_ns() - started,
                    process_cpu_ns=time.process_time_ns() - started_cpu,
                    process_cpu_excludes_cold_child=True,
                )
                write(directory, "RESULT.json", report)
                outcomes.append(
                    dict(
                        run=name,
                        config=bank.config,
                        resources=bank.resources(),
                        final_brier=float(
                            np.mean(
                                [
                                    metrics(
                                        np.asarray(last[t]["predictions"]),
                                        panels[("dev", t)][1],
                                    )["brier"]
                                    for t in TASKS
                                ]
                            )
                        ),
                        updates=sum(r["completed_updates"] for r in fits),
                        forward_mac=sum(r["forward_mac"] for r in fits),
                        gradient_mac=sum(r["gradient_mac"] for r in fits),
                        wall_ns=report["wall_ns"],
                        cold_process_equal=True,
                    )
                )
    result = dict(
        schema="hepta.cell.shared-plastic-result.v1",
        status="RESEARCH_ONLY_HOLD",
        outcomes=outcomes,
        source_groups={"train": 24, "development": 8},
        fresh_confirmation_sources=0,
        ordinary_daemon_adopt=0,
        wall_ns=time.perf_counter_ns() - wall,
        process_cpu_ns=time.process_time_ns() - cpu,
        cost_scope="current import, normalization, all model creation, training, serving, IO and cold subprocess wall; historical acquisition separate; energy/peak RAM unknown",
        promotion="NoUpdate",
    )
    write(root, "RESULT.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset")
    parser.add_argument("--output")
    parser.add_argument("--cold")
    arguments = parser.parse_args()
    print(
        json.dumps(
            cold(arguments.cold)
            if arguments.cold
            else run(arguments.dataset, arguments.output),
            allow_nan=False,
        )
    )
