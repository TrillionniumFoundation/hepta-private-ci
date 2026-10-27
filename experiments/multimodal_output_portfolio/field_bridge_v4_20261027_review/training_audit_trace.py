"""Independent NumPy policy, trace, guard and logical-cost verification.

No model, observer, source tensor or training primitive is imported here.
"""
from collections import Counter
import numpy as np

if __package__:
    from .training_audit_common import (PANEL, ROLES, NAMES, TIMING_KEYS, need, object_sha, valid_hash, vector, near, identity)
else:
    from training_audit_common import (PANEL, ROLES, NAMES, TIMING_KEYS, need, object_sha, valid_hash, vector, near, identity)

def translated(raw, observed, fit):
    raw, observed, fit = (vector(v, 30, k) for v, k in ((raw, "raw"), (observed, "origin"), (fit, "fit")))
    result = raw.copy()
    selected = np.asarray(PANEL)
    result[selected] = raw[selected] - (observed[selected] - fit[selected])
    return result

def head_prediction(head, raw):
    """Independent reconstruction, with intermediate values retained for checks."""
    mode = head["mode"]
    dimension = {"field":12, "generic":12, "richer":30, "h7":7}[mode]
    need(head["dimension"] == dimension and head["ridge"] == 1.0
         and head["fit_rows"] == 24 and head["prediction_clipping"] is False,
         "Frozen-head specification changed")
    need(head["feature_names"] == list(NAMES) and head["coefficient_count"] == (dimension+1)*4,
         "Head feature/coefficient inventory changed")
    raw = vector(raw, 30, "head input")
    mean, scale = vector(head["raw_mean"], 30, "raw mean"), vector(head["raw_scale"], 30, "raw scale")
    pmean = vector(head["projected_mean"], dimension, "projected mean")
    pscale = vector(head["projected_scale"], dimension, "projected scale")
    projection, coefficients = np.asarray(head["projection"]), np.asarray(head["coefficients"])
    need(projection.shape == (30, dimension) and coefficients.shape == (dimension+1, 4)
         and np.isfinite(projection).all() and np.isfinite(coefficients).all()
         and np.all(scale >= 1e-6) and np.all(pscale >= 1e-6), "Invalid frozen linear operator")
    standardized = np.divide(np.subtract(raw, mean), scale)
    projected = np.matmul(standardized, projection)
    normalized = np.divide(np.subtract(projected, pmean), pscale)
    design = np.empty(dimension+1, dtype=np.float64)
    design[0], design[1:] = 1., normalized
    prediction = np.matmul(design, coefficients)
    need(np.isfinite(prediction).all(), "Nonfinite independently reconstructed prediction")
    return prediction, {"raw_standardized_max_abs": float(np.max(np.abs(standardized))),
                        "projected_standardized_max_abs": float(np.max(np.abs(normalized)))}

def fit_initial(bank):
    need(bank["schema"] == "hepta.field-bridge.v3.terminal-reference-bank.1"
         and bank["feature_names"] == list(NAMES), "Wrong frozen bank")
    rows = [r for r in bank["records"] if r["step"] == 0]
    need(len(rows) == 4 and {r["trajectory"] for r in rows} == {0,1,2,3}, "Missing fit origins")
    values = np.stack([vector(row["state"],30,"fit origin") for row in rows])
    need(np.array_equal(values[:, PANEL], np.repeat(values[0:1, PANEL],4,axis=0)), "Fit origins need averaging")
    initial = {k:rows[0]["state_checkpoint"][k] for k in ("parameters", "optimizer")}
    need(all({k:r["state_checkpoint"][k] for k in initial} == initial for r in rows), "Fit initial parameter/SGD differs")
    return values[0], initial

def base_policy(protocol, seed, method, scope, head, origin):
    constant = method.startswith("ordinary_")
    return {"schema":"hepta.field-bridge.v4.policy.1", "study_id":protocol["study_id"], "seed":seed,
        "method":method, "action_index":int(method[-1]) if constant else None,
        "head_sha256":None if head is None else object_sha(head), "scope":scope,
        "panel_indices":list(PANEL), "fit_initial":origin.tolist(),
        "transform":"raw[I]-(observed_initial[I]-fit_initial[I]); other coordinates unchanged",
        "uses_translated_prediction_state":method.startswith("origin_"),
        "observed_initial_rule":"existing first step-zero probe/guard measurement; immutable through rejection",
        "predictor":"frozen V3 two normalizations, projection, linear head; np.argmax first tie",
        "ordinary_constant_full_path":constant, "steps":288, "macro_steps":48}

def counters(value, label):
    need(isinstance(value, dict) and all(isinstance(k,str) and type(v) is int and v >= 0 for k,v in value.items()),
         label + " must contain nonnegative integer counters")
    need(all(not any(word in key for word in ("audit", "endpoint", "terminal_fit", "native")) or amount == 0
             for key,amount in value.items()), label + " contains forbidden training work")
    return {key:amount for key,amount in value.items() if amount}

def add_forward(result, prefix, calls, examples, action):
    result.update({prefix+"_calls":calls, prefix+"_examples":examples,
                   prefix+"_refinement_examples":examples*(1+(action != 0))})

def hard_cost(prefix, pairs, batches, action):
    result = {}
    add_forward(result, prefix+"_generator", batches, pairs, action)
    result[prefix+"_reward_observer_calls"] = 2*batches
    result[prefix+"_reward_observer_digit_examples"] = 2*pairs
    return result

def expected_feature_cost(protocol, allocation, seed):
    p = protocol["training"]
    action = p["fixed_actions"][str(seed)]
    probe = allocation["roles"]["qualification_probe"]["pairs"] * len(p["conditions"])
    guard = allocation["roles"]["qualification_guard"]["pairs"]
    probe_batches = len(p["conditions"])*int(np.ceil(allocation["roles"]["qualification_probe"]["pairs"]/p["panel_batch_size"]))
    guard_batches = int(np.ceil(guard/p["panel_batch_size"]))
    gradient_examples = p["adapt_batch_size"] + p["rehearsal_batch_size"]
    result = hard_cost("current_hard_value", probe, probe_batches, action)
    for prefix in ("directional_generator", "directional_teacher"):
        add_forward(result,prefix,2,gradient_examples,action)
    result.update(directional_backward_calls=1, directional_backward_examples=gradient_examples,
                  directional_gradient_measurements=1, feature_probe_reverse_calls=3,
                  feature_probe_reverse_examples=2*probe+guard)
    add_forward(result,"adapt_feature_probe",probe_batches,probe,action)
    add_forward(result,"clean_feature_probe",guard_batches,guard,action)
    add_forward(result,"margin_generator",probe_batches,probe,action)
    result.update(margin_reward_observer_calls=2*probe_batches, margin_reward_observer_digit_examples=2*probe)
    return result

def expected_block_cost(protocol, allocation, seed, action_index, accepted):
    p = protocol["training"]
    action = p["fixed_actions"][str(seed)]
    n = p["macro_steps"]
    examples = n*(p["adapt_batch_size"]+p["rehearsal_batch_size"])
    guard = allocation["roles"]["qualification_guard"]["pairs"]
    result = hard_cost("candidate_guard",guard,int(np.ceil(guard/p["panel_batch_size"])),action)
    for prefix in ("gradient_generator", "gradient_teacher"):
        add_forward(result,prefix,2*n,examples,action)
    result.update(gradient_backward_calls=n, gradient_backward_examples=examples,
                  scheduled_gradient_microsteps=n, transaction_snapshots=1)
    if action_index:
        result["optimizer_steps"] = n
    if accepted:
        result["accepted_blocks"] = 1
    else:
        result.update(rejected_blocks=1, discarded_gradient_microsteps=n)
    return result

def schedule_sha(protocol, seed, sid, step):
    p = protocol["training"]
    rows = [{"step":t,"adapt_seed":seed*100003+p["batch_seed_offset"]+sid*1009+t,
             "clean_seed":seed*100003+p["rehearsal_seed_offset"]+sid*1009+t,
             "noise_seed":p["forward_seed_offset"]+t,"condition":p["conditions"][t % len(p["conditions"])]}
            for t in range(step,step+48)]
    return object_sha(rows)

def trace_audit(rows, done, protocol, allocation, seed, sid, method, head, expected_base,
                initial_identity, baseline_guard, parameter_count, trace_bytes, checkpoint_bytes):
    need(len(rows)==12 and [r["record_index"] for r in rows]==list(range(12)), "Incomplete decision/outcome journal")
    clocks = [r["committed_monotonic_ns"] for r in rows]
    need(all(type(v) is int and v > 0 for v in clocks) and all(a<b for a,b in zip(clocks,clocks[1:])), "Journal clock is not strictly increasing")
    need(done["study_id"]==protocol["study_id"] and done["seed"]==seed and done["method"]==method
         and done["schedule_id"]==sid and done["schema"]=="hepta.field-bridge.v4.trained-path.1",
         "Path study/method/seed/schedule identity differs")
    need(done["source_roles"]==list(ROLES) and done["endpoint_accessed"] is False
         and done["best_step_selection"] is False and done["final_step"]==288, "Path scope/terminal time differs")
    origin = vector(rows[0]["raw_state"],30,"first measured state")
    realized = {**expected_base,"observed_initial":origin.tolist(),"schedule_id":sid}
    need(done["policy_identity"]==realized and done["policy_sha256"]==object_sha(realized)
         and done["base_policy_sha256"]==object_sha(expected_base), "Frozen or realized policy identity differs")
    need(len(done["decisions"])==6, "Path decision summary is incomplete")
    previous = initial_identity
    identity(previous,"initial state")
    resources, actions, accepted_all, errors, scales = Counter(), [], [], [], []
    learning_rate = protocol["training"]["learning_rate"]
    baseline = np.asarray(baseline_guard["values"],dtype=np.float64)
    nprobe = allocation["roles"]["qualification_probe"]["pairs"]*4
    nguard = allocation["roles"]["qualification_guard"]["pairs"]
    need(baseline.shape==(nguard,) and np.isfinite(baseline).all(), "Invalid original guard baseline")
    feature_cost = expected_feature_cost(protocol,allocation,seed)
    for position,step in enumerate(range(0,288,48)):
        decision,outcome = rows[2*position:2*position+2]
        need(decision["schema"]=="hepta.field-bridge.v4.decision.1" and decision["kind"]=="decision_before_update"
             and decision["study_id"]==protocol["study_id"] and decision["seed"]==seed and decision["method"]==method
             and decision["schedule_id"]==sid and decision["step"]==step, "Decision path identity differs")
        raw = vector(decision["raw_state"],30,"raw feature")
        need(np.array_equal(decision["observed_initial"],origin)
             and np.array_equal(decision["calibration_context"],origin[list(PANEL)])
             and decision["panel_indices"]==list(PANEL)
             and np.array_equal(decision["fit_initial"],expected_base["fit_initial"]), "First calibration capture changed")
        mapped = translated(raw,origin,expected_base["fit_initial"])
        need(np.array_equal(decision["mapped_state"],mapped), "Fourteen-field translation differs")
        use_mapped = method.startswith("origin_")
        need(decision["prediction_state_kind"]==("mapped" if use_mapped else "raw"), "Wrong predictor state")
        if head is None:
            need(decision["predictions"] is None, "Ordinary control fitted a predictor")
            chosen = int(method[-1])
        else:
            prediction,scale = head_prediction(head,mapped if use_mapped else raw)
            errors.append(near(decision["predictions"],prediction,"Frozen head prediction"))
            scales.append(scale)
            chosen = int(np.argmax(prediction))
        need(type(decision["action_index"]) is int and decision["action_index"]==chosen, "Independent argmax/constant action differs")
        need(decision["base_policy_sha256"]==done["base_policy_sha256"]
             and decision["policy_sha256"]==done["policy_sha256"], "Decision policy SHA differs")
        identity(decision["before"],"decision before")
        need(decision["before"]==previous, "Parameter or SGD discontinuity between blocks")
        need(decision["schedule_sha256"]==schedule_sha(protocol,seed,sid,step), "Scheduled 48-step minibatch/noise sequence differs")
        current = np.asarray(decision["current_reward_values"],dtype=np.float64)
        need(current.shape==(nprobe,) and np.isfinite(current).all()
             and len(decision["current_output_sha256"])==nprobe
             and all(valid_hash(h) for h in decision["current_output_sha256"]), "Invalid probe observations")
        near(raw[0],current.mean(),"Current hard feature")
        near(raw[6],step/288,"Learning-time feature",atol=0.)
        near(raw[4],np.sqrt(np.mean(np.square(raw[16:24]))),"Operator displacement summary")
        feature = decision["feature_receipt"]
        need(feature["names"]==list(NAMES) and feature["before"]==previous
             and feature["state_grad_rng_invariant"] is True, "Feature state-preservation receipt differs")
        measured = feature["measured"]
        g,m = measured["gradient_l2"], measured["momentum_l2"]
        need(np.isfinite([g,m,measured["gradient_momentum_dot"]]).all() and g>=0 and m>=0, "Invalid direction norms")
        near(raw[7],g/np.sqrt(parameter_count),"Gradient RMS")
        near(raw[5],m/np.sqrt(parameter_count),"Momentum RMS")
        cosine = np.clip(measured["gradient_momentum_dot"]/(g*m),-1.,1.) if g*m>0 else 0.
        near(raw[8],cosine,"Gradient/momentum cosine")
        need(all(valid_hash(measured[k]) for k in ("gradient_sha256","momentum_sha256","direction_sha256"))
             and measured["next_gradient"]["optimizer_advanced"] is False, "Directional measurement advanced optimizer or lacks tensor identity")
        need(counters(feature["resources"],"feature costs")==feature_cost, "Feature workload counters differ")
        resources.update(feature_cost)
        digest = object_sha(decision)
        need(outcome["schema"]=="hepta.field-bridge.v4.block-outcome.1" and outcome["kind"]=="block_outcome"
             and outcome["study_id"]==protocol["study_id"] and outcome["decision_sha256"]==digest
             and outcome["policy_sha256"]==done["policy_sha256"], "Outcome is not bound to its committed decision")
        receipt = outcome["receipt"]
        need(receipt["start"]==step and receipt["end"]==step+48 and receipt["action_index"]==chosen
             and receipt["multiplier"]==protocol["training"]["multipliers"][chosen]
             and receipt["schedule_id"]==sid and receipt["schedule_sha256"]==decision["schedule_sha256"]
             and receipt["before"]==previous and receipt["clock_advances_on_rejection"] is True,
             "Block span/action/schedule/clock differs")
        for key in ("candidate","after"):
            identity(receipt[key],"block "+key)
        guard = np.asarray(receipt["guard_values"],dtype=np.float64)
        need(guard.shape==(nguard,) and np.isfinite(guard).all() and len(receipt["guard_output_sha256"])==nguard
             and all(valid_hash(v) for v in receipt["guard_output_sha256"]), "Invalid raw guard observations")
        delta = float(np.mean(guard-baseline))
        near(receipt["guard_delta"],delta,"Raw empirical guard delta")
        accepted = delta >= protocol["training"]["guard_min_delta"]
        need(type(receipt["accepted"]) is bool and receipt["accepted"]==accepted, "Guard accept/reject predicate differs")
        if not accepted or chosen==0:
            need(receipt["after"]==previous, "Rejected/zero block failed parameter and SGD restoration")
        if accepted:
            need(receipt["after"]==receipt["candidate"], "Accepted state differs from candidate")
        if chosen==0:
            need(receipt["candidate"]==previous, "Zero-action candidate changed parameters or SGD")
        if accepted and chosen:
            learning_rate = protocol["training"]["learning_rate"]*protocol["training"]["multipliers"][chosen]
        for key in ("first_gradient","last_gradient"):
            gradient = receipt[key]
            need(gradient["optimizer_advanced"] is (chosen!=0)
                 and np.isfinite([gradient["loss"],gradient["unclipped_gradient_norm"]]).all()
                 and gradient["unclipped_gradient_norm"]>=0, "First/last gradient receipt differs")
        block_cost = expected_block_cost(protocol,allocation,seed,chosen,accepted)
        need(counters(receipt["resources"],"block costs")==block_cost, "Block workload/rejection/zero counters differ")
        resources.update(block_cost)
        summary = {"step":step,"action_index":chosen,"accepted":accepted,"decision_sha256":digest}
        need(done["decisions"][position]==summary, "Path decision summary is not exact")
        previous = receipt["after"]
        actions.append(chosen)
        accepted_all.append(accepted)
    need(done["final_identity"]==previous, "Terminal identity does not follow all six blocks")
    resources.update(panel_origin_captures=1,panel_origin_calibration_context_values=14,
                     panel_origin_calibration_context_bytes=112,panel_origin_translation_calls=6,
                     panel_origin_coordinates=84,policy_prediction_calls=0 if head is None else 6,
                     training_trace_bytes=trace_bytes,checkpoint_bytes=checkpoint_bytes)
    actual = counters(done["resources"],"path costs")
    for key in TIMING_KEYS:
        need(type(done["resources"].get(key,0)) is int and done["resources"].get(key,0)>=0, "Invalid measured control/I/O cost")
        resources[key] = done["resources"].get(key,0)
    expected = {k:v for k,v in resources.items() if v}
    need(actual==expected, "Path total counters do not match independent feature/block/storage reconstruction")
    need(type(done["wall_ns"]) is int and done["wall_ns"]>0 and type(done["cpu_ns"]) is int and done["cpu_ns"]>=0,
         "Missing inclusive path timing")
    need(done["wall_ns"]>=resources["policy_control_wall_ns"]+resources["checkpoint_serialization_wall_ns"]
         and done["cpu_ns"]>=resources["policy_control_cpu_ns"], "Control/serialization time exceeds its containing path")
    return {"seed":seed,"method":method,"schedule_id":sid,"actions":actions,"accepted":accepted_all,
            "policy_sha256":done["policy_sha256"],"base_policy_sha256":done["base_policy_sha256"],
            "max_prediction_error":max(errors,default=0.),"normalization_ranges":scales,
            "expected_final_learning_rate":learning_rate,"resources":expected,
            "final_identity":previous,"path_wall_ns":done["wall_ns"],"path_cpu_ns":done["cpu_ns"],
            "representation_storage":{"active_calibration_array_bytes":112,
                "audit_numeric_payload_per_decision_for_raw_mapped_observed_fit_and_context":(4*30+14)*8,
                "trace_compressed_bytes":trace_bytes,
                "scope":"112B is active calibration payload only; full30 audit metadata, Python containers, temporary vectors, head arrays, and serialized logs are additional."}}
