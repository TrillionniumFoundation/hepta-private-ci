"""Read-only independent R15 statistics recomputation; no project imports."""
import bisect, gzip, hashlib, json, math, os, resource, time
from pathlib import Path
import numpy as np
from scipy.stats import t as student

H=Path('/workspace/scratch/e0cf0c9f99f7/hepta-hcsn/tools/hcsn/addressed_decision_r15_20261101')
REPO=H.parents[2]
SEEDS=(151101,151103,151107,151109,151113,151117,151119,151123)
DOMAINS=('iid','ood')
ARMS=('A','B','C','D','hmm_same_matrix','free_value','factorized_value','memoryless_value','learned_state_confidence','learned_stop_value','learned_value_risk','learned_ordinary_dual')
METRICS=('utility','reward','fee','all_queries_correct','reads','refreshes','waits')
USES=(1,100,1000,10000)
start=time.perf_counter()
inputs={}; discrepancies=[]; max_abs=0.; close_checks=0; raw_queries=0

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1<<20),b''): digest.update(chunk)
    return digest.hexdigest()

def load(path):
    path=Path(path); inputs[str(path.relative_to(REPO))]=sha(path)
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)

def compare(a,b,label,tolerance=3e-11):
    global max_abs, close_checks
    close_checks+=1
    if a is None or b is None:
        if a is not b: discrepancies.append({'field':label,'recomputed':a,'reported':b})
        return
    difference=abs(float(a)-float(b)); max_abs=max(max_abs,difference)
    if not math.isfinite(difference) or difference>tolerance+1e-10*max(abs(float(a)),abs(float(b))):
        discrepancies.append({'field':label,'recomputed':a,'reported':b,'abs_error':difference})

def ensure(condition,message):
    if not condition: raise AssertionError(message)

def hash_manifest(path,base):
    manifest=load(path)
    for name,digest in manifest['files'].items():
        actual=sha(base/name)
        ensure(actual==digest,f'Frozen file changed: {name}')
        inputs[str((base/name).relative_to(REPO))]=actual
    return len(manifest['files'])

core_count=hash_manifest(H/'SOURCE_MANIFEST.json',REPO)
supp_count=hash_manifest(H/'SUPPLEMENT_MANIFEST.json',H)
summary=load(H/'results/SUMMARY.json')
freeze=load(H/'run_02/FREEZE.json')
publication=load(H/'run_02/SUPPLEMENT_PUBLICATION.json')
ensure(publication['supplement_commit']=='e4b51213bd19b6532553d252056573c17abc4814','Unexpected supplement commit')
ensure(publication['remote_readback_verified'] is True,'Supplement publication not verified')
train_cpu={}; training_function_cpu={}; original_source=freeze['original_source_commit']
for seed in SEEDS:
    path=H/'run_01/training'/f'{seed}.json.gz'
    ensure(sha(path)==freeze['training'][path.name],'Training archive differs from freeze')
    training=load(path)
    ensure(training['seed']==seed and training['development'] is False,'Wrong training registration')
    ensure(training['source_commit']==original_source,'Wrong training source')
    training_function_cpu[seed]=float(training['training_cpu_seconds'])
    receipt=load(H/'run_01/supervisor'/f'train_{seed}.json')
    ensure(receipt['exit_code']==0,'Failed training process')
    train_cpu[seed]=float(receipt['user_cpu_seconds']+receipt['system_cpu_seconds'])
    ensure(train_cpu[seed]+.002>=training_function_cpu[seed],'Incomplete training CPU envelope')
    del training

fit_values={domain:{arm:{metric:[] for metric in METRICS} for arm in ARMS} for domain in DOMAINS}
costs={domain:{arm:[] for arm in ARMS} for domain in DOMAINS}
mean_ledger=[]; tape_ids=set(); same_hmm_episodes=0; worker_cpu=0.; world_cpu=0.; full_worker_cpu=0.

def action_cost(actions,dt,scale):
    cost=0.; previous=0; counters={'READ':0,'REFRESH':0,'WAIT':0}
    for action in actions:
        name=action['action']; ensure(name in counters,'Unknown executed action')
        slots=2 if name=='REFRESH' else 1
        ensure(action['step']==previous+slots and action['step']<=3,'Bad action duration')
        cost+=.003*slots*dt+(.025*scale if name=='READ' else .07*scale if name=='REFRESH' else 0.)
        previous=action['step']; counters[name]+=1
    return cost,counters,previous

def query_truth(tape,key,deadline,side='left'):
    path=tape['paths'][key]
    j=(bisect.bisect_left(path['times'],deadline) if side=='left' else bisect.bisect_right(path['times'],deadline))-1
    return int(path['states'][max(0,j)])

def recompute_episode(ep,tape):
    global raw_queries
    ensure(ep.get('status')=='completed','A retained arm failed')
    ensure(ep['world']==tape['fingerprint'],'Wrong world fingerprint')
    ensure(len(ep['queries'])==6,'Incomplete completed episode')
    rewards=[]; fees=[]; counts={'READ':0,'REFRESH':0,'WAIT':0}
    for q,trace in enumerate(ep['queries']):
        raw_queries+=1
        ensure(trace['query']==q and trace['key']==tape['query_keys'][q],'Query/address mismatch')
        compare(trace['deadline'],tape['deadlines'][q],'raw deadline')
        compare(trace['dt'],tape['dts'][q],'raw dt')
        truth=query_truth(tape,trace['key'],tape['deadlines'][q])%4
        ensure(trace['target']==truth,'Target differs from saved world at pre-write deadline')
        reward=float(trace['answer']==truth)
        scale=(.5,1.,2.,4.)[hashlib.sha256(f"r15-price:{ep['seed']}:{q}".encode()).digest()[0]%4]
        compare(scale,trace['price_scale'],'raw public price')
        fee,executed,last=action_cost(trace['actions'],trace['dt'],scale)
        compare(trace['submitted_after'],last*trace['dt'],'raw submission latency')
        for action in trace['actions']:
            expected=tape['deadlines'][q]-(3-action['step'])*trace['dt']
            compare(action['time'],expected,'raw completion time')
        compare(reward,trace['reward'],'raw correctness')
        compare(fee,trace['fee'],'raw fee')
        compare(reward-fee,trace['utility'],'raw utility')
        rewards.append(reward);fees.append(fee)
        for key in counts: counts[key]+=executed[key]
    metrics=dict(reward=math.fsum(rewards)/6,fee=math.fsum(fees)/6,
        utility=math.fsum(r-f for r,f in zip(rewards,fees))/6,
        all_queries_correct=float(all(rewards)),reads=float(counts['READ']),
        refreshes=float(counts['REFRESH']),waits=float(counts['WAIT']))
    for name,value in metrics.items(): compare(value,ep[name],'episode.'+name)
    return metrics

for domain in DOMAINS:
    for seed in SEEDS:
        record=load(H/'run_02/confirmation'/f'{seed}_{domain}.json.gz')
        ensure(record['seed']==seed and record['domain']==domain and record['count']==128,'Wrong confirmation registration')
        ensure(record['development'] is False,'Development data in formal confirmation')
        ensure(record['source_commit']==original_source,'Core source changed')
        ensure(record['supplement_commit']==publication['supplement_commit']==record['freeze_commit'],'Supplement identity mismatch')
        ensure(record['freeze_sha256']==sha(H/'run_02/FREEZE.json'),'Wrong freeze hash')
        ensure(record['supplement_manifest_sha256']==sha(H/'SUPPLEMENT_MANIFEST.json'),'Wrong supplemental manifest')
        receipt=load(H/'run_02/supervisor'/f'confirm_{seed}_{domain}.json')
        ensure(receipt['exit_code']==0,'Supplement worker failed')
        measured=float(receipt['user_cpu_seconds']+receipt['system_cpu_seconds'])
        ensure(measured+.002>=record['worker_cpu_seconds'],'Incomplete confirmation CPU envelope')
        worker_cpu+=record['worker_cpu_seconds']; full_worker_cpu+=measured; world_cpu+=record['world_cpu_seconds']
        tapes={tape['seed']:tape for tape in record['world_tapes']}
        ensure(len(tapes)==128,'Wrong tape coverage')
        ensure(not(tape_ids & {t['fingerprint'] for t in tapes.values()}),'Reused confirmation world across fit/domain units')
        tape_ids.update(t['fingerprint'] for t in tapes.values())
        maps={arm:{ep['seed']:ep for ep in record['arms'][arm]['episodes']} for arm in (*ARMS,'mean_value')}
        for arm in (*ARMS,'mean_value'): ensure(set(maps[arm])==set(tapes),'Incomplete paired episode coverage')
        for epseed in tapes:
            ensure(maps['D'][epseed]['queries']==maps['hmm_same_matrix'][epseed]['queries'],'D/HMM trace difference')
            same_hmm_episodes+=1
        for arm in ARMS:
            collected={metric:[] for metric in METRICS}
            for epseed,ep in maps[arm].items():
                measured_metrics=recompute_episode(ep,tapes[epseed])
                for metric in METRICS: collected[metric].append(measured_metrics[metric])
            for metric in METRICS: fit_values[domain][arm][metric].append(math.fsum(collected[metric])/128)
            arm_record=record['arms'][arm]
            episode_cpu=math.fsum(ep['cpu_seconds'] for ep in maps[arm].values())
            compare(episode_cpu,arm_record['cpu_seconds'],'arm CPU sum')
            online=episode_cpu/128; cold=arm_record['preparation_cpu']+arm_record['checkpoint_io_cpu']
            costs[domain][arm].append(dict(seed=seed,online=online,cold=cold,
                full={n:train_cpu[seed]+cold+n*online for n in USES}))
        mean_arm=record['arms']['mean_value']; failures=[]; mean_fees=0.
        for epseed,ep in maps['mean_value'].items():
            if ep['status']=='completed':
                # Validate raw complete episodes, but never aggregate their performance.
                measured_metrics=recompute_episode(ep,tapes[epseed]); mean_fees+=measured_metrics['fee']*6
                continue
            ensure(ep['status']=='invalid_support','Unexpected mean failure')
            ensure(all(ep[k] is None for k in ('utility','reward','fee','all_queries_correct')),'Invented failed mean score')
            failure=ep['failure']; q=failure['query']; tape=tapes[epseed]
            ensure(len(failure['completed_queries'])==q,'Incorrect failed prefix coverage')
            ensure(failure['observation_likelihood']==0,'Unsupported exception was hidden')
            ensure(failure['quality']=='read','Positive-support refresh cannot be impossible')
            p=np.asarray(failure['checkpoint']['beliefs'])[failure['key']]
            token=failure['token']
            likelihood=float(p[32:].sum()) if token==4 else float(.1*p[:32].sum()+.6*p[token:32:4].sum())
            ensure(likelihood==0,'Claimed zero support differs from frozen emission model')
            step=failure['completed_step'];dt=tape['dts'][q]
            scale=(.5,1.,2.,4.)[hashlib.sha256(f"r15-price:{epseed}:{q}".encode()).digest()[0]%4]
            before,_,last=action_cost(failure['current_query_prior_actions'],dt,scale)
            ensure(step==last+1,'Failed READ duration wrong')
            expected_current=before+.003*dt+.025*scale
            compare(failure['current_query_total_incurred_fee'],expected_current,'failed action incurred fee')
            compare(failure['failed_observation_fee'],.025*scale,'failed READ price')
            total_fee=expected_current+math.fsum(qr['fee'] for qr in failure['completed_queries'])
            mean_fees+=total_fee
            failures.append(dict(episode_seed=epseed,query=q,key=failure['key'],token=token,
                cpu_seconds=ep['cpu_seconds'],incurred_fee=total_fee))
        mean_cpu=math.fsum(ep['cpu_seconds'] for ep in maps['mean_value'].values())
        compare(mean_cpu,mean_arm['cpu_seconds'],'mean all-attempt CPU')
        mean_ledger.append(dict(seed=seed,domain=domain,attempted=128,invalid=len(failures),failures=failures,
            all_cpu=mean_cpu,failed_cpu=math.fsum(f['cpu_seconds'] for f in failures),
            total_cpu=mean_cpu+mean_arm['preparation_cpu']+mean_arm['checkpoint_io_cpu'],incurred_fees=mean_fees))
        del record

# Independent scalar enumeration and arithmetic, without statistics-module calls.
def stats(vector):
    vector=[float(v) for v in vector];n=len(vector);mean=math.fsum(vector)/n
    variance=math.fsum((v-mean)**2 for v in vector)/(n-1)
    se=math.sqrt(variance/n)
    radius=float(student.isf(.025,n-1))*se
    return dict(mean=mean,se=se,ci=[mean-radius,mean+radius],values=vector)
def signs(vector):
    observed=abs(math.fsum(vector));threshold=observed-16*np.finfo(float).eps*max(math.fsum(abs(v) for v in vector),np.finfo(float).tiny)
    extreme=0
    for mask in range(256):
        signed=math.fsum(v if mask&(1<<j) else -v for j,v in enumerate(vector))
        extreme+=abs(signed)>=threshold
    return extreme/256,extreme

independent={};pvalues={};gain={};guard={};cost_gate={}
for domain in DOMAINS:
    values=fit_values[domain]
    for arm in ARMS:
        for metric in METRICS:
            estimate=stats(values[arm][metric]);reported=summary['domains'][domain]['arms'][arm][metric]
            compare(estimate['mean'],reported['mean'],f'{domain}.{arm}.{metric}.mean')
            for actual,expected in zip(estimate['values'],reported['fit_values']):compare(actual,expected,'fit raw metric')
            for actual,expected in zip(estimate['ci'],reported['t95_interval']):compare(actual,expected,'arm t95 interval')
    v={arm:np.asarray(values[arm]['utility']) for arm in 'ABCD'}
    contrasts={'B_minus_A':v['B']-v['A'],'D_minus_C':v['D']-v['C'],'C_minus_A':v['C']-v['A'],
               'D_minus_B':v['D']-v['B'],'interaction':v['D']-v['C']-v['B']+v['A']}
    estimates={name:stats(vector) for name,vector in contrasts.items()}
    for name,estimate in estimates.items():
        reported=summary['domains'][domain]['primary_utility_contrasts'][name]
        compare(estimate['mean'],reported['mean'],f'{domain}.{name}.mean')
        for actual,expected in zip(estimate['ci'],reported['t95_interval']):compare(actual,expected,f'{domain}.{name}.t95')
    p,extreme=signs(contrasts['D_minus_B']);pvalues[domain]=p
    signreport=summary['domains'][domain]['D_minus_B_sign_flip']
    compare(p,signreport['p_value'],domain+'.signflip.p',0)
    ensure(extreme==signreport['extreme_assignments'] and signreport['assignments']==256,'Sign assignment count differs')
    noninf={}
    for metric in ('utility','reward'):
        diff=np.asarray(values['D'][metric])-np.asarray(values['B'][metric]);estimate=stats(diff)
        lower=estimate['mean']-float(student.isf(.0125,7))*estimate['se']
        compare(lower,summary['domains'][domain]['noninferiority'][metric]['lower'],domain+'.NI.'+metric)
        noninf[metric]=dict(mean=estimate['mean'],lower=lower,passes=lower>-.01)
    guard[domain]=all(x['passes'] for x in noninf.values())
    online={arm:math.fsum(row['online'] for row in costs[domain][arm])/8 for arm in ARMS}
    curves={arm:{n:math.fsum(row['full'][n] for row in costs[domain][arm])/8 for n in USES} for arm in ARMS}
    ratios={n:curves['D'][n]/curves['B'][n] for n in USES};online_ratio=online['D']/online['B']
    reported=summary['domains'][domain]['costs']
    compare(online_ratio,reported['D_over_B_online_cpu'],domain+'.online_cost_ratio')
    for n in USES:compare(ratios[n],reported['D_over_B_full_cpu_by_uses'][str(n)],domain+'.full_cost_ratio.'+str(n))
    for arm in ARMS:
        compare(online[arm],reported['arms'][arm]['mean_online_cpu_per_episode'],domain+'.arm_online.'+arm)
        for n in USES:compare(curves[arm][n],reported['arms'][arm]['mean_full_cpu_by_uses'][str(n)],domain+'.arm_full.'+arm+str(n))
    cost_gate[domain]=online_ratio<=.9 and ratios[1000]<=.9
    independent[domain]=dict(contrasts=estimates,sign_flip_p=p,sign_flip_extreme=extreme,
        noninferiority=noninf,online_D_over_B=online_ratio,full_D_over_B_by_uses={str(n):ratios[n] for n in USES},cost_gate=cost_gate[domain])

ordered=sorted(DOMAINS,key=lambda d:(pvalues[d],d));last=0.;holm={}
for position,domain in enumerate(ordered):
    last=max(last,min(1.,(2-position)*pvalues[domain]));holm[domain]=last
for domain in DOMAINS:
    compare(holm[domain],summary['domains'][domain]['D_minus_B_sign_flip']['holm_adjusted_p'],domain+'.Holm',0)
    estimate=independent[domain]['contrasts']['D_minus_B']
    gain[domain]=estimate['mean']>=.01 and estimate['ci'][0]>0 and holm[domain]<.05
    independent[domain]['Holm_p']=holm[domain]
    independent[domain]['gain_gate']=gain[domain]

failures=sum(row['invalid'] for row in mean_ledger)
ensure(failures>0,'This audit expects the disclosed mean failure and must review a no-failure variant explicitly')
compare(failures,summary['mean_failure_ledger']['failed_attempts'],'mean total failures',0)
compare(sum(row['attempted'] for row in mean_ledger),summary['mean_failure_ledger']['attempted'],'mean total attempts',0)
for domain in DOMAINS:
    ensure(summary['domains'][domain]['arms']['mean_value'] is None,'Survivor-only mean performance was reported')
    ensure(summary['domains'][domain]['secondary']['D_minus_mean'] is None,'D-minus-mean was reported despite failed support')
    selected=[row for row in mean_ledger if row['domain']==domain]
    reported=summary['mean_failure_ledger']['domains'][domain]
    compare(sum(row['invalid'] for row in selected),reported['invalid_support'],domain+'.mean failures',0)
    compare(sum(row['invalid'] for row in selected)/1024,reported['invalid_support_rate'],domain+'.failure rate',0)
    for measured,key in (('all_cpu','cpu_seconds_all_attempts'),('failed_cpu','cpu_seconds_failed_attempts'),('total_cpu','total_measured_cpu'),('incurred_fees','incurred_task_fees_all_attempts')):
        compare(math.fsum(row[measured] for row in selected),reported[key],domain+'.mean '+key)
    independent[domain]['mean_invalid_support']=sum(row['invalid'] for row in selected)

admission=dict(design_complete=True,quality_gain=all(gain.values()),quality_noninferiority=all(guard.values()),
               quality_guarded_cost=all(guard.values()) and all(cost_gate.values()),same_matrix_HMM_behavior_identical=True,
               HX_exclusive_operator_gain=False,all_thirteen_arms_valid=False,mean_secondary_admissible=False)
for key,value in admission.items():ensure(summary['admission'][key]==value,'Admission mismatch: '+key)
compare(world_cpu,summary['research_infrastructure']['world_generation_cpu_seconds'],'world CPU')
compare(worker_cpu,summary['research_infrastructure']['confirmation_worker_cpu_seconds'],'worker function CPU')
compare(math.fsum(train_cpu.values()),summary['research_infrastructure']['training_allocated_cpu_seconds'],'training entire-process CPU')

# Retain old worker costs without reading or pooling any old confirmation result.
old_worker_cpu=0.;old_failed_cpu=0.;old_worker_count=0
for path in sorted((H/'run_01/supervisor').glob('confirm_*.json')):
    receipt=json.loads(path.read_text())
    if receipt.get('kind')!='confirm' or 'exit_code' not in receipt:continue
    inputs[str(path.relative_to(REPO))]=sha(path)
    amount=receipt['user_cpu_seconds']+receipt['system_cpu_seconds']
    old_worker_cpu+=amount;old_worker_count+=1
    if receipt['exit_code']!=0:old_failed_cpu+=amount
core_after=hash_manifest(H/'SOURCE_MANIFEST.json',REPO)
supp_after=hash_manifest(H/'SUPPLEMENT_MANIFEST.json',H)
usage=resource.getrusage(resource.RUSAGE_SELF)
report=dict(schema='hcsn-r15-independent-statistics-audit-v1',passed=not discrepancies,
    method='Independent raw world/query/action reconstruction and scalar arithmetic; no project statistical functions imported or called',
    source_commit=original_source,supplement_commit=publication['supplement_commit'],
    input_sha256=inputs,frozen_core_files_verified=core_count,frozen_supplement_files_verified=supp_count,
    frozen_source_unchanged=True,registered_fit_seeds=list(SEEDS),cohorts=16,episodes_per_cohort=128,
    paired_world_tapes=len(tape_ids),raw_complete_query_records_verified=raw_queries,
    same_matrix_HMM_identical_episode_traces=same_hmm_episodes,
    domains=independent,admission=admission,mean_failure_ledger=mean_ledger,
    total_mean_invalid_support=failures,total_mean_attempts=2048,
    comparison=dict(summary_path=str((H/'results/SUMMARY.json').relative_to(REPO)),numeric_checks=close_checks,
        maximum_absolute_difference=max_abs,discrepancies=discrepancies),
    cumulative_confirmation_cpu=dict(original_workers=old_worker_count,original_cpu_seconds=old_worker_cpu,
        original_failed_worker_cpu_seconds=old_failed_cpu,new_worker_cpu_seconds=full_worker_cpu,
        both_runs_cpu_seconds=old_worker_cpu+full_worker_cpu,original_confirmation_results_read=False),
    audit_process_cpu_seconds_through_report=usage.ru_utime+usage.ru_stime,
    audit_wall_seconds_through_report=time.perf_counter()-start,
    limits=['CPU timing is independently reconciled to receipts, not rebenchmarked.',
            'Original run_01 performance is excluded; only its cost receipts enter cumulative research accounting.',
            'Fit-level t intervals and four simultaneous NI bounds use the frozen parametric convention.',
            'Exact sign-flip inference assumes paired sign exchangeability.',
            'No claim of continuum convergence, production Rust performance, GPU energy or learned semantic addressing follows.'])
report['serialization_retry']=json.loads((H/'results/INDEPENDENT_STATISTICS_AUDIT.serialization_failure.json').read_text())
out=H/'results/INDEPENDENT_STATISTICS_AUDIT.json'
with out.open('x') as stream:
    json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False,default=lambda item: item.item() if isinstance(item,np.generic) else str(item));stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps({'passed':report['passed'],'numeric_checks':close_checks,'maximum_absolute_difference':max_abs,
                  'D_minus_B':{d:independent[d]['contrasts']['D_minus_B']['mean'] for d in DOMAINS},
                  'Holm':holm,'admission':admission,'mean_failures':failures,'HMM_identical_episodes':same_hmm_episodes,
                  'output':str(out)},sort_keys=True))
