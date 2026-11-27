"""Fixed-gallery three-seed differences after both independently selected long arms lock."""
import argparse, json
from pathlib import Path
import numpy as np

def main(data):
    long=data/'long';hy=data/'hybrid_long'
    result={}; seeds=(109,271,463)
    with np.load(long/'cold_ranks.npz') as base:
        for budget in (120,600,1800,3600,7200):
            with np.load(hy/f'cold-{budget}.npz') as warm:
                scores={}
                for method in ('hybrid','literal','smooth','linear','conventional'):
                    raw=[warm[str(s)] if method=='hybrid' else base[f'{method}/{s}/{budget}'] for s in seeds]
                    scores[method]=np.mean([(a[:,:,0]==1).mean(0) for a in raw],0)
                d={}
                for label,ref in [('hybrid','conventional'),('hybrid','literal'),('hybrid','linear'),('literal','conventional')]:
                    q=scores[label]-scores[ref];g=np.random.default_rng(220711)
                    boot=np.concatenate([q[g.integers(len(q),size=(100,len(q)))].mean(1) for _ in range(80)])
                    d[f"{label}-{ref}"]={'strict_R1_difference':float(q.mean()),'paired95':np.quantile(boot,[.025,.975]).tolist()}
                result[str(budget)]={'r1':{k:float(v.mean()) for k,v in scores.items()},'contrasts':d}
    (data/'time_matched_long_comparison.json').write_text(json.dumps(result,indent=1))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);main(p.parse_args().data)
