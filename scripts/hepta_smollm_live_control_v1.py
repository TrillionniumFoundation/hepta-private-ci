#!/usr/bin/env python3
"""Explicit original pilot child followed by in-budget live resource release.

The unchanged supervisor owns wait4, the 100 ms terminal observation and failure.
This entry never qualifies a model, issues credentials or changes model work.
"""

import argparse
import ctypes
import gc
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_smollm_execution_source_v1 as execution_source

PROFILE = "hepta-original-model-control-live-release-v1"
SCHEMA = "hepta-original-model-control-live-input-v1"
EXECUTION_SOURCE_PROFILE = os.environ.get("HEPTA_PAIRED_EXECUTION_PROFILE")
CHAIN_COMMIT = execution_source.selected_commit(
    "ad490ed4b1132a333159fd76702809fd248a4462", EXECUTION_SOURCE_PROFILE
)
RUNTIME_SHA = "65ccc6454befd96fa5ce1f5bdde2c56cb6cbb741cf495b8d24a758039f99f755"
PLAN_SHA = "01ec1a644f37b9fc7a4c6616f589768df97f8eed7a289b5de86afadaa7ce6165"
ROLES = (
    "candidate",
    "current-backbone",
    "fresh-budget-matched-lora",
    "budget-matched-full-tune",
    "randomized-rank-matched-lora",
)
RECEIPT = "live-control-release-v1.json"
FLAGS = dict(
    production_qualification=False, installation_authorized=False, reward_eligible=False
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def closed(value, fields):
    require(
        type(value) is dict and set(value) == set(fields.split()),
        "closed live-control fields required",
    )


def manifest(chain, plan):
    chain, plan = Path(chain).resolve(), Path(plan).resolve()
    execution_source.verify_selected(chain, EXECUTION_SOURCE_PROFILE)
    require(
        subprocess.check_output(
            ["git", "-C", str(chain), "rev-parse", "HEAD"], text=True
        ).strip()
        == CHAIN_COMMIT,
        "exact original observation checkout required",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(chain),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "formal",
            "config",
        ],
        check=True,
    )
    runtime = chain / "scripts/llm_runtime_pilot.py"
    require(
        sha(runtime) == RUNTIME_SHA and sha(plan) == PLAN_SHA,
        "original runtime and model plan bytes required",
    )
    value = json.loads(plan.read_bytes())
    require(
        value["training_steps"] == 10
        and value["runtime_source"] == RUNTIME_SHA
        and value["training_budget"] == dict(wall_seconds=1800, rss_bytes=16 * 1024**3)
        and value["inference_budget"] == dict(wall_seconds=600, rss_bytes=8 * 1024**3),
        "original model work and budgets required",
    )
    entry = Path(__file__).resolve()
    return dict(
        schema="hepta-original-model-control-live-entry-v1",
        profile=PROFILE,
        chain=dict(root=str(chain), commit=CHAIN_COMMIT),
        entry=dict(path=str(entry), sha256=sha(entry)),
        runtime=dict(path=str(runtime), sha256=RUNTIME_SHA),
        plan=dict(path=str(plan), sha256=PLAN_SHA, identity=identity(value)),
        training_budget=value["training_budget"],
        inference_budget=value["inference_budget"],
        **FLAGS,
    )


def request(entry, phase, role, materials, output, artifact=None):
    value = dict(
        schema=SCHEMA,
        profile=PROFILE,
        execution_entry=entry,
        phase=phase,
        role=role,
        materials=str(materials),
        output=str(output),
        artifact=str(artifact) if artifact else None,
        **FLAGS,
    )
    validate(value)
    return value


def validate(value):
    closed(
        value,
        "schema profile execution_entry phase role materials output artifact production_qualification installation_authorized reward_eligible",
    )
    require(
        value["schema"] == SCHEMA
        and value["profile"] == PROFILE
        and all(value[key] is False for key in FLAGS),
        "explicit unqualified live-control namespace required",
    )
    entry = value["execution_entry"]
    require(
        entry == manifest(entry["chain"]["root"], entry["plan"]["path"]),
        "frozen live-control entry changed",
    )
    require(
        value["phase"] in ("train", "evaluate")
        and value["role"] in ROLES
        and not (value["phase"] == "train" and value["role"] == "candidate"),
        "only original controls and original evaluations use this entry",
    )
    require(
        all(
            type(value[key]) is str and Path(value[key]).is_absolute()
            for key in ("materials", "output")
        ),
        "absolute original child paths required",
    )
    require(
        (value["artifact"] is None)
        if value["phase"] == "train"
        else (type(value["artifact"]) is str and Path(value["artifact"]).is_absolute()),
        "original artifact argument required",
    )
    return value


def process_identity():
    stat = Path("/proc/self/stat").read_text()
    return dict(pid=os.getpid(), birth_ticks=int(stat.rsplit(")", 1)[1].split()[19]))


def release():
    records = []
    libc = ctypes.CDLL(None)
    trim = libc.malloc_trim
    trim.argtypes, trim.restype = [ctypes.c_size_t], ctypes.c_int
    for name, operation in (
        ("live-model-cycle-release", gc.collect),
        ("live-model-allocator-trim", lambda: trim(0)),
    ):
        wall, cpu = time.monotonic_ns(), time.process_time_ns()
        result = operation()
        records.append(
            dict(
                stage=name,
                wall_ns=time.monotonic_ns() - wall,
                cpu_ns=time.process_time_ns() - cpu,
                result=result,
            )
        )
    return records


def execute(value):
    validate(value)
    sys.path.insert(0, str(Path(value["execution_entry"]["chain"]["root"]) / "scripts"))
    runtime = importlib.import_module("llm_runtime_pilot")
    require(
        Path(runtime.__file__).resolve()
        == Path(value["execution_entry"]["runtime"]["path"])
        and sha(runtime.__file__) == RUNTIME_SHA,
        "loaded original pilot module required",
    )
    directory = Path(value["output"])
    args = SimpleNamespace(
        materials=value["materials"],
        plan=value["execution_entry"]["plan"]["path"],
        output=value["output"],
        phase=value["phase"],
        role=value["role"],
        artifact=value["artifact"],
    )
    start, cpu_start = time.monotonic_ns(), time.process_time_ns()
    report = dict(
        schema="hepta-original-model-control-live-receipt-v1",
        profile=PROFILE,
        input_sha256=identity(value),
        execution_entry=value["execution_entry"],
        phase=value["phase"],
        role=value["role"],
        child_arguments=vars(args),
        process_before=process_identity(),
        original_child_returned=False,
        original_actual_before_sha256=None,
        original_actual_after_sha256=None,
        stages=[],
        errors=[],
        outcome="failed",
        **FLAGS,
    )
    primary = None
    try:
        # Returning from the original function removes its model/tensor locals.
        # An exceptional traceback may retain them; failure never attests release.
        runtime.child(args)
        report["original_child_returned"] = True
    except BaseException as error:
        primary = error
        report["primary_error"] = dict(
            type=type(error).__name__, message=str(error)[:256]
        )
        raise
    finally:
        secondary = []

        def capture(error):
            secondary.append(error)
            report["errors"].append(
                dict(type=type(error).__name__, message=str(error)[:256])
            )

        try:
            report["original_actual_before_sha256"] = sha(
                directory / "actual-receipt.json"
            )
        except BaseException as error:
            capture(error)
        release_start, release_cpu = time.monotonic_ns(), time.process_time_ns()
        try:
            report["stages"] = release()
        except BaseException as error:
            capture(error)
        report.update(
            release_wall_ns=time.monotonic_ns() - release_start,
            release_cpu_ns=time.process_time_ns() - release_cpu,
        )
        try:
            report["original_actual_after_sha256"] = sha(
                directory / "actual-receipt.json"
            )
            require(
                report["original_actual_before_sha256"]
                == report["original_actual_after_sha256"],
                "original actual receipt changed during release",
            )
            report["process_after"] = process_identity()
            require(
                report["process_after"] == report["process_before"],
                "live child identity changed",
            )
            report.update(
                process_wall_ns=time.monotonic_ns() - start,
                process_cpu_ns=time.process_time_ns() - cpu_start,
                process_peak_rss_bytes=resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * 1024,
                memory_scope="Linux process lifetime high-water; not a sum of stage peaks",
                cost_scope="original actual CPU excludes this release; original supervisor wait4 includes it",
                outcome="attempt-completed"
                if primary is None and not secondary
                else "failed",
            )
        except BaseException as error:
            capture(error)
        try:
            save(directory / RECEIPT, report)
        except BaseException as error:
            capture(error)
        if secondary:
            if primary is not None:
                for error in secondary:
                    primary.add_note(
                        "live-control secondary error: "
                        + type(error).__name__
                        + ": "
                        + str(error)[:256]
                    )
            else:
                raise secondary[0]


def verify(value, supervisor):
    validate(value)
    directory = Path(value["output"])
    report = json.loads((directory / RECEIPT).read_bytes())
    actual = json.loads((directory / "actual-receipt.json").read_bytes())
    budget = value["execution_entry"][
        "training_budget" if value["phase"] == "train" else "inference_budget"
    ]
    require(
        supervisor["outcome"] == "success"
        and type(supervisor["exit_code"]) is int
        and supervisor["exit_code"] == 0
        and supervisor["stop_reason"] is None
        and supervisor["waited_child_reaped"] is True
        and supervisor["owned_child_reap_resolved"] is True
        and supervisor["owned_child_echild_observed"] is False
        and supervisor["waited_child_observation_error"] is None
        and supervisor["budget"] == budget
        and supervisor["exit_observation_profile"]["profile"]
        == "linux-owned-exit-worker-pidfd-v4"
        and supervisor["exit_observation_profile"]["maximum_drain_ns"] == 100000000
        and supervisor["terminal_reconciliation_profile"]
        == "explicit-linux-owned-exit-worker-pidfd-v4",
        "unchanged original supervisor and terminal budget required",
    )
    require(
        report["schema"] == "hepta-original-model-control-live-receipt-v1"
        and report["profile"] == PROFILE
        and report["input_sha256"] == identity(value)
        and report["execution_entry"] == value["execution_entry"]
        and report["phase"] == value["phase"]
        and report["role"] == value["role"]
        and report["outcome"] == "attempt-completed"
        and report["original_child_returned"] is True
        and report["errors"] == []
        and all(report[key] is False for key in FLAGS)
        and report["process_before"] == report["process_after"]
        and report["original_actual_before_sha256"]
        == report["original_actual_after_sha256"]
        == sha(directory / "actual-receipt.json")
        and actual["schema"] == "llm-runtime-actual-child-v1"
        and actual["outcome"] == "success"
        and actual["phase"] == value["phase"]
        and actual["role"] == value["role"]
        and actual["experiment"] == value["execution_entry"]["plan"]["identity"]
        and actual["runtime_source"] == RUNTIME_SHA,
        "original child and live release receipt binding required",
    )
    require(
        [item["stage"] for item in report["stages"]]
        == ["live-model-cycle-release", "live-model-allocator-trim"]
        and all(
            type(item[key]) is int and item[key] >= 0
            for item in report["stages"]
            for key in ("wall_ns", "cpu_ns", "result")
        )
        and all(
            type(report[key]) is int and report[key] >= 0
            for key in (
                "process_wall_ns",
                "process_cpu_ns",
                "process_peak_rss_bytes",
                "release_wall_ns",
                "release_cpu_ns",
            )
        ),
        "actual bounded live release observations required",
    )
    return dict(
        path=str(directory / RECEIPT),
        sha256=sha(directory / RECEIPT),
        input_sha256=identity(value),
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    args = parser.parse_args()
    require(
        args.input.is_absolute()
        and args.input.stat().st_size <= 65536
        and sha(args.input) == args.input_sha256,
        "bounded unchanged explicit live-control input required",
    )
    execute(json.loads(args.input.read_bytes()))


if __name__ == "__main__":
    main()
