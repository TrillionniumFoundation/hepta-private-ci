#!/usr/bin/env python3
"""Read-only independent scalar record/identity/dedup audit; no model or RNG."""
from pathlib import Path
import argparse,gzip,hashlib,json,math,statistics,struct

ROOT=Path(__file__).resolve().parent
FITS=[11,23,37,53,71]
RAW=['A','C','D','CD','G','CG']
PAIRS={'D':'A','CD':'C','G':'A','CG':'C'}
ARMS=RAW+[k+'_gated' for k in PAIRS]
METRICS=['expected_utility','belief_brier','q_mse','continuation_q_mse','teacher_behavior_regret','own_bank_probability_mse','own_bank_logit_mse']
PROTOCOL='f0b35b698c3da2738ef187fa6dea1f402a418d5cbf317f3fa425c5097fe26e90'
DESIGN='da512b0ac3a1fc9c67e8d004456f2c8605dcbddb3ec64888f3431627ec77b18c'
DRIVER='2472219f9d94fda23b74852ef4b09a0377e70c4211bb43bdd67aab6c4304e2f6'

def require(ok,label):
    if not ok:raise ValueError(label)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    p=Path(p);b=p.read_bytes();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def close(x,y,label,tol=2e-11):
    require(math.isfinite(x) and math.isfinite(y) and abs(x-y)<=tol*(1+max(abs(x),abs(y))),label)
def avg(xs):return math.fsum(xs)/len(xs)
def head_sha(head):return hashlib.sha256(b''.join(struct.pack('<d',x) for row in head for x in row)).hexdigest()
def schedule(w,fields):
    require(set(w)==set(fields+['id','packets','packet_sha256']),'world schema')
    return {k:w[k] for k in fields}

def probe_metrics(p,arm):
    belief='D' if arm in ('D','CD') else 'G' if arm in ('G','CG') else 'A'
    continuation='C' if arm in ('C','CD','CG') else 'A'
    n=p['rows'];require(len(p['world_ids'])==n,'probe count')
    qerr=[];cont=[];brier=[];ownerr=[];logerr=[];regret=[]
    for i in range(n):
        bp=p[belief+'_belief'][i];z=p[belief+'_logit'][i];own=p['model_bank7'][i]
        require(0<=bp<=1 and 0<own<1,'finite probability range')
        close(bp,1/(1+math.exp(-max(-700.,min(700.,z)))),'sigmoid logit identity')
        y=p['teacher_q'][i];legal=p['legal'][i];c=p[continuation+'_continuation'][i]
        q=[0.]+c+[1-2*bp,2*bp-1];indices=[j for j,v in enumerate(legal) if v]
        require(len(indices)>0,'at least one legal action')
        chosen=max(indices,key=lambda j:q[j]);best=max(y[j] for j in indices)
        qerr.append(avg([(q[j]-y[j])**2 for j in indices]))
        cont.extend((q[j]-y[j])**2 for j in [1,2,3] if legal[j])
        brier.append((bp-p['teacher_belief'][i])**2);ownerr.append((bp-own)**2)
        logerr.append((z-(math.log(own)-math.log1p(-own)))**2);regret.append(best-y[chosen])
    return {'expected_rows':n,'q_mse':avg(qerr),'continuation_q_mse':avg(cont),
        'belief_brier':avg(brier),'own_bank_probability_mse':avg(ownerr),'own_bank_logit_mse':avg(logerr),'teacher_behavior_regret':avg(regret)}

def check_metric_record(record,probe,arm):
    expected=probe_metrics(probe,arm)
    for key,value in expected.items():close(record[key],value,'probe metric '+key)
    close(record['expected_utility'],avg(record['world_utilities']),'full-world utility mean')

def verify_old177(study,analytic):
    before=read(ROOT/'PREVIOUS_177_BEFORE.json');after=read(ROOT/'OLD_177_PRESERVATION.json')
    require(sha(ROOT/'PREVIOUS_177_BEFORE.json')==after['before_manifest_sha256'],'old177 before identity')
    require(before['total_files']==after['total_files']==177 and after['all177_unchanged'],'old177 count')
    for key,base,count in [('previous_root_payload',study.parent,88),('previous_ndu_value_grid',study.parent/'ndu_value_grid',35),('previous_analytic_belief_bypass',analytic,54)]:
        require(before[key]==after['after'][key] and len(before[key])==count,'old177 after map')
        for name,entry in before[key].items():
            path=base/name;require(path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256'],'old immutable '+name)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);ap.add_argument('--analytic-root',required=True)
    args=ap.parse_args();study=Path(args.study_root);analytic=Path(args.analytic_root);records=ROOT/'records'
    require(sha(ROOT/'PROTOCOL_BEFORE_RESULTS.json')==PROTOCOL,'protocol identity')
    require(sha(ROOT/'DESIGN_BEFORE_RESULTS.json')==DESIGN and sha(ROOT/'run_belief_compile.py')==DRIVER,'design/driver identity')
    protocol=read(ROOT/'PROTOCOL_BEFORE_RESULTS.json');design=read(ROOT/'DESIGN_BEFORE_RESULTS.json')
    require(protocol['design_sha256']==DESIGN and protocol['frozen_design']==design,'protocol design chain')
    for name,h in design['local_source_sha256'].items():require(sha(ROOT/name)==h,'local source '+name)
    for name,h in design['joint_source_sha256'].items():require(sha(study/name)==h,'joint source '+name)
    require(sha(analytic/'run_analytic_belief.py')==design['analytic_driver_sha256'],'analytic library source')
    require(sha(ROOT/'HISTORY_REGISTRY.json.gz')==design['history_registry_sha256'],'history identity')
    require(sha(ROOT/'HISTORICAL_SEED_REGISTRY.json')==design['historical_seed_registry_sha256'],'seed history identity')
    r=read(records/'RESULTS.json.gz');qualification=read(records/'QUALIFICATION.json')
    require(r['status']==qualification['status']=='completed','completed once')
    require(r['protocol']==protocol and r['protocol_sha256']==PROTOCOL and qualification['driver_sha256']==DRIVER,'executed identity')
    require(sha(records/'RESULTS.json.gz')==qualification['results_sha256'],'results receipt')
    require(r['execution_graph_changed'] is False and r['teacher_targets_used_for_fitting'] is False,'pure weight self-target scope')
    require(r['all_original_inputs_and_sources_unchanged'] and r['all_test_worlds_generated'],'completed source/test flags')
    require([f['fit'] for f in r['fits']]==FITS,'all five fits')
    frozen=read(records/'ALL_SOLVERS_AND_GATES_BEFORE_TEST.json')
    require(sha(records/'ALL_SOLVERS_AND_GATES_BEFORE_TEST.json')==r['selection_freeze_sha256'],'all fit freeze')
    require(frozen['protocol_sha256']==PROTOCOL and frozen['design_sha256']==DESIGN and not frozen['test_worlds_generated'] and not frozen['test_scoring_started'],'pre-generation freeze')
    for name,h in frozen['record_sha256'].items():require(sha(records/name)==h,'pre-test file '+name)
    require(len(frozen['record_sha256'])==25,'five problems/solvers/before plus10 old probes')
    history=read(ROOT/'HISTORY_REGISTRY.json.gz');fields=history['canonical_schedule_fields']
    previous={hashlib.sha256(canonical(schedule(e['world'],fields))).hexdigest() for e in history['entries']}
    require(len(history['entries'])==1680 and len(previous)==1616,'history coverage')
    for e in history['entries']:require(hashlib.sha256(canonical(schedule(e['world'],fields))).hexdigest()==e['schedule_sha256'],'historical content fingerprint')
    dedup=read(records/'ALL_TEST_WORLDS_DEDUP_BEFORE_SCORING.json')
    require(sha(records/'ALL_TEST_WORLDS_DEDUP_BEFORE_SCORING.json')==r['dedup_before_scoring_sha256'],'dedup identity')
    require(dedup['selection_freeze_sha256']==r['selection_freeze_sha256'] and dedup['test_scoring_started'] is False,'dedup ordered after gates before score')
    require(dedup['passed'] and not dedup['duplicates'] and not dedup['resampling'] and not dedup['seed_reselection'],'no repeat/resample')
    require(dedup['global_unseen_beyond_registered_history_claim'] is False,'known-history scope')
    require(dedup['seed_records']==protocol['derived_rng_streams'],'declared seed streams')
    entropy=[]
    for item in dedup['seed_records']:
        payload=item['payload'];require(payload['design_sha256']==DESIGN and payload['generator_sha256']==design['joint_source_sha256']['run_head_edit.py'],'seed domain source')
        h=hashlib.sha256(canonical(payload)).hexdigest();require(item['sha256']==h and item['integer_entropy_decimal']==str(int(h,16)),'full256-bit seed')
        entropy.append(int(h,16))
    require(len(entropy)==len(set(entropy))==20,'20 distinct domain-separated streams')
    new=set();count=0
    for item in dedup['world_records']:
        path=records/item['file'];require(sha(path)==item['sha256'],'test world file')
        worlds=read(path);require(len(worlds)==32,'worlds per fit/domain')
        fingerprints=[hashlib.sha256(canonical(schedule(w,fields))).hexdigest() for w in worlds]
        require(fingerprints==item['schedule_sha256'],'world fingerprint list')
        for fp in fingerprints:require(fp not in previous and fp not in new,'known or current duplicate');new.add(fp)
        count+=len(worlds)
    require(count==len(new)==320 and dedup['world_count']==320,'all320 before scoring')
    metrics_verified=0;probes_verified=0;ci_count=0
    for f,ff in zip(r['fits'],frozen['fits']):
        fit=f['fit'];before=read(records/f'fit_{fit}_BEFORE_TEST.json')
        require(before==ff and not ff['tests'],'per-fit pre-test record')
        require(f['gates']==ff['gates'] and f['heads']==ff['heads'] and f['solvers']==ff['solvers'],'no test-informed changes')
        for name,head in f['heads'].items():require(head_sha(head)==f['head_sha256'][name],'head identity')
        for name,base in PAIRS.items():
            gate=f['gates'][name];gain=f['validation'][name]['expected_utility']-f['validation'][base]['expected_utility']
            close(gain,gate['validation_gain'],'correct incumbent VAL gain');require(gate['accepted']==(gain>=.005) and gate['incumbent']==base,'fixed paired VAL gate')
            require(f['heads'][name][:3]==f['heads'][base][:3],'continuation unchanged')
            model=f['candidate_models'][name];require(model['only_belief_row_changes_verified'] and model['json_roundtrip_head_identical'],'weight JSON shape guard')
            expected=[row+[bias] for row,bias in zip(model['network_w2'],model['network_b2'])]
            require(expected==f['heads'][name],'published parameter recipe')
        for split in ['train','validation']:
            ref=f['probes'][split];require(sha(records/ref['file'])==ref['sha256'],'original probe source')
            probe=read(records/ref['file']);probes_verified+=1
            oldprobe=read(analytic/'records'/f'fit_{fit}_{split}_PROBE.json.gz')
            for key in ['world_ids','teacher_q','legal','teacher_belief','model_bank7','A_continuation','C_continuation']:
                require(probe[key]==oldprobe[key],'original shared probe equality '+key)
            for arm in RAW:check_metric_record(f[split][arm],probe,arm);metrics_verified+=1
        for domain in ['iid','ood']:
            test=f['tests'][domain];require(sha(records/test['probe_file'])==test['probe_file_sha256'],'new probe identity')
            require(sha(records/test['world_file'])==test['world_file_sha256'],'new world identity')
            probe=read(records/test['probe_file']);probes_verified+=1
            for arm in ARMS:
                if arm in RAW:metric_arm=arm
                else:
                    raw=arm.removesuffix('_gated');metric_arm=raw if f['gates'][raw]['accepted'] else PAIRS[raw]
                    require(test['arms'][arm]==test['arms'][metric_arm],'gated arm exact accept/restore')
                require(len(test['arms'][arm]['world_utilities'])==32,'complete32 utility values')
                check_metric_record(test['arms'][arm],probe,metric_arm);metrics_verified+=1
    contrasts={k+'_minus_'+v:(k,v) for k,v in PAIRS.items()}
    contrasts.update({k+'_gated_minus_'+v:(k+'_gated',v) for k,v in PAIRS.items()})
    contrasts.update({'D_minus_G':('D','G'),'CD_minus_CG':('CD','CG'),'C_minus_A':('C','A')})
    for domain in ['iid','ood']:
        summary=r['summary'][domain]
        for arm in ARMS:
            for metric in METRICS:
                values=[f['tests'][domain]['arms'][arm][metric] for f in r['fits']]
                require(summary['arms'][arm][metric]['per_fit']==values,'per-fit aggregate inputs')
                close(summary['arms'][arm][metric]['mean'],avg(values),'aggregate mean')
        require(set(summary['contrasts'])==set(contrasts),'all contrasts retained')
        for name,(a,b) in contrasts.items():
            for metric in METRICS:
                values=[f['tests'][domain]['arms'][a][metric]-f['tests'][domain]['arms'][b][metric] for f in r['fits']]
                report=summary['contrasts'][name][metric];require(report['per_fit']==values and report['independent_fits']==5,'paired fit values')
                m=avg(values);half=2.7764451051977987*statistics.stdev(values)/math.sqrt(5)
                close(report['mean'],m,'contrast mean');close(report['descriptive_paired_95_ci'][0],m-half,'CI low');close(report['descriptive_paired_95_ci'][1],m+half,'CI high');ci_count+=1
    verify_old177(study,analytic)
    transfer=read(ROOT/'TRANSFER_VERIFICATION.json')
    require(len(transfer['files'])==49 and transfer['all49_files_verified'],'49 source records transferred')
    for item in transfer['files']:
        path=records/item['name'];require(sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'transfer identity')
    process=read(records/'PROCESS_VERIFICATION.json')
    require(process['state']=='succeeded' and process['exit_code']==0 and process['stderr_bytes']==0 and not process['timed_out'] and not process['cancelled'],'successful durable process')
    stages=[x['stage'] for x in process['ordered_events']]
    require(stages==['solvers_and_original_gates_frozen']*5+['all_five_solver_and_gate_records_frozen_before_generation','all320_worlds_deduplicated_before_any_test_scoring']+['test_complete']*5+['finished'],'event chronology')
    print(json.dumps({'status':'passed_record_identity_metrics_dedup','verifier_sha256':sha(__file__),
        'results_sha256':qualification['results_sha256'],'probes_verified':probes_verified,
        'arm_split_records_verified':metrics_verified,'contrast_metric_CIs_verified':ci_count,
        'test_worlds_verified':320,'history_unique_schedules':1616,'previous_frozen_files_verified':177,
        'transferred_raw_files_verified':49,'new_model_calls':0,'random_draws':0,
        'scope':'Scalar record arithmetic, source/parameter identity, exact registered-content dedup and recorded freeze chain only. Convex numerical-source verification is independently handled by verify_belief_solver_records.py; no global external-history freshness claim.'},indent=2))

if __name__=='__main__':main()
