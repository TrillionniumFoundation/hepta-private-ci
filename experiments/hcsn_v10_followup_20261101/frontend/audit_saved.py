"""Independent saved-arithmetic audit; no fitter/model/metric imports."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    with np.load(path, allow_pickle=False) as z:
        return {k:z[k].copy() for k in z.files}


def audit(root):
    checked, candidates_seen, predictions_seen = 0, 0, 0
    data_root=Path(__file__).resolve().parents[3]/'recovered/v3/experiments/hcsn_task_value_v1/results/async_frontend001/data'
    raw={name:load(data_root/(('validation' if name=='val' else name)+'.npz')) for name in ('train','val','test')}
    selections = json.loads((root/'SELECTION_COMPLETE.json').read_text())
    roles = json.loads((root/'DEVELOPMENT_ROLES.json').read_text())
    assert not set(roles['train']['actors']) & set(roles['val']['actors'])
    for modality in ('audio','video','av'):
        directory = root/modality
        candidates = json.loads((directory/'CANDIDATES.json').read_text())
        winner = min(candidates, key=lambda r:r['validation']['nll'])
        assert winner['id'] == selections[modality]['id']
        assert digest(directory/'selected.npz') == selections[modality]['selected_sha256']
        selected=load(directory/'selected.npz')
        chosen=load(directory/(winner['id']+'.npz'))
        assert set(selected)==set(chosen) and all(np.array_equal(selected[k],chosen[k]) for k in selected)
        for row in candidates:
            modelpath = directory/(row['id']+'.npz')
            assert digest(modelpath) == row['checkpoint_sha256']
            model = load(modelpath)
            train = load(directory/(row['id']+'-train.npz'))
            z = model['training_features']
            dot = z@z.T
            if str(model['kernel']) == 'linear':
                gram = dot
            else:
                distances = ((z[:,None,:]-z[None,:,:])**2).sum(-1)
                gram = np.exp(-float(str(model['kernel'])[3:])*distances)
            target = np.eye(6)[train['labels']]
            assert np.max(np.abs(model['prior']-target.mean(0))) < 1e-14
            residual = (gram+float(model['alpha'])*np.eye(len(z)))@model['dual']-(target-model['prior'])
            assert np.max(np.abs(residual)) < 1e-8
            logits = gram@model['dual']+model['prior']
            p = np.exp(logits-logits.max(1,keepdims=True))
            p /= p.sum(1,keepdims=True)
            assert np.max(np.abs(p-train['probabilities'])) < 1e-10
            candidates_seen += 1
            checked += 4
        for path in directory.glob('*-*.npz'):
            if not ('-train.npz' in path.name or '-val.npz' in path.name or path.name.startswith(('selected-prefix','legacy-prefix'))):
                continue
            prediction = load(path)
            p, y = prediction['probabilities'], prediction['labels']
            assert p.shape == (len(y),6) and np.isfinite(p).all() and np.all(p>=0)
            assert np.max(np.abs(p.sum(1)-1)) < 1e-12
            assert len(set(prediction['recording_ids'])) == len(y)
            split = 'train' if path.stem.endswith('-train') else 'val' if path.stem.endswith('-val') else 'test'
            assert np.array_equal(prediction['recording_ids'],raw[split]['clip_ids'])
            assert np.array_equal(prediction['actor_ids'],raw[split]['actors'])
            assert np.array_equal(y,raw[split]['labels'])
            if split != 'test':
                assert prediction['recording_ids'].tolist() == roles[split]['recordings']
                assert prediction['actor_ids'].tolist() == roles[split]['actors']
            if '-train' in path.stem or '-val' in path.stem:
                matching = next((r for r in candidates if path.stem.startswith(r['id']+'-')),None)
                if matching:
                    key = 'train' if split=='train' else 'validation'
                    m = matching[key]
                    actual = {'n':len(y),'correct':int(np.sum(p.argmax(1)==y)),
                              'accuracy':float(np.mean(p.argmax(1)==y)),
                              'nll':float(np.mean(-np.log(p[np.arange(len(y)),y]))),
                              'brier':float(np.mean(np.sum((p-np.eye(6)[y])**2,axis=1)))}
                    assert all(abs(m[k]-v)<1e-12 for k,v in actual.items())
            predictions_seen += 1
            checked += 8
    return {'status':'PASS','candidates':candidates_seen,'prediction_files':predictions_seen,
            'assertion_groups':checked,'auditor_sha256':digest(Path(__file__)),'scope':'All saved weights/normal-equation residuals/train predictions, selection, candidate metrics, probability validity and development role IDs; no independent decoding, future cohort, feature-encoder, scientific quality or energy qualification.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.directory)
    with args.out.open('x') as f:
        json.dump(result,f,indent=2)
        f.write('\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
