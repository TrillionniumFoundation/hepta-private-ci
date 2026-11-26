"""One actual-reduction-guarded trial from a retained nonsmooth surrogate.

The original smooth finite-difference scope remains FAILED. Its midpoint
primitive-VJP matrix is only an algebraic proposal model here: this scope does
not certify a classical or Clarke Jacobian, or a semismooth Newton method.
There is one solve, at most one fresh physical forward, and no retry. A complete
research candidate is exported only after actual objective reduction passes.
"""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import resource
import signal
import sys
import time
import traceback

FAILED_RESULT_SHA256 = "15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105"
PARENT_SHA256 = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
FIRST_ORDER_SHA256 = "eecdf0a2f6aabbdbc65b79ed44c96b5badbd406c51252d89643260a923b5a55f"
FIXTURE_SOURCE_SHA256 = "8506d27e0a5740901e0bdb40da17478de009d41629125d0888ba81ece01c374d"
SOURCES = (
    "nonsmooth_trial_v4/nonsmooth_trial.py",
    "sensitivity_v4/first_order.py", "sensitivity_v4/verify_first_order.py",
    "native_profile_v4/small_hcsn_profile.py", "native_profile_v4/profile_io.py",
    "native_profile_v4/source_binding.py",
)
COORDINATES = [
    {"name": "raw_cost", "flat_index": 4, "scale": 1.0},
    {"name": "input_drive.weight", "flat_index": 0, "scale": 1.0},
    {"name": "input_mark.weight", "flat_index": 0, "scale": 1.0},
    {"name": "recurrent.weight", "flat_index": 96, "scale": 1.0},
    {"name": "readout.weight", "flat_index": 0, "scale": 1.0},
    {"name": "readout.bias", "flat_index": 0, "scale": 1.0},
]
OBJECTIVE = {
    "target_rule": "retained base_output + [0.0001,-0.0001]",
    "target_offset": [1e-4, -1e-4], "observation_weights": [1.0, 1.0],
    "ridge": 1e-3, "max_step_norm": 1.0,
    "residual": "prediction minus target",
    "state": "fresh complete four-tick trajectory; rebuild initial_state after the edit",
}
GATE = {"absolute_floor": 1e-12, "relative_floor": 1e-6, "minimum_ratio": 0.1,
        "rule": "pred > tau and ared > tau and ared/pred >= minimum_ratio",
        "tau": "absolute_floor + relative_floor * max(abs(Phi0), abs(Phi_trial))"}
BUDGET = {"runs": 1, "quadratic_solves": 1, "physical_forward_calls": 1,
          "scalar_output_vjp_calls": 0, "new_linearizations": 0,
          "finite_difference_calls": 0, "backtracking_steps": 0, "retries": 0,
          "training_loop_updates": 0, "candidate_exports": 1,
          "maximum_wall_seconds": 120, "maximum_cpu_seconds": 120,
          "intraop_threads": 1, "interop_threads": 1}
MAX_JSON = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned(path, expected):
    require(isinstance(expected, str) and len(expected) == 64
            and all(c in "0123456789abcdef" for c in expected), "SHA-256 pin required")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    require(0 < len(raw) <= MAX_JSON and hashlib.sha256(raw).hexdigest() == expected,
            "bounded pinned input differs: " + str(path))
    return raw


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite JSON number")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def verify_sources(args, protocol):
    roots = {"nonsmooth_trial_v4": Path(__file__).resolve().parent,
             "sensitivity_v4": Path(args.sensitivity_module_dir).resolve(),
             "native_profile_v4": Path(args.profile_module_dir).resolve()}
    require(set(protocol["source_sha256"]) == set(SOURCES), "complete implementation pins required")
    require(protocol["source_sha256"]["sensitivity_v4/first_order.py"] == FIRST_ORDER_SHA256
            and protocol["source_sha256"]["sensitivity_v4/verify_first_order.py"] == FIXTURE_SOURCE_SHA256,
            "original solver and fixture sources must remain unchanged")
    for name, expected in protocol["source_sha256"].items():
        directory, filename = name.split("/")
        read_pinned(roots[directory] / filename, expected)
    return roots


def require_original_failure(receipt):
    require(receipt.get("schema") == "hepta.smallhcsn.sensitivity-engineering-result.v1"
            and receipt.get("status") == "FAILED"
            and receipt.get("training_updates") == 0
            and receipt.get("second_order_autograd") is False,
            "the exact original FAILED smooth scope is required")
    fd = receipt["finite_difference"]
    rows = fd["rows"]
    require(fd["passed"] is False and fd["atol"] == 1e-7 and fd["rtol"] == 3e-5
            and len(rows) == 6
            and [{key: row[key] for key in ("name", "flat_index", "scale")} for row in rows] == COORDINATES,
            "original failed coordinate roster or FD settings differ")
    require(all(row["h"] == 1e-5 and row["half_h"] == 5e-6
                and row["central_scales_agree"] is True and row["vjp_matches_fd"] is True for row in rows)
            and rows[0]["stencil_resolved"] is False
            and rows[0]["status"] == "INCONCLUSIVE_OR_FAILED"
            and all(row["stencil_resolved"] is True and row["status"] == "PASSED" for row in rows[1:]),
            "scope only admits the retained raw_cost[4] nonsmooth failure, not a changed diagnostic")
    require("engineering_step" not in receipt and "candidate_construction" not in receipt,
            "original scope must have stopped before any step or candidate construction")
    return receipt


def restored_forward(parent, candidate, candidate_sha256, x, margin, result, fingerprint):
    """Temporarily evaluate true physics, then restore every parent tensor.

    LoadedProfile.forward deliberately cannot be used while its model differs
    from the frozen parent. Use the same physical model directly and its public
    population checker, without changing the profile identity or frozen guard.
    """
    torch, model = parent.torch, parent.model
    parent.require_frozen()
    original = {name: value.detach().clone() for name, value in model.state_dict().items()}
    diagnostics = copy.deepcopy(model.last_diagnostics)
    gradients = {name: None if parameter.grad is None else parameter.grad.detach().clone()
                 for name, parameter in model.named_parameters()}
    try:
        with torch.no_grad():
            model.load_state_dict(candidate, strict=True)
            require(fingerprint(model.state_dict()) == candidate_sha256, "temporary candidate load differs")
            initial = model.initial_state(x.shape[1], margin)
            parent.check_population(initial)
            require(initial.step == 0, "trial requires a fresh initial population")
            result["counts"]["physical_forward_calls"] += 1
            require(result["counts"]["physical_forward_calls"] == 1, "one-forward trial budget exceeded")
            logits, features, final_state = model(x, state=initial, return_features=True)
            parent.check_population(final_state)
            require(final_state.step == x.shape[0]
                    and bool(torch.isfinite(logits).all() and torch.isfinite(features).all()),
                    "invalid final clock or nonfinite physical output")
            require(fingerprint(model.state_dict()) == candidate_sha256, "physical forward changed model tensors")
            prediction = (logits[-1, :, 1] - logits[-1, :, 0]).detach().cpu().numpy().copy()
            require(prediction.shape == (2,), "fixed trial output shape changed")
            return prediction
    finally:
        with torch.no_grad():
            model.load_state_dict(original, strict=True)
        model.last_diagnostics = diagnostics
        restored = model.state_dict()
        require(set(restored) == set(original)
                and all(torch.equal(restored[name], value) for name, value in original.items()),
                "complete parent restoration failed")
        parent.require_frozen()
        for name, parameter in model.named_parameters():
            before = gradients[name]
            require(parameter.grad is None if before is None else parameter.grad is not None
                    and torch.equal(parameter.grad, before), "trial changed an accumulated gradient")
        result["parent_restored"] = True
        result["parent_state_after_sha256"] = parent.current_state_sha256()
        result["accumulated_gradients_unchanged"] = True
        result["diagnostics_restored"] = True


def execute(args, protocol, output, result):
    # Check the exact FAILED evidence before importing numerical dependencies.
    receipt = require_original_failure(parse(read_pinned(args.sensitivity_result, FAILED_RESULT_SHA256)))
    roots = verify_sources(args, protocol)
    sys.path.insert(0, str(roots["sensitivity_v4"]))
    sys.path.insert(0, str(roots["native_profile_v4"]))
    import first_order
    import verify_first_order
    import small_hcsn_profile
    import profile_io
    from source_binding import RUNTIME
    for module, directory in ((first_order, roots["sensitivity_v4"]),
                              (verify_first_order, roots["sensitivity_v4"]),
                              (small_hcsn_profile, roots["native_profile_v4"]),
                              (profile_io, roots["native_profile_v4"])):
        require(Path(module.__file__).resolve().parent == directory, "wrong dependency import")
    require(protocol["runtime"] == RUNTIME
            and [coordinate.record() for coordinate in verify_first_order.COORDINATES] == COORDINATES,
            "runtime or original fixed coordinates changed")
    parent = small_hcsn_profile.load_profile(args.parent_profile, protocol["parent_profile_sha256"], args.materials)
    old_parent = receipt["parent"]
    require(parent.profile_sha256 == old_parent["profile_sha256"]
            and parent.candidate_sha256 == old_parent["checkpoint_sha256"] == PARENT_SHA256
            and parent.model_state_sha256 == old_parent["state_sha256"]
            and parent.source_binding_sha256 == old_parent["source_binding_sha256"]
            and parent.config == old_parent["config"]
            and parent.manifest["runtime"] == RUNTIME
            and parent.manifest["format"] == "actual_p2p_v2_full", "physical parent or runtime differs")
    result["parent"] = dict(old_parent)
    result["original_sensitivity_protocol_sha256"] = receipt["protocol_sha256"]
    result["parent_restored"] = True
    result["parent_state_after_sha256"] = parent.current_state_sha256()
    result["accumulated_gradients_unchanged"] = True
    result["diagnostics_restored"] = True
    np = first_order.np
    coordinates = verify_first_order.COORDINATES
    x, margin = verify_first_order.fixture()
    x, margin = first_order._inputs(parent.model, x, margin)
    linear = receipt["linearization"]
    metadata = {key: value for key, value in linear.items() if key not in ("base_output", "jacobian")}
    body = {key: value for key, value in metadata.items() if key != "linearization_sha256"}
    base, jacobian = np.array(linear["base_output"], dtype=np.float64), np.array(linear["jacobian"], dtype=np.float64)
    _, _, layout = first_order._layout(parent.model, coordinates)
    require(first_order._digest(body) == metadata["linearization_sha256"]
            and first_order._digest(layout) == metadata["coordinate_sha256"]
            and layout == metadata["coordinate_layout"]
            and metadata["parent_state_sha256"] == parent.model_state_sha256
            and first_order._array_digest(x.numpy()) == metadata["input_sha256"]
            and first_order._array_digest(margin.numpy()) == metadata["initial_margin_sha256"]
            and first_order._array_digest(base) == metadata["base_output_sha256"]
            and first_order._array_digest(jacobian) == metadata["jacobian_sha256"]
            and base.shape == (2,) and jacobian.shape == (2, 6)
            and bool(np.isfinite(base).all() and np.isfinite(jacobian).all()),
            "retained matrix, fixture, coordinates or metadata identity differs")
    base.setflags(write=False)
    jacobian.setflags(write=False)
    surrogate = first_order.Linearization(coordinates, base, jacobian, metadata)
    targets = base + np.asarray(OBJECTIVE["target_offset"], dtype=np.float64)
    result["counts"]["quadratic_solves"] += 1
    step = first_order.solve_gauss_newton(surrogate, targets, ridge=OBJECTIVE["ridge"],
                                         observation_weights=OBJECTIVE["observation_weights"])
    require(step["shared_coordinate_count"] == 6 and step["observation_count"] == 2
            and 0 <= step["data_rank"] <= 2 and step["data_nullity"] >= 4
            and step["data_full_column_rank"] is False and step["ridge_is_data_identification"] is False,
            "ridge uniqueness must not be represented as weight identification")
    proposal = {"schema": "hepta.smallhcsn.nonsmooth-surrogate-proposal.v1",
                "protocol_sha256": args.protocol_sha256, "original_failed_result_sha256": FAILED_RESULT_SHA256,
                "original_smooth_status": "FAILED", "classical_jacobian_admitted": False,
                "verified_semismooth_method": False,
                "surrogate": "retained model-declared midpoint primitive-VJP matrix",
                "objective": OBJECTIVE, "targets": targets.tolist(), "algebraic_step": step}
    proposal_pin = profile_io.write_new(output / "SURROGATE_STEP.json", profile_io.canonical(proposal) + b"\n", MAX_JSON)
    result["surrogate_proposal"] = proposal_pin
    result["retained_linearization_sha256"] = metadata["linearization_sha256"]
    delta = np.asarray(step["delta"], dtype=np.float64)
    phi0 = float(step["objective_at_zero"])
    predicted_reduction = phi0 - float(step["regularized_objective"])
    tau0 = GATE["absolute_floor"] + GATE["relative_floor"] * abs(phi0)
    step_norm = float(np.linalg.norm(delta))
    gate = {"Phi0": phi0, "pred": predicted_reduction, "step_norm": step_norm,
            "pre_forward_floor": tau0, "Phi_trial": None, "ared": None, "ratio": None, "tau": None}
    candidate, construction, prediction = None, None, None
    decision, reason = "REJECTED", "insufficient_predicted_reduction"
    if step_norm > OBJECTIVE["max_step_norm"]:
        reason = "prespecified_radius_exceeded_no_clipping"
    elif predicted_reduction > tau0:
        candidate, construction = first_order.apply_coordinate_step(parent.model, coordinates, delta,
            expected_parent_state_sha256=parent.model_state_sha256,
            expected_coordinate_sha256=metadata["coordinate_sha256"],
            learning_receipt_sha256=proposal_pin["sha256"],
            state_fingerprint=small_hcsn_profile.tensor_state_sha256,
            max_step_norm=OBJECTIVE["max_step_norm"])
        if not construction["changed"]:
            reason = "no_representable_parameter_change"
        else:
            result["parent_restored"] = False
            prediction = restored_forward(parent, candidate, construction["candidate_state_sha256"], x, margin,
                                          result, small_hcsn_profile.tensor_state_sha256)
            error = prediction - targets
            data_objective = float(0.5 * (error @ error))
            penalty = float(0.5 * OBJECTIVE["ridge"] * (delta @ delta))
            phi_trial = data_objective + penalty
            actual_reduction = phi0 - phi_trial
            tau = GATE["absolute_floor"] + GATE["relative_floor"] * max(abs(phi0), abs(phi_trial))
            ratio = actual_reduction / predicted_reduction
            require(all(math.isfinite(value) for value in (phi_trial, actual_reduction, tau, ratio)),
                    "nonfinite actual objective or reduction")
            gate.update({"data_objective": data_objective, "ridge_penalty": penalty,
                         "Phi_trial": phi_trial, "ared": actual_reduction, "ratio": ratio, "tau": tau})
            accepted = predicted_reduction > tau and actual_reduction > tau and ratio >= GATE["minimum_ratio"]
            decision = "ACCEPTED" if accepted else "REJECTED"
            reason = "actual_reduction_gate_passed" if accepted else "actual_reduction_gate_failed_no_retry"
    parent.require_frozen()
    result.update({"decision": decision, "reason": reason, "gate": gate})
    evidence = {"schema": "hepta.smallhcsn.nonsmooth-single-trial-evidence.v1",
                "protocol_sha256": args.protocol_sha256, "status": "COMPLETED_SINGLE_TRIAL",
                "decision": decision, "reason": reason, "original_failed_result_sha256": FAILED_RESULT_SHA256,
                "original_smooth_status": "FAILED", "original_finite_difference_passed": False,
                "classical_jacobian_admitted": False, "verified_semismooth_method": False,
                "source_sha256": dict(protocol["source_sha256"]), "runtime": dict(RUNTIME),
                "parent": dict(old_parent), "retained_linearization_sha256": metadata["linearization_sha256"],
                "surrogate_proposal": proposal_pin, "objective": OBJECTIVE, "gate_rule": GATE, "gate": gate,
                "base_output": base.tolist(), "trial_output": None if prediction is None else prediction.tolist(),
                "coordinate_edit_construction": construction, "counts": dict(result["counts"]),
                "parent_restored": result["parent_restored"],
                "parent_state_after_sha256": result["parent_state_after_sha256"],
                "accumulated_gradients_unchanged": result["accumulated_gradients_unchanged"],
                "diagnostics_restored": result["diagnostics_restored"],
                "eligible_for_research_export": decision == "ACCEPTED",
                "natural_task_benefit_claim": False, "production_adoption": False}
    evidence_pin = profile_io.write_new(output / "TRIAL_EVIDENCE.json", profile_io.canonical(evidence) + b"\n", MAX_JSON)
    result["trial_evidence"] = evidence_pin
    if decision == "ACCEPTED":
        edit = {**construction, "schema": "hepta.smallhcsn.accepted-nonsmooth-edit.v1",
                "trial_evidence": evidence_pin, "original_failed_result_sha256": FAILED_RESULT_SHA256,
                "original_smooth_status": "FAILED", "classical_jacobian_admitted": False,
                "actual_nonlinear_improvement_measured": True, "actual_reduction": gate["ared"],
                "natural_task_benefit_claim": False, "production_adoption": False}
        edit_pin = profile_io.write_new(output / "EDIT_RECEIPT.json", profile_io.canonical(edit) + b"\n", MAX_JSON)
        result["edit_receipt"] = edit_pin
        result["candidate_export"] = small_hcsn_profile.export_candidate(parent, candidate, edit_pin["sha256"],
            output / "accepted_candidate.pt", coordinates=COORDINATES)
        result["counts"]["candidate_exports"] = 1
        result["candidate_exported"] = True
    parent.require_frozen()
    result["status"] = "COMPLETED_SINGLE_TRIAL"


def limit_expired(signum, _frame):
    raise TimeoutError("registered trial time budget expired: signal " + str(signum))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "protocol-sha256", "parent-profile", "profile-module-dir",
                 "sensitivity-module-dir", "sensitivity-result", "materials", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    protocol = parse(read_pinned(args.protocol, args.protocol_sha256))
    require(protocol["schema"] == "hepta.smallhcsn.nonsmooth-single-trial.v1"
            and protocol["ready_for_execution"] is True
            and protocol["failed_sensitivity_result_sha256"] == FAILED_RESULT_SHA256
            and protocol["parent_checkpoint_sha256"] == PARENT_SHA256
            and protocol["coordinates"] == COORDINATES and protocol["objective"] == OBJECTIVE
            and protocol["actual_reduction_gate"] == GATE and protocol["budget"] == BUDGET,
            "registered one-trial protocol differs; no revised target, tolerance, coordinate or budget")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    signal.signal(signal.SIGALRM, limit_expired)
    signal.signal(signal.SIGXCPU, limit_expired)
    signal.alarm(120)
    resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
    result = {"schema": "hepta.smallhcsn.nonsmooth-single-trial-result.v1",
              "protocol_sha256": args.protocol_sha256, "status": "FAILED", "decision": "REJECTED",
              "reason": "scope_not_completed", "original_failed_result_sha256": FAILED_RESULT_SHA256,
              "original_smooth_status": "FAILED", "classical_jacobian_admitted": False,
              "verified_semismooth_method": False, "candidate_exported": False, "candidate_adopted": False,
              "historical_matrix_rerun": False, "original_failure_modified": False,
              "old_training_or_test_data_read": False, "test_retuning": False,
              "second_order_autograd": False, "natural_task_benefit_claim": False,
              "counts": {"quadratic_solves": 0, "physical_forward_calls": 0, "scalar_output_vjp_calls": 0,
                         "new_linearizations": 0, "finite_difference_calls": 0, "backtracking_steps": 0,
                         "retries": 0, "training_loop_updates": 0, "candidate_exports": 0}}
    try:
        execute(args, protocol, output, result)
    except Exception as error:
        result["error"] = repr(error)
        result["traceback"] = traceback.format_exc()
    finally:
        signal.alarm(0)
        result["wall_s"] = time.perf_counter() - started
        result["cpu_s"] = time.process_time() - cpu
        raw = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
        with (output / "RESULT.json").open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"status": result["status"], "decision": result["decision"],
                      "candidate_exported": result["candidate_exported"],
                      "result_sha256": hashlib.sha256(raw).hexdigest()}))
    # A completed rejection is a valid negative engineering observation.
    # Consumers must separately require decision=ACCEPTED and an export pin.
    return 0 if result["status"] == "COMPLETED_SINGLE_TRIAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
