"""Read-only reconstruction of completed runtime evidence; never executes a model or native process."""
import ast
from collections import Counter
from decimal import Decimal, ROUND_CEILING, localcontext
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import expit, log_ndtr

ROOT=Path('/tmp/aen-round2-20261027')
REPO=Path('/workspace/scratch/d831a963ef2f/hepta-analytic')
SOURCE=REPO/'experiments/analytic_event_neuron/round2'
OUT=ROOT/'reviews/RUNTIME_INDEPENDENT_REVIEW.json'
Q=1<<24
ZERO='0'*64
CHECKS=Counter()
ERRORS={}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def check(cond,category,label):
    CHECKS[category]+=1
    if not bool(cond):
        raise AssertionError(category+': '+label)


def close(a,b,category,label,tol=1e-10):
    a,b=np.asarray(a,float),np.asarray(b,float)
    check(a.shape==b.shape and np.isfinite(a).all() and np.isfinite(b).all(),category,label+' domain')
    error=float(np.max(np.abs(a-b))) if a.size else 0.
    ERRORS[category]=max(ERRORS.get(category,0.),error)
    check(error<=tol,category,label)


def envelope(p):
    obj=read(p)
    check(set(obj)=={'document','sha256'} and digest(obj['document'])==obj['sha256'],'durable_envelope',str(p.relative_to(ROOT)))
    return obj['document']


def verify_freezes():
    main,harness=read(ROOT/'FREEZE.json'),read(ROOT/'RUNTIME_HARNESS_FREEZE.json')
    for relative,expected in main['sources_sha256'].items():
        check(sha(REPO/relative)==expected,'main_freeze','source '+relative)
    for relative,expected in main['artifacts_sha256'].items():
        check(sha(ROOT/relative)==expected,'main_freeze','artifact '+relative)
    check(harness['main_freeze_sha256']==sha(ROOT/'FREEZE.json') and harness['main_source_commit']==main['source_commit'],'harness_freeze','main binding')
    for relative,expected in harness['sources_sha256'].items():
        check(sha(REPO/relative)==expected,'harness_freeze','source '+relative)
    for relative,expected in harness['parity_evidence_sha256'].items():
        check(sha(ROOT/relative)==expected,'harness_freeze','prior parity evidence '+relative)
    return main,harness


def scalar_filter(parameters,history,horizon):
    drift,q,scale=parameters
    mean,var,last,likelihood=0.,1.,0.,0.
    for y,t,seen,noise in zip(history['observations'],history['times'],history['mask'],history['obs_var']):
        dt=t-last;check(dt>=0,'public_filter','nonregressing observation clock')
        mean+=drift*dt;var+=q*dt
        if seen:
            innovation=y-mean;total=var+scale*noise
            likelihood-=.5*(math.log(2*math.pi*total)+innovation*innovation/total)
            gain=var/total;mean+=gain*innovation;var*=1-gain
        last=t
    return mean+drift*horizon,var+q*horizon,likelihood


def independent_forecast(model,history,horizon):
    if model['kind']=='filter':
        m,v,_=scalar_filter(model['parameters'],history,horizon)
        return m,v,None
    check(model['kind']=='protected_filter' and model.get('output_quantization') is None,'model_contract','registered protected FP64 model')
    m0,v0,l0=scalar_filter(model['anchor']['parameters'],history,horizon)
    m1,v1,l1=scalar_filter(model['adaptive']['parameters'],history,horizon)
    weight=model['prior'] if model['routing']=='fixed' else float(expit(math.log(model['prior'])-math.log1p(-model['prior'])+l1-l0))
    proposal=m0+weight*(m1-m0)
    d=float(np.clip((proposal-m0)/math.sqrt(v0),-model['epsilon'],model['epsilon']))
    return m0+math.sqrt(v0)*d,v0*(1+abs(d)),(m0,v0)


def density_bound(m,v,m0,v0):
    excess=(v-v0)/v0;d=(m-m0)/math.sqrt(v0)
    if excess<0 or (excess==0 and d!=0):
        return None,None
    if excess==0:
        return 0.,m0
    bound=.5*math.log1p(excess)+d*d/(2*excess)
    z=-d/excess
    witness=m0+math.sqrt(v0)*z
    direct=.5*math.log(v/v0)+.5*((witness-m)**2/v-(witness-m0)**2/v0)
    close(bound,direct,'density_vertex','quadratic supremum attained',1e-9)
    return bound,witness


def logdiff(large,small):
    return large+math.log(-math.expm1(small-large))


def event_logs(m,v,lo=-.6,hi=.6):
    a,b=(lo-m)/math.sqrt(v),(hi-m)/math.sqrt(v)
    put,call=float(log_ndtr(a)),float(log_ndtr(-b))
    middle=logdiff(float(log_ndtr(-a)),float(log_ndtr(-b))) if a>=0 else logdiff(float(log_ndtr(b)),float(log_ndtr(a)))
    return np.array([put,middle,call])


def native_check(n,binary_sha):
    check(n['native_binary_sha256']==binary_sha and n['original_neuron_runtime'] and n['original_sparse_journal'] and n['typed_model_port'] and n['independent_anchor_witness'],'native_identity','typed original owner and binary binding')
    check(n['abstain'] and n['legacy_runtime_confidence_ppm']==0 and n['authority']=='DENY_ALL' and not n['native_owner_integration'],'authority','unqualified experimental owner')
    inp=np.array(n['input_parameters_fp64']);actual=np.array(n['head']['parameters_q24_decoded'])
    close(actual,np.rint(inp*Q)/Q,'native_q24_parameters','actual parameter lattice',0.)
    p=np.exp(event_logs(*actual));close(p,n['head']['probabilities'],'native_cdf','independent scipy log-CDF',3e-15)
    raw=np.array(n['head']['probabilities'])*Q;counts=np.floor(raw).astype(int)
    remaining=Q-int(counts.sum());order=sorted(range(3),key=lambda i:(-(raw[i]-counts[i]),i))
    for i in order[:remaining]:counts[i]+=1
    check(counts.tolist()==n['head']['probabilities_q24'] and counts.sum()==Q and np.all(counts>=0),'native_raw_mass','independent largest remainder integer rounding')
    return actual,p


def record_check(r,model,model_sha,key,data_sha,binary_sha):
    h=r['public_history'];check(set(h)=={'id','observations','times','mask','obs_var'},'public_information','exact deployed information contract')
    check(all(y==0. for y,seen in zip(h['observations'],h['mask']) if not seen),'public_information','missing storage absent')
    check(r['model_file_sha256']==model_sha and r['model_entry_sha256']==digest(model) and r['model_key']==key and r['dataset_sha256']==data_sha and r['history_sha256']==digest(h),'binding','model and public history hashes')
    close([r['conditioning_time'],r['target_time']],[h['times'][-1],h['times'][-1]+r['horizon']],'public_information','time semantics',0.)
    check(r['authority']=='DENY_ALL' and not r['production_agentd_owner'] and not r['cross_owner_atomicity'] and r['decoder_reopened_from_disk_before_native'] and not r['encoder_residual_used_by_native'],'authority','separate research receiver')
    m,v,anchor=independent_forecast(model,h,r['horizon']);close([m,v],[r['source_forecast']['mean'],r['source_forecast']['variance']],'public_forecast','same public likelihood forecast')
    decoder=r['decoder'];config=decoder['config'];levels=decoder['levels']
    decoded=[levels[0]*config['mean_step'],math.exp(levels[1]*config['logvar_step'])]
    close(decoded,[r['decoded_mean'],r['decoded_variance']],'decoder','counts alone readout',0.)
    check(r['packet']['config_sha256']==digest(config) and r['packet']['sequence']==r['sequence']==decoder['sequence'],'decoder','packet config and sequence')
    actual,p=native_check(r['native'],binary_sha)
    close(r['native']['input_parameters_fp64'],[r['head_mean'],r['head_variance'],-.6,.6],'native_inputs','intended input after JSON parser roundtrip',2e-15)
    check(r['native']['case']=='round2.'+r['subject'] and r['native']['sequence']==r['sequence'],'native_binding','subject and sequence')
    check(r['logical_unit_events']==sum(abs(x) for x in r['packet']['counts']) and r['packet_bytes']==len(json.dumps(r['packet'],sort_keys=True,separators=(',',':')).encode()),'logical_cost','packet unit events and bytes')
    q=r['delivered_probabilities_q24'];check(len(q)==3 and all(type(x)is int and 0<=x<=Q for x in q) and sum(q)==Q,'delivered_mass','nonnegative exact integer mass')
    close(r['delivered_probabilities'],np.array(q)/Q,'delivered_mass','actual delivered probability values',0.)
    bounds=None;worst=None;eventmax=None
    if anchor:
        a,b=anchor;close([a,b],[r['protected_density_bounds']['anchor_mean'],r['protected_density_bounds']['anchor_variance']],'anchor','independent public-anchor filter')
        all_bounds=[]
        for name,pair in [('before_encoding',[m,v]),('after_event_encoding',decoded),('after_native_q24_input',actual[:2])]:
            val,witness=density_bound(*pair,a,b);saved=r['protected_density_bounds'][name]
            check(saved['finite']==(val is not None),'density_envelope','finite branch')
            if val is not None:close(val,saved['upper_bound'],'density_envelope',name,1e-9)
            all_bounds.append(val)
            if name=='after_native_q24_input':worst=witness
        bounds=all_bounds
        check(all_bounds[0] is not None and all_bounds[0]<=.02+1e-10,'fp64_protection','source model remains protected')
    guarded=r['runtime_mode']=='anchor_guarded'
    check(guarded==r['explicit_frozen_anchor_reference'],'guard_scope','explicit extra same-public anchor')
    if guarded:
        check(bounds[-1] is not None and bounds[-1]<=model['epsilon'],'guarded_gaussian','actual native density envelope')
        gc=r['guard_certificate'];close(actual[:2],[gc['mean'],gc['variance']],'guarded_gaussian','guard output exactly native input',0.)
        check([gc['mean_q24'],gc['variance_q24']]==[int(actual[0]*Q),int(actual[1]*Q)],'guarded_gaussian','actual lattice integers')
        close(bounds[-1],gc['pointwise_nll_bound'],'guarded_gaussian','actual certificate')
        expected_mean=round((a+float(np.clip(decoded[0]-a,-.5*model['epsilon']*math.sqrt(b),.5*model['epsilon']*math.sqrt(b))))*Q)/Q
        d=(expected_mean-a)/math.sqrt(b);expected_var=max(math.ceil(b*(1+abs(d))*Q),math.ceil(b*Q))/Q
        close(actual[:2],[expected_mean,expected_var],'guarded_gaussian','independent reserved shift/ceil variance',0.)
        logs=event_logs(a,b);close(logs,r['anchor_log_probabilities'],'anchor_events','independent stable anchor log CDF',2e-10)
        check(digest(r['anchor_log_probabilities'])==r['anchor_log_probabilities_sha256'],'anchor_events','anchor log hash')
        check(min(q)>0,'guarded_events','all finite Gaussian anchor events supported')
        excess=logs-np.log(np.array(q)/Q);eventmax=float(excess.max())
        check(eventmax<=model['epsilon'],'guarded_events','delivered event pointwise logloss bound')
        ec=r['categorical_guard_certificate'];close(excess,ec['pointwise_event_nll_bound'],'guarded_events','certificate cross check',2e-10)
        close(eventmax,ec['maximum_event_nll_excess'],'guarded_events','certificate maximum',2e-10)
        minima=[]
        with localcontext() as ctx:
            ctx.prec=100
            for lp in r['anchor_log_probabilities']:
                threshold=Decimal(Q)*(Decimal.from_float(lp)-Decimal.from_float(model['epsilon'])).exp()
                minima.append(max(1,int(threshold.to_integral_value(rounding=ROUND_CEILING))))
        check(minima==ec['minimum_counts'] and all(x>=lower for x,lower in zip(q,minima)),'guarded_events','independent high precision minimum counts')
        raw=r['native']['head']['probabilities_q24']
        for i in range(3):
            for j in range(3):
                if i!=j and q[i]>minima[i]:
                    check(2*((q[j]-raw[j])-(q[i]-raw[i])+1)>=0,'guarded_events','integer convex projection exchange optimality')
        check(r['delivered_probability_source']=='post_native_research_adapter' and not r['original_rust_witness_binds_post_projection'] and ec['original_native_owner_output_unchanged'],'guard_scope','raw native versus own delivery witness separated')
    else:
        check(q==r['native']['head']['probabilities_q24'] and r['categorical_guard_certificate'] is None and r['delivered_probability_source']=='native_head','guard_scope','unguarded output honestly native')
    requestkeys=['schema','subject','model_file_sha256','model_entry_sha256','model_key','dataset_sha256','generation','tick_id','sequence','history_sha256','conditioning_time','target_time','horizon','observation_kind','runtime_mode']
    request={k:r[k] for k in requestkeys};check(digest(request)==r['request_sha256'],'checkpoint','public request digest')
    after=digest({'subject':r['subject'],'predecessor':r['checkpoint_before'],'request':r['request_sha256'],'decoder':r['decoder'],'native_checkpoint':r['native']['checkpoint_after'],'delivered_probabilities_q24':q,'anchor_log_probabilities':r['anchor_log_probabilities']})
    check(after==r['checkpoint_after'],'checkpoint','own checkpoint binds corrected output and native checkpoint')
    check(any(digest([model_sha,key,digest(model),h['id'],r['horizon'],data_sha,r['generation'],config,r['runtime_mode'],limit])==r['subject'] for limit in (1,1024)),'checkpoint','versioned subject')
    return {'bounds':bounds,'worst_x':worst,'event_bound':eventmax}


def main():
    began=time.perf_counter_ns();frozen,harness=verify_freezes()
    runtime_root=ROOT/'runtime_confirmation'
    before={p.relative_to(ROOT).as_posix():sha(p) for p in runtime_root.rglob('*') if p.is_file()}
    published=read(ROOT/'RUNTIME_RESULTS.json');accounting=read(ROOT/'RUNTIME_ACCOUNTING.json')
    binarysha=sha(ROOT/'native/analytic_event');check(binarysha==read(ROOT/'native/BUILD_RECEIPT.json')['binary_sha256'],'native_identity','executable receipt')
    diff=read(ROOT/'runtime_harness_validation/AST_DIFF.json')
    old=(SOURCE/'runtime_bridge.py').read_text();new=(SOURCE/'runtime_confirmation.py').read_text()
    oldfn=next(n for n in ast.parse(old).body if isinstance(n,ast.FunctionDef) and n.name=='qualify')
    newfn=next(n for n in ast.parse(new).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_confirmation')
    reversed_source=ast.get_source_segment(new,newfn)
    for change in diff['reversible_qualification_only_source_replacements']:
        check(reversed_source.count(change['after'])==1,'harness_scope','single declared source replacement')
        reversed_source=reversed_source.replace(change['after'],change['before'])
    check(ast.dump(ast.parse(reversed_source).body[0],include_attributes=False)==ast.dump(oldfn,include_attributes=False),'harness_scope','AST identical after admission/provenance reversal')
    profile_reports=[];forecast_reports=[];unique_histories=set();generated=0;allchecks=0;allnative={};all_composite=0;all_pending=Counter();all_files_bytes=0
    for result in published['profiles']:
        seed,profile=result['seed'],result['profile'];base=runtime_root/f'seed_{seed}';directory=base/profile
        summary=read(directory/'RUNTIME_QUALIFICATION.json');forecast=read(directory/'FORECAST_RECEIPTS.json');recovery=read(directory/'RECOVERY_RECEIPTS.json');stress=read(directory/'STRESS_RECEIPTS.json')
        datareceipt=read(base/'DATA_RECEIPT.json')
        with np.load(base/'DATA.npz',allow_pickle=False) as data:
            check(str(data['split'].item())=='runtime_confirmation' and len(data['ids'])==16,'data_scope','fresh qualification split and generated count')
            check(datareceipt['seed']==1500000+seed and datareceipt['file_sha256']==sha(base/'DATA.npz'),'data_scope','seed and dataset bytes')
            check(datareceipt['created_utc']>harness['created_utc'] and datareceipt['generated_after_both_freezes'] and datareceipt['runtime_harness_freeze_sha256']==sha(ROOT/'RUNTIME_HARNESS_FREEZE.json') and datareceipt['main_freeze_sha256']==sha(ROOT/'FREEZE.json'),'data_scope','recorded post-freeze generation')
            expected_histories={str(data['ids'][i]):{'id':str(data['ids'][i]),'observations':np.where(data['mask'][i],data['obs'][i],0.).tolist(),'times':data['times'][i].tolist(),'mask':data['mask'][i].tolist(),'obs_var':data['obs_var'][i].tolist()} for i in range(4)}
        if profile=='analytic_count_only':generated+=16
        check(sha(directory/'RUNTIME_QUALIFICATION.json')==result['summary_sha256'],'summary_binding','profile summary digest')
        check(summary['passed'] and not summary['parity_only'] and summary['qualification_data_role']=='runtime_confirmation' and summary['source_sha256']==sha(SOURCE/'runtime_confirmation.py') and summary['frozen_engine_source_sha256']==sha(SOURCE/'runtime_bridge.py'),'summary_binding','actual formal harness and frozen engine')
        check(len(forecast)==summary['forecasts']==result['forecast_cases']==12 and len(summary['checks'])==result['checks'] and all(c['passed'] for c in summary['checks']),'qualification_counts','all listed checks and twelve horizon cases')
        allchecks+=len(summary['checks'])
        check(len(recovery)==result['fresh_python_processes']==2 and len(stress)==result['tail_fixtures'],'qualification_counts','recovery and tail fixture counts')
        job=read(directory/'recovery_job_0.json');modelpath=Path(job['models_file']);modelsha=sha(modelpath);key=job['model_key'];model=read(modelpath)
        for part in key.split('.'):model=model[part]
        check(frozen['artifacts_sha256'][modelpath.relative_to(ROOT).as_posix()]==modelsha==summary['model_file_sha256']==job['expected_model_sha256'],'binding','model unchanged and preconfirmed')
        datas=sha(base/'DATA.npz');native_records={};owner_entries={};pending_counts=Counter();composite=0
        for owner in (directory/'owners').iterdir():
            if not owner.is_dir():continue
            sp=owner/'state.json';wp=owner/'delivery.witness.json';pp=owner/'pending.json'
            if sp.exists():
                state=envelope(sp);witness=envelope(wp)
                check(state['subject']==witness['subject']==owner.name and len(witness['records'])==state['sequence']==len(state['entries']),'durable_witness','complete composite ancestry')
                prior=ZERO;nativeprior=ZERO;levels=[0,0];entries={};rebuilt=None
                for r,w in zip(sorted(state['entries'].values(),key=lambda x:x['sequence']),witness['records']):
                    stats=record_check(r,model,modelsha,key,datas,binarysha)
                    owner_entries[(r['subject'],r['sequence'])]=(r,stats);composite+=1
                    check(r['checkpoint_before']==prior and r['native']['checkpoint_before']==nativeprior and w['predecessor']==prior and w['sequence']==r['sequence'],'durable_witness','native and composite ancestry')
                    check(w['checkpoint']==r['checkpoint_after'] and w['native_checkpoint']==r['native']['checkpoint_after'] and w['request_sha256']==r['request_sha256'] and w['delivered_output_sha256']==digest(r['delivered_probabilities_q24']),'durable_witness','own witness binds actual delivered counts')
                    levels=[levels[i]+r['packet']['counts'][i] for i in range(2)]
                    check(levels==r['decoder']['levels'],'decoder','chronological count accumulation')
                    entries[r['tick_id']]=r;target=[r['source_forecast']['mean'],math.log(r['source_forecast']['variance'])]
                    residual=[target[0]-levels[0]*r['decoder']['config']['mean_step'],target[1]-levels[1]*r['decoder']['config']['logvar_step']]
                    encoder={'schema':'hepta.signed-event.neuron.v1','decoder':r['decoder'],'last_target':target,'residual':residual}
                    rebuilt={'schema':r['schema'],'subject':r['subject'],'checkpoint':r['checkpoint_after'],'native_checkpoint':r['native']['checkpoint_after'],'sequence':r['sequence'],'time':r['conditioning_time'],'encoder':encoder,'decoder':r['decoder'],'entries':dict(entries)}
                    check(digest(rebuilt)==w['state_sha256'],'durable_witness','each independently reconstructed intermediate state hash')
                    prior,nativeprior=r['checkpoint_after'],r['native']['checkpoint_after']
                    n=r['native'];native_records[(n['case'],n['sequence'],n['checkpoint_after'])]=n
                check(state==rebuilt,'durable_witness','full final persisted encoder/receiver state')
            if pp.exists():
                pending=envelope(pp);pending_counts[pending['stage']]+=1
                if 'native' in pending:
                    n=pending['native'];native_check(n,binarysha);native_records[(n['case'],n['sequence'],n['checkpoint_after'])]=n
            for name,magic in [('native/state.journal',b'HPTNSJ01'),('native/anchor.witness',b'HPTNWA01')]:
                path=owner/name
                if path.exists():check(path.read_bytes().startswith(magic),'native_files','original binary format present and separately hashed')
        checks=Counter(x['name'] for x in summary['checks'])
        check(pending_counts==Counter({'prepared':2,'native_committed':1}),'partial_commits','retained blocked interventions')
        check(recovery[0]==read(directory/'recovery_0.json') and recovery[1]==read(directory/'recovery_1.json'),'recovery','raw fresh worker receipts match summary')
        check(recovery[0]['receipt']==forecast[0] and recovery[0]['native_requests_this_process']==recovery[0]['native_ticks_this_process']==0,'recovery','duplicate acknowledgement no native call')
        continuation=recovery[1]['receipt'];check(recovery[1]['native_requests_this_process']==recovery[1]['native_ticks_this_process']==1 and continuation['packet']['counts']==[0,0] and continuation['observation_kind']=='propagation' and continuation['native']['checkpoint_before']==forecast[0]['native']['checkpoint_after'],'recovery','fresh continuation zero events retains ancestry')
        local=[]
        for r in forecast:
            check(r['public_history']==expected_histories[r['public_history']['id']] and r['horizon'] in (.5,1.,2.),'data_scope','actual first four registered public histories')
            unique_histories.add(r['public_history']['id'])
            check(owner_entries[(r['subject'],r['sequence'])][0]==r,'coverage','forecast receipt durable exact match')
            stats=owner_entries[(r['subject'],r['sequence'])][1]
            local.append(stats)
            forecast_reports.append({'seed':seed,'profile':profile,'history_id':r['public_history']['id'],'horizon':r['horizon'],**stats})
        check(len({(r['public_history']['id'],r['horizon']) for r in forecast})==12,'data_scope','four times three unique forecasts')
        for r in stress:
            check(owner_entries[(r['subject'],r['sequence'])][0]==r and r['horizon']==0.,'tail_fixture','separate deterministic fixture')
            check(0 in r['native']['head']['probabilities_q24'] and min(r['delivered_probabilities_q24'])>0 and r['delivered_probabilities_q24']!=r['native']['head']['probabilities_q24'],'tail_fixture','raw support loss and corrected support')
        finite=[s['bounds'][-1] for s in local if s['bounds'] is not None and s['bounds'][-1] is not None]
        unbounded=sum(s['bounds'] is not None and s['bounds'][-1] is None for s in local)
        violations=sum(x>.02 for x in finite)+unbounded
        check(violations==result['gaussian_bound_violations'] and unbounded==result['gaussian_unbounded_cases'],'density_summary','actual bound violation count')
        if finite:close(max(finite),result['maximum_finite_gaussian_bound'],'density_summary','maximum actual bound',1e-9)
        eventbounds=[s['event_bound'] for s in local if s['event_bound'] is not None]
        if eventbounds:close(max(eventbounds),result['maximum_delivered_event_nll_excess'],'events_summary','maximum delivered event excess',2e-10)
        matching=next(x for x in accounting['profiles'] if x['seed']==seed and x['profile']==profile)
        measures={'unique_successful_native_ticks':len(native_records),'committed_composite_ticks':composite,'pending_stages':dict(pending_counts),
                  'native_roundtrip_ns':sum(n['subprocess_roundtrip_ns'] for n in native_records.values()),'native_typed_tick_wall_ns':sum(n['typed_tick_wall_ns'] for n in native_records.values()),
                  'native_head_execution_micros':sum(n['head_execution_micros'] for n in native_records.values()),'native_journal_bytes_written':sum(n['journal_bytes_written'] for n in native_records.values()),
                  'maximum_sampled_native_resident_bytes':max(n['process_resident_bytes'] for n in native_records.values()),'qualification_wall_ns':summary['wall_ns'],'qualification_parent_cpu_ns':summary['parent_cpu_ns'],
                  'profile_final_file_bytes':sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())}
        for name,value in measures.items():check(value==matching[name],'cost_accounting',name)
        allnative.update(native_records);all_composite+=composite;all_pending+=pending_counts;all_files_bytes+=measures['profile_final_file_bytes']
        profile_reports.append({'seed':seed,'profile':profile,'forecast_cases':len(forecast),'listed_qualification_checks':len(summary['checks']),'check_name_counts':dict(checks),
                                'gaussian_bound_violations':violations,'gaussian_bound_max':max(finite) if finite else None,'delivered_event_bound_max':max(eventbounds) if eventbounds else None,
                                'tail_fixture_count':len(stress),'raw_forecast_output_changes':sum(r['delivered_probabilities_q24']!=r['native']['head']['probabilities_q24'] for r in forecast),
                                'all_committed_gaussian_bound_max':max((s['bounds'][-1] for r,s in owner_entries.values() if s['bounds'] is not None and s['bounds'][-1] is not None),default=None),
                                'all_committed_event_bound_max':max((s['event_bound'] for r,s in owner_entries.values() if s['event_bound'] is not None),default=None),'accounting':measures})
    check(len(profile_reports)==15 and len(unique_histories)==20 and generated==80 and len(forecast_reports)==180 and allchecks==1100,'total_scope','exact coverage and nonindependent check scope')
    check(len(allnative)==320 and all_composite==305,'total_scope','native success versus committed receiver ticks')
    check(published['checks']==allchecks and published['unique_exercised_histories']==len(unique_histories) and published['generated_histories']==generated and published['forecast_cases']==len(forecast_reports),'published_summary','coverage reconciliation')
    after={p.relative_to(ROOT).as_posix():sha(p) for p in runtime_root.rglob('*') if p.is_file()};check(before==after,'read_only_audit','all runtime evidence unchanged')
    frozen2,harness2=verify_freezes();check(frozen==frozen2 and harness==harness2,'read_only_audit','both freezes unchanged')
    bounds_by_profile={}
    for profile in ['analytic_count_only','protected_count_only','protected_anchor_guarded']:
        records=[x for x in forecast_reports if x['profile']==profile];finite=[x['bounds'][-1] for x in records if x['bounds'] is not None and x['bounds'][-1] is not None]
        bounds_by_profile[profile]={'forecasts':len(records),'finite_gaussian_bound_max':max(finite) if finite else None,'gaussian_bound_violations':sum(x>.02 for x in finite),'delivered_event_bound_max':max((x['event_bound'] for x in records if x['event_bound'] is not None),default=None)}
    limits=[
        '1,100 are heterogeneous qualification assertions, not independent trials. The 180 random forecast cases reuse 20 unique histories, four of sixteen generated per seed, across three profiles and three horizons.',
        'Five additional deterministic tail fixtures deliberately test numerical support loss; they are separate from the 180 random forecasts and do not provide sampled efficacy evidence.',
        'No native process, model fit, data generator or qualification function was reexecuted by this independent audit. Saved native outputs were checked by independent scalar filtering/CDF/integer arithmetic and persisted receipt reconstruction.',
        'All composite delivery witnesses and their intermediate state hashes were independently reconstructed. Raw native journal/witness files were hashed and magic headers inspected; the opaque native digest formats were not independently reimplemented or replayed.',
        'Recovery and negative-intervention conclusions rely on the frozen qualification code and its saved results plus retained states/pending markers. The audit did not inject a second set of faults.',
        'The runtime qualification harness required a separately frozen operational amendment to admit the fresh runtime_confirmation split. Reversing only declared admission/provenance edits yields the identical original qualification AST; original inference, guard and worker sources remain frozen.',
        'Count-only protected forecasts violate the .02 Gaussian envelope in 27/60 cases. This negative outcome is not erased by the separately named anchor_guarded mode.',
        'Guarded runtime recomputes an explicit frozen same-public-information anchor after count decoding. This extra reference and reserved shift differ from transporting the protected FP64 model alone; retention efficacy is not inherited from that study.',
        'Final protected categorical counts are a separate post-native probability projection. The original Rust owner output and witness remain raw; the corrected counts are bound by the adapter own checkpoint and delivery witness, not by the original Rust output digest.',
        'The corrected categorical law need not equal Gaussian CDF values at its delivered Gaussian parameters. Gaussian-density and categorical-event logscore guarantees are distinct.',
        'Witnesses are independent state files within one experimental local owner environment, not an externally anchored tamper-proof service; coordinated rollback of all stores was not qualified.',
        'Partial commits remain pending and require explicit reconciliation. There is no atomic transaction across the Python decoder owner and Rust native owner.',
        'Default 1,024-tick lifetime is bounded; this evidence does not establish multi-year semantic retention, production Agentd dispatch, authorization, network efficiency or isolated hardware speed.',
        'Only confidence zero, abstention and DENY_ALL are qualified. No calibrated production success probability or production promotion follows.',
        'Cost measurements are nested shared-host observations. Child CPU, failed native request isolated latency and total adapter write amplification were not recorded; null entries must remain missing.',
    ]
    return {'schema':'hepta.runtime-independent-review.v1','passed':True,'reviewer':'retention_round2; not author of runtime engine, qualification harness or results',
            'scope':'Read-only independent reconstruction of every completed profile and committed receiver receipt; no scientific rerun','source_commit':frozen['source_commit'],
            'runtime_harness_commit':harness['runtime_harness_source_commit'],'main_freeze_sha256':sha(ROOT/'FREEZE.json'),'harness_freeze_sha256':sha(ROOT/'RUNTIME_HARNESS_FREEZE.json'),
            'both_freezes_verified_before_after':True,'frozen_source_files':len(frozen['sources_sha256']),'frozen_prepared_artifacts':len(frozen['artifacts_sha256']),
            'harness_sources_verified':len(harness['sources_sha256']),'runtime_evidence_files_hashed':len(before),'runtime_evidence_sha256':before,
            'results_sha256':sha(ROOT/'RUNTIME_RESULTS.json'),'accounting_sha256':sha(ROOT/'RUNTIME_ACCOUNTING.json'),'checks_by_category':dict(CHECKS),'maximum_absolute_recomputation_error':ERRORS,
            'coverage':{'profiles':15,'listed_qualification_assertions':allchecks,'generated_histories':generated,'unique_random_histories_exercised':20,'random_forecasts':180,'fresh_python_process_receipts':30,'deterministic_tail_fixtures':5,'unique_successful_native_ticks':len(allnative),'committed_composite_ticks_independently_reconstructed':all_composite,'pending_stages':dict(all_pending),'native_processes_reexecuted_by_review':0},
            'numerical_results':bounds_by_profile,'profiles':profile_reports,'forecast_recomputed_bounds':forecast_reports,
            'costs':{'qualification_wall_ns':sum(p['accounting']['qualification_wall_ns'] for p in profile_reports),'qualification_parent_cpu_ns':sum(p['accounting']['qualification_parent_cpu_ns'] for p in profile_reports),'successful_native_roundtrip_ns':sum(n['subprocess_roundtrip_ns'] for n in allnative.values()),'successful_native_typed_tick_wall_ns':sum(n['typed_tick_wall_ns'] for n in allnative.values()),'successful_native_head_execution_micros':sum(n['head_execution_micros'] for n in allnative.values()),'native_journal_bytes_written':sum(n['journal_bytes_written'] for n in allnative.values()),'profile_final_file_bytes':all_files_bytes,'total_child_cpu_ns':None,'failed_native_request_isolated_latency_ns':None,'total_adapter_file_write_bytes':None},
            'harness_AST_reversal_identical':True,'own_witness_vs_raw_native_separation_confirmed':True,'limitations':limits,
            'conclusion':'Guarded Q24 Gaussian parameters and separately projected categorical counts satisfy their declared .02 bounds in inspected evidence; count-only transport does not. The result establishes bounded non-authorizing runtime qualification, not production authority or retained efficacy.',
            'review_tool_recovery':'Initial read-only review assertion incorrectly demanded bit-identical native input JSON roundtrip. Actual observed error was checked and the assertion aligned with the frozen harness 2e-15 tolerance; a subsequent report-only serialization error for NumPy scalar counts was corrected. No scientific artifact, experiment, source or result was altered.',
            'review_wall_ns':time.perf_counter_ns()-began}


if __name__=='__main__':
    result=main();OUT.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))+'\n')
    print(json.dumps({'passed':result['passed'],'checks':sum(CHECKS.values()),'coverage':result['coverage'],'numerical_results':result['numerical_results'],'costs':result['costs'],'path':str(OUT)},indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)))
