"""Verify recovered file hashes, scores, immutable source bindings and all 16 cold arrays."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import runpy
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'original'
ARMS = ('literal', 'smooth', 'lif', 'sdpa')
MODES = ('aligned', 'video_swapped', 'audio_swapped', 'both_swapped')


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric_differences(a, b, out):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            numeric_differences(a[key], b[key], out)
    elif isinstance(a, list):
        assert len(a) == len(b)
        for left, right in zip(a, b):
            numeric_differences(left, right, out)
    elif type(a) in (int, float):
        assert type(b) in (int, float)
        assert np.isfinite(a) and np.isfinite(b)
        out.append(abs(a-b))
    else:
        assert a == b


def verify():
    expected = read(RAW/'SUMMARY.json')
    seal = read(RAW/'seal.json')
    identity = read(ROOT/'source_and_checkpoints.json')
    assert sha(RAW/'SUMMARY.json') == '1120cf42a453fde43cb73d497fae48a32da4a9a85cd128bf4a549b8576e08404'
    assert expected['seal_sha256'] == sha(RAW/'seal.json')
    assert seal['source'] == sha(RAW/'scripts/cpu_quality.py')
    assert seal['data'] == identity['data_source']['data']['sha256']
    checkpoints = {(w['arm'],w['step']): w for w in identity['weights']}
    assert len(checkpoints) == 8 and all(w['matches_sealed'] for w in checkpoints.values())
    arm_files = {}
    first_ids = first_labels = None
    for arm in ARMS:
        folder = RAW/'fits'/arm
        fit = read(folder/'fit.json')
        assert sha(folder/'fit.json') == seal['fits'][arm]
        assert fit['seed'] == 137 and fit['width'] == 4096
        assert [s['step'] for s in fit['train_steps']] == list(range(1,17))
        assert fit['train_steps'] == read(folder/'steps.json')
        assert fit['observations'] == read(folder/'observations.json')
        assert [s['step'] for s in fit['observations']] == [0,4,16]
        for row in fit['observations']:
            step = row['step']
            assert sha(folder/f'panel-{step}.npz') == row['panel_sha256']
            if step:
                assert row['weights_sha256'] == checkpoints[(arm,step)]['sha256']
        assert sha(folder/'full-dev-16.npz') == fit['observations'][-1]['full_dev_sha256']
        selected = min(fit['observations'][1:], key=lambda s:s['panel']['aligned']['nll'])['step']
        c = RAW/'cold'/arm
        cold = read(c/'result.json')
        assert fit['selected_step'] == cold['step'] == selected
        assert sha(c/'logits.npz') == cold['sha256']
        with np.load(c/'logits.npz',allow_pickle=False) as arrays:
            ids = arrays['ids']
            labels = arrays['labels']
            assert len(set(ids)) == len(ids) == 1311
            assert len({s.split('_')[0] for s in ids}) == 16
            assert len(np.unique(labels)) == 72
            if first_ids is None:
                first_ids, first_labels = ids.copy(), labels.copy()
            assert np.array_equal(ids, first_ids) and np.array_equal(labels, first_labels)
            for m in MODES:
                assert arrays[m].shape == (1311,72) and np.isfinite(arrays[m]).all()
                assert np.mean(arrays[m].argmax(1) == labels) == cold['metrics'][m]['top1']
        arm_files[arm] = dict(fit_sha256=sha(folder/'fit.json'),cold_sha256=sha(c/'result.json'),
                              logits_sha256=sha(c/'logits.npz'),selected=selected)
    with TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for name in ('fits','cold','seal.json'):
            (stage/name).symlink_to(RAW/name)
        scorer = runpy.run_path(str(RAW/'scripts/recount_cpu.py'))
        scorer['main'](stage)
        observed = read(stage/'SUMMARY.json')
        delta = []
        numeric_differences(expected,observed,delta)
        assert max(delta) < 1e-12
        replay = dict(scalar_numeric_entries=len(delta),maximum_abs_error=max(delta),
                      summary_bytewise_identical=sha(stage/'SUMMARY.json')==sha(RAW/'SUMMARY.json'),
                      this_replay_sha256=sha(stage/'SUMMARY.json'))
    return dict(arms=arm_files,development_logit_archives=16,cold_archives=4,
                cold_variants_per_arm=4,cold_logits=4*4*1311*72,
                on_host_checkpoints=8,on_host_checkpoint_bytes=sum(w['bytes'] for w in checkpoints.values()),
                original_scorer_replay=replay,numpy=np.__version__,python=sys.version.split()[0])


if __name__ == '__main__':
    print(json.dumps(verify(),indent=2,allow_nan=False))
