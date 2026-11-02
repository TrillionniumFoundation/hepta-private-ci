"""Independent actual-state/access/score reconstruction of renewal trajectories.

Actual recurrent steps and analytic probabilities are reimplemented here.
Saved simulated candidate values are checked for decision consistency; the
4-particle hypothetical planner is source-reviewed, not wholly rerun here.
"""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import log_ndtr, ndtr


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a, b, tolerance=2e-10):
    assert np.allclose(a, b, atol=tolerance, rtol=tolerance)


def logistic(x):
    return 1/(1+np.exp(-np.clip(x, -40, 40)))


def model_step(w, family, x, h):
    if family == "gru":
        z = logistic(x@w["Wz"]+h@w["Uz"]+w["bz"])
        r = logistic(x@w["Wr"]+h@w["Ur"]+w["br"])
        n = np.tanh(x@w["Wn"]+(r*h)@w["Un"]+w["bn"])
        state = (1-z)*h+z*n
    elif family == "ssm":
        event = max(x[1], float(x[15] == 0))
        decay = np.exp(-x[0]*np.logaddexp(0,w["rate"])-event*np.logaddexp(0,w["event_rate"]))
        state = decay*h+(1-decay)*np.tanh(x@w["W"]+w["b"])
    else:
        assert family == "mlp"
        state = np.tanh(x@w["W"]+w["b"])
    logits = state@w["out"]+w["bout"]
    probability = np.exp(logits-logits.max()); probability /= probability.sum()
    if x[2] == 0:
        probability[:] = .2
    if x[1] == 1:
        probability = x[5:10].copy()
    return state, probability


def analytic_probability(obs, now, physics):
    cap = 32
    horizon = now-obs["time"]-max(obs["refractory_remaining"],0.)
    if horizon <= 0:
        return np.array(obs["content_probs"])
    n = np.arange(1,cap+1)
    t = horizon-(n-1)*physics["refractory"]
    gap = obs["x"]+(n-1)*physics["reset"]
    safe = np.where(t>0,t,1.)
    scale = physics["sigma"]*np.sqrt(safe)
    a = (-gap-physics["nu"]*safe)/scale
    b = (-gap+physics["nu"]*safe)/scale
    tail = np.where(t>0,ndtr(a)+np.exp(np.minimum(-2*physics["nu"]*gap/physics["sigma"]**2+log_ndtr(b),0)),0.)
    assert tail[-1] <= 1e-10
    count = np.r_[1.,tail[:-1]]-tail
    assert count.min() >= -1e-10
    count = np.maximum(count,0); count /= count.sum()
    transition = np.column_stack([np.roll([.15,.55,0.,0.,.30],i) for i in range(5)])
    vector, probability = np.array(obs["content_probs"]), np.zeros(5)
    for weight in count:
        probability += weight*vector
        vector = transition@vector
    return probability


def audit(base):
    base = Path(base)
    plan = json.loads((base/"PLAN.json").read_text())
    frozen = json.loads((base/"FROZEN_MODELS.json").read_text())
    fits = json.loads((base/"FIT.json").read_text())
    summary = json.loads((base/"SUMMARY.json").read_text())
    snapshot = base/"source_snapshot"
    for path,digest in plan["source_sha256"].items():
        assert sha(snapshot/path)==digest
    assert sha(snapshot/"physics.py")==plan["physics_sha256"]
    assert sha(base/"PLAN.json")==frozen["plan_sha256"]
    assert sha(base/"FIT.json")==frozen["fit_sha256"]
    for path,digest in frozen["checkpoints"].items():
        assert sha(base/path)==digest
    for path,digest in summary["raw_sha256"].items():
        assert sha(base/path)==digest
    models, ordinary_families, candidate_status = {}, {}, []
    for seed in plan["fit_seeds"]:
        fit = fits[str(seed)]
        for family in plan["families"]:
            candidates = fit["families"][family]["candidates"]
            selected = min(candidates,key=lambda x:(x["validation_nll"],x["width"]))
            assert selected["width"]==fit["families"][family]["selected_width"]
            path=base/"fits"/f"{family}_{seed}_w{selected['width']}.npz"
            models[seed,family]=dict(np.load(path))
            candidate_status.extend({"seed":seed,"family":family,"width":c["width"],
                "budget_exhausted":c["budget_exhausted"],"validation_plateau_stop":c["validation_plateau_stop"]} for c in candidates)
        chosen=min(plan["ordinary_core_families"],key=lambda f:(fit["families"][f]["validation_nll"],f))
        assert chosen==fit["selected_ordinary_family"]
        ordinary_families[seed]=chosen
    worlds={}
    with gzip.open(base/"evaluation/worlds.jsonl.gz","rt") as stream:
        for line in stream:
            row=json.loads(line);worlds[row["condition"],row["world"]]=row["episode"]
    config=plan["config"]
    indexed,ticks,max_state_error={ },0,0.
    with gzip.open(base/"evaluation/runs.jsonl.gz","rt") as stream:
        for line in stream:
            run=json.loads(line)
            seed,family=run["fit_seed"],run["family"]
            episode=worlds[run["condition"],run["world"]]
            physics=episode["calibration"]["estimated"]
            obs={"time":0.,"x":episode["initial_x"],"refractory_remaining":0.,"content_probs":[.2]*5,"has_read":False}
            hidden=None if seed is None else np.zeros(models[seed,family]["out"].shape[0])
            budget,pending,stopped,reads=config["budget"],None,False,0
            probabilities_at_deadlines={}
            for tick,row in enumerate(run["trace"]):
                assert tick==row["tick"]
                now=tick*config["dt"]
                fresh=pending==tick
                if fresh:
                    obs={"time":now,"x":episode["path"]["x"][tick],
                        "refractory_remaining":episode["path"]["refractory_remaining"][tick],
                        "content_probs":np.eye(5)[episode["path"]["content"][tick]].tolist(),"has_read":True}
                    assert row["observed"]==obs
                    pending=None
                else:
                    assert row["observed"] is None
                assert row["visible_observation"]==obs
                if seed is None:
                    probability=analytic_probability(obs,now,physics)
                    assert row["state"] is None
                else:
                    packet=np.array([0 if tick==0 else config["dt"],fresh,obs["has_read"],obs["x"],obs["refractory_remaining"],
                        *obs["content_probs"],now-obs["time"],physics["nu"],physics["sigma"],physics["reset"],physics["refractory"],now])
                    hidden,probability=model_step(models[seed,family],family,packet,hidden)
                    error=float(np.max(abs(hidden-row["state"])))
                    max_state_error=max(max_state_error,error);assert error<2e-10
                close(probability,row["probabilities"])
                if tick in config["deadlines"]:
                    probabilities_at_deadlines[tick]=probability
                action=row["action"]
                if tick==config["ticks"] or stopped:
                    assert action is None
                elif budget<=0 or not any(d>tick for d in config["deadlines"]):
                    assert action=="STOP"
                elif run["controller"]=="lightweight":
                    detail=row["policy_detail"]
                    expected="READ" if detail["forecast_error"]>config["light_threshold"] and min(d for d in config["deadlines"] if d>tick)-tick<=2 else "WAIT"
                    assert action==expected
                else:
                    values=row["policy_detail"]["candidate_values"]
                    best=max(values,key=lambda r:(r["net_value"],-r["arrival_tick"]))
                    expected="STOP" if best["net_value"]<=0 else ("READ" if best["arrival_tick"]==tick+1 else "WAIT")
                    assert action==expected
                if action=="READ":
                    budget-=1;reads+=1;pending=tick+1
                if action=="STOP":stopped=True
                assert row["budget_after"]==budget and row["read_reveal_tick"]==pending
                ticks+=1
            correct,nll,brier=[],[],[]
            for pred in run["predictions"]:
                tick=pred["tick"];p=probabilities_at_deadlines[tick];truth=episode["path"]["content"][tick]
                close(p,pred["probabilities"]);assert truth==pred["truth_for_scoring_only"]
                correct.append(int(p.argmax()==truth));nll.append(-np.log(max(p[truth],1e-12)))
                brier.append(np.sum((p-np.eye(5)[truth])**2))
            assert len(correct)==len(config["deadlines"])
            for name,value in {"accuracy":np.mean(correct),"reads":reads,"read_cost":reads*config["read_cost"],
                    "net_reward":np.mean(correct)-reads*config["read_cost"],"nll":np.mean(nll),"brier":np.mean(brier)}.items():
                close(value,run["summary"][name])
            key=run["condition"],run["world"],seed,family,run["controller"]
            assert key not in indexed;indexed[key]=run
    assert len(indexed)==len(worlds)*(4+6*len(plan["fit_seeds"]))
    extension_checks=None
    if (base/"EXTENSION_PLAN.json").exists():
        extension=json.loads((base/"EXTENSION_PLAN.json").read_text())
        original=Path(extension["base_directory"])
        if not original.exists():original=base.parent/"development002"
        assert sha(original/"PLAN.json")==extension["base_plan_sha256"]
        assert sha(original/"FIT.json")==extension["base_fit_sha256"]
        assert sha(original/"FROZEN_MODELS.json")==extension["base_frozen_models_sha256"]
        assert sha(base/"source_snapshot/extend.py")==extension["extension_source_sha256"]
        old_plan=json.loads((original/"PLAN.json").read_text())
        old_fit=json.loads((original/"FIT.json").read_text())
        candidates=sorted((int(seed),family,c["width"]) for seed,report in old_fit.items()
            for family,item in report["families"].items() for c in item["candidates"] if c["budget_exhausted"])
        assert candidates==sorted(tuple(x) for x in extension["candidates"])
        assert plan["world_namespace"]!=old_plan["world_namespace"]
        unchanged=0
        for seed,report in old_fit.items():
            assert sha(base/"fits"/f"data_{seed}.npz")==sha(original/"fits"/f"data_{seed}.npz")
            for family,item in report["families"].items():
                for candidate in item["candidates"]:
                    width=candidate["width"]
                    if (int(seed),family,width) not in candidates:
                        path=f"{family}_{seed}_w{width}.npz"
                        assert sha(base/"fits"/path)==sha(original/"fits"/path);unchanged+=1
                    else:
                        updated=next(c for c in fits[seed]["families"][family]["candidates"] if c["width"]==width)
                        assert updated["validation_nll_history"][:321]==candidate["validation_nll_history"]
                        assert updated["repeated_epoch0_to320_validation_exact"] is True
                        assert updated["repeated_epoch320_best_weights_exact"] is True
        with gzip.open(original/"evaluation/worlds.jsonl.gz","rt") as stream:
            old_world_seeds={json.loads(line)["episode"]["seed"] for line in stream}
        assert not old_world_seeds&{episode["seed"] for episode in worlds.values()}
        extension_checks={"only_predeclared_exhausted_candidates_extended":candidates,
            "unchanged_candidate_checkpoint_hashes":unchanged,
            "all_training_data_hashes_unchanged":True,"first321_validation_values_exact":True,
            "new_world_seeds_disjoint":True,
            "scope":"Additional validation-only budget rule, not the initial registered maximum; repeated prefix CPU charged anew"}
    effects={}
    for condition in plan["conditions"]:
        paired=[];mlp=[]
        for seed in plan["fit_seeds"]:
            ordinary=ordinary_families[seed]
            for world in range(plan["worlds_per_condition"]):
                a=indexed[condition,world,None,"analytic","task_value"]
                h=indexed[condition,world,None,"exact_history","task_value"]
                for x,y in zip(a["trace"],h["trace"]):
                    close(x["probabilities"],y["probabilities"]);assert x["action"]==y["action"]
                paired.append(a["summary"]["net_reward"]-indexed[condition,world,seed,ordinary,"task_value"]["summary"]["net_reward"])
                mlp.append(a["summary"]["net_reward"]-indexed[condition,world,seed,"mlp","task_value"]["summary"]["net_reward"])
        close(np.mean(paired),summary["conditions"][condition]["contrasts"]["D-B"]["mean"])
        close(np.mean(mlp),summary["conditions"][condition]["contrasts"]["D-M"]["mean"])
        effects[condition]={"D_minus_B":float(np.mean(paired)),"D_minus_MLP":float(np.mean(mlp)),"D_minus_exact_history":0.}
    return {"runs_reconstructed":len(indexed),"tick_states_reconstructed":ticks,
            "maximum_hidden_state_error":max_state_error,"effects":effects,"candidate_status":candidate_status,
            "validation_only_extension_checks":extension_checks,
            "planner_scope":"Actual access chronology and state/probability/head/score replay; saved candidate values checked for decision consistency, full stochastic hypothetical planner not rerun",
            "scope":"Original finite synthetic perfect-READ renewal process; not raw AV or strong-baseline qualification"}
