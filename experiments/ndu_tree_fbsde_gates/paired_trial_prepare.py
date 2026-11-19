"""Freeze disjoint synthetic paired-learning rows; future data contain no worlds.

Evaluation secrets are intentionally *not* generated here. This is a synthetic
mechanism qualification, not an independent natural-data source.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from random import Random
from paired_continuation import generate_public,world_for_training,digest,canon


def prepare(*,n_train=4096,n_future=512):
    train=generate_public('train',seed=801, count=n_train)
    f1=generate_public('future_1',seed=1801,count=n_future)
    f2=generate_public('future_2',seed=2801,count=n_future)
    seen=[{r['group_id'] for r in arr} for arr in (train,f1,f2)]
    if seen[0]&seen[1] or seen[0]&seen[2] or seen[1]&seen[2]:
        raise ValueError('inter-cohort source identity overlap')
    rng=Random(314159)
    train_worlds=[list(world_for_training(r,rng=rng)) for r in train]
    return {"train_rows":train,"train_worlds":{"train_rows_sha256":digest(train),"worlds":train_worlds},
            "future_1":f1,"future_2":f2}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--output-dir',required=True)
    a.add_argument('--train-count',type=int,default=4096)
    a.add_argument('--future-count',type=int,default=512)
    cfg=a.parse_args()
    folder=Path(cfg.output_dir)
    if not folder.exists() or not folder.is_dir():
        raise ValueError('pre-existing private output dir required')
    data=prepare(n_train=cfg.train_count,n_future=cfg.future_count)
    for name,value in data.items():
        with (folder/(name+'.json')).open('x',encoding='utf-8') as f:
            f.write(canon(value)+'\n')
    print(canon({"created":[str(folder/(k+'.json')) for k in data],
                "future_worlds_generated":False,"authority":"DENY_ALL"}))

if __name__=='__main__':
    main()
