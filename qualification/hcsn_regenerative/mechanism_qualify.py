"""Independent three-step RNN qualification; consumes no task test data."""

import argparse
import hashlib
from pathlib import Path
import resource
import time
import traceback

import numpy as np

from .mechanism_contract import ARMS, RUNNER_FILES, STATE_COUNT, EXPECTED_PARAMETERS, file_sha, read_json, utc_now, verify_sources, write_json
from .mechanism_model import DeviceEnergy, environment, make_model, memory_report
from .mechanism_worker import configure_torch


def numpy_mirror(parameters, arrays, arm, channel, observations, indices):
    """Independent FP64 reference of the observer, using represented FP32 inputs."""
    x = observations.astype(np.float64)
    p = None
    cohort = (indices[:, 0] >= 2).astype(np.int64)
    matrix = arrays[arm + "__matrix"].astype(np.float64)
    first = arrays[arm + "__first_step"].astype(np.float64)
    features = arrays[arm + "__features"].astype(np.float64)
    for step in range(x.shape[1]):
        dt = indices[:, step]
        pred = first[cohort, dt] if p is None else np.einsum("bi,bij->bj", p, matrix[cohort, dt])
        raw = np.einsum("bi,bij->bj", pred, features[cohort, dt])
        z = np.stack((raw[:, 0] / (1 + raw[:, 0]), raw[:, 1] / (1 + raw[:, 1]), raw[:, 2]), -1)
        if channel != "dual":
            value = z[:, {"margin": 0, "call": 1, "risk": 2}[channel]]
            z = np.stack((value, value ** 2, value ** 3), -1)
        obs = x[:, step]
        hidden = np.tanh(obs @ parameters["encoder.0.weight"].T + parameters["encoder.0.bias"])
        encoded = hidden @ parameters["encoder.2.weight"].T + parameters["encoder.2.bias"]
        gate_logit = np.concatenate((obs, z), -1) @ parameters["gate.weight"].T + parameters["gate.bias"]
        gate = 1 / (1 + np.exp(-gate_logit))
        weighted = pred * np.exp(gate * np.tanh(encoded))
        p = weighted / weighted.sum(-1, keepdims=True)
    return p @ parameters["readout.weight"].T + parameters["readout.bias"]


def graph_checks(arrays, metadata, device):
    torch = configure_torch(device)
    observations = np.array([[[.25, 1., .025], [-.4, 0., .075], [.6, 0., .05]],
                             [[-.3, 1., .1], [.2, 0., .025], [-.1, 0., .075]]], dtype=np.float32)
    indices = np.array([[0, 2, 1], [3, 0, 2]], dtype=np.int64)
    target = np.array([[.2], [-.4]], dtype=np.float64)
    checks = []
    for arm in ARMS:
        channel = metadata["arms"][arm]["channel"]
        model = make_model(arrays, arm, channel, 1103, device)
        if model.matrix.shape[-1] != STATE_COUNT or sum(p.numel() for p in model.parameters()) != EXPECTED_PARAMETERS:
            raise ValueError("The numerically selected S81 / 2890-parameter architecture is required")
        x = torch.tensor(observations, device=device, requires_grad=True)
        dt = torch.tensor(indices, device=device)
        value, audit, trace = model(x, dt, return_trace=True)
        expected_carry = torch.bmm(trace[0]["posterior"].unsqueeze(1), model.matrix[trace[0]["cohort"], dt[:, 1]]).squeeze(1)
        carry_error = float((expected_carry - trace[1]["pred"]).abs().max().item())
        reinitialization_difference = float((model.first_step[trace[0]["cohort"], dt[:, 1]] - trace[1]["pred"]).abs().max().item())
        checks.append(dict(name="state_carry", arm=arm, maximum_carry_error=carry_error,
                           difference_from_reinitialization=reinitialization_difference,
                           passed=carry_error < 1e-7 and reinitialization_difference > 1e-7,
                           mass_audit=audit, memory=memory_report(model, batch_size=2)))
        parameters = {name: parameter.detach().cpu().numpy().astype(np.float64) for name, parameter in model.named_parameters()}
        mirror = numpy_mirror(parameters, arrays, arm, channel, observations, indices)
        difference = float(np.max(np.abs(mirror - value.detach().cpu().numpy())))
        checks.append(dict(name="represented_fp32_forward_vs_fp64_mirror", arm=arm, maximum_absolute_difference=difference,
                           tolerance=2e-5, passed=difference <= 2e-5))
        loss = (value - torch.tensor(target, dtype=torch.float32, device=device)).square().mean()
        loss.backward()
        # Full mechanism, a single-channel gate, and conditional cohorts cover distinct graph paths.
        if arm not in ("regenerative_dual", "risk_only", "conditional_boundary"):
            continue
        def objective():
            return float(np.square(numpy_mirror(parameters, arrays, arm, channel, observations, indices) - target).mean())
        for name, parameter in model.named_parameters():
            if name not in ("encoder.0.weight", "encoder.2.weight", "gate.weight", "readout.weight"):
                continue
            gradient = parameter.grad.detach().cpu().numpy().astype(np.float64)
            for flat in np.argsort(np.abs(gradient).ravel())[-2:]:
                index = np.unravel_index(int(flat), gradient.shape)
                original, epsilon = parameters[name][index], 1e-5
                parameters[name][index] = original + epsilon
                plus = objective()
                parameters[name][index] = original - epsilon
                minus = objective()
                parameters[name][index] = original
                finite_difference = (plus - minus) / (2 * epsilon)
                automatic = float(gradient[index])
                error = abs(automatic - finite_difference)
                tolerance = 2e-6 + .003 * abs(finite_difference)
                checks.append(dict(name="parameter_gradient", arm=arm, parameter=name, index=[int(i) for i in index],
                                   automatic_fp32=automatic, represented_fp64_finite_difference=finite_difference,
                                   absolute_error=error, tolerance=tolerance,
                                   passed=bool(np.isfinite(finite_difference) and abs(finite_difference) > 1e-10 and error <= tolerance)))
        input_gradient = float(x.grad[0, 0, 0].item())
        original = float(observations[0, 0, 0])
        # Keep FD perturbations in FP64; rounding the perturbation into FP32 would change its denominator.
        xp, xm = observations.astype(np.float64), observations.astype(np.float64)
        xp[0, 0, 0], xm[0, 0, 0] = original + 1e-5, original - 1e-5
        finite_difference = float((np.square(numpy_mirror(parameters, arrays, arm, channel, xp, indices) - target).mean()
                                   - np.square(numpy_mirror(parameters, arrays, arm, channel, xm, indices) - target).mean()) / 2e-5)
        error = abs(input_gradient - finite_difference)
        checks.append(dict(name="first_step_input_gradient", arm=arm, automatic_fp32=input_gradient,
                           represented_fp64_finite_difference=finite_difference, absolute_error=error,
                           tolerance=2e-6 + .003 * abs(finite_difference),
                           passed=bool(np.isfinite(finite_difference) and error <= 2e-6 + .003 * abs(finite_difference))))
    return checks


def qualify(bundle, device, output):
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise FileExistsError("Qualification receipts are append-only")
    started, cpu = time.monotonic(), time.process_time()
    directory = Path(__file__).parent
    names = list(RUNNER_FILES) + ["mechanism_qualify.py", "tests/test_mechanism_training.py"]
    pins = {str((directory / name).relative_to(directory.parents[1])): file_sha(directory / name) for name in names}
    result = dict(schema="hcsn-mechanism-graph-qualification-v1", at=utc_now(), device=device, status="failed",
                  state_count=STATE_COUNT, expected_parameter_count=EXPECTED_PARAMETERS,
                  bundle_sha256=file_sha(bundle), bundle_metadata_sha256=file_sha(bundle.with_suffix(".json")),
                  source_pins=pins, checks=[], full_physical_energy_joules=None,
                  fixture_scope="Fixed non-task three-step observations; no training, validation or test split consumed",
                  original_campaign_completion_credit=0)
    energy = None
    try:
        metadata = read_json(bundle.with_suffix(".json"))
        if (metadata["bundle_sha256"] != result["bundle_sha256"] or set(metadata["arms"]) != set(ARMS)
                or metadata.get("state_count") != STATE_COUNT):
            raise ValueError("Bundle identity or ten-arm roster mismatch")
        verify_sources(metadata["source_pins"])
        with np.load(bundle, allow_pickle=False) as archive:
            arrays = {name: archive[name].copy() for name in archive.files}
        for name, array in arrays.items():
            if array.dtype != np.float32 or not np.isfinite(array).all() or hashlib.sha256(array.tobytes()).hexdigest() != metadata["array_sha256"][name]:
                raise ValueError("Unbound or nonfinite FP32 operator " + name)
        configure_torch(device)
        result["environment"] = environment(device)
        result["bundle_construction_environment"] = {key: metadata[key] for key in ("schema", "python", "numpy", "scipy")}
        energy = DeviceEnergy(device)
        result["checks"] = graph_checks(arrays, metadata, device)
        verify_sources(pins)
        result["status"] = "pass" if all(check["passed"] for check in result["checks"]) else "failed"
    except Exception as error:
        result["error"] = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    result["wall_seconds"] = time.monotonic() - started
    result["process_cpu_seconds"] = time.process_time() - cpu
    result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["energy"] = energy.finish() if energy else dict(device_interval_joules=None, full_physical_energy_joules=None)
    if str(device).startswith("cuda"):
        try:
            import torch
            result["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
            result["peak_gpu_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        except Exception:
            result["peak_gpu_allocated_bytes"] = None
    write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--device", required=True, choices=("cpu", "cuda"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = qualify(args.bundle, args.device, args.output)
    print(result["status"])
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
