"""Freeze and run R14 true-world deployed-policy audits on new random tapes."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
from scipy.stats import t

from .audit import audit_prefix, choose_actor, clone_actor, conditional_posterior
from .upstream.cell import Cell
from .upstream.data import EpisodeOwner, generate_episode_tapes
from .upstream.estimators import restore_model
from .upstream.task_value import ExactBeliefDP


HERE = Path(__file__).resolve().parent
CHECKPOINTS = HERE / "upstream/checkpoints"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+"\n")


def source_files():
    paths = list(HERE.glob("*.py")) + list((HERE/"upstream").glob("*.py"))
    paths += [HERE/n for n in ("PROTOCOL.json", "UPSTREAM.json")]
    paths += list((HERE/"upstream").rglob("*.json"))
    return {str(p.relative_to(HERE)): digest(p) for p in sorted(paths)}


def verify():
    freeze = json.loads((HERE/"SOURCE_FREEZE.json").read_text())
    if freeze["files"] != source_files():
        raise ValueError("R14 sources/checkpoints changed after the registered freeze")
    upstream = json.loads((HERE/"UPSTREAM.json").read_text())
    for row in upstream["files"]:
        if digest(HERE/row["destination"]) != row["copied_sha256"]:
            raise ValueError("Inherited source or checkpoint differs: "+row["destination"])
    return freeze


def metric_average(rows):
    count = sum(weight for _, weight in rows)
    result = {"prefix_occurrences":count, "unique_prefixes":len(rows)}
    for key in ("one_step_regret", "stop_deficit"):
        result[key] = sum(row[key]*weight for row,weight in rows)/count if count else None
    valid = [(row,weight) for row,weight in rows if row["advantage_absolute_error_mean"] is not None]
    result["advantage_mae"] = sum(row["advantage_absolute_error_mean"]*weight for row,weight in valid)/sum(w for _,w in valid) if valid else None
    pair_mass = sum(row["rank_pairs"]*weight for row,weight in rows)
    result["rank_agreement"] = sum(row["rank_correct"]*weight for row,weight in rows)/pair_mass if pair_mass else None
    result["below_best_prefix_stop_count"] = sum(weight for row,weight in rows if row["stop_deficit"] > 1e-10)
    result["reset_strictly_best_count"] = sum(weight for row,weight in rows if row["reset_strictly_best"])
    result["selected_reset_count"] = sum(weight for row,weight in rows if row["selected"] == "RESET")
    result["max_mass_error"] = max((abs(x-1.) for row,_ in rows for x in row["true_qpi"]["leaf_mass"].values()),default=0.)
    result["max_decomposition_error"] = max((row["decomposition_max_error"] for row,_ in rows),default=0.)
    result["mean_absolute_decomposition"] = {key:sum(weight*np.mean(list(map(abs,row["decomposition"][key].values()))) for row,weight in rows)/count if count else None for key in ("state_estimation","continuation_policy","world_model")}
    return result


def run_case(seed, domain, protocol, output, selections):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    folder = output/str(seed)/domain
    folder.mkdir(parents=True)
    ordinary = selections[str(seed)]["kind"]
    kinds = (ordinary,"hx_distribution")
    fits = {kind:json.loads((CHECKPOINTS/str(seed)/(kind+".json")).read_text()) for kind in kinds}
    models = {kind:fit["selected_model"] for kind,fit in fits.items()}
    fitted_cell = restore_model(models["hx_distribution"]).build_cell()
    true_cell = Cell()
    true_world, fitted_world = ExactBeliefDP(true_cell), ExactBeliefDP(fitted_cell)
    tape_seed = protocol["tape_seed_offsets"][domain]+seed
    tapes = generate_episode_tapes(tape_seed,protocol["episodes_per_seed_domain"],
                                   protocol["horizon"],protocol["domains"][domain])
    order = list(protocol["arms"])
    np.random.default_rng(seed+(domain=="ood")).shuffle(order)
    all_results, comparisons = {}, {}
    with gzip.open(folder/"episodes.jsonl.gz","wt") as episode_log, gzip.open(folder/"prefixes.jsonl.gz","wt") as prefix_log:
        for arm in order:
            kind, control = protocol["arms"][arm]
            kind = ordinary if kind=="ordinary" else kind
            model = restore_model(models[kind])
            planner = ExactBeliefDP(fitted_cell)
            prefix_states, episodes = {}, []
            execution_start = time.process_time()
            for index,tape in enumerate(tapes):
                owner = EpisodeOwner(true_cell,tape,protocol["budget"])
                model.start(fitted_cell.prior)
                tp,fp = true_cell.prior.copy(),fitted_cell.prior.copy()
                prefix, actions, references = [],[],[]
                while True:
                    schedule,budget = owner.remaining_schedule,owner.remaining_reads
                    key = json.dumps([prefix,list(schedule),budget],separators=(",",":"))
                    prefix_id = hashlib.sha256(key.encode()).hexdigest()
                    if key not in prefix_states:
                        prefix_states[key] = dict(id=prefix_id,model=clone_actor(model),true=tp.copy(),fitted=fp.copy(),
                            schedule=schedule,budget=budget,prefix=list(prefix),occupancy=0)
                    prefix_states[key]["occupancy"] += 1
                    references.append(prefix_id)
                    action = choose_actor(model,planner,schedule,budget,control)
                    actions.append(action)
                    if action.startswith("STOP"):
                        terminal = owner.finish(int(action[-1]))
                        break
                    observation = owner.advance(action)
                    model.step(observation["input"])
                    tp = conditional_posterior(true_world,tp,observation)
                    fp = conditional_posterior(fitted_world,fp,observation)
                    prefix.append([action,observation["token"],observation["dt"]])
                terminal.update(episode=index,arm=arm,actions=actions,prefix_ids=references,
                                causal_inputs=prefix,public_schedule=list(tape.dt))
                episodes.append(terminal)
                episode_log.write(json.dumps(terminal,sort_keys=True,allow_nan=False)+"\n")
            execution_cpu = time.process_time()-execution_start
            audit_start = time.process_time()
            audit_planner = ExactBeliefDP(fitted_cell)
            rows,roots,occupied = [],[],[]
            for state in prefix_states.values():
                row = audit_prefix(true_world,fitted_world,state["model"],state["true"],state["fitted"],
                                   state["schedule"],state["budget"],audit_planner,control)
                row.update(prefix_id=state["id"],arm=arm,kind=kind,control=control,
                           causal_prefix=state["prefix"],occupancy=state["occupancy"])
                prefix_log.write(json.dumps(row,sort_keys=True,allow_nan=False)+"\n")
                pair=(row,state["occupancy"])
                rows.append(pair)
                (occupied if state["prefix"] else roots).append(pair)
            audit_cpu = time.process_time()-audit_start
            root_count = sum(w for _,w in roots)
            root_value = sum(row["true_qpi"]["q"][row["selected"]]*w for row,w in roots)/root_count
            all_results[arm] = dict(kind=kind,control=control,episodes=len(episodes),
                mean_utility=float(np.mean([x["utility"] for x in episodes])),
                mean_reward=float(np.mean([x["reward"] for x in episodes])),
                accuracy=float(np.mean([x["correct"] for x in episodes])),
                mean_task_cost=float(np.mean([x["cost"] for x in episodes])),
                counts={a:sum(x["counts"][a] for x in episodes) for a in ("READ","WAIT","RESET")},
                initial_stop_count=sum(len(x["actions"])==1 for x in episodes),
                exact_root_expected_utility=root_value,all_prefixes=metric_average(rows),
                roots=metric_average(roots),occupied_prefixes=metric_average(occupied),
                execution_and_capture_cpu_seconds=execution_cpu,audit_cpu_seconds=audit_cpu,
                checkpoint_sha256=digest(CHECKPOINTS/str(seed)/(kind+".json")))
            comparisons[arm]=episodes
    for metric in ("mean_utility","exact_root_expected_utility"):
        a,b,c,d=[all_results[x][metric] for x in "ABCD"]
        all_results[metric+"_contrasts"]={"B-A":b-a,"D-C":d-c,"C-A":c-a,"D-B":d-b,"interaction":(d-c)-(b-a)}
    result=dict(seed=seed,domain=domain,tape_seed=tape_seed,order=order,arms=all_results,
        paired_tapes=len(tapes),causal_input_schema="10 raw features; no evaluator belief/state/fee fed to actor",
        source_freeze_sha256=digest(HERE/"SOURCE_FREEZE.json"),
        evidence={p.name:dict(sha256=digest(p),bytes=p.stat().st_size) for p in folder.glob("*.gz")},
        true_world_identity=true_world.model_identity,fitted_world_identity=fitted_world.model_identity,
        cpu_seconds=time.process_time()-started_cpu,wall_seconds=time.perf_counter()-started_wall)
    write(folder/"RESULT.json",result)
    print(json.dumps({"completed":f"{seed}/{domain}","cpu_seconds":result["cpu_seconds"]}),flush=True)
    return result


def summarize(results):
    output={"scope":"new evaluation tapes of eight inherited fits; descriptive audit, no candidate selection or new superiority test","domains":{}}
    for domain in ("iid","ood"):
        cases=[r for r in results if r["domain"]==domain]
        summary={"fit_count":len(cases),"paired_tapes":sum(r["paired_tapes"] for r in cases),"contrasts":{},"arms":{}}
        for metric in ("mean_utility","exact_root_expected_utility"):
            summary["contrasts"][metric]={}
            for contrast in ("B-A","D-C","C-A","D-B","interaction"):
                values=np.array([r["arms"][metric+"_contrasts"][contrast] for r in cases])
                half=t.ppf(.975,len(values)-1)*values.std(ddof=1)/np.sqrt(len(values))
                summary["contrasts"][metric][contrast]=dict(mean=float(values.mean()),ci95_descriptive=[float(values.mean()-half),float(values.mean()+half)],fit_values=values.tolist())
        for arm in "ABCD":
            rows=[r["arms"][arm] for r in cases]
            entry={key:float(np.mean([r[key] for r in rows])) for key in ("mean_utility","accuracy","mean_task_cost","exact_root_expected_utility")}
            entry["counts"]={a:sum(r["counts"][a] for r in rows) for a in ("READ","WAIT","RESET")}
            entry["initial_stop_count"]=sum(r["initial_stop_count"] for r in rows)
            for stage in ("roots","occupied_prefixes","all_prefixes"):
                total=sum(r[stage]["prefix_occurrences"] for r in rows)
                stage_row=dict(prefix_occurrences=total,unique_prefixes=sum(r[stage]["unique_prefixes"] for r in rows))
                for key in ("one_step_regret","stop_deficit","advantage_mae","rank_agreement"):
                    usable=[r[stage] for r in rows if r[stage][key] is not None]
                    stage_row[key]=float(np.mean([r[key] for r in usable])) if usable else None
                for key in ("below_best_prefix_stop_count","reset_strictly_best_count","selected_reset_count"):
                    stage_row[key]=sum(r[stage][key] for r in rows)
                for key in ("max_mass_error","max_decomposition_error"):
                    stage_row[key]=max(r[stage][key] for r in rows)
                stage_row["mean_absolute_decomposition"]={key:(float(np.mean([r[stage]["mean_absolute_decomposition"][key] for r in rows if r[stage]["prefix_occurrences"]])) if total else None) for key in ("state_estimation","continuation_policy","world_model")}
                entry[stage]=stage_row
            summary["arms"][arm]=entry
        output["domains"][domain]=summary
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("freeze","run"))
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    if args.stage=="freeze":
        path=HERE/"SOURCE_FREEZE.json"
        if path.exists():
            raise FileExistsError("Do not replace an existing source freeze")
        write(path,dict(schema="hcsn.r14.value.freeze.v1",files=source_files(),unix_time=time.time(),evaluation_started=False))
        return
    verify()
    if args.out is None:
        parser.error("--out is required")
    output=args.out.resolve()
    output.mkdir(parents=True,exist_ok=False)
    wall,cpu=time.perf_counter(),time.process_time()
    write(output/"STARTED.json",dict(source_freeze_sha256=digest(HERE/"SOURCE_FREEZE.json"),unix_time=time.time()))
    protocol=json.loads((HERE/"PROTOCOL.json").read_text())
    selections=json.loads((HERE/"upstream/CANDIDATE_FREEZE.json").read_text())["selection"]
    results=[]
    try:
        for seed in protocol["seeds"]:
            for domain in protocol["domains"]:
                results.append(run_case(seed,domain,protocol,output,selections))
        write(output/"SUMMARY.json",summarize(results))
        verify()
    except Exception as error:
        write(output/"FAILURE.json",dict(type=type(error).__name__,error=str(error),completed=len(results)))
        raise
    write(output/"PROCESS_BODY.json",dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
          max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,energy_joules=None,
          python=platform.python_version(),numpy=np.__version__,new_training_cpu_seconds=0.,
          scope="body includes new data generation, actual rollout, complete counterfactual trees and evidence I/O; excludes interpreter startup and this last receipt; outer process receipt is authoritative"))


if __name__=="__main__":
    main()
