"""Label-denied V6 execution audit, with independent forward quotient algebra.

This verifies deterministic execution and stopped conditions, not scientific
acceptance, independent provenance of the source corpora, or native authority.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_audit_v6 import audit_policy
from cell_field_features import file_hash
from cell_field_planner_v6 import make_plan
import cell_field_policy_v6
from cell_field_policy_v6 import POLICIES, nested_errors
from cell_field_repair_v6 import repair_sequence
from cell_field_replay_v4 import (_arrays, _close, _exact, _read, _require,
    _task_inputs, _verified_protocol, _warmup)
from cell_field_replay_v5 import _deny, _fixed as legacy_fixed, _stable
from cell_field_response_v5 import build_response
from cell_field_safety_v5 import verify_action
from cell_field_state import CellTrainingState
from cell_learning_models import canonical, normalize_features


CANDIDATE = "future_field_h8_repaired"
KNOWN_STATUS = {"completed", "not_executed_tangent_infeasible",
                "not_executed_unresolved", "not_executed_rejected"}


def _forward_field(response, saved):
    """Build O by dense forward JVP products, independently of the VJP recursion."""
    h, p = len(response.transitions), response.gradients.shape[-1]
    dims = np.arange(2*(h+1), 1, -2)
    _exact(saved["field_dimensions"], dims, "future field dimensions")
    _require(saved["field_observations"].shape == (h+1,2*(h+1),3*p)
        and saved["field_inputs"].shape == (h,2*h,p), "future field array shape")
    matrices = [transition.jvp(np.eye(3*p)) for transition in response.transitions]
    observation = np.zeros_like(saved["field_observations"])
    inputs = np.zeros_like(saved["field_inputs"])
    for k in range(h+1):
        transport, rows = np.eye(3*p), []
        for j in range(k,h+1):
            rows.append(response.gradients[j] @ transport[:p])
            if j < h:
                transport = matrices[j] @ transport
        observation[k,:dims[k]] = np.vstack(rows)
    for k in range(h):
        inputs[k,:dims[k+1]] = response.dt*observation[k+1,:dims[k+1],:p]
    relative = 0.
    for key,value in (("field_observations",observation),("field_inputs",inputs)):
        error = np.abs(saved[key]-value)
        relative = max(relative,float(np.max(error/np.maximum(1.,np.abs(value)),initial=0.)))
        _require(np.all(error <= 2e-12+2e-11*np.abs(value)), "independent forward field coefficients: "+key)
    # A fixed arbitrary nonzero full-state origin and time-varying action sequence
    # exercise the stored quotient directly, rather than only its impulse maps.
    state = np.sin(np.arange(3*p)+.5)*np.repeat([1e-4,1e-6,1e-8],p)
    actions = np.cos(np.arange(h*p).reshape(h,p)+.25)/np.sqrt(p)
    retained = saved["field_observations"][0] @ state
    maximum = _close(retained[:2],response.gradients[0]@state[:p],"initial arbitrary tangent output")
    for k,action in enumerate(actions):
        state = matrices[k]@state
        state[:p] += response.dt*action
        retained = retained[2:] + saved["field_inputs"][k,:dims[k+1]]@action
        maximum = max(maximum,_close(retained[:2],response.gradients[k+1]@state[:p],"arbitrary tangent/action field output"))
    return {"coefficient_relative_error":relative,"arbitrary_origin_output_error":maximum}


def _fixed(directory, baseline, expected, split, plan, anchor):
    extra = directory.parent/(directory.name+"-future-field.npz")
    arrays,record = _arrays(extra),_read(extra.with_suffix(".json"))
    _require(record["initial_state_sha256"] == baseline.digest()
        and record["predictions_sha256"] == file_hash(extra), "future fixed forecast commitment")
    response = build_response(baseline,split["current_train"],
        (split["current_probe"],split["old_probe"]),horizon=8,dt=plan["h"])
    field = _forward_field(response,arrays)
    old = _arrays(directory/"frozen_predictions.npz")
    _exact(arrays["actions"],old["actions"],"future fixed common library")
    field["impulse_prediction_error"] = _close(arrays["predictions"],
        np.einsum("kij,aj->aki",response.impulse_maps(),old["actions"]),"future fixed all impulse forecasts")
    result = legacy_fixed(directory,baseline,expected,split,plan,anchor)
    result["future_field"] = field
    return result


def _verified(state, split, actions, anchor, plan, bound, status, *, guarded=False, horizon=8):
    options = {"horizon":horizon,"dt":plan["h"],"action_bound":bound,
               "candidate_status":status,"commit_steps":horizon}
    function = verify_action if guarded else repair_sequence
    if guarded:
        options["backtracking"] = plan["policy_configuration"]["backtracking"]
    result = function(state,{r:split[r] for r in ("current_train","old_probe")},actions,anchor,**options)
    _require(not list(nested_errors(result["record"])), "actual prospective execution error")
    return result


def _policy(directory, warmup, expected, split, projected, plan, anchor, policy):
    record,trajectory = _read(directory/"result.json"),_arrays(directory/"trajectory.npz")
    _require(record["status"] in KNOWN_STATUS and not list(nested_errors(record)), "policy disposition or actual error")
    replay = audit_policy(directory,warmup,projected,split,anchor,plan["policy_configuration"])
    n,spec,config = record["completed_steps"],POLICIES[policy],plan["policy_configuration"]
    _require(record["policy"] == policy and sum(s["committed_steps"] for s in record["steps"]) == n,
             "policy identity/committed accounting")
    result = {"policy":policy,"status":"passed","execution_status":record["status"],
        "replayed_optimizer_steps":n,"execution_errors":0,"maximum_committed_probe_excess":replay["maximum_future_probe_excess"],
        "midpoint_replan":"not_requested","verified_blocks":0,"prospective_optimizer_steps":0}
    steps = [s for s in record["steps"] if "plan" in s]
    offset = 0
    for i,step in enumerate(steps):
        _require(step["at_step"] == offset, "contiguous policy plan offsets")
        saved,declared = _arrays(directory/f"plans/{i}.npz"),_read(directory/f"plans/{i}.json")
        _require(declared == step["plan"], "frozen policy plan record")
        state = warmup.clone()
        state.set_vector(trajectory["states"][offset])
        state.step_count += offset
        _require(state.digest() == record["state_digests"][offset], "complete prospective origin")
        if declared["status"] == "qualified":
            verified = _verified(state,split,saved["actions"],anchor,plan,config["action_bound"],"qualified",
                                 guarded=policy=="response_h8_guarded",horizon=spec["horizon"])
            key = "safety" if policy=="response_h8_guarded" else "repair"
            _require(_stable(verified["record"]) == _stable(step[key]), "complete nonlinear trial/accounting replay")
            count = step["committed_steps"]
            _require(count == (spec["horizon"] if verified["record"]["certified"] else 0), "whole-block atomic disposition")
            _exact(verified["arrays"]["actions"],trajectory["actions"][offset:offset+count],"adopted repaired actions")
            _exact(verified["arrays"]["states"],trajectory["states"][offset:offset+count+1],"adopted repaired complete vectors")
            _require(verified["state"].digest() == record["state_digests"][offset+count], "adopted repaired metadata")
            result["verified_blocks"] += 1
            result["prospective_optimizer_steps"] += verified["record"]["verified_optimizer_steps"]
        else:
            _require(step["committed_steps"] == 0 and "actions" not in saved, "unavailable plan was not executed")
        if policy == CANDIDATE:
            response = build_response(state,split["current_train"],(split["current_probe"],split["old_probe"]),horizon=8,dt=plan["h"])
            fields = _arrays(directory/f"plans/{i}-field.npz")
            result.setdefault("field_checks",[]).append(_forward_field(response,fields))
            _close(saved["maps"],response.terminal_sequence_maps(),"future field terminal maps vs full adjoint")
            if "actions" in saved:
                full = np.zeros(3*state.parameter_count)
                loss_path = [response.observations[0]]
                for k,action in enumerate(saved["actions"]):
                    full = response.transitions[k].jvp(full)
                    full[:state.parameter_count] += plan["h"]*action
                    loss_path.append(response.observations[k+1]+response.gradients[k+1]@full[:state.parameter_count])
                _close(fields["planned_loss_path"],loss_path,"planned field loss path")
            if offset == 16:
                midpoint = CellTrainingState.load(directory/"midpoint",**expected,expected_state_digest=state.digest())
                options = {k:config[k] for k in ("dt","effort_price","action_bound","old_weight","hard_retention")}
                recomputed = make_plan(midpoint,split,anchor,method="future_field",horizon=8,**options)
                _require(_stable(recomputed["record"]) == _stable(declared), "midpoint complete solver recomputation")
                errors = {k:_close(recomputed[k],saved[k],"midpoint "+k)
                          for k in ("maps","reference_states","reference_observations")}
                if recomputed["actions"] is not None:
                    errors["actions"] = _close(recomputed["actions"],saved["actions"],"midpoint planned actions")
                    again = _verified(midpoint,split,recomputed["actions"],anchor,plan,config["action_bound"],"qualified")
                    _require(_stable(again["record"]) == _stable(step["repair"]), "midpoint repaired plan replay")
                receipts = _read(directory/"receipts.json")
                for k in range(16,n):
                    _require(midpoint.advance(*split["current_train"],intervention=plan["h"]*trajectory["actions"][k]) == receipts[k], "restored suffix receipt")
                    _exact(midpoint.vector(),trajectory["states"][k+1],"restored suffix state")
                _require(midpoint.digest() == record["terminal_state_sha256"], "restored terminal full state")
                _exact(midpoint.head.predict_proba(projected),trajectory["terminal_probabilities"],"restored probabilities")
                result.update(midpoint_replan="passed",midpoint_max_errors=errors,restored_suffix_steps=n-16)
        offset += step["committed_steps"]
    if policy == "zero":
        _exact(trajectory["actions"],np.zeros_like(trajectory["actions"]),"zero actual control")
    else:
        _require(offset == n, "all committed blocks covered")
    if policy == CANDIDATE and result["midpoint_replan"] == "not_requested":
        result["midpoint_replan"] = "not_reached" if n<16 else "no_plan_at_stopped_midpoint"
    return result


def _pressure(directory, warmup, expected, split, projected, plan, anchor, indices):
    search,stored,receipts = _read(directory/"search.json"),_arrays(directory/"search.npz"),_read(directory/"search_receipts.json")
    state,checkpoints,crossing = warmup.clone(),{},None
    x,y = split["old_probe"]
    for k in range(len(stored["states"])):
        _exact(state.vector(),stored["states"][k],"pressure search state")
        loss = float(state.head.loss_gradients(normalize_features(x),y,0.)[0])
        _require(loss == stored["old_losses"][k], "pressure search loss")
        if k and loss>anchor and crossing is None:
            crossing = k
        for phase,offset in search["checkpoint_offsets"].items():
            if k==offset:
                checkpoints[phase] = state.clone()
        if k<len(receipts):
            _require(state.advance(*split["current_train"]) == receipts[k], "pressure search receipt")
    expected_offsets = {} if crossing is None else {"prevention":max(0,crossing-8),"recovery":crossing}
    _require(search["status"] == ("no_pressure_crossing" if crossing is None else "pressure_crossing")
        and search["old_anchor"] == anchor and search["tau"] == crossing
        and search["checkpoint_offsets"] == expected_offsets and len(stored["states"]) == len(receipts)+1
        and search["completed_steps"] == len(receipts) == (plan["pressure"]["max_search_steps"] if crossing is None else crossing), "bounded first-crossing search")
    report = {"search_steps":len(receipts),"status":"passed"}
    for guarded in (True,False):
        rows = _read(directory/("guarded-results.json" if guarded else "results.json"))
        checked,certified,updates = 0,0,0
        for phase,origin in checkpoints.items():
            target = directory/phase
            state = CellTrainingState.load(target/"initial",**expected,expected_state_digest=origin.digest())
            frozen = _read(target/"frozen_plans.json")
            identities = ["zero"]+[f"{m}:b{b:g}:hard{int(h)}" for m in plan["pressure"]["models"]
                for b in plan["pressure"]["budgets"] for h in plan["pressure"]["hard_retention"]]
            _require(len(frozen["plans"]) == 13 and [c["id"] for c in frozen["plans"]] == identities, "pressure candidate census")
            for i,candidate in enumerate(frozen["plans"]):
                path = target/f"plans/{i}.npz"
                actions = _arrays(path)["actions"] if str(i) in frozen["arrays"] else None
                if actions is not None:
                    _require(file_hash(path) == frozen["arrays"][str(i)], "pressure frozen action commitment")
                result = _verified(state,split,actions,anchor,plan,candidate["bound"],candidate["record"]["status"],guarded=guarded)
                folder = target/("guarded" if guarded else "verified")
                saved,record = _arrays(folder/f"{i}.npz"),_read(folder/f"{i}.json")
                _require(record == rows[checked] and record["candidate_id"] == candidate["id"]
                    and record["checkpoint"] == phase and not list(nested_errors(record))
                    and _stable(result["record"]) == _stable(record["verification"]), "paired pressure verification")
                for key in ("states","old_losses","actions"):
                    _exact(result["arrays"][key],saved[key],"pressure accepted/rejected "+key)
                _exact(result["state"].head.predict_proba(projected),saved["terminal_probabilities"],"pressure terminal probabilities")
                _exact([state.head_from_vector(v).predict_proba(projected[indices]) for v in result["arrays"]["states"]],
                       saved["retention_probabilities"],"pressure unlabelled retention paths")
                checked += 1
                certified += int(result["record"]["certified"])
                updates += result["record"]["verified_optimizer_steps"]
        _require(checked == len(rows) == 13*len(checkpoints), "all instantiated pressure slots")
        report["guarded" if guarded else "repaired"] = {"instantiated_slots":checked,"certified":certified,"verified_optimizer_steps":updates}
    return report


def audit(run_directory, output, expected_protocol_sha256, protocol_path):
    root,target = Path(run_directory).resolve(),Path(output).resolve()
    _require(not target.exists() and not target.is_relative_to(root), "new audit output outside sealed run required")
    sys.addaudithook(_deny)
    denied = []
    for name in ("validation_labels.json.enc","final_labels.json.enc","label-key.bin"):
        try:
            (root/name).open("rb").close()
        except PermissionError:
            denied.append(name)
    _require(len(denied) == 3, "withheld-input denial hook")
    began,cpu = time.perf_counter_ns(),time.process_time_ns()
    report = {"schema":"hepta.cell-field-independent-replay.v6","status":"failed","fits":[],"failures":[],
        "auditor_sha256":file_hash(__file__),"expected_protocol_sha256":expected_protocol_sha256,
        "withheld_input_paths_denied":denied,"authority":"DENY_ALL","production_authority":False,
        "scope":"execution integrity, independent forward finite-window field algebra, exact replay and replan; no scientific acceptance",
        "prediction_scope":"future field/analytic/SVD reconstructed; Full algebra from stored A/C; legacy four maps commitment/application/first-step checks"}
    try:
        plan,seal = _verified_protocol(root,Path(protocol_path),expected_protocol_sha256)
        summary,hashes = _read(root/"run.json"),_read(root/"executed_source.json")
        identities = [(t,s,h) for t in plan["tasks"] for s in plan["seeds"] for h in plan["head_modes"]]
        _require(plan["schema"] == "hepta.cell-field-fresh-protocol.v6" and summary.get("completed_at")
            and len(identities) == 12 and [(f["task"],f["seed"],f["head"]) for f in summary["fits"]] == identities
            and all(f["status"] == "completed" and not f.get("error") for f in summary["fits"]), "complete fit identities/dispositions")
        source_root = Path(cell_field_policy_v6.__file__).parent
        required = {"cell_field_run_v6.py","cell_field_experiments_v6.py","cell_field_policy_v6.py",
            "cell_field_planner_v6.py","cell_field_observable_v6.py","cell_field_repair_v6.py",
            "cell_field_response_v5.py","cell_field_safety_v5.py","cell_field_state.py","cell_learning_models.py",
            "cell_field_action_io.py","cell_field_control.py"}
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
                    while offset<anchor:
                        baseline.advance(*split["current_train"])
                        offset += 1
                    row["fixed"].append(_fixed(directory/f"fixed/anchor{anchor}",baseline,expected,split,plan,warm["old_anchor"]))
                indices = inputs["retention_indices"]
                _require(indices == [r["index"] for r in inputs["sources"] if r["role"] == "old_test"], "retention source order")
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
