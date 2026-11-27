"""Read-only R3 complete-census, raw-metric and saved-model verification."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np


def require(condition, reason):
    if not condition: raise ValueError(reason)


def verify(source, root, out):
    sys.path.insert(0, str(source.resolve()))
    from integral import fresh_terminals, representation_witness
    from integral_sweep import name_for, specs
    from integral_trial import model_for, panels, sources, terminal_for
    from models import assign, vector
    from problem import decimal_oracle, make_world, terminals
    from run import digest, predictions, residual, scores, write_json
    from structured import new_terminals, panel_world, priced_decisions
    import torch

    t=time.process_time(), time.perf_counter()
    out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((root/'PLAN.json').read_text());complete=json.loads((root/'COMPLETE.json').read_text())
    require(complete['plan_sha256']==digest((root/'PLAN.json').read_bytes()),'sweep plan changed')
    require(plan['source_sha256']==sources(),'source mismatch')
    require(plan['runs']==specs(),'different experiment plan')
    require([r['name'] for r in complete['census']]==[name_for(s) for s in specs()],'incomplete census')
    require(complete['completed']==50 and complete['failed']==0,'run failures')
    reference={}
    for name,family,bits,horizon,intervention in panels():
        w=panel_world(bits,intervention)
        reference[name]=decimal_oracle(w,terminal_for(w,family,name),horizon)
    # Independent factual probability reference, separate from entropic recursion.
    w=panel_world(2,'joint');g=fresh_terminals(w,'indicator')
    np.testing.assert_allclose(reference['probability_joint'][-1],g@np.linalg.matrix_power(w.kernel(),3).T,atol=1e-14)
    rows=[];reports={};replaymax=0.;scalar_count=0;changed=0;replaypanels=0
    for entry in complete['census']:
        require(entry['status']=='completed','failed member')
        folder=root/entry['name'];data=(folder/'REPORT.json').read_bytes();r=json.loads(data)
        require(digest(data)==entry['report_sha256'],'report hash mismatch')
        cp=json.loads((folder/'PLAN.json').read_text())
        require(r['plan_sha256']==digest((folder/'PLAN.json').read_bytes()),'child plan mismatch')
        require(cp['source_sha256']==plan['source_sha256'],'child source mismatch')
        for field in ('family','optimizer','seed','intervals'):
            require(r[field]==cp[field]==entry[field],'identity mismatch: '+field)
        require(r['cpu_cap']==cp['cpu_cap']==entry['cpu_seconds'],'budget mismatch')
        seal=json.loads((folder/'PREDICTIONS_SEAL.json').read_text())
        require(digest((folder/'PREDICTIONS.npz').read_bytes())==r['prediction_sha256']==seal['sha256'],'prediction hash mismatch')
        raw=np.load(folder/'PREDICTIONS.npz',allow_pickle=False);oracle=np.load(folder/'ORACLES.npz',allow_pickle=False)
        m=model_for(r['family'],r['seed'],r['intervals'])
        if m is not None:
            init=np.load(folder/'INITIAL.npy',allow_pickle=False);weights=np.load(folder/'WEIGHTS.npy',allow_pickle=False)
            np.testing.assert_array_equal(vector(m),init)
            require(digest(init.tobytes())==r['initial_sha256'],'initial weight mismatch')
            require(digest(weights.tobytes())==r['selected_sha256']==seal['weights'],'selected weight mismatch')
            require(weights.size==r['parameter_count'],'weight count mismatch')
            change=not np.array_equal(init,weights);changed+=int(change)
            if r['optimizer']=='none':require(not change,'untrained control changed')
            assign(m,weights)
            with torch.no_grad():
                world=make_world();train=torch.tensor(terminals(world,'train'))
                mse=float(residual(m,world.tensor(),train,3).square().sum())
            require(np.isclose(mse,r['training_mse'],rtol=1e-12,atol=1e-15),'training loss mismatch')
        for name,family,bits,horizon,intervention in panels():
            w=panel_world(bits,intervention);term=terminal_for(w,family,name)
            np.testing.assert_array_equal(raw[name+'_terminal'],term)
            np.testing.assert_array_equal(oracle[name],reference[name])
            require(digest(raw[name].tobytes())==r['timings'][name]['sha256'],'panel hash mismatch')
            recalc=scores(raw[name],reference[name],w,name=='probability_joint')
            recalc.update(priced_decisions(raw[name],reference[name]))
            u=w.risk*(raw[name][:-1,...,w.left]-raw[name][:-1,...,w.right])
            recalc['derivative_grid_tail_fraction']=float(np.mean(np.abs(u)>4))
            for k,v in recalc.items():
                actual=r['metrics'][name][k]
                require(actual==v if v is None or isinstance(v,bool) else np.isclose(actual,v,atol=1e-14,rtol=1e-12),'metric mismatch: '+k)
            again=predictions(m,'D' if m is None else 'B',w.tensor(),term,horizon)
            error=float(np.max(np.abs(again-raw[name])))
            require(error<=1e-13,'saved-model replay mismatch')
            replaymax=max(replaymax,error);scalar_count+=raw[name][1:].size;replaypanels+=1
            rows.append(dict(run=entry['name'],family=r['family'],optimizer=r['optimizer'],seed=r['seed'],
                             intervals=r['intervals'],cpu_cap=r['cpu_cap'],panel=name,rmse=recalc['rmse'],
                             max_error=recalc['final_max_error'],priced_regret=recalc['priced_decision_regret'],
                             priced_accuracy=recalc['priced_decision_accuracy'],tail_fraction=recalc['derivative_grid_tail_fraction'],
                             invalid_probability=recalc.get('probability_invalid_fraction'),training_mse=r['training_mse'],
                             training_cpu=r['fit']['training_cpu_seconds'],child_cpu=entry['child_cpu'],child_wall=entry['child_wall'],
                             peak_rss=r['process_peak_rss_bytes']))
        reports[entry['name']]=r
    pairs=[]
    for family,cap in [('raw',8),('mixture',8),('integral',2),('integral',8)]:
        for seed in (11,23,47):
            b=reports[f'{family}-adam-s{seed}-b{cap}-g64'];c=reports[f'{family}-trf-s{seed}-b{cap}-g64']
            require(b['initial_sha256']==c['initial_sha256'] and b['parameter_count']==c['parameter_count']==65,'B/C mismatch')
            rb=b['metrics']['new_composed']['rmse'];rc=c['metrics']['new_composed']['rmse']
            pairs.append(dict(family=family,seed=seed,cpu_cap=cap,B_rmse=rb,C_rmse=rc,B_over_C=rb/rc))
    # Disclosed constructive approximation witness on TRAINING terminals only.
    world=make_world();g=terminals(world,'train');truth=decimal_oracle(world,g,3);witness=[]
    for n in (16,32,64,128):
        p=predictions(representation_witness(n),'B',world.tensor(),g,3)
        witness.append(dict(intervals=n,train_rmse=float(np.sqrt(np.mean((p[1:]-truth[1:])**2))),
                            train_max_error=float(np.max(np.abs(p-truth))),learned=False))
    overlap={}
    for f in ('uniform','composed','indicator'):
        a={x.tobytes() for x in fresh_terminals(world,f)};old={x.tobytes() for x in new_terminals(world,f)}
        overlap[f]=dict(unique=len(a),overlap_round2=len(a & old),replacement=False)
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    write_json(out/'PAIRED.json',pairs);write_json(out/'WITNESS.json',witness)
    receipt=dict(verified_runs=50,verified_panels=replaypanels,scalar_predictions=int(scalar_count),
                 changed_models=changed,saved_models=49,bc_pairs=len(pairs),max_replay_error=replaymax,
                 terminal_overlap=overlap,source_sha256=sources(),training_selection=False,
                 audit_cpu=time.process_time()-t[0],audit_wall=time.perf_counter()-t[1],production_authorized=False)
    write_json(out/'AUDIT.json',receipt)
    return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(verify(a.source,a.runs,a.out),sort_keys=True))


if __name__=='__main__':main()
