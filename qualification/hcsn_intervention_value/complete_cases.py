"""Prepare the complete-case input view using only a signed physical-media validity list."""
import argparse
import json
from pathlib import Path

import numpy as np

from . import frontend as f


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data_root',type=Path)
    p.add_argument('semantic',type=Path)
    p.add_argument('output',type=Path)
    args=p.parse_args(); root=args.data_root
    args.output.mkdir(parents=True,exist_ok=False)
    raw,semantic=(args.output/n for n in ('raw','semantic'))
    raw.mkdir();semantic.mkdir()
    for name in ('gallery','train','dev','retain'):
        (raw/(name+'.npz')).symlink_to((root/'features'/(name+'.npz')).resolve())
    roster=json.loads((root/'roster/test.json').read_text())
    path=root/'features/test.complete.npz';receipt=root/'receipts/test.complete.json'
    audit=json.loads(receipt.read_text())
    if f.digest(path) not in json.dumps(audit):raise ValueError('unbound complete-case file')
    d=f.load_raw(path);ids=d['query_id'].astype(str).tolist()
    if len(ids)!=len(set(ids)):raise ValueError('duplicate complete-case query')
    all_ids=[r['query_id'] for r in roster]
    omitted=sorted(set(all_ids)-set(ids))
    if any(n not in all_ids for n in ids) or len(ids)+len(omitted)!=len(all_ids):
        raise ValueError('invalid media subset')
    sem=args.semantic/'test.npz'
    with np.load(sem,allow_pickle=False) as z:
        names=z['query_id'].astype(str).tolist()
        if len(names)!=len(set(names)) or set(names)!=set(all_ids):raise ValueError('semantic roster mismatch')
        indexes={n:i for i,n in enumerate(names)}
        with (semantic/'test.npz').open('xb') as file:
            np.savez_compressed(file,query_id=np.asarray(ids),probability=z['probability'][[indexes[i] for i in ids]])
    (raw/'test.npz').symlink_to(path.resolve())
    f.dump(args.output/'validity_seal.json',dict(original_count=len(all_ids),eligible_count=len(ids),
         original_ids=all_ids,valid_ids=ids,omitted=omitted,media_validity_sha256=f.digest(receipt),
         original_roster=f.digest(root/'roster/test.json'),complete_raw=f.digest(path),
         full_semantic=f.digest(sem),complete_semantic=f.digest(semantic/'test.npz'),
         criterion='Objective original audio/video coverage. Scores and predictions do not select cases.'))


if __name__=='__main__':main()
