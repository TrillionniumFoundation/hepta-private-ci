"""One registered engineering pass on a cold-loaded real SmallHCSN profile.

No historical experiment is rerun. Matrix examples test the quadratic solver;
only the pinned physical model supplies the reported parameter sensitivities.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import signal
import sys
import time
import traceback

import numpy as np

from first_order import (Coordinate, Linearization, candidate_state, controlled_finite_difference,
                         linearize_fresh, solve_gauss_newton)

PARENT_SHA256 = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
COORDINATES = (
    Coordinate("raw_cost", 4), Coordinate("input_drive.weight", 0),
    Coordinate("input_mark.weight", 0), Coordinate("recurrent.weight", 96),
    Coordinate("readout.weight", 0), Coordinate("readout.bias", 0),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fixture():
    x = np.zeros((4, 2, 6), dtype=np.float64)
    x[0, :, 0], x[0, :, 2] = (-0.4, 0.6), 1.0
    x[2, :, 1], x[2, :, 3] = (0.7, -0.2), 1.0
    x[:, :, 4] = np.arange(4)[:, None] / 3
    x[:, :, 5] = ((0.03, -0.02), (-0.01, 0.04), (0.02, 0.02), (-0.03, 0.01))
    return x, np.array([0.59, 0.73], dtype=np.float64)


def matrix_linearization(jacobian, base):
    return Linearization(tuple(Coordinate("matrix_test", i) for i in range(jacobian.shape[1])),
                         base, jacobian, {"linearization_sha256": "1" * 64,
                         "parent_state_sha256": "2" * 64, "coordinate_sha256": "3" * 64})


def quadratic_checks():
    base = np.array([0.1, 0.2, 0.3])
    j = np.array([[1.0, 2.0], [0.0, 1.0], [2.0, -1.0]])
    step = solve_gauss_newton(matrix_linearization(j, base), base + [1.0, -2.0, 0.5],
                             ridge=0.25, observation_weights=[1.0, 2.0, 0.5])
    # Independently derived two-by-two normal equations: [[3.25,1],[1,6.75]].
    expected = np.array([12.375, -8.8125]) / 20.9375
    np.testing.assert_allclose(step["delta"], expected, atol=1e-12, rtol=1e-12)
    require(step["data_rank"] == 2 and step["stationarity_max_abs"] < 1e-12, "quadratic exact solution failed")
    cases = [step]
    for ridge in (0.0, 0.25):
        zero = solve_gauss_newton(matrix_linearization(np.zeros((3, 2)), base), base + 1, ridge=ridge)
        require(zero["data_rank"] == 0 and zero["data_nullity"] == 2
                and zero["nonzero_condition_number"] is None and zero["delta"] == [0.0, 0.0]
                and zero["regularized_problem_unique"] == (ridge > 0), "zero-information semantics changed")
        json.dumps(zero, allow_nan=False)
        cases.append(zero)
    deficient = solve_gauss_newton(matrix_linearization(np.array([[1.0, 1.0], [2.0, 2.0]]),
                                  np.zeros(2)), [1, 2], ridge=0.25)
    require(deficient["data_rank"] == 1 and deficient["data_nullity"] == 1
            and not deficient["data_full_column_rank"] and deficient["regularized_problem_unique"],
            "ridge was confused with data identification")
    cases.append(deficient)
    return cases


def execute(args, protocol, result):
    root = Path(__file__).resolve().parent
    profile_root = Path(args.profile_module_dir).resolve()
    require(set(protocol["source_sha256"]) == {
        "first_order.py", "verify_first_order.py", "small_hcsn_profile.py",
        "profile_io.py", "source_binding.py"}, "complete implementation source pins required")
    for name, expected in protocol["source_sha256"].items():
        actual_path = root / name if name in ("first_order.py", "verify_first_order.py") else profile_root / name
        require(sha(actual_path) == expected, "registered implementation source changed: " + name)
    sys.path.insert(0, str(profile_root))
    import small_hcsn_profile
    require(Path(small_hcsn_profile.__file__).resolve() == profile_root / "small_hcsn_profile.py", "wrong profile import")
    profile = small_hcsn_profile.load_profile(args.profile, protocol["parent_profile_sha256"], args.materials)
    require(profile.candidate_sha256 == PARENT_SHA256 == protocol["parent_checkpoint_sha256"], "different physical parent")
    c = profile.model.config
    require((c.neurons, c.feature_bank, c.message_mode, c.boundary_mode, c.backend, c.precision)
            == (8, "value_risk", "full", "qvi", "dense", "float64"), "fixed engineering parent family changed")
    result["parent"] = {"profile_sha256": profile.profile_sha256, "checkpoint_sha256": profile.candidate_sha256,
                        "state_sha256": profile.model_state_sha256, "source_binding_sha256": profile.source_binding_sha256,
                        "config": asdict(c)}
    result["quadratic_checks"] = quadratic_checks()
    model, torch = profile.model, profile.torch
    gradient_before = {name: None if p.grad is None else p.grad.detach().clone() for name, p in model.named_parameters()}
    original = {name: value.clone() for name, value in model.state_dict().items()}
    x, margin = fixture()
    linearization = linearize_fresh(model, x, margin, COORDINATES,
                                   state_fingerprint=small_hcsn_profile.tensor_state_sha256)
    require(linearization.jacobian.shape == (2, 6), "shared coordinate/output count changed")
    result["linearization"] = {**linearization.metadata, "base_output": linearization.base_output.tolist(),
                               "jacobian": linearization.jacobian.tolist()}
    result["finite_difference"] = controlled_finite_difference(model, x, margin, linearization,
        state_fingerprint=small_hcsn_profile.tensor_state_sha256, h=1e-5, atol=1e-7, rtol=3e-5)
    require(result["finite_difference"]["passed"], "fixed AD/FD check unresolved or failed; no retuning")
    # This deliberately tiny, declared engineering residual tests materialization.
    # It is not a natural-task label, a performance benchmark, or a learned benefit.
    step = solve_gauss_newton(linearization, linearization.base_output + [1e-4, -1e-4], ridge=1e-3)
    require(1 <= step["data_rank"] <= 2 and step["data_nullity"] >= 4
            and not step["data_full_column_rank"], "two observations falsely identify six coordinates")
    state, edit = candidate_state(model, linearization, step,
        state_fingerprint=small_hcsn_profile.tensor_state_sha256, max_step_norm=1.0)
    allowed = {}
    for coordinate in COORDINATES:
        allowed.setdefault(coordinate.name, set()).add(coordinate.flat_index)
    for name, value in state.items():
        changed = set(torch.nonzero(value.reshape(-1) != original[name].reshape(-1)).flatten().tolist())
        require(changed <= allowed.get(name, set()), "unregistered parameter or buffer changed")
    require(profile.current_state_sha256() == profile.model_state_sha256, "parent model was mutated")
    for name, parameter in model.named_parameters():
        before = gradient_before[name]
        require(parameter.grad is None if before is None else parameter.grad is not None
                and torch.equal(parameter.grad, before), "VJP changed an accumulated gradient")
    result["engineering_step"] = step
    result["candidate_construction"] = edit
    result["candidate_exported"] = False
    result["candidate_adopted"] = False
    result["physical_forward_calls"] = 26
    result["scalar_output_vjp_calls"] = 2
    result["quadratic_solves"] = 5
    result["status"] = "PASSED_BOUNDED_ENGINEERING"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "protocol-sha256", "profile", "profile-module-dir", "materials", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(sha(args.protocol) == args.protocol_sha256, "registered protocol changed")
    protocol = json.loads(Path(args.protocol).read_text())
    require(protocol["schema"] == "hepta.smallhcsn.sensitivity-engineering.v1"
            and protocol["ready_for_execution"] is True, "protocol is not registered for execution")
    require(protocol["coordinates"] == [c.record() for c in COORDINATES]
            and protocol["fd"] == {"h": 1e-5, "half_h": 5e-6, "atol": 1e-7, "rtol": 3e-5,
                                   "one_sided_gap_floor_factor": 4, "gap_shrink_ratio": 0.75}
            and protocol["max_step_norm"] == 1.0, "fixed engineering settings changed")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    signal.alarm(120)
    resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
    result = {"schema": "hepta.smallhcsn.sensitivity-engineering-result.v1",
              "protocol_sha256": args.protocol_sha256, "status": "FAILED",
              "historical_matrix_rerun": False, "training_updates": 0, "test_retuning": False,
              "second_order_autograd": False, "actual_task_improvement_claim": False}
    try:
        execute(args, protocol, result)
    except Exception as error:
        result["error"] = repr(error)
        result["traceback"] = traceback.format_exc()
    finally:
        signal.alarm(0)
        result["wall_s"] = time.perf_counter() - started
        result["cpu_s"] = time.process_time() - cpu
        with (output / "RESULT.json").open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"status": result["status"], "result_sha256": sha(output / "RESULT.json")}))
    return 0 if result["status"] == "PASSED_BOUNDED_ENGINEERING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
