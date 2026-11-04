#!/usr/bin/env python3
"""One-shot analytic Belief execution-graph ablation; zero weight edits."""
from pathlib import Path
import argparse,ast,copy,datetime,gzip,hashlib,json,platform,resource,signal,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parent
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def blob(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
def save(path,value):
    with Path(path).open('xb') as f:f.write(blob(value))
def save_gz(path,value):
    with Path(path).open('xb') as f:f.write(gzip.compress(blob(value),mtime=0))
def unpack(path):
    path=Path(path);b=path.read_bytes();return gzip.decompress(b) if path.suffix=='.gz' else b
def mean_ci(values):
    v=np.asarray(values,dtype=float);m=float(v.mean());h=2.7764451051977987*float(v.std(ddof=1))/np.sqrt(5)
    return {'mean':m,'per_fit':v.tolist(),'descriptive_paired_95_ci':[m-h,m+h],'independent_fits':5}
def load_checked(study):
    tree=ast.parse((study/'checked_replay.py').read_text());defs=[]
    for n in tree.body:
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('checked_mm','MM'):defs.append(n)
        elif isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='AUDIT' for t in n.targets):defs.append(n)
    a={'np':np,'ast':ast};exec(compile(ast.Module(body=defs,type_ignores=[]),'checked_primitives','exec'),a)
    source=(study/'run_head_edit.py').read_text();needle='tree=ast.parse((ROOT/file).read_text(),filename=file)'
    assert source.count(needle)==1
    source=source.replace(needle,needle+"\n    tree=ast.fix_missing_locations(MM().visit(tree));ns['checked_mm']=checked_mm")
    tree=ast.fix_missing_locations(a['MM']().visit(ast.parse(source)))
    m={'__name__':'analytic_belief_import_only','__file__':str(study/'run_head_edit.py'),'checked_mm':a['checked_mm'],'MM':a['MM']}
    exec(compile(tree,str(study/'run_head_edit.py'),'exec'),m);return m,a
def policy_parameter_hash(policy):
    h=hashlib.sha256()
    for name,a in sorted(policy.network.items()):h.update(name.encode());h.update(np.asarray(a).tobytes())
    for key,a in sorted(policy.tables.items()):h.update(str(key).encode());h.update(np.asarray(a).tobytes())
    h.update(policy.confusion.tobytes());h.update(policy.mask.tobytes())
    return h.hexdigest()

class Features:
    """Only checkpoint/model inputs; no Oracle, target posterior or teacher rows."""
    def __init__(self,policy,checked):
        self.policy,self.checked=policy,checked;self.memo={};self.seconds=0.;self.calls=0
        self.positive=np.asarray(policy.artifact['coordinates'])>0
        self.min_p=1.;self.max_p=0.;self.max_identity_error=0.
        self.parameter_hash=policy_parameter_hash(policy)
    def get(self,public,state):
        key=json.dumps([public,state],sort_keys=True,separators=(',',':'))
        if key not in self.memo:
            start=time.process_time();mass,bank,pub=self.policy.represent(public,state)
            p=float(bank[7])
            if not np.isfinite(p) or not 0.<=p<=1.:raise ArithmeticError('analytic bank7 probability outside finite[0,1]; no clipping')
            # Independent same-model deadline/strict-sign identity check, not a teacher calculation.
            future=mass.copy()
            for i in range(state['tick'],6):
                future=self.checked(future,self.policy.tables[(public['duration'][i],public['drive'][i])])
            expected=float(np.sum(future[self.positive]));error=abs(p-expected)
            if not np.isfinite(expected) or error>2e-12:raise ArithmeticError('bank7 deadline6 strict-sign identity mismatch')
            n=self.policy.network;raw=np.r_[pub,mass,bank]
            assert len(raw)==85 and float(raw[83])==p
            x=np.r_[np.tanh(self.checked(n['w1'],raw)+n['b1']),1.]
            self.memo[key]=(x,p);self.calls+=1;self.seconds+=time.process_time()-start
            self.min_p=min(self.min_p,p);self.max_p=max(self.max_p,p);self.max_identity_error=max(self.max_identity_error,error)
        return self.memo[key]
    def __call__(self,public,state):return self.get(public,state)[0]

def scores(module,theta,features,public,state,project):
    x,bank_p=features.get(public,state);q,p=module['predicted'](theta,x)
    if project:
        p=bank_p;q[4]=1-2*p;q[5]=2*p-1
    return q,p

def utility(module,public,theta,features,oracle,project):
    visits=0
    def recurse(state):
        nonlocal visits
        visits+=1;q,_=scores(module,theta,features,public,state,project)
        action=int(np.where(module['legal'](public,state),q,-np.inf).argmax())
        if action==0:return 0.
        if action in (4,5):
            target=oracle.posterior(state)
            return 1-2*target if action==4 else 2*target-1
        total=0.
        for probability,completion in module['outcomes'](public,state,action,oracle):
            if probability:
                after=module['successor'](public,state,action,completion)
                total+=probability*(recurse(after)-(after['charges']-state['charges']))
        return total
    return recurse(module['initial'](public)),visits

def evaluate(module,worlds,theta,features,oracles,project):
    rows=[utility(module,p,theta,features,oracles[p['id']],project) for p in worlds]
    values=[float(v) for v,_ in rows]
    return {'expected_utility':float(np.mean(values)),'world_utilities':values,'visited_nodes':sum(n for _,n in rows)}

def probe_record(module,checked,rows,features,A,C):
    xp=[features.get(r['public'],r['state']) for r in rows];x=np.array([v[0] for v in xp]);pbank=np.array([v[1] for v in xp])
    a=checked(x,A.T);c=checked(x,C.T);pa=module['NumpyPolicy'].sigmoid(a[:,3]);pc=module['NumpyPolicy'].sigmoid(c[:,3])
    assert np.array_equal(pa,pc)
    return {'rows':len(rows),'world_ids':[r['world'] for r in rows],
        'teacher_q':[r['q'] for r in rows],'legal':[r['legal'] for r in rows],
        'teacher_belief':[r['posterior'] for r in rows],'model_bank7':pbank.tolist(),
        'learned_belief':pa.tolist(),'A_continuation':a[:,:3].tolist(),'C_continuation':c[:,:3].tolist(),
        'scope':'teacher values are metric targets only; policy feature/scorer has no teacher input'}

def probe_metrics(probe,arm):
    y=np.asarray(probe['teacher_q']);mask=np.asarray(probe['legal'],dtype=float);target=np.asarray(probe['teacher_belief'])
    p=np.asarray(probe['model_bank7'] if arm in ('P','CP') else probe['learned_belief'])
    continuation=np.asarray(probe['C_continuation'] if arm in ('C','CP') else probe['A_continuation'])
    q=np.c_[np.zeros(len(p)),continuation,1-2*p,2*p-1]
    action=np.where(mask,q,-np.inf).argmax(1);best=np.where(mask,y,-np.inf).max(1)
    return {'q_mse':float(np.mean(((q-y)**2*mask).sum(1)/mask.sum(1))),
        'continuation_q_mse':float(np.sum((continuation-y[:,1:4])**2*mask[:,1:4])/np.sum(mask[:,1:4])),
        'belief_brier':float(np.mean((p-target)**2)),
        'teacher_behavior_regret':float(np.mean(best-y[np.arange(len(y)),action])),'rows':len(p)}

class BudgetExceeded(RuntimeError):pass

def main(args):
    study=Path(args.study_root);inputs=Path(args.inputs);out=Path(args.output)
    if out.exists():raise FileExistsError('new output directory required')
    protocol=json.loads((ROOT/'PROTOCOL_BEFORE_RESULTS.json').read_text())
    semantics=json.loads((ROOT/'SEMANTICS_BEFORE_RUN.json').read_text());semfits={r['fit']:r for r in semantics['models']}
    assert digest(__file__)==protocol['driver_sha256'] and digest(ROOT/'SEMANTICS_BEFORE_RUN.json')==protocol['semantics_sha256']
    assert digest(ROOT/'SOURCE_SEMANTICS.md')==protocol['source_argument_sha256']
    assert {n:digest(study/n) for n in protocol['source_sha256']}==protocol['source_sha256']
    oldb=unpack(args.old_results);assert hashlib.sha256(oldb).hexdigest()==protocol['original_results_uncompressed_sha256']
    assert digest(args.old_heads)==protocol['old_heads_gzip_sha256']
    oldfits={r['fit']:r for r in json.loads(oldb)['fits']};oldheads={r['fit']:r for r in json.loads(unpack(args.old_heads))['fits']}
    out.mkdir(parents=True,exist_ok=False);start=time.process_time();wall=time.perf_counter()
    result={'schema':'hepta-analytic-belief-structure-ablation-v1','status':'started','protocol':protocol,
        'protocol_sha256':digest(ROOT/'PROTOCOL_BEFORE_RESULTS.json'),'new_weight_parameters_changed':0,
        'execution_graph_changed':True,'fresh_holdout_generated':False,'fits':[]}
    contexts=[];input_hashes={}
    def budget():
        if time.process_time()-start>=110:raise BudgetExceeded('110 CPU-second graceful stop before120 hard cap')
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        if rss>4*1024**3:raise BudgetExceeded('4GiB sampled RSS cap')
    try:
        m,audit=load_checked(study);m['SEED']=protocol['seed'];m['TEST_WORLDS']=32
        for fit in protocol['fits']:
            budget();begin=time.process_time();prior=oldfits[fit];h=oldheads[fit]
            mp=inputs/f'fit_{fit}/model_renewal/model.json';dp=inputs/f'fit_{fit}/data/fit_{fit}_data.json'
            assert digest(mp)==prior['source_model_sha256']==semfits[fit]['sha256'] and digest(dp)==prior['source_data_sha256']
            input_hashes[str(mp)]=digest(mp);input_hashes[str(dp)]=digest(dp)
            artifact=json.loads(mp.read_text());data=json.loads(dp.read_text())
            for key in ('schema','family','n_grid','head_dimensions','bank_semantics','target'):
                assert artifact[key]==semfits[fit][key]
            assert artifact['family']=='renewal' and artifact['head_dimensions']==[85,48,4]
            assert artifact['target']==protocol['required_target'] and artifact['bank_semantics']==protocol['required_bank_semantics']
            assert np.array_equal(np.asarray(artifact['coordinates']),np.r_[np.linspace(-1.,1.,33)[1:-1],-1.,1.])
            old_artifact=copy.deepcopy(artifact);old_artifact['network']['w2']=h['network_w2'];old_artifact['network']['b2']=h['network_b2']
            assert hashlib.sha256(blob(old_artifact)).hexdigest()==prior['candidate_model_sha256']==h['candidate_model_sha256']
            A=m['head'](artifact);C=m['head'](old_artifact);assert np.array_equal(A[3],C[3])
            ah=hashlib.sha256(A.tobytes()).hexdigest();ch=hashlib.sha256(C.tobytes()).hexdigest()
            features=Features(m['NumpyPolicy'](artifact),audit['checked_mm'])
            definitions={'A':(A,False),'C':(C,False),'P':(A,True),'CP':(C,True)}
            f={'fit':fit,'source_model_sha256':prior['source_model_sha256'],'source_data_sha256':prior['source_data_sha256'],
               'C_model_sha256':prior['candidate_model_sha256'],'A_P_head_sha256':ah,'C_CP_head_sha256':ch,
               'same_representation_and_decoder_for_all_arms':True,'new_weight_parameters_changed':0,
               'train':{},'validation':{},'probes':{},'tests':{},'timing':{}}
            ids={}
            for split in ('train','validation'):
                rows=data[split]['rows'];worlds=m['public_unique'](rows);ids[split]={p['id'] for p in worlds}
                for p in worlds:m['ns']['validate_public'](p)
                oracles={p['id']:m['Oracle'](p,m['law'],artifact['confusion']) for p in worlds}
                probe=probe_record(m,audit['checked_mm'],rows,features,A,C);name=f'fit_{fit}_{split}_PROBE.json.gz';save_gz(out/name,probe)
                f['probes'][split]={'file':name,'sha256':digest(out/name),'rows':len(rows)}
                for arm,(theta,project) in definitions.items():
                    budget();v=evaluate(m,worlds,theta,features,oracles,project);v.update(probe_metrics(probe,arm));f[split][arm]=v
                f[split]['world_count']=len(worlds)
            assert not ids['train']&ids['validation']
            assert abs(f['validation']['A']['expected_utility']-prior['baseline_validation_utility'])<=1e-10
            assert abs(f['validation']['C']['expected_utility']-prior['selected_direct']['validation_utility'])<=1e-10
            # Full reference-policy parity on original VAL, no extra candidate.
            for arm,theta in [('A',A),('C',C)]:
                u,values,nodes=m['eval_worlds'](worlds,theta,features,oracles)
                assert u==f['validation'][arm]['expected_utility'] and values==f['validation'][arm]['world_utilities']
            pgain=f['validation']['P']['expected_utility']-f['validation']['A']['expected_utility']
            cpgain=f['validation']['CP']['expected_utility']-f['validation']['C']['expected_utility']
            gates={'P':{'reference':'A','validation_gain':pgain,'accepted':pgain>=.005},
                   'CP':{'reference':'C','validation_gain':cpgain,'accepted':cpgain>=.005}}
            arms=dict(definitions);arms['P_gated']=definitions['P'] if gates['P']['accepted'] else definitions['A']
            arms['CP_gated']=definitions['CP'] if gates['CP']['accepted'] else definitions['C']
            for arm,g in gates.items():
                g['restored_execution_mode_if_rejected']=not g['accepted'];g['paired_checkpoint_parameters_unchanged']=True
            f['gates']=gates;f['timing']['before_test_cpu_seconds']=time.process_time()-begin
            result['fits'].append(f);contexts.append({'fit':fit,'artifact':artifact,'A':A,'C':C,'ah':ah,'ch':ch,
                'features':features,'definitions':definitions,'arms':arms,'seen_ids':ids['train']|ids['validation']})
            save(out/f'fit_{fit}_BEFORE_TEST.json',f)
            print(json.dumps({'stage':'original_train_val_fixed','fit':fit,'P_val_gain':pgain,'CP_val_gain':cpgain,
                              'P_accepted':gates['P']['accepted'],'CP_accepted':gates['CP']['accepted'],'cpu':time.process_time()-start}),flush=True)
        frozen={'protocol_sha256':result['protocol_sha256'],'driver_sha256':digest(__file__),
            'written_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fresh_test_generated_at_write':False,
            'fits':copy.deepcopy(result['fits']),'record_file_sha256':{p.name:digest(p) for p in out.iterdir() if p.is_file()}}
        save(out/'ALL_TRAIN_VAL_BEFORE_TEST.json',frozen);result['before_test_sha256']=digest(out/'ALL_TRAIN_VAL_BEFORE_TEST.json')
        print(json.dumps({'stage':'all_five_gates_frozen_before_new_test','sha256':result['before_test_sha256']}),flush=True)
        for context,f in zip(contexts,result['fits']):
            fit=context['fit'];features=context['features'];begin=time.process_time()
            for domain in ('iid','ood'):
                budget();worlds=m['make_worlds'](fit,domain);result['fresh_holdout_generated']=True
                for i,p in enumerate(worlds):p['id']=f'analytic_belief_{protocol["seed"]}_{domain}_{fit}_{i}'
                assert not {p['id'] for p in worlds}&context['seen_ids']
                oracles={p['id']:m['Oracle'](p,m['law'],context['artifact']['confusion']) for p in worlds}
                rows=m['behavior_rows'](worlds,context['artifact']['confusion'],fit,domain)
                probe=probe_record(m,audit['checked_mm'],rows,features,context['A'],context['C'])
                pn=f'fit_{fit}_{domain}_PROBE.json.gz';wn=f'fit_{fit}_{domain}_WORLDS.json.gz';save_gz(out/pn,probe);save_gz(out/wn,worlds)
                arm_result={};cache={}
                for arm,(theta,project) in context['arms'].items():
                    budget();key=(theta.tobytes(),project)
                    if key not in cache:
                        v=evaluate(m,worlds,theta,features,oracles,project)
                        metric_arm=('CP' if np.array_equal(theta,context['C']) else 'P') if project else ('C' if np.array_equal(theta,context['C']) else 'A')
                        v.update(probe_metrics(probe,metric_arm));cache[key]=v
                    arm_result[arm]=copy.deepcopy(cache[key])
                f['tests'][domain]={'world_count':len(worlds),'world_file':wn,'world_file_sha256':digest(out/wn),
                    'probe_file':pn,'probe_file_sha256':digest(out/pn),'arms':arm_result}
            assert policy_parameter_hash(features.policy)==features.parameter_hash
            assert hashlib.sha256(context['A'].tobytes()).hexdigest()==context['ah'] and hashlib.sha256(context['C'].tobytes()).hexdigest()==context['ch']
            f['runtime_model_parameters_unchanged']=True
            f['probability_audit']={'unique_feature_states':features.calls,'minimum_bank7':features.min_p,'maximum_bank7':features.max_p,
                'maximum_same_model_deadline_identity_error':features.max_identity_error,'out_of_range_or_nonfinite':0,'projection_clipping_operations':0,'teacher_inputs_to_projection':0}
            f['timing'].update(test_cpu_seconds=time.process_time()-begin,feature_cpu_seconds=features.seconds)
            print(json.dumps({'stage':'fresh_test_complete','fit':fit,'cpu':time.process_time()-start}),flush=True)
        result['summary']={}
        pairs={'P_minus_A':('P','A'),'CP_minus_C':('CP','C'),'P_gated_minus_A':('P_gated','A'),
               'CP_gated_minus_C':('CP_gated','C'),'C_minus_A':('C','A'),'interaction':None}
        for domain in ('iid','ood'):
            def values(arm,key):return np.array([f['tests'][domain]['arms'][arm][key] for f in result['fits']])
            summary={'arms':{},'contrasts':{}}
            for arm in contexts[0]['arms']:
                summary['arms'][arm]={key:{'mean':float(values(arm,key).mean()),'per_fit':values(arm,key).tolist()}
                    for key in ('expected_utility','belief_brier','q_mse','continuation_q_mse','teacher_behavior_regret')}
            for name,pair in pairs.items():
                summary['contrasts'][name]={}
                for key in ('expected_utility','belief_brier','q_mse'):
                    delta=values(pair[0],key)-values(pair[1],key) if pair else values('CP',key)-values('C',key)-values('P',key)+values('A',key)
                    summary['contrasts'][name][key]=mean_ci(delta)
            result['summary'][domain]=summary
        assert all(digest(p)==v for p,v in input_hashes.items())
        assert {n:digest(study/n) for n in protocol['source_sha256']}==protocol['source_sha256']
        assert hashlib.sha256(unpack(args.old_results)).hexdigest()==protocol['original_results_uncompressed_sha256']
        assert digest(args.old_heads)==protocol['old_heads_gzip_sha256']
        result.update(status='completed',all_original_inputs_unchanged=True,matmul_audit=audit['AUDIT'])
    except Exception as exc:
        result['status']='blocked';result['error_type']=type(exc).__name__;message=str(exc)
        for p in [str(study),str(inputs),str(out),str(Path.home()),str(args.old_results),str(args.old_heads)]:message=message.replace(p,'<source_or_output>')
        result['error']=message
    finally:
        usage=resource.getrusage(resource.RUSAGE_SELF)
        result['measurement']={'cpu_seconds':time.process_time()-start,'wall_seconds':time.perf_counter()-wall,
            'process_cpu_seconds_at_measurement':time.process_time(),'peak_rss_bytes':usage.ru_maxrss*(1 if sys.platform=='darwin' else 1024),
            'endpoint':'before final results compression and qualification write;120 CPU hard cap covers whole process'}
        result['environment']={'python':sys.version,'numpy':np.__version__,'platform':platform.platform()}
        save_gz(out/'RESULTS.json.gz',result)
        q={'schema':'hepta-analytic-belief-qualification-v1','status':result['status'],'driver_sha256':digest(__file__),
            'protocol_sha256':result['protocol_sha256'],'results_sha256':digest(out/'RESULTS.json.gz'),
            'measurement':result['measurement'],'execution_graph_changed':True,'new_weight_parameters_changed':0,
            'scientific_scope':'Analytic structural bypass ablation, not pure WSP; no FullHX/Trader or training-superiority claim',
            'P_accepted_fits':sum(f.get('gates',{}).get('P',{}).get('accepted',False) for f in result['fits']),
            'CP_accepted_fits':sum(f.get('gates',{}).get('CP',{}).get('accepted',False) for f in result['fits']),
            'error':result.get('error')}
        save(out/'QUALIFICATION.json',q)
        print(json.dumps({'stage':'finished','status':result['status'],'measurement':result['measurement'],
            'P_accepted':q['P_accepted_fits'],'CP_accepted':q['CP_accepted_fits'],'results_sha256':q['results_sha256'],'error':result.get('error')}),flush=True)
    return 0 if result['status']=='completed' else 2

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);ap.add_argument('--inputs',required=True)
    ap.add_argument('--old-results',required=True);ap.add_argument('--old-heads',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();resource.setrlimit(resource.RLIMIT_CPU,(115,120))
    signal.signal(signal.SIGXCPU,lambda *_:(_ for _ in ()).throw(BudgetExceeded('115 CPU-second signal;120 hard cap')))
    with np.errstate(over='raise',invalid='raise',divide='raise'):sys.exit(main(args))
