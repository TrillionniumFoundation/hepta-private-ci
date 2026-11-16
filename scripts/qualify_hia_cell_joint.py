#!/usr/bin/env python3
"""Execute one frozen native-HIA/GRU owner candidate, with real cold processes.

The local subprocess lane is explicitly distinct from the native runtime lane.
This bounded integration fixture claims neither learning benefit nor production.
"""

from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

from hepta_cell_joint_worker import device, load_candidate, sha
from hepta_cells.bundle import Bundle, REQUIRED, OPTIONAL
from hepta_cells.component_types import Budget, Partition, PendingExecution, digest
from hepta_cells.hia_component import HiaCellComponent
from hepta_cells.lifecycle import CellOwner
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


def write(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def freeze(hia_root, output):
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        "joint_builder", hia_root / "tools/cell_bridge_native.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    build = module.build_native_bridge(hia_root, output / "native")
    dataset = {
        "scope": "integration fixture, no learning or business-effect claim",
        "observation": [0.25, -0.5, 0.75],
        "action": [0.0],
    }
    data_hash = write(output / "inputs.json", dataset)
    config = TemporalConfig(3, 1, 2, hidden_dim=4, seed=41)
    models = {}
    for cell in ("MEM", "PRED"):
        kernel = TemporalKernel(cell, config)
        model_hash = kernel.checkpoint(
            output / (cell + ".npz"), kernel.initial_state("joint-run")
        )
        parts = {
            key: digest(
                {"field": key, "profile": "joint-gru-fixture-v1", "data": data_hash}
            )
            for key in REQUIRED
        }
        parts.update({key: None for key in OPTIONAL})
        parts.update(
            base=kernel.kernel_sha256,
            heads=kernel.heads_sha256,
            composition=config.sha256,
        )
        models[cell] = {
            "path": cell + ".npz",
            "sha256": model_hash,
            "config": asdict(config),
            "bundle": Bundle(cell + "-baseline", 1, parts).record(),
        }
    cells_root = Path(__file__).resolve().parent.parent
    locations = []
    for package in ("hepta_cells", "hepta_pred1"):
        locations += [
            ("cells", cells_root, p)
            for p in (cells_root / "scripts" / package).glob("*.py")
        ]
    locations += [
        ("cells", cells_root, cells_root / "scripts" / name)
        for name in (
            "hepta_cell_joint_worker.py",
            "hepta_cell_campaign_worker.py",
            "runtime_stdio.py",
            "runtime_process_contract.py",
            "runtime_process_bridge.py",
            "qualify_runtime_process_bridge.py",
            "qualify_runtime_campaign.py",
            "package_hia_cell_candidate.py",
            "verify_hepta_maintenance_cycle.py",
            "refreeze_joint_worker.py",
        )
    ]
    locations += [("cells", cells_root, Path(__file__).resolve())]
    compiler_paths = (
        subprocess.check_output(
            ["git", "-C", str(hia_root), "ls-files", "-z", "--", "hepta"], timeout=10
        )
        .decode()
        .split("\0")
    )
    locations += [("hia", hia_root, hia_root / p) for p in compiler_paths if p]
    locations += [
        ("hia", hia_root, hia_root / p)
        for p in (
            "tools/cell_bridge_native.py",
            "examples/hia_cell_bridge/continuation.hepta",
            "pyproject.toml",
            "docs/HIA_CORE_LOWERING_ABI.json",
            "docs/HIA_CORE_EMITTER_ABI.json",
            "docs/HIA_BYTE_WRAPPER_ABI.json",
            "docs/HIA_MACHINE_OBJECT_ABI.json",
        )
    ]
    locations += [
        ("artifacts", output, output / p)
        for p in (
            "MEM.npz",
            "PRED.npz",
            "inputs.json",
            "native/cell_bridge.so",
            "native/build.json",
        )
    ]
    files = [
        {"root": name, "path": str(path.relative_to(root)), "sha256": sha(path)}
        for name, root, path in sorted(
            locations, key=lambda item: (item[0], str(item[2]))
        )
    ]
    # Retain the exact executed source bytes. Source edits made after this run
    # must not erase the provenance needed to review this candidate.
    for item in files:
        if item["root"] == "artifacts":
            continue
        source_root = cells_root if item["root"] == "cells" else hia_root
        retained = output / "executed-source" / item["root"] / item["path"]
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / item["path"], retained)
        assert sha(retained) == item["sha256"]
    manifest = {
        "schema": "hepta.joint-cell-candidate.v1",
        "hia_root": str(hia_root),
        "source_bases": {
            "hia_compiler": build["compiler_commit"],
            "cells": "bb34e07389ad75d3b4629b63b0af0ee46f9b9594",
            "runtime": "5f7f03a1f22905789371ce0e181a1a0f013beca9",
        },
        "source_binding": "complete listed execution sources and artifacts; new files by SHA256",
        "runtime_execution": "local subprocess control; native runtime lane requires separate same-candidate execution",
        "device": device(),
        "files": files,
        "models": models,
        "native": {
            "image": "native/cell_bridge.so",
            "image_sha256": build["image_sha256"],
            "source_sha256": build["source_sha256"],
        },
        "partition": {
            "principal_id": "qualification",
            "agent_id": "joint-owner",
            "run_id": "joint-run",
        },
        "budget": asdict(Budget(max_elapsed_ms=5000)),
        "total_work_units": 1000000,
        "claims": {
            "whole_stack_qualified": False,
            "native_runtime_qualified": False,
            "learning_benefit": False,
            "production_ready": False,
        },
    }
    write(output / "candidate.json", manifest)
    return manifest, build, dataset


def child(candidate, database, request, output, label, *, reject=False):
    started = time.perf_counter_ns()
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).with_name("hepta_cell_joint_worker.py")),
        "--candidate",
        str(candidate),
        "--database",
        str(database),
    ]
    result = subprocess.run(
        command,
        input=json.dumps(request).encode(),
        capture_output=True,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    record = {
        "request": request,
        "exit_code": result.returncode,
        "wall_ns": time.perf_counter_ns() - started,
        "stdout": result.stdout.decode(),
        "stderr": result.stderr.decode(),
    }
    write(output / (label + ".json"), record)
    if reject:
        assert result.returncode != 0, label
        return record
    assert result.returncode == 0, record
    return json.loads(record["stdout"]), record


def run(hia_root, output):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    manifest, build, data = freeze(hia_root, output)
    candidate, database = output / "candidate.json", output / "owner.sqlite"
    candidate_hash = sha(candidate)
    records, checks = [], []
    for cell in ("MEM", "PRED"):
        request = {
            "request_id": "A-observe",
            "cell_id": cell,
            "operation": "step",
            "payload": {
                "operation": "observe",
                "cursor": 0,
                "observation": data["observation"],
            },
        }
        observed, cost = child(candidate, database, request, output, cell + "-observe")
        records.append(cost)
        assert observed["result"]["output"]["cell"]["cursor"] == 1
        request.update(
            request_id="B-predict",
            payload={"operation": "predict", "action": data["action"]},
        )
        predicted, cost = child(candidate, database, request, output, cell + "-predict")
        records.append(cost)
        model = manifest["models"][cell]
        kernel, state = TemporalKernel.restore_checkpoint(
            output / model["path"],
            expected_sha256=model["sha256"],
            cell_id=cell,
            config=TemporalConfig(**model["config"]),
        )
        state = kernel.observe(
            state, data["observation"], episode_id="joint-run", cursor=0
        )
        expected = kernel.predict(
            state, data["action"], episode_id="joint-run"
        ).tolist()
        assert predicted["result"]["output"]["cell"]["logits"] == expected
        repeated, cost = child(
            candidate, database, request, output, cell + "-cold-original-readback"
        )
        records.append(cost)
        assert repeated["result"] == predicted["result"]
        request["request_id"] = "C-new-predict"
        fresh, cost = child(
            candidate, database, request, output, cell + "-cold-new-task"
        )
        records.append(cost)
        assert fresh["result"]["output"]["cell"]["logits"] == expected
        assert fresh["result"]["sequence"] == 3
        request["payload"]["action"] = [1.0]
        child(
            candidate,
            database,
            request,
            output,
            cell + "-request-conflict",
            reject=True,
        )
        checks += [
            cell + ":native-to-real-gru",
            cell + ":exact-cold-replay",
            cell + ":new-cold-inference",
            cell + ":changed-request-refused",
        ]
    value, binding, roots, native = load_candidate(candidate)
    model = value["models"]["MEM"]
    kernel, _ = TemporalKernel.restore_checkpoint(
        output / model["path"],
        expected_sha256=model["sha256"],
        cell_id="MEM",
        config=TemporalConfig(**model["config"]),
    )
    partition = Partition(**value["partition"], cell_id="MEM")
    fault_db = output / "reply-loss.sqlite"
    owner = CellOwner(fault_db)
    inner = TemporalComponent(kernel, Bundle(**model["bundle"]), "joint-run")

    class InterruptedReply:
        def __getattr__(self, name):
            return getattr(native, name)

        def resume(self, *args, **kwargs):
            raise OSError("controlled interruption after real Cell result was retained")

    component = HiaCellComponent(
        owner,
        inner,
        InterruptedReply(),
        candidate_sha256=binding,
        image_sha256=manifest["native"]["image_sha256"],
    )
    owner.create(partition, component, budget=Budget(**value["budget"]))
    payload = {"operation": "observe", "cursor": 0, "observation": data["observation"]}
    try:
        owner.step(partition, component, "lost-reply", payload)
        raise AssertionError("interrupted native reply accepted")
    except PendingExecution:
        pass
    assert owner.status(partition)["pending"] == ["lost-reply"]
    assert component.continuation_status(partition, "lost-reply")[
        "cell_result_retained"
    ]
    owner.close()
    native.close()
    request = {
        "request_id": "lost-reply",
        "cell_id": "MEM",
        "operation": "readback",
        "payload": None,
    }
    child(
        candidate,
        fault_db,
        {**request, "operation": "cancel"},
        output,
        "fault-cancel-before-result",
    )
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                child,
                candidate,
                fault_db,
                request,
                output,
                "fault-cold-original-result-" + str(i),
            )
            for i in range(2)
        ]
        concurrent = [future.result() for future in futures]
    (recovered, cost), (also_recovered, other_cost) = concurrent
    records.extend((cost, other_cost))
    assert recovered["result"] == also_recovered["result"]
    assert recovered["result"]["sequence"] == 1
    assert recovered["result"]["output"]["cell"]["cursor"] == 1
    assert recovered["continuation"]["phase"] == "completed"
    checks += [
        "retained-result-before-caught-reply-error",
        "cold-hia-resume-original-result",
        "concurrent-readback-one-terminal",
        "late-result-preserved-after-cancel-request",
    ]
    crash_program = r"""
import os, sys
from pathlib import Path
from hepta_cell_joint_worker import load_candidate
from hepta_cells.bundle import Bundle
from hepta_cells.component_types import Budget, Partition
from hepta_cells.hia_component import HiaCellComponent
from hepta_cells.lifecycle import CellOwner
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent
v, digest, roots, native = load_candidate(sys.argv[1]); model = v["models"]["MEM"]
k, _ = TemporalKernel.restore_checkpoint(roots["artifacts"] / model["path"], expected_sha256=model["sha256"], cell_id="MEM", config=TemporalConfig(**model["config"]))
p = Partition(**v["partition"], cell_id="MEM"); owner = CellOwner(sys.argv[2])
class HardDeath:
    def __getattr__(self, name): return getattr(native, name)
    def resume(self, *args, **kwargs): os._exit(23)
c = HiaCellComponent(owner, TemporalComponent(k, Bundle(**model["bundle"]), p.run_id), HardDeath(), candidate_sha256=digest, image_sha256=v["native"]["image_sha256"])
owner.create(p, c, budget=Budget(**v["budget"]))
owner.step(p, c, "hard-death", {"operation":"observe", "cursor":0, "observation":[0.25,-0.5,0.75]})
"""
    crash_db = output / "hard-death.sqlite"
    dead = subprocess.run(
        [sys.executable, "-B", "-c", crash_program, str(candidate), str(crash_db)],
        capture_output=True,
        timeout=30,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).parent),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    write(
        output / "hard-death-original.json",
        {
            "exit_code": dead.returncode,
            "stdout": dead.stdout.decode(),
            "stderr": dead.stderr.decode(),
            "program": crash_program,
        },
    )
    assert dead.returncode == 23
    hard = child(
        candidate,
        crash_db,
        {
            "request_id": "hard-death",
            "cell_id": "MEM",
            "operation": "readback",
            "payload": None,
        },
        output,
        "hard-death-cost-unknown",
        reject=True,
    )
    hard_result = json.loads(hard["stdout"])
    assert hard_result["status"] == "pending" and hard_result["owner"]["sequence"] == 0
    assert hard_result["continuation"]["cell_result_retained"]
    checks.append("hard-process-death-retains-result-and-unknown-cost-reservation")
    value, binding, roots, native = load_candidate(candidate)
    unknown_db = output / "unknown.sqlite"
    owner = CellOwner(unknown_db)
    inner = TemporalComponent(kernel, Bundle(**model["bundle"]), "joint-run")

    def interrupted(*_):
        raise OSError("controlled interruption without retained result")

    inner.step = interrupted
    component = HiaCellComponent(
        owner,
        inner,
        native,
        candidate_sha256=binding,
        image_sha256=manifest["native"]["image_sha256"],
    )
    owner.create(partition, component, budget=Budget(**value["budget"]))
    try:
        owner.step(partition, component, "unknown", payload)
        raise AssertionError("missing outcome accepted")
    except PendingExecution:
        pass
    owner.close()
    native.close()
    request = {
        "request_id": "unknown",
        "cell_id": "MEM",
        "operation": "readback",
        "payload": None,
    }
    negative = child(
        candidate, unknown_db, request, output, "unknown-cold-readback", reject=True
    )
    assert json.loads(negative["stdout"])["status"] == "pending"
    request["operation"] = "cancel"
    cancelled, _ = child(
        candidate, unknown_db, request, output, "unknown-cancel-request"
    )
    assert cancelled["continuation"]["phase"] == "cancel_requested"
    repeated, _ = child(candidate, unknown_db, request, output, "unknown-cancel-repeat")
    assert repeated["result"] == cancelled["result"]
    checks += ["unknown-no-auto-replay", "cancellation-not-completion"]
    bad = json.loads(candidate.read_text())
    bad["native"]["image_sha256"] = "a" * 64
    write(output / "wrong-image.json", bad)
    request = {
        "request_id": "wrong-image",
        "cell_id": "MEM",
        "operation": "status",
        "payload": None,
    }
    child(
        output / "wrong-image.json",
        database,
        request,
        output,
        "wrong-image-refused",
        reject=True,
    )
    checks.append("changed-native-image-binding-refused")
    load_candidate(candidate)[3].close()
    assert sha(candidate) == candidate_hash
    durations = sorted(r["wall_ns"] for r in records)
    import math

    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "schema": "hepta.native-hia-real-cell-joint-observation.v1",
        "candidate_sha256": candidate_hash,
        "checks_passed": checks,
        "candidate_sources_unchanged": True,
        "scope": "one frozen local-subprocess integration fixture; actual native HIA and real MEM/PRED GRUs",
        "cost": {
            "wall_ns": time.perf_counter_ns() - wall,
            "parent_cpu_ns": time.process_time_ns() - cpu,
            "child_cpu_seconds": usage.ru_utime + usage.ru_stime,
            "child_peak_rss_kib": usage.ru_maxrss,
            "cold_process_samples": len(durations),
            "cold_process_p95_ns": durations[math.ceil(0.95 * len(durations)) - 1],
            "cold_process_p99_ns": durations[math.ceil(0.99 * len(durations)) - 1],
            "quantile_scope": "empirical nearest-rank of this small fixture only",
            "compile_wall_ns": build["compile_wall_ns"],
            "energy_joules": None,
            "max_inflight": 1,
        },
        "claims": {
            "native_hia_real_cell_local_bridge": True,
            "native_runtime_qualified": False,
            "independent_learning_benefit": False,
            "full_cost_qualified": False,
            "ordinary_daemon_adoption": False,
            "production_ready": False,
        },
        "remaining_unknown": [
            "hard process death before original elapsed cost publication retains reservation"
        ],
    }
    write(output / "RESULT.json", result)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hia-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(run(args.hia_root.resolve(), args.output.resolve()), sort_keys=True)
    )
