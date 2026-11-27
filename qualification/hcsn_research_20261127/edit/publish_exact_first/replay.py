"""Cold re-score a sealed selected network using only receiver density evolution."""
import argparse
import json
import sys
import time
from pathlib import Path
ENTRY=time.perf_counter()
import numpy as np
import torch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
sys.path.insert(1,str(HERE.parent/'command'))
import experiment as core
import study as sequential
import exact

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--seed',type=int,required=True)
    ap.add_argument('--stage',choices=['first','second'],required=True)
    for name in ('parents','input','command-data','prior','second','output'):
        ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args()
    torch.set_num_threads(1)
    model,c,_=core.read_parent(a)
    name='direct' if a.stage=='first' else 'secant'
    source=a.prior if a.stage=='first' else a.second
    p=source/str(a.seed)/name
    seal=json.loads((source/'seal.json').read_text())
    assert core.sha((p/'selected.pt').read_bytes())==seal['models'][f'{a.seed}/{name}']
    candidate=torch.load(p/'selected.pt',weights_only=True,map_location='cpu')
    model.load_state_dict(candidate['model'],strict=True)
    test=(core.loads(a,'test',c) if a.stage=='first' else {'cmd':sequential.parts(a,'test',c)['cmd']})
    before=time.perf_counter()
    dest=a.output/str(a.seed)
    dest.mkdir(exist_ok=True,parents=True)
    results={};arrays={}
    with np.load(p/'predictions.npz',allow_pickle=False) as original:
        for k,(x,y,ids) in test.items():
            ys=exact.scores(model,c,x)
            labels=ys.argmax(1).numpy()
            z=ys.float().numpy()
            ref=original[k+'_scores']
            assert np.array_equal(ids,original[k+'_id'])
            col=k+('_class' if a.stage=='first' else '_pred')
            results[k]=dict(count=len(ids),max_abs=float(np.abs(z-ref).max()),disagreement=int((labels!=original[col]).sum()),
                            first_original_bytewise_scores_equal=bool(np.array_equal(z,ref)),
                            accuracy=float((labels==y.numpy()).mean()),raw_scores_with_id_sha256=core.sha(ids.tobytes()+z.tobytes()))
            arrays.update({k+'_scores':z,k+'_pred':labels,k+'_ids':ids,k+'_y':y.numpy()})
    artifact=dest/(a.stage+'-predictions.npz')
    np.savez_compressed(artifact,**arrays)
    results.update(scoring_s=time.perf_counter()-before,cold_total_s=time.perf_counter()-ENTRY,
                   protocol=core.sha((HERE/'PROTOCOL.md').read_bytes()),source_selected=seal['models'][f'{a.seed}/{name}'],
                   source_raw=core.sha((p/'predictions.npz').read_bytes()),raw_sha256=core.sha(artifact.read_bytes()),
                   pass_gate=all(x['max_abs']<=1e-4 and x['disagreement']==0 for x in results.values()))
    core.write(dest/(a.stage+'-replay.json'),results)
    print(a.seed,a.stage,results,flush=True)
if __name__=='__main__':main()
