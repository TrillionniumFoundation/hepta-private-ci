"""Execute a trained tensor HCSN online under actual native owner decisions.

The native policy consumes internal renewal-cell value, natural margin, predicted
classification error, and interval first-passage activity. Internal cell value is
not relabeled as the Bellman value of the external classification task.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import torch

from .model import HCSNClassifier
from .native_bridge import MANIFEST, OBJECTIVE, POLICIES, NativeSession, Signals, UPSTREAM, profile, restored_binary
from .run_native import write


def model_identity(model):
    identity = {"config": model.config, "state": {}}
    for key, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        identity["state"][key] = {"shape": list(tensor.shape), "dtype": str(tensor.dtype),
                                   "sha256": hashlib.sha256(tensor.numpy().tobytes()).hexdigest()}
    return UPSTREAM.digest(identity), identity


def _signals(logits, aux):
    confidence = logits.softmax(-1).max().item()
    raw = {"cell_renewal_value": aux["continuation"].mean().item(),
           "natural_margin": aux["margin"].mean().item(),
           "interval_event_mass": aux["event_probability"].mean().item(),
           "classification_confidence": confidence}
    signals = Signals(torch.tanh(aux["continuation"].mean()).item(),
                      torch.tanh(aux["margin"].mean()).item(),
                      1 - confidence, raw["interval_event_mass"])
    signals.packet()
    return signals, raw


def run_live(model, x, dt, labels, read_costs, output, *, binary=None, context=None,
             episode_ids=None, recover_first=True, provenance=None):
    """Run all fixed policies on every supplied heldout episode without lookahead.

    Inputs may be tensors or array-likes. The caller owns training/test separation;
    its provenance is retained. This function never fits a controller or model.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    binary = binary or restored_binary()
    x, dt = torch.as_tensor(x, dtype=torch.float32), torch.as_tensor(dt, dtype=torch.float32)
    labels = torch.as_tensor(labels, dtype=torch.long)
    costs = torch.as_tensor(read_costs, dtype=torch.float64).expand(len(x))
    if x.ndim != 3 or dt.shape != x.shape[:2] or labels.shape != (len(x),) or len(x) == 0:
        raise ValueError("Expected nonempty x[N,T,I], dt[N,T], labels[N]")
    if not bool(torch.isfinite(costs).all()) or bool((costs < 0).any()) or x.shape[1] > 512:
        raise ValueError("Invalid external costs or native horizon")
    if context is not None:
        context = torch.as_tensor(context, dtype=torch.float32)
    episode_ids = episode_ids or [f"heldout{i}" for i in range(len(x))]
    model = model.cpu().eval()
    model_digest, identity = model_identity(model)
    data_digest = hashlib.sha256(x.numpy().tobytes() + dt.numpy().tobytes()
                                 + labels.numpy().tobytes() + costs.numpy().tobytes()
                                 + (b"" if context is None else context.numpy().tobytes())).hexdigest()
    write(output / "PROTOCOL.json", {"schema": "hcsn-live-native-protocol.v1",
        "objective": OBJECTIVE, "source_model_sha256": model_digest,
        "policies": {name: profile(name, model_digest) for name in POLICIES},
        "heldout_selection": "all supplied episodes; selection belongs to caller's frozen protocol",
        "interpretation": "actual model steps and native owner actions; no controller fitting",
        "feature_semantics": {"continuation": "tanh(mean internal renewal-cell value)",
                              "margin": "tanh(mean natural boundary minus pressure)",
                              "risk": "1-max softmax; no safety-calibration claim",
                              "activity": "mean interval first-passage mass"},
        "internal_cell_cost_is_not_external_read_cost": True,
        "policies_fitted_on_these_episodes": False})
    write(output / "INPUT_IDENTITY.json", {"model": identity, "model_sha256": model_digest,
        "dataset_sha256": data_digest, "provenance": provenance, "native": MANIFEST})
    started = time.process_time(), time.perf_counter()
    summary = {}
    for policy in POLICIES:
        policy_started = time.process_time(), time.perf_counter()
        records = []
        for number in range(len(x)):
            active_model, state = model, None
            root = output / policy / f"episode{number:05d}"
            case = f"episode{number:05d}"
            native = NativeSession(root, binary=binary, policy=policy, model_digest=model_digest,
                                   case=case, seed=number)
            rows, native_costs, recoveries = [], [], []
            model_cpu, model_wall = 0.0, 0.0
            recovery_parent_cpu, recovery_wall = 0.0, 0.0
            for index in range(x.shape[1]):
                cpu, wall = time.process_time(), time.perf_counter()
                with torch.no_grad():
                    logits, state, aux = active_model.step(
                        x[number:number + 1, index], dt[number:number + 1, index], state,
                        context=None if context is None else context[number:number + 1, index])
                    signals, raw = _signals(logits, aux)
                model_cpu += time.process_time() - cpu
                model_wall += time.perf_counter() - wall
                prediction = int(logits.argmax(-1).item())
                row = native.tick(signals, context={"dataset_sha256": data_digest,
                    "episode": str(episode_ids[number]), "prefix": index + 1,
                    "signal_semantics": "internal-cell-value-and-external-classification-risk"})
                rows.append({"prefix": index + 1, "prediction": prediction,
                             "raw_signals": raw, "signals": asdict(signals), "native": row["native"]})
                if native.terminal:
                    break
                if recover_first and number == 0 and index == 0:
                    recovery_started = time.process_time(), time.perf_counter()
                    snapshot = root / "NEURAL_PREFIX.pt"
                    torch.save({"config": model.config, "model": model.state_dict(),
                                "state": state, "cursor": index + 1, "data_sha256": data_digest,
                                "model_sha256": model_digest}, snapshot)
                    native_costs.append(native.close())
                    # The tensor state is restored into a fresh model object and native
                    # process. The controlling Python interpreter is not restarted.
                    saved = torch.load(snapshot, map_location="cpu", weights_only=True)
                    if saved["data_sha256"] != data_digest or saved["cursor"] != index + 1:
                        raise ValueError("Recovery task identity or cursor changed")
                    active_model = HCSNClassifier(**saved["config"]).eval()
                    active_model.load_state_dict(saved["model"])
                    if model_identity(active_model)[0] != model_digest:
                        raise ValueError("Recovered neural model identity changed")
                    state = saved["state"]
                    native = NativeSession(root, binary=binary, policy=policy, model_digest=model_digest,
                                           case=case, seed=number, resume=True)
                    recovery_cpu = time.process_time() - recovery_started[0]
                    recovery_elapsed = time.perf_counter() - recovery_started[1]
                    recovery_parent_cpu += recovery_cpu
                    recovery_wall += recovery_elapsed
                    recoveries.append({"snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                                       "native_resume": native.open_receipt,
                                       "new_native_process": True, "new_neural_model_object": True,
                                       "python_interpreter_restarted": False,
                                       "parent_cpu_seconds": recovery_cpu,
                                       "wall_seconds": recovery_elapsed,
                                       "native_child_cpu_attribution": "Exact child lifetime CPU is retained in native_process_costs; not isolated to Resume RPC"})
            terminal_probe = native.verify_terminal() if native.terminal else None
            native_costs.append(native.close())
            reads = len(rows)
            correct = int(prediction == int(labels[number]))
            record = {"episode": str(episode_ids[number]), "policy": policy,
                "model_updates_executed": reads, "actual_reads": reads,
                "model_updates_avoided": x.shape[1] - reads, "correct": correct,
                "paid_read_cost": float(costs[number]) * reads,
                "utility": correct - float(costs[number]) * reads,
                "stop_reason": "native_stop" if native.terminal else "finite_horizon",
                "model_cpu_seconds": model_cpu, "model_wall_seconds": model_wall,
                "recovery_parent_cpu_seconds": recovery_parent_cpu,
                "recovery_wall_seconds": recovery_wall,
                "native_process_costs": native_costs, "recoveries": recoveries,
                "events": rows, "terminal_probe": terminal_probe}
            write(root / "RESULT.json", record)
            records.append(record)
        summary[policy] = {"episodes": len(records),
            "accuracy": sum(x["correct"] for x in records) / len(records),
            "mean_utility": sum(x["utility"] for x in records) / len(records),
            "actual_reads": sum(x["actual_reads"] for x in records),
            "avoided_model_updates": sum(x["model_updates_avoided"] for x in records),
            "native_stop_episodes": sum(x["stop_reason"] == "native_stop" for x in records),
            "model_cpu_seconds": sum(x["model_cpu_seconds"] for x in records),
            "native_child_cpu_seconds": sum(c["child_cpu_seconds"] for x in records
                                             for c in x["native_process_costs"]),
            "cold_native_and_neural_restorations": sum(len(x["recoveries"]) for x in records),
            "recovery_parent_cpu_seconds": sum(x["recovery_parent_cpu_seconds"] for x in records),
            "recovery_wall_seconds": sum(x["recovery_wall_seconds"] for x in records),
            "parent_cpu_seconds": time.process_time() - policy_started[0],
            "elapsed_wall_seconds": time.perf_counter() - policy_started[1]}
    result = {"summary": summary, "parent_cpu_seconds": time.process_time() - started[0],
              "elapsed_wall_seconds": time.perf_counter() - started[1],
              "model_sha256": model_digest, "dataset_sha256": data_digest,
              "production_authority": False, "hardware_energy_measured": False,
              "controller_coefficients_are_hand_specified": True}
    write(output / "SUMMARY.json", result)
    return result
