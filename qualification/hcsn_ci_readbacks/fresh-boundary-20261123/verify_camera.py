"""Replay the batch in reverse order with the original in-memory RGB decoder and no supplied labels."""
import argparse
from pathlib import Path
import hashlib
import json
import time
import numpy as np
import torch
from qualification.hcsn_intervention_value.media import vision
from recover_preroll import recover

def parse(path):return json.loads(path.read_text())
def hashed(tensor):return hashlib.sha256(tensor.detach().contiguous().numpy().tobytes()).hexdigest()
def verify(args):
    began=time.monotonic(); out=args.out
    roster=parse(out/'roster.json');receipt=parse(out/'camera-receipt.json')
    sources={str(r['pageid']):r for r in parse(Path(__file__).with_name('cohort.json'))['sources']}
    prior={row['query_id']:row for row in receipt['rows']}
    with np.load(out/'camera.npz',allow_pickle=False) as archive:old=dict(zip(archive['query_id'].tolist(),archive['probability'].copy()))
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert vision.digest(args.weights)==receipt['weights']
    model,tfm,labels=vision.load_model(args.weights)
    audit={}
    with torch.inference_mode():
        for item in reversed(roster):
            # Only the physical file, registered time and opaque query ID reach the decoder/model.
            ident=item['query_id'];r=sources[item['recording']]
            name=item['recording']+Path(r['title']).suffix
            p=next(root/name for root in args.originals if (root/name).is_file())
            assert vision.digest(p)==r['source_sha256']==prior[ident]['source_sha256']
            try:
                images,clock=vision.decode_prefixes(p,item['start_seconds'],vision.source_meta(p))
                t=torch.stack([tfm(image) for image in images]);del images
                assert clock==prior[ident]['clock']
                status='original-decoder'
            except ValueError as error:
                if ident!='fresh-37320740-w01' or str(error)!='invalid frame sequence':raise
                t,proof=recover({'query_id':ident,'start_seconds':item['start_seconds']},p,tfm)
                assert proof['rgb_sha256']==prior[ident]['rgb_sha256']
                status='certified-preroll'
            logits=model(t);probs=vision.cumulative_class_probability(logits,labels)
            assert hashed(t)==prior[ident]['transform_sha256'] and hashed(logits)==prior[ident]['logits_sha256']
            assert np.array_equal(probs.numpy(),old[ident])
            audit[ident]=dict(route=status,posterior_sha256=hashed(probs))
            print(ident,status,flush=True)
    proof=dict(rows=audit,queries=len(audit),prefix_posteriors=6*len(audit),original_unmodified_clock_cases=sum(v['route']=='original-decoder' for v in audit.values()),
               wall_seconds=time.monotonic()-began,model_sha256=receipt['weights'])
    args.output.write_text(json.dumps(proof,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('weights','out','output'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--originals',type=Path,nargs='+',required=True)
    verify(p.parse_args())
