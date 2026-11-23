"""Fit exactly one purchase edit on the old TRAIN panel. This entry point opens TRAIN outcomes only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

import numpy as np
from bounded_optimizer import discover, UNIT
from qualification.hcsn_blocker_followup import metrics, readout_edit
from qualification.hcsn_intervention_value import frontend

HERE = Path(__file__).resolve().parent
QUAL = HERE.parents[1]


def historical_inputs(split):
    base = QUAL / 'hcsn_blocker_followup/evidence'
    manifest = json.loads((base / 'archive_manifest.json').read_text())['archives']
    hashes = {}
    def read(archive, member, expected):
        with ZipFile(archive) as z:
            blob = z.read(member)
        actual = hashlib.sha256(blob).hexdigest()
        if actual != expected:
            raise ValueError(f'Invalid member {member}')
        hashes[member] = actual
        return blob
    def member(kind, suffix):
        name = f'media/{kind}/{split}.{suffix}'
        (archive, sig), = [(a, v['files'][name]['sha256']) for a,v in manifest.items() if name in v['files']]
        return read(base/archive, name, sig)
    def arrays(data):
        with np.load(io.BytesIO(data), allow_pickle=False) as a:
            return dict(a)
    protocol = json.loads((HERE / 'protocol.json').read_text())['frozen_sha256']
    front = json.loads(read(QUAL/'hcsn_intervention_value/evidence/records-04.zip', 'primary/discovery/front_weights.json', protocol['audio_gallery']))
    fit = json.loads(read(base/'locked_heads.zip', 'fit.json', protocol['old_source_svd']))['full-svd-.1']
    raw = arrays(member('features','npz'))
    camera = arrays(member('semantic','npz'))
    roster = json.loads(member('roster','json'))
    assert set(raw['split'].tolist()) == {split}
    expected = {r['query_id']:(int(r['label']),str(r['group'])) for r in roster}
    assert expected == {i:(int(y),str(g)) for i,y,g in zip(raw['query_id'],raw['label'],raw['group'],strict=True)}
    photo = dict(zip(camera['query_id'].tolist(),camera['probability'],strict=True))
    assert len(photo) == len(roster) and set(photo) == set(expected)
    paid = np.stack([photo[i] for i in raw['query_id']])
    state = frontend.candidate(frontend.render(raw, front['final'], front['reference'], paid), 'imagenet_visual')
    x = readout_edit.matrix(state, fit)
    w = np.r_[fit['beta'],fit['bias']]
    free_hit = state['scores'][:,0].argmax(-1) == state['target']
    paid_hit = state['read_scores'][:,0].argmax(-1) == state['target']
    return x,w,state,free_hit,paid_hit,hashes


def fit_train():
    start = perf_counter()
    x,w,state,f,p,hashes = historical_inputs('train')
    before = perf_counter()
    edit = discover(x,w,state,f,p,0.10001)
    end = perf_counter()
    gap = x @ (w + np.array(edit)/UNIT) - 0.30
    result = metrics.evaluate(state, gap>0)
    assert sum(map(abs,edit)) <= UNIT and min(abs(gap)) >= 0.10 and result['worst_delta_free'] >= -1e-12
    return dict(fit_partition='train', inputs=hashes, code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), HERE/'bounded_optimizer.py')},
                edit_unit='1/1000000000', edit_numerators=edit, training_windows=len(gap), training_sources=len(set(state['group'])),
                preprocessing_seconds=before-start, fitting_seconds=end-before, elapsed_through_train_validation_seconds=perf_counter()-start,
                training_min_margin=float(min(abs(gap))), training=result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    result=fit_train()
    with args.output.open('x') as stream:
        json.dump(result,stream,sort_keys=True,indent=2)
        stream.write('\n')
