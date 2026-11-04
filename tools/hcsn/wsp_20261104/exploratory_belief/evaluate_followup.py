"""Predeclared exploratory raw/gated 2x2 on actual published Hepta heads.

No model selection on fresh holdout. Original continuation candidate is reused,
not refit. Belief proposals are from original TRAIN only. All inference products
use the prior explicit-reference checked path under strict floating-point flags.
"""
from pathlib import Path
from fractions import Fraction
import argparse,ast,copy,gzip,hashlib,json,platform,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,obj):Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def load_checked(study):
    """Load the prior audit primitives only, without running another experiment."""
    tree=ast.parse((study/'checked_replay.py').read_text())
    definitions=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in ('checked_mm','MM'):definitions.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='AUDIT' for t in node.targets):definitions.append(node)
    audit={'np':np,'ast':ast}
    exec(compile(ast.Module(body=definitions,type_ignores=[]),'checked_audit_primitives','exec'),audit)
    source=(study/'run_head_edit.py').read_text()
    before="tree=ast.parse((ROOT/file).read_text(),filename=file)"
    after=before+"\n    tree=ast.fix_missing_locations(MM().visit(tree));ns['checked_mm']=checked_mm"
    assert source.count(before)==1;source=source.replace(before,after)
    tree=ast.fix_missing_locations(audit['MM']().visit(ast.parse(source)))
    ns={'__name__':'followup_import_only','__file__':str(study/'run_head_edit.py'),'checked_mm':audit['checked_mm'],'MM':audit['MM']}
    exec(compile(tree,str(study/'run_head_edit.py'),'exec'),ns)
    return ns,audit

def terminal_diagnostic(theta,arr):
    x,y,mask,_=arr;rows=[];targetsign=[]
    for i in range(len(x)):
        ids=np.flatnonzero(mask[i]);best=np.max(y[i,ids]);winners=ids[np.abs(y[i,ids]-best)<=1e-10]
        if len(winners)==1 and winners[0] in (4,5):rows.append(i);targetsign.append(1. if winners[0]==5 else -1.)
    rows=np.asarray(rows,dtype=int);sign=np.asarray(targetsign)
    logits=np.sum(x[rows]*theta[3],axis=1);signed=sign*logits
    return {'constraint_rows':len(rows),'wrong_sign_rows':rows[signed<=0].tolist(),
            'minimum_signed_logit':float(signed.min()),'margin_violation':float(max(0.,np.max(1e-4-signed)))}

def mean_ci(values):
    v=np.asarray(values,dtype=float);half=2.7764451051977987*float(v.std(ddof=1))/np.sqrt(5)
    return {'mean':float(v.mean()),'per_fit':v.tolist(),'descriptive_paired_95_ci':[float(v.mean()-half),float(v.mean()+half)],'independent_fits':5}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);ap.add_argument('--inputs',required=True)
    ap.add_argument('--old-results',required=True);ap.add_argument('--output',required=True);args=ap.parse_args()
    study=Path(args.study_root);data_root=Path(args.inputs);oldroot=Path(args.old_results);outroot=Path(args.output)
    if outroot.exists():raise FileExistsError('output must be new')
    protocol=json.loads((ROOT/'PROTOCOL_BEFORE_RESULTS.json').read_text());proposals=json.loads((ROOT/'BELIEF_PROPOSALS.json').read_text())
    assert digest(ROOT/'PROTOCOL_BEFORE_RESULTS.json')==proposals['protocol_sha256']
    assert digest(study/'run_head_edit.py')==protocol['source_original_experiment_sha256']
    assert digest(oldroot/'results.json')==protocol['source_original_results_sha256']
    old=json.loads((oldroot/'results.json').read_text());oldfits={f['fit']:f for f in old['fits']}
    assert protocol['seed']==870140000 and protocol['worlds_per_fit_per_domain']==32 and protocol['validation_acceptance_improvement']==.005
    outroot.mkdir(parents=True,exist_ok=False)
    # This file exists before loading/evaluating any fresh holdout world.
    manifest={'protocol_sha256':digest(ROOT/'PROTOCOL_BEFORE_RESULTS.json'),'proposal_sha256':digest(ROOT/'BELIEF_PROPOSALS.json'),
              'evaluator_sha256':digest(__file__),'solver_sha256':digest(ROOT/'solve_belief_lp.py'),
              'old_results_sha256':digest(oldroot/'results.json'),
              'original_dependency_sha256':{p.name:digest(p) for p in study.glob('*.py')},
              'strict_execution':{'over':'raise','invalid':'raise','divide':'raise','matmul':'explicit-reference execution; diagnostic BLAS independently compared'},
              'fresh_test_outputs_exist_at_write':False}
    save(outroot/'EXECUTION_MANIFEST_BEFORE_TEST.json',manifest)
    module,audit=load_checked(study);module['SEED']=protocol['seed'];module['TEST_WORLDS']=32
    begin=time.perf_counter();global_start=time.process_time();records=[]
    for proposal in proposals['fits']:
        fit=proposal['fit'];t0=time.process_time();prior=oldfits[fit]
        model_path=data_root/f'fit_{fit}/model_renewal/model.json';data_path=data_root/f'fit_{fit}/data/fit_{fit}_data.json'
        candidate_path=oldroot/f'fit_{fit}_candidate_model.json'
        assert digest(model_path)==prior['source_model_sha256'] and digest(data_path)==prior['source_data_sha256']
        assert digest(candidate_path)==prior['candidate_model_sha256']
        artifact=json.loads(model_path.read_text());data=json.loads(data_path.read_text());old_artifact=json.loads(candidate_path.read_text())
        base=module['head'](artifact);continuation=module['head'](old_artifact)
        restored=copy.deepcopy(old_artifact);restored['network']['w2']=artifact['network']['w2'];restored['network']['b2']=artifact['network']['b2'];assert restored==artifact
        assert np.array_equal(base[3],continuation[3]) and np.array_equal(base[3],np.asarray(proposal['base_weights']))
        policy=module['NumpyPolicy'](artifact);features=module['FrozenFeatures'](policy)
        train=module['row_arrays'](data['train']['rows'],features);validation=module['row_arrays'](data['validation']['rows'],features)
        train_ids=set(r['world'] for r in data['train']['rows']);val_ids=set(r['world'] for r in data['validation']['rows']);assert not train_ids&val_ids
        belief=base.copy();belief[3]=np.asarray(proposal['effective_weights'])
        both=continuation.copy();both[3]=belief[3]
        random=base.copy();random[3]=np.asarray(proposal['random_weights'])
        assert np.array_equal(belief[:3],base[:3]) and np.array_equal(random[:3],base[:3]) and np.array_equal(both[:3],continuation[:3])
        for theta in (base,continuation,belief,both,random):assert np.isfinite(theta).all()
        actual_delta=belief[3]-base[3];random_delta=random[3]-base[3];rho=proposal['rho']
        actual_l1=sum((abs(Fraction.from_float(float(a))-Fraction.from_float(float(b))) for a,b in zip(belief[3],base[3])),Fraction(0))
        random_l1=sum((abs(Fraction.from_float(float(a))-Fraction.from_float(float(b))) for a,b in zip(random[3],base[3])),Fraction(0))
        assert actual_l1<=Fraction.from_float(rho) and random_l1<=Fraction.from_float(rho)
        baseline_terminal=terminal_diagnostic(base,train);belief_terminal=terminal_diagnostic(belief,train)
        if proposal['proposal_available']:assert belief_terminal['margin_violation']<=protocol['numerical_constraint_tolerance']
        worlds=module['public_unique'](data['validation']['rows']);confusion=artifact['confusion']
        oracles={p['id']:module['Oracle'](p,module['law'],confusion) for p in worlds}
        raw={'raw00_base':base,'raw10_old_continuation':continuation,'raw01_belief':belief,'raw11_both':both,'raw01_random_belief':random}
        val={};vcache={};vstart=time.process_time()
        for name,theta in raw.items():
            key=theta.tobytes()
            if key not in vcache:vcache[key]=module['eval_worlds'](worlds,theta,features,oracles)
            u,values,nodes=vcache[key]
            val[name]={'utility':u,'world_utilities':values,'visited_nodes':nodes}
        baseval=val['raw00_base']['utility'];assert abs(baseval-prior['baseline_validation_utility'])<=1e-10
        assert abs(val['raw10_old_continuation']['utility']-prior['selected_direct']['validation_utility'])<=1e-10
        arms=dict(raw);gates={}
        mapping={'gated10_old_continuation':'raw10_old_continuation','gated01_belief':'raw01_belief','gated11_both':'raw11_both','gated01_random_belief':'raw01_random_belief'}
        for name,source in mapping.items():
            delta=val[source]['utility']-baseval;accepted=delta>=.005
            # If no Belief proposal exists, raw interventions become declared no-ops.
            if source in ('raw01_belief','raw01_random_belief') and not proposal['proposal_available']:accepted=False
            arms[name]=raw[source] if accepted else base
            gates[name]={'raw_arm':source,'validation_gain':delta,'accepted':accepted,
                         'rollback_to_base':not accepted,'rollback_exact_parameter_equality':bool(accepted or np.array_equal(arms[name],base)),
                         'belief_proposal_available':proposal['proposal_available']}
        result={'fit':fit,'source_model_sha256':digest(model_path),'source_data_sha256':digest(data_path),'old_candidate_sha256':digest(candidate_path),
                'belief_proposal_available':proposal['proposal_available'],'nonzero_belief_edit':proposal['nonzero_edit'],
                'validation':val,'gates':gates,'baseline_terminal_train':baseline_terminal,'belief_terminal_train':belief_terminal,
                'random_terminal_train':terminal_diagnostic(random,train),
                'actual_belief_delta_l1':float(actual_l1),'actual_belief_delta_l2':float(np.linalg.norm(actual_delta)),
                'actual_random_delta_l1':float(random_l1),'actual_random_delta_l2':float(np.linalg.norm(random_delta)),
                'realized_l1_norm_matching_error':abs(float(actual_l1)-float(random_l1)),
                'realized_l2_norm_matching_error':abs(float(np.linalg.norm(actual_delta))-float(np.linalg.norm(random_delta))),
                'training_metrics':{name:module['metrics'](theta,train) for name,theta in raw.items()},
                'timing':{'validation_cpu_seconds':time.process_time()-vstart},'tests':{}}
        # Every raw/gated candidate and validation decision is now frozen.
        save(outroot/f'fit_{fit}_BEFORE_TEST.json',result)
        for split in ('iid','ood'):
            testworlds=module['make_worlds'](fit,split)
            for i,p in enumerate(testworlds):p['id']=f"wsp_belief_followup_{protocol['seed']}_{split}_{fit}_{i}"
            assert not {p['id'] for p in testworlds}&(train_ids|val_ids)
            test_oracles={p['id']:module['Oracle'](p,module['law'],confusion) for p in testworlds}
            testrows=module['behavior_rows'](testworlds,confusion,fit,split);testarr=module['row_arrays'](testrows,features)
            oracle_values=[float(test_oracles[p['id']].q(module['initial'](p)).max()) for p in testworlds]
            arm_results={};cache={};estart=time.process_time()
            for name,theta in arms.items():
                key=theta.tobytes()
                if key not in cache:
                    utility,values,nodes=module['eval_worlds'](testworlds,theta,features,test_oracles)
                    cache[key]={'expected_utility':utility,'world_utilities':values,'visited_nodes':nodes,**module['metrics'](theta,testarr)}
                arm_results[name]=copy.deepcopy(cache[key])
            result['tests'][split]={'world_count':len(testworlds),'public_worlds_sha256':hashlib.sha256(json.dumps(testworlds,sort_keys=True).encode()).hexdigest(),
                                    'oracle_utility':float(np.mean(oracle_values)),'arms':arm_results,'unique_policies_evaluated':len(cache),'cpu_seconds':time.process_time()-estart}
            save(outroot/f'fit_{fit}_{split}_worlds.json',testworlds)
        result['timing'].update(total_cpu_seconds=time.process_time()-t0,feature_cpu_seconds=features.seconds,feature_cache_size=features.calls)
        save(outroot/f'fit_{fit}_results.json',result);records.append(result)
        print(json.dumps({'fit':fit,'nonzero_belief_edit':proposal['nonzero_edit'],'wrong_terminal_before':len(baseline_terminal['wrong_sign_rows']),
                          'wrong_terminal_after':len(belief_terminal['wrong_sign_rows']),'gate_accepts':{n:g['accepted'] for n,g in gates.items()},
                          'iid_raw_belief_delta':result['tests']['iid']['arms']['raw01_belief']['expected_utility']-result['tests']['iid']['arms']['raw00_base']['expected_utility'],
                          'ood_raw_belief_delta':result['tests']['ood']['arms']['raw01_belief']['expected_utility']-result['tests']['ood']['arms']['raw00_base']['expected_utility']}),flush=True)
    result={'schema':'hepta-exploratory-belief-followup-results-v1','protocol':protocol,'execution_manifest':manifest,'fits':records,'summary':{},
            'cpu_seconds':time.process_time()-global_start,'wall_seconds':time.perf_counter()-begin,'numpy':np.__version__,'python':sys.version,'platform':platform.platform(),
            'matmul_audit':audit['AUDIT'],'scientific_qualification':'exploratory only; no global effectiveness/full-model superiority claim'}
    for split in ('iid','ood'):
        summary={};names=list(records[0]['tests'][split]['arms'])
        def values(name):return np.array([f['tests'][split]['arms'][name]['expected_utility'] for f in records])
        for name in names:
            summary[name]={'mean_utility':float(values(name).mean()),'change_from_base':mean_ci(values(name)-values('raw00_base'))}
        summary['contrasts']={
            'raw_belief_plus_continuation_minus_continuation':mean_ci(values('raw11_both')-values('raw10_old_continuation')),
            'gated_belief_plus_continuation_minus_gated_continuation':mean_ci(values('gated11_both')-values('gated10_old_continuation')),
            'raw_belief_minus_random_belief':mean_ci(values('raw01_belief')-values('raw01_random_belief')),
            'gated_belief_minus_gated_random_belief':mean_ci(values('gated01_belief')-values('gated01_random_belief')),
            'raw_factorial_interaction':mean_ci(values('raw11_both')-values('raw10_old_continuation')-values('raw01_belief')+values('raw00_base')),
            'gated_factorial_interaction':mean_ci(values('gated11_both')-values('gated10_old_continuation')-values('gated01_belief')+values('raw00_base'))}
        result['summary'][split]=summary
    save(outroot/'results.json',result)
    print(json.dumps({'complete':True,'cpu_seconds':result['cpu_seconds'],'wall_seconds':result['wall_seconds'],'matmul_audit':audit['AUDIT']}),flush=True)

if __name__=='__main__':
    with np.errstate(over='raise',invalid='raise',divide='raise'):main()
