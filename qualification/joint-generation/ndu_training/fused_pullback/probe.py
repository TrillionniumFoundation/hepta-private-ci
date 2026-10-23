"""One frozen hand-only numerical/performance probe; no TRAIN entry exists."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback
from unittest.mock import patch

import numpy as np

from independent.accounting import WorkLedger
from model import JointModel
from ndu_training.cv_train_d2.budget import ROOT
from ndu_training.fused_pullback import hand, numeric, performance
from ndu_training.fused_pullback.kernel import gradient_work
from ndu_training.fused_pullback.provenance import verify_partitioned
from ndu_training.reinfer_d1.kernels import planned_units

HERE = Path(__file__).resolve().parent


def plan():
    return json.loads((HERE / "plan.json").read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def sources():
    old = json.loads((ROOT / "ndu_training/cv_train_d2/frozen-d2.json").read_text())[
        "sources"
    ]
    paths = (
        {ROOT / name for name in old}
        | set(HERE.glob("*.py"))
        | {HERE / "plan.json", HERE / "PROTOCOL.md"}
    )
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def quote():
    p = plan()
    q = WorkLedger("quote")
    work = 0
    for arm in ("A", "N"):
        for weighted in (False, True):
            for step in (64, 65):
                for mode in p["performance_modes"]:
                    reserve = max(
                        q.estimate_kernel(
                            **gradient_work(
                                tuple(p["dimensions"]),
                                arm,
                                64,
                                32,
                                weighted,
                                mode,
                                observed=step == 64,
                                fallback=fallback,
                            )
                        )
                        for fallback in (
                            None,
                            "observed",
                            "empty_moments",
                            "hidden_cancellation",
                            "mean_cancellation",
                        )
                    )
                    work += reserve * (
                        p["performance_waves"] * p["performance_repetitions_each_block"]
                        + 1
                    )
    return {
        "benchmark_upper_reservation_units": work,
        "one_hand_reference_build_units_reserve": planned_units()[
            "shared_reference_units_bound"
        ]
        // 3
        + 5_000_000,
        "numerical_update_comparison_reservation": 1_100_000_000,
        "total_reserved_units": work
        + planned_units()["shared_reference_units_bound"] // 3
        + 1_105_000_000,
        "benchmark_blocks": 8 * 4 * 4,
        "benchmark_calls": 8 * 4 * 4 * 16,
        "model_loads": 0,
        "TRAIN_constructions": 0,
        "service_requests": 0,
        "future_training_authorized": False,
    }


def provenance_check():
    visits, phases = [], []

    class FakeMeter:
        @contextmanager
        def phase(self, recipients, stage):
            phases.append({"recipients": recipients, "stage": stage})
            yield

    items = {"hand/TRAIN-inputs.npz": "common", "hand/base-reference-11.npz": "CV"}

    def fake_sha(path):
        visits.append({"path": str(path), "recipients": phases[-1]["recipients"]})
        return items[str(path)]

    partition = verify_partitioned(items, FakeMeter(), sha=fake_sha)
    assert visits[0]["recipients"] == ("A-plain", "N-plain", "A-CV", "N-CV")
    assert visits[1]["recipients"] == ("A-CV", "N-CV")
    return {
        "pass": True,
        "partition": partition,
        "hash_invocation_recipients": visits,
        "actual_file_io": False,
    }


def run(out, frozen_path):
    p, frozen = plan(), json.loads(Path(frozen_path).read_text())
    if (
        frozen["sources"] != sources()
        or frozen["quote"]["total_reserved_units"] >= p["operator_cap"]
    ):
        raise RuntimeError("source or declared-work admission mismatch")
    if any(
        os.environ.get(key) != "1"
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    ):
        raise RuntimeError("one-thread environment required")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write(
        HERE / "hand-d3-opened.json",
        {"out": str(out), "frozen_sha256": sha(frozen_path), "TRAIN": False},
    )
    ledger, vectors = WorkLedger("HAND-d3", p["operator_cap"]), {}
    report = {
        "status": "running",
        "hand_only": True,
        "numeric": {},
        "benchmark_blocks": [],
        "plan": p,
        "quote": frozen["quote"],
    }
    signal.signal(
        signal.SIGPROF,
        lambda *_: (_ for _ in ()).throw(RuntimeError("hand probe CPU cap")),
    )
    signal.setitimer(signal.ITIMER_PROF, 9.8)
    try:
        library = ROOT / "runs/codex-cloud-ndu-training-train-d1/build/libjoint.so"
        old_artifacts = json.loads((library.parents[1] / "artifacts.json").read_text())[
            "files"
        ]
        if sha(library) != old_artifacts["build/libjoint.so"]["sha256"]:
            raise ValueError("original NativeAdam library identity changed")
        report["CV_hash_recipient_check"] = provenance_check()
        # No actual weights, datasets, fitting helpers or training driver allowed.
        with (
            patch.object(
                JointModel,
                "load",
                side_effect=AssertionError("real model loading forbidden"),
            ),
            patch.object(
                JointModel,
                "fit_decoder",
                side_effect=AssertionError("fitting forbidden"),
            ),
            patch.object(
                JointModel,
                "supervised_step",
                side_effect=AssertionError("training forbidden"),
            ),
        ):
            models, bound, arrays, bind_cpu = hand.fixture(p, ledger)
            bind_units = ledger.snapshot()["stages"]["reference_bind"]["consumed_units"]
            before = {key: model.digest() for key, model in models.items()}
            numeric.run(
                models, bound, arrays, p, ledger, library, vectors, report["numeric"]
            )
            if not report["numeric"]["required_pass"]:
                raise RuntimeError(
                    "fixed hybrid/legacy numerical conditions FAILED; no timing rescue"
                )
            performance.benchmark(
                models["drifted"], bound, arrays, p, ledger, report["benchmark_blocks"]
            )
            report["conditional_projections"] = performance.projections(
                report["benchmark_blocks"], bind_cpu, bind_units, p, ledger
            )
            assert before == {key: model.digest() for key, model in models.items()}
            report["read_only_models_unchanged"] = True
            report["new_binding_cpu_one_hand_reference"] = bind_cpu
            report["actual_unit_inputs"] = {
                name: hashlib.sha256(value.tobytes()).hexdigest()
                for name, value in arrays.items()
            }
        report["status"] = (
            "complete HAND-only; raw failures retained; no TRAIN authority"
        )
    except Exception:
        report.update(
            status="FAILED; hand evidence retained; no tolerance change or automatic rerun",
            error=traceback.format_exc(),
        )
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0)
        with (out / "all-gradient-vectors.npz").open("xb") as stream:
            np.savez(stream, **vectors)
        report.update(
            actual_process_cpu_before_receipts=time.process_time(),
            ledger=ledger.snapshot(),
            actual_service_requests=0,
            actual_TRAIN_data_or_weight_loads=0,
        )
        if time.process_time() > 10 or ledger.consumed_units > p["operator_cap"]:
            report["status"] = "FAILED CPU/operator cap; retained"
        write(out / "result.json", report)
        write(
            out / "artifacts.json",
            {
                "files": {
                    path.name: {"sha256": sha(path), "bytes": path.stat().st_size}
                    for path in sorted(out.iterdir())
                    if path.is_file()
                }
            },
        )
        terminal = {
            "status": report["status"],
            "physical_cpu_before_terminal_receipt": time.process_time(),
            "units": ledger.consumed_units,
            "stored_bytes_before_terminal_receipt": sum(
                path.stat().st_size for path in out.iterdir() if path.is_file()
            ),
        }
        if (
            terminal["stored_bytes_before_terminal_receipt"] > p["storage_cap_bytes"]
            or time.process_time() > 10
        ):
            terminal["status"] = "FAILED final CPU/storage cap; retained"
        write(out / "final-execution.json", terminal)
        print(json.dumps({**terminal, "cpu_after_terminal_write": time.process_time()}))
    return int(terminal["status"].startswith("FAILED"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("quote", "freeze", "smoke", "probe"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    if args.action == "quote":
        write(args.out, quote())
    elif args.action == "freeze":
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--", str(HERE)], text=True
        )
        if dirty.strip():
            raise RuntimeError("commit source/protocol before freeze")
        write(
            args.out,
            {
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "sources": sources(),
                "quote": quote(),
            },
        )
    elif args.action == "smoke":
        frozen = json.loads(Path(args.freeze).read_text())
        assert frozen["sources"] == sources()
        assert frozen["quote"]["total_reserved_units"] < plan()["operator_cap"]
        write(
            args.out,
            {
                "status": "zero-result hand entry smoke passed",
                "model_or_input_constructions": 0,
                "quote": quote(),
                "frozen_sha256": sha(args.freeze),
            },
        )
        print("hand entry smoke passed without model/input construction")
    else:
        return run(args.out, args.freeze)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
