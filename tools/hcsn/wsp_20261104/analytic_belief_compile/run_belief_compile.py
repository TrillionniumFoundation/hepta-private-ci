#!/usr/bin/env python3
"""Single frozen pure-weight Belief compilation experiment; bounded CPU."""
from pathlib import Path
import argparse, copy, datetime, gzip, hashlib, importlib.util, json, platform, resource, signal, sys, time
import numpy as np

ROOT = Path(__file__).resolve().parent
FITS = [11, 23, 37, 53, 71]
RAW = ['A', 'C', 'D', 'CD', 'G', 'CG']
CANDIDATES = {'D': 'A', 'CD': 'C', 'G': 'A', 'CG': 'C'}
ALL = RAW + [k+'_gated' for k in CANDIDATES]

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def blob(v): return (json.dumps(v, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
def save(path, value):
    with Path(path).open('xb') as f: f.write(blob(value))
def save_gz(path, value):
    with Path(path).open('xb') as f: f.write(gzip.compress(blob(value), mtime=0))
def unpack(path):
    p=Path(path); b=p.read_bytes(); return gzip.decompress(b) if p.suffix=='.gz' else b
def read(path): return json.loads(unpack(path))
def load_module(path, name):
    spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module); return module
def mean_ci(values):
    x=np.asarray(values,dtype=float); mean=float(x.mean()); half=2.7764451051977987*float(x.std(ddof=1))/np.sqrt(5)
    return {'mean':mean,'per_fit':x.tolist(),'descriptive_paired_95_ci':[mean-half,mean+half],'independent_fits':5}
def head_sha(theta): return hashlib.sha256(np.asarray(theta,dtype='<f8').tobytes()).hexdigest()

class BudgetExceeded(RuntimeError): pass

def probe_record(module, mm, rows, features, A, C, D, G):
    xp=[features.get(r['public'],r['state']) for r in rows]
    H=np.asarray([x for x,p in xp]); own=np.asarray([p for x,p in xp])
    a=mm(H,A.T); c=mm(H,C.T); d=mm(H,D.T); g=mm(H,G.T)
    assert np.array_equal(a[:,:3],d[:,:3]) and np.array_equal(a[:,:3],g[:,:3])
    assert np.array_equal(a[:,3],c[:,3])
    sigmoid=module['NumpyPolicy'].sigmoid
    return {'rows':len(rows),'world_ids':[r['world'] for r in rows],
        'teacher_q':[r['q'] for r in rows],'legal':[r['legal'] for r in rows],
        'teacher_belief':[r['posterior'] for r in rows], 'model_bank7':own.tolist(),
        'A_continuation':a[:,:3].tolist(),'C_continuation':c[:,:3].tolist(),
        'A_belief':sigmoid(a[:,3]).tolist(),'D_belief':sigmoid(d[:,3]).tolist(),'G_belief':sigmoid(g[:,3]).tolist(),
        'A_logit':a[:,3].tolist(),'D_logit':d[:,3].tolist(),'G_logit':g[:,3].tolist(),
        'scope':'Teacher values only in evaluation probe; solver problem contains H/own bank7/b0 only.'}

def probe_metrics(probe, arm):
    belief='D' if arm in ('D','CD') else 'G' if arm in ('G','CG') else 'A'
    continuation='C' if arm in ('C','CD','CG') else 'A'
    p=np.asarray(probe[belief+'_belief']); out=np.asarray(probe[continuation+'_continuation'])
    y=np.asarray(probe['teacher_q']); legal=np.asarray(probe['legal'],dtype=float)
    target=np.asarray(probe['teacher_belief']); own=np.asarray(probe['model_bank7'])
    if not np.all(np.isfinite(own)) or not np.all((0<own)&(own<1)):
        raise ArithmeticError('metric own-bank logit outside strict finite(0,1), no clipping')
    q=np.c_[np.zeros(len(p)),out,1-2*p,2*p-1]
    action=np.where(legal,q,-np.inf).argmax(1); best=np.where(legal,y,-np.inf).max(1)
    return {'expected_rows':len(p),'belief_brier':float(np.mean((p-target)**2)),
        'own_bank_probability_mse':float(np.mean((p-own)**2)),
        'own_bank_logit_mse':float(np.mean((np.asarray(probe[belief+'_logit'])-(np.log(own)-np.log1p(-own)))**2)),
        'q_mse':float(np.mean(((q-y)**2*legal).sum(1)/legal.sum(1))),
        'continuation_q_mse':float(np.sum((out-y[:,1:4])**2*legal[:,1:4])/np.sum(legal[:,1:4])),
        'teacher_behavior_regret':float(np.mean(best-y[np.arange(len(y)),action]))}

def schedule(world, fields):
    assert set(world)==set(fields+['id','packets','packet_sha256'])
    return {k:world[k] for k in fields}

def registered_integer_seeds(value):
    result=set()
    def visit(x, key=''):
        if isinstance(x,dict):
            for k,v in x.items(): visit(v,k)
        elif isinstance(x,list):
            for v in x: visit(v,key)
        elif isinstance(x,int) and not isinstance(x,bool) and 'seed' in key.lower(): result.add(x)
    visit(value); return result

def derive_seed(design_sha, generator_sha, fit, domain, purpose):
    payload={'namespace':'hepta-belief-compile-domain-separation-v1','design_sha256':design_sha,
        'generator_sha256':generator_sha,'fit':fit,'domain':domain,'purpose':purpose,'replication':0}
    encoded=canonical(payload); hexdigest=hashlib.sha256(encoded).hexdigest()
    return {'payload':payload,'sha256':hexdigest,'integer_entropy_decimal':str(int(hexdigest,16))}

def main(args):
    start,wall=time.process_time(),time.perf_counter()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=False)
    study,analytic,inputs=Path(args.study_root),Path(args.analytic_root),Path(args.inputs)
    result={'schema':'hepta-pure-weight-analytic-belief-compilation-v1','status':'started',
        'fits':[],'execution_graph_changed':False,'teacher_targets_used_for_fitting':False,
        'fresh_test_scoring_started':False,'test_worlds_generated':False,'all_test_worlds_generated':False}
    contexts=[]; input_hashes={}
    def budget():
        if time.process_time()-start>=170: raise BudgetExceeded('170CPU graceful stop before180 hard cap')
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        if rss>4*1024**3: raise BudgetExceeded('4GiB sampled RSS cap')
    try:
        protocol=read(ROOT/'PROTOCOL_BEFORE_RESULTS.json');design=read(ROOT/'DESIGN_BEFORE_RESULTS.json')
        result.update(protocol=protocol,protocol_sha256=digest(ROOT/'PROTOCOL_BEFORE_RESULTS.json'))
        assert digest(ROOT/'DESIGN_BEFORE_RESULTS.json')==protocol['design_sha256']
        assert digest(__file__)==design['local_source_sha256']['run_belief_compile.py']
        for name,expected in design['local_source_sha256'].items(): assert digest(ROOT/name)==expected
        for name,expected in design['joint_source_sha256'].items(): assert digest(study/name)==expected
        assert digest(analytic/'run_analytic_belief.py')==design['analytic_driver_sha256']
        assert hashlib.sha256(unpack(args.old_results)).hexdigest()==design['original_results_uncompressed_sha256']
        assert digest(args.old_heads)==design['old_heads_sha256']
        assert design['fits']==FITS and design['raw_arms']==RAW and design['worlds_per_fit_per_domain']==32
        frozen_paths=[ROOT/'PROTOCOL_BEFORE_RESULTS.json',ROOT/'DESIGN_BEFORE_RESULTS.json',
            ROOT/'HISTORY_REGISTRY.json.gz',ROOT/'HISTORICAL_SEED_REGISTRY.json',
            ROOT/'PREVIOUS_177_BEFORE.json',analytic/'run_analytic_belief.py',
            Path(args.old_results),Path(args.old_heads)]
        frozen_paths += [ROOT/name for name in design['local_source_sha256']]
        frozen_paths += [study/name for name in design['joint_source_sha256']]
        input_hashes.update({str(path):digest(path) for path in frozen_paths})
        old={f['fit']:f for f in read(args.old_results)['fits']}; heads={f['fit']:f for f in read(args.old_heads)['fits']}
        history=read(ROOT/'HISTORY_REGISTRY.json.gz'); oldseeds=read(ROOT/'HISTORICAL_SEED_REGISTRY.json')
        assert digest(ROOT/'HISTORY_REGISTRY.json.gz')==design['history_registry_sha256']
        assert digest(ROOT/'HISTORICAL_SEED_REGISTRY.json')==design['historical_seed_registry_sha256']
        fields=history['canonical_schedule_fields']; prior_hashes=set()
        for entry in history['entries']:
            h=hashlib.sha256(canonical(schedule(entry['world'],fields))).hexdigest()
            assert h==entry['schedule_sha256']; prior_hashes.add(h)
        assert len(history['entries'])==1680 and len(prior_hashes)==history['unique_schedule_count']==1616
        integer_history=registered_integer_seeds(oldseeds)
        source=load_module(analytic/'run_analytic_belief.py','frozen_analytic_library')
        solver=load_module(ROOT/'belief_convex.py','frozen_belief_convex')
        module,audit=source.load_checked(study);mm=audit['checked_mm'];module['TEST_WORLDS']=32
        assert solver.REGULARIZATION==1e-4 and solver.PGD_MAX_STEPS==20000 and solver.FW_TOLERANCE==1e-8
        for fit in FITS:
            budget();fstart=time.process_time()
            mp=inputs/f'fit_{fit}/model_renewal/model.json';dp=inputs/f'fit_{fit}/data/fit_{fit}_data.json'
            assert digest(mp)==old[fit]['source_model_sha256'] and digest(dp)==old[fit]['source_data_sha256']
            input_hashes[str(mp)]=digest(mp); input_hashes[str(dp)]=digest(dp)
            artifact=read(mp);data=read(dp)
            assert artifact['head_dimensions']==[85,48,4] and artifact['family']=='renewal'
            assert artifact['target']==design['required_target'] and artifact['bank_semantics']==design['required_bank_semantics']
            A=module['head'](artifact); old_artifact=copy.deepcopy(artifact)
            old_artifact['network']['w2']=heads[fit]['network_w2'];old_artifact['network']['b2']=heads[fit]['network_b2']
            assert hashlib.sha256(blob(old_artifact)).hexdigest()==old[fit]['candidate_model_sha256']
            C=module['head'](old_artifact);assert np.array_equal(A[3],C[3])
            features=source.Features(module['NumpyPolicy'](artifact),mm)
            fit_feature_start=time.process_time()
            train_xp=[features.get(r['public'],r['state']) for r in data['train']['rows']]
            H=np.asarray([x for x,p in train_xp]);p=np.asarray([p for x,p in train_xp])
            fit_feature_cpu=time.process_time()-fit_feature_start
            problem=solver.prepare(H,p,A[3],mm)
            problem_record=solver.problem_record(problem)
            problem_record.update(fit=fit,source_model_sha256=digest(mp),source_data_sha256=digest(dp),
                fitting_feature_construction_cpu_seconds=fit_feature_cpu)
            pname=f'fit_{fit}_PROBLEM.json.gz';save_gz(out/pname,problem_record)
            db,direct=solver.direct(problem,mm,budget)
            gb,gradient=solver.pgd(problem,mm,budget)
            sname=f'fit_{fit}_SOLVERS.json'
            solver_record={'fit':fit,'problem_sha256':digest(out/pname),'direct':direct,'gradient':gradient,
                'shared_setup_cpu_seconds':problem['setup_cpu_seconds'],
                'same_convex_FW_precision_cost_comparison_allowed':bool(direct['converged_to_declared_FW_tolerance'] and gradient['converged_to_declared_FW_tolerance']),
                'direct_gradient_objective_difference':direct['objective']-gradient['objective'],
                'scope':'Same fixed convex self-target problem and own FW stop. No full-model-training comparison.'}
            save(out/sname,solver_record)
            if not direct['converged_to_declared_FW_tolerance']:
                raise ArithmeticError('direct numerical convex fit failed predeclared FW tolerance')
            if direct['linear_equation_residual_linf']>1e-9*(1+float(np.max(np.abs(problem['rhs'])))):
                raise ArithmeticError('independent direct linear residual gate failed')
            definitions={'A':A,'C':C};candidate_models={}
            for key,base,b in [('D',A,db),('CD',C,db),('G',A,gb),('CG',C,gb)]:
                candidate=base.copy();candidate[3]=b
                assert np.array_equal(candidate[:3],base[:3])
                compiled=copy.deepcopy(old_artifact if key in ('CD','CG') else artifact)
                compiled['network']['w2'][3]=b[:-1].tolist();compiled['network']['b2'][3]=float(b[-1])
                encoded=blob(compiled);roundtrip=read_bytes_model=json.loads(encoded)
                actual_head=module['head'](roundtrip)
                assert np.array_equal(actual_head,candidate)
                restored=copy.deepcopy(roundtrip)
                parent=old_artifact if key in ('CD','CG') else artifact
                restored['network']['w2'][3]=copy.deepcopy(parent['network']['w2'][3])
                restored['network']['b2'][3]=parent['network']['b2'][3]
                assert restored==parent
                definitions[key]=actual_head
                candidate_models[key]={'canonical_model_sha256':hashlib.sha256(encoded).hexdigest(),
                    'network_w2':roundtrip['network']['w2'],'network_b2':roundtrip['network']['b2'],
                    'only_belief_row_changes_verified':True,'json_roundtrip_head_identical':True}
            f={'fit':fit,'source_model_sha256':digest(mp),'source_data_sha256':digest(dp),
                'problem_file':pname,'problem_file_sha256':digest(out/pname),
                'solver_file':sname,'solver_file_sha256':digest(out/sname),'solvers':solver_record,
                'head_sha256':{k:head_sha(v) for k,v in definitions.items()},
                'heads':{k:v.tolist() for k,v in definitions.items()},
                'candidate_models':candidate_models,
                'edited_parameter_scope':'Only49 Belief-row+bias coordinates relative to each paired A/C incumbent; W1/core/decoder/continuation unchanged.',
                'new_changed_parameters':{k:int(np.count_nonzero(definitions[k][3]!=definitions[base][3])) for k,base in CANDIDATES.items()},
                'train':{},'validation':{},'probes':{},'gates':{},'tests':{}}
            for split in ['train','validation']:
                rows=data[split]['rows'];worlds=module['public_unique'](rows)
                assert len(worlds)==(64 if split=='train' else 16)
                for world in worlds:
                    assert hashlib.sha256(canonical(schedule(world,fields))).hexdigest() in prior_hashes
                oracles={w['id']:module['Oracle'](w,module['law'],artifact['confusion']) for w in worlds}
                probe=probe_record(module,mm,rows,features,A,C,definitions['D'],definitions['G'])
                filename=f'fit_{fit}_{split}_PROBE.json.gz';save_gz(out/filename,probe)
                f['probes'][split]={'file':filename,'sha256':digest(out/filename),'rows':len(rows)}
                evaluated={}
                for name,theta in definitions.items():
                    budget();key=head_sha(theta)
                    if key not in evaluated: evaluated[key]=source.evaluate(module,worlds,theta,features,oracles,False)
                    item=copy.deepcopy(evaluated[key]);item.update(probe_metrics(probe,name));f[split][name]=item
                f[split]['world_count']=len(worlds)
            assert abs(f['validation']['A']['expected_utility']-old[fit]['baseline_validation_utility'])<1e-10
            assert abs(f['validation']['C']['expected_utility']-old[fit]['selected_direct']['validation_utility'])<1e-10
            arms=dict(definitions)
            for name,base in CANDIDATES.items():
                gain=f['validation'][name]['expected_utility']-f['validation'][base]['expected_utility']
                accepted=gain>=.005
                f['gates'][name]={'incumbent':base,'validation_gain':gain,'accepted':accepted,
                    'reused_original_validation':True,'gated_parent_hash':head_sha(definitions[base]),
                    'restore_if_rejected_verified':True}
                arms[name+'_gated']=definitions[name] if accepted else definitions[base]
                assert accepted or np.array_equal(arms[name+'_gated'],definitions[base])
            f['timing_before_test']={'cpu_seconds':time.process_time()-fstart,
                'feature_cache_cpu_seconds':features.seconds,'feature_states':features.calls}
            save(out/f'fit_{fit}_BEFORE_TEST.json',f)
            result['fits'].append(f);contexts.append({'artifact':artifact,'features':features,'definitions':definitions,'arms':arms})
            print(json.dumps({'stage':'solvers_and_original_gates_frozen','fit':fit,
                'D_FW_gap':direct['numerical_fw_gap'],'G_FW_gap':gradient['numerical_fw_gap'],
                'G_steps':gradient['steps'],'G_converged':gradient['converged_to_declared_FW_tolerance'],
                'accepted':{k:v['accepted'] for k,v in f['gates'].items()},'cpu':time.process_time()-start}),flush=True)
        frozen={'protocol_sha256':result['protocol_sha256'],'design_sha256':protocol['design_sha256'],
            'written_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'test_worlds_generated':False,'test_scoring_started':False,'fits':copy.deepcopy(result['fits']),
            'record_sha256':{p.name:digest(p) for p in out.iterdir() if p.is_file()}}
        save(out/'ALL_SOLVERS_AND_GATES_BEFORE_TEST.json',frozen)
        result['selection_freeze_sha256']=digest(out/'ALL_SOLVERS_AND_GATES_BEFORE_TEST.json')
        print(json.dumps({'stage':'all_five_solver_and_gate_records_frozen_before_generation',
            'sha256':result['selection_freeze_sha256']}),flush=True)
        # Generate and audit all320 worlds before any test scorer/Oracle call.
        generated={};seen=set();seed_seen=set();seed_records=[];world_records=[];duplicates=[]
        for fit in FITS:
            for domain in ['iid','ood']:
                budget()
                seeds={purpose:derive_seed(protocol['design_sha256'],design['joint_source_sha256']['run_head_edit.py'],fit,domain,purpose) for purpose in ['worlds','behavior_probes']}
                for purpose,record in seeds.items():
                    expected=[r for r in protocol['derived_rng_streams'] if r['payload']['fit']==fit and r['payload']['domain']==domain and r['payload']['purpose']==purpose]
                    assert len(expected)==1 and expected[0]==record
                    entropy=int(record['integer_entropy_decimal'])
                    if entropy in integer_history or entropy in seed_seen: raise ArithmeticError('domain-separated seed collides with registered integer seed')
                    seed_seen.add(entropy);seed_records.append(record)
                module['SEED']=int(seeds['worlds']['integer_entropy_decimal'])-fit*10000-(1000000 if domain=='ood' else 0)
                worlds=module['make_worlds'](fit,domain)
                result['test_worlds_generated']=True
                for i,w in enumerate(worlds):
                    w['id']=f'belief_compile_{protocol["design_sha256"][:16]}_{fit}_{domain}_{i}'
                    fingerprint=hashlib.sha256(canonical(schedule(w,fields))).hexdigest()
                    if fingerprint in prior_hashes: duplicates.append({'fit':fit,'domain':domain,'index':i,'kind':'registered_history','schedule_sha256':fingerprint})
                    if fingerprint in seen: duplicates.append({'fit':fit,'domain':domain,'index':i,'kind':'within_current320','schedule_sha256':fingerprint})
                    seen.add(fingerprint)
                filename=f'fit_{fit}_{domain}_WORLDS.json.gz';save_gz(out/filename,worlds)
                world_records.append({'fit':fit,'domain':domain,'file':filename,'sha256':digest(out/filename),
                    'schedule_sha256':[hashlib.sha256(canonical(schedule(w,fields))).hexdigest() for w in worlds]})
                generated[(fit,domain)]={'worlds':worlds,'seeds':seeds,'world_record':world_records[-1]}
        result['all_test_worlds_generated']=True
        dedup={'schema':'hepta-belief-compile-before-scoring-dedup-v1','design_sha256':protocol['design_sha256'],
            'selection_freeze_sha256':result['selection_freeze_sha256'],'test_scoring_started':False,
            'world_count':320,'unique_world_schedule_count':len(seen),'history_occurrences':1680,
            'history_unique_schedules':1616,'history_registry_sha256':design['history_registry_sha256'],
            'historical_seed_registry_sha256':design['historical_seed_registry_sha256'],
            'registered_integer_seeds_checked':len(integer_history),'seed_records':seed_records,
            'world_records':world_records,'duplicates':duplicates,'passed':not duplicates,
            'coverage':history['covered'],'uncovered':history['not_covered'],
            'global_unseen_beyond_registered_history_claim':False,'seed_reselection':False,'resampling':False}
        save(out/'ALL_TEST_WORLDS_DEDUP_BEFORE_SCORING.json',dedup)
        result['dedup_before_scoring_sha256']=digest(out/'ALL_TEST_WORLDS_DEDUP_BEFORE_SCORING.json')
        if duplicates: raise ArithmeticError('known content duplicate detected: stop without any test score or seed retry')
        assert len(seen)==320
        print(json.dumps({'stage':'all320_worlds_deduplicated_before_any_test_scoring',
            'sha256':result['dedup_before_scoring_sha256'],'known_duplicates':0}),flush=True)
        result['fresh_test_scoring_started']=True
        for f,context in zip(result['fits'],contexts):
            fit=f['fit'];features=context['features'];definitions=context['definitions'];teststart=time.process_time()
            for domain in ['iid','ood']:
                budget();gen=generated[(fit,domain)];worlds=gen['worlds']
                module['SEED']=int(gen['seeds']['behavior_probes']['integer_entropy_decimal'])-fit*10000-5000000-(100000 if domain=='ood' else 0)
                rows=module['behavior_rows'](worlds,context['artifact']['confusion'],fit,domain)
                probe=probe_record(module,mm,rows,features,definitions['A'],definitions['C'],definitions['D'],definitions['G'])
                filename=f'fit_{fit}_{domain}_PROBE.json.gz';save_gz(out/filename,probe)
                oracles={w['id']:module['Oracle'](w,module['law'],context['artifact']['confusion']) for w in worlds}
                evaluations={};arms={}
                for name,theta in context['arms'].items():
                    budget();key=head_sha(theta)
                    rawname=name.removesuffix('_gated')
                    metric_name=rawname if name in RAW or f['gates'][rawname]['accepted'] else CANDIDATES[rawname]
                    if key not in evaluations: evaluations[key]=source.evaluate(module,worlds,theta,features,oracles,False)
                    item=copy.deepcopy(evaluations[key]);item.update(probe_metrics(probe,metric_name));arms[name]=item
                f['tests'][domain]={'world_count':32,'world_file':gen['world_record']['file'],
                    'world_file_sha256':gen['world_record']['sha256'],'probe_file':filename,'probe_file_sha256':digest(out/filename),
                    'arms':arms,'unique_parameter_policies_evaluated':len(evaluations)}
            assert source.policy_parameter_hash(features.policy)==features.parameter_hash
            assert {k:head_sha(v) for k,v in definitions.items()}==f['head_sha256']
            f['runtime_parameters_unchanged_after_evaluation']=True
            f['probability_audit']={'minimum_bank7':features.min_p,'maximum_bank7':features.max_p,
                'maximum_same_model_deadline_identity_error':features.max_identity_error,'feature_states':features.calls,
                'new_probability_clipping':0,'teacher_inputs_to_fitting':0}
            f['test_cpu_seconds']=time.process_time()-teststart
            print(json.dumps({'stage':'test_complete','fit':fit,'cpu':time.process_time()-start}),flush=True)
        metrics=['expected_utility','belief_brier','q_mse','continuation_q_mse','teacher_behavior_regret','own_bank_probability_mse','own_bank_logit_mse']
        contrasts={k+'_minus_'+base:(k,base) for k,base in CANDIDATES.items()}
        contrasts.update({k+'_gated_minus_'+base:(k+'_gated',base) for k,base in CANDIDATES.items()})
        contrasts.update({'D_minus_G':('D','G'),'CD_minus_CG':('CD','CG'),'C_minus_A':('C','A')})
        result['summary']={}
        for domain in ['iid','ood']:
            values=lambda arm,key:np.asarray([f['tests'][domain]['arms'][arm][key] for f in result['fits']])
            summary={'arms':{},'contrasts':{}}
            for arm in ALL:
                summary['arms'][arm]={key:{'mean':float(values(arm,key).mean()),'per_fit':values(arm,key).tolist()} for key in metrics}
            for name,(a,b) in contrasts.items():
                summary['contrasts'][name]={key:mean_ci(values(a,key)-values(b,key)) for key in metrics}
            result['summary'][domain]=summary
        assert all(digest(p)==h for p,h in input_hashes.items())
        for name,h in design['joint_source_sha256'].items(): assert digest(study/name)==h
        for name,h in design['local_source_sha256'].items(): assert digest(ROOT/name)==h
        assert digest(analytic/'run_analytic_belief.py')==design['analytic_driver_sha256']
        result.update(status='completed',all_original_inputs_and_sources_unchanged=True,matmul_audit=audit['AUDIT'])
    except Exception as exc:
        result.update(status='blocked',error_type=type(exc).__name__)
        message=str(exc)
        for path in [str(study),str(analytic),str(inputs),str(out),str(ROOT),str(Path.home()),args.old_results,args.old_heads]: message=message.replace(path,'<source_or_output>')
        result['error']=message
    finally:
        usage=resource.getrusage(resource.RUSAGE_SELF)
        result['measurement']={'cpu_seconds':time.process_time()-start,'wall_seconds':time.perf_counter()-wall,
            'process_cpu_seconds_at_measurement':time.process_time(),'peak_rss_bytes':usage.ru_maxrss*(1 if sys.platform=='darwin' else 1024),
            'endpoint':'Before final results compression and qualification write;180CPU hard cap covers whole process.'}
        result['environment']={'python':sys.version,'numpy':np.__version__,'platform':platform.platform()}
        save_gz(out/'RESULTS.json.gz',result)
        qualification={'schema':'hepta-belief-compile-process-qualification-v1','status':result['status'],
            'driver_sha256':digest(__file__),'results_sha256':digest(out/'RESULTS.json.gz'),
            'protocol_sha256':result.get('protocol_sha256'),'measurement':result['measurement'],
            'execution_graph_changed':False,'edited_parameter_scope':'49 Belief weights per candidate only',
            'new_full_model_training':False,'test_scoring_started':result['fresh_test_scoring_started'],
            'gates_accepted':{k:sum(f.get('gates',{}).get(k,{}).get('accepted',False) for f in result['fits']) for k in CANDIDATES},
            'error':result.get('error')}
        save(out/'QUALIFICATION.json',qualification)
        print(json.dumps({'stage':'finished','status':result['status'],'measurement':result['measurement'],
            'gates_accepted':qualification['gates_accepted'],'results_sha256':qualification['results_sha256'],
            'error':result.get('error')}),flush=True)
    return 0 if result['status']=='completed' else 2

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for name in ['study-root','analytic-root','inputs','old-results','old-heads','output']:ap.add_argument('--'+name,required=True)
    args=ap.parse_args();resource.setrlimit(resource.RLIMIT_CPU,(175,180))
    signal.signal(signal.SIGXCPU,lambda *_:(_ for _ in ()).throw(BudgetExceeded('175CPU signal before180 hard cap')))
    with np.errstate(over='raise',invalid='raise',divide='raise'):sys.exit(main(args))
