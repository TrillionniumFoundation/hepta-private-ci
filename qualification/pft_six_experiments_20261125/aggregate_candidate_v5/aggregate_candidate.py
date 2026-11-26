"""Independently materialize, evaluate, export and cold-check an actual peer step.

Both modes require separately admitted protocols. No central candidate gate is
inherited, no equation is solved again, and the original smooth failure stays.
"""
import argparse
import copy
from dataclasses import asdict
from fractions import Fraction
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
ENTRY = "aggregate_candidate_v5/aggregate_candidate.py"
FAILED = "15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105"
PROFILE = "4a8feafa490224f0ad14d318835f51d1147b8b6b93c7a56e9f9eb3ddc3d43d77"
PARENT = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
ROSTER = ["ai395", "pocket4"]
ROWS = {"ai395": "7e0946d79ae2069178cdea466b6ec12b90ba27afbaf651ace5921794883af8be",
        "pocket4": "cad4b3c7f03dc3d2154fe93ff81611b4b4d98250c0c8764efbde021ffeef9972"}
SOURCES = {
    "native_profile_v4/profile_io.py": "3c6d4d0d6ad478460e3b422bfb22220406080c48a5ef1d33e2cb3479e43e738f",
    "native_profile_v4/source_binding.py": "72f29914e87a5c35d1e33c41267da7057a739a077047513b11d8dcf48c2a42a3",
    "native_profile_v4/small_hcsn_profile.py": "a1c28b0a8a05d52d6394dde21381fb791bdcff8f10909947f50afc84d13cfd5a",
    "native_profile_v4/bounded_process.py": "776e37c8ac04f9a5e2eda773b071521dfb689567e3abe4f9550124d399728805",
    "native_profile_v4/numeric_runner.py": "0d3fbb8c849f442d254f83a12a5ad433f2c678cb6723bcb04018c4b05a97d472",
    "native_profile_v4/verify_nonsmooth_cold.py": "93e278863a7e73cde336e540a1fa707478693a4027d69115533b8058a58d40e7",
    "sensitivity_v4/first_order.py": "eecdf0a2f6aabbdbc65b79ed44c96b5badbd406c51252d89643260a923b5a55f",
    "sensitivity_v4/verify_first_order.py": "8506d27e0a5740901e0bdb40da17478de009d41629125d0888ba81ece01c374d",
    "nonsmooth_trial_v4/nonsmooth_trial.py": "8e3de69622c23f36660f49bb0f66a232aa113a97b858cfe1c24c41a02defee95",
}
RUNTIME = {"python": "3.14.4", "numpy": "2.5.5", "torch": "2.15.0+cpu",
           "device": "cpu", "threads": 1, "interop_threads": 1}
BUDGETS = {
    "trial": {"model_loads": 1, "physical_forward_calls": 1, "quadratic_solves": 0,
              "vjp_calls": 0, "training_updates": 0, "candidate_exports": 1,
              "historical_matrix_runs": 0, "retries": 0, "wall_seconds": 120, "cpu_seconds": 120},
    "cold": {"child_invocations": 1, "model_loads": 1, "physical_forward_calls": 1,
             "quadratic_solves": 0, "vjp_calls": 0, "training_updates": 0,
             "candidate_exports": 0, "retries": 0, "child_wall_seconds": 55, "outer_wall_seconds": 90},
}
CAP = 1024 * 1024
SOLVER = "two-host exact Fraction ridge solve; componentwise nearest binary64; no new solve here"


def require(value, message):
    if not value:
        raise ValueError(message)


def bootstrap(args):
    for name, expected in SOURCES.items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, "changed dependency: " + name)
    require(not any(name in sys.modules for name in ("torch", "numpy", "profile_io", "first_order")), "fresh process required")
    sys.path[:0] = [str(ROOT / folder) for folder in ("native_profile_v4", "nonsmooth_trial_v4", "sensitivity_v4")]
    io, old, cold = (importlib.import_module(name) for name in ("profile_io", "nonsmooth_trial", "verify_nonsmooth_cold"))
    for module, path in ((io, "native_profile_v4/profile_io.py"), (old, "nonsmooth_trial_v4/nonsmooth_trial.py"),
                         (cold, "native_profile_v4/verify_nonsmooth_cold.py")):
        require(Path(module.__file__).resolve() == (ROOT/path).resolve(), "wrong helper import location")
    protocol = io.parse(io.read_named(args.protocol, args.protocol_sha256, CAP))
    require(protocol["schema"] == "hepta.smallhcsn.aggregate-candidate-protocol.v1"
            and protocol["ready_for_execution"] is True and protocol["mode"] == args.mode,
            "inactive or wrong aggregate scope")
    require(protocol["original_failed_result_sha256"] == FAILED and protocol["parent_profile_sha256"] == PROFILE
            and protocol["parent_checkpoint_sha256"] == PARENT and protocol["objective"] == old.OBJECTIVE
            and protocol["actual_reduction_gate"] == old.GATE and protocol["runtime"] == RUNTIME
            and protocol["budget"] == BUDGETS[args.mode]
            and protocol["cold_comparison"] == {"atol": 1e-12, "rtol": 1e-11}, "fixed numerical contract differs")
    require(set(protocol["source_sha256"]) == set(SOURCES) | {ENTRY}, "complete source pins required")
    for name, expected in protocol["source_sha256"].items():
        io.read_named(ROOT / name, expected, CAP)
    require({k: protocol["source_sha256"][k] for k in SOURCES} == SOURCES, "V4 numerical sources differ")
    require(set(protocol["peer_input_sha256"]) == {"common", *ROSTER}, "two complete peer outputs required")
    for value in protocol["peer_input_sha256"].values():
        io.digest(value)
    if args.mode == "cold":
        io.digest(protocol["trial_result_sha256"])
        require(args.trial_output is not None, "cold scope requires its own trial output")
    return io, old, cold, protocol


def rational(value):
    require(type(value) is list and len(value) == 2
            and all(type(x) is str and 0 < len(x) <= 618 and x.lstrip("-").isdigit()
                    and str(int(x)) == x for x in value), "bounded canonical rational pair")
    numerator, denominator = map(int, value)
    require(denominator > 0, "positive denominator")
    number = Fraction(numerator, denominator)
    require(max(number.numerator.bit_length(), number.denominator.bit_length()) <= 2048
            and [str(number.numerator), str(number.denominator)] == value, "reduced bounded rational")
    return number


def pack(value):
    return [str(value.numerator), str(value.denominator)]


def guarded_forward(old, parent, candidate, candidate_sha, x, margin, report, fingerprint):
    model, torch = parent.model, parent.torch
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    parameters = dict(model.named_parameters())
    flags = {k: p.requires_grad for k, p in parameters.items()}
    gradients = {k: (p.grad, None if p.grad is None else p.grad.detach().clone()) for k, p in parameters.items()}
    modes = [(m, m.training) for m in model.modules()]
    config, diagnostics = copy.deepcopy(model.config), copy.deepcopy(model.last_diagnostics)
    report["parent_trainability"] = flags
    def same_grad(parameter, saved):
        return parameter.grad is None if saved is None else parameter.grad is not None and torch.equal(parameter.grad, saved)
    try:
        return old.restored_forward(parent, candidate, candidate_sha, x, margin, report, fingerprint)
    finally:
        checks = {"state_unchanged_before_outer_cleanup": fingerprint(model.state_dict()) == parent.model_state_sha256,
                  "trainability_unchanged_before_outer_cleanup": flags == {k: p.requires_grad for k, p in parameters.items()},
                  "gradients_unchanged_before_outer_cleanup": all(same_grad(p, gradients[k][1]) for k, p in parameters.items()),
                  "config_unchanged_before_outer_cleanup": asdict(model.config) == asdict(config),
                  "modes_unchanged_before_outer_cleanup": all(m.training == mode for m, mode in modes)}
        with torch.no_grad():
            model.load_state_dict(state, strict=True)
            for name, parameter in parameters.items():
                parameter.requires_grad_(flags[name])
                original, value = gradients[name]
                if original is not None:
                    original.copy_(value)
                parameter.grad = original
        model.config, model.last_diagnostics = config, diagnostics
        for module, mode in modes:
            module.training = mode
        parent.require_frozen()
        checks.update(state_restored=parent.current_state_sha256() == parent.model_state_sha256,
                      trainability_restored=flags == {k: p.requires_grad for k, p in parameters.items()},
                      gradients_restored=all(same_grad(p, gradients[k][1]) for k, p in parameters.items()), diagnostics_restored=True)
        report["restoration"] = checks
        require(all(checks.values()), "unexpected parent mutation or failed restoration; stop")


def peer_inputs(args, protocol, io, old, cold):
    failed = old.require_original_failure(io.parse(io.read_named(args.failed_result, FAILED, CAP)))
    paths = {"common": args.peer_common, "ai395": args.ai395_result, "pocket4": args.pocket4_result}
    records = {}
    for name, path in paths.items():
        raw = io.read_named(path, protocol["peer_input_sha256"][name], CAP)
        records[name] = io.parse(raw)
        require(raw == io.canonical(records[name]), "peer evidence must remain canonical")
    common, a, b = (records[name] for name in ("common", *ROSTER))
    lin, parent = failed["linearization"], failed["parent"]
    require(common["schema"] == "hepta.fixed-peer-common.v1" and common["active"] is True
            and common["roster"] == ROSTER and common["row_sha256"] == ROWS
            and common["original_failed_result_sha256"] == FAILED
            and common["source_linearization_sha256"] == lin["linearization_sha256"]
            and common["candidate_sha256"] == parent["checkpoint_sha256"] == PARENT
            and common["profile_sha256"] == parent["profile_sha256"] == PROFILE
            and common["source_binding_sha256"] == parent["source_binding_sha256"]
            and common["ridge_binary64"] == 0.001, "peer lineage differs from original frozen parent")
    require(common["source_sha256"] == protocol["peer_source_sha256"]
            and set(common["source_sha256"]) == {"profile_io.py", "peer.py", "exact_equations.py"}
            and common["source_sha256"]["profile_io.py"] == SOURCES["native_profile_v4/profile_io.py"], "peer source pins differ")
    for name in ("peer.py", "exact_equations.py"):
        io.read_named(Path(args.peer_code) / name, common["source_sha256"][name], CAP)
    require(all(value == lin[key] for key, value in common["linearization"].items() if key != "derivative")
            and common["linearization"]["coordinate_layout"] == lin["coordinate_layout"], "retained coordinate metadata differs")
    for node, result, other in (("ai395", a, b), ("pocket4", b, a)):
        require(result["schema"] == "hepta.fixed-peer-run.v1" and result["status"] == "PEER_STEP_AGREED"
                and result["common_sha256"] == protocol["peer_input_sha256"]["common"]
                and result["peer_confirmed_same_step"] is True
                and result["node_identity"]["node"] == node
                and result["node_identity"]["hostname"] == common["hostnames"][node]
                and result["node_identity"]["source_sha256"] == common["source_sha256"]
                and result["peer_identity"] == other["node_identity"], "independent peer identity or agreement differs")
        require(result["frames_sent"] == other["frames_received"]
                and [frame["kind"] for frame in result["frames_sent"]] == ["hello", "contribution", "step"],
                "bidirectional actual frame receipts differ")
        for frame in result["frames_sent"]:
            io.digest(frame["sha256"])
            require(type(frame["bytes"]) is int and 4 < frame["bytes"] <= 65540, "frame byte bound")
    require(a["step"] == b["step"] and a["step_sha256"] == b["step_sha256"] == io.sha(io.canonical(a["step"]))
            and a["contributions"] == b["contributions"], "exact step and contribution identities required; no approximate substitution")
    transport, route = a["transport"], common["transport"]
    selected = transport["selection"]["selected"]
    require(transport["strict_host_key_checking"] is True and transport["controller_relays_contributions"] is False
            and selected["interface_bound"] is True and selected["interface"] == "br-usb4"
            and selected["local_address"][0] == route["local_source"] == "10.77.0.2"
            and selected["remote_address"][0] == route["peer_address"] == "10.77.0.4"
            and selected["transport"] == route["required_transport"] and selected["port"] == 22,
            "actual direct two-host transport receipt required")
    # Recompute statistics and verify the received solution, without elimination or any solve.
    source = [[Fraction.from_float(v) for v in row] for row in lin["jacobian"]]
    residual = [Fraction.from_float(v + d) - Fraction.from_float(v)
                for v, d in zip(lin["base_output"], old.OBJECTIVE["target_offset"])]
    expected = {}
    for index, node in enumerate(ROSTER):
        row, r = source[index], residual[index]
        expected[node] = {"schema": "hepta.fixed-peer-rational-contribution.v1", "node": node,
            "common_sha256": io.sha(io.canonical(common)), "row_sha256": ROWS[node], "observation_count": 1,
            "local_ridge_applied": False, "gram": [[pack(x*y) for y in row] for x in row],
            "moment": [pack(x*r) for x in row], "residual_square": pack(r*r)}
    require(a["contributions"] == expected, "actual peer statistics differ from the fixed retained rows")
    step = a["step"]
    require(step["schema"] == "hepta.fixed-peer-rational-step.v1"
            and step["common_sha256"] == io.sha(io.canonical(common)) and step["round"] == common["round"]
            and step["parent_state_sha256"] == parent["state_sha256"]
            and step["coordinate_sha256"] == lin["coordinate_sha256"]
            and step["contribution_sha256"] == {n: io.sha(io.canonical(v)) for n, v in expected.items()}, "aggregate step lineage differs")
    delta = step["delta"]
    require(len(delta) == len(step["delta_rational"]) == 6
            and all(type(v) is float and math.isfinite(v) for v in delta), "bounded binary64 step")
    exact, rounded = list(map(rational, step["delta_rational"])), list(map(Fraction.from_float, delta))
    ridge = Fraction.from_float(0.001)
    gram = [[sum(row[i]*row[j] for row in source) for j in range(6)] for i in range(6)]
    moment = [sum(row[i]*r for row, r in zip(source, residual)) for i in range(6)]
    require(all(sum(gram[i][j]*exact[j] for j in range(6)) + ridge*exact[i] == moment[i] for i in range(6))
            and delta == list(map(float, exact)) and step["delta_hex"] == [v.hex() for v in delta]
            and step["delta_sha256"] == cold.array_sha(delta, (6,)), "received exact solution or binary64 conversion differs")
    quantization = [abs(x-y) for x, y in zip(exact, rounded)]
    stationarity = [sum(gram[i][j]*rounded[j] for j in range(6)) + ridge*rounded[i]-moment[i] for i in range(6)]
    require(step["quantization_absolute_error"] == list(map(pack, quantization))
            and all(error <= Fraction.from_float(math.ulp(value))/2 for error, value in zip(quantization, delta))
            and step["rounded_stationarity"] == list(map(pack, stationarity))
            and max(map(abs, stationarity)) <= Fraction.from_float(1e-12), "binary64 quantization or stationarity differs")
    norm2 = sum(v*v for v in rounded)
    phi0 = sum(v*v for v in residual) / 2
    linear = sum((sum(x*d for x, d in zip(row, rounded))-r)**2 for row, r in zip(source, residual)) / 2
    predicted = phi0 - linear - ridge*norm2/2
    aggregate = {"gram": [[pack(v) for v in row] for row in gram], "moment": list(map(pack, moment)),
                 "residual_square": pack(phi0*2)}
    require(step["aggregate_sha256"] == io.sha(io.canonical(aggregate))
            and rational(step["objective_at_zero_rational"]) == phi0
            and rational(step["predicted_reduction_at_rounded_step_rational"]) == predicted
            and step["objective_at_zero"] == float(phi0) and step["predicted_reduction"] == float(predicted)
            and rational(step["ridge_rational"]) == ridge and norm2 <= 1
            and step["global_ridge_applications"] == 1 and step["ridge_is_data_identification"] is False,
            "fixed aggregate objective, single ridge or norm differs")
    require(any(source[0][i]*source[1][j] != source[0][j]*source[1][i] for i in range(6) for j in range(6))
            and (step["data_rank"], step["data_nullity"], step["solver_rank"], step["observation_count"]) == (2, 4, 6, 2),
            "data rank versus regularized solve semantics differ")
    return failed, common, a, b


def trial(args, protocol, io, old, cold, evidence, out, report):
    failed, common, a, _ = evidence
    import first_order as first
    import verify_first_order as fixture
    import small_hcsn_profile as native
    from source_binding import RUNTIME as actual_runtime
    for module, path in ((first, "sensitivity_v4/first_order.py"), (fixture, "sensitivity_v4/verify_first_order.py"),
                         (native, "native_profile_v4/small_hcsn_profile.py")):
        require(Path(module.__file__).resolve() == (ROOT/path).resolve(), "wrong numerical import location")
    require(actual_runtime == RUNTIME and [c.record() for c in fixture.COORDINATES] == old.COORDINATES, "original runtime or coordinates differ")
    report["counts"]["model_loads"] = 1
    parent = native.load_profile(args.parent_profile, PROFILE, args.materials)
    require(parent.candidate_sha256 == PARENT and parent.config == failed["parent"]["config"]
            and parent.model_state_sha256 == failed["parent"]["state_sha256"]
            and parent.source_binding_sha256 == failed["parent"]["source_binding_sha256"], "loaded frozen parent differs")
    report["parent"] = failed["parent"]
    np, step, lin = first.np, a["step"], failed["linearization"]
    base, jacobian, delta = (np.asarray(value, dtype=np.float64) for value in (lin["base_output"], lin["jacobian"], step["delta"]))
    target = base + np.asarray(old.OBJECTIVE["target_offset"])
    residual, penalty = base-target, float(0.5*old.OBJECTIVE["ridge"]*(delta@delta))
    linear_residual = jacobian@delta + residual
    phi0 = float(0.5*(residual@residual))
    pred = phi0 - float(0.5*(linear_residual@linear_residual) + penalty)
    require(cold.close(phi0, step["objective_at_zero"]) and cold.close(pred, step["predicted_reduction"]), "received predicted reduction differs")
    gate = {"Phi0": phi0, "pred": pred, "step_norm": float(np.linalg.norm(delta)),
            "pre_forward_floor": 1e-12 + 1e-6*abs(phi0), "Phi_trial": None, "ared": None, "ratio": None, "tau": None}
    report.update(decision="REJECTED", reason="insufficient_predicted_reduction", gate=gate,
                  parent_restored=True, parent_state_after_sha256=parent.current_state_sha256())
    candidate = construction = prediction = None
    if gate["step_norm"] > 1.0:
        report["reason"] = "prespecified_radius_exceeded_no_clipping"
    elif pred > gate["pre_forward_floor"]:
        candidate, construction = first.apply_coordinate_step(parent.model, fixture.COORDINATES, delta,
            expected_parent_state_sha256=parent.model_state_sha256, expected_coordinate_sha256=lin["coordinate_sha256"],
            learning_receipt_sha256=protocol["peer_input_sha256"]["ai395"], state_fingerprint=native.tensor_state_sha256, max_step_norm=1.0)
        require(construction["changed"], "no representable parameter change; stop")
        x, margin = fixture.fixture()
        x, margin = first._inputs(parent.model, x, margin)
        require(first._array_digest(x.numpy()) == lin["input_sha256"]
                and first._array_digest(margin.numpy()) == lin["initial_margin_sha256"], "original fresh fixture differs")
        report["parent_restored"] = False
        prediction = guarded_forward(old, parent, candidate, construction["candidate_state_sha256"], x, margin, report, native.tensor_state_sha256)
        error = prediction-target
        data = float(0.5*(error@error))
        phit = data + penalty
        ared, tau = phi0-phit, 1e-12 + 1e-6*max(abs(phi0), abs(phit))
        ratio = ared/pred
        require(all(math.isfinite(v) for v in (data, phit, ared, tau, ratio)), "nonfinite nonlinear gate")
        gate.update(Phi_trial=phit, ared=ared, tau=tau, ratio=ratio, data_objective=data, ridge_penalty=penalty)
        accepted = pred > tau and ared > tau and ratio >= 0.1
        report.update(decision="ACCEPTED" if accepted else "REJECTED",
                      reason="actual_peer_step_reduction_passed" if accepted else "actual_peer_step_reduction_failed_no_retry")
    parent.require_frozen()
    report["parent_trainability"] = {name: p.requires_grad for name, p in parent.model.named_parameters()}
    record = {**report, "schema": "hepta.smallhcsn.aggregate-trial-evidence.v1", "status": "COMPLETED_SINGLE_PEER_TRIAL",
              "objective": old.OBJECTIVE, "gate_rule": old.GATE, "base_output": base.tolist(), "targets": target.tolist(),
              "trial_output": None if prediction is None else prediction.tolist(), "delta": step["delta"],
              "coordinate_edit_construction": construction, "eligible_for_research_export": report["decision"] == "ACCEPTED"}
    record_pin = io.write_new(out / "TRIAL_EVIDENCE.json", io.canonical(record)+b"\n", CAP)
    report["trial_evidence"] = record_pin
    if report["decision"] == "ACCEPTED":
        edit = {**construction, "schema": "hepta.smallhcsn.accepted-peer-aggregate-edit.v1", "trial_evidence": record_pin,
                "peer_input_sha256": protocol["peer_input_sha256"], "peer_step_sha256": a["step_sha256"], "solver": SOLVER,
                "original_failed_result_sha256": FAILED, "original_smooth_status": "FAILED", "classical_jacobian_admitted": False,
                "actual_nonlinear_improvement_measured": True, "actual_reduction": gate["ared"], "production_adoption": False}
        edit_pin = io.write_new(out / "EDIT_RECEIPT.json", io.canonical(edit)+b"\n", CAP)
        report["edit_receipt"] = edit_pin
        report["candidate_export"] = native.export_candidate(parent, candidate, edit_pin["sha256"], out / "aggregate_candidate.pt", coordinates=old.COORDINATES)
        report["candidate_exported"], report["counts"]["candidate_exports"] = True, 1
    parent.require_frozen()
    io.read_pin(args.materials, parent.manifest["checkpoint"], 32*CAP)
    report.update(status="COMPLETED_SINGLE_PEER_TRIAL", original_parent_checkpoint_unchanged=True)


def cold_check(args, protocol, io, old, cold, evidence, out, report):
    failed, _, a, _ = evidence
    receipts = Path(args.trial_output)
    result = io.parse(io.read_named(receipts / "RESULT.json", protocol["trial_result_sha256"], CAP))
    trial_record = io.parse(io.read_pin(receipts, result["trial_evidence"], CAP))
    edit = io.parse(io.read_pin(receipts, result["edit_receipt"], CAP))
    require(result["schema"] == "hepta.smallhcsn.aggregate-candidate-result.v1" and result["mode"] == "trial"
            and trial_record["schema"] == "hepta.smallhcsn.aggregate-trial-evidence.v1"
            and edit["schema"] == "hepta.smallhcsn.accepted-peer-aggregate-edit.v1", "own aggregate receipt schemas required")
    for item in (result, trial_record):
        require(item["status"] == "COMPLETED_SINGLE_PEER_TRIAL" and item["decision"] == "ACCEPTED"
                and item["original_failed_result_sha256"] == FAILED and item["original_smooth_status"] == "FAILED"
                and item["classical_jacobian_admitted"] is False and item["parent"] == failed["parent"]
                and item["peer_input_sha256"] == protocol["peer_input_sha256"] and item["peer_step_sha256"] == a["step_sha256"]
                and item["parent_restored"] is True and item["accumulated_gradients_unchanged"] is True
                and item["diagnostics_restored"] is True and all(item["restoration"].values())
                and item["parent_state_after_sha256"] == failed["parent"]["state_sha256"]
                and item["source_sha256"] == protocol["source_sha256"] and item["runtime"] == RUNTIME
                and item["protocol_sha256"] == result["protocol_sha256"],
                "this aggregate requires its own accepted, restored physical trial")
    require(result["candidate_exported"] is True and result["candidate_adopted"] is False
            and result["gate"] == trial_record["gate"] and result["counts"]["physical_forward_calls"] == 1
            and result["counts"]["candidate_exports"] == 1 and trial_record["delta"] == a["step"]["delta"]
            and trial_record["objective"] == old.OBJECTIVE and trial_record["gate_rule"] == old.GATE, "aggregate trial gate/export binding differs")
    exported = result["candidate_export"]
    require(edit["trial_evidence"] == result["trial_evidence"]
            and edit["learning_receipt_sha256"] == protocol["peer_input_sha256"]["ai395"]
            and edit["peer_input_sha256"] == protocol["peer_input_sha256"] and edit["peer_step_sha256"] == a["step_sha256"]
            and edit["candidate_state_sha256"] == exported["model_state_sha256"]
            and edit["parent_state_sha256"] == failed["parent"]["state_sha256"]
            and exported["parent_candidate_sha256"] == PARENT and exported["artifact"]["path"] == "aggregate_candidate.pt",
            "new full candidate receipt chain differs")
    targets = [v+d for v, d in zip(failed["linearization"]["base_output"], (1e-4, -1e-4))]
    require(trial_record["targets"] == targets and trial_record["base_output"] == failed["linearization"]["base_output"], "fixed targets differ")
    phi0 = 0.5*sum((v-t)**2 for v, t in zip(trial_record["base_output"], targets))
    penalty = 0.0005*sum(d*d for d in a["step"]["delta"])
    data = 0.5*sum((v-t)**2 for v, t in zip(trial_record["trial_output"], targets))
    phit, pred = data+penalty, a["step"]["predicted_reduction"]
    ared, tau = phi0-phit, 1e-12 + 1e-6*max(abs(phi0), abs(phit))
    require(pred > tau and ared > tau and ared/pred >= 0.1, "own actual nonlinear reduction did not pass")
    values = dict(Phi0=phi0, Phi_trial=phit, pred=pred, ared=ared, tau=tau, ratio=ared/pred, ridge_penalty=penalty, data_objective=data)
    require(all(cold.close(trial_record["gate"][key], value) for key, value in values.items()), "aggregate gate arithmetic differs")
    manifest = io.parse(io.read_named(args.parent_profile, PROFILE, CAP))
    require(manifest["checkpoint"]["sha256"] == PARENT and manifest["runtime"] == RUNTIME, "original profile differs")
    io.read_pin(args.materials, manifest["checkpoint"], 32*CAP)
    io.read_pin(receipts, exported["artifact"], 32*CAP)
    original_checkpoint = manifest["checkpoint"]
    manifest.update(format="research_candidate_v1", origin={"protocol_sha256": None, "coordinate_candidate_sha256": None})
    manifest["checkpoint"] = {**exported["artifact"], "path": (receipts.resolve()/"aggregate_candidate.pt").relative_to(Path(args.materials).resolve()).as_posix()}
    profile_pin = io.write_new(out / "CANDIDATE_PROFILE.json", io.canonical(manifest)+b"\n", CAP)
    x, margin = cold.fixture()
    task = {"schema": "hepta.smallhcsn.numeric-task.v1", "task_id": "actual-peer-aggregate-cold-only",
            "profile_sha256": profile_pin["sha256"], "candidate_sha256": exported["artifact"]["sha256"],
            "x": x, "initial": {"kind": "margin", "margin": margin}}
    task_pin = io.write_new(out / "NUMERIC_TASK.json", io.canonical(task)+b"\n", CAP)
    require(all(os.environ.get(k) == "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")), "fixed child thread environment required")
    report["counts"]["child_invocations"] = 1
    report["counts"].update(model_loads=None, physical_forward_calls=None)  # Child failure can interrupt either operation.
    from bounded_process import run_child
    pin = io.parse(run_child([sys.executable, "-B", str(ROOT/"native_profile_v4/numeric_runner.py"),
        "--profile", str(out/"CANDIDATE_PROFILE.json"), "--profile-sha256", profile_pin["sha256"],
        "--material-root", args.materials, "--task", str(out/"NUMERIC_TASK.json"), "--task-sha256", task_pin["sha256"],
        "--state-root", str(out), "--output", str(out/"cold")]))
    numeric = io.parse(io.read_pin(out/"cold", pin, 16*CAP), 16*CAP)
    require(numeric["profile_sha256"] == profile_pin["sha256"] and numeric["candidate_sha256"] == exported["artifact"]["sha256"]
            and numeric["model_state_sha256"] == exported["model_state_sha256"]
            and numeric["source_binding_sha256"] == failed["parent"]["source_binding_sha256"]
            and numeric["task_sha256"] == task_pin["sha256"] and (numeric["start_step"], numeric["end_step"]) == (0, 4)
            and numeric["production_adoption"] is False and numeric["real_cross_user_acceptance"] is False, "independent cold candidate identity differs")
    observed = [row[1]-row[0] for row in numeric["logits"][-1]]
    require(len(observed) == 2 and all(cold.close(v, expected, 1e-12, 1e-11)
            for v, expected in zip(observed, trial_record["trial_output"])), "strict aggregate cold margins differ")
    io.read_pin(out/"cold", numeric["population"], 32*CAP)
    io.read_pin(args.materials, original_checkpoint, 32*CAP)
    io.read_pin(receipts, exported["artifact"], 32*CAP)
    report["counts"].update(model_loads=1, physical_forward_calls=1)
    report.update(status="PASSED_AGGREGATE_COLD", candidate_profile=profile_pin, task=task_pin,
        cold_result={"root": "cold", "artifact": pin}, population={"root": "cold", "artifact": numeric["population"]},
        candidate_export=exported, cold_margins=observed, trial_margins=trial_record["trial_output"],
        max_abs_margin_difference=max(abs(x-y) for x, y in zip(observed, trial_record["trial_output"])),
        original_parent_checkpoint_unchanged=True, trial_result_sha256=protocol["trial_result_sha256"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("trial", "cold"), required=True)
    for name in ("protocol", "protocol-sha256", "failed-result", "parent-profile", "peer-common",
                 "ai395-result", "pocket4-result", "peer-code", "materials", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--trial-output")
    args = parser.parse_args()
    io, old, cold, protocol = bootstrap(args)
    out = Path(args.output).resolve()
    require(out.is_relative_to(Path(args.materials).resolve()), "output must remain in material root")
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    report = {"schema": "hepta.smallhcsn.aggregate-candidate-result.v1", "mode": args.mode, "status": "FAILED",
        "protocol_sha256": args.protocol_sha256, "source_sha256": protocol["source_sha256"], "runtime": RUNTIME,
        "registered_budget": BUDGETS[args.mode],
        "peer_input_sha256": protocol["peer_input_sha256"], "solver": SOLVER, "central_svd_step_reused": False,
        "central_candidate_gate_inherited": False, "original_failed_result_sha256": FAILED, "original_smooth_status": "FAILED",
        "original_failure_modified": False, "classical_jacobian_admitted": False, "verified_semismooth_method": False,
        "candidate_exported": False, "candidate_adopted": False, "production_adoption": False,
        "genuine_independent_users": False, "natural_task_benefit_claim": False, "network_bytes_are_training_speedup": False,
        "counts": {"model_loads": 0, "physical_forward_calls": 0, "quadratic_solves": 0, "vjp_calls": 0,
                   "training_updates": 0, "candidate_exports": 0, "historical_matrix_runs": 0, "retries": 0, "child_invocations": 0}}
    started, cpu = time.monotonic(), time.process_time()
    def expired(_signal, _frame):
        raise TimeoutError("single aggregate scope budget expired; no retry")
    signal.signal(signal.SIGALRM, expired)
    signal.signal(signal.SIGXCPU, expired)
    signal.alarm(120 if args.mode == "trial" else 85)
    resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
    try:
        evidence = peer_inputs(args, protocol, io, old, cold)
        report["peer_step_sha256"] = evidence[2]["step_sha256"]
        (trial if args.mode == "trial" else cold_check)(args, protocol, io, old, cold, evidence, out, report)
    except Exception as error:
        report.update(status="FAILED", error=repr(error), traceback=traceback.format_exc(limit=12))
    finally:
        signal.alarm(0)
        try:
            for key, path in (("common", args.peer_common), ("ai395", args.ai395_result), ("pocket4", args.pocket4_result)):
                io.read_named(path, protocol["peer_input_sha256"][key], CAP)
            io.read_named(args.failed_result, FAILED, CAP)
            io.read_named(args.parent_profile, PROFILE, CAP)
            report["retained_inputs_unchanged"] = True
        except Exception as error:
            report.update(status="FAILED", integrity_error=repr(error))
        if args.mode == "cold":
            imports = [n for n in sys.modules if n.split(".")[0] in ("torch", "numpy", "small_hcsn_profile", "first_order", "qualification")]
            report["driver_model_or_framework_imports"] = imports
            if imports:
                report.update(status="FAILED", error="cold driver imported numerical/model code")
        report.update(wall_s=time.monotonic()-started, cpu_s=time.process_time()-cpu)
        pin = io.write_new(out/"RESULT.json", io.canonical(report)+b"\n", CAP)
    print(io.canonical({"status": report["status"], "result": pin}).decode())
    return 0 if report["status"] in ("COMPLETED_SINGLE_PEER_TRIAL", "PASSED_AGGREGATE_COLD") else 1


if __name__ == "__main__":
    raise SystemExit(main())
