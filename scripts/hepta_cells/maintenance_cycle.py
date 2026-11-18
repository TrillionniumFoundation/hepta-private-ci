"""Controlled-fixture MEM/PRED A/B/C learning; optional exact native HIA bridge.

Same generated syntax templates and fixed optimizer schedule as the original
Python pilot. Neither mode qualifies real repository work or ordinary adoption.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from .component_types import digest
from .lifecycle import Budget, CellOwner, Partition, Qualification
from .temporal import TemporalConfig, TemporalKernel
from .maintenance_tasks import (
    ARMS,
    UPDATES,
    WALL_BUDGET_SECONDS,
    Compiler,
    child_cpu_seconds,
    cold_task,
    freeze_sources,
    fixtures,
    observations,
    repair,
    save,
    sources,
)
from .maintenance_semantics import split_binding
from .maintenance_serving import serve, serve_diagnostic, recover, measure_window
from .maintenance_metrics import summarize_tasks, summarize_decisions
from .maintenance_execution import (
    RuntimeBinding,
    bundle,
    freeze_native,
    freeze_runtime_pins,
    numeric_identity,
)


def cost_summary(windows, report):
    all_windows = [*windows, *(
        row for value in report.values()
        for row in value["cold"].get("cost_windows", [])
    )]
    groups = {}
    for row in all_windows:
        if row["stage"] == "task":
            key = "/".join(row[name] for name in ("cell", "phase", "arm"))
            groups.setdefault(key, []).append(row)
    return dict(
        windows=all_windows,
        task_latency={key: summarize_tasks(rows, scope=rows[0]["scope"])
                      for key, rows in sorted(groups.items())},
        decisions=summarize_decisions([value["decision"] for value in report.values()]),
        aggregation="windows are inclusive and may nest; never add stage, task, child and outer windows",
        shared_diagnostics="A acquisition and B original diagnostics are recorded once; A/B/retention per-arm windows exclude them",
        memory_scope="process-lifetime high-water marks only; campaign process-tree peak remains unknown",
        full_system_cost_known=False,
    )


def run(output, *, native_build_record=None, runtime_pins=None, semantic=False):
    started, cpu_started = time.perf_counter(), time.process_time()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    panels, frozen_sources = fixtures(semantic=semantic), sources()
    freeze_sources(root, frozen_sources)
    native = freeze_native(root, native_build_record)
    pins = freeze_runtime_pins(root, runtime_pins)
    numeric = numeric_identity()
    plan = dict(
        schema="hepta.semantic-maintenance-cycle.v1" if semantic else "hepta.controlled-maintenance-cycle.v1",
        parent_pid=os.getpid(),
        panels=panels,
        source_sha256=frozen_sources,
        seed=7641,
        hidden_dim=4,
        optimizer="Adam",
        learning_rate=0.003,
        updates=UPDATES,
        wall_budget_seconds=WALL_BUDGET_SECONDS,
        arms=ARMS,
        selection="B candidate success strictly exceeds every baseline; A retention not worse than frozen",
        fixture_only=True,
        independent_real_sources=0,
        ordinary_daemon_qualification=False,
        controls="frozen/no_learning intentionally identical; no_memory resets between observations; deterministic reads CPython diagnostics",
        fairness="same programs and nominal limits; PRED scores four actions, MEM one four-way head; actual work recorded, not matched compute",
        cold_scope="new inference request on restored final C state, not a new independent task",
        evaluation="CPython compile success only; no program execution or semantic/test-suite guarantee",
        python=sys.version,
        numpy=np.__version__,
        native=native,
        runtime_pins=pins,
        numeric=numeric,
        device=dict(
            machine=platform.machine(),
            processor=platform.processor(),
            platform=platform.platform(),
        ),
    )
    if semantic:
        plan.update(
            evaluation="CPython compile and isolated function results against frozen input/output checks",
            cold_scope="restore original state and logits, then run a new D-cold task with semantic checks in the cold process",
            task_contracts=split_binding({**panels, "D-cold": [cold_task()]}),
            cold_task=cold_task(),
            split_scope="exact source bytes and task IDs are disjoint; generated syntax families overlap",
            code_execution_scope="controlled generated functions; no ordinary repository distribution or OS sandbox claim",
        )
    plan_hash = save(root / "PLAN.json", plan)
    runtime = RuntimeBinding(root, plan_hash, frozen_sources, numeric, native, pins)
    compiler, report = Compiler(root, started, semantic=semantic), {}
    windows = []
    try:
        observed, episodes, labels = {}, {}, {}
        for task in panels["A"]:
            with measure_window(
                windows, "data_acquisition", "shared A diagnostic, four repair outcomes and encoding",
                phase="A", task_id=task["id"],
                diagnostic_scope="once across both cells and all arms; not charged again per arm",
            ):
                original = compiler.check(task, task["source"], "A", "observation")
                if original["success"]:
                    raise ValueError("fixture unexpectedly valid before repair")
                observed[task["id"]], episodes[task["id"]] = (
                    original,
                    observations(task, original),
                )
                labels[task["id"]] = [
                    compiler.check(
                        task, repair(task["source"], action), "A", "acquisition"
                    )["success"]
                    for action in range(4)
                ]
                if sum(labels[task["id"]]) != 1:
                    raise ValueError(
                        "training task does not have one observed successful repair"
                    )
        save(
            root / "A_DATA.json",
            dict(
                observations=observed,
                episodes={k: v.tolist() for k, v in episodes.items()},
                labels=labels,
            ),
        )
        for cell in ("memory", "predictor"):
            directory = root / cell
            directory.mkdir()
            kernel = TemporalKernel(
                cell,
                TemporalConfig(
                    13,
                    4 if cell == "predictor" else 1,
                    2 if cell == "predictor" else 4,
                    hidden_dim=4,
                    seed=7641,
                ),
            )
            parent_bundle = bundle(kernel, plan_hash)
            owner = CellOwner(directory / "owner.sqlite")
            parent, parent_manifest = runtime.component(
                owner, kernel, parent_bundle, "active"
            )
            active = Partition("controlled-fixture", "active", cell, "active")
            owner.create(
                active,
                parent,
                budget=Budget(max_work_units=100000, max_elapsed_ms=10000),
                total_work_units=100000000,
            )
            try:
                parent_hash = kernel.checkpoint(
                    directory / "parent.npz", parent.initial_state()
                )
                a_served, batch, actions, targets = [], [], [], []
                for task in panels["A"]:
                    with measure_window(
                        windows, "task", "Cell owner, inference, repair and compile/semantic check",
                        phase="A", cell=cell, arm="active", task_id=task["id"],
                        diagnostic_scope="excludes earlier shared A diagnostic and label acquisition",
                    ) as task_cost:
                        use = serve(
                            owner,
                            kernel,
                            parent_bundle,
                            task,
                            episodes[task["id"]],
                            "active",
                            runtime=runtime,
                            active=True,
                        )
                        use["outcome"] = compiler.check(
                            task,
                            repair(task["source"], use["action"]),
                            "A",
                            cell + "-active",
                        )
                    use["task_cost"] = task_cost
                    a_served.append(use)
                    for action in range(4) if cell == "predictor" else (0,):
                        batch.append(episodes[task["id"]])
                        actions.append(
                            np.eye(4)[action] if cell == "predictor" else [0.0]
                        )
                        targets.append(
                            np.eye(2, dtype=bool)[int(labels[task["id"]][action])]
                            if cell == "predictor"
                            else labels[task["id"]]
                        )
                save(directory / "A_SERVED.json", a_served)
                with (directory / "A_TRAINING.npz").open("xb") as stream:
                    np.savez(
                        stream,
                        episodes=np.asarray(batch),
                        actions=np.asarray(actions),
                        allowed=np.asarray(targets, dtype=bool),
                    )
                with measure_window(
                    windows, "training", "isolated candidate copy and Adam fitting",
                    cell=cell, preparation_scope="A acquisition and dataset serialization are outside this window",
                ):
                    candidate, training = kernel.train_candidate(
                        batch,
                        actions,
                        np.asarray(targets, dtype=bool),
                        updates=UPDATES,
                        lr=0.003,
                    )
                save(directory / "TRAINING.json", training)
                candidate_bundle = parent_bundle.successor(
                    cell + "-candidate",
                    {
                        **parent_bundle.components,
                        "base": candidate.kernel_sha256,
                        "heads": candidate.heads_sha256,
                    },
                    training["data_sha256"],
                    digest(["Adam", UPDATES, 0.003]),
                    plan_hash,
                )
                candidate_hash = candidate.checkpoint(
                    directory / "candidate.npz", candidate.initial_state("active")
                )
                with measure_window(
                    windows, "validation", "B and A-retention evaluation with all arms and persisted evaluation",
                    cell=cell,
                ):
                    results = {}
                    for phase in ("B", "A-retention"):
                        phase_results = {
                            arm: []
                            for arm in (ARMS if phase == "B" else ("frozen", "candidate"))
                        }
                        for task in panels["B" if phase == "B" else "A"]:
                            if task["id"] not in episodes:
                                with measure_window(
                                    windows, "shared_diagnostic", "original B diagnostic and encoding shared across all cells/arms",
                                    phase=phase, task_id=task["id"],
                                ):
                                    original = compiler.check(
                                        task, task["source"], phase, "observation"
                                    )
                                    observed[task["id"]], episodes[task["id"]] = (
                                        original,
                                        observations(task, original),
                                    )
                            for arm, outcomes in phase_results.items():
                                with measure_window(
                                    windows, "task", "Cell owner, inference, repair and compile/semantic check",
                                    phase=phase, cell=cell, arm=arm, task_id=task["id"],
                                    diagnostic_scope="excludes shared original diagnostic and encoding",
                                ) as task_cost:
                                    if arm == "deterministic":
                                        use = serve_diagnostic(
                                            owner,
                                            cell,
                                            task,
                                            observed[task["id"]]["error"],
                                            runtime,
                                        )
                                    else:
                                        trained = arm in ("candidate", "no_memory")
                                        use = serve(
                                            owner,
                                            candidate if trained else kernel,
                                            candidate_bundle if trained else parent_bundle,
                                            task,
                                            episodes[task["id"]],
                                            arm,
                                            runtime=runtime,
                                        )
                                    use["outcome"] = compiler.check(
                                        task,
                                        repair(task["source"], use["action"]),
                                        phase,
                                        cell + "-" + arm,
                                    )
                                use["task_cost"] = task_cost
                                outcomes.append(use)
                        results[phase] = phase_results
                    evaluation_hash = save(directory / "EVALUATION.json", results)
                with measure_window(
                    windows, "selection_and_switch", "fixed gate, Adopt or NoUpdate, active-version readback and persisted decision",
                    cell=cell,
                ) as decision_cost:
                    counts = {
                        arm: sum(row["outcome"]["success"] for row in rows)
                        for arm, rows in results["B"].items()
                    }
                    retained = {
                        arm: sum(row["outcome"]["success"] for row in rows)
                        for arm, rows in results["A-retention"].items()
                    }
                    admitted = (
                        all(
                            counts["candidate"] > counts[arm]
                            for arm in ("frozen", "no_learning", "deterministic")
                        )
                        and retained["candidate"] >= retained["frozen"]
                    )
                    target, candidate_manifest = runtime.component(
                        owner, candidate, candidate_bundle, "active"
                    )
                    if (
                        candidate_manifest == parent_manifest
                        or target.identity == parent.identity
                    ):
                        raise ValueError("trained candidate reused its parent's identity")
                    qualification = Qualification(
                        parent.identity.digest, target.identity.digest,
                        evaluation_hash if semantic else plan_hash,
                    )
                    decision = dict(
                        decision="Adopt" if admitted else "NoUpdate",
                        B_successes=counts,
                        denominator=8,
                        A_retention=retained,
                        reason="predeclared strict baseline and retention gates"
                        if admitted
                        else "candidate failed one or more predeclared baseline/retention gates",
                        candidate_weights_sha256=candidate.weights_sha256,
                        parent_weights_sha256=kernel.weights_sha256,
                        evaluation_digest=evaluation_hash if semantic else plan_hash,
                        ordinary_adopt=0,
                        ordinary_no_update=0,
                        parent_candidate_manifest_sha256=parent_manifest,
                        trained_candidate_manifest_sha256=candidate_manifest,
                    )
                    if admitted:
                        owner.qualify = lambda q: q == qualification
                        decision["adoption"] = owner.adopt(active, target, qualification)
                    selected, selected_bundle = (
                        (candidate, candidate_bundle)
                        if admitted
                        else (kernel, parent_bundle)
                    )
                    selected_component, selected_manifest = runtime.component(
                        owner, selected, selected_bundle, "active"
                    )
                    decision["selected_identity"] = selected_component.identity.digest
                    decision["selected_candidate_manifest_sha256"] = selected_manifest
                    if owner.status(active)["identity"] != asdict(
                        selected_component.identity
                    ):
                        raise ValueError(
                            "decision did not preserve the actual active version"
                        )
                    save(directory / "DECISION.json", decision)
                decision_cost["decision"] = decision["decision"]
                c_results = []
                for task in panels["C"]:
                    with measure_window(
                        windows, "task", "fresh original diagnostic, Cell owner, inference, repair and compile/semantic check",
                        phase="C", cell=cell, arm="selected", task_id=task["id"],
                        diagnostic_scope="fresh diagnostic and encoding included for this cell/task",
                    ) as task_cost:
                        original = compiler.check(task, task["source"], "C", "observation")
                        use = serve(
                            owner,
                            selected,
                            selected_bundle,
                            task,
                            observations(task, original),
                            "active",
                            runtime=runtime,
                            active=True,
                        )
                        use["outcome"] = compiler.check(
                            task,
                            repair(task["source"], use["action"]),
                            "C",
                            cell + "-selected",
                        )
                    use["task_cost"] = task_cost
                    c_results.append(use)
                save(directory / "C_SERVED.json", c_results)
                checkpoint = owner.checkpoint(active)
                live_hash = selected.checkpoint(
                    directory / "live.npz", checkpoint["state"]
                )
                cold = dict(
                    root=str(directory.resolve()),
                    cell=cell,
                    config=asdict(selected.config),
                    bundle=asdict(selected_bundle),
                    model_hash=live_hash,
                    checkpoint=checkpoint,
                    predict_action=c_results[-1]["predict_action"],
                    expected_logits=c_results[-1]["chosen_logits"],
                    sources=frozen_sources,
                    runtime=runtime.spec(),
                    candidate_manifest_sha256=selected_manifest,
                    wrapper_identity_digest=selected_component.identity.digest,
                )
                if semantic:
                    cold["new_task"] = plan["cold_task"]
                    cold["semantic"] = True
                save(directory / "COLD_REQUEST.json", cold)
                if semantic:
                    owner.close()
                cold_wall = time.perf_counter_ns()
                child_cpu_before = child_cpu_seconds()
                with measure_window(
                    windows, "cold_process", "fresh child launch, restore, inference, optional D task and wait/capture",
                    cell=cell, persistence_scope="parent COLD_PROCESS log persistence occurs after this window",
                ):
                    child = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "hepta_cells.maintenance_cycle",
                            "--recover",
                            str(directory / "COLD_REQUEST.json"),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env={
                            **os.environ,
                            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                        },
                    )
                child_cpu_after = child_cpu_seconds()
                save(
                    directory / "COLD_PROCESS.json",
                    dict(
                        returncode=child.returncode,
                        stdout=child.stdout,
                        stderr=child.stderr,
                        wall_ns=time.perf_counter_ns() - cold_wall,
                        whole_child_cpu_seconds=(
                            None
                            if child_cpu_before is None or child_cpu_after is None
                            else child_cpu_after - child_cpu_before
                        ),
                    ),
                )
                if child.returncode:
                    raise RuntimeError(
                        "cold restore failed; original child logs retained"
                    )
                if semantic:
                    owner = CellOwner(directory / "owner.sqlite")
                cold_result = json.loads((directory / "COLD_RESULT.json").read_text())
                if cold_result["pid"] == os.getpid() or owner.status(active)["pending"]:
                    raise ValueError(
                        "cold process identity or pending lifecycle mismatch"
                    )
                report[cell] = dict(
                    decision=decision,
                    parent_npz_sha256=parent_hash,
                    candidate_npz_sha256=candidate_hash,
                    training=training,
                    C_successes=sum(r["outcome"]["success"] for r in c_results),
                    C_denominator=8,
                    cold=cold_result,
                    local_no_update_complete=not admitted,
                    status="controlled_fixture_complete",
                )
            finally:
                owner.close()
        if sources() != frozen_sources:
            raise ValueError("source changed during execution")
        if time.perf_counter() - started > WALL_BUDGET_SECONDS:
            raise TimeoutError("predeclared whole-run budget exhausted")
        result = dict(
            plan_sha256=plan_hash,
            fixture_only=True,
            ordinary_daemon_qualification=False,
            native_hia_enabled=native is not None,
            cells=report,
            compile_calls=compiler.calls,
            wall_seconds=time.perf_counter() - started,
            parent_cpu_seconds=time.process_time() - cpu_started,
            energy_joules=None,
            peak_rss_bytes=None,
            cost_observations=cost_summary(windows, report),
            status="SEMANTIC_FIXTURE_COMPLETE" if semantic else "CONTROLLED_FIXTURE_COMPLETE",
            cost_scope="outer wall includes both cells, all attempts/controls, IO and cold children; parent CPU excludes child CPU reported separately; no physical energy measurement",
        )
        if semantic:
            result.update(
                semantic_subprocesses=compiler.semantic_calls,
                parent_compile_calls=compiler.calls,
                cold_new_tasks={cell: value["cold"]["new_task"]["outcome"]["success"]
                                for cell, value in report.items()},
                compile_count_scope="compile_calls counts parent checks; semantic subprocess compiles and cold checks are recorded separately",
            )
        save(root / "RESULT.json", result)
        return result
    except BaseException as error:
        save(
            root / "FAILURE.json",
            dict(
                error=f"{type(error).__name__}: {error}",
                compile_calls=compiler.calls,
                completed_cells=report,
                wall_seconds=time.perf_counter() - started,
                training_receipt=getattr(error, "receipt", None),
                cost_observations=cost_summary(windows, report),
                status="FAILED_OR_INCOMPLETE",
            ),
        )
        raise
    finally:
        runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?")
    parser.add_argument("--recover")
    parser.add_argument("--native-build-record")
    parser.add_argument("--runtime-pins")
    parser.add_argument("--semantic", action="store_true")
    args = parser.parse_args()
    if args.recover:
        recover(args.recover)
    elif args.output:
        result = run(
            args.output,
            native_build_record=args.native_build_record,
            runtime_pins=args.runtime_pins,
            semantic=args.semantic,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "compile_calls": result["compile_calls"],
                    "decisions": {
                        k: v["decision"]["decision"] for k, v in result["cells"].items()
                    },
                },
                sort_keys=True,
            )
        )
    else:
        parser.error("output or --recover is required")
