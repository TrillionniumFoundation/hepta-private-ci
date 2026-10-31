"""Finite-task qualification using real FullHX reads, native physics and processes."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np

from client import (HERE, ZERO, Client, config_from_dict, model_config, policy_from_entries,
                    run_owner, save, sha)
from task import State, World, generate_world, initial, legal


def packet(symbol, seed):
    rng = np.random.default_rng(seed)
    symbols = rng.integers(0, 4, 32).tolist()
    symbols[0], symbols[-1] = symbol, -1
    return {"schema": "hcsn.memory.packet.v1", "symbols": symbols, "dt": [1.] * 32}


def stable_receipt(receipt):
    stable = {k: receipt[k] for k in ("state", "requested", "actual", "observation", "cost", "task_after", "ledger")}
    inner = receipt["inner"]
    if inner is not None:
        stable["inner"] = {k: inner[k] for k in ("cell", "content", "features", "signals_q24", "jumps", "pair_after")}
    return stable


def qualify(binary, output):
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    weights = HERE.parents[1] / "round9_20261031/native/fixtures/fullhx.json"
    evidence = HERE.parent / "value/evidence/confirmation"
    cases = [json.loads((evidence/f"native_case_{i}.json").read_text()) for i in range(8)]
    protocol = {"schema": "hepta.r10.native.protocol.v1", "cases": 8, "world_seeds_per_case": 6,
                "families": ["ordinary", "distribution"],
                "policies": ["oracle", "ordinary", "matched_c1", "analytic", "fixed", "stop"],
                "binary_sha256": sha(binary), "weights_sha256": sha(weights),
                "runner_sha256": sha(Path(__file__)), "tick_micros": 50_000,
                "clock_scope": "declared task ticks; actual CPU/wall time separately measured",
                "model_scope": "frozen real FullHX binary observation from actual 32-symbol file; synthetic evidence task",
                "policy_scope": "precomputed value tables from frozen exported heads; no native head-training claim",
                "energy_measured": False, "production_activation": False}
    save(output/"PROTOCOL.json", protocol)
    data=output/"data"
    data.mkdir()
    templates=[]
    for symbol,seed in ((0,198332),(1,198331)):
        path=data/f"template{symbol}.json"
        save(path,packet(symbol,seed))
        templates.append({"path":str(path),"sha256":sha(path)})
    # Calibration is a separate recorded read. Do not assume model prediction is the first symbol.
    c=config_from_dict(cases[0]["task"])
    calibration=[]
    for symbol in (0,1):
        root=output/f"calibration{symbol}"
        model=output/f"calibration{symbol}.json"
        save(model,model_config(c,[templates[symbol]]*len(c.packets),cases[0]["policies"]["oracle"],"distribution",weights,173))
        world=World(symbol,(symbol,)*len(c.packets),(False,)*len(c.packets))
        row=run_owner(binary,model,root,c,world,policy_from_entries(cases[0]["policies"]["oracle"]),forced_first="READ",only_steps=1)
        calibration.append(row)
    save(output/"CALIBRATION.json",calibration)
    all_runs=[]
    inputs=[]
    restarts=[]
    counterfactuals=[]
    work=output/"work"
    work.mkdir()
    with gzip.open(output/"RECEIPTS.jsonl.gz","wt") as receipts:
        for case_index,case in enumerate(cases):
            c=config_from_dict(case["task"])
            policies=dict(case["policies"])
            # Strong validation-selected fixed rule uses the shared Python finite contract.
            from run import threshold_policy
            threshold=json.loads((evidence/"RESULTS.json").read_text())["fixed_threshold"]
            from oracle import Oracle
            teacher=Oracle(c);teacher.q(initial(c))
            fixed=threshold_policy(threshold)
            policies["fixed"]={s.key:[1.0 if a==fixed(c,s) else 0.0 for a in ("READ","WAIT","STOP")]
                               for s in teacher.states.values()}
            policies["stop"]={s.key:[0.,0.,1.] for s in teacher.states.values()}
            for seed_index in range(6):
                seed=110000+100*case_index+seed_index
                world=generate_world(c,seed)
                payloads=[{"path":str(data/f"missing-{case_index}-{seed_index}-{i}.json"),"sha256":ZERO}
                          if world.failures[i] else templates[world.votes[i]] for i in range(len(c.packets))]
                inputs.append({"case":case_index,"seed":seed,"world":asdict(world),"payloads":payloads})
                for family in protocol["families"]:
                    for method in protocol["policies"]:
                        name=f"c{case_index}-s{seed_index}-{family}-{method}"
                        model=work/(name+".json")
                        save(model,model_config(c,payloads,policies[method],family,weights,seed))
                        policy=policy_from_entries(policies[method])
                        result=run_owner(binary,model,work/name,c,world,policy)
                        receipts.write(json.dumps({"run":name,"trace":result.pop("trace")})+"\n")
                        result.update(name=name,case=case_index,seed=seed,family=family,method=method)
                        all_runs.append(result)
                        if case_index<2 and seed_index==0 and method in ("oracle","analytic"):
                            resumed=run_owner(binary,model,work/(name+"-restart"),c,world,policy,restart=True,forced_first="READ")
                            continuous=run_owner(binary,model,work/(name+"-comparison"),c,world,policy,forced_first="READ")
                            equal=[stable_receipt(x) for x in resumed["trace"]]==[stable_receipt(x) for x in continuous["trace"]]
                            assert equal,(name,"restart changed acknowledged trajectory")
                            assert resumed["processes"]==2
                            restarts.append({"name":name,"equal":equal,"forced_first":"READ","restarted_processes":resumed["processes"]})
                            receipts.write(json.dumps({"run":name+"-restart","trace":resumed["trace"]})+"\n")
                # Fork the entire actual native+content+task frontier after a forced first READ.
                if case_index<4 and seed_index<2:
                    name=f"prefix-c{case_index}-s{seed_index}"
                    model=work/(name+".json")
                    save(model,model_config(c,payloads,policies["oracle"],"distribution",weights,seed))
                    policy=policy_from_entries(policies["oracle"])
                    prefix=run_owner(binary,model,work/name,c,world,policy,forced_first="READ",only_steps=1)
                    state=State(**prefix["state"])
                    branches={}
                    before={p.name:sha(p) for p in (work/name).iterdir() if p.is_file()}
                    for requested in ("READ","WAIT","STOP"):
                        dest=work/(name+"-"+requested)
                        shutil.copytree(work/name,dest)
                        assert before=={p.name:sha(p) for p in dest.iterdir() if p.is_file()}
                        branches[requested]=run_owner(binary,model,dest,c,world,policy,
                            forced_first=requested,start=state,acknowledgement=prefix["task_after"])
                    counterfactuals.append({"case":case_index,"seed":seed,"prefix_state":prefix["state"],
                                           "prefix_task_digest":prefix["task_after"],"files":before,"branches":branches})
    means={}
    for family in protocol["families"]:
        for method in protocol["policies"]:
            group=[r for r in all_runs if r["family"]==family and r["method"]==method]
            means[family+"/"+method]={k:float(np.mean([r[k] for r in group]))
                for k in ("quality","utility","reads","clock","task_cost","cpu_seconds","wall_seconds","peak_child_rss_kib")}
    for method in protocol["policies"]:
        left=[r for r in all_runs if r["family"]=="ordinary" and r["method"]==method]
        right=[r for r in all_runs if r["family"]=="distribution" and r["method"]==method]
        assert all(a["state"]==b["state"] for a,b in zip(left,right))
    report={"schema":"hepta.r10.native.qualification.v1","passed":True,"runs":len(all_runs),
            "all_action_state_cost_decoder_parity":True,"restart_pairs":restarts,
            "cloned_midtrajectory_counterfactual_states":len(counterfactuals),
            "cloned_counterfactual_executions":3*len(counterfactuals),"means":means,
            "native_source_build_required":True,"protocol":protocol,
            "controller_evidence":"policy precedes payload access; whole native state cloned for counterfactuals",
            "physics_task_relation":"finite CTMC propagated on READ/WAIT; task refractory is a separate declared control constraint; latent CTMC firing does not trigger READ",
            "analytic_cell_advantage_established":False,"energy_joules":None,
            "campaign_parent_cpu_seconds":time.process_time()-cpu,"campaign_wall_seconds":time.perf_counter()-started}
    save(output/"INPUTS.json",inputs)
    save(output/"RUNS.json",all_runs)
    save(output/"COUNTERFACTUALS.json",counterfactuals)
    save(output/"REPORT.json",report)
    print("HCSN_NATIVE_REPORT "+json.dumps(report),flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    qualify(args.binary.resolve(),args.output.resolve())
