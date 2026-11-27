"""Compare NumPy CfC against exact pinned ncps source, without training.

The reference cell receives explicit common weights in float64. Initialization,
sequence-wrapper broadcasting, mixed memory and downstream task benefit are
outside this probe. The same final input feature is used both as an ordinary
feature and as explicit (batch, 1) elapsed time.
"""

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import time
import types

import numpy as np

from .cfc import CfCModel, NCPS_REFERENCE_COMMIT
from hepta_pred1.models import Model

REFERENCE_SHA256 = "79dcc1cbb3b6898dc2310e9086a2e031e31cbaeb129d69adcbf45eaa16d6b74d"
LICENSE_SHA256 = "aedff72c6a199d144f3425c92e2727292785609432d243347b5acaca0450ff31"
GATES = {"f1": "ff1", "f2": "ff2", "ta": "time_a", "tb": "time_b"}
TOLERANCES = dict(
    reference_atol=2e-11,
    reference_rtol=2e-10,
    finite_difference_atol=5e-7,
    finite_difference_rtol=2e-5,
    epsilon=1e-6,
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _error(actual, expected, *, finite_difference=False):
    prefix = "finite_difference" if finite_difference else "reference"
    np.testing.assert_allclose(
        actual,
        expected,
        atol=TOLERANCES[prefix + "_atol"],
        rtol=TOLERANCES[prefix + "_rtol"],
    )
    return float(np.max(np.abs(np.asarray(actual) - np.asarray(expected))))


def _finite_difference(function, values, *, time_input=False):
    """Central differences, with a second-order right derivative at dt=0."""
    result = np.zeros_like(values)
    epsilon = TOLERANCES["epsilon"]
    baseline = function()
    for index in np.ndindex(values.shape):
        original = values[index]
        values[index] = original + epsilon
        plus = function()
        if time_input and index[-1] == values.shape[-1] - 1 and original == 0:
            values[index] = original + 2 * epsilon
            plus_two = function()
            result[index] = (-3 * baseline + 4 * plus - plus_two) / (2 * epsilon)
        else:
            values[index] = original - epsilon
            minus = function()
            result[index] = (plus - minus) / (2 * epsilon)
        values[index] = original
    return result


def _case(torch, reference_class, seed, batch, arrays):
    hidden, dimension, actions, outputs, steps = 3, 5, 2, 3, 4
    model = CfCModel("cfc", dimension, actions, outputs, hidden, seed)
    rng = np.random.default_rng(seed + 100 * batch)
    for value in model.params.values():
        value[:] = rng.normal(0, 0.15, value.shape)
    reference = reference_class(
        dimension, hidden, mode="default", backbone_layers=0
    ).double()
    with torch.no_grad():
        for local, official in GATES.items():
            layer = getattr(reference, official)
            layer.weight.copy_(torch.tensor(model.params["W" + local].T))
            layer.bias.copy_(torch.tensor(model.params["b" + local]))
    x = rng.normal(0, 0.3, (batch, steps, dimension))
    x[:, :, -1] = np.stack([np.roll([0.0, 0.001, 0.2, 20.0], i) for i in range(batch)])
    action = rng.normal(0, 0.3, (batch, actions))
    initial = rng.normal(0, 0.4, (batch, hidden))
    state, expected = initial.copy(), torch.tensor(initial)
    key = f"seed{seed}_batch{batch}"
    arrays[key + "_x"], arrays[key + "_initial"], arrays[key + "_action"] = (
        x,
        initial,
        action,
    )
    for name, value in model.params.items():
        arrays[key + "_p_" + name] = value.copy()
    transition_checks = []
    for index in range(steps):
        observation, previous = x[:, index].copy(), state.copy()
        xt = torch.tensor(observation, requires_grad=True)
        ht = torch.tensor(previous, requires_grad=True)
        official, _ = reference(xt, ht, xt[:, -1:])
        cotangent = rng.normal(0, 0.5, (batch, hidden))
        dx, dh = torch.autograd.grad(
            (official * torch.tensor(cotangent)).sum(), (xt, ht)
        )

        def score():
            return float(
                np.sum(
                    model.observe(observation, {"fast": previous})["fast"] * cotangent
                )
            )

        finite_x = _finite_difference(score, observation, time_input=True)
        finite_h = _finite_difference(score, previous)
        state = model.observe(observation, {"fast": state})["fast"]
        with torch.no_grad():
            expected, _ = reference(
                torch.tensor(x[:, index]), expected, torch.tensor(x[:, index, -1:])
            )
        transition_checks.append(
            dict(
                step=index,
                elapsed_seconds=observation[:, -1].tolist(),
                state_max_absolute_error=_error(state, expected.numpy()),
                input_derivative_max_absolute_error=_error(
                    finite_x, dx.numpy(), finite_difference=True
                ),
                previous_state_derivative_max_absolute_error=_error(
                    finite_h, dh.numpy(), finite_difference=True
                ),
            )
        )
        for suffix, value in (
            ("state_numpy", state),
            ("state_ncps", expected.numpy()),
            ("dx_finite", finite_x),
            ("dx_ncps", dx.numpy()),
            ("dh_finite", finite_h),
            ("dh_ncps", dh.numpy()),
        ):
            arrays[f"{key}_step{index}_{suffix}"] = value.copy()
    # Full sequence BPTT starts from the same zero episode state as Model.forward.
    reference.zero_grad(set_to_none=True)
    ref_state = torch.zeros(batch, hidden, dtype=torch.float64)
    tensor_x = torch.tensor(x)
    for index in range(steps):
        ref_state, _ = reference(tensor_x[:, index], ref_state, tensor_x[:, index, -1:])
    head = {
        name: torch.tensor(model.params[name], requires_grad=True)
        for name in ("Wh", "bh", "Wy", "by")
    }
    features = torch.cat((ref_state, torch.tensor(action)), dim=1)
    logits = torch.tanh(features @ head["Wh"] + head["bh"]) @ head["Wy"] + head["by"]
    allowed = np.array([[1, 0, 0], [0, 1, 1], [1, 1, 1]], dtype=bool)[:batch]
    weights = np.arange(1, batch + 1, dtype=np.float64)
    weights /= weights.sum()
    torch_loss = torch.sum(
        torch.tensor(weights)
        * (
            torch.logsumexp(logits, dim=1)
            - torch.logsumexp(
                logits.masked_fill(~torch.tensor(allowed), -torch.inf), dim=1
            )
        )
    )
    torch_loss.backward()
    loss, analytic = model.loss_and_grads(x, action, allowed, sample_weights=weights)
    official_grads = {name: value.grad.detach().numpy() for name, value in head.items()}
    for local, official in GATES.items():
        layer = getattr(reference, official)
        official_grads["W" + local] = layer.weight.grad.detach().numpy().T
        official_grads["b" + local] = layer.bias.grad.detach().numpy()
    gradient_errors = {}
    for name in model.params:
        gradient_errors[name] = _error(analytic[name], official_grads[name])
        arrays[key + "_gradient_numpy_" + name] = analytic[name]
        arrays[key + "_gradient_ncps_" + name] = official_grads[name]
    numpy_logits = model.forward(x, action)
    arrays[key + "_logits_numpy"], arrays[key + "_logits_ncps"] = (
        numpy_logits,
        logits.detach().numpy(),
    )
    arrays[key + "_allowed"], arrays[key + "_weights"] = allowed, weights
    return dict(
        seed=seed,
        batch=batch,
        hidden=hidden,
        input_dimension=dimension,
        sequence_steps=steps,
        parameter_coordinates=model.parameter_count,
        input_derivative_coordinates=batch * steps * dimension,
        previous_state_derivative_coordinates=batch * steps * hidden,
        transitions=transition_checks,
        loss=loss,
        loss_absolute_error=_error(loss, torch_loss.item()),
        logits_max_absolute_error=_error(numpy_logits, logits.detach().numpy()),
        parameter_gradient_max_absolute_errors=gradient_errors,
    )


def run_probe(reference_path, license_path, output_dir):
    """Retain exact reference bytes, numerical arrays and pass/failure receipt."""
    import torch

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    report = dict(
        schema="hepta.cell.cfc-official-parity.v1",
        status="started",
        ncps_commit=NCPS_REFERENCE_COMMIT,
        reference_path="ncps/torch/cfc_cell.py",
        reference_sha256=REFERENCE_SHA256,
        reference_git_blob="564885f723882dc4b9f8d3046ada152474eb9294",
        license_sha256=LICENSE_SHA256,
        license="Apache-2.0",
        dtype="float64",
        mode="default",
        backbone_layers=0,
        common_weights="explicit normal(0,0.15) weights and biases copied to every layer; matrix weights transposed",
        time_input="same final feature plus explicit (batch,1) elapsed time; no squeezed sequence wrapper",
        seeds=[11, 23, 47],
        batches=[1, 2, 3],
        hidden_dimension=3,
        tolerances=TOLERANCES,
        cases=[],
        fresh_confirmation=0,
        scientific_status="HOLD",
        exclusions="initialization equivalence, mixed memory, sequence wrapper, task benefit, gradient learning-rule comparison",
        runtime=dict(
            python=platform.python_version(),
            numpy=np.__version__,
            torch=torch.__version__,
            platform=platform.platform(),
            torch_threads=torch.get_num_threads(),
        ),
        execution_command=" ".join(sys.argv),
        energy_joules=None,
        provider_billing=None,
    )
    arrays = {}
    try:
        reference_raw, license_raw = (
            Path(reference_path).read_bytes(),
            Path(license_path).read_bytes(),
        )
        if (
            _sha(reference_raw) != REFERENCE_SHA256
            or _sha(license_raw) != LICENSE_SHA256
        ):
            raise ValueError("pinned official source or license mismatch")
        sources = {
            "ncps_cfc_cell.py": reference_raw,
            "ncps_LICENSE": license_raw,
            "hepta_cfc.py": Path(inspect.getsourcefile(CfCModel)).read_bytes(),
            "hepta_models.py": Path(inspect.getsourcefile(Model)).read_bytes(),
            "probe.py": Path(__file__).read_bytes(),
        }
        report["source_sha256s"] = {name: _sha(raw) for name, raw in sources.items()}
        for name, raw in sources.items():
            (output / name).write_bytes(raw)
        official = types.ModuleType("hepta_pinned_ncps_cell")
        exec(
            compile(reference_raw, str(Path(reference_path)), "exec"), official.__dict__
        )
        for seed in report["seeds"]:
            for batch in report["batches"]:
                report["cases"].append(
                    _case(torch, official.CfCCell, seed, batch, arrays)
                )
        report["status"] = "passed_numerical_reference_only"
        report["summary"] = dict(
            cases=len(report["cases"]),
            transitions=sum(len(c["transitions"]) for c in report["cases"]),
            parameter_gradient_coordinates=sum(
                c["parameter_coordinates"] for c in report["cases"]
            ),
            input_derivative_coordinates=sum(
                c["input_derivative_coordinates"] for c in report["cases"]
            ),
            previous_state_derivative_coordinates=sum(
                c["previous_state_derivative_coordinates"] for c in report["cases"]
            ),
            maximum_parameter_gradient_absolute_error=max(
                max(c["parameter_gradient_max_absolute_errors"].values())
                for c in report["cases"]
            ),
            maximum_state_absolute_error=max(
                t["state_max_absolute_error"]
                for c in report["cases"]
                for t in c["transitions"]
            ),
            maximum_input_derivative_absolute_error=max(
                t["input_derivative_max_absolute_error"]
                for c in report["cases"]
                for t in c["transitions"]
            ),
            maximum_previous_state_derivative_absolute_error=max(
                t["previous_state_derivative_max_absolute_error"]
                for c in report["cases"]
                for t in c["transitions"]
            ),
        )
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report.update(
            wall_ns=time.perf_counter_ns() - started,
            process_cpu_ns=time.process_time_ns() - cpu,
        )
        with (output / "ARRAYS.npz").open("xb") as stream:
            np.savez_compressed(stream, **arrays)
        report["arrays_sha256"] = _sha((output / "ARRAYS.npz").read_bytes())
        with (output / "REPORT.json").open("x") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_probe(args.reference, args.license, args.output)
    print(json.dumps({"status": report["status"], **report["summary"]}, sort_keys=True))


if __name__ == "__main__":
    main()
