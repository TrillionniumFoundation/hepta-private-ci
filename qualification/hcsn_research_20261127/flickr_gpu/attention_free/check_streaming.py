"""Compare all-token logits and measured cache bytes for actual caption inputs."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

from study import ROOT, BASE, SEEDS, ARMS, Captioner, Samples, sha, write
from streaming import IncrementalCaptioner
import numpy as np
import torch


@torch.no_grad()
def measure(model,images,words,repeats):
    full=model(images,words)
    cache=IncrementalCaptioner(model)
    def streaming(detail=False):
        cache.begin_image(images)
        sizes=[cache.state_bytes()]
        out=[]
        for ids in words.unbind(1):
            out.append(cache.next_token(ids))
            if detail:sizes.append(cache.state_bytes())
        return torch.stack(out,dim=1),sizes
    st,space=streaming(True)
    error=float((st-full).abs().max())
    # Float32 GEMMs for one token can round differently from the batched matrix kernel.
    assert torch.isfinite(st).all() and torch.isfinite(full).all()
    def timed(f):
        out=[]
        for i in range(repeats):
            tic=time.perf_counter();f();out.append(time.perf_counter()-tic)
        return statistics.median(out)
    return dict(max_abs_logit_difference=error,within_float32_tolerance=error<3e-4,
        token_positions_exceeding_tolerance=int(((st-full).abs().amax(-1)>=3e-4).sum()),cache_bytes_after_image=space[0],
        cache_bytes_after_1_text=space[1],cache_bytes_after_15_text=space[15],cache_bytes_after_31_text=space[31],
        cache_per_photo_after_31_text=space[31]//len(images),
        median_all_logits_in_one_pass_seconds=timed(lambda:model(images,words)),
        median_image_prefill_then_31_single_token_logits_seconds=timed(streaming))


def main():
    origin=sys.argv[1];assert origin in ('random','selected')
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    manifest=json.loads((ROOT/'data/manifest.json').read_text());d=Samples(ROOT/'data','train',manifest)
    idx=np.asarray(sorted(range(len(d.pix)),key=lambda i:hashlib.sha256(b'hepta-causal-stream-audit-v1'+bytes(d.ids[i])).digest())[:8])
    im,tx=d.batch(idx,np.zeros(8,dtype=int),torch.device('cpu'));rows={}
    if origin=='selected':
        seal=json.loads((BASE/'results/seal.json').read_text());assert len(seal['states'])==18
    for arm in ARMS:
        for seed in SEEDS:
            model=Captioner(arm,seed).eval();k=f'{arm}-{seed}'
            if origin=='selected':
                ck=BASE/'results'/k/'selected.pt';assert sha(ck)==seal['states'][k]
                model.load_state_dict(torch.load(ck,map_location='cpu',weights_only=True))
            rows[k]={str(batch):measure(model,im[:batch],tx[:batch,:-1],3) for batch in (1,8)}
    out=dict(origin=origin,rows=rows,source=sha(Path(__file__).with_name('streaming.py')),
        certification=sha(Path(__file__)),interpretation='CPU float32. Cached dynamic tensor bytes only, excluding weights, workspace, scalar token position, outputs and PyTorch allocator overhead. 4 image positions followed by 31 supported text positions. Single-token serial and one-pass teacher-forced timings differ in workload.',
        sampled_training_ids_sha256=hashlib.sha256(d.ids[idx].tobytes()).hexdigest())
    write(BASE/f'streaming_{origin}.json',out)
    print('verified streaming',origin,len(rows),flush=True)


if __name__=='__main__':main()
