"""Bounded exact per-step repair of a planned sequence, with atomic adoption.

Every accepted future probe loss is <= the original warmup threshold. Failure
means this finite search found no safe sequence; it is not global infeasibility.
All optimizer state, clock, sampler and context stay on prospective clones until
the caller adopts a completely certified block. No held-out retention is proved.
"""

import hashlib
import time

import numpy as np

from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import normalize_features


def _repair_step(state, train, probe, intended, anchor, dt, bound):
    p, old_x, old_y = state.parameter_count, *probe
    record = {"status":"unresolved", "trials":[], "optimizer_updates":0,
              "initial_state_sha256":state.digest(), "repaired":False}

    def measure(vector, action, kind, length=None):
        if len(record["trials"]) >= 16:
            raise RuntimeError("fixed sixteen-head trial budget exceeded")
        trial_record = {"kind":kind,"length":length,"action_sha256":hashlib.sha256(action.tobytes()).hexdigest()}
        record["trials"].append(trial_record)
        loss, gradients = state.head_from_vector(vector).loss_gradients(old_x,old_y,0.)
        gradient = np.concatenate([gradients[n].ravel() for n in state.names])
        if not np.isfinite(loss) or not np.isfinite(gradient).all():
            raise ValueError("nonfinite exact old-probe trial")
        trial_record.update(old_loss=float(loss),within_threshold=bool(loss <= anchor))
        return float(loss),gradient

    def advance(action):
        current = state.clone()
        receipt = current.advance(*train,intervention=dt*action)
        record["optimizer_updates"] += 1
        return current,receipt

    try:
        first,receipt = advance(intended)
        value,gradient = measure(first.vector(),intended,"intended")
        if value <= anchor:
            record.update(status="certified",old_loss=value,accepted_kind="intended")
            return first,intended.copy(),receipt,record
        base,_ = advance(np.zeros(p))
        base_vector = base.vector()
        planned = base_vector.copy()
        planned[:p] += dt*intended
        if not np.array_equal(planned,first.vector()):
            raise RuntimeError("common Adam/sampler base differs across prospective actions")
        magnitude = float(np.max(np.abs(gradient)))
        selected,selected_vector,selected_loss,selected_length = None,None,None,None

        def trial(length,kind):
            action = np.clip(intended-length*(gradient/magnitude),-bound,bound)
            vector = base_vector.copy()
            vector[:p] += dt*action
            value,_ = measure(vector,action,kind,float(length))
            return action,vector,value

        if magnitude > 0:
            left = 0.
            for j in range(12):
                length = bound*2.**j/64.
                action,vector,value = trial(length,"gradient_grid")
                if value <= anchor:
                    selected,selected_vector,selected_loss,selected_length = action,vector,value,length
                    right = length
                    for _ in range(2):
                        middle = (left+right)/2
                        action,vector,value = trial(middle,"gradient_bisect")
                        if value <= anchor:
                            right = middle
                            selected,selected_vector,selected_loss,selected_length = action,vector,value,middle
                        else:
                            left = middle
                    break
                left = length
        if selected is None:
            hold = (state.parameter_vector()-base_vector[:p])/dt
            record["parameter_hold_within_box"] = bool(np.isfinite(hold).all() and np.all(np.abs(hold) <= bound))
            if record["parameter_hold_within_box"]:
                vector = base_vector.copy()
                vector[:p] += dt*hold
                value,_ = measure(vector,hold,"parameter_hold")
                if value <= anchor:
                    selected,selected_vector,selected_loss = hold,vector,value
        if selected is None:
            record.update(status="rejected",reason="bounded_search_exhausted; global feasibility unknown")
            return None,None,None,record
        committed,receipt = advance(selected)
        expected = base.clone()
        expected.set_vector(selected_vector)
        if committed.digest() != expected.digest():
            raise RuntimeError("selected repair does not replay its complete optimizer/sampler state")
        value,_ = measure(committed.vector(),selected,"selected_replay",selected_length)
        if value > anchor or value != selected_loss:
            raise RuntimeError("selected repair failed exact replayed threshold")
        record.update(status="certified",repaired=True,old_loss=value,
            accepted_kind="parameter_hold" if selected_length is None else "gradient_line",
            accepted_length=selected_length,terminal_state_sha256=committed.digest())
        return committed,selected,receipt,record
    except Exception as error:
        record.update(status="unresolved",error={"type":type(error).__name__,"message":str(error)})
        return None,None,None,record


def repair_sequence(state, development, candidate, old_anchor, *, horizon=8, dt=.02,
                    action_bound=4., candidate_status="qualified", commit_steps=8):
    """Certify a frozen repaired block or return the exact original checkpoint.

    Intended velocities must already satisfy the V4/V5 per-coordinate box.
    Failed steps use a fixed projected old-gradient line search: twelve lengths
    b*2**j/64, j=0..11; the first safe bracket gets two bisection refinements.
    If none passes, parameter hold is tested only when its exact velocity is in
    the same box. A chosen repair is independently advanced and re-evaluated.
    At most sixteen loss/gradient head evaluations occur per failed step.

    Returned ``state``, ``next_state`` and ``commit_state`` are complete clones.
    ``certified_optimizer_steps`` never means publication: committed steps here
    remain zero. On rejection the returned trajectory is just the input state;
    per-step diagnostic records retain the uncommitted prospective search.
    """
    began,cpu = time.perf_counter_ns(),time.process_time_ns()
    if (type(state) is not CellTrainingState or not 1 <= state.parameter_count <= 4096
            or type(horizon) is not int or not 1 <= horizon <= 8
            or type(commit_steps) is not int or not 1 <= commit_steps <= horizon
            or type(dt) not in (int,float) or not np.isfinite(dt) or not 0 < dt <= 1
            or type(action_bound) not in (int,float) or not np.isfinite(action_bound) or not 0 < action_bound <= 1e6
            or type(old_anchor) not in (int,float) or not np.isfinite(old_anchor) or old_anchor < 0
            or not isinstance(development,dict) or set(development) != {"current_train","old_probe"}
            or candidate_status not in ("qualified","tangent_infeasible","unresolved")):
        raise ValueError("bounded complete state, frozen threshold and declared training/probe inputs required")
    pairs = {name:tuple(np.asarray(v).copy() for v in pair) for name,pair in development.items()}
    identities = {name:dataset_digest(*pair) for name,pair in pairs.items()}
    if (state.active_context != "current_train" or state.contexts.get("current_train") != identities["current_train"]
            or any(x.shape[1] != state.head.width or np.any(y >= state.head.classes) for x,y in pairs.values())):
        raise ValueError("declared selected training context and probe coordinates required")
    p,before,bound = state.parameter_count,state.digest(),action_bound/np.sqrt(state.parameter_count)
    actions = None
    if candidate_status == "qualified":
        actions = np.asarray(candidate,dtype=np.float64).copy()
        if actions.shape == (p,):
            actions = np.vstack((actions,np.zeros((horizon-1,p))))
        if actions.shape != (horizon,p) or not np.isfinite(actions).all() or np.any(np.abs(actions) > bound):
            raise ValueError("finite intended actions already within the frozen box required")
    elif candidate is not None:
        raise ValueError("unavailable plan must not supply executable actions")
    probe = normalize_features(pairs["old_probe"][0]),pairs["old_probe"][1]
    initial = float(state.head.loss_gradients(*probe,0.)[0])
    if not np.isfinite(initial):
        raise ValueError("finite initial old-probe loss required")
    record = {"schema":"hepta.cell-field-exact-sequence-repair.v6","status":"rejected","certified":False,
        "candidate_status":candidate_status,"initial_state_sha256":before,"horizon":horizon,"dt":dt,
        "action_bound":action_bound,"old_anchor":float(old_anchor),"threshold_slack":0.,
        "initial_old_loss":initial,"initial_old_excess":initial-old_anchor,"initial_within_threshold":initial <= old_anchor,
        "data_sha256":identities,"requested_commit_steps":commit_steps,"step_records":[],
        "certified_optimizer_steps":0,"committed_optimizer_steps":0,"prospective_safe_steps":0,
        "verified_optimizer_steps":0,"probe_head_evaluations":1,"repaired_steps":0,
        "trial_head_cap_per_failed_step":16,"authority":"DENY_ALL","production_authority":False,
        "rule":"projected old-gradient grid b*2^j/64,j=0..11;two refinements;bounded exact parameter-hold fallback",
        "scope":"fixed-probe finite-search certificate; no held-out preservation or global feasibility claim"}
    result = {"record":record,"state":state.clone(),"next_state":state.clone(),"commit_state":state.clone(),
        "arrays":{"states":state.vector()[None,:],"actions":np.zeros((0,p)),"old_losses":np.array([initial])},"receipts":[]}
    if candidate_status != "qualified":
        record["status"] = "not_executed_"+candidate_status
    else:
        record["candidate_actions_sha256"] = hashlib.sha256(actions.tobytes()).hexdigest()
        current,states,losses,accepted,receipts = state.clone(),[state.vector()],[initial],[],[]
        next_state,commit_state = None,None
        for k,intended in enumerate(actions):
            trial_start,trial_cpu = time.perf_counter_ns(),time.process_time_ns()
            following,action,receipt,step = _repair_step(current,pairs["current_train"],probe,intended,old_anchor,dt,bound)
            step.update(step=k,cpu_ns=time.process_time_ns()-trial_cpu,wall_ns=time.perf_counter_ns()-trial_start)
            record["step_records"].append(step)
            record["verified_optimizer_steps"] += step["optimizer_updates"]
            record["probe_head_evaluations"] += len(step["trials"])
            if step["status"] != "certified":
                record.update(status=step["status"],failed_at_step=k)
                break
            current = following
            states.append(current.vector())
            losses.append(step["old_loss"])
            accepted.append(action)
            receipts.append(receipt)
            record["prospective_safe_steps"] += 1
            record["repaired_steps"] += int(step["repaired"])
            if k == 0:
                next_state = current.clone()
            if k+1 == commit_steps:
                commit_state = current.clone()
        if len(accepted) == horizon:
            accepted = np.asarray(accepted)
            result.update(state=current,next_state=next_state,commit_state=commit_state,receipts=receipts,
                arrays={"states":np.asarray(states),"actions":accepted,"old_losses":np.asarray(losses)})
            record.update(status="certified",certified=True,certified_optimizer_steps=horizon,
                maximum_future_excess=float(max(losses[1:])-old_anchor),first_step_state_sha256=next_state.digest(),
                commit_state_sha256=commit_state.digest(),accepted_actions_sha256=hashlib.sha256(accepted.tobytes()).hexdigest())
    record.update(returned_state_sha256=result["state"].digest(),
        returned_state_within_threshold=bool(result["arrays"]["old_losses"][-1] <= old_anchor),
        cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-began)
    if state.digest() != before:
        raise RuntimeError("prospective repair changed its input checkpoint")
    return result
