"""Post-run, planning-only replay and forward-JVP audit of frozen common J32.

Uses the existing physical optimizer/head and qualified Adam derivative primitive,
but never calls the producer's reference, field, proposal or rollout builders.
The report's full/field backward construction is checked by forward propagation.
"""

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
import time

import numpy as np


PROTOCOL = "0c89285fe70713a959884248de24d7b45e2652901627aa59e844897b0304d0b9"
SOURCE = "0e761ba53d4921c1fd454636d4857ba0114e1e85fb23e773b761b7abefe7f545"
COMMIT = "6f1b57802b13866472a3f799343b705b4acddc55"
BRANCHES = ("zero32", "myopic_h1_zero_tail", "full32_one_action", "full32_eight_actions",
            "field32_eight_actions", "loss2_32_eight_actions")
WEIGHTS = np.r_[np.full(4, .25), np.full(4, .0625)]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "ordinary input file required")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    require(Path(path).stat().st_size <= 32 << 20, "bounded JSON required")
    return json.loads(Path(path).read_bytes())


def near(actual, expected, description, *, atol=1e-11, rtol=1e-10):
    a, b = np.asarray(actual), np.asarray(expected)
    require(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
            and np.allclose(a, b, atol=atol, rtol=rtol), description)
    return float(np.max(np.abs(a - b))) if a.size else 0.


def observed(head, prepared, names):
    rows = [head.loss_gradients(x, y, 0.) for x, y in prepared]
    return (np.asarray([row[0] for row in rows]),
            np.asarray([np.concatenate([row[1][name].ravel() for name in names]) for row in rows]))


def forward_coefficients(gradients, transitions, dt=.02):
    """Independent full-state and two-state forward recurrences, all32 inputs."""
    h, q, p = len(transitions), *gradients.shape[1:]
    sensitivity, propagation = np.zeros((3*p, h*p)), np.eye(3*p)
    retained = np.zeros((2, h*p))
    observation_zero = np.hstack((gradients[0], np.zeros((q, 2*p))))
    field_initial = [observation_zero]
    field_inputs = [[] for _ in range(h)]
    for k, a in enumerate(transitions):
        sensitivity = a @ sensitivity
        sensitivity[:p, k*p:(k+1)*p] += dt*np.eye(p)
        full_output = gradients[k+1] @ sensitivity[:p]
        propagation = a @ propagation
        field_initial.append(gradients[k+1] @ propagation[:p])
        for start in range(k+1):
            field_inputs[start].append(full_output[:, start*p:(start+1)*p])
        aggregate = np.hstack((gradients[k].reshape(2, 4, p).mean(axis=1), np.zeros((2, 2*p))))
        reconstructed = np.linalg.pinv(aggregate, rcond=1e-10)
        reduced_output = gradients[k+1] @ (a @ reconstructed)[:p] @ retained
        reduced_output[:, k*p:(k+1)*p] += dt*gradients[k+1]
        retained = reduced_output.reshape(2, 4, h*p).mean(axis=1)
    return {"full": full_output.reshape(q, h, p).transpose(1, 0, 2),
        "loss2": reduced_output.reshape(q, h, p).transpose(1, 0, 2),
        "field_initial": np.vstack(field_initial),
        "field_inputs": [np.vstack(rows) for rows in field_inputs]}


def audit_reference(directory, state, train, prepared):
    from cell_field_response_v5 import AdamDerivative
    with np.load(directory / "reference.npz", allow_pickle=False) as archive:
        saved = {key: archive[key].copy() for key in archive.files}
    p = state.parameter_count
    require(saved["states"].shape == (33, 3*p) and saved["observations"].shape == (33, 8)
            and saved["gradients"].shape == (33, 8, p)
            and np.array_equal(saved["nominal_actions"], np.zeros((32, p))), "reference shape and zero nominal control")
    actual, gradients, transitions, gradient_error = state.clone(), [], [], 0.
    for k in range(33):
        losses, gradient = observed(actual.head, prepared, state.names)
        require(np.array_equal(actual.vector(), saved["states"][k])
                and np.array_equal(losses, saved["observations"][k]), "reference actual state/loss differs")
        gradient_error = max(gradient_error, near(gradient, saved["gradients"][k], "independent panel gradients", atol=1e-14))
        gradients.append(gradient)
        if k < 32:
            derivative = AdamDerivative(state, actual.vector(), actual.step_count, train)
            transitions.append(derivative.jvp(np.eye(3*p)))
            actual.advance(*train, intervention=np.zeros(p))
    independent = forward_coefficients(np.asarray(gradients), transitions)
    errors = {name: near(saved[name+"_maps"], independent["full" if name == "field" else name],
                         "independent forward terminal map: " + name) for name in ("full", "field", "loss2")}
    errors["panel_gradient"] = gradient_error
    errors["field_initial"] = near(saved["field_initial"], independent["field_initial"], "forward arbitrary-initial-state field")
    offsets = np.r_[0, np.cumsum([len(rows) for rows in independent["field_inputs"]])]
    require(np.array_equal(offsets, saved["field_input_offsets"]), "finite-window field input indexing")
    errors["field_inputs"] = near(saved["field_inputs"], np.vstack(independent["field_inputs"]), "forward all-action field outputs")
    full = saved["full_maps"][:8].transpose(1, 0, 2).reshape(8, -1)
    field = saved["field_maps"][:8].transpose(1, 0, 2).reshape(8, -1)
    errors["full_field_singular_values"] = near(np.linalg.svd(full, compute_uv=False),
        np.linalg.svd(field, compute_uv=False), "full/field action-response spectra", atol=1e-13)
    require(saved["field_initial"].shape == (264, 3*p) and 264 > 3*p, "long field dimension scope")
    return saved, independent, errors


def expected_actions(reference, independent, branch):
    p = reference["gradients"].shape[-1]
    count = 0 if branch == "zero32" else 1 if branch in BRANCHES[1:3] else 8
    model = "loss2" if branch.startswith("loss2") else "full"
    matrix = (.02*reference["gradients"][1])[None] if branch == BRANCHES[1] else independent[model][:count]
    actions = np.zeros((32, p))
    if count:
        linear = np.einsum("q,kqp->kp", WEIGHTS, matrix)
        actions[:count] = np.clip(-linear / (.02*.03), -4./np.sqrt(p), 4./np.sqrt(p))
    return actions, count


def audit_branch(directory, branch, state, train, prepared, reference, independent, global_row):
    from cell_field_state import CellTrainingState
    record, proposal = read(directory / "result.json"), read(directory / "proposal.json")
    require(record == global_row and record["status"] == "completed_unguarded_diagnostic"
            and record["completed_steps"] == 32 and record["scientific_acceptance"] is False
            and record["production_authority"] is False and record["safety_filter_used"] is False,
            "branch execution status or global census differs")
    with np.load(directory / "trajectory.npz", allow_pickle=False) as archive:
        actions, states, losses = [archive[key].copy() for key in ("actions", "states", "losses")]
    proposed = np.load(directory / "proposed_actions.npy", allow_pickle=False)
    expected, free = expected_actions(reference, independent, branch)
    require(actions.shape == (32, state.parameter_count) and states.shape == (33, 3*state.parameter_count)
            and losses.shape == (33, 8) and np.array_equal(actions, proposed)
            and np.isfinite(actions).all() and np.all(np.abs(actions) <= 4./np.sqrt(state.parameter_count))
            and np.array_equal(actions[free:], np.zeros_like(actions[free:]))
            and proposal["free_action_steps"] == free and proposal["evaluation_endpoint"] == 32,
            "same declared actions, free prefix, box and fixed zero tail required")
    action_error = near(actions, expected, "independently solved box quadratic")
    actual = state.clone()
    require(record["initial_state_sha256"] == state.digest() and len(record["state_sha256"]) == 33
            and len(record["receipts"]) == 32, "complete initial identity and receipt census")
    for k in range(33):
        measured, _ = observed(actual.head, prepared, state.names)
        require(np.array_equal(actual.vector(), states[k]) and np.array_equal(measured, losses[k])
                and actual.digest() == record["state_sha256"][k], "exact actual physical state/loss replay")
        if k < 32:
            receipt = actual.advance(*train, intervention=.02*actions[k])
            require(receipt == record["receipts"][k], "exact receipt/RNG/clock/context replay")
    loaded = CellTrainingState.load(directory / "terminal", state.bindings, state.protocol,
        state.contexts, record["terminal_state_sha256"])
    require(actual.digest() == loaded.digest() == record["terminal_state_sha256"]
            and actual._metadata() == loaded._metadata(), "complete terminal checkpoint identity")
    anchors = reference["observations"][0, 4:]
    excess = losses[1:, 4:] - anchors
    penalty = float(.5*.02*.03*np.square(actions).sum())
    objective = float(WEIGHTS @ losses[-1] + penalty)
    near(record["old_anchors"], anchors, "original warmup anchors", atol=0., rtol=0.)
    near(record["initial_old_excess"], losses[0, 4:] - anchors, "initial excess", atol=0., rtol=0.)
    near(record["actual_common_objective"], objective, "true priced J32", atol=1e-14, rtol=0.)
    near(record["parameter_penalty"], penalty, "same physical effort price", atol=1e-14, rtol=0.)
    near(record["current_terminal_risk"], losses[-1, :4].mean(), "true current-panel risk", atol=1e-14, rtol=0.)
    near(record["old_terminal_risk"], losses[-1, 4:].mean(), "true old-panel risk", atol=1e-14, rtol=0.)
    require(record["old_violating_steps"] == int(np.any(excess > 0., axis=1).sum())
            and record["maximum_old_excess"] == float(excess.max()), "all observed old violations retained")
    forecasts = {}
    for model in ("full", "field", "loss2"):
        prediction = reference["observations"][-1] + np.einsum("kqp,kp->q", reference[model+"_maps"], actions)
        price = float(WEIGHTS @ prediction + penalty)
        error = losses[-1] - prediction
        reported = record["forecasts_on_actual_actions"][model]
        near(reported["terminal_panels"], prediction, "same-action terminal forecast", atol=1e-14, rtol=0.)
        near(reported["terminal_panel_errors_actual_minus_tangent"], error, "forecast panel residual", atol=1e-14, rtol=0.)
        near(reported["tangent_common_objective"], price, "priced tangent J32", atol=1e-14, rtol=0.)
        near(reported["objective_error_actual_minus_tangent"], WEIGHTS @ error, "priced forecast residual", atol=1e-14, rtol=0.)
        forecasts[model] = {"predicted_J32": price, "actual_minus_predicted_J32": objective-price,
            "predicted_risk_change_from_zero": float(WEIGHTS @ (prediction-reference["observations"][-1])),
            "panel_rmse": float(np.sqrt(np.mean(error**2))), "old_panel_rmse": float(np.sqrt(np.mean(error[4:]**2)))}
    return {"branch": branch, "J32": objective, "current_terminal": float(losses[-1, :4].mean()),
        "old_terminal": float(losses[-1, 4:].mean()), "effort": penalty,
        "warmup_old_mean": float(anchors.mean()), "maximum_old_excess": float(excess.max()),
        "old_violating_steps": int(np.any(excess > 0., axis=1).sum()),
        "terminal_maximum_old_excess": float(excess[-1].max()),
        "action_l2": float(np.linalg.norm(actions)), "action_linf": float(np.max(np.abs(actions))),
        "saturated_coordinate_fraction_in_free_prefix": float(np.mean(np.abs(actions[:free]) == 4./np.sqrt(state.parameter_count))) if free else 0.,
        "independent_proposal_max_abs_error": action_error, "forecasts": forecasts,
        "rollout_cpu_ns": record["cpu_ns"], "rollout_wall_ns": record["wall_ns"]}


def audit(workspace, run, output):
    workspace, run, output = map(lambda p: Path(p).resolve(), (workspace, run, output))
    require(not output.exists() and run != output and run not in output.parents, "new separate audit output required")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    code = workspace / "hepta-repo-v8/qa/stem-bakeoff"
    sys.path.insert(0, str(code))
    from cell_field_common_run_v8 import load_planning, load_warmup
    from cell_learning_models import normalize_features
    sources, report, seal = [read(run / name) for name in ("executed_source.json", "report.json", "diagnostic_seal.json")]
    before = file_hash(run / "diagnostic_seal.json")
    require(file_hash(run / "protocol.json") == PROTOCOL and sha(sources) == SOURCE and len(sources) == 107
            and seal["protocol_sha256"] == report["protocol_sha256"] == PROTOCOL
            and seal["source_sha256"] == report["source_sha256"] == SOURCE
            and report["source_commit"] == COMMIT, "exact remotely frozen execution identity")
    actual_files = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file() and p.name != "diagnostic_seal.json"}
    require(actual_files == set(seal["files"]), "complete sealed output inventory")
    for name, identity in seal["files"].items():
        path = run / name
        require(path.stat().st_size == identity["bytes"] and file_hash(path) == identity["sha256"], "sealed evidence bytes differ")
    for name, identity in sources.items():
        require(file_hash(code / name) == identity, "executed source differs")
    grid, planning = workspace / "pft-development-v7b/grid", workspace / "pft-development-v7b/planning-only"
    plan, base, index = read(run / "protocol.json"), read(grid / "protocol.json"), read(planning / "index.json")
    pins = plan["base_inputs"]
    require(file_hash(grid / "protocol.json") == pins["protocol_sha256"]
            and file_hash(grid / "development_seal.json") == pins["seal_sha256"]
            and file_hash(planning / "index.json") == pins["planning_index_sha256"], "original used input pins changed")
    fits = [(v, t, h, s, f"{v}-{t}-seed{s}-{h}") for v, t, h, s in
            product(("v5", "v6"), ("agnews", "dbpedia"), ("linear", "gated"), (7, 17, 29))]
    expected = {(fit, branch) for *_, fit in fits for branch in BRANCHES}
    global_rows = {(row["fit"], row["branch"]): {k: v for k, v in row.items() if k != "fit"} for row in report["rows"]}
    require(len(report["rows"]) == len(global_rows) == 144 and set(global_rows) == expected
            and report["fits"] == 24 and report["output_slots"] == 144, "all144 registered slots required")
    data = {(v, t): load_planning(planning, grid, index, v, t, pins["protocol_sha256"])
            for v, t in product(("v5", "v6"), ("agnews", "dbpedia"))}
    rows, coefficients, costs, directions = [], [], [], []
    for v, t, h, s, fit in fits:
        train, panels, _ = data[v, t]
        state, _ = load_warmup(workspace, base, fit, v, train)
        prepared = [(normalize_features(x), y) for x, y in panels]
        reference, independent, errors = audit_reference(run / fit, state, train, prepared)
        coefficients.append({"fit": fit, "errors": errors})
        costs.append({"fit": fit, **read(run / fit / "preparation.json")})
        for branch in BRANCHES:
            row = audit_branch(run / fit / branch, branch, state, train, prepared, reference, independent, global_rows[fit, branch])
            rows.append({"fit": fit, "version": v, "task": t, "head": h, "seed": s, **row})
        actions = {branch: np.load(run / fit / branch / "proposed_actions.npy", allow_pickle=False).ravel() for branch in BRANCHES}
        for target, baseline in ((BRANCHES[2], BRANCHES[1]), (BRANCHES[3], BRANCHES[2]),
                                  (BRANCHES[5], BRANCHES[3]), (BRANCHES[4], BRANCHES[3])):
            a, b = actions[target], actions[baseline]
            na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
            directions.append({"fit": fit, "target": target, "baseline": baseline,
                "action_cosine": float(a @ b / (na*nb)) if na*nb else None,
                "action_norm_ratio": na/nb if nb else None,
                "action_max_abs_difference": float(np.max(np.abs(a-b)))})
    require(report["status_counts"] == dict(Counter(row["status"] for row in report["rows"])), "reported status counts")
    require(file_hash(run / "diagnostic_seal.json") == before, "original evidence seal changed")
    for name, identity in sources.items():
        require(file_hash(code / name) == identity, "executed source changed during audit")
    from common_objective_summary_v8 import summarize
    result = {"schema": "hepta.common-terminal-independent-audit.v8", "status": "PASS",
        "protocol_sha256": PROTOCOL, "source_sha256": SOURCE, "source_commit": COMMIT,
        "run_seal_sha256_before": before, "run_seal_sha256_after": file_hash(run / "diagnostic_seal.json"),
        "report_sha256": file_hash(run / "report.json"), "sealed_files": len(actual_files),
        "exact_actual_trajectories": 144, "exact_actual_updates": 4608, "exact_zero_reference_updates": 768,
        "exact_state_and_loss_rows": 4752, "independent_forward_fields": 24,
        "coefficient_checks": coefficients, "rows": rows, "action_direction_pairs": directions,
        "summary": summarize(rows, costs, report),
        "audit_cpu_ns": time.process_time_ns()-cpu, "audit_wall_ns": time.perf_counter_ns()-began,
        "source_files": {p.name: file_hash(p) for p in (Path(__file__), Path(__file__).with_name("common_objective_summary_v8.py"))},
        "selection_labels_accessed": False, "new_sources_accessed": False,
        "scientific_acceptance": False, "production_authority": False,
        "scope": "independent actual replay and forward coefficient recurrence using original physical head/optimizer and qualified derivative primitive; planning-only diagnostic, no external-future causal inference"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "run", "output"):
        parser.add_argument("--" + name, required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "exact_actual_trajectories", "exact_actual_updates", "audit_cpu_ns")}))
