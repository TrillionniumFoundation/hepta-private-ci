#!/usr/bin/env python3
"""Bounded complete-utility bias-grid search on the published joint policies.

Only the frozen TRAIN public worlds select a candidate. All five selections and
original-validation receipts are fixed before any new holdout world is made.
The original strict reference evaluator is reused without a proxy objective.
"""
from pathlib import Path
from fractions import Fraction
import argparse, ast, copy, datetime, gzip, hashlib, itertools, json
import platform, resource, signal, sys, time
import numpy as np

ROOT = Path(__file__).resolve().parent
TCRIT = 2.7764451051977987

def sha_bytes(value): return hashlib.sha256(value).hexdigest()
def sha(path): return sha_bytes(Path(path).read_bytes())
def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
def save(path, value):
    with Path(path).open('xb') as stream: stream.write(json_bytes(value))
def save_gz(path, value):
    with Path(path).open('xb') as stream: stream.write(gzip.compress(json_bytes(value), mtime=0))
def read_bytes(path):
    path=Path(path); value=path.read_bytes()
    return gzip.decompress(value) if path.suffix=='.gz' else value
def fraction(value): return Fraction.from_float(float(value))
def exact_squared_change(new, old):
    return sum(((fraction(a)-fraction(b))**2 for a,b in zip(new.ravel(),old.ravel())), Fraction(0))
def rational(value): return {'numerator':str(value.numerator),'denominator':str(value.denominator)}
def mean_ci(values):
    v=np.asarray(values, dtype=float); mean=float(v.mean())
    half=TCRIT*float(v.std(ddof=1))/np.sqrt(5)
    return {'mean':mean,'per_fit':v.tolist(),'descriptive_paired_95_ci':[mean-half,mean+half],'independent_fits':5}

def load_checked(study):
    tree=ast.parse((study/'checked_replay.py').read_text()); definitions=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in ('checked_mm','MM'): definitions.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='AUDIT' for t in node.targets): definitions.append(node)
    audit={'np':np,'ast':ast}
    exec(compile(ast.Module(body=definitions,type_ignores=[]),'frozen_checked_primitives','exec'),audit)
    source=(study/'run_head_edit.py').read_text()
    before='tree=ast.parse((ROOT/file).read_text(),filename=file)'
    after=before+"\n    tree=ast.fix_missing_locations(MM().visit(tree));ns['checked_mm']=checked_mm"
    assert source.count(before)==1
    tree=ast.fix_missing_locations(audit['MM']().visit(ast.parse(source.replace(before,after))))
    module={'__name__':'value_grid_import_only','__file__':str(study/'run_head_edit.py'),
            'checked_mm':audit['checked_mm'],'MM':audit['MM']}
    exec(compile(tree,str(study/'run_head_edit.py'),'exec'),module)
    return module,audit

class BudgetExceeded(RuntimeError): pass

def main(args):
    study=Path(args.study_root); inputs=Path(args.inputs); out=Path(args.output)
    if out.exists(): raise FileExistsError('output must be new')
    protocol=json.loads((ROOT/'PROTOCOL_BEFORE_RESULTS.json').read_text())
    assert sha(__file__)==protocol['driver_sha256']
    assert protocol['seed']==870150000 and protocol['grid']==[-.1,-.05,0.,.05,.1]
    assert protocol['validation_gain_threshold']==.005 and protocol['cpu_hard_limit_seconds']==300
    source_before={name:sha(study/name) for name in protocol['source_sha256']}
    assert source_before==protocol['source_sha256']
    old_bytes=read_bytes(args.old_results); heads_bytes=Path(args.old_heads).read_bytes()
    assert sha_bytes(old_bytes)==protocol['original_results_uncompressed_sha256']
    assert sha_bytes(heads_bytes)==protocol['old_heads_gzip_sha256']
    prior=json.loads(old_bytes); oldfits={r['fit']:r for r in prior['fits']}
    headrows={r['fit']:r for r in json.loads(gzip.decompress(heads_bytes))['fits']}
    out.mkdir(parents=True,exist_ok=False)
    begin_cpu=time.process_time(); begin_wall=time.perf_counter()
    state={'schema':'hepta-ndu-value-grid-results-v1','status':'started','protocol':protocol,
           'protocol_sha256':sha(ROOT/'PROTOCOL_BEFORE_RESULTS.json'), 'fits':[],
           'pilot':protocol['feasibility_pilot'],'new_holdout_generated':False}
    def budget():
        if time.process_time()-begin_cpu>=290: raise BudgetExceeded('290-second graceful stop before 300 CPU-second hard cap')
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes=peak if sys.platform=='darwin' else peak*1024
        if peak_bytes>4*1024**3: raise BudgetExceeded('4 GiB sampled peak RSS ceiling')
    contexts=[]; input_before={}; current_table=None
    try:
        module,audit=load_checked(study); module['SEED']=protocol['seed']; module['TEST_WORLDS']=32
        # Check every frozen incumbent before evaluating any grid candidate.
        for fit in protocol['fits']:
            previous=oldfits[fit]; h=headrows[fit]
            model_path=inputs/f'fit_{fit}/model_renewal/model.json'
            data_path=inputs/f'fit_{fit}/data/fit_{fit}_data.json'
            assert sha(model_path)==previous['source_model_sha256']==h['source_model_sha256']
            assert sha(data_path)==previous['source_data_sha256']
            input_before[str(model_path)]=sha(model_path); input_before[str(data_path)]=sha(data_path)
            artifact=json.loads(model_path.read_text()); data=json.loads(data_path.read_text())
            old_artifact=copy.deepcopy(artifact)
            old_artifact['network']['w2']=h['network_w2']; old_artifact['network']['b2']=h['network_b2']
            assert sha_bytes(json_bytes(old_artifact))==previous['candidate_model_sha256']==h['candidate_model_sha256']
            A=module['head'](artifact); C=module['head'](old_artifact); rho=fraction(previous['radius'])
            assert np.array_equal(A[3],C[3]) and np.isfinite(C).all()
            c2=exact_squared_change(C[:3],A[:3]); feasible=c2<=rho*rho
            state['fits'].append({'fit':fit,'incumbent_in_original_radius':feasible,'original_radius':previous['radius'],
                'radius_squared_exact':rational(rho*rho),'incumbent_total_change_squared_exact':rational(c2),
                'source_model_sha256':previous['source_model_sha256'],'source_data_sha256':previous['source_data_sha256'],
                'incumbent_model_sha256':previous['candidate_model_sha256']})
            contexts.append({'fit':fit,'prior':previous,'artifact':artifact,'data':data,'A':A,'C':C,'rho':rho})
        save(out/'INCUMBENT_BUDGET_BEFORE_SEARCH.json',{'protocol_sha256':state['protocol_sha256'],'fits':state['fits']})
        if not all(r['incumbent_in_original_radius'] for r in state['fits']):
            raise ValueError('Frozen C is outside original exact squared radius; no search, no relaxation')
        grid=list(itertools.product(protocol['grid'],repeat=3)); assert len(grid)==125 and grid[62]==(0.,0.,0.)
        # Complete all TRAIN searches and original-VAL gates before new holdout.
        for context,result in zip(contexts,state['fits']):
            budget(); fit=context['fit']; fit_cpu=time.process_time(); data=context['data']
            A,C=context['A'],context['C']; artifact=context['artifact']; rho=context['rho']
            features=module['FrozenFeatures'](module['NumpyPolicy'](artifact)); context['features']=features
            trainworlds=module['public_unique'](data['train']['rows']); valworlds=module['public_unique'](data['validation']['rows'])
            train_ids={p['id'] for p in trainworlds}; val_ids={p['id'] for p in valworlds}; assert not train_ids&val_ids
            context['seen_world_ids']=train_ids|val_ids
            oracles={p['id']:module['Oracle'](p,module['law'],artifact['confusion']) for p in trainworlds}
            candidates=[]; current_table={'fit':fit,'candidates':candidates}; best=None; search_start=time.process_time()
            for index,offset in enumerate(grid):
                budget(); theta=C.copy(); theta[:3,48]=C[:3,48]+np.asarray(offset,dtype=float)
                assert np.array_equal(theta[:3,:48],C[:3,:48]) and np.array_equal(theta[3],A[3])
                total2=exact_squared_change(theta[:3],A[:3]); step2=exact_squared_change(theta[:3],C[:3]); feasible=total2<=rho*rho
                utility,values,nodes=module['eval_worlds'](trainworlds,theta,features,oracles)
                assert np.isfinite(utility) and np.isfinite(values).all()
                row={'index':index,'bias_offset_nominal':list(offset),'bias_delta_realized':(theta[:3,48]-C[:3,48]).tolist(),
                    'bias_weights':theta[:3,48].tolist(),'feasible':feasible,'total_change_squared_exact':rational(total2),
                    'incremental_change_squared_exact':rational(step2),'train_utility':utility,
                    'train_world_utilities':values,'visited_nodes':nodes}
                candidates.append(row)
                key=(-utility,step2,offset)
                if feasible and (best is None or key<best[0]): best=(key,row,theta.copy())
            assert best is not None and candidates[62]['feasible']
            V=best[2]; selected=best[1]; rng=np.random.default_rng(protocol['seed']+1000*fit+881)
            nominal=np.asarray(selected['bias_offset_nominal']); random_offset=nominal[rng.permutation(3)]*rng.choice([-1.,1.],3)
            R_proposed=C.copy(); R_proposed[:3,48]=C[:3,48]+random_offset
            random2=exact_squared_change(R_proposed[:3],A[:3]); random_step2=exact_squared_change(R_proposed[:3],C[:3])
            random_feasible=random2<=rho*rho; R=R_proposed if random_feasible else C.copy()
            assert sum((fraction(x)**2 for x in nominal),Fraction(0))==sum((fraction(x)**2 for x in random_offset),Fraction(0))
            table_name=f'fit_{fit}_ALL_125_TRAIN.json.gz'; save_gz(out/table_name,current_table); current_table=None
            result.update({'training_worlds':len(trainworlds),'validation_worlds':len(valworlds),
                'candidate_count':len(candidates),'feasible_candidates':sum(r['feasible'] for r in candidates),
                'grid_scores_file':table_name,'grid_scores_sha256':sha(out/table_name),'selected_index':selected['index'],
                'selected_offset':selected['bias_offset_nominal'],'selected_train_utility':selected['train_utility'],
                'incumbent_train_utility':candidates[62]['train_utility'],'selected_step_squared_exact':selected['incremental_change_squared_exact'],
                'selected_total_change_squared_exact':selected['total_change_squared_exact'],
                'selected_head':V.tolist(),'incumbent_head':C.tolist(),'baseline_head':A.tolist(),
                'random_control':{'seed':protocol['seed']+1000*fit+881,'offset_nominal':random_offset.tolist(),
                    'feasible':random_feasible,'proposal_head':R_proposed.tolist(),'effective_head':R.tolist(),
                    'nominal_equal_norm_verified':True,'realized_step_squared_exact':rational(random_step2),
                    'realized_step_squared_difference_vs_V_exact':rational(random_step2-exact_squared_change(V[:3],C[:3])),
                    'total_change_squared_exact':rational(random2),'if_infeasible':'effective no-op C; no retry'},
                'timing':{'train_search_and_candidate_record_cpu_seconds':time.process_time()-search_start}})
            # Descriptive calibration only: never enters selection or acceptance.
            trainarr=module['row_arrays'](data['train']['rows'],features); valarr=module['row_arrays'](data['validation']['rows'],features)
            raw={'A_original':A,'C_incumbent':C,'V_grid_raw':V,'R_permutation_raw':R}; val={}; metrics={}; vstart=time.process_time()
            val_oracles={p['id']:module['Oracle'](p,module['law'],artifact['confusion']) for p in valworlds}
            for name,theta in raw.items():
                utility,values,nodes=module['eval_worlds'](valworlds,theta,features,val_oracles)
                val[name]={'utility':utility,'world_utilities':values,'visited_nodes':nodes}
                metrics[name]={'train':module['metrics'](theta,trainarr),'validation':module['metrics'](theta,valarr)}
            assert abs(val['A_original']['utility']-context['prior']['baseline_validation_utility'])<=1e-10
            assert abs(val['C_incumbent']['utility']-context['prior']['selected_direct']['validation_utility'])<=1e-10
            gain=val['V_grid_raw']['utility']-val['C_incumbent']['utility']; accept=gain>=.005
            rgain=val['R_permutation_raw']['utility']-val['C_incumbent']['utility']; raccept=random_feasible and rgain>=.005
            arms=dict(raw); arms['V_grid_gated']=V if accept else C; arms['R_permutation_gated']=R if raccept else C
            assert all(np.array_equal(t[3],A[3]) for t in arms.values())
            result.update({'validation':val,'descriptive_fixed_probe_metrics':metrics,
                'gates':{'V':{'increment_vs_C':gain,'accepted':accept,'revert_to_C':not accept,'exact_parameter_revert_verified':bool(accept or np.array_equal(arms['V_grid_gated'],C))},
                         'R':{'increment_vs_C':rgain,'accepted':raccept,'revert_to_C':not raccept,'exact_parameter_revert_verified':bool(raccept or np.array_equal(arms['R_permutation_gated'],C))}},
                'belief_and_representation_unchanged':True,'tests':{}})
            result['timing'].update(validation_and_descriptive_probes_cpu_seconds=time.process_time()-vstart,
                                    fit_before_test_cpu_seconds=time.process_time()-fit_cpu)
            context['arms']=arms; context.pop('data')
            save(out/f'fit_{fit}_BEFORE_TEST.json',result)
            print(json.dumps({'stage':'selection_and_val_fixed','fit':fit,'selected_index':selected['index'],
                'feasible':result['feasible_candidates'],'val_gain_vs_C':gain,'accepted':accept,'cpu':time.process_time()-begin_cpu}),flush=True)
        before={'protocol_sha256':state['protocol_sha256'],'driver_sha256':sha(__file__),
                'written_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'fresh_test_generated_at_write':False,'fits':copy.deepcopy(state['fits']),
                'record_file_sha256':{p.name:sha(p) for p in out.iterdir() if p.is_file()}}
        save(out/'ALL_SELECTIONS_AND_VAL_BEFORE_TEST.json',before)
        state['before_test_receipt_sha256']=sha(out/'ALL_SELECTIONS_AND_VAL_BEFORE_TEST.json')
        print(json.dumps({'stage':'all_five_frozen_before_new_test','receipt_sha256':state['before_test_receipt_sha256']}),flush=True)
        for context,result in zip(contexts,state['fits']):
            fit=context['fit']; features=context['features']; test_start=time.process_time(); budget()
            for domain in ('iid','ood'):
                worlds=module['make_worlds'](fit,domain); state['new_holdout_generated']=True
                for i,p in enumerate(worlds): p['id']=f'wsp_ndu_value_grid_{protocol["seed"]}_{domain}_{fit}_{i}'
                assert not {p['id'] for p in worlds}&context['seen_world_ids']
                test_oracles={p['id']:module['Oracle'](p,module['law'],context['artifact']['confusion']) for p in worlds}
                cache={}; arms={}
                for name,theta in context['arms'].items():
                    budget(); key=theta.tobytes()
                    if key not in cache:
                        utility,values,nodes=module['eval_worlds'](worlds,theta,features,test_oracles)
                        cache[key]={'expected_utility':utility,'world_utilities':values,'visited_nodes':nodes}
                    arms[name]=copy.deepcopy(cache[key])
                worldfile=f'fit_{fit}_{domain}_WORLDS.json.gz'; save_gz(out/worldfile,worlds)
                result['tests'][domain]={'world_count':len(worlds),'world_file':worldfile,'world_file_sha256':sha(out/worldfile),
                    'arms':arms,'unique_policies_evaluated':len(cache)}
            result['timing'].update(test_cpu_seconds=time.process_time()-test_start,
                feature_cpu_seconds=features.seconds,feature_cache_states=features.calls)
            print(json.dumps({'stage':'fresh_test_complete','fit':fit,'cpu':time.process_time()-begin_cpu}),flush=True)
        state['summary']={}
        for domain in ('iid','ood'):
            def vals(arm): return np.array([r['tests'][domain]['arms'][arm]['expected_utility'] for r in state['fits']])
            s={name:{'mean_utility':float(vals(name).mean()),'per_fit_utility':vals(name).tolist(),
                     'minus_C':mean_ci(vals(name)-vals('C_incumbent'))} for name in contexts[0]['arms']}
            s['contrasts']={'V_raw_minus_R_raw':mean_ci(vals('V_grid_raw')-vals('R_permutation_raw')),
                'V_gated_minus_R_gated':mean_ci(vals('V_grid_gated')-vals('R_permutation_gated')),
                'C_minus_A':mean_ci(vals('C_incumbent')-vals('A_original'))}
            state['summary'][domain]=s
        assert {name:sha(study/name) for name in source_before}==source_before
        assert all(sha(p)==v for p,v in input_before.items())
        assert sha_bytes(read_bytes(args.old_results))==protocol['original_results_uncompressed_sha256']
        assert sha(args.old_heads)==protocol['old_heads_gzip_sha256']
        state.update(status='completed',matmul_audit=audit['AUDIT'],all_old_inputs_unchanged=True,
                     no_gradient_steps=True,scope='Finite feasible 125-point grid optimum for computed TRAIN full utility; no continuous/global NDU or training-superiority claim')
    except Exception as exc:
        state['status']='blocked'; state['error_type']=type(exc).__name__
        message=str(exc)
        for private_path in [str(study),str(inputs),str(out),str(Path(args.old_results)),str(Path(args.old_heads)),str(Path.home())]:
            message=message.replace(private_path,'<input_or_output>')
        state['error']=message
        if current_table is not None: save_gz(out/'INCOMPLETE_TRAIN_SEARCH.json.gz',current_table)
    finally:
        usage=resource.getrusage(resource.RUSAGE_SELF)
        state['measurement']={'cpu_seconds':time.process_time()-begin_cpu,'wall_seconds':time.perf_counter()-begin_wall,
            'process_cpu_seconds_at_finish':time.process_time(),
            'peak_rss_bytes':usage.ru_maxrss if sys.platform=='darwin' else usage.ru_maxrss*1024,
            'pilot_cpu_seconds_separate':sum(r['cpu_seconds'] for r in protocol['feasibility_pilot']['runs']),
            'pilot_is_not_total_cost':True}
        state['environment']={'python':sys.version,'numpy':np.__version__,'platform':platform.platform()}
        save_gz(out/'RESULTS.json.gz',state)
        qualification={'schema':'hepta-ndu-value-grid-qualification-v1','status':state['status'],
            'protocol_sha256':state['protocol_sha256'],'driver_sha256':sha(__file__),
            'results_sha256':sha(out/'RESULTS.json.gz'),'measurement':state['measurement'],
            'source_unchanged':state.get('all_old_inputs_unchanged',False),
            'all_incumbents_in_original_exact_radius':len(state['fits'])==5 and all(r['incumbent_in_original_radius'] for r in state['fits']),
            'fresh_holdout_generated':state['new_holdout_generated'],
            'complete_grid_rows':sum(r.get('candidate_count',0) for r in state['fits']),
            'scientific_status':'exploratory; numerical search completion does not imply task-value qualification',
            'error':state.get('error')}
        save(out/'QUALIFICATION.json',qualification)
        print(json.dumps({'stage':'finished','status':state['status'],'measurement':state['measurement'],
                          'results_sha256':qualification['results_sha256'],'error':state.get('error')}),flush=True)
    return 0 if state['status']=='completed' else 2

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--study-root',required=True); ap.add_argument('--inputs',required=True)
    ap.add_argument('--old-results',required=True); ap.add_argument('--old-heads',required=True); ap.add_argument('--output',required=True)
    arguments=ap.parse_args()
    resource.setrlimit(resource.RLIMIT_CPU,(295,300))
    signal.signal(signal.SIGXCPU,lambda *_:(_ for _ in ()).throw(BudgetExceeded('295 CPU-second signal; hard cap remains 300')))
    with np.errstate(over='raise',invalid='raise',divide='raise'):
        sys.exit(main(arguments))
