"""Real original Harrier backbone to existing Cell heads; bounded synthetic mechanics, not efficacy."""
from __future__ import annotations
import os
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_TF='0', TOKENIZERS_PARALLELISM='false', HF_HUB_DISABLE_TELEMETRY='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import collections
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / 'hepta-cell-training-current'
OUT = HERE / 'harrier-real-cell-integration-v2'
PREVIOUS = HERE / 'harrier-real-cell-integration'
REVISION = '31de22b673913c7d658c0f03f792d77c2dcf8ebd'
MODEL_REPO = 'microsoft/harrier-oss-v1-270m'
SNAPSHOT = Path('/workspace/shared/hepta-cell-model-cache/models--microsoft--harrier-oss-v1-270m/snapshots') / REVISION
DOWNLOAD = Path('/workspace/shared/cell-model-evidence/download-manifest.json')
sys.path.insert(0, str(ROOT / 'codex-rs/hepta-neuron/qualification'))
import numpy as np
import torch
import decision_cell_bakeoff as b
from laya_loader_view import _inventory, _digest

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
if hasattr(os, 'sched_setaffinity'):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:1])

def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024 * 1024): h.update(block)
    return h.hexdigest()

def write_json(path, obj):
    raw = b.canonical_json(obj)
    with path.open('xb') as f: f.write(raw)
    return hashlib.sha256(raw).hexdigest()

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()

source = {'commit':git('rev-parse','HEAD'), 'tree':git('rev-parse','HEAD^{tree}')}
assert source['commit'] == '17e55bb34e63888b8f03a8f001d963d5a9b69fac'
assert not git('status','--porcelain')
OUT.mkdir(exist_ok=False)
started = time.perf_counter()
cpu_started = time.process_time()
expected = [{k: item[k] for k in ('path','bytes','sha256')} for item in json.loads(DOWNLOAD.read_text()) if item['repo'] == MODEL_REPO and item['revision'] == REVISION]
expected.sort(key=lambda x:x['path'])
original = _inventory(SNAPSHOT)
assert original == expected, 'snapshot differs from retained original download bytes'
snapshot_digest = _digest(original)
write_json(OUT/'model-inventory-before.json', original)
all_rows = b.build_dataset()
rows = []
for split in ('train','tuning','calibration','test'):
    for action in range(6):
        candidates = [r for r in all_rows if r.split == split and r.action == action]
        count = 2 if split == 'train' else 1
        assert len(candidates) >= count
        rows.extend(candidates[:count])
rows.extend([r for r in all_rows if r.split == 'ood_test'][:6])
assert len(rows) == 36
previous_rows = json.loads((PREVIOUS/'synthetic-rows.json').read_text())
assert json.loads(b.canonical_json([r.as_dict() for r in rows])) == previous_rows
previous_plan = json.loads((PREVIOUS/'plan.json').read_text())
assert hash_file(PREVIOUS/'plan.json') == '09edb086718f9fc86a1f1cf8cea2c2af1c32e4919ef8070cbdc72aa439d119d6'
assert previous_plan['source'] == source and previous_plan['model_snapshot_digest'] == snapshot_digest
cache = next((PREVIOUS/'embeddings').glob('*.npz'))
assert hash_file(cache) == '8d523988325481947bfae931b26d6112b0f9f6ca07e34c11d68ed95ca8087358'
with np.load(cache, allow_pickle=False) as saved:
    assert saved['example_ids'].tolist() == [r.example_id for r in rows]
    reused_state = saved['embeddings'].copy()
    reused_target = saved['target_embeddings'].copy()
assert reused_state.shape == (36,640) and reused_target.shape == (36,4,640)
assert reused_state.dtype == reused_target.dtype == np.float32
assert np.isfinite(reused_state).all() and np.isfinite(reused_target).all()
extra_rows = [r for r in all_rows if r.split == 'calibration' and r.ood == 1][:2]
assert len(extra_rows) == 2
rows.extend(extra_rows)
assert len({r.example_id for r in rows}) == len(rows) == 38
assert {r.ood for r in rows if r.split == 'calibration'} == {0,1}
cache_provenance = {
    'prior_plan_sha256':hash_file(PREVIOUS/'plan.json'),
    'prior_driver_sha256':hash_file(HERE/'run_harrier_cell_integration.py'),
    'prior_log_sha256':hash_file(HERE/'harrier-real-cell-integration.log'),
    'prior_row_manifest_sha256':hash_file(PREVIOUS/'synthetic-rows.json'),
    'prior_model_inventory_sha256':hash_file(PREVIOUS/'model-inventory-before.json'),
    'feature_npz_path':str(cache),'feature_npz_sha256':hash_file(cache),
    'original_encoder_vectors':180,'original_forward_calls':45,
    'original_encoding_seconds':45.86084750600003,
    'original_pipeline_status':'FAILED_CLOSED_AT_CALIBRATION_MISSING_OOD_POPULATION_AFTER_SUCCESSFUL_EXTRACTION',
    'new_calibration_rows':2,'test_or_ood_test_rows_changed':False,
    'cache_identity_verified':True,
}
assert previous_plan['rows_sha256'] == cache_provenance['prior_row_manifest_sha256']
assert previous_plan['driver_sha256'] == cache_provenance['prior_driver_sha256']
assert json.loads((PREVIOUS/'model-inventory-before.json').read_text()) == original
for split in {r.split for r in rows}:
    left={r.source_group for r in rows if r.split==split}
    right={r.source_group for r in rows if r.split!=split}
    assert left.isdisjoint(right)
row_digest=write_json(OUT/'synthetic-rows.json', [r.as_dict() for r in rows])
source_files={str(p.relative_to(ROOT)):hash_file(p) for p in [Path(b.__file__),b._TENSOR_PATH,ROOT/'codex-rs/hepta-neuron/qualification/decision_cell_calibration.py',ROOT/'codex-rs/hepta-neuron/qualification/decision_cell_metrics.py']}
plan={
 'kind':'bounded_original_backbone_cell_head_mechanics_NOT_QUALIFICATION', 'source':source,
 'driver_sha256':hash_file(__file__), 'source_files_sha256':source_files,
 'model_repository':MODEL_REPO, 'model_revision':REVISION, 'model_snapshot_digest':snapshot_digest,
 'download_manifest_sha256':hash_file(DOWNLOAD), 'rows_sha256':row_digest,
 'feature_cache_provenance':cache_provenance,
 'split_counts':dict(collections.Counter(r.split for r in rows)),
 'feature_profile':'original Harrier Gemma3 backbone + attention-mask-mean-v1; deliberately NOT published last-token+normalized SentenceTransformer representation',
 'maximum_length':192, 'batch_size':4, 'device':'cpu', 'torch_threads':1,
 'tokenization':{'class':'AutoTokenizer fast','local_files_only':True,'padding':True,'truncation':True,'maximum_length':192,'special_tokens':'tokenizer defaults','files':[x for x in original if x['path'] in ('tokenizer.json','tokenizer_config.json','special_tokens_map.json')]},
 'pooling_definition':'sum(last_hidden_state * attention_mask[...,None], token_axis) / clamp_min(sum(attention_mask[...,None],token_axis),1), then cast fp32; no L2 normalization',
 'pooling_mask_semantics':'Include every token whose tokenizer attention_mask is 1, including unmasked special tokens; exclude padding',
 'training_head_width':128,'consumer_batch_size':16,
 'train_seed':b.SEED, 'optimizer':'existing fit_heads AdamW', 'maximum_epochs':400,
 'holdout_policy':'Only train drives gradients; tuning selects epoch; calibration fits thresholds; test and ood_test excluded from training/selection/calibration. Templates remain synthetic and shared, not independent future families.',
 'new_external_data_upload':False, 'custom_remote_code':False, 'independent_efficacy':False,
 'all_blockers_closed':False, 'production_activation_allowed':False
}
plan_digest=write_json(OUT/'plan.json',plan)
print(json.dumps({'phase':'inputs_frozen','plan_sha256':plan_digest,'rows':38,'cached_vectors':180,'new_vectors_planned':10}),flush=True)
encoder = b.EncoderAdapter('harrier-270m-original-backbone', SNAPSHOT, {'kind':'transformers','trust_remote_code':False,'tokenizer_use_fast':True,'allowed_unexpected_keys':[]}, 'cpu', expected_snapshot_digest=snapshot_digest)
assert all(not p.requires_grad and p.device.type=='cpu' for p in encoder.model.parameters())
load_seconds=time.perf_counter()-started
forward=[]
def observe(module,args,kwargs):
    ids=kwargs['input_ids']; mask=kwargs['attention_mask']
    forward.append({'shape':list(ids.shape),'nonpadding_tokens':mask.sum(-1).tolist()})
handle=encoder.model.register_forward_pre_hook(observe,with_kwargs=True)
texts=[r.text for r in extra_rows]
pair_texts=[r.text+'\nCandidate under evaluation: '+candidate for r in extra_rows for candidate in r.candidates]
features_started=time.perf_counter()
state,state_ms=encoder.encode(texts,batch_size=4)
target_flat,target_ms=encoder.encode(pair_texts,batch_size=4)
features_seconds=time.perf_counter()-features_started
handle.remove()
assert state.shape==(2,640) and target_flat.shape==(8,640)
assert np.isfinite(state).all() and np.isfinite(target_flat).all()
assert _inventory(SNAPSHOT)==original, 'encoder changed original snapshot'
parameters=sum(p.numel() for p in encoder.model.parameters())
loading_report=encoder.loading_report
encoder.close()
target=np.concatenate((reused_target,target_flat.reshape(2,4,640)),axis=0)
state=np.concatenate((reused_state,state),axis=0)
assert state.shape==(38,640) and target.shape==(38,4,640)
embedding=b.save_embeddings(OUT,'harrier-original-mean-pool',[r.example_id for r in rows],state,target)
print(json.dumps({'phase':'real_encoder_complete','forward_calls':len(forward),'new_vectors':10,'cached_vectors':180,'seconds':features_seconds}),flush=True)
parts={}
for split in ('train','tuning','calibration','test','ood_test'):
    indexes=[i for i,r in enumerate(rows) if r.split==split]
    parts[split]=b.tensors([rows[i] for i in indexes],state[indexes],target[indexes])
torch.manual_seed(b.SEED)
initial=b.parameter_group_digests(b.TypedHeads(640))
training_started=time.perf_counter()
heads,training=b.fit_heads(parts['train'],parts['tuning'])
training_seconds=time.perf_counter()-training_started
changed={k:v!=initial[k] for k,v in b.parameter_group_digests(heads).items()}
assert all(changed.values()),changed
calibration=b.calibrate(heads,parts['calibration'])
metrics=b.evaluate(heads,parts['test'],calibration)
ood_metrics=b.evaluate(heads,parts['ood_test'],calibration)
metadata={
 'base_model':{'repo':MODEL_REPO,'revision':REVISION,'snapshot_digest':snapshot_digest,'files':original},
 'source':source,'calibration':calibration,'training':training,'synthetic_panel_only':True,
 'real_original_backbone_executed':True,'base_backbone_frozen':True,
 'representation_profile':plan['feature_profile'],'experiment_plan_sha256':plan_digest,
 'dataset_sha256':row_digest,'embedding_artifact':embedding,
 'independent_acceptance':False,'future_window_evidence':False,
}
_,artifact=b.save_head_artifact(OUT,'harrier-original-backbone-cell-head',heads,metadata)
manifest=json.loads(Path(artifact['manifest_path']).read_text())
bundle=b._tensor_module.HeadTensorBundleV2(
 manifest_path=Path(artifact['manifest_path']),manifest_sha256=artifact['manifest_sha256'],
 weights_path=Path(artifact['weights_path']),weights_sha256=artifact['weights_sha256'],
 expected_base_snapshot=snapshot_digest,expected_runtime_profile=manifest['runtime_profile'])
x=torch.from_numpy(state);tx=torch.from_numpy(target)
expected_batches=[]
observed_batches=[]
probability_batches=[]
for start in range(0,len(x),16):
    with torch.inference_mode(): expected_batches.append(heads(x[start:start+16],tx[start:start+16]))
    outputs, probabilities=bundle.observe_with_probabilities(x[start:start+16],tx[start:start+16])
    observed_batches.append(outputs)
    probability_batches.append(probabilities)
expected_outputs={k:torch.cat([batch[k] for batch in expected_batches]) for k in expected_batches[0]}
observed={k:torch.cat([batch[k] for batch in observed_batches]) for k in observed_batches[0]}
probabilities={k:torch.cat([batch[k] for batch in probability_batches]) for k in probability_batches[0]}
np.savez_compressed(OUT/'expected-head-logits.npz', **{k:v.detach().numpy() for k,v in expected_outputs.items()})
if calibration['calibration_support_mode']=='reject_all':
    assert not probabilities['supported'].any()
parity={k:torch.equal(v,observed[k]) for k,v in expected_outputs.items()}
assert all(parity.values()),parity
post_inventory=_inventory(SNAPSHOT)
assert post_inventory==original,'source model bytes changed'
write_json(OUT/'model-inventory-after.json',post_inventory)
assert not git('status','--porcelain')
assert source_files=={name:hash_file(ROOT/name) for name in source_files}
report={
 'status':'PASS_REAL_ENCODER_TRAIN_SAVE_SHARED_CONSUMER_PARITY',
 'source':source,'driver_sha256':hash_file(__file__),'plan_sha256':plan_digest,
 'source_files_sha256':source_files,'source_clean_before_and_after':True,
 'model_repository':MODEL_REPO,'model_revision':REVISION,'model_snapshot_digest':snapshot_digest,
 'model_parameter_count':parameters,'loading_report':loading_report,
 'model_bytes_unchanged':True,'model_trained':False,'head_groups_changed':changed,
 'split_counts':plan['split_counts'],'synthetic_rows_sha256':row_digest,
 'real_encoder_vectors_total':190,'new_encoder_vectors_this_run':10,
 'new_forward_calls_this_run':len(forward),'new_forward_observations':forward,
 'reused_feature_provenance':cache_provenance,
 'expected_head_logits_sha256':hash_file(OUT/'expected-head-logits.npz'),
 'consumer_batch_size':16,'consumer_all_rows':len(x),
 'consumer_supported_count':int(probabilities['supported'].sum()),
 'tokenization':plan['tokenization'],'pooling_definition':plan['pooling_definition'],
 'pooling_mask_semantics':plan['pooling_mask_semantics'],
 'embedding_artifact':embedding,'head_artifact':artifact,'training':training,
 'all_six_head_logits_bit_identical_after_reload':parity,
 'diagnostic_test_metrics':metrics,'diagnostic_ood_metrics':ood_metrics,
 'calibration':calibration,'resources':{
 'device':'cpu','cpu_affinity':sorted(os.sched_getaffinity(0)), 'torch_threads':torch.get_num_threads(),
 'load_and_preflight_seconds':load_seconds,'new_encoder_seconds':features_seconds,'cached_original_encoder_seconds':cache_provenance['original_encoding_seconds'],
 'head_training_seconds':training_seconds,'wall_seconds':time.perf_counter()-started,
 'process_cpu_seconds':time.process_time()-cpu_started,
 'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
 'gpu_used':False},
 'runtime':{n:importlib.metadata.version(n) for n in ('torch','transformers','numpy','safetensors')},
 'python':sys.version,'platform':platform.platform(),'host':platform.node(),
 'representation_profile':plan['feature_profile'],'published_harrier_representation_parity':False,
 'independent_future_benefit':False,'six_arm_four_scale_comparison':False,
 'independent_calibration_or_performance_qualification':False,'lifecycle_qualified':False,
 'model_selection_or_activation':False,'all_blockers_closed':False,
 'limitations':'Small synthetic corpus with shared templates; original model byte/LFS identity is locally rechecked, not independent execution attestation. Diagnostic metrics are not acceptance. No split or generation change performed.'
}
report_digest=write_json(OUT/'report.json',report)
print(json.dumps({'phase':'complete','status':report['status'],'report_sha256':report_digest,'resources':report['resources'],'groups_changed':changed,'parity':parity}),flush=True)
