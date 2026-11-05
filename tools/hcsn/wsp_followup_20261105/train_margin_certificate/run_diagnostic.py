"""TRAIN-only bounded search for a rigorously checked necessary-system witness."""
import argparse
import ctypes
import datetime
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import resource
import signal
import sys
import time
import traceback
import numpy as np
from scipy.optimize import minimize
from certificate import equal_head_feasibility, exact_witness, f, pack
from io_helpers import canonical, read, save, sha


def environment():
    try:
        rounding = int(ctypes.CDLL(None).fegetround())
    except (AttributeError, OSError):
        rounding = None
    smallest = np.float64(float.fromhex("0x0.0000000000001p-1022"))
    return {"python": sys.version, "numpy": np.__version__, "scipy": importlib.metadata.version("scipy"),
            "platform": platform.platform(), "float_format": float.__getformat__("double"),
            "fegetround_observed": rounding,
            "FE_TONEAREST_zero_is_platform_assumption": True,
            "gradual_underflow_probe": bool(np.float64(np.finfo(np.float64).tiny)*np.float64(.5)>0
                                             and smallest*np.float64(1)==smallest and smallest>0),
            "rounding_probes_pass": bool(np.float64(1)+np.float64(2**-53)==1
                                           and np.float64(1+2**-52)+np.float64(2**-53)==1+2**-51),
            "scope": "observations of this execution, not a proof about every NumPy platform"}


def source_checks(protocol, args):
    roots = {"new": Path(__file__).parent, "science": args.science, "joint": args.joint, "inputs": args.inputs}
    for group, files in protocol["files"].items():
        for name, expected in files.items():
            assert sha((roots[group]/name).read_bytes()) == expected, (group, name)


def search(original, rows, configuration):
    started = time.process_time()
    count = len(rows)
    if not count:
        return np.zeros(0), {"status": "EMPTY_NECESSARY_SYSTEM", "calls": 0, "cpu_seconds": 0.0}
    matrix = np.zeros((count, 147), dtype=np.float64)
    for i, row in enumerate(rows):
        a, b = row["target_action"]-1, row["competitor_action"]-1
        matrix[i, 49*a:49*(a+1)] = row["hidden"]
        matrix[i, 49*b:49*(b+1)] = -np.asarray(row["hidden"])
    center = np.asarray(original).reshape(-1)
    rhs = -(matrix@center)  # numerical search only; proof recomputes exact -A*C
    best = np.zeros(count)
    best_direction_score = -math.inf
    calls, trace = 0, []
    class SearchLimit(Exception):
        pass
    def objective(y):
        nonlocal best, best_direction_score, calls
        if time.process_time()-started >= configuration["per_fit_search_cpu_seconds"]:
            raise SearchLimit("fixed per-fit dual-search CPU cap")
        if not np.isfinite(y).all() or np.any(y<0):
            raise ArithmeticError("invalid numerical dual point")
        vector = matrix.T@y
        linear = float(rhs@y)
        norm = float(np.linalg.norm(vector))
        direction_score = linear/norm if norm>0 else (math.inf if linear>0 else -math.inf)
        if direction_score>best_direction_score:
            best_direction_score, best = direction_score, y.copy()
        value = .5*float(vector@vector)-linear
        gradient = matrix@vector-rhs
        if not math.isfinite(value) or not np.isfinite(gradient).all():
            raise ArithmeticError("nonfinite dual-search arithmetic")
        calls += 1
        if calls%50==0:
            trace.append({"call": calls, "objective": value, "direction_score": direction_score if math.isfinite(direction_score) else None,
                          "zero_numerical_vector_positive_linear": norm==0 and linear>0,
                          "cpu_seconds": time.process_time()-started})
        return value, gradient
    record = {"method": "L-BFGS-B nonnegative smooth minimum-distance dual",
              "optimizer_status_is_not_a_certificate": True}
    try:
        result = minimize(objective, np.zeros(count), jac=True, method="L-BFGS-B",
                          bounds=[(0, None)]*count, options=configuration["options"])
        record.update(status="SOLVER_RETURNED", solver_success=bool(result.success),
                      solver_status=int(result.status), solver_message=str(result.message),
                      iterations=int(result.nit), evaluations=int(result.nfev))
    except (SearchLimit, ArithmeticError, FloatingPointError) as error:
        record.update(status="SEARCH_CAPPED_OR_NUMERIC_FAILURE", error_type=type(error).__name__, error=str(error))
    largest = float(best.max()) if len(best) else 0.
    if largest>0:
        best = best/largest
    record.update(calls=calls, trace=trace, cpu_seconds=time.process_time()-started,
                  normalization="one final binary64 division by maximum component; resulting values are exact witness inputs",
                  best_direction_score=None if not math.isfinite(best_direction_score) else best_direction_score,
                  nonzero_multipliers=int(np.count_nonzero(best)), multiplier_sha256=sha(best.tobytes()))
    return best, record


def main(args):
    started, wall = time.process_time(), time.perf_counter()
    out = args.output
    out.mkdir(exist_ok=False)
    protocol = read(args.protocol)
    assert protocol["status"] == "FROZEN_BEFORE_TRAIN_DIAGNOSTIC"
    limits = protocol["resources"]["producer"]
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]+2))
    resource.setrlimit(resource.RLIMIT_AS, (protocol["resources"]["address_space_bytes"],)*2)
    def limit(*unused):
        raise TimeoutError("frozen producer resource limit")
    signal.signal(signal.SIGXCPU, limit)
    signal.signal(signal.SIGALRM, limit)
    signal.alarm(limits["wall_seconds"])
    source_checks(protocol, args)
    save(out/"STARTED.json", {"protocol_sha256": sha(args.protocol.read_bytes()),
         "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "environment": environment(),
         "new_validation_or_test_files_accessed": False, "held_out_rows_used_or_scored": False,
         "archived_shared_fit_data_container_read_in_full": True,
         "legacy_loader_initializes_truth_law_then_discards_it": True,
         "no_candidate_model_created_or_saved": True})
    sys.path.insert(0, str(args.science))
    import planning as p
    ctx = p.load_context(args.joint)
    # Legacy definitions initialize a truth-law object, but this diagnostic
    # never queries it. Targets exclusively reuse compile_own and C's tables.
    del ctx.law, ctx.truth_tables
    reports = []
    try:
        for fit in protocol["fits"]:
            fit_start = time.process_time()
            expected = protocol["expected"][str(fit)]
            candidate = read(args.science/f"execution_r1/run/fit_{fit}_CANDIDATES.json.gz")
            model = read(args.science/f"execution_r1/run/models/fit_{fit}_C.json.gz")
            original = ctx.head(model)[:3]
            policy = ctx.NumpyPolicy(model)
            data = read(args.inputs/f"fit_{fit}/data/fit_{fit}_data.json")
            public_worlds = ctx.public_unique(data["train"]["rows"])
            assert len(public_worlds)==64
            Hs, Ys, Ws, constraints, worlds = [], [], [], [], []
            alias_classes, alias_conflicts, alias_witness = {}, [], None
            row_index = 0
            for world_index, public in enumerate(public_worlds):
                saved_world = candidate["training_worlds"][world_index]
                schedule = {key: public[key] for key in protocol["schedule_fields"]}
                assert p.sha(p.canonical(schedule).encode())==saved_world["schedule_sha256"]
                assert public["id"]==saved_world["world_id"]
                states = p.enumerate_states(ctx, public, True, protocol["reconstruction"]["max_full_states_per_world"])
                compiled, identity, _ = p.compile_own(ctx, policy, public, protocol["reconstruction"]["max_markov_states_per_world"])
                assert identity["table_sha256"]==saved_world["own_bellman"]["table_sha256"]
                world_policy = p.WorldPolicy(ctx, public, policy, compiled)
                eligible = sum(any(ctx.legal(public, state)[1:4]) for state in states.values())
                assert len(states)==saved_world["full_states"] and eligible==saved_world["continuation_eligible_states"]
                for state_index, state in enumerate(states.values()):
                    hidden, bank = world_policy.feature(state)
                    if hidden.shape!=(49,) or hidden[-1]!=1 or not np.isfinite(hidden).all() or np.any(abs(hidden)>1):
                        raise ArithmeticError("unexpected fixed hidden representation")
                    row = compiled["rows"][p.markov_key(state)]
                    probability = float(np.clip(row["belief"], 1e-12, 1-1e-12))
                    mask = np.asarray(row["legal"][1:4], dtype=float)
                    count = mask.sum()
                    weights = mask/(64*eligible*count) if count else mask
                    Hs.append(hidden)
                    Ys.append([*row["q"][1:4], np.log(probability)-np.log1p(-probability)])
                    Ws.append([*weights, 1/(64*len(states))])
                    assert abs(bank-row["belief"])<=2e-12
                    target = row["action"]
                    state_record = {"global_row_index": row_index, "world_index": world_index,
                        "state_index": state_index, "world_id": public["id"], "state": state,
                        "state_sha256": sha(p.canonical(state).encode()), "hidden": hidden.tolist(),
                        "hidden_sha256": sha(hidden.tobytes()), "target_action": target,
                        "teacher_q": row["q"], "legal": row["legal"],
                        "teacher_table_sha256": identity["table_sha256"]}
                    alias_key = hidden.tobytes()+bytes(row["legal"])
                    first = alias_classes.get(alias_key)
                    if first is None:
                        alias_classes[alias_key] = state_record
                    elif first["target_action"] != target:
                        alias_conflicts.append({"first_global_row_index": first["global_row_index"],
                            "conflicting_global_row_index": row_index,
                            "first_target_action": first["target_action"], "conflicting_target_action": target,
                            "hidden_sha256": state_record["hidden_sha256"], "legal": row["legal"]})
                        if alias_witness is None:
                            alias_witness = [first, state_record]
                    others = [a for a in (1,2,3) if row["legal"][a] and a!=target]
                    if target in (1,2,3):
                        assert len(others)<=1
                        for competitor in others:
                            constraints.append({**state_record, "competitor_action": competitor})
                    row_index += 1
                worlds.append({"world_index": world_index, "world_id": public["id"], "public": public,
                     "schedule_sha256": saved_world["schedule_sha256"], "full_states": len(states),
                     "continuation_eligible_states": eligible, "teacher_table_sha256": identity["table_sha256"]})
            H, Y, W = np.asarray(Hs), np.asarray(Ys), np.asarray(Ws)
            del Hs, Ys, Ws
            hashes = {name+"_sha256": sha(array.tobytes()) for name,array in (("H",H),("Y",Y),("W",W))}
            assert len(H)==expected["rows"] and all(hashes[k]==expected[k] for k in hashes)
            reconstruction = {"fit": fit, "rows": len(H), "world_count": len(worlds), "worlds": worlds,
                **hashes, "all_original_identities_exact": True, "constraints": len(constraints),
                "constraint_rows_sha256": sha(canonical(constraints).encode()),
                "cpu_seconds": time.process_time()-fit_start}
            save(out/f"fit_{fit}_RECONSTRUCTION.json.gz", reconstruction)
            if alias_witness is not None:
                for row in alias_witness:
                    a=row["target_action"]
                    row["teacher_gap_exact"] = pack(f(row["teacher_q"][a]) - max(
                        f(value) for j,(value,legal) in enumerate(zip(row["teacher_q"],row["legal"])) if legal and j!=a))
            aliases = {"fit": fit, "full_rows": row_index, "exact_feature_and_mask_classes": len(alias_classes),
                       "conflicting_rows_against_first_in_class": len(alias_conflicts),
                       "all_conflict_indices": alias_conflicts, "first_complete_witness": alias_witness,
                       "fixed_representation_deterministic_four_output_argmax_incompatible": alias_witness is not None,
                       "scope": "exact hidden binary64 bytes and identical legal mask; not a task-value impossibility"}
            alias_identity = save(out/f"fit_{fit}_ALIASES.json.gz", aliases)
            del alias_classes, alias_conflicts, alias_witness
            del H, Y, W
            feasibility = equal_head_feasibility(original)
            if feasibility["weak_system_feasible"]:
                multipliers = np.zeros(len(constraints))
                search_record = {"status": "SKIPPED_ANALYTIC_WEAK_FEASIBILITY", "cpu_seconds": 0.,
                                 "reason": "exact common continuation row lies inside the true Frobenius ball"}
            else:
                multipliers, search_record = search(original, constraints, protocol["search"])
            witness = [{**row, "multiplier": float(y)} for row,y in zip(constraints,multipliers) if y>0]
            witness_identity = save(out/f"fit_{fit}_WITNESS.json.gz", witness)
            proof = exact_witness(original, witness)
            status = ("WEAK_RELAXATION_FEASIBLE" if feasibility["weak_system_feasible"] else
                      "F64_NECESSARY_SYSTEM_INFEASIBLE" if proof["F64_necessary_relaxation"]["strict_separation"] else
                      "IDEAL_REAL_ONLY_INFEASIBLE" if proof["ideal_real"]["strict_separation"] else "UNKNOWN")
            report = {"fit": fit, "status": status, "rows": row_index, "constraints": len(constraints),
                "identity_reconstruction_passed": True, "equal_head": feasibility,
                "exact_alias_incompatible": aliases["fixed_representation_deterministic_four_output_argmax_incompatible"],
                "aliases": alias_identity,
                "search": search_record, "witness": witness_identity, "exact_certificate": proof,
                "fit_cpu_seconds": time.process_time()-fit_start,
                "no_task_value_or_generalization_qualification": True}
            save(out/f"fit_{fit}_RESULT.json.gz", report)
            reports.append(report)
            print(canonical({"fit":fit,"status":status,"constraints":len(constraints),"cpu_seconds":time.process_time()-started}), flush=True)
        source_checks(protocol,args)
        result = {"schema":"hepta.training-continuation-necessary-system.v1", "completed":True,
            "fits": {str(row["fit"]): {k:row[k] for k in ("status","rows","constraints")} for row in reports},
            "all_reconstruction_identities_exact": all(row["identity_reconstruction_passed"] for row in reports),
            "full_rows":sum(row["rows"] for row in reports), "worlds":320,
            "ideal_real_infeasible_fits":[row["fit"] for row in reports if row["exact_certificate"]["ideal_real"]["strict_separation"]],
            "conditional_F64_infeasible_fits":[row["fit"] for row in reports if row["exact_certificate"]["F64_necessary_relaxation"]["strict_separation"]],
            "weak_relaxation_feasible_fits":[row["fit"] for row in reports if row["equal_head"]["weak_system_feasible"]],
            "unknown_fits":[row["fit"] for row in reports if row["status"]=="UNKNOWN"],
            "exact_alias_incompatible_fits":[row["fit"] for row in reports if row["exact_alias_incompatible"]],
            "new_validation_or_test_files_accessed":False,"held_out_rows_used_or_scored":False,
            "archived_shared_fit_data_container_read_in_full":True,
            "legacy_loader_initializes_truth_law_then_discards_it":True,
            "candidate_model_created_or_saved":False,
            "new_scientific_efficacy_qualified":False,"production_qualified":False,
            "scope":"specified zero-margin continuation comparisons on frozen TRAIN full-state rows; off-policy states included; not a task-value impossibility or full-network theorem",
            "internal_cpu_seconds_before_final_write":time.process_time()-started,
            "internal_wall_seconds_before_final_write":time.perf_counter()-wall}
        save(out/"RESULTS.json",result)
    except BaseException as error:
        save(out/"FAILED.json",{"type":type(error).__name__,"error":str(error),"traceback":traceback.format_exc(),
             "completed_fits":[row["fit"] for row in reports],"planned_fits":protocol["fits"],"all_partial_records_retained":True,
             "cpu_seconds":time.process_time()-started,"wall_seconds":time.perf_counter()-wall})
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for key in ("science","joint","inputs","protocol","output"):
        parser.add_argument("--"+key,type=Path,required=True)
    args=parser.parse_args()
    with np.errstate(over="raise",invalid="raise",divide="raise"):
        main(args)
