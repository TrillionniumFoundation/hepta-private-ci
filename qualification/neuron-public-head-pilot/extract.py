"""Frozen public-text diagnostic. No remote model/code access and no model fitting."""
import argparse, hashlib, importlib.metadata, json, os, resource, sys, time
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,required=True,help='Prepared experiment directory containing frozen plan and selected rows')
parser.add_argument('--snapshot',type=Path,required=True,help='Existing pinned Harrier snapshot, no network downloads')
parser.add_argument('--bakeoff-dir',type=Path,default=Path(__file__).resolve().parent.parent/'neuron-model-bakeoff',help='Published artifact_guard.py helper directory')
args=parser.parse_args()
SOURCE=Path(__file__).resolve().parent
P=args.output_dir.resolve()
sys.path.insert(0,str(args.bakeoff_dir.resolve()))
from artifact_guard import SnapshotGuard
import artifact_guard
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
H=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,x): (P/name).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
if not __debug__: raise RuntimeError('optimized Python forbidden')
assert H(P/'plan.json')=='48ff3c003067370449254daefcf465c4960fbc01a39dae5b83d98123d3aec55c'
plan=json.loads((P/'plan.json').read_text()); rows=json.loads((P/'selected-local-only.json').read_text())
assert H(P/'selected-local-only.json')==plan['selected_local_sha256']
assert H(P/'rows.json')==plan['rows_sha256']
assert H(artifact_guard.__file__)==H(SOURCE/'observed/source/artifact_guard_reference.py')
assert not (P/'features.npz').exists(), 'never overwrite existing extraction'
torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
snapshot=args.snapshot.resolve()
meta={'plan_sha256':H(P/'plan.json'),'rows_sha256':H(P/'rows.json'),'driver_sha256':H(__file__),'guard_sha256':H(artifact_guard.__file__),'package_versions':{k:importlib.metadata.version(k) for k in ['torch','transformers','sentence-transformers','numpy','tokenizers','safetensors','huggingface-hub']},'torch_threads':torch.get_num_threads(),'cpu_affinity':sorted(os.sched_getaffinity(0)),'snapshots':{},'timings_seconds':{},'splits':{}}
start=time.monotonic()
expected=json.loads((SOURCE/'observed/extraction.json').read_text())
assert meta['package_versions']==expected['package_versions'], 'runtime versions differ from observed recipe'
with SnapshotGuard(snapshot) as guard:
    assert guard.original==expected['snapshot_inventory'], 'snapshot differs from observed pinned original'
    meta['snapshot_inventory']=guard.original;meta['snapshot_sha256']=guard.digest
    model=SentenceTransformer(str(guard.path),device='cpu',trust_remote_code=False,local_files_only=True,model_kwargs={'torch_dtype':torch.float32})
    model.max_seq_length=256;model.eval()
    assert all(p.dtype==torch.float32 for p in model.parameters())
    assert model[1].pooling_mode_lasttoken and not model[1].pooling_mode_mean_tokens
    guard.verify('after load');meta['snapshots']['after_load']='unchanged'
    meta['timings_seconds']['load_including_copy']=time.monotonic()-start
    # Independent manual last-nonpadding pooling against the module chain, same token batch.
    texts=[r['text'] for r in rows['head_train'][:8]]
    tokens=model.tokenize(texts)
    with torch.inference_mode():
        token_features=model[0]({k:v.clone() for k,v in tokens.items()})
        attention=token_features['attention_mask']; idx=(attention*torch.arange(attention.shape[1])).max(dim=1).values
        manual=torch.nn.functional.normalize(token_features['token_embeddings'][torch.arange(8),idx],p=2,dim=1)
        native=model({k:v.clone() for k,v in tokens.items()})['sentence_embedding']
    delta=float((manual-native).abs().max());assert delta<=1e-6, delta
    meta['native_pooling_parity_max_abs']=delta
    arrays={}
    for split in ['head_train','temperature','conformal','test']:
        t=time.monotonic(); texts=[r['text'] for r in rows[split]]
        lengths=[len(model.tokenizer(t,add_special_tokens=True,truncation=False)['input_ids']) for t in texts]
        z=model.encode(texts,prompt='',batch_size=8,show_progress_bar=False,convert_to_numpy=True,normalize_embeddings=True)
        assert z.shape==(len(texts),640) and z.dtype==np.float32 and np.isfinite(z).all()
        assert np.max(np.abs(np.linalg.norm(z,axis=1)-1))<1e-5
        arrays[split]=z
        meta['splits'][split]={'rows':len(texts),'truncated_rows':sum(n>256 for n in lengths),'raw_token_min':min(lengths),'raw_token_max':max(lengths),'raw_token_sum':sum(lengths),'used_token_sum':sum(min(256,n) for n in lengths),'feature_sha256':hashlib.sha256(z.tobytes()).hexdigest()}
        meta['timings_seconds'][split]=time.monotonic()-t
        print(json.dumps({'split':split,**meta['splits'][split],'seconds':meta['timings_seconds'][split]}),flush=True)
        guard.verify('after '+split);meta['snapshots']['after_'+split]='unchanged'
    guard.verify('before result write');meta['snapshots']['before_result_write']='unchanged'
# Guard exit verifies source/runtime again; only now publish frozen features.
np.savez_compressed(P/'features.npz',**arrays)
meta['features_file_sha256']=H(P/'features.npz');meta['max_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;meta['timings_seconds']['total']=time.monotonic()-start
save('extraction.json',meta)
print(json.dumps({'complete':True,'features_file_sha256':meta['features_file_sha256'],'max_rss_kib':meta['max_rss_kib'],'total_seconds':meta['timings_seconds']['total']}),flush=True)
