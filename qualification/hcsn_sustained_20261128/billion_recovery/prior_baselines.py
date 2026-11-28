"""Reconstruct class-count comparisons from the SHA-bound source dataset."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main(path):
    with path.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest() == '18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad'
    with np.load(path, allow_pickle=False) as d:
        y, splits = d['labels'], d['split']
    train = np.flatnonzero(splits == 0)
    held = y[splits == 2]
    rng = np.random.default_rng(137+7369)
    draw = np.concatenate([rng.choice(train,16) for _ in range(16)])
    for label, rows, smooth in [('4_steps',draw[:64],1),('16_steps',draw,1),('all_training_labels',train,0)]:
        counts = np.bincount(y[rows],minlength=72)
        p = (counts+smooth) / (len(rows)+72*smooth)
        ties = np.flatnonzero(counts == counts.max())
        prediction = ties.min()
        print(json.dumps(dict(source=label,training_presentations=len(rows),
                              distinct_clips=len(np.unique(rows)),distinct_classes=int((counts>0).sum()),
                              tie_ids=ties.tolist(),prediction=int(prediction),
                              mean_nll=float(-np.log(p[held]).mean()),
                              joint_accuracy=float((held==prediction).mean()),
                              correct=int((held==prediction).sum()))))


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('data',type=Path)
    main(args.parse_args().data)
