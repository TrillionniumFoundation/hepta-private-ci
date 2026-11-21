"""Post-run descriptive arithmetic only; never imports a model or optimizer."""
from pathlib import Path
from fractions import Fraction
import datetime
import gzip
import hashlib
import json
import math
import statistics

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"v2/attempt001"
FITS=(11,23,37,53,71)


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix==".gz" else raw)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def rational(doc):return Fraction(int(doc["numerator"]),int(doc["denominator"]))


def main():
    result=read(OUT/"RESULTS.json")
    fits=[];action_summary={};state_count=0;max_normalization=0.
    family_cpu=0.;program_cpu=0.;solver_cpu=0.
    for fit in FITS:
        record=read(ROOT/f"attempt001/fit_{fit}_FAMILY.json.gz")
        p=record["program"]
        norms={}
        for arm in ("R","P","RP"):
            norm=record["models"][arm]["original_Q_radius_norm"]
            delta=rational(norm["delta_squared"])
            declared=rational(norm["original_Q_declared_squared"])
            safe=rational(norm["safe_radius_squared"])
            norms[arm]=dict(delta_L2=math.sqrt(float(delta)),delta_squared=float(delta),
                exact_delta_squared=norm["delta_squared"],
                original_Q_declared_squared=norm["original_Q_declared_squared"],
                safe_radius_squared=norm["safe_radius_squared"],
                fraction_original_squared_budget=float(delta/declared),
                fraction_safe_squared_budget=float(delta/safe),exact_inequality=delta<=safe<=declared)
        selected=read(OUT/f"fit_{fit}_SELECTION.json.gz")
        family_cpu+=record["CPU_seconds"];program_cpu+=p["CPU_seconds"]
        solver_cpu+=p["readout_solver"]["cpu_seconds"]
        fits.append(dict(fit=fit,selected_units=p["selected_units"],
            actual_changed_coordinates=p["actual_changed_coordinates"],
            intended_std=p["intended_preactivation_std"],actual_std=p["actual_preactivation_std"],
            radius=p["radius"],norms=norms,representation_scaling=p["representation_scaling"],
            alpha=selected["selected_alpha"],selection_decision=selected["decision"],
            family_CPU_seconds=record["CPU_seconds"],program_CPU_seconds=p["CPU_seconds"],
            readout_solver_CPU_seconds=p["readout_solver"]["cpu_seconds"],
            max_KKT_residual=p["readout_solver"]["kkt_stationarity_linf"],
            restore=result["restoration"][str(fit)]))
        action_summary[str(fit)]={}
        for domain in ("iid","ood"):
            block=read(OUT/f"confirmation_{fit}_{domain}.json.gz")
            comparisons={name:dict(raw_state_count=0,different_actions=0,worlds_with_action_difference=0,
                worlds_with_C_occupied_action_difference=0,worlds_with_utility_difference=0,
                omega_disagreement=[],C_normalized_occupancy_disagreement=[],utility_delta=[])
                for name in ("R_minus_C","RP_minus_P")}
            for row in block["records"]:
                graph=read(OUT/row["graph"]);n=len(graph["states"])
                state_count+=n;max_normalization=max(max_normalization,row["oracle_checks"]["probability_error"])
                occupancy=graph["C_occupancy"];total=math.fsum(occupancy)
                for key,(left,right) in {"R_minus_C":("R","C"),"RP_minus_P":("RP","P")}.items():
                    target=comparisons[key]
                    differences=[a!=b for a,b in zip(graph["arm_actions"][left],graph["arm_actions"][right])]
                    count=sum(differences)
                    occupied=math.fsum(o for d,o in zip(differences,occupancy) if d)
                    target["raw_state_count"]+=n;target["different_actions"]+=count
                    target["worlds_with_action_difference"]+=bool(count)
                    target["worlds_with_C_occupied_action_difference"]+=occupied>0.
                    target["omega_disagreement"].append(math.fsum(w for d,w in zip(differences,graph["omega"]) if d))
                    target["C_normalized_occupancy_disagreement"].append(occupied/total)
                    delta=row["arms"][left]["utility"]-row["arms"][right]["utility"]
                    target["utility_delta"].append(delta)
                    target["worlds_with_utility_difference"]+=delta!=0.
            for target in comparisons.values():
                target["mean_omega_disagreement"]=statistics.fmean(target["omega_disagreement"])
                target["mean_C_occupancy_disagreement"]=statistics.fmean(target["C_normalized_occupancy_disagreement"])
                target["mean_utility_delta"]=statistics.fmean(target["utility_delta"])
                target["maximum_absolute_world_utility_delta"]=max(abs(v) for v in target["utility_delta"])
            action_summary[str(fit)][domain]=comparisons
    # These values summarize existing scalar records. They are not additional tests.
    exploratory={}
    for domain in ("iid","ood"):
        m={arm:record["mean"] for arm,record in result["summary"][domain].items()}
        exploratory[domain]=dict(S_minus_C=m["S"]-m["C"],B_minus_C=m["B"]-m["C"],
            Q_minus_C=m["Q"]-m["C"],BQ_minus_C=m["BQ"]-m["C"],
            Q_fraction_of_mean_BQ_gain=(m["Q"]-m["C"])/(m["BQ"]-m["C"]),
            BQ_minus_Q=m["BQ"]-m["Q"],BQ_minus_J_own=m["BQ"]-m["J_own"],
            BQ_minus_B_minus_Q_plus_C=m["BQ"]-m["B"]-m["Q"]+m["C"],
            RP_minus_P=m["RP"]-m["P"],R_minus_C=m["R"]-m["C"],
            K_minus_C=m["K"]-m["C"])
    summary=dict(schema="hepta.causal-rescue.saved-record-descriptives.v1",
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        result_sha256=sha(OUT/"RESULTS.json"),source_script_sha256=sha(Path(__file__)),
        scope="Existing frozen scalar/model-certificate/action records only; no model execution, optimization, CI refit or new significance claim",
        model_calls=0,optimizer_calls=0,fits=fits,action_comparisons=action_summary,
        confirmation_states=state_count,max_graph_normalization_error=max_normalization,
        exploratory=exploratory,family_construction_CPU_seconds=family_cpu,
        program_CPU_seconds=program_cpu,readout_solver_CPU_seconds=solver_cpu)
    with (ROOT/"SAVED_RECORD_DIAGNOSTICS.json").open("x") as stream:
        json.dump(summary,stream,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps(dict(fits=[{k:v for k,v in f.items() if k in
        ("fit","selected_units","actual_std","representation_scaling","alpha")} for f in fits],
        exploratory=exploratory,confirmation_states=state_count,
        family_construction_CPU_seconds=family_cpu,readout_solver_CPU_seconds=solver_cpu),indent=2))


if __name__=="__main__":main()
