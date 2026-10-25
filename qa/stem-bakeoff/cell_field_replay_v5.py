"""Independent label-denied replay of the sealed V5 finite experiment.

Checks execution integrity, including stopped conditions. It does not accept a
scientific hypothesis, authenticate a host, or grant model publication authority.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_action_control import score_common
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_planner_v5 import make_plan
import cell_field_policy_v5
from cell_field_policy_v5 import POLICIES
from cell_field_replay_v4 import (_arrays, _close, _exact, _read, _require,
    _task_inputs, _verified_protocol, _warmup)
from cell_field_response_v5 import build_response, compress_response
from cell_field_safety_v5 import verify_action
from cell_field_state import CellTrainingState
from cell_learning_models import canonical, normalize_features


CANDIDATE = "response_h8_guarded"


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if not k.endswith(("cpu_ns", "wall_ns"))}
    return [_stable(v) for v in value] if isinstance(value, list) else value


def _fixed(directory, baseline, expected, split, plan, anchor):
    frozen, rows = _read(directory/"frozen_plan.json"), _read(directory/"branches.json")
    state = CellTrainingState.load(directory/"initial", **expected, expected_state_digest=baseline.digest())
    library = fixed_library(state.parameter_count)
    names, actions = [n for n, _ in library], np.asarray([u for _, u in library])
    _require(frozen["actions"] == names and frozen["models"] == plan["models"]
        and frozen["old_anchor"] == anchor and frozen["initial_state_sha256"] == state.digest()
        and frozen["frozen_predictions_sha256"] == file_hash(directory/"frozen_predictions.npz"), "fixed commitment")
    prediction, actual, reference = (_arrays(directory/name) for name in
        ("frozen_predictions.npz", "actual_trajectories.npz", "reference.npz"))
    maps, values, p, h = prediction["loss_maps"], prediction["predictions"], state.parameter_count, 8
    _require(maps.shape == (7,9,2,p) and values.shape == (7,49,9,2)
        and actual["states"].shape == (49,9,3*p) and actual["observations"].shape == (49,9,2)
        and len(rows) == 49 and [r["action_id"] for r in rows] == names
        and all(r["status"] == "completed" for r in rows), "complete fixed census")
    _exact(prediction["actions"], actions, "fixed library")
    _exact([r["u"] for r in rows], actions, "executed fixed actions")
    application = _close(values, np.asarray([np.einsum("kij,aj->aki", m, actions) for m in maps]), "map application")
    impulse = np.vstack((plan["h"]*np.eye(p), np.zeros((2*p,p)))) / reference["state_scales"][:,None]
    response = np.zeros((9,3*p,p))
    for k in range(h):
        response[k+1] = reference["A"][k] @ response[k] + (impulse if k == 0 else 0)
    full = np.einsum("kij,kjl->kil", reference["C_extended"][:,:2], response)
    full_error = _close(maps[4], full, "full tangent from recorded coefficients")
    first_error = max(_close(m[1], full[1], "first-step tangent") for m in maps[:6])
    _exact(maps[:,0], np.zeros_like(maps[:,0]), "initial tangent")
    _exact(values[:,0], np.zeros_like(values[:,0]), "zero-action prediction")
    analytic = build_response(state, split["current_train"], (split["current_probe"],split["old_probe"]), horizon=8, dt=plan["h"])
    analytic_error = _close(maps[5], analytic.impulse_maps(), "analytic response recomputation")
    _exact(analytic.states, reference["reference_states"], "analytic/reference states")
    reduced = compress_response(maps[5], plan["response"]["impulse_compression_relative_tolerance"])
    _require(reduced["rank"] == frozen["preparation"]["response_v5"]["response_rank"], "reported response rank")
    saved = _arrays(directory/"response.npz")
    _close(saved["basis"], reduced["basis"], "SVD basis")
    _close(saved["coefficients"], reduced["coefficients"], "SVD coefficients")
    reconstructed = np.einsum("kir,pr->kip", saved["coefficients"], saved["basis"])
    _close(maps[6], reconstructed, "SVD response reconstruction")
    residual = float(np.linalg.norm((maps[5]-maps[6]).reshape(18,p), 2))
    _require(abs(residual-frozen["preparation"]["response_v5"]["spectral_residual"]) <= 1e-12, "SVD residual")
    for u in actions:
        _require(np.linalg.norm((maps[5]-maps[6])@u) <= residual*np.linalg.norm(u)+1e-12, "action-response residual bound")
    probes = [(normalize_features(split[r][0]),split[r][1]) for r in ("current_probe","old_probe")]
    _exact(actual["states"][0], reference["reference_states"], "actual zero states")
    _exact(actual["observations"][0], reference["reference_observations"][:,:2], "actual zero observations")
    _exact(actual["real_delta"], actual["observations"]-reference["reference_observations"][:,:2], "actual deviations")
    scoring = {k:plan["fixed_scoring"][k] for k in ("dt","effort_price","direct_coefficient","current_shift","feasibility_tolerance")}
    for i, row in enumerate(rows):
        replay, sequence = state.clone(), np.zeros((8,p))
        sequence[0] = actions[i]
        for k in range(9):
            _exact(replay.vector(), actual["states"][i,k], "nonlinear fixed state")
            _exact([replay.head.loss_gradients(x,y,0.)[0] for x,y in probes], actual["observations"][i,k], "nonlinear fixed probes")
            if k < 8:
                replay.advance(*split["current_train"], intervention=plan["h"]*sequence[k])
        _require(replay.digest() == row["final_state_sha256"], "nonlinear fixed terminal identity")
        _require(score_common(actual["real_delta"][i], sequence, reference["reference_observations"][:,:2], anchor, **scoring) == row["scores"], "fixed actual score")
        for m, name in enumerate(plan["models"]):
            _require(score_common(values[m,i], sequence, reference["reference_observations"][:,:2], anchor, **scoring) == row["predicted_scores"][name], "fixed predicted score")
    return {"status":"passed", "branches":49, "replayed_optimizer_steps":392,
        "map_error":application, "full_tangent_error":full_error, "first_step_error":first_error,
        "analytic_map_error":analytic_error, "response_rank":reduced["rank"], "spectral_residual":residual}


def _policy(directory, warmup, expected, split, projected, plan, anchor, policy):
    record, trajectory, receipts = _read(directory/"result.json"), _arrays(directory/"trajectory.npz"), _read(directory/"receipts.json")
    n, p, spec = record["completed_steps"], warmup.parameter_count, POLICIES[policy]
    errors = ([record["error"]] if record.get("error") else []) + [s["error"] for s in record["steps"] if s.get("error")]
    _require(not errors, "recorded policy execution errors: "+str(errors))
    _require(record["status"] in {"completed","not_executed_tangent_infeasible","not_executed_unresolved","not_executed_rejected"}, "known policy disposition")
    _require(record["policy"] == policy and record["registered_steps"] == 32 and type(n) is int and 0 <= n <= 32
        and (record["status"] == "completed") == (n == 32), "policy execution disposition")
    _require(trajectory["states"].shape == (n+1,3*p) and trajectory["actions"].shape == (n,p)
        and trajectory["probabilities"].shape == (n+1,len(projected),4)
        and len(receipts) == n and len(record["state_digests"]) == n+1, "policy trace census")
    replay = CellTrainingState.load(directory/"initial", **expected, expected_state_digest=warmup.digest())
    _require(record["initial_state_sha256"] == replay.digest(), "policy origin")
    old_x, old_y = split["old_probe"]
    midpoint, maximum = None, None
    for k in range(n+1):
        _exact(replay.vector(), trajectory["states"][k], "policy actual state")
        _exact(replay.head.predict_proba(projected), trajectory["probabilities"][k], "policy probabilities")
        _require(replay.digest() == record["state_digests"][k], "policy full metadata")
        if k and spec["guard"]:
            excess = float(replay.head.loss_gradients(normalize_features(old_x),old_y,0.)[0])-anchor
            _require(excess <= 0, "committed guarded probe violation")
            maximum = excess if maximum is None else max(maximum,excess)
        if k == 16:
            midpoint = CellTrainingState.load(directory/"midpoint", **expected, expected_state_digest=replay.digest())
        if k < n:
            _require(replay.advance(*split["current_train"], intervention=plan["h"]*trajectory["actions"][k]) == receipts[k], "policy receipt")
    terminal = CellTrainingState.load(directory/"terminal", **expected, expected_state_digest=replay.digest())
    _require(terminal.digest() == record["terminal_state_sha256"], "policy terminal identity")
    _exact(trajectory["terminal_probabilities"], trajectory["probabilities"][-1], "terminal predictions")
    bound = plan["policy_configuration"]["action_bound"]/np.sqrt(p)
    _require(np.all(np.abs(trajectory["actions"]) <= bound), "committed action box")
    steps = [s for s in record["steps"] if "plan" in s]
    _require(sum(s["committed_steps"] for s in record["steps"]) == n, "committed-step accounting")
    for i, step in enumerate(steps):
        saved, declared = _arrays(directory/f"plans/{i}.npz"), _read(directory/f"plans/{i}.json")
        _require(declared == step["plan"], "saved solver record")
        start, count = step["at_step"], step["committed_steps"]
        if count:
            _require(count == spec["horizon"] and declared["status"] == "qualified", "committed qualified block")
            scale = step["safety"]["accepted_scale"] if spec["guard"] else 1.
            _exact(trajectory["actions"][start:start+count], scale*saved["actions"], "adopted frozen action sequence")
            if spec["guard"]:
                safety = step["safety"]
                _require(safety["certified"] and safety["threshold_slack"] == 0 and safety["old_anchor"] == anchor
                    and safety["initial_state_sha256"] == record["state_digests"][start]
                    and safety["returned_state_sha256"] == record["state_digests"][start+count]
                    and safety["committed_optimizer_steps"] == 0, "guard identity/threshold")
    if policy == "zero":
        _exact(trajectory["actions"], np.zeros_like(trajectory["actions"]), "zero control")
    result = {"policy":policy,"status":"passed","execution_status":record["status"],
        "replayed_optimizer_steps":n,"execution_errors":0,"maximum_committed_probe_excess":maximum,"midpoint_replan":"not_requested"}
    if policy == CANDIDATE and midpoint is not None:
        block = next(((i,s) for i,s in enumerate(steps) if s["at_step"] == 16), None)
        if block is not None:
            i, step = block
            config = {k:plan["policy_configuration"][k] for k in ("dt","effort_price","action_bound","old_weight","hard_retention")}
            recomputed = make_plan(midpoint,split,anchor,method="adjoint",horizon=8,**config)
            saved = _arrays(directory/f"plans/{i}.npz")
            _require(_stable(recomputed["record"]) == _stable(step["plan"]), "midpoint solver recomputation")
            errors = {key:_close(recomputed[key],saved[key],"midpoint "+key)
                      for key in ("maps","reference_states","reference_observations")}
            if recomputed["actions"] is not None:
                errors["actions"] = _close(recomputed["actions"],saved["actions"],"midpoint planned actions")
                verified = verify_action(midpoint,{r:split[r] for r in ("current_train","old_probe")},
                    recomputed["actions"],anchor,horizon=8,dt=plan["h"],action_bound=config["action_bound"],
                    backtracking=plan["policy_configuration"]["backtracking"],commit_steps=8)
                _require(_stable(verified["record"]) == _stable(step["safety"]), "midpoint nonlinear verification")
            result.update(midpoint_replan="passed",midpoint_max_errors=errors)
        else:
            result["midpoint_replan"] = "no_plan_at_stopped_midpoint"
        for k in range(16,n):
            _require(midpoint.advance(*split["current_train"],intervention=plan["h"]*trajectory["actions"][k]) == receipts[k], "restored suffix receipt")
            _exact(midpoint.vector(),trajectory["states"][k+1],"restored suffix state")
        _require(midpoint.digest() == terminal.digest(), "restored terminal identity")
        _exact(midpoint.head.predict_proba(projected),trajectory["terminal_probabilities"],"restored terminal probabilities")
        result["restored_suffix_steps"] = n-16
    elif policy == CANDIDATE:
        result["midpoint_replan"] = "not_reached"
    return result


def _pressure(directory, warmup, expected, split, projected, plan, anchor, retention_indices):
    search, stored, receipts = _read(directory/"search.json"), _arrays(directory/"search.npz"), _read(directory/"search_receipts.json")
    _require(search["status"] in ("pressure_crossing","no_pressure_crossing") and search["old_anchor"] == anchor, "pressure search disposition")
    replay, checkpoints, first_crossing = warmup.clone(), {}, None
    x,y = split["old_probe"]
    normalized = normalize_features(x)
    for k in range(len(stored["states"])):
        _exact(replay.vector(),stored["states"][k],"pressure search state")
        loss = float(replay.head.loss_gradients(normalized,y,0.)[0])
        _require(loss == stored["old_losses"][k], "pressure search probe")
        if k and loss > anchor and first_crossing is None:
            first_crossing = k
        for name, offset in search["checkpoint_offsets"].items():
            if offset == k:
                checkpoints[name] = replay.clone()
        if k < len(receipts):
            _require(replay.advance(*split["current_train"]) == receipts[k], "pressure search receipt")
    _require(len(receipts)+1 == len(stored["states"]) and first_crossing == search["tau"], "first pressure crossing")
    _require(search["completed_steps"] == len(receipts) == (first_crossing if first_crossing is not None
             else plan["pressure"]["max_search_steps"]), "bounded complete pressure search")
    expected_offsets = {} if first_crossing is None else {"prevention":max(0,first_crossing-8),"recovery":first_crossing}
    _require(search["checkpoint_offsets"] == expected_offsets, "pressure checkpoint selection")
    rows, checked, certified, updates = _read(directory/"results.json"), 0, 0, 0
    for phase, origin in checkpoints.items():
        target = directory/phase
        state = CellTrainingState.load(target/"initial",**expected,expected_state_digest=origin.digest())
        frozen = _read(target/"frozen_plans.json")
        candidate_ids = ["zero"] + [f"{m}:b{b:g}:hard{int(h)}" for m in plan["pressure"]["models"]
                                   for b in plan["pressure"]["budgets"] for h in plan["pressure"]["hard_retention"]]
        _require(len(frozen["plans"]) == 13 and [c["id"] for c in frozen["plans"]] == candidate_ids, "pressure candidate census")
        for i,candidate in enumerate(frozen["plans"]):
            action = _arrays(target/f"plans/{i}.npz")["actions"] if str(i) in frozen["arrays"] else None
            if action is not None:
                _require(file_hash(target/f"plans/{i}.npz") == frozen["arrays"][str(i)], "pressure action commitment")
            result = verify_action(state,{r:split[r] for r in ("current_train","old_probe")},action,anchor,
                horizon=8,dt=plan["h"],action_bound=candidate["bound"],backtracking=plan["pressure"]["backtracking"],
                candidate_status=candidate["record"]["status"],commit_steps=8)
            saved, record = _arrays(target/f"verified/{i}.npz"), _read(target/f"verified/{i}.json")
            _require(record == rows[checked] and record["candidate_id"] == candidate["id"]
                and _stable(result["record"]) == _stable(record["verification"]), "pressure prospective verification")
            for key in ("states","old_losses","actions"):
                _exact(result["arrays"][key],saved[key],"pressure certified/rejected "+key)
            _exact(result["state"].head.predict_proba(projected),saved["terminal_probabilities"],"pressure terminal predictions")
            retention = np.asarray([state.head_from_vector(v).predict_proba(projected[retention_indices])
                                    for v in result["arrays"]["states"]])
            _exact(retention,saved["retention_probabilities"],"pressure unlabelled retention predictions")
            certified += int(result["record"]["certified"])
            updates += result["record"]["verified_optimizer_steps"]
            checked += 1
    _require(checked == len(rows) == 13*len(checkpoints), "all instantiated pressure slots")
    return {"status":"passed","search_steps":len(receipts),"registered_slots":26,
            "instantiated_slots":checked,"certified":certified,"verified_optimizer_steps":updates}


def _deny(event, arguments):
    if event == "open" and arguments and any(s in str(arguments[0]).lower()
            for s in ("validation_labels","final_labels","label-key")):
        raise PermissionError("audit cannot open withheld labels or decryption keys")


def audit(run_directory, output, expected_protocol_sha256, protocol_path):
    root, target = Path(run_directory).resolve(), Path(output).resolve()
    _require(not target.exists() and not target.is_relative_to(root), "new output outside sealed run required")
    sys.addaudithook(_deny)
    denied = []
    for name in ("validation_labels.json.enc","final_labels.json.enc","label-key.bin"):
        try:
            (root/name).open("rb").close()
        except PermissionError:
            denied.append(name)
    _require(len(denied) == 3, "withheld-input denial hook")
    began,cpu = time.perf_counter_ns(),time.process_time_ns()
    report = {"schema":"hepta.cell-field-independent-replay.v5","status":"failed","fits":[],"failures":[],
        "auditor_sha256":file_hash(__file__),"expected_protocol_sha256":expected_protocol_sha256,
        "withheld_input_paths_denied":denied,"authority":"DENY_ALL","production_authority":False,
        "scope":"exact local execution replay and deterministic replan; no scientific acceptance or attestation",
        "prediction_scope":"analytic/SVD reconstruction; Full algebra from stored A/C; legacy four maps commitment/application/first-step checks, not independent reduction re-derivation"}
    try:
        plan,seal = _verified_protocol(root,Path(protocol_path),expected_protocol_sha256)
        summary,hashes = _read(root/"run.json"),_read(root/"executed_source.json")
        identities = [(t,s,h) for t in plan["tasks"] for s in plan["seeds"] for h in plan["head_modes"]]
        _require(plan["schema"] == "hepta.cell-field-fresh-protocol.v5" and summary.get("completed_at")
            and len(identities) == 12 and [(f["task"],f["seed"],f["head"]) for f in summary["fits"]] == identities, "complete fit identities")
        source_root = Path(cell_field_policy_v5.__file__).parent
        required = {"cell_field_run_v5.py","cell_field_experiments_v5.py","cell_field_policy_v5.py",
            "cell_field_planner_v5.py","cell_field_response_v5.py","cell_field_safety_v5.py",
            "cell_field_state.py","cell_learning_models.py","cell_field_action_io.py","cell_field_control.py"}
        _require(isinstance(hashes,dict) and required <= set(hashes), "complete critical source inventory")
        for name,digest in hashes.items():
            _require(Path(name).name == name and not (source_root/name).is_symlink()
                and file_hash(source_root/name) == digest, "executed source changed: "+name)
        report.update(source_files_verified=len(hashes),sealed_files_verified=len(seal["files"]),
            seal_sha256=file_hash(root/"pre_evaluation_seal.json"),executed_source_sha256=file_hash(root/"executed_source.json"))
        tasks = {task:_task_inputs(root,task,plan) for task in plan["tasks"]}
        for task,seed,head in identities:
            row = {"fit_id":f"{task}-seed{seed}-{head}","status":"failed","fixed":[],"policies":[]}
            report["fits"].append(row)
            try:
                directory = root/task/f"seed{seed}-{head}"
                inputs,split,projected,contexts = tasks[task]
                state,warm,expected,count = _warmup(directory,task,seed,head,inputs,split,projected,contexts,plan,hashes,expected_protocol_sha256)
                row["checkpoint_bindings_verified"] = count
                baseline,offset = state.clone(),0
                for anchor in plan["anchor_offsets"]:
                    while offset < anchor:
                        baseline.advance(*split["current_train"])
                        offset += 1
                    row["fixed"].append(_fixed(directory/f"fixed/anchor{anchor}",baseline,expected,split,plan,warm["old_anchor"]))
                indices = inputs["retention_indices"]
                _require(indices == [r["index"] for r in inputs["sources"] if r["role"] == "old_test"], "retention source-feature order")
                row["pressure"] = _pressure(directory/"pressure",state,expected,split,projected,plan,warm["old_anchor"],indices)
                for policy in plan["mpc"]["policies"]:
                    row["policies"].append(_policy(directory/"mpc"/policy,state,expected,split,projected,plan,warm["old_anchor"],policy))
                row["status"] = "passed"
            except Exception as error:
                report["failures"].append({"fit_id":row["fit_id"],"type":type(error).__name__,"message":str(error)})
        _verified_protocol(root,Path(protocol_path),expected_protocol_sha256)
        report.update(run_unchanged_after_replay=True,status="failed" if report["failures"] else "passed")
    except Exception as error:
        report["failures"].append({"type":type(error).__name__,"message":str(error)})
    report.update(completed_at=datetime.now(timezone.utc).isoformat(),cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-began)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("xb") as stream:
        stream.write(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-directory","output","expected-protocol-sha256","protocol-path"):
        parser.add_argument("--"+name,required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({k:result[k] for k in ("status","failures")}),flush=True)
    sys.exit(0 if result["status"] == "passed" else 1)
