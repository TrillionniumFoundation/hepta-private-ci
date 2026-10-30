"""Continuous 4096-step audit of the frozen full risk-feature classifier.

Uses generated, label-free inputs and an untrained registered initialization.
It does not establish trained long-context quality or long-network gradients.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import numpy as np
import torch

from experiments.hcsn_free_boundary_v1 import training
from experiments.hcsn_risk_ablation_v1.model import RiskClassifier
from experiments.hcsn_risk_ablation_v1.study import verify


OBSERVATIONS = 4096
MODEL_SEED = 9401
INPUT_SEED = 103071
DURATIONS = [0., .125, 1., 3.5, 5., 32.]
ARM = "risk_margin_j_risk"
RESTORE_AT = 1024
RESTORE_STEPS = 16
LIMITS = dict(mass=1e-6, projection_l1=260 * np.finfo(np.float32).eps,
              risk_min=-1e-9, risk_max=1 + 2e-6,
              content_absolute=1 + 8 * np.finfo(np.float32).eps)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_state(path, state):
    values = dict(elapsed=state["elapsed"].cpu().numpy())
    for i, layer in enumerate(state["layers"]):
        for key, value in layer.items():
            values[f"layer{i}_{key}"] = value.cpu().numpy()
    np.savez_compressed(path, **values)


def load_state(path):
    with np.load(path, allow_pickle=False) as values:
        return dict(elapsed=torch.from_numpy(values["elapsed"].copy()),
                    layers=[{key: torch.from_numpy(values["layer0_" + key].copy())
                             for key in ("content", "probability", "boundary")}])


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    package = Path(__file__).resolve().parent
    repo = package.parent.parent
    protocol_path = repo / "experiments/hcsn_risk_ablation_v1/PROTOCOL.json"
    protocol = verify(protocol_path)
    sources = dict(protocol["source_files_sha256"])
    sources[str(Path(__file__).relative_to(repo))] = digest(Path(__file__))
    registration = dict(schema="hcsn-full-network-long-stream-registration.v1",
        model=ARM, model_seed=MODEL_SEED, input_seed=INPUT_SEED,
        observations=OBSERVATIONS, batch=1, input_dim=64, output_dim=8, width=32, depth=1,
        durations=DURATIONS, physical_time_scale=.1,
        inputs="Four randomly selected one-hot coordinates per token, no labels or dataset access",
        dtype="float32", network_state="Untrained deterministic initialization; continuous step calls",
        restore_at=RESTORE_AT, restore_steps=RESTORE_STEPS, restoration_criterion="bitwise equal logits and final probability state",
        limits=LIMITS, protocol_sha256=digest(protocol_path), source_sha256=sources,
        limitations=["One initialization and generated input stream, no trained checkpoint claim",
                     "No content quality or long-gradient claim",
                     "Global elapsed-time frontend can saturate; its saturation is recorded",
                     "CPU numerical check, not energy or throughput evidence"])
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    generator = torch.Generator().manual_seed(INPUT_SEED)
    positions = torch.randint(64, (OBSERVATIONS, 4), generator=generator)
    x = torch.zeros((1, OBSERVATIONS, 64))
    x[0].scatter_add_(1, positions, torch.ones_like(positions, dtype=x.dtype))
    dt = torch.tensor([[DURATIONS[i % len(DURATIONS)] for i in range(OBSERVATIONS)]])
    np.savez_compressed(output / "inputs.npz", x=x.numpy(), dt=dt.numpy())
    model = RiskClassifier(ARM, 64, 8, 32, 1, MODEL_SEED).eval()
    weights_sha = training.save_weights(output / "initial_weights.npz", model)
    state, rows, probabilities, contents, logits_trace = None, [], [], [], []
    saved_probability_after_restore_window = None
    failures, restoration = [], None
    cumulative_events = np.zeros(8, dtype=np.float64)
    try:
        with torch.inference_mode():
            for i in range(OBSERVATIONS):
                logits, state, aux = model.step(x[:, i], dt[:, i], state)
                p = state["layers"][0]["probability"]
                content = state["layers"][0]["content"]
                risk = aux["first_event_probability"]
                mass_error = float((p.double().sum(-1) - 1).abs().max())
                correction = float(aux["projection_actual_l1_correction"].max())
                raw_mass_error = float((aux["projection_pre_projection_mass"] - 1).abs().max())
                events = aux["activity"].reshape(-1).double().numpy()
                cumulative_events += events
                frontend_input = torch.cat((x[:, i], dt[:, i, None] / 32, state["elapsed"][:, None] / 32), -1)
                frontend = model.frontend(frontend_input)
                saturation = float((frontend.abs() >= .99999).float().mean())
                assert bool(torch.isfinite(logits).all())
                assert mass_error <= LIMITS["mass"] and float(p.min()) >= 0
                assert correction <= LIMITS["projection_l1"]
                assert float(risk.min()) >= LIMITS["risk_min"] and float(risk.max()) <= LIMITS["risk_max"]
                assert float(content.abs().max()) <= LIMITS["content_absolute"]
                row = [i + 1, float(state["elapsed"][0]), mass_error, raw_mass_error, correction,
                       float(risk.min()), float(risk.max()), float(risk.mean()),
                       float(content.abs().max()), float(logits.abs().max()), saturation,
                       float(aux["boundary"].min()), float(aux["boundary"].max()),
                       float(aux["active_mass"].mean()), float(aux["refractory_mass"].mean()),
                       float(events.sum()), float(cumulative_events.sum())]
                rows.append(row)
                probabilities.append(p.cpu().numpy().copy())
                contents.append(content.cpu().numpy().copy())
                logits_trace.append(logits.cpu().numpy().copy())
                if i + 1 == RESTORE_AT:
                    save_state(output / "state_001024.npz", state)
                if i + 1 == RESTORE_AT + RESTORE_STEPS:
                    saved_probability_after_restore_window = p.clone()
                if i + 1 in (1024, 2048, 3072, 4096):
                    (output / "PROGRESS.json").write_text(json.dumps(dict(completed=i + 1, latest=row)) + "\n")
            save_state(output / "state_004096.npz", state)
            restored_model = RiskClassifier(ARM, 64, 8, 32, 1, MODEL_SEED).eval()
            training.load_weights(output / "initial_weights.npz", restored_model)
            restored_state = load_state(output / "state_001024.npz")
            restored_logits = []
            for i in range(RESTORE_AT, RESTORE_AT + RESTORE_STEPS):
                value, restored_state, _ = restored_model.step(x[:, i], dt[:, i], restored_state)
                restored_logits.append(value.numpy().copy())
            expected = np.asarray(logits_trace)[RESTORE_AT:RESTORE_AT + RESTORE_STEPS]
            actual = np.asarray(restored_logits)
            restoration = dict(logits_bitwise_equal=bool(np.array_equal(actual, expected)),
                probability_bitwise_equal=bool(torch.equal(restored_state["layers"][0]["probability"], saved_probability_after_restore_window)),
                maximum_logit_difference=float(np.abs(actual - expected).max()))
            assert restoration["logits_bitwise_equal"] and restoration["probability_bitwise_equal"]
    except Exception:
        failures.append(traceback.format_exc())
    trace = np.asarray(rows)
    np.savez_compressed(output / "raw_stream.npz", scalar_trace=trace,
                        probabilities=np.asarray(probabilities), contents=np.asarray(contents), logits=np.asarray(logits_trace))
    changed = [path for path, sha in sources.items() if digest(repo / path) != sha]
    result = dict(schema="hcsn-full-network-long-stream-audit.v1",
        passed=not failures and not changed and len(rows) == OBSERVATIONS,
        observations_completed=len(rows), failures=failures, source_changed_during_audit=changed,
        source_sha256=sources, initial_weights_sha256=weights_sha, state_restoration=restoration,
        maximum_probability_mass_error=float(trace[:, 2].max()) if len(trace) else None,
        maximum_pre_projection_mass_error=float(trace[:, 3].max()) if len(trace) else None,
        maximum_l1_correction=float(trace[:, 4].max()) if len(trace) else None,
        risk_min=float(trace[:, 5].min()) if len(trace) else None, risk_max=float(trace[:, 6].max()) if len(trace) else None,
        maximum_content_absolute=float(trace[:, 8].max()) if len(trace) else None,
        maximum_logit_absolute=float(trace[:, 9].max()) if len(trace) else None,
        final_frontend_saturation_fraction=float(trace[-1, 10]) if len(trace) else None,
        cumulative_expected_events_per_physical_channel=cumulative_events.tolist(),
        self_cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall,
        peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        scalar_trace_columns=["observation", "elapsed_input_time", "maximum_mass_error", "maximum_raw_mass_error",
            "maximum_l1_correction", "minimum_risk", "maximum_risk", "mean_risk", "maximum_content_absolute",
            "maximum_logit_absolute", "frontend_saturation_fraction", "minimum_boundary", "maximum_boundary",
            "mean_active_mass", "mean_refractory_mass", "expected_events_sum_this_step", "expected_events_cumulative_sum"],
        task_labels_read=False, trained_checkpoint_used=False, long_gradient_measured=False,
        gpu_measured=False, energy_measured=False)
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "observations_completed", "self_cpu_seconds", "wall_seconds")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    main(args.output)
