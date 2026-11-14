"""Aggregate the frozen v2 experiment without selecting on holdout outcomes.

    python -m rrsnn_v2.aggregate_results --self-test
    python -m rrsnn_v2.aggregate_results --check
    python -m rrsnn_v2.aggregate_results --wait

Primary: rr_density_sampled minus the pre-locked ctrnn_matched_cpu.
Secondary: the comparator already locked in selection.json by validation NLL.
Paired intervals resample training seeds and shared scenario/value-group indices
with replacement, preserving model pairing and all four paired conditions.
The fixed replay draws are averaged BEFORE utility-difference bootstrapping.
Negative transfer is computed BEFORE that averaging, for each actual replay.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import time

for _name in ("OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","OMP_NUM_THREADS","NUMEXPR_NUM_THREADS"):
    os.environ[_name]="1"
import numpy as np

ROOT=Path(__file__).resolve().parent
RESULTS=ROOT/"results"
BOOTSTRAP_DRAWS=10000
BOOTSTRAP_SEED=930201
TRANSFER_EPSILON=1e-8
CONDITIONS=("A0","A2","B0","B2")

CONTRACT={
    "schema":"rrsnn.v2.aggregation-contract.v1",
    "set_before_reading_new_holdout_metrics":True,
    "bootstrap_draws":BOOTSTRAP_DRAWS,"bootstrap_seed":BOOTSTRAP_SEED,
    "bootstrap_algorithm":"Paired crossed two-axis bootstrap: resample training seeds, then one shared episode/value-group sample for the draw. Candidate and comparator share all indices; all four conditions stay within their original value group. Average fixed replay draws before estimating utility contrasts.",
    "sampling_uncertainty":"Intervals condition on the fixed replay draws; they do not separately estimate the variance of unlimited future spike-path sampling.",
    "negative_transfer":"Compare raw achieved utilities per aligned seed/replay/episode using epsilon1e-8, before averaging replay outcomes. A deterministic comparator is broadcast to each sampled candidate replay, without counting extra independent seeds or scenarios.",
    "main_table":"Mean and sample SD of five per-seed means; actual epochs, updates, CPU process seconds, wall seconds, peak process RSS and state metadata reported separately.",
    "paired_group":"Four rows per value group ordered A_shock0,A_shock2,B_shock0,B_shock2. Assert common values/budget/refill/schedule and common mean maturity.",
    "high_value_retention":"From final live bitmask: retained value minus retained_count*mean(initial item values), and retained top2 fraction minus retained_count/4. These are terminal-only diagnostics and exclude early-emission rewards.",
    "anticipation":"Use group-level shock2-minus-shock0 renewal/emission means from the dedicated probe. Empirical action-distribution TV remains descriptive because finite-sample plug-in TV is upward biased.",
    "model_selection":"Read and verify selection.json; never select a comparator by holdout metrics.",
    "incompleteness":"Do not produce a partial main comparison if any planned main/paired result is missing. Optional transfer/probe results are aggregated only when complete for their stated seed set.",
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    path=Path(path)
    if path.suffix==".gz":
        with gzip.open(path,"rt",encoding="utf-8") as handle:return json.load(handle)
    return json.loads(path.read_text())


def stats(values):
    a=np.asarray(values,dtype=float)
    if a.ndim!=1 or not np.isfinite(a).all():raise ValueError("Finite seed-level vector required")
    return {"mean":float(a.mean()),"seed_sd":float(a.std(ddof=1)) if len(a)>1 else 0.,
            "seed_values":a.tolist(),"n_seeds":len(a)}


class PairedBootstrap:
    """Shared scenario resampling preserves the crossed evaluation design."""
    def __init__(self,seeds,groups,draws=BOOTSTRAP_DRAWS,seed=BOOTSTRAP_SEED):
        self.seeds=int(seeds);self.groups=int(groups);self.draws=int(draws)
        rng=np.random.default_rng(seed+1009*groups+17*seeds)
        self.seed_weights=np.empty((draws,seeds),dtype=float)
        self.group_counts=np.empty((draws,groups),dtype=np.uint16)
        for draw in range(draws):
            self.seed_weights[draw]=np.bincount(rng.integers(seeds,size=seeds),minlength=seeds)/seeds
            self.group_counts[draw]=np.bincount(rng.integers(groups,size=groups),minlength=groups)

    def summary(self,values):
        a=np.asarray(values,dtype=float)
        if a.shape!=(self.seeds,self.groups) or not np.isfinite(a).all():
            raise ValueError("Expected finite [training_seed, scenario_group] estimands")
        selected=self.seed_weights@a
        replicates=np.einsum("bg,bg->b",selected,self.group_counts,optimize=False)/self.groups
        result=stats(a.mean(1))
        result["paired_bootstrap_95_percentile_interval"]=np.quantile(replicates,[.025,.975]).tolist()
        result["bootstrap_draws"]=self.draws
        return result


def retention(values,masks):
    """All returned arrays follow the masks' [seed,replay,episode] shape."""
    values=np.asarray(values,dtype=float);masks=np.asarray(masks)
    if masks.dtype.kind not in "iu" or np.any(masks<0) or np.any(masks>15):
        raise ValueError("Final live mask must be integer in[0,15]")
    alive=((masks[...,None]>>np.arange(4))&1).astype(bool)
    count=alive.sum(-1)
    retained=(alive*values).sum(-1)
    ranking=np.argsort(values,axis=-1,kind="stable")[:,-2:]
    top2=np.zeros_like(values,dtype=bool)
    np.put_along_axis(top2,ranking,True,axis=-1)
    top2_fraction=(alive*top2).sum(-1)/2
    return {"retained_count":count.astype(float),"retained_value":retained,
            "retained_top2_fraction":top2_fraction,
            "retained_top2_excess_same_count":top2_fraction-count/4,
            "retained_value_excess_same_count":retained-count*values.mean(-1)}


def paired_indices(scenarios):
    if len(scenarios)%4:raise ValueError("Paired scenarios must contain complete four-condition groups")
    for group in range(len(scenarios)//4):
        block=scenarios[4*group:4*group+4]
        if [(s["profile"],s["shock_amount"]) for s in block]!=[("A",0),("A",2),("B",0),("B",2)]:
            raise ValueError("Unexpected paired condition order")
        for field in ("values","budget","refill_amount","shock_time","refill_time","horizon"):
            if any(s[field]!=block[0][field] for s in block):raise ValueError(f"Nonpaired field:{field}")
        if len({sum(s["deadlines"])/4 for s in block})!=1:raise ValueError("Mean maturities differ")
    return np.arange(len(scenarios)).reshape(-1,4)


def planned_runs(plan):
    return [v+("_sampled" if sampled else "") for v,sampled in plan["training_families"]]+["ctrnn_matched_cpu"]


def readiness(plan):
    missing=[];complete_training=complete_evaluation=0
    if not (RESULTS/"selection.json").exists():missing.append(str(RESULTS/"selection.json"))
    for run in planned_runs(plan):
        sampled=run.endswith("_sampled")
        for seed in plan["seeds"]:
            folder=RESULTS/run/f"seed_{seed}"
            training=folder/"training.json"
            if training.exists():complete_training+=1
            else:missing.append(str(training))
            paths=[folder/"closed_test.json.gz",folder/"closed_shift.json.gz"]
            paths += [folder/f"paired_rep{i}.json.gz" for i in range(4 if sampled else 1)]
            for path in paths:
                if path.exists():complete_evaluation+=1
                else:missing.append(str(path))
    return {"schema":"rrsnn.v2.aggregate-readiness.v1","ready":not missing,
            "completed_training_files":complete_training,"completed_required_evaluation_files":complete_evaluation,
            "missing_count":len(missing),"missing":missing}


def load_evaluations(run,seeds,dataset,selection,scenarios,transfer_backend=None):
    repetitions=4 if dataset=="paired" and run.endswith("_sampled") else 1
    evaluations=[];paths=[];modes=[]
    for seed in seeds:
        seed_rows=[]
        for repeat in range(repetitions):
            folder=RESULTS/run/f"seed_{seed}"
            filename=(f"transfer_{dataset}_{transfer_backend}.json.gz" if transfer_backend else
                      f"paired_rep{repeat}.json.gz" if dataset=="paired" else f"closed_{dataset}.json.gz")
            path=folder/filename;payload=read_json(path)
            if payload["run_name"]!=run or payload["seed"]!=seed:raise ValueError("Mismatched result identity")
            if payload.get("dataset")!=dataset:raise ValueError("Mismatched result dataset")
            if dataset=="paired" and payload.get("repeat")!=repeat:raise ValueError("Mismatched paired replay identity")
            if payload["checkpoint_sha256"]!=selection["checkpoints"][run][str(seed)]:
                raise ValueError("Evaluation checkpoint differs from validation-locked checkpoint")
            e=payload["evaluation"]
            if e["episodes"]!=len(scenarios) or e["budget_violations"]!=0 or not e["ledger_conservation"]:
                raise ValueError("Evaluation episode count or ledger invariant failed")
            if len(e["episode_live_final"])!=len(scenarios):raise ValueError("Missing final live masks")
            seed_rows.append({k:e[k] for k in e if k.startswith("episode_")})
            modes.append(e["mode"]);paths.append({"path":str(path.relative_to(ROOT)),"sha256":sha(path)})
        evaluations.append(seed_rows)
    fields={"utility":"episode_utility","oracle":"episode_oracle",
            "normalized_utility":"episode_normalized_utility","budget_spent":"episode_budget_spent",
            "internal_count":"episode_internal_count"}
    arrays={name:np.asarray([[r[field] for r in row] for row in evaluations],dtype=float)
            for name,field in fields.items()}
    if any(a.shape!=(len(seeds),repetitions,len(scenarios)) for a in arrays.values()):
        raise ValueError("Unexpected episode-array shape")
    if any(not np.isfinite(a).all() for a in arrays.values()):raise ValueError("Nonfinite evaluation")
    oracle=arrays["oracle"];utility=arrays["utility"]
    if np.max(utility-oracle)>1e-8:raise ValueError("Utility exceeds oracle")
    expected=np.divide(utility,oracle,out=np.ones_like(utility),where=oracle>1e-12)
    if not np.allclose(expected,arrays["normalized_utility"],rtol=0,atol=1e-12):
        raise ValueError("Normalized utility convention mismatch")
    if not np.allclose(oracle,oracle[0,0],rtol=0,atol=1e-12):raise ValueError("Task oracle differs across seeds/replays")
    masks=np.asarray([[r["episode_live_final"] for r in row] for row in evaluations])
    values=np.asarray([s["values"] for s in scenarios])
    retained=retention(values,masks)
    stored=np.asarray([[r["episode_retained_value"] for r in row] for row in evaluations])
    if not np.allclose(retained["retained_value"],stored,rtol=0,atol=1e-10):
        raise ValueError("Final bitmask and reported retained value disagree")
    arrays.update(retained);arrays["regret"]=oracle-utility
    return {"arrays":arrays,"replays":repetitions,"modes":sorted(set(modes)),"files":paths,
            "unique_zero_oracle_episodes":int(np.sum(oracle[0,0]<=1e-12))}


def grouped(array,indices=None):
    # Closed-loop datasets have one condition per episode. Paired datasets
    # retain all4 conditions inside each value group for every operation.
    return array[:,:,:,None] if indices is None else array[:,:,indices]


def compare(candidate,reference,bootstrap,indices=None):
    ca=candidate["arrays"];ra=reference["arrays"]
    if ca["utility"].shape[0::2]!=ra["utility"].shape[0::2]:raise ValueError("Unpaired seed/episode axes")
    replay=max(candidate["replays"],reference["replays"])
    if candidate["replays"] not in (1,replay) or reference["replays"] not in (1,replay):
        raise ValueError("Incompatible replay counts")
    def difference(metric):
        a,b=grouped(ca[metric],indices),grouped(ra[metric],indices)
        return np.broadcast_to(a,(a.shape[0],replay,*a.shape[2:]))-np.broadcast_to(b,(b.shape[0],replay,*b.shape[2:]))
    raw=difference("utility")
    negative=raw < -TRANSFER_EPSILON
    positive=raw > TRANSFER_EPSILON
    tied=~(negative|positive)
    metrics=("utility","normalized_utility","regret","retained_value","retained_count",
             "retained_top2_fraction","retained_top2_excess_same_count","retained_value_excess_same_count")
    contrasts={metric:bootstrap.summary(difference(metric).mean(axis=(1,3))) for metric in metrics}
    result={"contrasts_candidate_minus_reference":contrasts,
        "negative_transfer_episode_fraction":bootstrap.summary(negative.mean(axis=(1,3))),
        "positive_transfer_episode_fraction":bootstrap.summary(positive.mean(axis=(1,3))),
        "equal_utility_episode_fraction":bootstrap.summary(tied.mean(axis=(1,3))),
        "actual_aligned_replay_episode_comparisons":int(raw.size),
        "training_seeds":raw.shape[0],"scenario_groups":raw.shape[2],"conditions_per_group":raw.shape[3],
        "aligned_replays":replay,"candidate_stored_replays":candidate["replays"],
        "reference_stored_replays":reference["replays"],
        "rate_interpretation":"Fraction of actual aligned replay outcomes below/above the comparator. This depends on the specified coupling of stochastic replays and is not the sign of a replay-averaged performance difference.",
        "fixed_replay_conditioning":True}
    if indices is not None:
        result["by_condition"]={name:{
            "utility_delta":bootstrap.summary(difference("utility")[:,:,:,j].mean(1)),
            "normalized_utility_delta":bootstrap.summary(difference("normalized_utility")[:,:,:,j].mean(1)),
            "negative_transfer_episode_fraction":bootstrap.summary(negative[:,:,:,j].mean(1)),
            "retained_value_excess_delta":bootstrap.summary(difference("retained_value_excess_same_count")[:,:,:,j].mean(1))}
            for j,name in enumerate(CONDITIONS)}
        delta=difference("utility").mean(1)
        interaction=(delta[:,:,1]-delta[:,:,0])-(delta[:,:,3]-delta[:,:,2])
        result["shock_x_maturity_interaction_difference"]=bootstrap.summary(interaction)
    return result


def describe(dataset,indices=None):
    output={"modes":dataset["modes"],"stored_replays_per_seed":dataset["replays"],
            "unique_zero_oracle_episodes":dataset["unique_zero_oracle_episodes"],
            "metrics":{name:stats(a.mean(axis=(1,2))) for name,a in dataset["arrays"].items()}}
    if indices is not None:
        output["by_condition"]={condition:{name:stats(grouped(a,indices)[:,:,:,j].mean(axis=(1,2)))
                 for name,a in dataset["arrays"].items()} for j,condition in enumerate(CONDITIONS)}
        u=grouped(dataset["arrays"]["utility"],indices).mean(1)
        interaction=(u[:,:,1]-u[:,:,0])-(u[:,:,3]-u[:,:,2])
        output["shock_x_maturity_utility_interaction"]=stats(interaction.mean(1))
    return output


def anticipation(path,seeds,bootstrap):
    if not path.exists():return {"status":"not_present"}
    data=read_json(path);rows=data["results"];names=sorted({r["run_name"] for r in rows})
    output={"status":"complete","source_sha256":sha(path),"announced_shock":data["announced_shock"],
            "pre_shock_decision_time":data["pre_shock_decision_time"],"rows":[],
            "tv_scope":"Descriptive plug-in TV, upward biased with finite paths. No TV rejection test, significance threshold or causal-superiority claim."}
    for name in names:
        rr=[next((r for r in rows if r["run_name"]==name and r["seed"]==seed),None) for seed in seeds]
        if any(r is None for r in rr):
            return {"status":"incomplete_not_aggregated","source_sha256":sha(path)}
        renew=np.array([r["group_renewals"] for r in rr],dtype=float)
        emit=np.array([r["group_emissions"] for r in rr],dtype=float)
        drop=np.array([r["group_due_drops"] for r in rr],dtype=float)
        if renew.shape!=(len(seeds),bootstrap.groups,2):raise ValueError("Probe group shape mismatch")
        output["rows"].append({"run_name":name,
            "paths_per_group_condition_by_seed":[r["paths_per_group_condition"] for r in rr],
            "renewal_treatment_effect":bootstrap.summary(renew[:,:,1]-renew[:,:,0]),
            "emission_treatment_effect":bootstrap.summary(emit[:,:,1]-emit[:,:,0]),
            "due_drop_treatment_effect":bootstrap.summary(drop[:,:,1]-drop[:,:,0]),
            "empirical_tv_descriptive":stats([r["mean_empirical_action_distribution_tv"] for r in rr])})
    return output


def aggregate():
    plan=read_json(ROOT/"experiment_plan.json");protocol=read_json(ROOT/"analysis_protocol.json")
    ready=readiness(plan)
    if not ready["ready"]:raise RuntimeError(f"Refusing partial main table: {ready['missing_count']} required files missing")
    selection=read_json(RESULTS/"selection.json");seeds=plan["seeds"];runs=planned_runs(plan)
    if selection["primary_candidate"]!=plan["primary_candidate"] or selection["primary_comparator"]!=plan["primary_comparator"]:
        raise ValueError("Primary comparison changed")
    if selection["holdout_metrics_used_for_selection"]:raise ValueError("Holdout-based selection is prohibited")
    if selection["plan_sha256"]!=sha(ROOT/"experiment_plan.json"):raise ValueError("Selection plan changed")
    frozen={name:sha(ROOT/name)==expected for name,expected in plan["frozen_sources"].items()}
    analysis_hashes={name:sha(ROOT/name)==expected for name,expected in protocol["scripts"].items()}
    if not all(frozen.values()) or not all(analysis_hashes.values()):raise ValueError("Frozen source drift")
    if selection["evaluation_source_sha256"]!=sha(ROOT/"evaluate.py"):raise ValueError("Evaluator changed after selection")
    if selection["sampling_source_sha256"]!=sha(ROOT/"audit/sampled_policy.py"):raise ValueError("Sampler changed after selection")
    scenarios={name:read_json(ROOT/"data"/f"{name}_scenarios.json") for name in ("test","shift","paired")}
    index=paired_indices(scenarios["paired"])
    boot={name:PairedBootstrap(len(seeds),len(index) if name=="paired" else len(scenarios[name])) for name in scenarios}
    training={};datasets={};rows=[];input_files=[]
    for run in runs:
        training[run]=[];datasets[run]={}
        for seed in seeds:
            path=RESULTS/run/f"seed_{seed}"/"training.json";record=read_json(path)
            if record["run_name"]!=run or record["seed"]!=seed:raise ValueError("Training run identity mismatch")
            if record["checkpoint_sha256"]!=selection["checkpoints"][run][str(seed)]:raise ValueError("Training checkpoint mismatch")
            if sha(path.with_name("model.pt"))!=record["checkpoint_sha256"]:raise ValueError("Checkpoint artifact changed")
            if record["plan"]["data_manifest_sha256"]!=plan["data_manifest_sha256"]:raise ValueError("Training data manifest changed")
            if any(sha(ROOT/name)!=expected for name,expected in record["source_hashes"].items()):
                raise ValueError("Training source record does not match frozen files")
            if record["holdout_opened_by_training"]:raise ValueError("Training opened holdout")
            training[run].append(record);input_files.append({"path":str(path.relative_to(ROOT)),"sha256":sha(path)})
        records=training[run]
        row={"run_name":run,"variant":records[0]["variant"],"sampled_training":records[0]["sampled_training"],
             "training_objective":records[0]["training_objective"],
             "validation_nll":stats([r["best_validation_nll"] for r in records]),
             "actual_epochs":stats([r["plan"]["epochs"] for r in records]),
             "actual_updates":stats([r["plan"]["updates"] for r in records]),
             "best_epochs":[r["best_epoch"] for r in records],
             "training_cpu_seconds":stats([r["train_cpu_seconds"] for r in records]),
             "training_wall_seconds":stats([r["train_seconds"] for r in records]),
             "peak_training_process_rss_mib":stats([r["process_peak_rss_mib"] for r in records]),
             "all_gradients_finite":all(r["gradients_all_finite"] for r in records),
             "maximum_sample_probability_correction":max(r["maximum_sample_probability_correction"] for r in records),
             "metadata":records[0]["metadata"],"evaluation":{}}
        for name in scenarios:
            ds=load_evaluations(run,seeds,name,selection,scenarios[name])
            datasets[run][name]=ds;input_files.extend(ds["files"])
            row["evaluation"][name]=describe(ds,index if name=="paired" else None)
        rows.append(row)
    allowed=plan["secondary_comparators_selected_only_by_mean_validation_nll"]
    means={name:float(np.mean([r["best_validation_nll"] for r in training[name]])) for name in allowed}
    expected_secondary=min(means,key=means.get)
    if selection["secondary_strong_baseline"]!=expected_secondary:raise ValueError("Secondary baseline is not validation-locked minimum")
    for name in means:
        if abs(means[name]-selection["secondary_baseline_mean_validation_nll"][name])>1e-12:
            raise ValueError("Validation selection values changed")
    candidate=selection["primary_candidate"]
    comparisons={}
    for label,reference in (("primary",selection["primary_comparator"]),("secondary",expected_secondary)):
        comparisons[label]={"candidate":candidate,"reference":reference,
            "selection_rule":"Pre-locked same-CPU comparator" if label=="primary" else "Lowest mean validation NLL among pre-listed alternatives",
            "datasets":{name:compare(datasets[candidate][name],datasets[reference][name],boot[name],index if name=="paired" else None)
                        for name in scenarios}}
    transfers=[]
    for run,backend in (("rr_density_sampled","brownian"),("rr_density","brownian"),("rr_density","ctmc")):
        for name in ("test","shift"):
            paths=[RESULTS/run/f"seed_{seed}"/f"transfer_{name}_{backend}.json.gz" for seed in seeds]
            if not all(p.exists() for p in paths):
                transfers.append({"run_name":run,"backend":backend,"dataset":name,"status":"not_complete_not_aggregated"})
                continue
            target=load_evaluations(run,seeds,name,selection,scenarios[name],backend)
            input_files.extend(target["files"])
            transfers.append({"run_name":run,"backend":backend,"dataset":name,"status":"complete",
                "target":describe(target),"target_minus_primary_execution":compare(target,datasets[run][name],boot[name]),
                "interpretation":"Same weights; Brownian uses a different physical law. CTMC versus density compares sampled nonlinear decisions to an expected-state policy. This is a transfer diagnostic, not an equality claim."})
    cpu_ratio=np.array([r["train_cpu_seconds"] for r in training["ctrnn_matched_cpu"]]) / np.array([r["train_cpu_seconds"] for r in training[candidate]])
    result={"schema":"rrsnn.v2.aggregate-results.v1","contract":CONTRACT,
        "seeds":seeds,"models":len(runs),"completed_training_runs":len(runs)*len(seeds),
        "primary_candidate":candidate,"primary_comparator":selection["primary_comparator"],
        "secondary_comparator":expected_secondary,
        "source_validation":{"training_frozen_files":frozen,"analysis_protocol_scripts":analysis_hashes,
            "selection_sha256":sha(RESULTS/"selection.json"),"experiment_plan_sha256":sha(ROOT/"experiment_plan.json"),
            "analysis_protocol_sha256":sha(ROOT/"analysis_protocol.json"),"aggregator_sha256":sha(__file__)},
        "scenario_sha256":{name:sha(ROOT/"data"/f"{name}_scenarios.json") for name in scenarios},
        "equal_cpu_comparator_seconds_ratio":stats(cpu_ratio),
        "rows":rows,"comparisons":comparisons,"transfer_diagnostics":transfers,
        "anticipation_probe":anticipation(RESULTS/"anticipation_probe.json",seeds,boot["paired"]),
        "input_files":input_files,
        "limitations":["Five fitted training seeds; bootstrap intervals rely on this small seed sample and are not broad replication guarantees.",
                       "Intervals condition on the finite fixed replay draws, including one replay per test/shift seed; extra path-sampling uncertainty is not separately estimated.",
                       "Only the pre-locked shift comparison is primary. Other model rows, test/paired contrasts, transfer and probe diagnostics must not be promoted to separately confirmed discoveries without multiplicity treatment.",
                       "Negative transfer uses each actual replay comparison; stochastic-comparator rates depend on the provided replay coupling.",
                       "Terminal retention excludes discounted early outputs and is not a replacement for total task utility.",
                       "Synthetic shift and announced-shock tasks are not real chronological future windows or evidence of production Hepta utility.",
                       "Training logical state, sampled persistent numeric buffers, model parameters and whole-process RSS are different quantities; metadata is retained rather than claiming identical actual memory."]}
    destination=RESULTS/"aggregate.json"
    temporary=RESULTS/"aggregate.inprogress.json"
    temporary.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    temporary.replace(destination)
    return result


def self_test():
    checks=[]
    # Opposite replay outcomes cancel in mean, but half are negative transfer.
    c={"arrays":{},"replays":2};b={"arrays":{},"replays":1}
    for metric in ("utility","normalized_utility","regret","retained_value","retained_count",
                   "retained_top2_fraction","retained_top2_excess_same_count","retained_value_excess_same_count"):
        c["arrays"][metric]=np.array([[[0.],[2.]]]);b["arrays"][metric]=np.array([[[1.]]])
    out=compare(c,b,PairedBootstrap(1,1,draws=256))
    assert out["contrasts_candidate_minus_reference"]["utility"]["mean"]==0
    assert out["negative_transfer_episode_fraction"]["mean"]==.5
    assert out["positive_transfer_episode_fraction"]["mean"]==.5
    assert out["equal_utility_episode_fraction"]["mean"]==0
    checks.append({"name":"negative_transfer_before_replay_averaging","passed":True})
    # Constant paired differences stay constant under both resampled axes.
    boot=PairedBootstrap(5,7,draws=10000)
    const=boot.summary(np.full((5,7),.25))
    assert np.allclose(const["paired_bootstrap_95_percentile_interval"],[.25,.25],atol=1e-15)
    checks.append({"name":"paired_bootstrap_constant_difference","passed":True})
    values=np.array([[4.,3.,2.,1.]]*4)
    r=retention(values,np.array([[[3,12,15,0]]],dtype=np.int64))
    assert np.array_equal(r["retained_value"],[[[7.,3.,10.,0.]]])
    assert np.array_equal(r["retained_value_excess_same_count"],[[[2.,-2.,0.,0.]]])
    assert np.array_equal(r["retained_top2_excess_same_count"],[[[.5,-.5,0.,0.]]])
    checks.append({"name":"terminal_retention_hand_calculation","passed":True})
    a=np.tile([4.,3.,5.,2.],(5,2,3,1))
    indices=np.arange(12).reshape(3,4)
    assert np.array_equal(grouped(a.reshape(5,2,12),indices),a)
    paired_candidate={"replays":2,"arrays":{m:a.reshape(5,2,12) for m in c["arrays"]}}
    paired_reference={"replays":1,"arrays":{m:np.ones((5,1,12)) for m in c["arrays"]}}
    grouped_result=compare(paired_candidate,paired_reference,PairedBootstrap(5,3,draws=256),indices)
    assert grouped_result["shock_x_maturity_interaction_difference"]["mean"]==2
    assert grouped_result["actual_aligned_replay_episode_comparisons"]==120
    assert grouped_result["by_condition"]["A0"]["utility_delta"]["mean"]==3
    checks.append({"name":"four_condition_interaction_stays_grouped","passed":True})
    s=stats([1.,3.]);assert s["mean"]==2 and abs(s["seed_sd"]-np.sqrt(2))<1e-14
    checks.append({"name":"sample_seed_sd_ddof1","passed":True})
    output={"schema":"rrsnn.v2.aggregation-self-test.v1","checks":checks,
            "no_holdout_results_read":True,"contract":CONTRACT,"aggregator_sha256":sha(__file__)}
    destination=ROOT/"audit/results";destination.mkdir(parents=True,exist_ok=True)
    (destination/"aggregation_self_test.json").write_text(json.dumps(output,indent=2)+"\n")
    (destination/"aggregation_contract.json").write_text(json.dumps(CONTRACT,indent=2)+"\n")
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test",action="store_true");parser.add_argument("--check",action="store_true")
    parser.add_argument("--wait",action="store_true");parser.add_argument("--interval",type=float,default=20.)
    parser.add_argument("--timeout",type=float,default=14400.)
    args=parser.parse_args()
    if args.self_test:
        result=self_test();print(json.dumps({"passed":True,"checks":len(result["checks"]),"no_holdout_results_read":True}));return
    plan=read_json(ROOT/"experiment_plan.json");begun=time.monotonic();last=None
    while True:
        ready=readiness(plan)
        if args.check:
            print(json.dumps(ready,indent=2));return
        if ready["ready"]:
            started=time.perf_counter()
            try:
                result=aggregate()
            except (EOFError,json.JSONDecodeError,gzip.BadGzipFile) as error:
                if not args.wait:raise
                print(json.dumps({"ready_paths_but_write_in_progress":str(error)}),flush=True)
                if time.monotonic()-begun>args.timeout:raise
                time.sleep(max(.1,min(args.interval,60.)))
                continue
            primary=result["comparisons"]["primary"]["datasets"]["shift"]
            print(json.dumps({"complete":True,"path":str(RESULTS/"aggregate.json"),
                "seconds":time.perf_counter()-started,"primary_shift_delta":primary["contrasts_candidate_minus_reference"]["normalized_utility"],
                "primary_shift_negative_transfer":primary["negative_transfer_episode_fraction"]}),flush=True)
            return
        signature=(ready["completed_training_files"],ready["completed_required_evaluation_files"],ready["missing_count"])
        if signature!=last:
            print(json.dumps({k:v for k,v in ready.items() if k!="missing"}),flush=True);last=signature
        if not args.wait:raise SystemExit("Required results incomplete; use--check or--wait. No partial main table was written.")
        if time.monotonic()-begun>args.timeout:raise SystemExit("Timed out waiting for required results")
        time.sleep(max(.1,min(args.interval,60.)))


if __name__=="__main__":main()
