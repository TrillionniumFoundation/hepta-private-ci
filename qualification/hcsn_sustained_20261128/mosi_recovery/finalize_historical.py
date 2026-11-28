"""Finalize the matching historical scores, preserving the original prediction archives."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def audit(task):
    sys.path.insert(0, str(task / 'source'))
    from verify import summary
    from cold import derangement

    run = task / 'candidate_replay'
    hist = json.loads((task / 'source/SEAL.json').read_text())
    checks = json.loads((run / 'candidate_hash_seal.json').read_text())
    assert checks['historical_seal_sha256'] == sha(task / 'source/SEAL.json')
    with np.load(task / 'reconstructed/test.npz') as test:
        y, clip, video = test['y'], test['clip'], test['video']
    assert sha(task / 'reconstructed/test.npz') == hist['test_input_sha256']
    assert len(y) == 686 and len(np.unique(video)) == 31
    def score(pred):
        if np.ptp(pred) != 0:
            return summary(pred, y, video)
        with np.errstate(invalid='ignore', divide='ignore'):
            stats = summary(pred, y, video)
        stats.update(pearson=None, calibration_slope=None)
        return stats
    results = {}
    attempted = 0
    expected = {'intact', 'y', 'clip', 'video'}
    for mod in ('text', 'audio', 'vision', 'av'):
        expected.add('drop_' + mod)
        expected.update(f'swap_{mod}_{i}' for i in range(3))
    for row in checks['rows']:
        for obj in row['objects']:
            attempted += 1
            key = obj['name']
            w = run / 'fits' / key
            assert sha(w) == obj['reconstructed']
            assert obj['match'] == (sha(w) == hist['weights'].get(key))
            if not obj['match']:
                continue
            f = run / (key + '.cold.npz')
            with np.load(f, allow_pickle=False) as z:
                assert set(z.files) == expected
                for k, a in [('y', y), ('clip', clip), ('video', video)]:
                    assert np.array_equal(z[k], a)
                assert all(z[k].shape == y.shape and np.isfinite(z[k]).all()
                           for k in expected - {'clip', 'video'})
                results[key] = {'score_sha256': sha(f), 'archived_weight_sha256': sha(w),
                                'intact': score(z['intact']), 'drop_AV': score(z['drop_av']),
                                'scope': 'Exact checkpoint scored on sealed inputs; original fit wall timestamps unavailable'}
    for seed in (21901, 65741, 89303):
        perm = derangement(video, seed)
        assert len(np.unique(perm)) == len(y) and np.all(video != video[perm])
    final = {'source_branch': 'research/hcsn-mosi-three-stream-20261127-e0bf',
             'original_seal_sha256': sha(task / 'source/SEAL.json'),
             'hash_comparison_seal_sha256': sha(run / 'candidate_hash_seal.json'),
             'candidate_groups': len(checks['rows']), 'eligible_objects': len(results),
             'attempted_objects': attempted, 'authenticated_cold_results': results,
             'recovered_historical_fit_histories': sum(r['historical_fit_history_recovered'] for r in checks['rows']),
             'score_source_scope': 'Only byte-identical historical weights scored on authenticated cold data.',
             'summary_fix': 'Original prediction files retained unchanged. A constant drop-AV prediction has undefined Pearson and calibration slope. These descriptive metrics are encoded as JSON null.',
             'summary_fix_source_sha256': sha(Path(__file__))}
    out = run / 'reconstruction_result.json'
    body = json.dumps(final, indent=2, allow_nan=False) + '\n'
    if out.exists():
        assert out.read_text() == body
    else:
        tmp = out.with_suffix('.finalized'); tmp.write_text(body); tmp.replace(out)
    print('reconstructed', attempted, 'byte_identical', len(results), 'receipt', sha(out), flush=True)
    for key, values in results.items():
        if '413' in key:
            print(key, 'intact_video_mae', values['intact']['video_mae'], 'drop_av', values['drop_AV']['video_mae'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    audit(parser.parse_args().root.resolve())
