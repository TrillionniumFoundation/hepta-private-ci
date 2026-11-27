"""Inspect retained checkpoints and arrays; no Torch or numerical solver calls."""

import argparse
import hashlib
import io
import json
import math
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import numpy as np
from ptzip import Tensor, load_checkpoint

NAMES = ("active", "content", "phase_mass", "phase_content")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fp(value):
    if isinstance(value, Tensor):
        return {
            "kind": "tensor",
            "device": value.device,
            "layout": value.layout,
            "dtype": value.dtype,
            "shape": list(value.shape),
            "stride": list(value.stride),
            "offset": value.offset,
            "sha256": digest(value.array.tobytes(order="C")),
        }
    if isinstance(value, dict):
        return {
            "kind": "dict",
            "items": [
                (fp(k), fp(v))
                for k, v in sorted(
                    value.items(),
                    key=lambda item: (type(item[0]).__name__, str(item[0])),
                )
            ],
        }
    if isinstance(value, (tuple, list)):
        return {"kind": type(value).__name__, "items": [fp(v) for v in value]}
    require(
        type(value) in (str, int, float, bool, type(None)),
        "primitive checkpoint metadata",
    )
    return (
        {"kind": "float", "hex": value.hex()}
        if type(value) is float
        else {"kind": type(value).__name__, "value": value}
    )


def canonical(value):
    return json.dumps(fp(value), sort_keys=True, separators=(",", ":"))


def tensor(raw):
    raw = np.ascontiguousarray(raw)
    return Tensor(
        raw,
        raw.shape,
        tuple(x // raw.itemsize for x in raw.strides),
        0,
        "torch.float64",
        False,
    )


def read_arrays(path):
    with np.load(path, allow_pickle=False) as stored:
        data = {name: stored[name].copy() for name in stored.files}
    require(
        all(
            value.dtype == np.float64 and np.isfinite(value).all()
            for value in data.values()
        ),
        "finite retained FP64 arrays",
    )
    return data


def bound(actual, expected, absolute, relative, reason):
    delta = np.abs(np.asarray(actual) - np.asarray(expected))
    ratios = delta / (absolute + relative * np.abs(expected))
    require(bool(np.all(ratios <= 1)), reason)
    return {
        "maximum_absolute_error": float(delta.max()),
        "maximum_mixed_gate_ratio": float(ratios.max()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--frozen-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    require("torch" not in sys.modules, "no Torch import")
    archive_raw = (args.root / "ORIGINAL.zip").read_bytes()
    require(
        digest(archive_raw)
        == "31cca7713e060283efc00f55792cb5a30c032355244110836800241a8b46311f",
        "original artifact SHA",
    )
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        require(
            len(archive.infolist()) == 66 and archive.testzip() is None,
            "all66 artifact CRCs",
        )
        require(len(set(archive.namelist())) == 66, "unique archive members")
        for name in archive.namelist():
            require(
                archive.read(name) == (args.root / "raw" / name).read_bytes(),
                "loose artifact bytes " + name,
            )
    baseline_raw = args.baseline.read_bytes()
    require(
        digest(baseline_raw)
        == "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e",
        "frozen old-operator archive SHA",
    )
    with tarfile.open(fileobj=io.BytesIO(baseline_raw), mode="r:gz") as archive:
        raw = archive.extractfile(
            next(
                item
                for item in archive.getmembers()
                if item.name.endswith("numpy001/ARRAYS.npz")
            )
        ).read()
    require(
        digest(raw)
        == "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305",
        "old operator array SHA",
    )
    with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
        baseline = {name: stored[name].copy() for name in stored.files}
    root = args.root / "raw" / "adam-resume" / "protocol"
    result = json.loads((root / "RESULT.json").read_text())
    source = json.loads((args.root / "raw" / "adam-resume-source.json").read_text())
    frozen = json.loads(args.frozen_source.read_text())
    require(
        source["source_commit"] == "994def0b188c5105d0ceb9ace281af7f4bd0e3b2",
        "exact admitted source",
    )
    require(
        source["source_sha256"] == frozen["source_sha256"]
        and source["prefrozen_inventory_sha256"]
        == digest(args.frozen_source.read_bytes()),
        "source13 and inventory binding",
    )
    require(
        result["status"] == "PASS"
        and result["error"] is None
        and all(row["passed"] for row in result["checks"]),
        "all recorded producer checks true",
    )
    states = {}
    identities = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and (
            path.suffix == ".pt" or path.name.endswith(".pt.pending")
        ):
            state = load_checkpoint(path.read_bytes())
            states[str(path.relative_to(root))] = state
            identities.append(
                {
                    "path": str(path.relative_to(root)),
                    "bytes": path.stat().st_size,
                    "sha256": digest(path.read_bytes()),
                    "logical_sha256": digest(canonical(state).encode()),
                }
            )
    require(len(states) == 17, "all17 PT/pending payloads read")
    exact_comparisons = []

    def exact(left, right, reason):
        require(canonical(left) == canonical(right), reason)
        exact_comparisons.append(reason)

    for geometry in ("uniform", "graded"):
        c1 = states[geometry + "-continuous/step1.pt"]
        c2 = states[geometry + "-continuous/state.pt"]
        first = states[geometry + "-first/state.pt"]
        resume = states[geometry + "-resumed/state.pt"]
        exact(c1, first, geometry + " complete step1")
        exact(c2, resume, geometry + " complete step2")
        full = json.loads((root / (geometry + "-FULLSTATE.json")).read_text())
        require(
            json.dumps(fp(c2), sort_keys=True)
            == json.dumps(full["continuous"], sort_keys=True),
            "native continuous full fingerprint",
        )
        require(
            json.dumps(fp(resume), sort_keys=True)
            == json.dumps(full["resumed"], sort_keys=True),
            "native resumed full fingerprint",
        )
        for state in (c1, c2, first, resume):
            require(state["source"] == source, "all state sources")
            require(
                state["cursor"] == state["step"] in (1, 2),
                "integer completed step cursor",
            )
            for i, name in enumerate(NAMES):
                require(
                    np.array_equal(
                        state["original_inputs"][name].array,
                        baseline[geometry + "_input" + str(i)],
                    ),
                    "original input law bytes",
                )
        c_arrays = read_arrays(root / (geometry + "-continuous/ARRAYS.npz"))
        r_arrays = read_arrays(root / (geometry + "-resumed/ARRAYS.npz"))
        for name in c_arrays:
            if name.startswith("next_"):
                require(
                    c_arrays[name].tobytes() == r_arrays[name].tobytes(),
                    geometry + " next exact " + name,
                )
        cr = json.loads((root / (geometry + "-continuous/RESULT.json")).read_text())
        rr = json.loads((root / (geometry + "-resumed/RESULT.json")).read_text())
        require(
            next(row for row in cr["records"] if row["label"] == "next")
            == next(row for row in rr["records"] if row["label"] == "next"),
            geometry + " next complete record exact",
        )
    old = states["uniform-first/state.pt"]
    bad = states["omit-adam.pt"]
    require(
        set(old) - set(bad) == {"adam"} and set(bad) - set(old) == set(),
        "omit only Adam",
    )
    exact({key: old[key] for key in bad}, bad, "omit control other fields exact")
    require(
        (root / "crash-published.pt").read_bytes()
        == (root / "uniform-first/state.pt").read_bytes(),
        "process crash preserves old published bytes",
    )
    exact(states["crash-published.pt"], old, "crash published remains full step1")
    exact(
        states["crash-published.pt.pending"],
        states["uniform-continuous/state.pt"],
        "crash pending is complete continuous step2",
    )
    require(
        (root / "crash-published.pt.pending").read_bytes()
        != (root / "crash-published.pt").read_bytes(),
        "pending new distinct bytes",
    )
    records, updates = [], []
    for entry in result["actors"]:
        label = entry["label"]
        actor = json.loads((root / label / "RESULT.json").read_text())
        arrays = read_arrays(root / label / "ARRAYS.npz")
        geometry = actor["geometry"]
        operator = baseline[geometry + "_operator"]
        n = len(baseline[geometry + "_input0"])
        require(
            actor["completed_forward_calls"]
            == len(actor["forward_journal"])
            == actor["calls"]["forwards"],
            "completed forward counts",
        )
        require(
            actor["completed_adjoint_calls"]
            == len(actor["backward_journal"])
            == actor["calls"]["adjoints"],
            "completed adjoint counts",
        )
        require(
            actor["completed_adam_updates"] == actor["calls"]["adam_updates"],
            "completed Adam counts",
        )
        for index, row in enumerate(actor["records"]):
            name = row["label"]
            output, target = arrays[name + "_output"], arrays[name + "_target"]
            residual = output - target
            loss = math.fsum(float(value) ** 2 for value in residual.flat) / output.size
            require(
                abs(loss - row["loss"]) <= 1e-18 + 2e-15 * abs(loss),
                "actual MSE reduction",
            )
            cot = arrays[f"backward{index}_cotangent"]
            cot_error = bound(
                cot, residual * (2 / output.size), 1e-17, 2e-15, "live MSE cotangent"
            )
            values = [arrays[name + "_before_" + key] for key in NAMES]
            carrier = np.vstack(
                (
                    np.column_stack((values[0], values[1])),
                    np.column_stack((values[2], values[3])),
                )
            )
            predicted_output = np.empty_like(output)
            predicted_vjp = np.empty_like(carrier)
            for t, s, channel in np.ndindex(output.shape):
                predicted_output[t, s, channel] = math.fsum(
                    float(operator[t, s, j]) * float(carrier[j, channel])
                    for j in range(len(carrier))
                )
            for j, channel in np.ndindex(carrier.shape):
                predicted_vjp[j, channel] = math.fsum(
                    float(operator[t, s, j]) * float(cot[t, s, channel])
                    for t, s in np.ndindex(operator.shape[:2])
                )
            actual_vjp = arrays[f"backward{index}_vjp"]
            forward_error = bound(
                output,
                predicted_output,
                1e-8,
                2e-7,
                "live parameter forward versus retained G",
            )
            vjp_error = bound(
                actual_vjp,
                predicted_vjp,
                3e-7,
                3e-5,
                "live current-cot VJP versus retained G transpose",
            )
            blocks = (
                actual_vjp[:n, 0],
                actual_vjp[:n, 1:],
                actual_vjp[n:, 0],
                actual_vjp[n:, 1:],
            )
            gradients = {key: arrays[name + "_gradient_" + key] for key in NAMES}
            before = {key: arrays[name + "_before_" + key] for key in NAMES}
            for i, key in enumerate(NAMES):
                require(
                    np.array_equal(gradients[key], blocks[i]),
                    "live VJP enters Tensor gradient " + key,
                )
                require(
                    np.array_equal(before[key], arrays[f"forward{index}_input{i}"]),
                    "recorded live forward input",
                )
            require(
                np.array_equal(output, arrays[f"forward{index}_output"]),
                "recorded live forward output",
            )
            require(
                json.dumps(
                    fp({key: tensor(value) for key, value in gradients.items()}),
                    sort_keys=True,
                )
                == json.dumps(row["gradient"], sort_keys=True),
                "gradient fingerprint matches raw arrays",
            )
            records.append(
                {
                    "actor": label,
                    "loss_label": name,
                    "loss": loss,
                    "cotangent": cot_error,
                    "forward_old_G": forward_error,
                    "vjp_old_G_transpose": vjp_error,
                }
            )
            if name == "next":
                continue
            step = int(name.removeprefix("step"))
            after_state = (
                states["crash-published.pt.pending"]
                if label == "uniform-crash"
                else states[label + f"/step{step}.pt"]
            )
            old_state = None if step == 1 else states[geometry + "-continuous/step1.pt"]
            for i, key in enumerate(NAMES):
                grad = gradients[key]
                old_m = (
                    np.zeros_like(grad)
                    if old_state is None
                    else old_state["adam"]["state"][i]["exp_avg"].array
                )
                old_v = (
                    np.zeros_like(grad)
                    if old_state is None
                    else old_state["adam"]["state"][i]["exp_avg_sq"].array
                )
                moment = 0.9 * old_m + (1 - 0.9) * grad
                square = 0.999 * old_v + (1 - 0.999) * grad * grad
                candidate = before[key] - (1e-4 / (1 - 0.9**step)) * moment / (
                    np.sqrt(square) / math.sqrt(1 - 0.999**step) + 1e-8
                )
                actual_m = after_state["adam"]["state"][i]["exp_avg"].array
                actual_v = after_state["adam"]["state"][i]["exp_avg_sq"].array
                m_error = bound(
                    actual_m, moment, 1e-18, 2e-15, "Adam first moment algebra"
                )
                v_error = bound(
                    actual_v, square, 1e-21, 2e-15, "Adam second moment algebra"
                )
                actual_after = arrays[name + "_after_" + key]
                update_error = bound(
                    actual_after, candidate, 3e-15, 2e-15, "Adam FP64 update algebra"
                )
                require(
                    np.array_equal(actual_after, after_state["parameters"][key].array),
                    "updated parameter checkpoint binding",
                )
                require(
                    np.array_equal(grad, after_state["gradients"][key].array),
                    "saved gradient checkpoint binding",
                )
                require(
                    int(after_state["adam"]["state"][i]["step"].array) == step,
                    "Adam serialized scalar step",
                )
                require(
                    bool(np.any(actual_after != before[key])),
                    "actual nonzero tensor update",
                )
                updates.append(
                    {
                        "actor": label,
                        "step": step,
                        "parameter": key,
                        "first_moment": m_error,
                        "second_moment": v_error,
                        "parameter_update": update_error,
                    }
                )
    require(
        len(records) == 13 and len(updates) == 36,
        "13 loss records and nine four-tensor update events",
    )
    require("torch" not in sys.modules, "no Torch imported during audit")
    report = {
        "schema": "hcsn-adjoint-adam-retained-artifact-independent-audit-v1",
        "passed": True,
        "reviewer": "/root/review_spatial",
        "source_commit": source["source_commit"],
        "run_id": 43228409724,
        "job_id": 131217519039,
        "original_zip": {
            "bytes": len(archive_raw),
            "sha256": digest(archive_raw),
            "crc_members": 66,
        },
        "strict_nonexecuting_ptzip_reader": True,
        "checkpoint_payloads_read": identities,
        "complete_logical_equalities": exact_comparisons,
        "loss_and_live_vjp_checks": records,
        "adam_algebra_checks": updates,
        "producer_checks": len(result["checks"]),
        "producer_checks_are_overlapping_not_independent_replications": True,
        "actual_invocations": result["actual_calls"],
        "unknown_actor_costs": result["unknown_actor_costs"],
        "next_loss_and_four_gradient_buffers_exact_both_geometries": True,
        "original_admission_controls_are_actual_not_new_audit_executions": True,
        "review_new_candidate_model_torch_ode_adjoint_expm_static_optimizer_calls": 0,
        "review_cpu_seconds": time.process_time() - cpu,
        "review_wall_seconds": time.perf_counter() - wall,
        "inspector": {
            "bytes": Path(__file__).stat().st_size,
            "sha256": digest(Path(__file__).read_bytes()),
        },
        "ptzip_reader": {
            "bytes": (Path(__file__).parent / "ptzip.py").stat().st_size,
            "sha256": digest((Path(__file__).parent / "ptzip.py").read_bytes()),
        },
        "scope": [
            "Fixed physics/support N7/N12, four raw FP64 initial tensors, first-order synthetic MSE, exact same-runtime/source restoration only.",
            "Independent Adam arithmetic is algebra on retained values, not an optimizer execution; moments and updates are checked within explicit FP64 rounding gates, while path restoration equality is exact over full payload.",
            "Process crash on the same running OS, not power loss, hostile Python/checkpoint or dependency-binary attestation.",
            "No n512/full-network/physical gradients/migration/historical training/task benefit/energy/adoption qualification.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "payloads": 17,
                "losses": 13,
                "four_tensor_update_events": 9,
                "review_new_model_torch_optimizer_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
