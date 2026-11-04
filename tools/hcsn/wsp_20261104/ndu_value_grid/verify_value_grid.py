#!/usr/bin/env python3
"""Read-only verification of the frozen value-grid records; no model execution."""
from pathlib import Path
from fractions import Fraction
import argparse, gzip, hashlib, itertools, json
import numpy as np

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    p=Path(p);b=p.read_bytes()
    return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)
def frac(v):return Fraction.from_float(float(v))
def squared(a,b):return sum(((frac(x)-frac(y))**2 for x,y in zip(a.ravel(),b.ravel())),Fraction(0))
def rat(d):return Fraction(int(d['numerator']),int(d['denominator']))
def near(a,b):assert abs(float(a)-float(b))<=2e-12,(a,b)
def ci(v):
    v=np.asarray(v);h=2.7764451051977987*float(v.std(ddof=1))/np.sqrt(5)
    return [float(v.mean()-h),float(v.mean()+h)]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);ap.add_argument('--old-heads',required=True)
    args=ap.parse_args();study=Path(args.study_root);rec=ROOT/'records'
    p=read(ROOT/'PROTOCOL_BEFORE_RESULTS.json');r=read(rec/'RESULTS.json.gz');q=read(rec/'QUALIFICATION.json')
    assert p==r['protocol'] and sha(ROOT/'PROTOCOL_BEFORE_RESULTS.json')==r['protocol_sha256']==q['protocol_sha256']
    assert sha(ROOT/'run_value_grid.py')==p['driver_sha256']==q['driver_sha256']
    assert sha(rec/'RESULTS.json.gz')==q['results_sha256']
    assert r['status']==q['status']=='completed' and q['complete_grid_rows']==625
    assert {n:sha(study/n) for n in p['source_sha256']}==p['source_sha256']
    assert sha(args.old_heads)==p['old_heads_gzip_sha256']
    old=read(args.old_heads);oldheads={x['fit']:x for x in old['fits']}
    source_path=study/'records/results_strict.json.gz';oldbytes=gzip.decompress(source_path.read_bytes())
    assert hashlib.sha256(oldbytes).hexdigest()==p['original_results_uncompressed_sha256']
    oldfits={x['fit']:x for x in json.loads(oldbytes)['fits']}
    geometry_path=study/'fixtures/train_linear_geometry.npz'
    assert sha(geometry_path)=='2928beeceabd3c6b48cda7d1b5df2de4ddbbaecc2ebedb23d2a8ce75df1816d5'
    geometry=np.load(geometry_path,allow_pickle=False)
    transfer=read(ROOT/'TRANSFER_VERIFICATION.json')
    assert len(transfer['files'])==24
    for x in transfer['files']:
        path=rec/x['name'];assert path.stat().st_size==x['bytes'] and sha(path)==x['sha256']
    before=read(rec/'ALL_SELECTIONS_AND_VAL_BEFORE_TEST.json')
    assert before['fresh_test_generated_at_write'] is False
    assert sha(rec/'ALL_SELECTIONS_AND_VAL_BEFORE_TEST.json')==r['before_test_receipt_sha256']
    assert len(before['record_file_sha256'])==11
    for n,h in before['record_file_sha256'].items():
        assert 'WORLDS' not in n and n not in ('RESULTS.json.gz','QUALIFICATION.json') and sha(rec/n)==h
    beforefits={x['fit']:x for x in before['fits']}
    grid=list(itertools.product(p['grid'],repeat=3));assert len(grid)==125 and grid[62]==(0.,0.,0.)
    assert [x['fit'] for x in r['fits']]==p['fits']
    rows_verified=0;worlds_verified=0;contrast_summaries_verified=0;norm_discrepancies=[]
    for f in r['fits']:
        fit=f['fit'];prior=oldfits[fit];h=oldheads[fit];A=np.array(f['baseline_head']);C=np.array(f['incumbent_head']);V=np.array(f['selected_head'])
        assert np.array_equal(A,geometry[f'fit{fit}_theta'])
        assert np.array_equal(C,np.c_[h['network_w2'],h['network_b2']]) and np.array_equal(A[3],C[3])
        for k in ('source_model_sha256','source_data_sha256'):assert f[k]==prior[k]
        assert f['incumbent_model_sha256']==prior['candidate_model_sha256']==h['candidate_model_sha256']
        assert f['original_radius']==prior['radius'];rho2=frac(f['original_radius'])**2
        assert rat(f['radius_squared_exact'])==rho2 and squared(C[:3],A[:3])<=rho2
        assert rat(f['incumbent_total_change_squared_exact'])==squared(C[:3],A[:3])
        table=read(rec/f['grid_scores_file']);assert sha(rec/f['grid_scores_file'])==f['grid_scores_sha256']
        rows=table['candidates'];assert len(rows)==125 and table['fit']==fit
        keys=[]
        for index,(row,offset) in enumerate(zip(rows,grid)):
            assert row['index']==index and row['bias_offset_nominal']==list(offset)
            theta=C.copy();theta[:3,48]=C[:3,48]+np.asarray(offset)
            assert row['bias_weights']==theta[:3,48].tolist()
            assert row['bias_delta_realized']==(theta[:3,48]-C[:3,48]).tolist()
            total2=squared(theta[:3],A[:3]);step2=squared(theta[:3],C[:3])
            assert rat(row['total_change_squared_exact'])==total2 and rat(row['incremental_change_squared_exact'])==step2
            assert row['feasible']==(total2<=rho2)
            assert len(row['train_world_utilities'])==f['training_worlds']==64
            near(np.mean(row['train_world_utilities']),row['train_utility'])
            if row['feasible']:keys.append(((-row['train_utility'],step2,offset),index,theta))
            rows_verified+=1
        _,index,expected=min(keys,key=lambda x:x[0])
        assert index==f['selected_index'] and np.array_equal(expected,V)
        assert f['selected_train_utility']==rows[index]['train_utility']>=rows[62]['train_utility']==f['incumbent_train_utility']
        assert f['feasible_candidates']==sum(x['feasible'] for x in rows)
        random=f['random_control'];rng=np.random.default_rng(p['seed']+1000*fit+881)
        offset=np.asarray(f['selected_offset']);ro=offset[rng.permutation(3)]*rng.choice([-1.,1.],3)
        R=C.copy();R[:3,48]=C[:3,48]+ro
        assert ro.tolist()==random['offset_nominal'] and np.array_equal(R,np.array(random['proposal_head']))
        assert sum(frac(x)**2 for x in offset)==sum(frac(x)**2 for x in ro)
        assert rat(random['total_change_squared_exact'])==squared(R[:3],A[:3])
        assert random['feasible']==(squared(R[:3],A[:3])<=rho2)
        difference=squared(R[:3],C[:3])-squared(V[:3],C[:3])
        assert rat(random['realized_step_squared_difference_vs_V_exact'])==difference
        norm_discrepancies.append(float(difference))
        expected_R=R if random['feasible'] else C
        assert np.array_equal(expected_R,np.array(random['effective_head']))
        prior_record=read(rec/f'fit_{fit}_BEFORE_TEST.json');assert prior_record==beforefits[fit]
        for k,v in prior_record.items():
            if k not in ('tests','timing'):assert f[k]==v
        for k,v in prior_record['timing'].items():assert f['timing'][k]==v
        assert prior_record['tests']=={}
        val=f['validation'];baseval=val['C_incumbent']['utility']
        for name,x in val.items():near(np.mean(x['world_utilities']),x['utility']);assert len(x['world_utilities'])==16
        for gate,arm,feasible in [('V','V_grid_raw',True),('R','R_permutation_raw',random['feasible'])]:
            g=f['gates'][gate];gain=val[arm]['utility']-baseval
            assert g['increment_vs_C']==gain and g['accepted']==(feasible and gain>=.005)
            assert g['revert_to_C']==(not g['accepted']) and g['exact_parameter_revert_verified']
        metrics=f['descriptive_fixed_probe_metrics']
        for split in ('train','validation'):
            assert all(m[split]['belief_brier']==metrics['A_original'][split]['belief_brier'] for m in metrics.values())
        for domain,test in f['tests'].items():
            wp=rec/test['world_file'];assert sha(wp)==test['world_file_sha256']
            worlds=read(wp);assert len(worlds)==test['world_count']==32
            assert [w['id'] for w in worlds]==[f'wsp_ndu_value_grid_{p["seed"]}_{domain}_{fit}_{i}' for i in range(32)]
            worlds_verified+=len(worlds)
            for arm,x in test['arms'].items():
                assert len(x['world_utilities'])==32 and np.isfinite(x['world_utilities']).all()
                near(np.mean(x['world_utilities']),x['expected_utility'])
            for gate,raw,gated in [('V','V_grid_raw','V_grid_gated'),('R','R_permutation_raw','R_permutation_gated')]:
                expected_arm=raw if f['gates'][gate]['accepted'] else 'C_incumbent'
                assert test['arms'][gated]==test['arms'][expected_arm]
    for domain,s in r['summary'].items():
        C=np.array([f['tests'][domain]['arms']['C_incumbent']['expected_utility'] for f in r['fits']])
        for arm,entry in s.items():
            if arm=='contrasts':continue
            values=np.array([f['tests'][domain]['arms'][arm]['expected_utility'] for f in r['fits']]);delta=values-C
            assert entry['per_fit_utility']==values.tolist() and entry['minus_C']['per_fit']==delta.tolist()
            near(entry['mean_utility'],values.mean());near(entry['minus_C']['mean'],delta.mean())
            for a,b in zip(entry['minus_C']['descriptive_paired_95_ci'],ci(delta)):near(a,b)
        def arm_values(name):
            return np.array([f['tests'][domain]['arms'][name]['expected_utility'] for f in r['fits']])
        expected_contrasts={
            'C_minus_A':C-arm_values('A_original'),
            'V_raw_minus_R_raw':arm_values('V_grid_raw')-arm_values('R_permutation_raw'),
            'V_gated_minus_R_gated':arm_values('V_grid_gated')-arm_values('R_permutation_gated')}
        assert set(s['contrasts'])==set(expected_contrasts)
        for name,delta in expected_contrasts.items():
            entry=s['contrasts'][name]
            assert entry['independent_fits']==5 and entry['per_fit']==delta.tolist()
            assert len(entry['descriptive_paired_95_ci'])==2
            near(entry['mean'],delta.mean())
            for a,b in zip(entry['descriptive_paired_95_ci'],ci(delta)):near(a,b)
            contrast_summaries_verified+=1
    assert rows_verified==625 and worlds_verified==320 and r['all_old_inputs_unchanged']
    assert contrast_summaries_verified==6
    assert r['measurement']['process_cpu_seconds_at_finish']<300 and r['measurement']['peak_rss_bytes']<4*1024**3
    assert r['matmul_audit']['nonfinite_count']==0
    print(json.dumps({'status':'passed','exact_budget_and_selection_rows_verified':rows_verified,
        'heldout_world_records_verified':worlds_verified,'contrast_summaries_verified':contrast_summaries_verified,
        'V_validation_accepts':sum(f['gates']['V']['accepted'] for f in r['fits']),
        'R_validation_accepts':sum(f['gates']['R']['accepted'] for f in r['fits']),
        'actual_random_vs_V_squared_norm_differences':norm_discrepancies,
        'scope':'record/hash/norm/selection/gate/aggregate verification only; no model or utility reevaluation'},indent=2))
if __name__=='__main__':main()
