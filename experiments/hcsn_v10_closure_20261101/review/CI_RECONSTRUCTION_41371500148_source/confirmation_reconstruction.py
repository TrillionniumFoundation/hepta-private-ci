"""Independent frozen-shard, actual-state and adjusted-interval reconstruction."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from .renewal_reconstruction import analytic_probability,close,model_step


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stream_rows(path):
    with gzip.open(path,"rt") as stream:
        for line in stream:yield json.loads(line)


def replay(run,episode,config,models):
    family,seed=run["family"],run["fit_seed"]
    physics=episode["calibration"]["estimated"]
    obs={"time":0.,"x":episode["initial_x"],"refractory_remaining":0.,"content_probs":[.2]*5,"has_read":False}
    state=None if seed is None else np.zeros(models[seed,family]["out"].shape[0])
    budget,pending,stopped,reads=config["budget"],None,False,0
    predictions={};maximum=0.
    for tick,row in enumerate(run["trace"]):
        assert tick==row["tick"]
        now=tick*config["dt"];fresh=pending==tick
        if fresh:
            obs={"time":now,"x":episode["path"]["x"][tick],
                "refractory_remaining":episode["path"]["refractory_remaining"][tick],
                "content_probs":np.eye(5)[episode["path"]["content"][tick]].tolist(),"has_read":True}
            assert row["observed"]==obs;pending=None
        else:assert row["observed"] is None
        assert obs==row["visible_observation"]
        if seed is None:
            p=analytic_probability(obs,now,physics);assert row["state"] is None
        else:
            packet=np.array([0 if tick==0 else config["dt"],fresh,obs["has_read"],obs["x"],
                obs["refractory_remaining"],*obs["content_probs"],now-obs["time"],physics["nu"],
                physics["sigma"],physics["reset"],physics["refractory"],now])
            state,p=model_step(models[seed,family],family,packet,state)
            error=float(np.max(abs(state-row["state"])));maximum=max(maximum,error);assert error<2e-10
        close(p,row["probabilities"])
        if tick in config["deadlines"]:predictions[tick]=p
        action=row["action"]
        if tick==config["ticks"] or stopped:assert action is None
        elif budget<=0 or not any(d>tick for d in config["deadlines"]):assert action=="STOP"
        elif run["controller"]=="lightweight":
            detail=row["policy_detail"]
            expected="READ" if detail["forecast_error"]>config["light_threshold"] and min(d for d in config["deadlines"] if d>tick)-tick<=2 else "WAIT"
            assert action==expected
        else:
            best=max(row["policy_detail"]["candidate_values"],key=lambda r:(r["net_value"],-r["arrival_tick"]))
            expected="STOP" if best["net_value"]<=0 else ("READ" if best["arrival_tick"]==tick+1 else "WAIT")
            assert action==expected
        if action=="READ":budget-=1;reads+=1;pending=tick+1
        if action=="STOP":stopped=True
        assert budget==row["budget_after"] and pending==row["read_reveal_tick"]
    accuracy,nll,brier=[],[],[]
    for row in run["predictions"]:
        tick=row["tick"];truth=episode["path"]["content"][tick];p=predictions[tick]
        close(p,row["probabilities"]);assert truth==row["truth_for_scoring_only"]
        accuracy.append(int(p.argmax()==truth));nll.append(-np.log(max(p[truth],1e-12)))
        brier.append(np.sum((p-np.eye(5)[truth])**2))
    assert len(accuracy)==len(config["deadlines"])
    reward=float(np.mean(accuracy)-reads*config["read_cost"])
    for name,value in {"accuracy":np.mean(accuracy),"nll":np.mean(nll),"brier":np.mean(brier),
        "reads":reads,"read_cost":reads*config["read_cost"],"net_reward":reward}.items():close(value,run["summary"][name])
    return reward,maximum,{"accuracy":float(np.mean(accuracy)),"reads":reads,"read_fee":reads*config["read_cost"],
        "nll":float(np.mean(nll)),"brier":float(np.mean(brier)),"net_reward":reward}


def audit(output):
    output=Path(output);repo=Path(__file__).resolve().parents[3]
    plan=json.loads((output/"CONFIRMATION_PLAN.json").read_text())
    base=Path(plan["base_directory"])
    if not base.is_dir():base=repo/plan["base_directory_repo_relative"]
    assert sha(base/"PLAN.json")==plan["base_plan_sha256"]
    assert sha(base/"FIT.json")==plan["base_fit_sha256"]
    assert sha(base/"FROZEN_MODELS.json")==plan["base_frozen_models_sha256"]
    frozen=json.loads((base/"FROZEN_MODELS.json").read_text())
    assert frozen["selection"]==plan["model_selection"] and frozen["checkpoints"]==plan["all_checkpoints"]
    assert plan["models_retrained"] is False and plan["selection_changed"] is False
    for name,digest in plan["all_checkpoints"].items():assert sha(base/name)==digest
    for name,digest in plan["source_sha256"].items():assert sha(output/"source_snapshot"/name)==digest
    assert sha(output/"source_snapshot/confirm.py")==plan["confirmation_source_sha256"]
    assert sha(output/"source_snapshot/physics.py")==plan["physics_sha256"]
    assert sha(output/"WORLD_SEEDS.json")==plan["world_seed_sha256"]
    excluded=set()
    for name,digest in plan["exclusion_source_sha256"].items():
        path=Path(name)
        if not path.is_absolute():path=repo/path
        assert sha(path)==digest
        if path.suffix==".npz":
            archive=np.load(path)
            excluded.update(map(int,archive["train_world_seeds"]));excluded.update(map(int,archive["validation_world_seeds"]))
        else:excluded.update(row["episode"]["seed"] for row in stream_rows(path))
    old_excluded=set(excluded)
    assignments=json.loads((output/"WORLD_SEEDS.json").read_text())
    assert len(assignments)==plan["total_worlds"]==384
    expected_keys={(condition,i) for condition in plan["conditions"] for i in range(192)}
    assert {(a["condition"],a["world"]) for a in assignments}==expected_keys
    assignment_map={}
    for assignment in assignments:
        condition_index=plan["conditions"].index(assignment["condition"])
        assert assignment["world"]==assignment["shard"]*24+assignment["local_index"]
        assert 0<=assignment["shard"]<8 and 0<=assignment["local_index"]<24
        retry=0
        seed=int(np.random.SeedSequence(plan["world_namespace"]+[condition_index,assignment["shard"],assignment["local_index"],retry]).generate_state(1)[0])
        while seed in excluded:
            retry+=1
            seed=int(np.random.SeedSequence(plan["world_namespace"]+[condition_index,assignment["shard"],assignment["local_index"],retry]).generate_state(1)[0])
        assert retry==assignment["collision_retry"] and seed==assignment["world_seed"]
        excluded.add(seed);assignment_map[assignment["condition"],assignment["world"]]=assignment
    models={}
    for seed in plan["fit_seeds"]:
        for family in plan["families"]:
            width=plan["model_selection"][str(seed)]["widths"][family]
            models[seed,family]=dict(np.load(base/"fits"/f"{family}_{seed}_w{width}.npz"))
    indexed,scored,parity,shards={}, {}, {}, []
    count_ticks,count_outputs,maximum=0,0,0.
    for number in range(8):
        directory=output/f"shard_{number:02d}"
        receipt=json.loads((directory/"COMPLETE.json").read_text())
        assert receipt["shard"]==number and receipt["worlds"]==48 and receipt["runs"]==1632
        assert receipt["plan_sha256"]==sha(output/"CONFIRMATION_PLAN.json")
        assert receipt["world_seed_sha256"]==plan["world_seed_sha256"]
        for name,digest in receipt["raw_sha256"].items():assert sha(directory/name)==digest
        worlds={}
        for row in stream_rows(directory/"worlds.jsonl.gz"):
            key=row["condition"],row["world"]
            assert key not in worlds
            assignment=assignment_map[key]
            assert all(row[k]==v for k,v in assignment.items())
            assert row["episode"]["seed"]==assignment["world_seed"]
            assert row["episode"]["seed"] not in old_excluded
            worlds[key]=row["episode"]
        assert len(worlds)==48
        local_count=0
        for run in stream_rows(directory/"runs.jsonl.gz"):
            key=(run["condition"],run["world"],run["fit_seed"],run["family"],run["controller"])
            assert key not in indexed and run["shard"]==number
            episode=worlds[run["condition"],run["world"]]
            reward,error,metrics=replay(run,episode,plan["config"],models)
            indexed[key]=reward;scored[key]=metrics;maximum=max(maximum,error);local_count+=1
            count_ticks+=len(run["trace"]);count_outputs+=len(run["predictions"])
            if run["family"] in ("analytic","exact_history"):
                signature=([r["probabilities"] for r in run["trace"]],[r["action"] for r in run["trace"]])
                twin=run["condition"],run["world"],run["controller"]
                if twin in parity:
                    close(signature[0],parity[twin][0]);assert signature[1]==parity[twin][1]
                else:parity[twin]=signature
        assert local_count==1632
        shards.append({"shard":number,"raw_files_sha256":receipt["raw_sha256"],"runs":local_count})
    assert len(indexed)==384*34
    expected_runs={(condition,i,s,f,c) for condition,i in expected_keys
        for s,f in [(None,"analytic"),(None,"exact_history")]+[(s,f) for s in plan["fit_seeds"] for f in plan["families"]]
        for c in ("lightweight","task_value")}
    assert set(indexed)==expected_runs
    summary=json.loads((output/"SUMMARY.json").read_text());paired=np.load(output/"PAIRED_CONTRASTS.npz")
    assert summary["worlds"]==384 and summary["runs"]==len(indexed)
    assert summary["tick_states"]==count_ticks and summary["mandatory_outputs"]==count_outputs
    assert sha(output/"PAIRED_CONTRASTS.npz")==summary["paired_sha256"]
    assert sha(output/"SHARD_MANIFEST.json")==summary["shard_manifest_sha256"]
    manifest=json.loads((output/"SHARD_MANIFEST.json").read_text())
    assert len(manifest)==8
    for row in manifest:assert row["complete_sha256"]==sha(output/f"shard_{row['shard']:02d}/COMPLETE.json")
    rng=np.random.default_rng(plan["bootstrap"]["seed"]);effects={};descriptive={}
    for condition in plan["conditions"]:
        vectors={};arm_rows={}
        for seed in plan["fit_seeds"]:
            family=plan["model_selection"][str(seed)]["ordinary_family"]
            arms={label:np.array([indexed[condition,i,s,f,c] for i in range(192)])
                for label,s,f,c in (("A",seed,family,"lightweight"),("B",seed,family,"task_value"),
                ("C",None,"analytic","lightweight"),("D",None,"analytic","task_value"),
                ("H",None,"exact_history","task_value"),("M",seed,"mlp","task_value"))}
            for label,s,f,c in (("A",seed,family,"lightweight"),("B",seed,family,"task_value"),
                ("C",None,"analytic","lightweight"),("D",None,"analytic","task_value"),
                ("H",None,"exact_history","task_value"),("M",seed,"mlp","task_value")):
                arm_rows.setdefault(label,[]).extend(scored[condition,i,s,f,c] for i in range(192))
            differences={"D-B":arms["D"]-arms["B"],"D-M":arms["D"]-arms["M"],"B-A":arms["B"]-arms["A"],
                "D-C":arms["D"]-arms["C"],"C-A":arms["C"]-arms["A"],
                "interaction":arms["D"]-arms["C"]-arms["B"]+arms["A"],"D-H":arms["D"]-arms["H"],"B-M":arms["B"]-arms["M"]}
            for name,array in differences.items():vectors.setdefault(name,[]).append(array)
        effects[condition]={}
        for name,values in vectors.items():
            array=np.array(values);close(array,paired[condition+"__"+name])
            bootstrap=[]
            for _ in range(plan["bootstrap"]["replicates"]):
                ii=rng.integers(5,size=5);jj=rng.integers(192,size=192)
                bootstrap.append(float(array[np.ix_(ii,jj)].mean()))
            primary=condition=="matched" and name in ("D-B","D-M")
            low,high=np.quantile(bootstrap,[.0125,.9875] if primary else [.025,.975])
            published=summary["conditions"][condition]["contrasts"][name]
            close([array.mean(),low,high],[published["mean"],published["lower"],published["upper"]])
            assert published["primary"]==primary and published["confidence_level"]==(.975 if primary else .95)
            assert published["positive_at_declared_threshold"]==bool(low>0)
            effects[condition][name]={"mean":float(array.mean()),"lower":float(low),"upper":float(high),"confidence_level":.975 if primary else .95}
        means={label:{metric:float(np.mean([row[metric] for row in values]))
                      for metric in ("accuracy","reads","read_fee","nll","brier","net_reward")}
               for label,values in arm_rows.items()}
        decomposition={name:means["D"][name]-means["B"][name] for name in means["D"]}
        close(decomposition["net_reward"],decomposition["accuracy"]-decomposition["read_fee"])
        descriptive[condition]={"arm_metric_means":means,"D_minus_B_decomposition":decomposition,
            "scope":"Descriptive requested decomposition; READ fee only, CPU not monetized; repeated analytic rows across fits are not new independent samples"}
    both=all(effects["matched"][name]["lower"]>0 for name in ("D-B","D-M"))
    assert both==summary["both_matched_primary_comparisons_positive"]
    return {"worlds":384,"shards":shards,"runs_reconstructed":len(indexed),"tick_states_reconstructed":count_ticks,
        "mandatory_outputs_reconstructed":count_outputs,"maximum_hidden_state_error":maximum,
        "frozen_model_selection_and_all_checkpoint_hashes_unchanged":True,"worlds_disjoint_from_prior_sources":True,
        "all_adjusted_intervals_recomputed":effects,"both_matched_primary_comparisons_positive":both,
        "descriptive_quality_and_read_fee_decomposition":descriptive,
        "scope":"Fixed posthoc-designed finite synthetic confirmation; bootstrap intervals descriptive, no power guarantee or real AV adoption claim",
        "planner_scope":"Actual states/access/scores reconstructed; stochastic hypothetical planner not entirely independently rerun"}
