"""Test deterministic, complete original recipes against the historical selected-weight hashes.

The original development timing histories cannot be reconstructed from SHA-256.
This program never passes rewritten or newly timed histories off as the old ones.
Only byte-identical weights are eligible for a historical checkpoint cold score.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
SEEDS=(413,677,941)


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temp.replace(path)


def run():
    import numpy as np
    import torch
    if os.getenv('PYTHONOPTIMIZE'):raise ValueError('original checks require default interpreter')
    data=HERE/'reconstructed';src=HERE/'source';root=HERE/'candidate_replay';root.mkdir(exist_ok=True)
    original=json.loads((src/'SEAL.json').read_text())
    original_data=json.loads((src/'data.json').read_text())
    for s in ('train','valid','test'):
        if sha(data/(s+'.npz'))!=original_data['splits'][s]['sha256']:raise ValueError('prepared source hash')
    sys.path.insert(0,str(src))
    from models import model,SEEDS,modalities,predict,SLICES
    from cold import derangement
    from verify import summary
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    stage=[(0,a) for a in ('raw_all','raw_text','raw_av')]+[(64,a) for a in ('fp_h','fp_h_text','fp_h_shuffle','fp_r','random_h')]
    status=root/'matching.json';rows=[]
    for w,arm in stage:
        for seed in SEEDS:
            key=f'{w}-{arm}-{seed}';folder=root/'fits';folder.mkdir(exist_ok=True)
            if not (folder/(key+'.json')).exists():
                subprocess.run([sys.executable,str(src/'train.py'),str(data),str(src/'law.npz'),str(folder),
                                str(w),arm,str(seed)],check=True)
            fs=sorted(folder.glob(key+'-r*.pt'))
            records=[]
            for p in fs:
                h=sha(p);same=original['weights'].get(p.name)==h
                records.append({'name':p.name,'reconstructed':h,'frozen':original['weights'].get(p.name),'match':same})
            rows.append({'width':w,'arm':arm,'seed':seed,'objects':records,
                         'historical_fit_history_recovered':sha(folder/(key+'.json'))==original['fits'][key+'.json']})
            write(status,{'stage':'fitting_by_train_and_validation_only','rows':rows,'historical_seal_sha256':sha(src/'SEAL.json')})
    sealed={'source_sha256':sha(Path(__file__)),'historical_seal_sha256':sha(src/'SEAL.json'),'torch':str(torch.__version__),
            'numpy':np.__version__,'rows':rows,'status':'reconstructed candidates compared before test-scoring'}
    seal=root/'candidate_hash_seal.json';write(seal,sealed)
    eligible=[(r,k) for r in rows for k in r['objects'] if k['match']]
    results={}
    if eligible:
        with np.load(data/'test.npz') as f:
            x=torch.from_numpy(f['x']);y=f['y'];clip=f['clip'];vid=f['video']
        for row,obj in eligible:
            key=obj['name'];p=root/'fits'/key
            if sha(p)!=obj['frozen']:raise ValueError('selected weight changed')
            net=model(row['width'],row['arm'],src/'law.npz');net.load_state_dict(torch.load(p,weights_only=True))
            base=modalities(x,row['arm']);z=predict(net,base);vectors={'intact':z,'y':y,'clip':clip,'video':vid}
            for name,sl in {**SLICES,'av':slice(768,793)}.items():
                alt=base.clone();alt[...,sl]=0
                vectors['drop_'+name]=predict(net,alt)
                for j,seed in enumerate((21901,65741,89303)):
                    perm=derangement(vid,seed)
                    alt=base.clone();alt[...,sl]=base[perm][...,sl]
                    vectors[f'swap_{name}_{j}']=predict(net,alt)
            out=root/(key+'.cold.npz');np.savez_compressed(out,**vectors)
            results[key]={'score_sha256':sha(out),'archived_weight_sha256':obj['frozen'],
                          'intact':summary(z,y,vid),'drop_AV':summary(vectors['drop_av'],y,vid),
                          'scope':'Exact checkpoint scored on sealed inputs; original fit wall timestamps unavailable'}
    final={'source_branch':'research/hcsn-mosi-three-stream-20261127-e0bf','original_seal_sha256':sha(src/'SEAL.json'),
           'hash_comparison_seal_sha256':sha(seal),'candidate_groups':len(rows),'eligible_objects':len(eligible),
           'attempted_objects':sum(len(r['objects']) for r in rows),'authenticated_cold_results':results,
           'recovered_historical_fit_histories':sum(r['historical_fit_history_recovered'] for r in rows),
           'score_source_scope':'No unverified reconstructed weights enter historical cold scoring.'}
    write(root/'reconstruction_result.json',final);print('terminal',len(eligible),sha(root/'reconstruction_result.json'),flush=True)


if __name__=='__main__':run()
