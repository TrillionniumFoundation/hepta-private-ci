"""Give both same-head gradient controls the already selected stronger anchor; no further search."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import time
import numpy as np
import torch
from study_edit import SEEDS,fit_one,read,write,sha,load_arrays,npz
from rls_core import projected,summarize,gate,target_labels,outcomes,select_masks
from verify_release import bundle,entry,calc

ARMS=('rls-32','recent-32','quad-32','ce-32')
ANCHOR_SEAL='77c511996a1fdf5782d2f628af19c4fbb6f883ae7d194fe7b2bb0d609890053c'


def run(task):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    old=task/'run';d=task/'matched_mu32';d.mkdir(exist_ok=True)
    assert sha(task/'preservation_diagnostic/development_seal.json')==ANCHOR_SEAL and read(task/'preservation_diagnostic/development_seal.json')['mu']==32
    main=read(old/'development_seal.json');fitcost={};records={};picks={};roles={}
    for seed in SEEDS:
        org=old/str(seed);sub=d/str(seed);sub.mkdir(exist_ok=True);src=org/'basis.npz';dst=sub/'basis.npz'
        assert sha(src)==main['parents'][str(seed)]['archive_sha256']
        if not dst.is_file():os.link(src,dst)
        assert sha(src)==sha(dst)
        for arm in ARMS:
            sr=fit_one(d,seed,arm);key=f'{seed}/{arm}';records[key]={};picks[key]={};fitcost[key]={}
            for j,rec in sr.items():
                eligible=[int(i) for i,r in rec['records'].items() if r['gate']]
                picks[key][j]={'full':max(map(int,rec['records'])),'first_dev_gate':min(eligible) if eligible else None}
                records[key][j]={'weights_sha256':rec['archive_sha256'],'stage_sha256':sha(sub/arm/f'stage{j}.json')}
                fitcost[key][j]=rec['through_stage_s']
                if arm=='rls-32':
                    with np.load(sub/arm/f'stage{j}.npz') as a,np.load(task/'preservation_diagnostic'/f'heads-{seed}.npz') as b:
                        assert np.array_equal(a['W0'],b['W'+j])
    seal={'prior_development_selection':ANCHOR_SEAL,'protocol_sha256':sha(task/'MATCHED_STRONG_ANCHOR.md'),'source_sha256':sha(Path(__file__)),
          'picks':picks,'registry':records}
    path=d/'development_seal.json'
    if path.exists():assert seal==read(path)
    else:write(path,seal)
    profiles={};effects={};all_scores={};vectors={};timing={};gates={};verror=0.;primary_prep=read(old/'prepared.json')['shared_input_load_s']
    for seed in SEEDS:
        b=load_arrays(old/str(seed)/'held.npz');y=b['held_y'];ids=b['held_ids'];actors=np.array([x.split('_')[0] for x in ids])
        baseline=projected(b['held'],b['text'],b['W0'])
        parent_basis=main['parents'][str(seed)];held=read(old/str(seed)/'held.json')
        setup=primary_prep+parent_basis['parent_deserialization_s']+parent_basis['keys_and_validation_and_save_s']+held['parent_deserialization_s']+held['keys_and_validation_and_save_s']
        for arm in ARMS:
            key=f'{seed}/{arm}';sub=d/key;all_scores[key]={};timing[key]={};gates[key]={};sum_held=0.
            for stage in range(6):
                j=str(stage);p=sub/f'stage{j}.npz';assert sha(p)==records[key][j]['weights_sha256']
                w=load_arrays(p);note=read(sub/f'stage{j}.json');m0=summarize(baseline,baseline,y,stage);all_scores[key][j]={};archive={}
                verify_s=0.;bt=time.perf_counter()
                for n,rec in note['records'].items():
                    z=projected(b['held'],b['text'],w['W'+n]);archive['scores'+n]=z.numpy();m=summarize(z,baseline,y,stage)
                    if int(n)==picks[key][j]['full']:vectors[seed,arm,stage]=outcomes(z,baseline,y,stage)
                    all_scores[key][j][n]={'metrics':m,'held_gate':bool(gate(m,m0))}
                    ti=time.perf_counter()
                    e=float(abs(calc(b['held'].numpy(),b['text'].numpy(),w['W'+n].numpy())-z.numpy()).max())
                    verror=max(verror,e);assert e<3e-5
                    verify_s+=time.perf_counter()-ti
                pp=sub/f'held{j}.npz';npz(pp,ids=ids,original_y=y.numpy(),edited_y=target_labels(y,stage).numpy(),**archive)
                sum_held+=time.perf_counter()-bt-verify_s
                selection=picks[key][j]['first_dev_gate']
                gates[key][j]=bool(selection is not None and all_scores[key][j][str(selection)]['held_gate'])
                all_scores[key][j]['archive_sha256']=sha(pp)
                timing[key][j]={'through_all_qualification_s':setup+fitcost[key][j]+sum_held,'through_fit_and_dev_s':fitcost[key][j],
                                'source_feature_and_parent_io_s':setup,'held_scoring_and_save_s':sum_held}
    who=np.unique(actors);ix=np.random.default_rng(83573).integers(len(who),size=(4000,len(who)))
    for arm in ARMS:
        profiles[arm]={};effects[arm]={}
        for j in range(6):
            v=[];cost=[]
            for seed in SEEDS:
                key=f'{seed}/{arm}';st=str(j);v.append(gates[key][st]);cost.append(timing[key][st]['through_all_qualification_s'])
            profiles[arm][str(j)]={'passing_seeds':sum(v),'qualification_mean_s':float(np.mean(cost)),
                                   'interpretable_all_three_cost_s':float(np.mean(cost)) if all(v) else None}
            effects[arm][str(j)]={}
            for g,m0 in select_masks(y,j).items():
                mask=m0.numpy()
                if not mask.any():continue
                counts=np.array([np.sum(mask&(actors==v)) for v in who])
                dvec=np.mean([vectors[seed,'rls-32',j]['nll']-vectors[seed,arm,j]['nll'] for seed in SEEDS],axis=0)
                sums=np.array([dvec[mask&(actors==v)].sum() for v in who]);effects[arm][str(j)][g]={'mean':float(dvec[mask].mean()),
                    'CI95':np.quantile(sums[ix].sum(1)/counts[ix].sum(1),[.025,.975]).tolist()}
    doc={'selection_sha256':sha(path),'fixed_mu':32,'profiles':profiles,'cold':all_scores,'timing':timing,'paired_nll_RLS_minus_arm':effects,
         'cross_algorithm_FP64_score_parity':verror,'separate_original_mu_search_s':read(task/'preservation_diagnostic/development_seal.json')['development_s']}
    write(d/'terminal.json',doc)
    release=task/'release_matched';release.mkdir(exist_ok=True)
    for seed in SEEDS:
        for arm in ARMS:
            loc=d/str(seed)/arm;files={p.name:p for p in loc.iterdir() if p.is_file()}
            assert len(files)==18;bundle(release/f'{seed}-{arm}.tar',files)
    for p in (path,d/'terminal.json',Path(__file__),task/'MATCHED_STRONG_ANCHOR.md'):
        tgt=release/p.name
        if not tgt.exists():os.link(p,tgt)
        assert sha(tgt)==sha(p)
    obs={p.name:entry(p) for p in release.iterdir() if p.name!='manifest.json'}
    write(release/'manifest.json',{'verified':{'dev_candidates':144,'held_head_scores':144,'maximum_fp64_score_error':verror,
                    'recursive_weights_equal_previous_selected_output':True},'terminal_sha256':sha(d/'terminal.json'),'objects':obs})
    print('terminal',sha(d/'terminal.json'),'seal',sha(path),'profiles',json.dumps(profiles),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
