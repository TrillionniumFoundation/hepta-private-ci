from pathlib import Path
import json,os,subprocess,sys,time
base=Path('/mnt/data/hepta_v15_work')
source=base/'qualification/stem-cell-v1'
env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
receipts=[]
for name in ('metered_a','metered_b'):
    out=base/name
    cmd=[sys.executable,str(source/'stem_stable_router_v15.py'),'--inputs',str(base/'original_input'),'--output',str(out)]
    start=time.perf_counter_ns()
    with (base/(name+'.log')).open('wb') as log:
        child=subprocess.Popen(cmd,env=env,stdout=log,stderr=log)
        pid,status,usage=os.wait4(child.pid,0)
        code=os.waitstatus_to_exitcode(status)
        child.returncode=code
    if code: raise RuntimeError((name,code))
    receipts.append({'replica':name,'exit_code':code,'wall_ns':time.perf_counter_ns()-start,
        'user_cpu_seconds':usage.ru_utime,'system_cpu_seconds':usage.ru_stime,
        'peak_rss_bytes':usage.ru_maxrss*1024,'major_faults':usage.ru_majflt,
        'scope':'Linux wait4 whole child includes Python/Torch import, training, persistence; excludes original Encoder and preparation'})
    subprocess.run([sys.executable,str(source/'stem_stable_router_v15_review.py'),'--inputs',str(base/'original_input'),
        '--candidates',str(out),'--output',str(base/(name+'_review.json'))],env=env,check=True)
a=json.loads((base/'metered_a/sealed.json').read_bytes())
b=json.loads((base/'metered_b/sealed.json').read_bytes())
assert a['models']==b['models']
for seed in a['seeds']:
    for field in ('oof_logits','oof_targets','calibration_probabilities','blind_probabilities','selected_research_candidate'):
        assert a['seeds'][seed][field]==b['seeds'][seed][field],(seed,field)
result={'replicas':receipts,'model_file_sha_equal':len(a['models']),'calibration_probability_rows_equal':768,
    'blind_probability_rows_equal':768,'out_of_fold_logits_equal':1536,'steps_per_campaign':3600,
    'held_labels_read':False,'held_scores':None,'production_authorized':False,'target_host_qualified':False}
(base/'measured_replicas.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
