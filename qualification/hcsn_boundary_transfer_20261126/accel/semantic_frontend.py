"""Apply the fixed speech encoder to each observed prefix before AV retrieval."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import time

START = time.perf_counter()
import numpy as np
import torch
from transformers import Wav2Vec2ForCTC
from benchmark import HASHES, digest, save

MODEL_FILES = {
    'config.json':'d3ec255c063d9f95057b553b19c20135b259875834a4fe9deb218a6be25b4cf3',
    'model.safetensors':'8aa76ab2243c81747a1f832954586bc566090c83a0ac167df6f31f0fa917d74a',
}
SPLITS = ('train','dev','retain','test')

def decode(it):
    p, expected = it
    if digest(p)!=expected:
        raise ValueError(f'corrupt public recording {p.name}')
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
        'stream=codec_type,sample_rate,start_time','-of','json',str(p)]))['streams']
    times=[float(s['start_time']) for s in streams if s['codec_type'] in ('video','audio')]
    if len(times)!=2 or max(abs(t) for t in times)>1e-9:
        raise ValueError('Expected zero common presentation-time origin')
    sr=int(next(s['sample_rate'] for s in streams if s['codec_type']=='audio'))
    if sr!=48000:
        raise ValueError('Expected 48 kHz source')
    pcm=subprocess.check_output(['ffmpeg','-nostdin','-threads','1','-v','error','-i',str(p),
                                 '-map','0:a:0','-ac','1','-t','2.88','-f','f32le','-'])
    data=np.frombuffer(pcm,dtype='<f4')
    if len(data)!=138240:
        raise ValueError('Incomplete 2.88-second audio')
    return data.reshape(-1,3).mean(1)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--base-code', type=Path, required=True)
    args=p.parse_args()
    args.output.mkdir(exist_ok=False,parents=True)
    if any(digest(args.model/k)!=v for k,v in MODEL_FILES.items()):
        raise ValueError('Unexpected pretrained weights')
    # The official CTC release omits the training-only masking vector. Disable
    # SpecAugment when constructing the frozen evaluation-only encoder.
    model,info=Wav2Vec2ForCTC.from_pretrained(
        args.model, local_files_only=True, output_loading_info=True,
        apply_spec_augment=False, mask_time_prob=0.0, mask_feature_prob=0.0)
    if info['missing_keys'] or info['mismatched_keys'] or info['error_msgs']:
        raise ValueError('Incomplete speech model')
    model.requires_grad_(False).eval().cuda()
    hashes={}
    for split in SPLITS:
        src=json.loads((args.original/(split+'.receipt.json')).read_text())
        for k,v in src['source_sha256'].items():
            if k in hashes and hashes[k]!=v:
                raise ValueError('Conflicting source hashes')
            hashes[k]=v
    names=sorted(hashes)
    if len(names)!=192:
        raise ValueError('incomplete recordings')
    names_to_i={n:i for i,n in enumerate(names)}
    items=[(args.original/'media-cache'/n,hashes[n]) for n in names]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        audio=torch.from_numpy(np.stack(list(pool.map(decode,items)))).cuda()
    after_decode=time.perf_counter()
    seq=[]
    with torch.inference_mode():
        for t in range(1,7):
            means=[]
            for batch in audio[:, :7680*t].split(12):
                wav=(batch-batch.mean(-1,keepdim=True))*torch.rsqrt(batch.var(-1,unbiased=False,keepdim=True)+1e-7)
                post=model(wav).logits.softmax(-1).mean(1)
                post=post[:,1:] # vocab ID 0 is the CTC blank for this pinned model
                template=post/post.sum(-1,keepdim=True).clamp_min(1e-12)
                means.append(template.sqrt().cpu().numpy())
            seq.append(np.concatenate(means))
    emb=np.stack(seq,axis=1)
    # Per-recording, per-prefix posterior histogram; no test labels used to construct it.
    if not np.isfinite(emb).all() or np.max(np.abs((emb**2).sum(-1)-1))>1e-5:
        raise ValueError('Invalid histogram normalization')
    after_neural=time.perf_counter()
    identities={}
    for split in SPLITS:
        path=args.original/(split+'.npz')
        if digest(path)!=HASHES[split]: raise ValueError('Wrong source split')
        with np.load(path,allow_pickle=False) as z:
            arrays=dict(z)
        q=emb[[names_to_i[n] for n in arrays['query_id']]]
        gallery=emb[np.array([[names_to_i[n] for n in row] for row in arrays['gallery_id']])]
        acoustic=-(np.square(q[:,None]-gallery).sum(-1)/2).transpose(0,2,1)
        visual=2*arrays['read_scores']-arrays['scores']
        if split=='train':
            scales=(max(acoustic.std(),1e-8),max(visual.std(),1e-8))
        arrays['scores']=acoustic/scales[0]
        arrays['read_scores']=(arrays['scores']+visual/scales[1])/2
        dst=args.output/(split+'.npz')
        np.savez_compressed(dst,**arrays)
        identities[split]=digest(dst)
    # The training engine remains byte-identical apart from the declared new cache hashes.
    code=args.base_code.read_text()
    for split,new_hash in identities.items():
        if code.count(HASHES[split])!=1: raise ValueError('Source shape changed')
        code=code.replace(HASHES[split],new_hash)
    entry=args.output/'semantic_executor.py'
    entry.write_text(code)
    receipt={'model':'facebook/wav2vec2-base-960h','revision':'22aad52d435eb6dbaf354bdad9b0da84ce7d6156',
             'weight_hashes':MODEL_FILES,'source_recording_count':len(names),'source_manifest_sha256':
             hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),'device':torch.cuda.get_device_name(0),
             'model_parameters':sum(x.numel() for x in model.parameters()),'missing_weights':info['missing_keys'],
             'frozen_parameters':all(not p.requires_grad for p in model.parameters()),
             'scales':list(map(float,scales)),'input_hashes':HASHES,'output_hashes':identities,
             'generated_runner':digest(entry),'original_runner':digest(args.base_code),'frontend_source':digest(__file__),
             'import_hash_load_decode_wall':after_decode-START,'prefix_inference_wall':after_neural-after_decode,
             'total_wall':time.perf_counter()-START,'torch':str(torch.__version__),'prefix_samples':[7680*t for t in range(1,7)]}
    save(receipt,args.output/'frontend_receipt.json')
    print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__':
    main()
