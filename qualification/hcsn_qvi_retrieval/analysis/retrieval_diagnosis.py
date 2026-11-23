"""Descriptive identification of free/paid outcomes after held-out confirmation."""
import argparse
import json
from pathlib import Path

import numpy as np


def describe(shard):
    with np.load(shard,allow_pickle=False) as z:
        label,dt,scores,paid = (z[k] for k in ('target','dt','scores','read_scores'))
    free = scores.argmax(-1) == label[:,None]
    fused = paid.argmax(-1) == label[:,None]
    elapsed = dt.cumsum(1)-dt[:,:1]
    discount = np.exp(-.2*elapsed)
    delay_cost = 2*np.expm1(-.2*elapsed)
    uf = free*discount + delay_cost
    uv = (fused-.3)*discount + delay_cost
    all_best = np.maximum(uf,uv).max(1)
    audio_best = uf.max(1)
    return dict(episodes=len(free),horizon=free.shape[1],free_correct_by_prefix=free.sum(0).tolist(),
                paid_correct_by_prefix=fused.sum(0).tolist(),
                video_fixes_free_error_by_prefix=(fused&~free).sum(0).tolist(),
                video_breaks_free_hit_by_prefix=(free&~fused).sum(0).tolist(),
                fixed_exit_free_utility=uf.mean(0).tolist(),fixed_exit_paid_utility=uv.mean(0).tolist(),
                hindsight_free_only_utility=float(audio_best.mean()),hindsight_with_paid_utility=float(all_best.mean()),
                episodes_with_strict_paid_increment=int((all_best>audio_best+1e-12).sum()),
                minimum_first_to_correct_wait_steps=[int(np.where(row)[0][0]) if row.any() else None for row in free],
                scope='Post-confirmation descriptive ablation of this fixed matcher and price. Perfect foresight takes maximum per episode over all prefixes, independent from Bellman recursion.')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('shard',type=Path)
    print(json.dumps(describe(p.parse_args().shard),indent=2,allow_nan=False))
