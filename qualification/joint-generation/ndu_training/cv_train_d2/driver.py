"""Single full-budget TRAIN-only 2x2 run; prepares/freezes without fitting by default."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
import traceback
from unittest.mock import patch

import numpy as np

from independent.accounting import WorkLedger
from independent.native_adam import NativeAdam, setup_work as adam_setup
from model import JointModel
from ndu_training.cv_train_d2 import cache, record
from ndu_training.cv_train_d2.budget import (
    HERE,
    ROOT,
    histories,
    plan,
    quote,
    update_quote,
)
from ndu_training.cv_train_d2.optimizer import AnchorAdam
from ndu_training.estimators import Sampler, WeightedObjective
from ndu_training.reinfer_d1 import service
from ndu_training.run import save_state


def cpu():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


def sources():
    previous = json.loads(
        (ROOT / "ndu_training/reinfer_d1/frozen-d1.json").read_text()
    )["sources"]
    paths = {ROOT / name for name in previous}
    paths.update(HERE.glob("*.py"))
    paths.update((HERE / "plan.json", HERE / "PROTOCOL.md"))
    return {str(path.relative_to(ROOT)): cache.sha(path) for path in sorted(paths)}


class Meter:
    """Physical phases run once; only their actual recipient systems pay them."""

    def __init__(self, historical):
        self.historical = historical
        self.own = {group: 0.0 for group in historical}
        self.stages = {group: {} for group in historical}
        self.physical_assigned = 0.0

    def totals(self):
        common = max(0.0, cpu() - self.physical_assigned)
        return {
            group: self.historical[group] + own + common
            for group, own in self.own.items()
        }

    @contextmanager
    def phase(self, groups, stage):
        if isinstance(groups, str):
            groups = (groups,)
        started = cpu()
        try:
            yield
        finally:
            elapsed = cpu() - started
            self.physical_assigned += elapsed
            for group in groups:
                self.own[group] += elapsed
                self.stages[group][stage] = self.stages[group].get(stage, 0.0) + elapsed
        self.check()

    def check(self):
        if max(self.totals().values()) > 9.85 or cpu() > 22.0:
            raise RuntimeError(
                "complete CPU cap admission with .15/.2s closing reserve"
            )


def draw_pool(arrays, shared):
    p, pool, stored = plan(), {}, {}
    for seed in p["model_seeds"]:
        for kind in p["samplers"]:
            key = f"{kind}-{seed}"
            sampler = Sampler(arrays["labels"], kind, seed + p["sampler_seed_offset"])
            draws = [sampler.draw() for _ in range(p["maximum_rounds"])]
            pool[key] = draws
            stored[key + "_indices"] = np.stack([d[0] for d in draws]).astype(np.int32)
            stored[key + "_weights"] = np.stack(
                [np.ones(64) if d[1] is None else d[1] for d in draws]
            )
            stored[key + "_full_mask"] = np.stack([d[2] for d in draws])
    shared.record(
        "sampler_prepare",
        master_streams=6,
        batches=6 * p["maximum_rounds"],
        drawn_requests=6 * p["maximum_rounds"] * 64,
    )
    return pool, stored


def initialize(meter, ledgers, bases, references, library, pool):
    states = {}
    for group in plan()["groups"]:
        with meter.phase(group, "setup"):
            states[group] = {}
            for seed in plan()["model_seeds"]:
                for kind in plan()["samplers"]:
                    key = f"{kind}-{seed}"
                    model = bases[seed].clone()
                    ledgers[group].charge_kernel(
                        "search_setup", "native_adam_prepare", **adam_setup(model)
                    )
                    native = NativeAdam(model, library)
                    optimizer = AnchorAdam(
                        native,
                        ledgers[group],
                        references.get(seed) if group.endswith("CV") else None,
                    )
                    objective = WeightedObjective(
                        group[0],
                        model,
                        rho=1.5,
                        ce_anchor=0.2,
                        ledger=ledgers[group],
                        optimizer=optimizer,
                    )
                    states[group][key] = {
                        "model": model,
                        "objective": objective,
                        "optimizer": optimizer,
                        "steps": 0,
                        "stream": hashlib.sha256(),
                        "prefix128": None,
                        "loss_trace": [],
                        "pool": pool[key],
                    }
    return states


def train_round(group, states, ledger, arrays, out):
    for key, state in states.items():
        step = state["steps"] + 1
        draw = state["pool"][step - 1]
        idx, weights, full = draw
        observe = step == 1 or step % 64 == 0
        exact = update_quote(group, key.split("-")[0], int((~full).sum()), observe)
        if ledger.remaining_units < exact:
            raise RuntimeError(
                "complete update preflight failed before parameter mutation"
            )
        state["optimizer"].bind_batch(idx, weights, full, step)
        state["objective"].row_weights = weights
        x = np.where(full[:, None], arrays["full"][idx], arrays["low"][idx])
        loss = state["objective"].step(
            state["model"],
            x,
            arrays["labels"][idx],
            0.003,
            ledger=ledger,
            full_mask=full,
        )
        state["steps"] = step
        state["stream"].update(record.draw_digest(draw))
        if observe:
            state["loss_trace"].append({"step": step, "batch_loss": loss})
        if step == 128:
            state["prefix128"] = state["stream"].hexdigest()
            save_state(state["model"], out / f"prefix128-{group}-{key}", ledger)


def serve_all(states, ledgers, meter, arrays, library, payloads):
    p = plan()
    for group in p["groups"]:
        with meter.phase(group, "service_setup"):
            for state in states[group].values():
                state["service"] = record.service_state()
                state["service"]["generator"] = service.prepare(state["model"], library)
    for si, seed in enumerate(p["model_seeds"]):
        for ki, kind in enumerate(p["samplers"]):
            key = f"{kind}-{seed}"
            for ci, rows in enumerate(arrays["cohorts"]):
                order = service.WILLIAMS[(si + ki + ci) % 4]
                for position in order:
                    group = p["groups"][position]
                    state, ledger = states[group][key]["service"], ledgers[group]
                    if ledger.remaining_units < 64 * 19236:
                        raise RuntimeError("actual service operator admission failed")
                    with meter.phase(group, "service"):
                        left, right, outputs, sizes, cost = service.batch(
                            state["generator"],
                            arrays["full"][rows],
                            844021 + 37 * ci + seed,
                        )
                        ledger.record(
                            "service",
                            units=cost["work_units"],
                            requests=64,
                            native_batches=1,
                        )
                    with meter.phase(group, "row_preservation"):
                        service.capture(
                            state,
                            rows,
                            0,
                            ci,
                            left,
                            right,
                            outputs,
                            sizes,
                            cost,
                            payloads,
                        )


def run(out, frozen_path):
    p = plan()
    frozen = json.loads(Path(frozen_path).read_text())
    if frozen["sources"] != sources() or not quote()["ready_for_review"]:
        raise RuntimeError("source/forecast admission mismatch")
    if any(
        os.environ.get(key) != "1"
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    ):
        raise RuntimeError("one-thread launch required")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    record.write(
        HERE / "TRAIN-d2-opened.json",
        {
            "out": str(out),
            "freeze_sha256": cache.sha(frozen_path),
            "formal_data": False,
        },
    )
    h = histories()
    historical = {
        group: h["base_cpu"] + (h["reference_cpu"] if group.endswith("CV") else 0)
        for group in p["groups"]
    }
    meter = Meter(historical)
    ledgers = {group: WorkLedger(group, 12_000_000_000) for group in p["groups"]}
    shared = WorkLedger("actual-shared")
    states, bases, references, results, payloads = {}, {}, {}, {}, {}
    report = {
        "status": "running",
        "TRAIN_only": True,
        "plan": p,
        "history": h,
        "groups": results,
    }
    signal.signal(
        signal.SIGPROF,
        lambda *_: (_ for _ in ()).throw(RuntimeError("physical CPU watchdog")),
    )
    signal.setitimer(signal.ITIMER_PROF, 22.0)
    try:
        identities = cache.verify_inputs()
        if identities != frozen["inputs"]:
            raise RuntimeError("frozen input identities changed")
        for group, ledger in ledgers.items():
            ledger.record(
                "historical_base_complete", units=h["base_units"], source_receipts=1
            )
            if group.endswith("CV"):
                ledger.record(
                    "historical_reference_complete",
                    units=h["reference_units"],
                    source_receipts=1,
                )
        arrays, mapping = cache.load_inputs()
        for seed in p["model_seeds"]:
            base = JointModel.load(ROOT / p["original_run"] / f"base-{seed}.npz")
            for value in base.params.values():
                value.flags.writeable = False
            bases[seed] = base
        observers = {
            seed: cache.readout_observer(base, shared) for seed, base in bases.items()
        }
        pool, stored_draws = draw_pool(arrays, shared)
        record.save(out / "master-draws.npz", stored_draws)
        record.write(
            out / "TRAIN-input-references.json",
            {
                "immutable_files": identities,
                "mapping": str(
                    (
                        ROOT / p["TRAIN_and_reference_run"] / "TRAIN-map.json"
                    ).relative_to(ROOT)
                ),
                "source_count": len(mapping["source_ids"]),
                "rows": 3072,
                "original_base_receipt": p["original_run"] + "/result.json",
                "CV_reference_receipt": p["TRAIN_and_reference_run"] + "/result.json",
            },
        )
        for ledger in ledgers.values():
            ledger.attribute_shared(shared)
        initial = meter.totals()
        for group, current in initial.items():
            forecast = (
                6
                * 128
                * p[
                    "update_cpu_forecast_CV"
                    if group.endswith("CV")
                    else "update_cpu_forecast_plain"
                ]
            )
            if (
                current
                + forecast
                + p["setup_cpu_forecast_each_group"]
                + p["tail_cpu_reserve_each_group"]
                >= 10
            ):
                raise RuntimeError(
                    f"pre-result complete 128-step CPU admission rejected: {group}"
                )
        with meter.phase(("A-CV", "N-CV"), "reference_cache_load"):
            references = {
                seed: cache.load_reference(seed, bases[seed], arrays)
                for seed in p["model_seeds"]
            }
        library = ROOT / p["original_run"] / "build/libjoint.so"
        states = initialize(meter, ledgers, bases, references, library, pool)
        record.write(
            out / "model-results-started.json",
            {"next": "first minibatch update", "TRAIN_only": True},
        )
        stopped = {}
        last_round = {group: 0.0 for group in p["groups"]}
        round_quotes = {
            group: sum(
                update_quote(group, kind)
                for _ in p["model_seeds"]
                for kind in p["samplers"]
            )
            for group in p["groups"]
        }
        for ri in range(p["maximum_rounds"]):
            for position in service.WILLIAMS[ri % 4]:
                group = p["groups"][position]
                if group in stopped:
                    continue
                if (
                    ledgers[group].remaining_units
                    < round_quotes[group] + p["tail_units_reserve_each_group"]
                ):
                    stopped[group] = (
                        "next six-candidate round plus full tail fails operator admission"
                    )
                    continue
                forecast = max(
                    last_round[group] * 1.5,
                    6
                    * p[
                        "update_cpu_forecast_CV"
                        if group.endswith("CV")
                        else "update_cpu_forecast_plain"
                    ],
                )
                if (
                    meter.totals()[group] + forecast + p["tail_cpu_reserve_each_group"]
                    >= 10
                ):
                    stopped[group] = (
                        "next six-candidate round plus full tail fails CPU admission"
                    )
                    continue
                before = cpu()
                with meter.phase(group, "adaptation"):
                    train_round(group, states[group], ledgers[group], arrays, out)
                last_round[group] = cpu() - before
            if len(stopped) == 4:
                break
        report["stops"] = stopped
        if any(
            state["steps"] < 128
            for group in states.values()
            for state in group.values()
        ):
            raise RuntimeError(
                "some candidate failed the declared common 128-step opportunity"
            )
        serve_all(states, ledgers, meter, arrays, library, payloads)
        for group in p["groups"]:
            results[group] = {"candidates": {}}
            with meter.phase(group, "readout_export"):
                for key, state in states[group].items():
                    seed = int(key.split("-")[1])
                    results[group]["candidates"][key] = record.final_candidate(
                        state,
                        arrays,
                        observers[seed],
                        bases[seed],
                        group,
                        key,
                        out,
                        ledgers[group],
                    )
        final_shared = WorkLedger("actual-final-shared")
        old = json.loads((ROOT / p["original_run"] / "result.json").read_text())
        report["contrasts"] = record.contrasts(results, old, final_shared)
        record.write(out / "output-payloads.json", payloads)
        for ledger in ledgers.values():
            ledger.attribute_shared(final_shared)
        report["status"] = "complete TRAIN 2x2; no confirmation"
    except Exception:
        report.update(
            status="FAILED; sealed; no outcome-driven retry",
            error=traceback.format_exc(),
        )
        signal.setitimer(signal.ITIMER_PROF, 0)
        for group, candidates in states.items():
            for key, state in candidates.items():
                # Preserve every partial model and moment even after a cap failure.
                save_state(
                    state["model"],
                    out / f"failed-{group}-{key}",
                    WorkLedger("forensics"),
                )
                if "service" in state:
                    record.save(
                        out / f"failed-service-{group}-{key}.npz",
                        {
                            name: value
                            for name, value in state["service"].items()
                            if isinstance(value, np.ndarray)
                        },
                    )
                results.setdefault(group, {}).setdefault("partial_candidates", {})[
                    key
                ] = {
                    "steps": state["steps"],
                    "stream_sha256": state["stream"].hexdigest(),
                    "loss_trace": state["loss_trace"],
                    "gradient_norm_trace": state["optimizer"].trace,
                }
        if payloads and not (out / "output-payloads.json").exists():
            record.write(out / "output-payloads.json", payloads)
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0)
        report.update(
            physical_current_process_cpu=cpu(),
            complete_attributed_cpu=meter.totals(),
            actual_phase_cpu=meter.stages,
            ledgers={group: ledger.snapshot() for group, ledger in ledgers.items()},
        )
        try:
            files = record.file_manifest(out)
            record.write(out / "artifacts.json", {"files": files})
            size = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
            if (
                size > p["storage_cap_bytes"]
                or cpu() > p["physical_current_process_cpu_cap"]
                or max(meter.totals().values()) > 10
            ):
                report["status"] = "FAILED closing/storage/CPU cap; sealed"
            record.write(out / "result.json", report)
            terminal = {
                "status": report["status"],
                "physical_current_process_cpu": cpu(),
                "complete_attributed_cpu": meter.totals(),
                "archive_bytes": sum(
                    path.stat().st_size for path in out.rglob("*") if path.is_file()
                ),
            }
            if (
                terminal["archive_bytes"] > p["storage_cap_bytes"]
                or cpu() > 22.2
                or max(meter.totals().values()) > 10
            ):
                terminal["status"] = "FAILED final receipt cap; sealed"
            record.write(out / "final-execution.json", terminal)
            print(
                json.dumps(
                    {
                        **terminal,
                        "cpu_after_final_write": cpu(),
                        "attributed_cpu_after_final_write": meter.totals(),
                    }
                )
            )
        except Exception:
            print(traceback.format_exc())
            return 1
    return int(terminal["status"].startswith("FAILED"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("quote", "freeze", "smoke", "train"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    if args.action == "quote":
        record.write(args.out, quote())
    elif args.action == "freeze":
        current = subprocess.check_output(
            ["git", "status", "--porcelain", "--", str(HERE)], text=True
        )
        if current.strip():
            raise RuntimeError("commit all source/plan/protocol before freeze")
        record.write(
            args.out,
            {
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "sources": sources(),
                "inputs": cache.verify_inputs(),
                "quote": quote(),
            },
        )
    elif args.action == "smoke":
        frozen = json.loads(Path(args.freeze).read_text())
        assert (
            frozen["sources"] == sources() and frozen["inputs"] == cache.verify_inputs()
        )
        with (
            patch.object(
                JointModel,
                "_forward",
                side_effect=AssertionError("smoke forbids forward"),
            ),
            patch.object(
                NativeAdam,
                "apply_gradients",
                side_effect=AssertionError("smoke forbids update"),
            ),
            patch.object(
                cache,
                "load_inputs",
                side_effect=AssertionError("smoke forbids TRAIN array load"),
            ),
        ):
            model = JointModel.load(ROOT / plan()["original_run"] / "base-11.npz")
            NativeAdam(model, ROOT / plan()["original_run"] / "build/libjoint.so")
            record.write(
                args.out,
                {
                    "status": "real entry smoke passed",
                    "forwards": 0,
                    "updates": 0,
                    "TRAIN_array_loads": 0,
                    "source_freeze": cache.sha(args.freeze),
                    "quote": quote(),
                },
            )
        print("real entry smoke passed without TRAIN prediction or optimizer update")
    else:
        return run(args.out, args.freeze)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
