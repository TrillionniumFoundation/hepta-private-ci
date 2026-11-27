"""Independent deterministic score, seal, scope and source readback of the 15 candidates."""
import argparse, hashlib, json, zipfile, io
from pathlib import Path
import numpy as np
from scipy.special import softmax
import torch
SITES={'input_drive.weight','input_drive.bias'}
SEEDS=(107,211,431)
METHODS=('keep','direct','wronglabel','unconditional','bp')
def sha(b): return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--results',type=Path,required=True);ap.add_argument('--parents',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();seal=json.loads((a.results/'seal.json').read_text())
    rows=[];passed=[]
    for seed in SEEDS:
        with zipfile.ZipFile(a.parents/'evidence'/f'hcsn_bp-{seed}.zip') as z:
            parent=torch.load(io.BytesIO(z.read(f'hcsn_bp-{seed}/selected.pt')),weights_only=True,map_location='cpu')
            parent_train=json.loads(z.read(f'train-hcsn_bp-{seed}-process.json'))['wall_seconds']
            parent_test=json.loads(z.read(f'test-hcsn_bp-{seed}-process.json'))['wall_seconds']
        grids={}
        for arm in METHODS:
            d=a.results/str(seed)/arm
            fit=json.loads((d/'fit.json').read_text()); result=json.loads((d/'test.json').read_text())
            assert sha((d/'fit.json').read_bytes())==seal['fit_records'][f'{seed}/{arm}']
            assert sha((d/'selected.pt').read_bytes())==seal['models'][f'{seed}/{arm}']==fit['selected_sha256']
            assert sha((d/'predictions.npz').read_bytes())==result['prediction_sha256']
            assert sha((d/'weights.npz').read_bytes())==fit['candidate_weights_sha256']
            roster=fit['candidates']
            viable=[k for k,v in roster.items() if v['dev']['ar']['acc']>=roster['keep']['dev']['ar']['acc']-.03-1e-12]
            choice=min(viable,key=lambda k:(-roster[k]['dev']['eng']['acc'],roster[k]['dev']['eng']['brier'],roster[k]['dw']))
            assert choice==fit['selected']
            selected=torch.load(d/'selected.pt',weights_only=True,map_location='cpu')
            with np.load(d/'weights.npz',allow_pickle=False) as proposed:
                assert set(proposed.files)==set(roster)
                w=torch.from_numpy(proposed[choice]).float()
                assert torch.equal(w[:-1].T,selected['model']['input_drive.weight']) and torch.equal(w[-1],selected['model']['input_drive.bias'])
            assert set(selected['model'])==set(parent['model'])
            changed=[k for k,v in parent['model'].items() if not torch.equal(selected['model'][k],v)]
            assert set(changed)<=SITES
            assert all(torch.equal(selected['ridge'][k],v) for k,v in parent['ridge'].items())
            assert torch.equal(selected['input_mean'],parent['input_mean']) and torch.equal(selected['input_scale'],parent['input_scale'])
            metrics={}
            with np.load(d/'predictions.npz',allow_pickle=False) as p:
                assert np.isfinite(p['example_drift']).all()
                for lang in ('eng','ar'):
                    y=p[lang+'_y'];v=p[lang+'_scores']; ids=p[lang+'_id']; pred=p[lang+'_class']
                    assert np.isfinite(v).all() and np.array_equal(pred,v.argmax(1))
                    if arm=='keep':grids[lang]=(ids.copy(),y.copy(),pred.copy())
                    assert np.array_equal(grids[lang][0],ids) and np.array_equal(grids[lang][1],y)
                    correct=pred==y; keep=grids[lang][2]==y; diff=correct.astype(int)-keep.astype(int)
                    acc=correct.mean(); brier=((softmax(v.astype('float64'),axis=1)-np.eye(10)[y])**2).sum(1).mean()
                    expect=result['scores'][lang]
                    assert len(y)==expect['n'] and abs(float(acc)-expect['acc'])<1e-14 and abs(float(brier)-expect['brier'])<1e-7
                    metrics[lang]={'n':len(y),'correct':int(correct.sum()),'acc':float(acc),'brier':float(brier),
                                   'delta_acc':float(diff.mean()),'gain_count':int((diff==1).sum()),'forget_count':int((diff==-1).sum())}
                    if lang=='eng':
                        person=np.array([s.split('_')[1] for s in ids]); metrics['by_speaker']={k:float(diff[person==k].mean()) for k in sorted(set(person))}
                    if arm=='keep' and lang=='ar':
                        with zipfile.ZipFile(a.parents/'evidence'/f'hcsn_bp-{seed}.zip') as z:
                            with np.load(io.BytesIO(z.read(f'hcsn_bp-{seed}/test.npz'))) as orig:
                                assert np.array_equal(orig['y'],y) and np.array_equal(orig['pred'],pred)
                                metrics['historical_arabic_max_score_error']=float(np.abs(orig['scores']-v).max())
            wall=fit['time_s']['cold_total_to_save']+result['cold_eval_s']
            gate=(metrics['eng']['delta_acc']>=.02-1e-12 and min(metrics['by_speaker'].values())>=0 and metrics['ar']['delta_acc']>=-.03-1e-12)
            def external(mode):
                file=a.results/'logs'/f'{mode}-{seed}-{arm}.json'
                return json.loads(file.read_text())['cold_process_wall_s'] if file.exists() else None
            rows.append(dict(historical_parent_train_s=parent_train,historical_parent_official_test_s=parent_test,
                             combined_cold_including_historical_parent_s=wall+parent_train+parent_test,
                             fit_external_process_wall_s=external('fit'),evaluate_external_process_wall_s=external('eval'),seed=seed,method=arm,choice=fit['selected'],scope_changed=changed,delta_norm=fit['physical_map_delta_norm'],
                             cold_stages_s=wall,fit_s=fit['time_s']['cold_total_to_save'],cold_eval_s=result['cold_eval_s'],primary_gate=gate,**metrics))
        relevant=[r for r in rows if r['seed']==seed]
        di=next(r for r in relevant if r['method']=='direct');bp=next(r for r in relevant if r['method']=='bp')
        passed.append({'seed':seed,'direct_primary':bool(di['primary_gate']),'bp_primary':bool(bp['primary_gate']),
                       'direct_minus_bp_new_accuracy':di['eng']['acc']-bp['eng']['acc'],
                       'direct_minus_bp_old_accuracy':di['ar']['acc']-bp['ar']['acc'],
                       'cold_bp_over_direct':bp['cold_stages_s']/di['cold_stages_s']})
    out={'all_models':len(rows),'observations_per_family':{'new_english':1000,'old_arabic':2200},
         'paired':passed, 'rows':rows,'official_arabic_keep_labels_match_history_all_parents':True,'strict_preservation_site_only':True,
         'all_direct_primary':all(p['direct_primary'] for p in passed),'all_replacement_gates':all(p['direct_primary'] and min(p['direct_minus_bp_new_accuracy']+.02,p['direct_minus_bp_old_accuracy']+.03)>=-1e-12 and p['cold_bp_over_direct']>1 for p in passed),
         'execution_note':'cold_stages includes process imports after timer start at module start, not OS startup; initial non-BP fits various overlap, final BP fits serial within study and official cold tests serial within study, with concurrent unrelated research on host. External process wall is recorded when available. Prior training and official evaluation are historical costs from the source archives; data acquisition and preprocessing are shared.'}
    a.out.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k!='rows'},indent=2))
if __name__=='__main__':main()
