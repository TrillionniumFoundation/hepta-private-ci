"""Independent count of all original and corrected predictions without fitting."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('corrected',type=Path);p.add_argument('legacy',type=Path);a=p.parse_args()
    r=json.loads((a.corrected/'RESULTS.json').read_bytes());new_path=a.corrected/'cold.npz'
    assert sha(new_path)==r['corrected_cold_sha256'] and sha(a.legacy/'cold.npz')==r['original_cold_sha256']
    assert sha(a.corrected/'SEAL.json')==r['seal_sha256']
    with np.load(new_path) as n,np.load(a.legacy/'cold.npz') as o:
        y=n['y'];ids=n['repeat'];pp=n['corrected_lif'];groups=np.unique(ids)
        assert np.array_equal(o['time_ms'],n['time_ms']) and np.array_equal(o['repeat'],ids) and np.array_equal(o['y'],y)
        assert np.array_equal(o['lif'],n['legacy_replay'])
        loss=lambda p:-np.log(np.where(y,p,1-p))
        rand=np.random.default_rng(30588).integers(0,len(groups),size=(6000,len(groups)))
        for arm,metrics in r['corrected_minus_archived_loss'].items():
            d=loss(pp)-loss(o[arm]);v=np.array([d[ids==g].mean() for g in groups])
            assert np.allclose(v,metrics['repeats'],rtol=0,atol=1e-14)
            assert abs(v.mean()-metrics['balanced'])<1e-14 and abs(d.mean()-metrics['pooled'])<1e-14
            ci=np.quantile(v[rand].mean(1),[.025,.975]);assert np.allclose(ci,metrics['ci95'],atol=1e-14,rtol=0)
    print(len(pp),'corrected probabilities,',len(r['corrected_minus_archived_loss']),'matched models and paired intervals verified')


if __name__=='__main__':main()
