"""One authorized TRAIN reconstruction; never trains or constructs held-out data."""

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
from independent.data_v2 import dataset, manifest
from model import JointModel
from ndu_training.diagnostics import gradient
from ndu_training.estimators import Sampler, WeightedObjective
from ndu_training.mechanism_readout.anchor_cv import correct, correction_work
from ndu_training.reinfer_d1.kernels import (
    Reference,
    flat,
    planned_units,
    request_readout,
)
from ndu_training.reinfer_d1 import service
from ndu_training.reinfer_d1.summary import summarize

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "runs/codex-cloud-ndu-training-train-d1"


def cpu():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def save(path, arrays):
    with Path(path).open("xb") as stream:
        np.savez(stream, **arrays)  # ZIP_STORED, lossless float64, no pickle.


def sources():
    old = json.loads((ROOT / "ndu_training/frozen-train-d1.json").read_text())[
        "sources"
    ]
    paths = (
        [ROOT / name for name in old]
        + list(HERE.glob("*.py"))
        + [
            HERE / "plan.json",
            HERE / "PROTOCOL.md",
            ROOT / "ndu_training/mechanism_readout/anchor_cv.py",
        ]
    )
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}


def preflight():
    quote = planned_units()
    assert all(value < 4_000_000_000 for value in quote["total_each_arm"].values())
    old = json.loads((OLD / "artifacts.json").read_text())["files"]
    names = [f"base-{s}.npz" for s in (11, 23, 47)] + [
        f"final-{a}-{kind}-{s}.npz"
        for a in ("A", "N")
        for kind in ("iid", "stratified")
        for s in (11, 23, 47)
    ]
    names += ["build/libjoint.so", "train-manifest.json", "result.json"]
    for name in names:
        assert sha(OLD / name) == old[name]["sha256"], name
    return quote


class Meter:
    def __init__(self, common):
        self.common = common
        self.own = {"A": 0.0, "N": 0.0}
        self.stages = {"A": {}, "N": {}}

    def totals(self):
        shared = max(self.common, cpu() - sum(self.own.values()))
        return {a: shared + value for a, value in self.own.items()}

    def check(self):
        if cpu() > 29.8 or max(self.totals().values()) > 14.8:
            raise RuntimeError(
                "diagnostic CPU admission stop with .2s evidence reserve"
            )

    @contextmanager
    def phase(self, arm, stage):
        self.check()
        started = cpu()
        try:
            yield
        finally:
            elapsed = cpu() - started
            self.own[arm] += elapsed
            self.stages[arm][stage] = self.stages[arm].get(stage, 0) + elapsed
        self.check()


def schedules(labels):
    result = {}
    for kind in ("iid", "stratified"):
        sampler = Sampler(labels, kind, 742019)
        result[kind] = [sampler.draw() for _ in range(32)]
        n = len(labels)
        coefficient = (
            sampler.counts[labels]
            / 64
            * (64 * sampler.mass[labels] / sampler.counts[labels])
            / np.bincount(labels, minlength=12)[labels]
            / 2
        )
        np.testing.assert_allclose(coefficient, 1 / (2 * n), rtol=0, atol=1e-15)
    return result


def gradient_measure(model, reference, kind, arm, schedule, ledger):
    objective = WeightedObjective(arm, model, ledger=ledger, stage="gradient_setup")
    reference_mean = flat(reference.mean)
    means = np.zeros((3, 7288))
    m2 = np.zeros_like(means)
    norms = []
    hashes = []
    shapes = [model.params[key].shape for key in reference.mean]
    keys = list(reference.mean)
    cuts = np.cumsum([0] + [model.params[key].size for key in keys])
    for number, (idx, w, full) in enumerate(schedule, 1):
        cache_idx = idx + np.where(full, 0, 3072)
        x = reference.x[cache_idx]
        y = reference.y[cache_idx]
        g = gradient(model, x, y, objective, w, ledger)
        ref = reference.pull(cache_idx, w, ledger, "gradient_diagnostic")
        ledger.charge_kernel(
            "gradient_diagnostic", "CV_correction", **correction_work(7288)
        )
        current = {
            key: g[cuts[i] : cuts[i + 1]].reshape(shape)
            for i, (key, shape) in enumerate(zip(keys, shapes))
        }
        corrected = flat(correct(current, reference.mean, ref))
        ref_flat = flat(ref)
        ledger.charge_kernel(
            "gradient_diagnostic",
            "variance_and_norms",
            scalar_ops=21 * 7288,
            div_ops=3 * 7288,
            sqrt_ops=18,
        )
        vectors = np.stack((g, corrected, ref_flat))
        difference = vectors - means
        means += difference / number
        m2 += difference * (vectors - means)
        norms.append([float(np.linalg.norm(v)) for v in vectors])
        hashes.append(
            [hashlib.sha256(v.astype("<f8").tobytes()).hexdigest() for v in vectors]
        )
    variance = m2.sum(1) / 31
    ledger.charge_kernel(
        "gradient_diagnostic",
        "final_variance_summary",
        scalar_ops=6 * 7288 - 3,
        div_ops=4,
        sqrt_ops=1,
    )
    return {"mean": means, "M2": m2, "batch_norms": np.asarray(norms)}, {
        "original_variance": float(variance[0]),
        "CV_variance": float(variance[1]),
        "variance_reduction": float(1 - variance[1] / variance[0]),
        "all_32_gradient_hashes": hashes,
        "reference_mean_max_error": reference.mean_max_error,
        "sample_reference_mean_error_norm": float(
            np.linalg.norm(means[2] - reference_mean)
        ),
    }


def run(out, freeze):
    frozen = json.loads(Path(freeze).read_text())
    if frozen["sources"] != sources():
        raise RuntimeError("source freeze mismatch")
    preflight()
    if any(
        os.environ.get(k) != "1"
        for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    ):
        raise RuntimeError("fixed one-thread launch required")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write(
        HERE / "diagnostic-d1-opened.json",
        {"out": str(out), "freeze_sha256": sha(freeze), "TRAIN_only": True},
    )
    report = {
        "status": "started",
        "new_inference_identity": True,
        "not_original_row_logs": True,
        "planned_units": planned_units(),
        "gradient": {},
        "service": {},
    }
    shared = WorkLedger("shared", 1_600_000_000)
    ledgers = {}
    meter = None
    models = {}
    references = {}
    states = {}
    payloads = {}
    readouts = {}

    def timeout(*_):
        raise RuntimeError("physical CPU watchdog stop")

    signal.signal(signal.SIGPROF, timeout)
    signal.setitimer(signal.ITIMER_PROF, max(0.001, 29.5 - cpu()))
    try:
        expected = json.loads((OLD / "train-manifest.json").read_text())
        data = dataset("train", expected["reconstruction_profile"])
        assert manifest(data) == {
            k: v for k, v in expected.items() if k != "reconstruction_profile"
        }
        groups = service.cohorts(data)
        schedule = schedules(data["labels"])
        source_ids = sorted(set(data["source_ids"]))
        source_index = {s: i for i, s in enumerate(source_ids)}
        save(
            out / "TRAIN-inputs.npz",
            {
                "full": data["full"],
                "low": data["low"],
                "labels": data["labels"],
                "commands": data["commands"],
                "source_scene": data["source_scenes"],
                "cohorts": groups,
                "row_source_index": np.array(
                    [source_index[s] for s in data["source_ids"]], dtype=np.uint16
                ),
                **{
                    kind + "_" + name: np.stack(
                        [
                            item[j] if item[j] is not None else np.ones(64)
                            for item in values
                        ]
                    )
                    for kind, values in schedule.items()
                    for j, name in enumerate(("indices", "weights", "full_mask"))
                },
            },
        )
        write(
            out / "TRAIN-map.json",
            {
                "source_ids": source_ids,
                "sources": data["sources"],
                "input_hashes": data["input_hashes"],
                "manifest": expected,
            },
        )
        x = np.concatenate((data["full"], data["low"]))
        y = np.tile(data["labels"], 2)
        for seed in (11, 23, 47):
            model = JointModel.load(OLD / f"base-{seed}.npz")
            for value in model.params.values():
                value.flags.writeable = False
            if not references:
                write(
                    out / "model-results-started.json",
                    {"first": "base-11 reference CE", "TRAIN_only": True},
                )
            references[seed] = Reference(model, x, y, shared)
            save(out / f"base-reference-{seed}.npz", references[seed].arrays())
            if cpu() > 2.5:
                raise RuntimeError("shared CPU reserve exceeded")
        if cpu() > 2.5:
            raise RuntimeError("shared CPU reserve exceeded")
        meter = Meter(cpu())
        for arm in ("A", "N"):
            ledgers[arm] = WorkLedger(arm, 4_000_000_000)
            ledgers[arm].attribute_shared(shared)
        for seed_index, seed in enumerate((11, 23, 47)):
            for arm in ("A", "N") if seed_index % 2 == 0 else ("N", "A"):
                for kind in ("iid", "stratified"):
                    key = f"{arm}-{kind}-{seed}"
                    with meter.phase(arm, "gradient"):
                        model = JointModel.load(OLD / f"final-{key}.npz")
                        for value in model.params.values():
                            value.flags.writeable = False
                        models[key] = model
                        arrays, summary = gradient_measure(
                            model,
                            references[seed],
                            kind,
                            arm,
                            schedule[kind],
                            ledgers[arm],
                        )
                        save(out / f"gradient-{key}.npz", arrays)
                        report["gradient"][key] = summary
                        states[key] = service.state()
                        states[key]["generator"] = service.prepare(
                            model, OLD / "build/libjoint.so"
                        )
        # Exactly 12 models x 48 cohorts x 4 waves x 64 requests.
        if any(value + 11.5 > 15 for value in meter.totals().values()):
            raise RuntimeError(
                "complete remaining service/evidence CPU reservation refused"
            )
        for seed_index, seed in enumerate((11, 23, 47)):
            labels = (
                f"A-iid-{seed}",
                f"A-stratified-{seed}",
                f"N-iid-{seed}",
                f"N-stratified-{seed}",
            )
            for ci, rows in enumerate(groups):
                for wave in range(4):
                    for position in service.WILLIAMS[(wave + seed_index + ci) % 4]:
                        key = labels[position]
                        arm = key[0]
                        state = states[key]
                        if ledgers[arm].remaining_units < 64 * 19236:
                            raise RuntimeError("service operator admission")
                        with meter.phase(arm, "service"):
                            p, q, outputs, sizes, cost = service.batch(
                                state["generator"],
                                data["full"][rows],
                                611371 + 1009 * wave + 37 * ci + seed,
                            )
                            ledgers[arm].record(
                                "service",
                                units=cost["work_units"],
                                requests=64,
                                native_batches=1,
                            )
                        with meter.phase(arm, "record"):
                            service.capture(
                                state,
                                rows,
                                wave,
                                ci,
                                p,
                                q,
                                outputs,
                                sizes,
                                cost,
                                payloads,
                            )
        old = json.loads((OLD / "result.json").read_text())
        for key, state in states.items():
            arm, kind, seed = key.split("-")
            seed = int(seed)
            with meter.phase(arm, "readout"):
                arrays = request_readout(
                    state["p"],
                    state["q"],
                    data["labels"],
                    references[seed],
                    ledgers[arm],
                )
                for metric in (
                    "task_utility",
                    "joint_success",
                    "consistency",
                    "pixel_mse",
                    "greedy_joint_success",
                ):
                    np.testing.assert_allclose(
                        arrays[metric].mean(),
                        old["systems"][arm]["candidates"][f"{kind}-{seed}"]["train"][
                            metric
                        ],
                        rtol=1e-10,
                        atol=1e-12,
                    )
                save(out / f"requests-{key}.npz", arrays)
                readouts[key] = arrays
        report["all_source_mechanism"] = summarize(readouts, states, data, groups)
        report["CV_accepted_for_further_TRAIN"] = all(
            value["CV_variance"] < value["original_variance"]
            for key, value in report["gradient"].items()
            if key.startswith("N-")
        )
        report["status"] = (
            "complete; CV accepted for review"
            if report["CV_accepted_for_further_TRAIN"]
            else "complete; CV REJECTED"
        )
    except Exception:
        report.update(status="FAILED; sealed; no retry", error=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0)
        for key, state in states.items():
            if meter:
                started = cpu()
            save(
                out / f"service-{key}.npz",
                {
                    k: v
                    for k, v in state.items()
                    if isinstance(v, np.ndarray) and k not in ("p", "q")
                },
            )
            report["service"][key] = {
                "batches": state["batches"],
                "completed_batches": int(state["completed"].sum()),
            }
            if key not in readouts:
                save(out / f"partial-pq-{key}.npz", {"p": state["p"], "q": state["q"]})
            if meter:
                meter.own[key[0]] += cpu() - started
        write(out / "output-payloads.json", payloads)
        original = json.loads((OLD / "result.json").read_text())
        report["models_unchanged"] = all(
            model.digest()
            == original["systems"][key[0]]["candidates"][key[2:]]["digest"]
            for key, model in models.items()
        )
        if not report["models_unchanged"]:
            report["status"] = "FAILED model mutation; sealed"
        report.update(
            physical_cpu_before_final_receipt=cpu(),
            actual_units={arm: ledger.snapshot() for arm, ledger in ledgers.items()},
            common_units=shared.snapshot(),
            complete_cpu_each_arm=None if meter is None else meter.totals(),
            stage_cpu=None if meter is None else meter.stages,
            stored_bytes_before_receipt=sum(
                p.stat().st_size for p in out.iterdir() if p.is_file()
            ),
        )
        if (
            cpu() > 30
            or (meter and max(meter.totals().values()) > 15)
            or report["stored_bytes_before_receipt"] > 64 * 2**20
        ):
            report["status"] = "FAILED final cap; sealed; no retry"
        write(out / "result.json", report)
        final = {
            "status": report["status"],
            "physical_cpu_after_result": cpu(),
            "complete_arm_cpu_after_result": None if meter is None else meter.totals(),
            "stored_bytes": sum(p.stat().st_size for p in out.iterdir() if p.is_file()),
        }
        if (
            final["physical_cpu_after_result"] > 30
            or (meter and max(meter.totals().values()) > 15)
            or final["stored_bytes"] > 64 * 2**20
        ):
            final["status"] = report["status"] = "FAILED closing cap; sealed"
        write(out / "final-execution.json", final)
        print(
            json.dumps(
                {
                    **final,
                    "physical_cpu_after_final_write": cpu(),
                    "complete_arm_cpu_after_final_write": None
                    if meter is None
                    else meter.totals(),
                    "out": str(out),
                }
            )
        )
    return int(report["status"].startswith("FAILED"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "smoke", "run"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    if args.action == "freeze":
        write(
            args.out,
            {
                "sources": sources(),
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "plan_units": planned_units(),
            },
        )
    elif args.action == "smoke":
        assert json.loads(Path(args.freeze).read_text())["sources"] == sources()
        with (
            patch(
                "model.JointModel._forward",
                side_effect=AssertionError("smoke forbids predictions"),
            ),
            patch(
                "independent.data_v2.dataset",
                side_effect=AssertionError("smoke forbids reconstruction"),
            ),
            patch(
                "__main__.dataset",
                side_effect=AssertionError("smoke forbids reconstruction"),
            ),
            patch(
                "independent.native.NativeGenerator._call_batch",
                side_effect=AssertionError("smoke forbids native predictions"),
            ),
        ):
            quote = preflight()
            model = JointModel.load(OLD / "final-A-iid-11.npz")
            service.prepare(model, OLD / "build/libjoint.so")
            write(
                args.out,
                {
                    "status": "entry smoke passed",
                    "model_forward_calls": 0,
                    "dataset_calls": 0,
                    "quote": quote,
                    "sources": sources(),
                },
            )
        print("real entry smoke passed: no dataset construction or model forward")
    else:
        raise SystemExit(run(args.out, args.freeze))
