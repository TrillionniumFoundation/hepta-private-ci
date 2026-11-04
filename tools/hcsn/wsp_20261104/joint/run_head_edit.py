"""Frozen continuation-head repair on published Hepta Neuron checkpoints.

Offline declared-law experiment. It never reads FullHX packets, touches live
training, or claims real packet / trading returns. Original source definitions
are AST-loaded with the network/content owner omitted. SciPy-generated truth
transition matrices are pinned as a separate, hashed numeric asset.
"""
import ast, copy, hashlib, json, math, os, platform, sys, time
from functools import lru_cache
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent
SOURCE_COMMIT='5b69a046d886cf4c2a73c50e58197360ea15d8f5'
BASE_TRAINING_COMMIT='36e9ddd099e09688593bccf2c32d1dfabc39ac99'
FITS=[11,23,37,53,71]
LAMBDAS=[1e-5,1e-4,1e-3,1e-2,.1,1.]
GD_STEPS=[1,5,20,100,500,2000]
RADIUS_FRACTION=.5
ACCEPT_IMPROVEMENT=.005
TEST_WORLDS=32
SEED=870040000
RENEWAL_SHA={11:'84c4386d0c8725959da10862cdfaad73b654b80e908f3de8d2383530767a38ac',23:'db58500626d4fc89161e4e4ce0ea89b75a70b92794c178cd679c56e60c7ac9ee',37:'cc4f66a63b0af1c90fb31764ee4a724b7837eab081abac94a50ccac7b882dd71',53:'608e4f54ebf89d85f9778a26034144c6c7cc3f5f8e0b988cbcd9a5ac57dcb937',71:'4d3c1124e4309b8124f98e2586f91fcc3022be5c733f29b04f2338fb6aa02d2c'}

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,obj): Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')
def selected_defs(file,names,ns):
    tree=ast.parse((ROOT/file).read_text(),filename=file)
    body=[node for node in tree.body if getattr(node,'name',None) in names or isinstance(node,(ast.Assign,ast.AnnAssign))]
    exec(compile(ast.Module(body=body,type_ignores=[]),file,'exec'),ns)
    return ns

legacy=selected_defs('legacy_task.py',{'public_features','fixed_action'},{'np':np})
ns=selected_defs('joint_task.py',{'validate_public','initial','legal','due_request','successor','public_features','history_features','Oracle','evaluate_terminal'}, {'np':np,'Path':Path,'copy':copy,'lru_cache':lru_cache,'legacy_public_features':legacy['public_features']})
deploy=selected_defs('joint_deploy.py',{'prior_mass','NumpyPolicy'},{'np':np,'public_features':ns['public_features']})
lawns=selected_defs('joint_law.py',{'IndependentLaw'},{'np':np,'lru_cache':lru_cache,'expit':lambda x:1/(1+np.exp(-x))})
NumpyPolicy=deploy['NumpyPolicy']; Oracle=ns['Oracle']; initial=ns['initial']; legal=ns['legal']; due_request=ns['due_request']; successor=ns['successor']
protocol=json.loads((ROOT/'joint_protocol.json').read_text())
truth_tables=np.load(ROOT/'truth_transitions.npz')
class TableLaw(lawns['IndependentLaw']):
    def transition(self,dt,drive): return truth_tables[f'dt{float(dt)}_drive{int(drive)}']
law=TableLaw(protocol['truth_raw'],protocol['n_grid'])

class FrozenFeatures:
    def __init__(self,policy): self.policy=policy; self.memo={}; self.calls=0; self.seconds=0.
    def key(self,p,s): return json.dumps([p,s],sort_keys=True,separators=(',',':'))
    def __call__(self,p,s):
        key=self.key(p,s)
        if key not in self.memo:
            start=time.process_time();mass,bank,pub=self.policy.represent(p,s);n=self.policy.network
            x=np.r_[np.tanh(n['w1']@np.r_[pub,mass,bank]+n['b1']),1.]
            self.memo[key]=x;self.calls+=1;self.seconds+=time.process_time()-start
        return self.memo[key]

def head(artifact):
    return np.c_[np.asarray(artifact['network']['w2']),np.asarray(artifact['network']['b2'])]
def predicted(theta,x):
    out=theta@x;p=float(NumpyPolicy.sigmoid(out[3]));return np.r_[0.,out[:3],1-2*p,2*p-1],p

def outcomes(public,state,action,oracle):
    due=due_request(public,state,action)
    if due is None:return [(1.,None)]
    probabilities=oracle.belief(state)@oracle.transitions[state['tick']]@oracle.emissions[due-1]
    f=public['failure_probability']
    return [(f,dict(failure=True,observation_tick=due))]+[((1-f)*float(probabilities[y]),dict(observation=y,observation_tick=due)) for y in (0,1)]

def policy_value(public,theta,features,oracle):
    visited=0
    def recurse(state):
        nonlocal visited
        visited+=1
        qs,_=predicted(theta,features(public,state));mask=np.asarray(legal(public,state));action=int(np.where(mask,qs,-np.inf).argmax())
        if action==0:return 0.
        if action in (4,5):
            p=oracle.posterior(state);return (1-2*p) if action==4 else (2*p-1)
        total=0.
        for probability,completion in outcomes(public,state,action,oracle):
            if probability:
                after=successor(public,state,action,completion)
                total+=probability*(recurse(after)-(after['charges']-state['charges']))
        return total
    return recurse(initial(public)),visited

def make_worlds(fit,split):
    domain=protocol['ood_domain' if split=='ood' else 'train_domain'];rng=np.random.default_rng(SEED+fit*10000+(1000000 if split=='ood' else 0))
    worlds=[]
    for i in range(TEST_WORLDS):
        p=dict(schema=ns['SCHEMA'],id=f'wsp_v1_{split}_{fit}_{i}',deadline=6,initial_budget=3,target_tick=6,
          duration=rng.choice(domain['durations'],6).tolist(),drive=rng.choice(domain['drives'],6).tolist(),
          reliability=rng.choice(domain['reliabilities'],6).tolist(),read_price=rng.choice(domain['prices'],6).tolist(),read_delay=rng.choice(domain['delays'],6).tolist(),
          prior_distance=float(rng.choice(protocol['prior_distances'])),latency_price=domain['latency_price'],repair_price=domain['repair_price'],failure_probability=domain['failure_probability'],
          packets=[f'not_read_{j}.json' for j in range(6)],packet_sha256=['0'*64]*6)
        ns['validate_public'](p);worlds.append(p)
    return worlds

def public_unique(rows):
    d={}
    for r in rows:
        if r['world'] in d:assert r['public']==d[r['world']]
        d[r['world']]=r['public']
    return list(d.values())

def row_arrays(rows,features):
    return np.array([features(r['public'],r['state']) for r in rows]),np.array([r['q'] for r in rows]),np.array([r['legal'] for r in rows],dtype=float),np.array([r['posterior'] for r in rows])

def metrics(theta,arr):
    x,y,m,p=arr;out=x@theta.T;belief=NumpyPolicy.sigmoid(out[:,3]);q=np.c_[np.zeros(len(x)),out[:,:3],1-2*belief,2*belief-1]
    action=np.where(m,q,-np.inf).argmax(1);targetbest=np.where(m,y,-np.inf).max(1)
    return dict(q_mse=float(np.mean(((q-y)**2*m).sum(1)/m.sum(1))),continuation_q_mse=float(np.sum((q[:,1:4]-y[:,1:4])**2*m[:,1:4])/np.sum(m[:,1:4])),belief_brier=float(np.mean((belief-p)**2)),teacher_behavior_regret=float(np.mean(targetbest-y[np.arange(len(y)),action])),rows=len(x))

def systems(theta,arr,lam):
    x,y,m,_=arr;result=[]
    for j in range(3):
        w=m[:,j+1]/m.sum(1)/len(x)
        a=x.T@(w[:,None]*x)+lam*np.eye(x.shape[1]);g=x.T@(w*(y[:,j+1]-x@theta[j]))
        result.append((a,g))
    return result

def direct(theta,arr,lam,radius):
    delta=np.array([np.linalg.solve(a,g) for a,g in systems(theta,arr,lam)])
    delta*=min(1.,radius/(np.linalg.norm(delta)+1e-300));new=theta.copy();new[:3]+=delta
    return new

def gradient(theta,arr,lam,radius,steps):
    new=theta.copy();operations=0
    for j,(a,g) in enumerate(systems(theta,arr,lam)):
        eta=1./float(np.linalg.eigvalsh(a)[-1]);delta=np.zeros(theta.shape[1])
        for _ in range(steps):delta+=eta*(g-a@delta);operations+=1
        new[j]+=delta
    delta=new[:3]-theta[:3];new[:3]=theta[:3]+delta*min(1.,radius/(np.linalg.norm(delta)+1e-300))
    return new,operations

def eval_worlds(worlds,theta,features,oracles):
    results=[policy_value(p,theta,features,oracles[p['id']]) for p in worlds]
    return float(np.mean([r[0] for r in results])),[float(r[0]) for r in results],sum(r[1] for r in results)

def choose(candidates,base,features,worlds,oracles,validation_arr):
    output=[]
    for name,theta,meta in candidates:
        assert np.isfinite(theta).all() and np.array_equal(theta[3],base[3])
        utility,values,nodes=eval_worlds(worlds,theta,features,oracles)
        entry=dict(name=name,validation_utility=utility,validation_values=values,visited_nodes=nodes,delta_norm=float(np.linalg.norm(theta-base)),**metrics(theta,validation_arr),**meta)
        output.append((entry,theta))
    best=max(output,key=lambda r:(r[0]['validation_utility'],-r[0]['q_mse'],-r[0]['delta_norm']))
    return best,output

def behavior_rows(worlds,confusion,fit,split):
    rng=np.random.default_rng(SEED+fit*10000+5000000+(100000 if split=='ood' else 0));rows=[]
    for p in worlds:
        oracle=Oracle(p,law,confusion);s=initial(p)
        while not s['terminal']:
            m=np.asarray(legal(p,s));q=oracle.q(s)
            rows.append(dict(world=p['id'],public=p,state=copy.deepcopy(s),legal=m.tolist(),q=np.where(m,q,0).tolist(),posterior=oracle.posterior(s)))
            weights=np.asarray(protocol['behavior_action_weights'])*m;action=int(rng.choice(6,p=weights/weights.sum()))
            if action in (0,4,5):s=successor(p,s,action);continue
            options=outcomes(p,s,action,oracle);ps=np.array([v[0] for v in options]);ps/=ps.sum();_,completion=options[int(rng.choice(len(options),p=ps))]
            s=successor(p,s,action,completion)
    return rows

def main(data_root,out_root):
    out_root.mkdir(parents=True,exist_ok=False)
    declaration=dict(schema='hepta-frozen-continuation-head-edit-v1',source_commit=SOURCE_COMMIT,base_training_commit=BASE_TRAINING_COMMIT,fit_ids=FITS,only_family='renewal',seed=SEED,test_worlds_per_fit_split=TEST_WORLDS,lambdas=LAMBDAS,gradient_steps=GD_STEPS,radius_fraction=RADIUS_FRACTION,accept_validation_improvement=ACCEPT_IMPROVEMENT,selection='highest exact declared-law validation utility, then lower masked Q error, then smaller norm; test is unused',primary='paired expected utility across 5 independent original fits on freshly generated public IID/OOD schedules',scope='known finite environment law + original TRAIN-fitted decoder confusion; no actual FullHX packet decoding, no new full-model training, no trading evidence',truth_tables_sha256=digest(ROOT/'truth_transitions.npz'),source_sha256={p.name:digest(p) for p in ROOT.glob('*.py')})
    save(out_root/'protocol_before_results.json',declaration)
    global_start=time.process_time();records=[];begin=time.perf_counter()
    for fit in FITS:
        fit_start=time.process_time();froot=data_root/f'fit_{fit}';model_path=froot/'model_renewal/model.json';data_path=froot/'data'/f'fit_{fit}_data.json'
        assert digest(model_path)==RENEWAL_SHA[fit],('original_model_hash',fit)
        artifact=json.loads(model_path.read_text());data=json.loads(data_path.read_text());base=head(artifact);policy=NumpyPolicy(artifact);features=FrozenFeatures(policy);confusion=artifact['confusion']
        trainrows=data['train']['rows'];valrows=data['validation']['rows'];train_ids=set(r['world'] for r in trainrows);val_ids=set(r['world'] for r in valrows);assert not train_ids&val_ids
        train=row_arrays(trainrows,features);validation=row_arrays(valrows,features);worlds=public_unique(valrows);oracles={p['id']:Oracle(p,law,confusion) for p in worlds}
        radius=RADIUS_FRACTION*float(np.linalg.norm(base[:3]));baseval,_,_=eval_worlds(worlds,base,features,oracles)
        candidate_start=time.process_time();ridge=[]
        for lam in LAMBDAS:
            start=time.process_time();theta=direct(base,train,lam,radius);ridge.append((f'ridge_{lam:g}',theta,dict(lam=lam,edit_cpu_seconds=time.process_time()-start)))
        ridge_solve_cpu=time.process_time()-candidate_start
        (selected_info,selected),ridge_results=choose(ridge,base,features,worlds,oracles,validation)
        chosen_lam=selected_info['lam'];candidate_start=time.process_time();gd=[];gradient_updates=0
        for steps in GD_STEPS:
            start=time.process_time();theta,n=gradient(base,train,chosen_lam,radius,steps);gradient_updates+=n;gd.append((f'gd_{steps}',theta,dict(lam=chosen_lam,steps=steps,edit_cpu_seconds=time.process_time()-start)))
        gd_cpu=time.process_time()-candidate_start
        (gd_info,gd_selected),gd_results=choose(gd,base,features,worlds,oracles,validation)
        rng=np.random.default_rng(SEED+fit*1000+777);randoms=[];matchnorm=float(np.linalg.norm(selected-base))
        for i in range(len(LAMBDAS)):
            d=rng.normal(size=(3,49));d*=matchnorm/np.linalg.norm(d);t=base.copy();t[:3]+=d;randoms.append((f'random_{i}',t,dict(seed=SEED+fit*1000+777)))
        (random_info,random_selected),random_results=choose(randoms,base,features,worlds,oracles,validation)
        accepted=selected_info['validation_utility']-baseval>=ACCEPT_IMPROVEMENT
        arms={'no_edit':base,'direct_raw':selected,'direct_gated':selected if accepted else base,'gradient_selected':gd_selected,'random_selected':random_selected}
        for j,name in enumerate(['wait_only','read_only','repair_only']):
            t=base.copy();t[j]=selected[j];arms[name]=t
        result=dict(fit=fit,source_model_sha256=digest(model_path),source_data_sha256=digest(data_path),training_worlds=len(train_ids),validation_worlds=len(val_ids),training_rows=len(trainrows),validation_rows=len(valrows),baseline_validation_utility=baseval,selected_direct=selected_info,selected_gradient=gd_info,selected_random=random_info,accepted=accepted,rollback_verified=bool(accepted or np.array_equal(arms['direct_gated'],base)),radius=radius,baseline_train_metrics=metrics(base,train),direct_train_metrics=metrics(selected,train),candidates={'direct':[r[0] for r in ridge_results],'gradient':[r[0] for r in gd_results],'random':[r[0] for r in random_results]},timing=dict(direct_all_solve_cpu_seconds=ridge_solve_cpu,gradient_all_solve_cpu_seconds=gd_cpu,gradient_coordinate_updates=gradient_updates),tests={})
        # Fit-specific independent test worlds are only generated after selection.
        for split in ('iid','ood'):
            testworlds=make_worlds(fit,split);assert not {p['id'] for p in testworlds}&(train_ids|val_ids)
            test_oracles={p['id']:Oracle(p,law,confusion) for p in testworlds};testrows=behavior_rows(testworlds,confusion,fit,split);testarr=row_arrays(testrows,features)
            oracle_values=[float(test_oracles[p['id']].q(initial(p)).max()) for p in testworlds];armresult={}
            for name,theta in arms.items():
                start=time.process_time();u,values,nodes=eval_worlds(testworlds,theta,features,test_oracles)
                armresult[name]=dict(expected_utility=u,world_utilities=values,visited_nodes=nodes,eval_cpu_seconds=time.process_time()-start,delta_norm=float(np.linalg.norm(theta-base)),**metrics(theta,testarr))
                assert armresult[name]['belief_brier']==armresult['no_edit']['belief_brier'],('belief_changed',fit,split,name)
            result['tests'][split]=dict(world_count=len(testworlds),public_worlds_sha256=hashlib.sha256(json.dumps(testworlds,sort_keys=True).encode()).hexdigest(),oracle_utility=float(np.mean(oracle_values)),oracle_world_utilities=oracle_values,arms=armresult)
            save(out_root/f'fit_{fit}_{split}_worlds.json',testworlds)
        result['timing'].update(total_cpu_seconds=time.process_time()-fit_start,feature_cpu_seconds=features.seconds,feature_cache_size=features.calls)
        edited=copy.deepcopy(artifact);edited['network']['w2']=selected[:,:48].tolist();edited['network']['b2']=selected[:,48].tolist();save(out_root/f'fit_{fit}_candidate_model.json',edited)
        restored=copy.deepcopy(edited);restored['network']['w2']=artifact['network']['w2'];restored['network']['b2']=artifact['network']['b2'];assert restored==artifact
        result['candidate_model_sha256']=digest(out_root/f'fit_{fit}_candidate_model.json');result['exact_semantic_restore_verified']=True
        # Small standalone real-model numerical fixture for Rust cross-validation.
        if fit==11:
            x,y,m,_=train;fx=x[:64];fy=y[:64,1:4];fw=m[:64,1:4]/m[:64].sum(1)[:,None]/64
            flambda=.01;expected=np.array([base[j]+np.linalg.solve(fx.T@(fw[:,j,None]*fx)+flambda*np.eye(49),fx.T@(fw[:,j]*(fy[:,j]-fx@base[j]))) for j in range(3)])
            save(out_root/'rust_fixture.json',dict(schema='hepta-real-head-proximal-ridge-fixture-v1',source_commit=SOURCE_COMMIT,source_model_sha256=digest(model_path),fit=fit,feature_dim=49,heads=['WAIT','READ','REPAIR'],features=fx.tolist(),targets=fy.tolist(),sample_weights=fw.tolist(),base_weights=base[:3].tolist(),lambda_=flambda,expected_weights=expected.tolist(),unclipped=True,objective='sum_i sample_weights_ij*(x_i dot theta_j-y_ij)^2+lambda*||theta_j-base_j||^2',frozen_belief_weights=base[3].tolist()))
        save(out_root/f'fit_{fit}_results.json',result);records.append(result)
        print(json.dumps(dict(fit=fit,accepted=accepted,lambda_=chosen_lam,validation_delta=selected_info['validation_utility']-baseval,iid_delta=result['tests']['iid']['arms']['direct_gated']['expected_utility']-result['tests']['iid']['arms']['no_edit']['expected_utility'],ood_delta=result['tests']['ood']['arms']['direct_gated']['expected_utility']-result['tests']['ood']['arms']['no_edit']['expected_utility'],cpu=result['timing']['total_cpu_seconds'])),flush=True)
    summary={'protocol':declaration,'fits':records,'total_cpu_seconds':time.process_time()-global_start,'wall_seconds':time.perf_counter()-begin,'python':sys.version,'numpy':np.__version__,'platform':platform.platform(),'summary':{}}
    for split in ('iid','ood'):
        s={}
        for arm in records[0]['tests'][split]['arms']:
            values=np.array([r['tests'][split]['arms'][arm]['expected_utility'] for r in records]);basevalues=np.array([r['tests'][split]['arms']['no_edit']['expected_utility'] for r in records]);diff=values-basevalues;half=2.7764451051977987*float(diff.std(ddof=1))/np.sqrt(5)
            s[arm]=dict(mean_utility=float(values.mean()),per_fit_utility=values.tolist(),mean_delta=float(diff.mean()),per_fit_delta=diff.tolist(),paired_95_ci=[float(diff.mean()-half),float(diff.mean()+half)],independent_units=5,ci_scope='descriptive unadjusted paired Student-t over original training fits; secondary gates not passed by these CIs')
        summary['summary'][split]=s
    save(out_root/'results.json',summary)
    print(json.dumps({'done':str(out_root),'cpu_seconds':summary['total_cpu_seconds'],'wall_seconds':summary['wall_seconds']}),flush=True)
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
