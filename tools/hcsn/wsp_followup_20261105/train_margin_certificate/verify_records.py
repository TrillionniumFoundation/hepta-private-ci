"""Independent Fraction arithmetic plus replay of every saved witness state.

This never calls the numerical search or the producer's certificate function.
It reuses the pinned deployed feature and own-law program definitions to bind
certificate rows to actual TRAIN sources, without any held-out task scoring.
"""
import argparse
from fractions import Fraction
import math
from pathlib import Path
import resource
import signal
import sys
import time
import traceback
import numpy as np
from io_helpers import canonical, read, raw_bytes, save, sha


def rational(x):
    if isinstance(x,bool) or not math.isfinite(float(x)):
        raise ValueError("invalid binary64 value")
    return Fraction.from_float(float(x))


def stored(x):
    return Fraction(int(x["numerator"]),int(x["denominator"]))


def independent_math(center, witness, report):
    c=[rational(x) for row in center for x in row]
    radius_squared=sum((x*x for x in c),Fraction())/4
    common=[sum((c[a*49+j] for a in range(3)),Fraction())/3 for j in range(49)]
    distance=sum(((c[a*49+j]-common[j])**2 for a in range(3) for j in range(49)),Fraction())
    equal=report["equal_head"]
    assert stored(equal["distance_squared"])==distance and stored(equal["radius_squared"])==radius_squared
    assert equal["weak_system_feasible"]==(distance<=radius_squared)
    assert equal["first_argmax_realization_qualified"] is False
    upper=math.isqrt(radius_squared.numerator//radius_squared.denominator)
    if upper*upper<radius_squared:
        upper+=1
    assert upper*upper>=radius_squared
    assert 49*max(abs(x)+upper for x in c)<2**1000
    u=Fraction(1,2**53)
    gamma=98*u/(1-98*u)
    error=[gamma*(sum(map(abs,c[49*a:49*(a+1)]),Fraction())+49*upper)
           +98*Fraction(1,2**1074)/(1-98*u) for a in range(3)]
    v=[Fraction() for _ in range(147)]
    offset=Fraction()
    for row in witness:
        y=rational(row["multiplier"])
        assert y>0
        a,b=row["target_action"]-1,row["competitor_action"]-1
        assert a in range(3) and b in range(3) and a!=b
        h=[rational(x) for x in row["hidden"]]
        assert len(h)==49 and h[-1]==1 and all(abs(x)<=1 for x in h)
        for j,x in enumerate(h):
            v[49*a+j]+=y*x
            v[49*b+j]-=y*x
        offset+=y*(error[a]+error[b])
    d=-sum((a*b for a,b in zip(v,c)),Fraction())
    squared=sum((x*x for x in v),Fraction())
    right=radius_squared*squared
    proof=report["exact_certificate"]
    assert stored(proof["radius_squared"])==radius_squared
    assert stored(proof["radius_upper"])==upper
    assert [stored(x) for row in proof["dual_vector"] for x in row]==v
    assert stored(proof["dual_vector_squared_norm"])==squared
    assert [stored(x) for x in proof["per_head_F64_absolute_error_bound"]]==error
    assert stored(proof["weighted_F64_error_bound"])==offset
    assert proof["nonzero_multipliers"]==proof["rows"]==len(witness)
    flags=[]
    for name,value in (("ideal_real",d),("F64_necessary_relaxation",d-offset)):
        expected=value>0 and value*value>right
        saved=proof[name]
        assert stored(saved["d"])==value and saved["d_positive"]==(value>0)
        assert stored(saved["left_squared"])==value*value and stored(saved["right_squared"])==right
        assert saved["strict_separation"]==expected
        flags.append(expected)
    status=("WEAK_RELAXATION_FEASIBLE" if distance<=radius_squared else
            "F64_NECESSARY_SYSTEM_INFEASIBLE" if flags[1] else
            "IDEAL_REAL_ONLY_INFEASIBLE" if flags[0] else "UNKNOWN")
    assert report["status"]==status
    if distance<=radius_squared:
        assert not any(flags) and not witness
    return {"status":status,"ideal_real_infeasible":flags[0],"conditional_F64_infeasible":flags[1],
            "weak_relaxation_feasible":distance<=radius_squared,"witness_rows":len(witness)}


def main(args):
    started,wall=time.process_time(),time.perf_counter()
    args.output.mkdir(exist_ok=False)
    protocol=read(args.protocol)
    limits=protocol["resources"]["verifier"]
    resource.setrlimit(resource.RLIMIT_CPU,(limits["cpu_seconds"],limits["cpu_seconds"]+2))
    resource.setrlimit(resource.RLIMIT_AS,(protocol["resources"]["address_space_bytes"],)*2)
    def limit(*unused):
        raise TimeoutError("frozen verifier resource cap")
    signal.signal(signal.SIGALRM,limit)
    signal.signal(signal.SIGXCPU,limit)
    signal.alarm(limits["wall_seconds"])
    roots={"new":Path(__file__).parent,"science":args.science,"joint":args.joint,"inputs":args.inputs}
    for group,files in protocol["files"].items():
        for name,expected in files.items():
            assert sha((roots[group]/name).read_bytes())==expected
    sys.path.insert(0,str(args.science))
    import planning as p
    ctx=p.load_context(args.joint)
    del ctx.law,ctx.truth_tables
    reports={}
    try:
        for fit in protocol["fits"]:
            result=read(args.run/f"fit_{fit}_RESULT.json.gz")
            reconstruction=read(args.run/f"fit_{fit}_RECONSTRUCTION.json.gz")
            source=read(args.science/f"execution_r1/run/fit_{fit}_CANDIDATES.json.gz")
            for name in ("H_sha256","Y_sha256","W_sha256","rows"):
                assert reconstruction[name]==source[name]==protocol["expected"][str(fit)][name]
            assert reconstruction["all_original_identities_exact"] and reconstruction["world_count"]==64
            assert result["rows"]==reconstruction["rows"] and result["constraints"]==reconstruction["constraints"]
            witness_path=args.run/f"fit_{fit}_WITNESS.json.gz"
            raw=raw_bytes(witness_path)
            assert sha(raw)==result["witness"]["sha256"] and len(raw)==result["witness"]["bytes"]
            witness=read(witness_path)
            alias_path=args.run/f"fit_{fit}_ALIASES.json.gz"
            alias_bytes=raw_bytes(alias_path)
            assert len(alias_bytes)==result["aliases"]["bytes"] and sha(alias_bytes)==result["aliases"]["sha256"]
            aliases=read(alias_path)
            alias_witness=aliases["first_complete_witness"] or []
            alias_flag=bool(alias_witness)
            assert aliases["fixed_representation_deterministic_four_output_argmax_incompatible"]==alias_flag==result["exact_alias_incompatible"]
            assert aliases["conflicting_rows_against_first_in_class"]==len(aliases["all_conflict_indices"])
            assert bool(aliases["all_conflict_indices"])==alias_flag
            if alias_flag:
                assert len(alias_witness)==2
                first,second=alias_witness
                assert np.asarray(first["hidden"],dtype=np.float64).tobytes()==np.asarray(second["hidden"],dtype=np.float64).tobytes()
                assert first["legal"]==second["legal"] and first["target_action"]!=second["target_action"]
                for item in alias_witness:
                    a=item["target_action"]
                    gap=rational(item["teacher_q"][a])-max(rational(q) for j,(q,valid) in enumerate(zip(item["teacher_q"],item["legal"])) if valid and j!=a)
                    assert stored(item["teacher_gap_exact"])==gap and gap>=0
                assert aliases["all_conflict_indices"][0]["first_global_row_index"]==first["global_row_index"]
                assert aliases["all_conflict_indices"][0]["conflicting_global_row_index"]==second["global_row_index"]
            model=read(args.science/f"execution_r1/run/models/fit_{fit}_C.json.gz")
            policy=ctx.NumpyPolicy(model)
            data=read(args.inputs/f"fit_{fit}/data/fit_{fit}_data.json")
            worlds=ctx.public_unique(data["train"]["rows"])
            grouped={}
            seen=set()
            for row in witness:
                identity=(row["world_index"],row["state_index"],row["target_action"],row["competitor_action"])
                assert identity not in seen
                seen.add(identity)
                grouped.setdefault(row["world_index"],[]).append(row)
            for row in alias_witness:
                grouped.setdefault(row["world_index"],[]).append(row)
            for world_index,public in enumerate(worlds):
                old=source["training_worlds"][world_index]
                regenerated=reconstruction["worlds"][world_index]
                assert public==regenerated["public"] and public["id"]==old["world_id"]==regenerated["world_id"]
                assert regenerated["teacher_table_sha256"]==old["own_bellman"]["table_sha256"]
                assert regenerated["full_states"]==old["full_states"]
                schedule={key:public[key] for key in protocol["schedule_fields"]}
                assert sha(p.canonical(schedule).encode())==old["schedule_sha256"]==regenerated["schedule_sha256"]
                if world_index not in grouped:
                    continue
                compiled,identity,_=p.compile_own(ctx,policy,public,protocol["reconstruction"]["max_markov_states_per_world"])
                assert identity["table_sha256"]==old["own_bellman"]["table_sha256"]
                states=list(p.enumerate_states(ctx,public,True,protocol["reconstruction"]["max_full_states_per_world"]).values())
                features=p.WorldPolicy(ctx,public,policy,compiled)
                for row in grouped[world_index]:
                    state=states[row["state_index"]]
                    assert p.canonical(state)==p.canonical(row["state"])
                    assert sha(p.canonical(state).encode())==row["state_sha256"]
                    hidden,_=features.feature(state)
                    assert hidden.tobytes()==np.asarray(row["hidden"],dtype=np.float64).tobytes()
                    assert sha(hidden.tobytes())==row["hidden_sha256"]
                    teacher=compiled["rows"][p.markov_key(state)]
                    assert teacher["q"]==row["teacher_q"] and teacher["legal"]==row["legal"]
                    assert teacher["action"]==row["target_action"]
                    assert teacher["legal"][teacher["action"]]
                    assert int(np.where(np.asarray(teacher["legal"]),np.asarray(teacher["q"]),-np.inf).argmax())==teacher["action"]
                    if "competitor_action" in row:
                        assert row["target_action"] in (1,2,3) and row["competitor_action"] in (1,2,3)
                        assert row["competitor_action"]!=row["target_action"] and teacher["legal"][row["competitor_action"]]
                    assert row["teacher_table_sha256"]==identity["table_sha256"]
            reports[str(fit)]=independent_math(ctx.head(model)[:3],witness,result)
            reports[str(fit)]["witness_worlds_reexecuted"]=len(grouped)
            reports[str(fit)]["exact_alias_incompatible"]=alias_flag
            save(args.output/f"fit_{fit}_VERIFIED.json",reports[str(fit)])
            print(canonical({"fit":fit,"status":reports[str(fit)]["status"],"independent_verification":"PASS"}),flush=True)
        overall=read(args.run/"RESULTS.json")
        assert overall["completed"] and overall["full_rows"]==144397 and overall["worlds"]==320
        assert overall["all_reconstruction_identities_exact"]
        assert set(overall["fits"])==set(reports)
        for fit,record in reports.items():
            assert overall["fits"][fit]["status"]==record["status"]
        for key,field in (("ideal_real_infeasible_fits","ideal_real_infeasible"),
                          ("conditional_F64_infeasible_fits","conditional_F64_infeasible"),
                          ("weak_relaxation_feasible_fits","weak_relaxation_feasible")):
            assert overall[key]==[int(fit) for fit,row in reports.items() if row[field]]
        assert overall["unknown_fits"]==[int(fit) for fit,row in reports.items() if row["status"]=="UNKNOWN"]
        assert overall["exact_alias_incompatible_fits"]==[int(fit) for fit,row in reports.items() if row["exact_alias_incompatible"]]
        assert not any(overall[k] for k in ("new_validation_or_test_files_accessed","held_out_rows_used_or_scored","candidate_model_created_or_saved", "new_scientific_efficacy_qualified","production_qualified"))
        save(args.output/"RESULTS.json",{"passed":True,"fits":reports,"protocol_sha256":sha(args.protocol.read_bytes()),
            "producer_result_sha256":sha((args.run/"RESULTS.json").read_bytes()),
            "independent_Fraction_arithmetic":True,"all_saved_witness_features_and_own_Q_reexecuted":True,
            "full_H_Y_W_reconstruction_hashes_checked_against_frozen_records":True,
            "full_H_Y_W_not_independently_regenerated_by_this_verifier":True,
            "new_validation_or_test_files_accessed":False,"held_out_rows_used_or_scored":False,
            "archived_shared_fit_data_container_read_in_full":True,
            "candidate_model_created_or_saved":False,
            "cpu_seconds_before_final_write":time.process_time()-started,"wall_seconds_before_final_write":time.perf_counter()-wall})
    except BaseException as error:
        save(args.output/"FAILED.json",{"type":type(error).__name__,"error":str(error),"traceback":traceback.format_exc(),
             "verified_fits":list(reports),"all_partial_records_retained":True})
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for key in ("science","joint","inputs","protocol","run","output"):
        parser.add_argument("--"+key,type=Path,required=True)
    main(parser.parse_args())
