"""Lossless NumPy-only deployment packages; frozen training sources stay untouched."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from .joint_deploy import NumpyPolicy

TOP = ('schema', 'family', 'n_grid', 'public_dimensions', 'head_dimensions', 'coordinates', 'confusion')
NETWORK = ('w1', 'b1', 'w2', 'b2')
GRU = tuple(name+'.'+suffix for name in ('initial_hidden', 'recurrent', 'mass_decoder', 'bank1', 'bank2')
            for suffix in (('weight_ih', 'bias_ih', 'weight_hh', 'bias_hh') if name == 'recurrent' else ('weight', 'bias')))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path); raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:
        stream.write(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)
    return dict(sha256=sha(path), bytes=path.stat().st_size)


def project_artifact(artifact):
    """Symmetric minimal inference view: no float conversion, rounding or retraining."""
    packed = {key: deepcopy(artifact[key]) for key in TOP}
    packed['network'] = {key: deepcopy(artifact['network'][key]) for key in NETWORK}
    if artifact['family'] == 'gru':
        packed['core'] = dict(weights={key: deepcopy(artifact['core']['weights'][key]) for key in GRU})
    elif artifact['family'] in ('renewal', 'full_markov', 'affine_markov'):
        packed['core'] = dict(tables=[{key: deepcopy(row[key]) for key in ('dt', 'drive', 'matrix')}
                                      for row in artifact['core']['tables']])
    else:
        raise ValueError('unknown family')
    NumpyPolicy(packed)
    return packed


def exact(left, right, path=''):
    """Check every retained leaf, including IEEE-754 signed zero and integer types."""
    if type(left) is not type(right):
        raise AssertionError(('type changed', path))
    if isinstance(left, dict):
        assert left.keys() == right.keys(), path
        for key in left: exact(left[key], right[key], path+'/'+str(key))
    elif isinstance(left, list):
        assert len(left) == len(right), path
        for i, (a, b) in enumerate(zip(left, right)): exact(a, b, path+'/'+str(i))
    elif isinstance(left, float):
        assert np.float64(left).tobytes() == np.float64(right).tobytes(), path
    else:
        assert left == right, path


def fixture_rows():
    """Public-only, directly constructed histories; no packet/evaluator or cohort I/O."""
    from . import joint_task as task
    public = dict(schema=task.SCHEMA, id='package-public-fixture', deadline=6, initial_budget=3,
        target_tick=6, duration=[.25, .5, 1., 1.5, .5, .25], drive=[-1, 1, 0, -1, 1, 0],
        reliability=[.65, .85, .95, .55, .85, .65], read_price=[.03, .12, .01, .18, .03, .12],
        read_delay=[2, 1, 1, 2, 1, 1], latency_price=.025, repair_price=.03,
        failure_probability=.08, prior_distance=.375, packets=[f'packet_{i}.json' for i in range(6)],
        packet_sha256=['0'*64]*6)
    rows = []
    for bit in (0, 1):
        state = task.initial(public)
        for action in (2, 1, 1, 1, 1, 1):
            rows.append(dict(public=deepcopy(public), state=deepcopy(state)))
            due = task.due_request(public, state, action)
            completion = None if due is None else dict(observation_tick=due, observation=bit)
            state = task.successor(public, state, action, completion)
        rows.append(dict(public=deepcopy(public), state=deepcopy(state)))
    return rows


def validate_predictions(raw, packed, rows):
    original, slim = NumpyPolicy(raw), NumpyPolicy(packed)
    for row in rows:
        a, b = original.predict(row['public'], row['state']), slim.predict(row['public'], row['state'])
        exact(a, b)
    return dict(rows=len(rows), fields=['q', 'belief', 'mass', 'bank', 'logit'], exact=True)


def package_file(raw_path, slim_path, sidecar_path, expected_sha256, rows=None):
    if sha(raw_path) != expected_sha256: raise ValueError('frozen model hash mismatch')
    raw = read(raw_path); packed = project_artifact(raw)
    payload = write(slim_path, packed); reread = read(slim_path)
    exact(packed, reread)
    validation = validate_predictions(raw, reread, fixture_rows() if rows is None else rows)
    removed = {key: value for key, value in raw.items() if key not in packed}
    removed['core'] = {key: value for key, value in raw['core'].items() if key not in packed['core']}
    removed['network'] = {key: value for key, value in raw['network'].items() if key not in NETWORK}
    metadata = dict(schema='joint-numpy-package-provenance-v1', original_sha256=expected_sha256,
        original_bytes=Path(raw_path).stat().st_size, package=payload, validation=validation,
        package_source_sha256=sha(__file__), deployment_source_sha256=sha(Path(__file__).with_name('joint_deploy.py')),
        removed_provenance=removed, scope='NumPy deployment only; sidecar excluded from inference parse; no native qualification')
    sidecar = write(sidecar_path, metadata)
    return dict(original_sha256=expected_sha256, package=payload, sidecar=sidecar, validation=validation)


def derive_all(root, out, published_model_commit):
    root, out = Path(root), Path(out); frozen = read(root/'MODEL_FREEZE.json')
    if len(published_model_commit) != 40 or set(published_model_commit)-set('0123456789abcdef'):
        raise ValueError('published final model commit required')
    if len(frozen['models']) != 20: raise ValueError('all 20 frozen final models required')
    repository = Path(__file__).resolve().parents[3]
    if any(sha(repository/p) != h for p, h in frozen['sources'].items()): raise ValueError('frozen source mutated')
    if any(sha(root/p) != h for p, h in frozen['models'].items()): raise ValueError('frozen weights mutated')
    out.mkdir(parents=True, exist_ok=False)
    models = {}
    for relative, digest in sorted(frozen['models'].items()):
        target = out/relative
        models[relative] = package_file(root/relative, target, target.with_name('provenance.json'), digest)
    manifest = dict(schema='joint-numpy-package-freeze-v1', published_model_commit=published_model_commit,
        model_freeze_sha256=sha(root/'MODEL_FREEZE.json'), package_source_sha256=sha(__file__), models=models)
    write(out/'PACKAGE_FREEZE.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--published-model-commit', required=True)
    args = parser.parse_args()
    result = derive_all(args.root, args.out, args.published_model_commit)
    print(json.dumps(dict(models=len(result['models']), out=args.out)))


if __name__ == '__main__': main()
