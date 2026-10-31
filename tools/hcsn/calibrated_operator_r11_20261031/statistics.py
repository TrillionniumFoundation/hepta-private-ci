"""Paired independent-fit inference and explicitly priced complete CPU costs."""
import numpy as np
from scipy.stats import t


def interval(values,comparisons=1):
    values=np.asarray(values,float)
    mean=float(values.mean())
    se=float(values.std(ddof=1)/np.sqrt(len(values)))
    half=float(t.ppf(1-.05/(2*comparisons),len(values)-1))*se
    return dict(mean=mean,lower=mean-half,upper=mean+half,seed_values=values.tolist(),
                independent_fits=len(values),familywise_comparisons=comparisons)


def analyze(rows,freeze,protocol):
    output=dict(scope=protocol["scope"],seeds=protocol["seeds"],splits={},
                energy_measured=False,unstructured_neural_dp_learning_claim=False,
                finite_ctmc_is_not_continuum_claim=True)
    for split in ("test","ood"):
        subset=[r for r in rows if r["split"]==split]
        arm_rows={arm:[r for r in subset if r["arm"]==arm] for arm in protocol["arms"]+["fitted_dp"]}
        summary={}
        for arm,data in arm_rows.items():
            item=dict(episodes=len(data),utility=float(np.mean([r["score"]["utility"] for r in data])),
                reward=float(np.mean([r["score"]["reward"] for r in data])),
                completed_jobs=float(np.mean([r["score"]["completed_jobs"] for r in data])),
                correct_jobs=float(np.mean([r["score"]["correct_jobs"] for r in data])),
                mean_reads=float(np.mean([r["counts"]["READ"] for r in data])),
                mean_skips=float(np.mean([r["counts"]["SKIP"] for r in data])),
                mean_stops=float(np.mean([r["counts"]["STOP"] for r in data])))
            if arm!="fitted_dp":
                item.update(runtime_cpu_seconds=float(np.mean([r["runtime_cpu_seconds"] for r in data])),
                    runtime_wall_seconds=float(np.mean([r["runtime_wall_seconds"] for r in data])),
                    max_native_q_error=max(r["native_q_error"] for r in data),
                    max_native_feature_error=max(r["native_feature_error"] for r in data),
                    max_target_q_error=max(r["max_target_q_error"] for r in data),
                    mean_decision_regret=sum(r["regret"] for r in data)/sum(r["decisions"] for r in data),
                    mean_episode_regret=float(np.mean([r["regret"] for r in data])),
                    stop_max_absolute=max(r["stop_max_absolute"] for r in data))
            summary[arm]=item
        contrasts={}
        lookup={(r["seed"],r["session"],r["arm"]):r for r in subset}
        for contrast in protocol["primary_contrasts"]:
            left,right=contrast.split("-")
            deltas=[]
            for seed in protocol["seeds"]:
                paired=[(r,lookup[(seed,r["session"],right)]) for r in arm_rows[left] if r["seed"]==seed]
                deltas.append(float(np.mean([a["score"]["utility"]-b["score"]["utility"] for a,b in paired])))
            contrasts[contrast]=interval(deltas,len(protocol["primary_contrasts"]))
        costs=[]
        for price in protocol["cpu_prices"]:
            for amortization in protocol["amortization_sessions"]:
                deltas=[]
                for seed in protocol["seeds"]:
                    fit=freeze["costs"][str(seed)]["fit_cpu_seconds"]
                    paired=[(r,lookup[(seed,r["session"],"ordinary_value")])
                            for r in arm_rows["analytic_value"] if r["seed"]==seed]
                    deltas.append(float(np.mean([a["score"]["utility"]-b["score"]["utility"]
                        -price*(a["runtime_cpu_seconds"]-b["runtime_cpu_seconds"]
                        +(fit["analytic"]-fit["ordinary"])/amortization) for a,b in paired])))
                costs.append(dict(cpu_price=price,amortization_sessions=amortization,
                                  contrast=interval(deltas,3)))
        changed=sum(r["decision_states"]!=lookup[(r["seed"],r["session"],"analytic_constant")]["decision_states"]
                    for r in arm_rows["analytic_value"])
        selected=next(x["contrast"] for x in costs if x["cpu_price"]==.01 and x["amortization_sessions"]==1000)
        g=summary["grid"]
        output["splits"][split]=dict(arms=summary,contrasts=contrasts,all_cost_contrasts=costs,
            causal_state_intervention_changed_sessions=changed,
            calibration_pass=g["mean_decision_regret"]<=.001 and g["max_target_q_error"]<=.004
                and g["max_native_q_error"]<=1e-7 and g["stop_max_absolute"]==0,
            net_contribution_pass=contrasts["analytic_value-ordinary_value"]["lower"]>0
                and changed>0 and selected["lower"]>0)
    output["calibration_pass"]=all(x["calibration_pass"] for x in output["splits"].values())
    output["net_contribution_pass"]=all(x["net_contribution_pass"] for x in output["splits"].values())
    output["cost_scope"]="Task utility already charges actual READ prices and declared task latency. CPU sensitivity adds complete native child+host process CPU (including model/grid fitting, propagation, content, persistence, startup) and fitted-model CPU amortization. Shared data/calibration/teacher CPU cancels between the two matched residual arms. Evaluation/replay CPU is research overhead and excluded from deployment cost; no energy claim."
    return output
