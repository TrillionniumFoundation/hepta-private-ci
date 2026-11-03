"""Fresh-process shared-consumer verification, never model-quality qualification."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import numpy as np
import torch
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
if hasattr(os,'sched_setaffinity'):
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:1])
HERE=Path(__file__).resolve().parent
OUT=HERE/'harrier-real-cell-integration-v2'
ROOT=HERE.parent/'hepta-cell-training-current'
start=time.perf_counter()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
report=json.loads((OUT/'report.json').read_text())
assert report['status']=='PASS_REAL_ENCODER_TRAIN_SAVE_SHARED_CONSUMER_PARITY'
assert subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()==report['source']['commit']
assert not subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain'],text=True).strip()
for path,digest in report['source_files_sha256'].items(): assert sha(ROOT/path)==digest
consumer=ROOT/'codex-rs/hepta-infer-worker-host/python/decision_cell_tensors.py'
spec=importlib.util.spec_from_file_location('standalone_consumer',consumer)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
a=report['head_artifact']
assert sha(a['manifest_path'])==a['manifest_sha256']
assert sha(a['weights_path'])==a['weights_sha256']
manifest=json.loads(Path(a['manifest_path']).read_text())
assert not any(manifest[key] for key in ('production_activation','operator_acceptance','selected','release'))
args=dict(manifest_path=Path(a['manifest_path']),manifest_sha256=a['manifest_sha256'],weights_path=Path(a['weights_path']),weights_sha256=a['weights_sha256'],expected_base_snapshot=report['model_snapshot_digest'],expected_runtime_profile=manifest['runtime_profile'])
bundle=module.HeadTensorBundleV2(**args)
e=report['embedding_artifact']
assert sha(e['path'])==e['sha256']
assert sha(OUT/'expected-head-logits.npz')==report['expected_head_logits_sha256']
rows=json.loads((OUT/'synthetic-rows.json').read_text())
with np.load(e['path'],allow_pickle=False) as data:
    assert data['example_ids'].tolist()==[r['example_id'] for r in rows]
    x=torch.from_numpy(data['embeddings'].copy())
    target=torch.from_numpy(data['target_embeddings'].copy())
outputs=[]
support=[]
for offset in range(0,len(x),16):
    raw,p=bundle.observe_with_probabilities(x[offset:offset+16],target[offset:offset+16])
    outputs.append(raw)
    support.append(p['supported'])
with np.load(OUT/'expected-head-logits.npz',allow_pickle=False) as expected:
    parity={key:np.array_equal(torch.cat([o[key] for o in outputs]).numpy(),expected[key]) for key in expected.files}
assert set(parity)=={'action','target','disposition','postcondition','ood','value_cost'}
assert all(parity.values())
negative={}
for name,change in [
    ('manifest_digest_substitution',{'manifest_sha256':'0'*64}),
    ('weight_digest_substitution',{'weights_sha256':'0'*64}),
    ('base_snapshot_substitution',{'expected_base_snapshot':'0'*64}),
    ('pooling_profile_substitution',{'expected_runtime_profile':{**manifest['runtime_profile'],'pooling':'last-token'}}),
]:
    try: module.HeadTensorBundleV2(**{**args,**change})
    except ValueError as exc: negative[name]=str(exc)
    else: raise AssertionError(name+' was accepted')
supported=torch.cat(support)
if report['calibration']['calibration_support_mode']=='reject_all': assert not supported.any()
result={
    'status':'PASS_FRESH_PROCESS_SHARED_CONSUMER_PARITY_AND_IDENTITY_REJECTIONS',
    'driver_sha256':sha(__file__),'input_report_sha256':sha(OUT/'report.json'),
    'source':report['source'],'consumer_source_sha256':sha(consumer),
    'rows':len(x),'batch_size':16,'all_six_head_logits_bit_identical':parity,
    'identity_rejection_probes':negative,'supported_rows':int(supported.sum()),
    'production_flags_false':True,'elapsed_seconds':time.perf_counter()-start,
    'new_encoder_execution':False,'independent_efficacy':False,'training_runtime_imported':False,
}
raw=(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
with (OUT/'fresh-consumer-verification.json').open('xb') as handle: handle.write(raw)
print(json.dumps({'status':result['status'],'sha256':hashlib.sha256(raw).hexdigest(),'parity':parity,'negative_checks':negative,'seconds':result['elapsed_seconds']}))
