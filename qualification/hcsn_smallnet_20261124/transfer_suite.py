"""Exact-rule and coordinate controls on real SmallHCSN checkpoints.

Independent trained seeds are separate calls to run_transfers. Permutations and
readout-basis views of one seed are equivalence controls, not extra statistical
samples. The sign view is an explicit coordinate adapter at the readout; it is
NOT a sign symmetry of the physical population dynamics.
"""

from copy import deepcopy
from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import torch
from torch import nn

from .editing import interface_program, propose, tensor_digest


INPUT_PATHS = ("input_drive", "input_mark")
_UNIT_VECTORS = ("raw_cost", "raw_boundary", "reset_absolute", "fixed_boundary")
_KNOWN_STATE_KEYS = frozenset((
    "input_drive.weight", "input_drive.bias", "input_mark.weight", "input_mark.bias",
    "recurrent.weight", "synaptic_mask", "readout.weight", "readout.bias", *_UNIT_VECTORS))


def _validate_order(order, neurons):
    raw = torch.as_tensor(order)
    if raw.dtype not in (torch.int8, torch.int16, torch.int32, torch.int64, torch.uint8):
        raise ValueError("a population permutation must contain actual integer indices")
    values = raw.to(dtype=torch.long, device="cpu")
    if (values.shape != (neurons,) or sorted(values.tolist()) != list(range(neurons))
            or bool((values[:neurons // 2] >= neurons // 2).any())
            or bool((values[neurons // 2:] < neurons // 2).any())):
        raise ValueError("order[new_unit]=old_unit must separately permute senders and receivers")
    return values


def receiver_feature_order(order, neurons):
    values = _validate_order(order, neurons)
    receiver = values[neurons // 2:] - neurons // 2
    return (receiver[:, None] * 5 + torch.arange(5)).reshape(-1)


def permute_population_state(state, order, neurons):
    """Move all complete-state unit axes, including the different message axis."""
    values = _validate_order(order, neurons)
    if (not is_dataclass(state) or set(state.__dataclass_fields__) !=
            {"density", "boundary", "drift", "cost", "message", "step", "config"}):
        raise ValueError("unrecognized complete population state; do not guess its axes")
    changes = {}
    for name in ("density", "boundary", "drift", "cost"):
        tensor = getattr(state, name)
        if tensor.ndim < 2 or tensor.shape[1] != neurons:
            raise ValueError("complete state has an incompatible population axis")
        changes[name] = tensor.index_select(1, values.to(tensor.device))
    if state.message.ndim != 3 or state.message.shape[1:] != (3, neurons):
        raise ValueError("message must retain its three channels and all neurons")
    changes["message"] = state.message.index_select(2, values.to(state.message.device))
    return replace(state, **changes)


def permute_model_state(state_dict, order, neurons):
    """Explicit SmallHCSN gauge, including heterogeneous physical buffers.

    Fail closed if the model adds a field that this mapping does not understand.
    The feature layout is receiver-major with five features per receiver.
    """
    values = _validate_order(order, neurons)
    if set(state_dict) != _KNOWN_STATE_KEYS:
        raise ValueError("SmallHCSN state schema changed; re-audit every population-dependent field")
    result = {name: tensor.detach().clone() for name, tensor in state_dict.items()}
    half = neurons // 2
    for name in _UNIT_VECTORS:
        tensor = state_dict[name]
        if tensor.shape != (neurons,):
            raise ValueError("physical/control vectors must retain every independent neuron")
        result[name] = tensor.index_select(0, values.to(tensor.device)).clone()
    for path in INPUT_PATHS:
        for suffix in ("weight", "bias"):
            name = path + "." + suffix
            tensor = state_dict[name]
            if tensor.shape[0] != half:
                raise ValueError("raw-input branches must target senders only")
            result[name] = tensor.index_select(0, values[:half].to(tensor.device)).clone()
    columns = torch.cat((values, values + neurons, values + 2 * neurons))
    for name in ("recurrent.weight", "synaptic_mask"):
        tensor = state_dict[name]
        if tensor.shape != (neurons, 3 * neurons):
            raise ValueError("coupling must expose all three complete message blocks")
        result[name] = tensor.index_select(0, values.to(tensor.device)).index_select(
            1, columns.to(tensor.device)).clone()
    feature_order = receiver_feature_order(values, neurons)
    readout = state_dict["readout.weight"]
    if readout.shape[1] != 5 * half:
        raise ValueError("readout must contain receiver features only")
    result["readout.weight"] = readout.index_select(1, feature_order.to(readout.device)).clone()
    return result


class ReadoutBasisView(nn.Module):
    """An explicit signed FEATURE-coordinate view, with unchanged dynamics.

    Inner features z are represented as z'=z*signs. The corresponding head is
    W'=W*signs, so logits agree. The state dictionary includes both the inner
    checkpoint and signs; running its weights without this adapter is invalid.
    This is intentionally separate from population permutation.
    """

    def __init__(self, model, signs):
        super().__init__()
        if not isinstance(getattr(model, "readout", None), nn.Linear):
            raise TypeError("a Linear readout is required")
        self.inner = deepcopy(model)
        vector = torch.as_tensor(signs, dtype=model.readout.weight.dtype,
                                 device=model.readout.weight.device)
        if vector.shape != (model.readout.in_features,) or not bool(((vector == 1) | (vector == -1)).all()):
            raise ValueError("one exact +1/-1 sign per readout feature required")
        self.register_buffer("signs", vector.clone())
        with torch.no_grad():
            self.inner.readout.weight.mul_(self.signs)
        self._basis_hook = self.inner.readout.register_forward_pre_hook(self._to_basis)

    def _to_basis(self, module, arguments):
        return (arguments[0] * self.signs.to(arguments[0]), *arguments[1:])

    @property
    def config(self):
        return self.inner.config

    @property
    def readout(self):
        return self.inner.readout

    def initial_state(self, *args, **kwargs):
        return self.inner.initial_state(*args, **kwargs)

    def forward(self, *args, **kwargs):
        output = self.inner(*args, **kwargs)
        if kwargs.get("return_features", False):
            logits, features, state = output
            return logits, features * self.signs.to(features), state
        return output


def _comparison(actual, expected, atol, rtol):
    if (not isinstance(actual, torch.Tensor) or not isinstance(expected, torch.Tensor)
            or actual.shape != expected.shape):
        return {"passed": False, "reason": "tensor_shape_or_type_mismatch"}
    finite = bool(torch.isfinite(actual).all() and torch.isfinite(expected).all())
    if not finite:
        return {"passed": False, "finite": False}
    difference = (actual.double() - expected.double()).abs()
    scaled = difference / (atol + rtol * expected.double().abs())
    largest = float(difference.max()) if difference.numel() else 0.0
    scaled_largest = float(scaled.max()) if scaled.numel() else 0.0
    return {"passed": bool((scaled <= 1).all()), "finite": True,
            "max_abs": largest if math.isfinite(largest) else None,
            "max_scaled": scaled_largest if math.isfinite(scaled_largest) else None,
            "elements": difference.numel()}


def _state_comparison(actual, expected, atol, rtol):
    names = ("density", "boundary", "drift", "cost", "message")
    details = {name: _comparison(getattr(actual, name), getattr(expected, name), atol, rtol)
               for name in names}
    clock = type(actual.step) is int and actual.step == expected.step
    configuration = actual.config == expected.config
    return {"passed": clock and configuration and all(row["passed"] for row in details.values()),
            "clock_equal": clock, "configuration_equal": configuration,
            "step": actual.step, "tensors": details}


def _full_comparison(actual, expected, atol, rtol):
    logits, features, state = actual
    expected_logits, expected_features, expected_state = expected
    checks = {"logits": _comparison(logits, expected_logits, atol, rtol),
              "features": _comparison(features, expected_features, atol, rtol),
              "complete_state": _state_comparison(state, expected_state, atol, rtol)}
    predictions = int(torch.count_nonzero(logits.argmax(-1) != expected_logits.argmax(-1)))
    return {"passed": all(row["passed"] for row in checks.values()) and predictions == 0,
            "prediction_disagreements": predictions, **checks}


def run_transfers(model, inputs, initial_state_factory=None, *, output_path=None, seed=2401124):
    """Run label-free controls and optionally create one complete JSON record.

    ``inputs`` is [time,batch,input]; no labels are accepted. A factory, when
    supplied, is called once as factory(model,batch_size). Its complete state is
    copied and correctly permuted. A caller must not count views as new seeds.
    All proposals, clones, transforms, checks and forwards are charged here.
    This function does not measure the LLM's program-discovery cost or training.
    """
    started, cpu_started = time.perf_counter(), time.process_time()
    if (inputs.ndim != 3 or min(inputs.shape) < 1 or not bool(torch.isfinite(inputs).all())
            or not isinstance(getattr(model, "readout", None), nn.Linear)
            or not hasattr(model.config, "neurons")):
        raise ValueError("SmallHCSN and finite [time,batch,input] probes required")
    if output_path is not None and Path(output_path).exists():
        raise FileExistsError("transfer evidence is create-only")
    source_digest = tensor_digest(model.state_dict())
    double = model.readout.weight.dtype == torch.float64
    atol, rtol = (2e-9, 2e-8) if double else (3e-5, 3e-5)
    phases, forward_calls, forward_rows = [], 0, 0
    report = {"schema": "hcsn-program-transfer-controls-v1", "seed": seed,
              "source_digest": source_digest, "config": asdict(model.config),
              "inputs_digest": tensor_digest({"unlabeled_inputs": inputs}),
              "input_shape": list(inputs.shape), "tolerances": {"atol": atol, "rtol": rtol},
              "implementation": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in ("editing.py", "transfer_suite.py", "model.py")},
              "classification": {"independent_trained_checkpoint_count": 1,
                  "views_are_independent_training_runs": False,
                  "population_sign_symmetry_claimed": False,
                  "label_schema_rule_is_new_discrimination": False},
              "label_accesses": 0, "panels": {}}

    def synchronize():
        if inputs.is_cuda:
            torch.cuda.synchronize(inputs.device)

    def forward(subject, data, state):
        nonlocal forward_calls, forward_rows
        # Count attempted work even if a numerical boundary refuses a run.
        forward_calls += 1
        forward_rows += data.shape[0] * data.shape[1]
        result = subject(data, return_features=True, state=deepcopy(state))
        synchronize()
        return result

    def phase(name, operation):
        wall, cpu = time.perf_counter(), time.process_time()
        before = forward_calls
        status = "interrupted"
        try:
            result = operation()
            status = "completed"
            return result
        except Exception as exc:
            status = "failed"
            report["panels"][name] = {"passed": False, "status": "FAILED",
                "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()}
            return None
        finally:
            synchronize()
            phases.append({"name": name, "status": status,
                           "wall_seconds": time.perf_counter() - wall,
                           "cpu_seconds": time.process_time() - cpu,
                           "attempted_forward_calls": forward_calls - before})

    with torch.no_grad():
        def initialize():
            original = deepcopy(model).eval()
            initial = (initial_state_factory(original, inputs.shape[1]) if initial_state_factory is not None
                       else original.initial_state(inputs.shape[1]))
            return original, initial
        initialized = phase("initialization", initialize)
        baseline = None
        if initialized is not None:
            original, initial = initialized
            report["initial_state"] = {
                "tensor_digest": tensor_digest({name: getattr(initial, name) for name in
                    ("density", "boundary", "drift", "cost", "message")}),
                "step": initial.step, "config": asdict(initial.config),
                "factory": "caller-supplied" if initial_state_factory is not None else "model.initial_state"}
            baseline = phase("reference", lambda: forward(original, inputs, initial))
        if baseline is not None:
            neurons, half, dimension = model.config.neurons, model.config.neurons // 2, inputs.shape[-1]
            generator = torch.Generator(device="cpu").manual_seed(seed)
            order = torch.cat((torch.randperm(half, generator=generator),
                               torch.randperm(half, generator=generator) + half))
            signs = (2 * torch.randint(0, 2, (model.readout.in_features,), generator=generator) - 1).to(
                dtype=model.readout.weight.dtype, device=model.readout.weight.device)
            # Ensure a nontrivial declared coordinate view, without looking at outcomes.
            signs[0] = -1
            matrix = torch.eye(dimension, dtype=torch.float64, device=inputs.device)
            matrix[0, 0] = 1.25
            if dimension > 1:
                matrix[1, 1] = .8
                matrix[0, 1] = .1
            offset = torch.linspace(-.08, .08, dimension, dtype=torch.float64, device=inputs.device)
            transform = {"matrix": matrix, "offset": offset}
            transformed_inputs = inputs @ matrix.to(inputs).T + offset.to(inputs)
            label_rule = {"kind": "class_permutation",
                          "old_to_new": list(reversed(range(model.readout.out_features))),
                          "scope": "replacement_label_schema"}
            inverse_labels = torch.argsort(torch.tensor(label_rule["old_to_new"], device=inputs.device))
            report["rules"] = {"input_matrix": matrix.cpu().tolist(), "input_offset": offset.cpu().tolist(),
                               "direct_input_paths": list(INPUT_PATHS), "population_order": order.tolist(),
                               "readout_basis_signs": signs.cpu().tolist(), "label_rule": label_rule}
            interface_state = None

            def input_panel():
                nonlocal interface_state
                interface_state, receipt = interface_program(original.state_dict(), INPUT_PATHS, transform)
                migrated = deepcopy(original)
                migrated.load_state_dict(interface_state)
                actual = forward(migrated, transformed_inputs, initial)
                result = _full_comparison(actual, baseline, atol, rtol)
                result.update(program=receipt, scope="same task under the declared new input interface")
                result["passed"] = result["passed"] and receipt["status"] in ("CANDIDATE", "KEEP")
                report["panels"]["input_interface"] = result
                return result
            phase("input_interface", input_panel)

            def unit_panel():
                candidate = permute_model_state(original.state_dict(), order, neurons)
                permuted = deepcopy(original)
                permuted.load_state_dict(candidate)
                new_initial = permute_population_state(initial, order, neurons)
                actual = forward(permuted, inputs, new_initial)
                columns = receiver_feature_order(order, neurons).to(inputs.device)
                expected = (baseline[0], baseline[1].index_select(-1, columns),
                            permute_population_state(baseline[2], order, neurons))
                result = _full_comparison(actual, expected, atol, rtol)
                result["scope"] = "within-role population permutation; all physical and state axes mapped"
                if interface_state is not None:
                    rerun, receipt = interface_program(candidate, INPUT_PATHS, transform)
                    expected_state = permute_model_state(interface_state, order, neurons)
                    comparisons = {name: _comparison(rerun[name], expected_state[name], atol, rtol)
                                   for name in rerun}
                    result["interface_program_equivariance"] = {
                        "passed": all(row["passed"] for row in comparisons.values()),
                        "tensors": comparisons, "program": receipt}
                    result["passed"] = result["passed"] and result["interface_program_equivariance"]["passed"]
                report["panels"]["population_permutation"] = result
                return result
            phase("population_permutation", unit_panel)

            def basis_panel():
                view = ReadoutBasisView(original, signs).eval()
                actual = forward(view, inputs, initial)
                expected = (baseline[0], baseline[1] * signs.to(baseline[1]), baseline[2])
                result = _full_comparison(actual, expected, atol, rtol)
                result.update(scope="explicit readout feature coordinates only; physical neuron signs unchanged",
                              complete_view_digest=tensor_digest(view.state_dict()))
                report["panels"]["readout_basis"] = result
                return result
            phase("readout_basis", basis_panel)

            def rule_panel():
                candidate, receipt = propose(original, rule=label_rule)
                applied = deepcopy(original)
                applied.load_state_dict(candidate)
                actual = forward(applied, inputs, initial)
                expected = (baseline[0].index_select(-1, inverse_labels), baseline[1], baseline[2])
                result = _full_comparison(actual, expected, atol, rtol)
                result.update(program=receipt, scope="replacement label schema, not simultaneous contradictory tasks")
                report["panels"]["label_schema_program"] = result
                return candidate
            base_rule_state = phase("label_schema_program", rule_panel)

            def basis_rule_panel():
                view = ReadoutBasisView(original, signs).eval()
                candidate, receipt = propose(view.inner, rule=label_rule)
                view.inner.load_state_dict(candidate)
                actual = forward(view, inputs, initial)
                expected = (baseline[0].index_select(-1, inverse_labels),
                            baseline[1] * signs.to(baseline[1]), baseline[2])
                result = _full_comparison(actual, expected, atol, rtol)
                result.update(program=receipt, scope="program rereads the coordinate-transformed checkpoint",
                              complete_view_digest=tensor_digest(view.state_dict()))
                report["panels"]["program_rerun_after_basis_change"] = result
                return result
            phase("program_rerun_after_basis_change", basis_rule_panel)

            if base_rule_state is not None:
                def copied_delta_panel():
                    view = ReadoutBasisView(original, signs).eval()
                    state = view.inner.state_dict()
                    for name in ("readout.weight", "readout.bias"):
                        state[name] = state[name] + base_rule_state[name] - original.state_dict()[name]
                    view.inner.load_state_dict(state)
                    actual = forward(view, inputs, initial)
                    expected = baseline[0].index_select(-1, inverse_labels)
                    result = _comparison(actual[0], expected, atol, rtol)
                    report["panels"]["copied_fixed_delta_control"] = {
                        "expected_rule_equivalence": result,
                        "prediction_disagreements": int(torch.count_nonzero(actual[0].argmax(-1) != expected.argmax(-1))),
                        "scope": "negative control; a failure to differ is reported, never retried",
                        "excluded_from_positive_control_gate": True}
                    return result
                phase("copied_fixed_delta_control", copied_delta_panel)

    unchanged = tensor_digest(model.state_dict()) == source_digest
    positive_names = ("input_interface", "population_permutation", "readout_basis",
                      "label_schema_program", "program_rerun_after_basis_change")
    report["source_unchanged"] = unchanged
    report["all_positive_controls_passed"] = unchanged and all(
        report["panels"].get(name, {}).get("passed", False) for name in positive_names)
    report["cost"] = {"attempted_forward_calls": forward_calls,
                      "attempted_forward_event_rows": forward_rows, "phases": phases,
                      "program_discovery_cost": "not instrumented; no total learning-time claim",
                      "boundary": "function entry through all proposals, clones, hashes, forwards and checks; JSON emission tail excluded",
                      "cpu_seconds": time.process_time() - cpu_started,
                      "wall_seconds": time.perf_counter() - started}
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    return report
