"""One bounded TRAIN diagnostic. There is deliberately no evaluation command."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import numpy as np

from data import templates
from independent.accounting import WorkLedger, counted_model_class
from independent.data_v2 import dataset, default_profile, manifest
from independent.evaluation import measure
from independent.learning import CachedObjective, CONTENT_PARAMETERS
from independent.mixed_training import mixed_step_work
from independent.native import compile_native
from independent.native_adam import NativeAdam, setup_work as adam_setup
from model import JointModel
from ndu_training.diagnostics import gradient_panel, score
from ndu_training.estimators import Sampler, WeightedObjective, weighted_work


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = "0aca16714390ca045a53cece9644992b7990fc9c"
DEPENDENCIES = [
    "data.py",
    "model.py",
    "utility.py",
    "control.py",
    "contracts.py",
    *[
        "independent/" + name
        for name in (
            "accounting.py",
            "data_v2.py",
            "evaluation.py",
            "inference.py",
            "learning.py",
            "mixed_training.py",
            "native.py",
            "native.c",
            "native_adam.py",
        )
    ],
]


def cpu():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + children.ru_utime + children.ru_stime


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def sources():
    paths = [ROOT / p for p in DEPENDENCIES]
    paths += sorted(HERE.glob("*.py")) + [HERE / "plan.json", HERE / "PROTOCOL.md"]
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }


def freeze(path):
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", str(HERE)], text=True
    )
    if dirty.strip():
        raise ValueError("commit diagnostic source before freezing")
    write(
        path,
        {
            "base_commit": BASE,
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "sources": sources(),
            "scope": "TRAIN-only; no formal data, marker or acceptance authority",
        },
    )


def service(model, data, plan, ledger, library):
    idx = np.concatenate([np.flatnonzero(data["labels"] == y)[:8] for y in range(12)])
    subset = {"full": data["full"][idx], "split": "train"}
    result = measure(
        model,
        None,
        "full",
        subset,
        {**plan, "native_library": library},
        1.0,
        seed=plan["sampling_seed"],
        observe=False,
    )
    ledger.record(
        "train_service",
        units=result["cost"]["operator_totals"]["consumed_units"]
        + result["cost"]["prepare"]["consumed_units"],
        actual_png_requests=len(idx),
    )
    return result


def save_state(model, path, ledger):
    model.save(path.with_suffix(".npz"))
    state = {
        f"{key}.{part}": value
        for key, moment in model._moments.items()
        for part, value in zip(("m", "v", "clock"), moment)
    }
    np.savez_compressed(path.with_suffix(".adam.npz"), **state)
    ledger.record(
        "export",
        exported_models=1,
        serialized_bytes=sum(
            p.stat().st_size
            for p in (path.with_suffix(".npz"), path.with_suffix(".adam.npz"))
        ),
    )


def train(out, receipt):
    plan = json.loads((HERE / "plan.json").read_text())
    if json.loads(Path(receipt).read_text())["sources"] != sources():
        raise ValueError("source differs from prospective TRAIN freeze")
    if any(
        os.environ.get(k) != "1"
        for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    ):
        raise ValueError(
            "launch this diagnostic with the three declared thread variables set to 1"
        )
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write(
        out / "train-started.json",
        {
            "freeze": str(receipt),
            "freeze_sha256": hashlib.sha256(Path(receipt).read_bytes()).hexdigest(),
            "formal_splits_allowed": False,
        },
    )
    shared = WorkLedger("shared", plan["operator_units_per_system"])
    ledgers, costs, states, results = {}, {}, {}, {}
    report = {
        "status": "running",
        "base_commit": BASE,
        "train_only": True,
        "plan": plan,
        "bases": {},
        "systems": results,
    }
    started_wall = time.perf_counter()
    active_total = 0.0
    bases = {}
    try:
        profile = default_profile()
        data = dataset("train", profile)  # The only split-construction call.
        write(
            out / "train-manifest.json",
            {**manifest(data), "reconstruction_profile": profile},
        )
        shared.record("base_data", prepared_rows=len(data["labels"]))
        compiled = compile_native(out / "build/libjoint.so")
        report["compile"] = compiled
        shared.record("base_compile", compiler_invocations=1)
        library = compiled["library_path"]
        reference_cpu = []
        Counted = counted_model_class(JointModel)
        for seed in plan["model_seeds"]:
            decoder = Counted(202, 12, 192, hidden=32, seed=seed, ledger=shared)
            bases[seed] = decoder
            with shared.phase("base_decoder"):
                decoder.fit_decoder(templates(), steps=plan["decoder_steps"])
            model = JointModel(202, 12, 192, hidden=32)
            model.params = {key: value.copy() for key, value in decoder.params.items()}
            bases[seed] = model
            obj, rng = CachedObjective("S", model), np.random.default_rng(seed + 1000)
            for _ in range(plan["pretrain_steps"]):
                idx = rng.integers(len(data["labels"]), size=64)
                mask = rng.random(64) < 0.5
                x = np.where(mask[:, None], data["full"][idx], data["low"][idx])
                obj.step(
                    model,
                    x,
                    data["labels"][idx],
                    0.003,
                    ledger=shared,
                    stage="base_pretrain",
                )
            bases[seed] = model
            row = {
                "digest": model.digest(),
                "train": score(model, data, shared, "base_train_score"),
                "gradient": gradient_panel(
                    model, data, shared, plan["gradient_repeats"]
                ),
            }
            measured = service(model, data, plan, shared, library)
            row["service"] = measured
            reference_cpu.append(float(np.mean(measured["per_row_cost"]["cpu_ns"])))
            save_state(model, out / f"base-{seed}", shared)
            report["bases"][str(seed)] = row
            if cpu() > plan["cpu_seconds_per_system"]:
                raise RuntimeError("shared preparation exceeded complete CPU cap")
        shared_cpu = (
            cpu()
        )  # Includes interpreter/imports, compiler children and all diagnostics above.
        report["shared_cpu_seconds"] = shared_cpu
        report["environment"] = {
            "python": sys.version,
            "numpy": np.__version__,
            "cwd": str(Path.cwd()),
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"], text=True
            ).strip(),
            "thread_environment": {
                k: os.environ[k]
                for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
            },
            "actual_threadpool_count": "not measured; configured limits only",
        }
        report["reference_full_cpu_ns"] = float(np.median(reference_cpu))
        for arm in ("A", "N"):
            ledgers[arm] = WorkLedger(arm, plan["operator_units_per_system"])
            ledgers[arm].attribute_shared(shared)
            costs[arm] = shared_cpu
            states[arm], results[arm] = {}, {"candidates": {}, "stop": None}
            before = cpu()
            for seed in plan["model_seeds"]:
                for kind in plan["samplers"]:
                    key = f"{kind}-{seed}"
                    model = bases[seed].clone()
                    ledgers[arm].charge_kernel(
                        "search_setup", "native_adam_prepare", **adam_setup(model)
                    )
                    optimizer = NativeAdam(model, library)
                    obj = WeightedObjective(
                        arm, model, ledger=ledgers[arm], optimizer=optimizer
                    )
                    sampler = Sampler(data["labels"], kind, seed + 3000)
                    states[arm][key] = {
                        "model": model,
                        "objective": obj,
                        "sampler": sampler,
                        "steps": 0,
                        "stream": hashlib.sha256(),
                        "trace": [],
                        "matched": None,
                    }
            elapsed = cpu() - before
            costs[arm] += elapsed
            active_total += elapsed
        # Same ordered candidate opportunities and draw streams for A and N.
        # Each complete system includes BOTH sampler candidates and all seeds.
        for round_index in range(plan["maximum_rounds"]):
            for arm in ("A", "N") if round_index % 2 == 0 else ("N", "A"):
                if results[arm]["stop"] is not None:
                    continue
                ledger = ledgers[arm]
                reserve = plan["tail_reserve_units"]
                round_units = sum(
                    ledger.estimate_kernel(
                        **mixed_step_work((202, 12, 192, 32), arm, 64)
                    )
                    + (
                        ledger.estimate_kernel(**weighted_work(64))
                        if kind == "stratified"
                        else 0
                    )
                    for _seed in plan["model_seeds"]
                    for kind in plan["samplers"]
                )
                if ledger.remaining_units < reserve + round_units:
                    results[arm]["stop"] = (
                        "next complete six-candidate round plus tail exceeds operator cap"
                    )
                    continue
                # Scheduler CPU is attributed in full to both systems.
                scheduler_cpu = max(0.0, cpu() - shared_cpu - active_total)
                if (
                    costs[arm] + scheduler_cpu + plan["tail_reserve_cpu_seconds"]
                    >= plan["cpu_seconds_per_system"]
                ):
                    results[arm]["stop"] = (
                        "CPU reserve for all final scoring/export/service reached"
                    )
                    continue
                before = cpu()
                for key, state in states[arm].items():
                    idx, w, mask = state["sampler"].draw()
                    state["stream"].update(idx.astype("<i8").tobytes() + mask.tobytes())
                    x = np.where(mask[:, None], data["full"][idx], data["low"][idx])
                    obj = state["objective"]
                    obj.row_weights = w
                    loss = obj.step(
                        state["model"],
                        x,
                        data["labels"][idx],
                        plan["learning_rate"],
                        ledger=ledger,
                        full_mask=mask,
                    )
                    state["steps"] += 1
                    if state["steps"] % 64 == 0:
                        state["trace"].append(
                            {"step": state["steps"], "batch_loss": loss}
                        )
                    if state["steps"] == plan["matched_steps"]:
                        state["matched"] = {
                            "stream_sha256": state["stream"].hexdigest(),
                            "train": score(
                                state["model"], data, ledger, "matched_train_score"
                            ),
                        }
                        save_state(state["model"], out / f"matched-{arm}-{key}", ledger)
                elapsed = cpu() - before
                costs[arm] += elapsed
                active_total += elapsed
                if (
                    costs[arm] + max(0, cpu() - shared_cpu - active_total)
                    > plan["cpu_seconds_per_system"]
                ):
                    raise RuntimeError(f"{arm} actual complete CPU cap exceeded")
            if all(results[a]["stop"] is not None for a in ("A", "N")):
                break
        for seed_index, seed in enumerate(plan["model_seeds"]):
            for arm in ("A", "N") if seed_index % 2 == 0 else ("N", "A"):
                before = cpu()
                for kind in plan["samplers"]:
                    key, ledger = f"{kind}-{seed}", ledgers[arm]
                    state = states[arm][key]
                    model = state["model"]
                    row = {
                        "steps": state["steps"],
                        "stream_sha256": state["stream"].hexdigest(),
                        "matched": state["matched"],
                        "trace": state["trace"],
                        "digest": model.digest(),
                        "train": score(model, data, ledger, "final_train_score"),
                        "parameter_delta_l2": {
                            p: float(
                                np.linalg.norm(model.params[p] - bases[seed].params[p])
                            )
                            for p in CONTENT_PARAMETERS
                        },
                    }
                    row["finite_parameters_and_moments"] = all(
                        np.isfinite(v).all()
                        for v in (
                            *model.params.values(),
                            *(v for m in model._moments.values() for v in m[:2]),
                        )
                    )
                    row["service"] = service(model, data, plan, ledger, library)
                    save_state(model, out / f"final-{arm}-{key}", ledger)
                    write(
                        out / f"rng-{arm}-{key}.json",
                        {
                            "indices": state["sampler"].rng.bit_generator.state,
                            "views": state["sampler"].views.bit_generator.state,
                        },
                    )
                    results[arm]["candidates"][key] = row
                elapsed = cpu() - before
                costs[arm] += elapsed
                active_total += elapsed
                if (
                    costs[arm] + max(0, cpu() - shared_cpu - active_total)
                    > plan["cpu_seconds_per_system"]
                ):
                    raise RuntimeError(
                        f"{arm} final work exceeded actual complete CPU cap"
                    )
        contrasts = {}
        for kind in plan["samplers"]:
            contrasts[kind] = []
            for seed in plan["model_seeds"]:
                key = f"{kind}-{seed}"
                a, n = results["A"]["candidates"][key], results["N"]["candidates"][key]
                if a["matched"] is None or n["matched"] is None:
                    raise RuntimeError("budget ended before declared matched prefix")
                if a["matched"]["stream_sha256"] != n["matched"]["stream_sha256"]:
                    raise RuntimeError("matched A/N minibatch stream differs")
                contrasts[kind].append(
                    {
                        "seed": seed,
                        "A_steps": a["steps"],
                        "N_steps": n["steps"],
                        "matched_N_minus_A": {
                            m: n["matched"]["train"][m] - a["matched"]["train"][m]
                            for m in ("task_utility", "joint_success")
                        },
                        "final_N_minus_A": {
                            m: n["train"][m] - a["train"][m]
                            for m in ("task_utility", "joint_success")
                        },
                    }
                )
        report["contrasts"] = contrasts
        scheduler_cpu = max(0.0, cpu() - shared_cpu - active_total)
        for arm in ("A", "N"):
            total_cpu = costs[arm] + scheduler_cpu
            results[arm].update(
                cpu_seconds=total_cpu,
                scheduler_cpu_seconds=scheduler_cpu,
                ledger=ledgers[arm].snapshot(),
            )
            for row in results[arm]["candidates"].values():
                svc = row["service"]
                row["train_complete_cpu_net"] = (
                    row["train"]["task_utility"]
                    - plan["compute_price"]
                    * (
                        float(np.mean(svc["per_row_cost"]["cpu_ns"]))
                        + svc["cost"]["prepare_cpu_ns"] / 100000
                        + total_cpu * 1e9 / (3 * 100000)
                    )
                    / report["reference_full_cpu_ns"]
                )
        report.update(
            status="TRAIN diagnostic complete; no confirmation",
            scheduler_cpu_seconds=scheduler_cpu,
            actual_process_cpu_seconds=cpu(),
        )
    except Exception:
        report.update(status="FAILED; retained; no retry", error=traceback.format_exc())
        # Failed partial weights remain inspectable, with no fresh experiment.
        forensic_started, forensic = cpu(), WorkLedger("failure-preservation")
        for seed, model in bases.items():
            save_state(model, out / f"failed-base-{seed}", forensic)
        for arm, candidates in states.items():
            for key, state in candidates.items():
                save_state(state["model"], out / f"failed-{arm}-{key}", forensic)
                results[arm].setdefault("partial_candidates", {})[key] = {
                    "steps": state["steps"],
                    "trace": state["trace"],
                    "matched": state["matched"],
                    "stream_sha256": state["stream"].hexdigest(),
                    "rng": state["sampler"].rng.bit_generator.state,
                    "view_rng": state["sampler"].views.bit_generator.state,
                }
        report.update(
            failure_preservation_cpu_seconds=cpu() - forensic_started,
            failure_preservation_ledger=forensic.snapshot(),
            failure_cpu_at_start=forensic_started,
            partial_active_cpu_seconds=costs,
        )
    finally:
        report["shared_ledger"] = shared.snapshot()
        report["partial_ledgers"] = {
            arm: ledger.snapshot() for arm, ledger in ledgers.items()
        }
        report["wall_seconds"] = time.perf_counter() - started_wall
        report["administration_cpu_start"] = cpu()
        write(out / "result.json", report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "out": str(out),
                    "error": report.get("error"),
                    "process_cpu_seconds": cpu(),
                },
                ensure_ascii=False,
            )
        )
    return 1 if report["status"].startswith("FAILED") else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "train"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.out)
    else:
        raise SystemExit(train(args.out, args.freeze))
