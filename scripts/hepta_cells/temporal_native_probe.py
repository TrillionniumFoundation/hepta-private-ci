"""Exercise trained temporal candidates through one frozen native HIA image.

This is an engineering interface probe. Its disclosed synthetic episodes are
never held-out source groups, and its different model sizes are not a controlled
kernel comparison. Each derived candidate retains its own immutable manifest.
"""

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np

from hepta_cell_joint_worker import sha
from qualify_hia_cell_joint import child, freeze, write
from .bundle import Bundle
from .lifecycle import CellOwner, Partition
from .temporal import TemporalConfig, TemporalKernel
from .task_observation import TaskLedger


def _variant(common, family, output, kind):
    """Freeze real trained weights without changing the common parent files."""
    output.mkdir()
    shutil.copytree(family / "native", output / "native")
    shutil.copy(family / "inputs.json", output / "inputs.json")
    manifest = copy.deepcopy(common)
    episodes = np.array(
        [
            [[0.25, -0.5, 0.75], [0.5, 0.25, 0.5]],
            [[-0.25, 0.5, 0.75], [-0.5, -0.25, 0.5]],
        ],
        dtype=np.float64,
    )
    actions = np.zeros((2, 1), dtype=np.float64)
    allowed = np.eye(2, dtype=bool)
    recipe = {
        "scope": "disclosed synthetic interface fixture, no B/C/D access",
        "episodes": episodes.tolist(),
        "actions": actions.tolist(),
        "allowed_mask": allowed.tolist(),
        "updates": 8,
        "learning_rate": 0.003,
        "gradient_norm_cap": 5.0,
        "kernel_kind": kind,
        "capacity_matched_comparison": False,
    }
    recipe_hash = write(output / "TRAINING_PLAN.json", recipe)
    models, training = {}, {}
    for cell in ("MEM", "PRED"):
        config = TemporalConfig(3, 1, 2, hidden_dim=4, seed=41, kind=kind)
        parent = TemporalKernel(cell, config)
        parent_identity = (parent.weights_sha256, parent.optimizer_sha256)
        try:
            candidate, receipt = parent.train_candidate(
                episodes,
                actions,
                allowed,
                updates=recipe["updates"],
                lr=recipe["learning_rate"],
                clip=recipe["gradient_norm_cap"],
            )
        except BaseException as error:
            write(
                output / (cell + "-TRAINING_FAILURE.json"),
                {
                    "error": f"{type(error).__name__}: {error}",
                    "receipt": getattr(error, "receipt", None),
                },
            )
            raise
        write(output / (cell + "-TRAINING_RECEIPT.json"), receipt)
        if parent_identity != (parent.weights_sha256, parent.optimizer_sha256):
            raise AssertionError("training changed the parent")
        if candidate.weights_sha256 == parent.weights_sha256:
            raise AssertionError("training did not change candidate weights")
        training[cell] = receipt
        old = Bundle(**common["models"][cell]["bundle"])
        parts = {
            **old.components,
            "base": candidate.kernel_sha256,
            "heads": candidate.heads_sha256,
            "composition": config.sha256,
        }
        bound = Bundle(cell + "-" + kind + "-trained-probe", 1, parts)
        checksum = candidate.checkpoint(
            output / (cell + ".npz"), candidate.initial_state("joint-run")
        )
        models[cell] = {
            "path": cell + ".npz",
            "sha256": checksum,
            "config": asdict(config),
            "bundle": bound.record(),
        }
    write(output / "TRAINING_RECEIPTS.json", training)
    manifest["models"] = models
    manifest["variant"] = {
        "parent_candidate_sha256": sha(family / "candidate.json"),
        "declared_changes": ["temporal_kernel", "trained_model_and_optimizer"],
        "training_plan_sha256": recipe_hash,
        "training_receipts_sha256": sha(output / "TRAINING_RECEIPTS.json"),
        "kernel_kind": kind,
        "role": "engineering interface candidate; no qualified Adopt",
    }
    for item in manifest["files"]:
        if item["root"] == "artifacts":
            item["sha256"] = sha(output / item["path"])
    manifest["files"].extend(
        {"root": "artifacts", "path": name, "sha256": sha(output / name)}
        for name in (
            "TRAINING_PLAN.json",
            "TRAINING_RECEIPTS.json",
            "MEM-TRAINING_RECEIPT.json",
            "PRED-TRAINING_RECEIPT.json",
        )
    )
    manifest["claims"]["native_runtime_qualified"] = False
    write(output / "candidate.json", manifest)
    return manifest


def _exercise(manifest, output):
    candidate, database = output / "candidate.json", output / "owner.sqlite"
    data = json.loads((output / "inputs.json").read_text())
    partition = manifest["partition"]
    checks, observations, resources = [], [], {}
    boot = Path("/proc/sys/kernel/random/boot_id").read_bytes()
    ledger = TaskLedger.create(
        output / "task-observations.sqlite",
        candidate_sha256=sha(candidate),
        clock_id=manifest["device"]["host_identity_sha256"]
        + ":"
        + hashlib.sha256(boot).hexdigest(),
        tasks=[
            dict(
                task_id=cell,
                cell=cell,
                phase="engineering-interface",
                arm=manifest["variant"]["kernel_kind"],
                source_group="disclosed-fixture-not-independent",
            )
            for cell in ("MEM", "PRED")
        ],
    )
    for cell in ("MEM", "PRED"):
        ledger.accept(cell)
    for cell in ("MEM", "PRED"):
        ledger.start(cell)
        model = manifest["models"][cell]
        kernel, state = TemporalKernel.restore_checkpoint(
            output / model["path"],
            expected_sha256=model["sha256"],
            cell_id=cell,
            config=TemporalConfig(**model["config"]),
        )
        training = json.loads((output / "TRAINING_RECEIPTS.json").read_text())[cell]
        if (
            kernel.weights_sha256 != training["candidate_weights_sha256"]
            or kernel.optimizer_sha256 != training["candidate_optimizer_sha256"]
        ):
            raise AssertionError("cold checkpoint lost weights or Adam state")
        resources[cell] = kernel.resources(state)
        request = {
            "request_id": "probe-observe",
            "cell_id": cell,
            "operation": "step",
            "payload": {
                "operation": "observe",
                "cursor": 0,
                "observation": data["observation"],
            },
        }
        observed, cost = child(candidate, database, request, output, cell + "-observe")
        observations.append(copy.deepcopy(cost))
        if observed["result"]["output"]["cell"]["cursor"] != 1:
            raise AssertionError("native observation did not advance real state")
        state = kernel.observe(
            state, data["observation"], episode_id="joint-run", cursor=0
        )
        expected = kernel.predict(
            state, data["action"], episode_id="joint-run"
        ).tolist()
        request.update(
            request_id="probe-predict",
            payload={"operation": "predict", "action": data["action"]},
        )
        predicted, cost = child(candidate, database, request, output, cell + "-predict")
        observations.append(copy.deepcopy(cost))
        if predicted["result"]["output"]["cell"]["logits"] != expected:
            raise AssertionError("native result differs from trained kernel")
        replay, cost = child(
            candidate, database, request, output, cell + "-cold-readback"
        )
        observations.append(copy.deepcopy(cost))
        if replay["result"] != predicted["result"]:
            raise AssertionError("cold replay replaced the original receipt")
        request["request_id"] = "probe-new-cold-predict"
        fresh, cost = child(candidate, database, request, output, cell + "-cold-new")
        observations.append(copy.deepcopy(cost))
        if (
            fresh["result"]["output"]["cell"]["logits"] != expected
            or fresh["result"]["sequence"] != 3
        ):
            raise AssertionError("new cold invocation lost persistent state")
        owner = CellOwner(database)
        try:
            restored = owner.checkpoint(Partition(**partition, cell_id=cell))["state"]
            if restored != state:
                raise AssertionError("durable owner state differs from trained kernel")
        finally:
            owner.close()
        request["payload"]["action"] = [1.0]
        conflict = child(
            candidate, database, request, output, cell + "-conflict", reject=True
        )
        observations.append(copy.deepcopy(conflict))
        if (
            "request ID is already bound to different arguments or epoch"
            not in conflict["stderr"]
        ):
            raise AssertionError("request failed for a reason other than conflict")
        owner = CellOwner(database)
        try:
            if (
                owner.checkpoint(Partition(**partition, cell_id=cell))["state"]
                != restored
            ):
                raise AssertionError("conflicting request changed durable state")
        finally:
            owner.close()
        checks.extend(
            cell + ":" + name
            for name in (
                "immutable-parent-training",
                "checkpoint-weights-and-adam",
                "native-trained-kernel",
                "exact-cold-replay",
                "new-cold-state",
                "conflicting-request-refused",
            )
        )
        final = output / (cell + "-TASK-RESULT.json")
        write(
            final,
            {
                "cell": cell,
                "candidate_sha256": sha(candidate),
                "checks": [name for name in checks if name.startswith(cell + ":")],
                "state": restored,
                "scope": "synthetic interface probe only",
            },
        )
        ledger.finish(cell, final, outcome="success")
    task_observations = ledger.report()
    write(output / "TASK_OBSERVATIONS.json", task_observations)
    return {
        "checks": checks,
        "subprocess_observations": observations,
        "model_resources": resources,
        "candidate_sha256": sha(candidate),
        "native_image_sha256": manifest["native"]["image_sha256"],
        "task_observations_sha256": sha(output / "TASK_OBSERVATIONS.json"),
    }


def run(hia_root, output):
    started = time.perf_counter_ns()
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hepta.temporal-native-probe-plan.v1",
        "kernels": ["gru", "cfc", "diag_ssm"],
        "seed": 41,
        "updates_per_cell": 8,
        "scope": "engineering interface/training/cold-recovery probe",
        "research_execution": None,
        "research_result": None,
        "independent_source_groups": 0,
        "qualified_adopt_count": 0,
        "stop_on_first_failure": True,
    }
    write(output / "PLAN.json", plan)
    family = output / "common"
    rows = []
    try:
        common, build, _ = freeze(hia_root.resolve(), family)
        for kind in plan["kernels"]:
            destination = output / kind
            row = {"kind": kind, "status": "STARTED", "result": None}
            rows.append(row)
            variant = _variant(common, family, destination, kind)
            originals = {
                item["path"]: sha(destination / item["path"])
                for item in variant["files"]
                if item["root"] == "artifacts"
            }
            result = _exercise(variant, destination)
            if originals != {name: sha(destination / name) for name in originals}:
                raise AssertionError("immutable candidate originals changed")
            row.update(status="PASS_INTERFACE_ONLY", result=result)
            write(destination / "RESULT.json", row)
    except BaseException as error:
        write(
            output / "FAILURE.json",
            {
                "error": f"{type(error).__name__}: {error}",
                "rows": rows,
                "wall_ns": time.perf_counter_ns() - started,
                "research_result": None,
            },
        )
        raise
    report = {
        "schema": "hepta.temporal-native-probe.v1",
        "status": "PASS_INTERFACE_ONLY",
        "source_commit": common["source_identity"]["cells"]["head"],
        "source_tree": common["source_identity"]["cells"]["tree"],
        "common_candidate_sha256": sha(family / "candidate.json"),
        "native_image_sha256": common["native"]["image_sha256"],
        "shared_build": build,
        "rows": rows,
        "wall_ns": time.perf_counter_ns() - started,
        "capacity_matched": False,
        "research_execution": None,
        "research_result": None,
        "qualified_adopt_count": 0,
        "independent_source_groups": 0,
        "physical_energy_joules": None,
        "process_tree_peak_rss_bytes": None,
        "runtime_transport": "local worker subprocess; native HIA image executed",
        "same_runtime_daemon_qualification": None,
    }
    write(output / "RESULT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hia-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.hia_root, args.output.resolve())
    print(json.dumps({"status": result["status"], "kernels": len(result["rows"])}))


if __name__ == "__main__":
    main()
