"""Independent finite-state, budget, aggregate and exact-certificate checks."""
from pathlib import Path
from fractions import Fraction
import argparse,gzip,hashlib,json,subprocess,sys
import numpy as np

ROOT=Path(__file__).resolve().parent

def read(name):
    p=ROOT/name;b=p.read_bytes();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ci(v):
    v=np.array(v);half=2.7764451051977987*float(v.std(ddof=1))/np.sqrt(5)
    return np.array([v.mean(),v.mean()-half,v.mean()+half])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);args=ap.parse_args();study=Path(args.study_root)
    manifest=read('FOLLOWUP_MANIFEST.json')
    for path,ref in manifest['files'].items():
        b=(ROOT/path).read_bytes();assert len(b)==ref['bytes'] and hashlib.sha256(b).hexdigest()==ref['sha256'],path
    original_check=json.loads(subprocess.check_output([sys.executable,str(study/'verify_delivery.py')],text=True))
    assert original_check['verified_files']==42
    p=read('PROTOCOL_BEFORE_RESULTS.json');proposals=read('BELIEF_PROPOSALS.json');results=read('records/results.json.gz')
    before=read('records/BEFORE_TEST_RECEIPTS.json.gz');execution=read('records/EXECUTION_MANIFEST_BEFORE_TEST.json.gz')
    assert sha(ROOT/'PROTOCOL_BEFORE_RESULTS.json')==proposals['protocol_sha256']==execution['protocol_sha256']
    assert sha(ROOT/'BELIEF_PROPOSALS.json')==execution['proposal_sha256']
    assert sha(ROOT/'evaluate_followup.py')==execution['evaluator_sha256']
    assert sha(ROOT/'solve_belief_lp.py')==execution['solver_sha256']==proposals['source_solver_sha256']
    geometry=study/'fixtures/train_linear_geometry.npz';assert sha(geometry)==p['source_geometry_sha256']
    assert sha(study/'run_head_edit.py')==p['source_original_experiment_sha256']
    assert p['seed']==870140000 and p['logit_margin']==1e-4 and p['budget_fraction']==.5
    g=np.load(geometry);train_count=0;wrong_before=0;wrong_after=0;correct_preserved=0;nonzero=0
    for proposed,actual in zip(proposals['fits'],results['fits']):
        fit=proposed['fit'];assert fit==actual['fit'];base=g[f'fit{fit}_theta'][3];new=np.asarray(proposed['effective_weights']);x=g[f'fit{fit}_x'];y=g[f'fit{fit}_y'];mask=g[f'fit{fit}_mask']
        assert np.array_equal(base,np.asarray(proposed['base_weights']))
        rows=[];sign=[]
        for i in range(len(x)):
            ids=np.flatnonzero(mask[i]);best=np.max(y[i,ids]);winners=ids[np.abs(y[i,ids]-best)<=1e-10]
            if len(winners)==1 and winners[0] in (4,5):rows.append(i);sign.append(1. if winners[0]==5 else -1.)
        sign=np.asarray(sign);rows=np.asarray(rows,dtype=int)
        old_signed=sign*np.sum(x[rows]*base,axis=1);new_signed=sign*np.sum(x[rows]*new,axis=1)
        assert rows.tolist()==proposed['unique_oracle_terminal_rows']
        assert np.min(new_signed)>=1e-4-1e-8
        assert rows[old_signed<=0].tolist()==proposed['wrong_sign_rows_before']==actual['baseline_terminal_train']['wrong_sign_rows']
        assert rows[new_signed<=0].tolist()==proposed['wrong_sign_rows_after']==actual['belief_terminal_train']['wrong_sign_rows']
        assert np.all(new_signed[old_signed>0]>0)
        rho=Fraction.from_float(proposed['rho'])
        exact_l1=sum((abs(Fraction.from_float(float(a))-Fraction.from_float(float(b))) for a,b in zip(new,base)),Fraction(0))
        assert exact_l1<=rho
        # Requested random deltas preserve the exact absolute-value multiset.
        assert np.array_equal(np.sort(abs(np.asarray(proposed['effective_delta']))),np.sort(abs(np.asarray(proposed['random_delta']))))
        assert actual['realized_l1_norm_matching_error']<=1e-12 and actual['realized_l2_norm_matching_error']<=1e-12
        assert before[str(fit)]['gates']==actual['gates'] and before[str(fit)]['validation']==actual['validation']
        for name,gate in actual['gates'].items():
            raw=gate['raw_arm'];delta=actual['validation'][raw]['utility']-actual['validation']['raw00_base']['utility']
            assert delta==gate['validation_gain'] and gate['accepted']==(delta>=.005)
            expected=raw if gate['accepted'] else 'raw00_base'
            for split in ('iid','ood'):
                assert actual['tests'][split]['arms'][name]==actual['tests'][split]['arms'][expected]
        for split in ('iid','ood'):
            assert actual['tests'][split]['world_count']==32
            for metrics in actual['tests'][split]['arms'].values():
                assert np.isfinite(metrics['expected_utility']) and len(metrics['world_utilities'])==32
                assert abs(np.mean(metrics['world_utilities'])-metrics['expected_utility'])<=1e-12
        train_count+=len(rows);wrong_before+=int(np.sum(old_signed<=0));wrong_after+=int(np.sum(new_signed<=0));correct_preserved+=int(np.sum((old_signed>0)&(new_signed>0)));nonzero+=int(np.any(base!=new))
    for split in ('iid','ood'):
        arms=results['fits'][0]['tests'][split]['arms']
        for arm in arms:
            values=[f['tests'][split]['arms'][arm]['expected_utility']-f['tests'][split]['arms']['raw00_base']['expected_utility'] for f in results['fits']]
            record=results['summary'][split][arm]['change_from_base']
            assert np.max(abs(ci(values)-np.r_[record['mean'],record['descriptive_paired_95_ci']]))<=1e-12
    assert train_count==457 and wrong_before==6 and wrong_after==0 and correct_preserved==451 and nonzero==3
    assert results['matmul_audit']['nonfinite_count']==0 and results['matmul_audit']['max_abs_difference']<=1e-12
    certificate=read('exact_certificate/exact_certificate.json')
    for path,expected in certificate['source_provenance']['input_sha256'].items():assert sha(study/path)==expected
    checked=subprocess.check_output([sys.executable,str(ROOT/'exact_certificate/exact_box_certificate.py'),'verify'],text=True)
    exact=json.loads(checked);assert exact['verified'] and exact['exactly_infeasible_cases']==2
    print(json.dumps({'verified_files':len(manifest['files']),'all_original_sources_preserved':True,'training_terminal_constraints':train_count,
                      'wrong_before':wrong_before,'wrong_after':wrong_after,'original_correct_preserved':correct_preserved,
                      'nonzero_belief_edits':nonzero,'belief_only_validation_accepts':sum(f['gates']['gated01_belief']['accepted'] for f in results['fits']),
                      'raw_and_gated_results_distinct_and_verified':True,'exact_ieee_box_infeasibility_certificates':2,
                      'global_effectiveness_qualified':False,'full_model_training_superiority_qualified':False},indent=2))
if __name__=='__main__':main()
