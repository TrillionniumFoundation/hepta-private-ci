"""Re-score the two real cohorts from frozen action rows without importing Torch."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)


def verify(folder):
    train = json.loads((folder / 'train.json').read_text())
    test = json.loads((folder / 'test.json').read_text())
    assert sha(folder / 'predictions.npz') == test['predictions_sha256']
    assert train['sealed_sha256'] == test['sealed_sha256'] == sha(folder / 'seal.json')
    assert set(test['arms']) == {'KEEP', 'inverse', 'same_BP', 'wide_BP', 'ridge'}

    groups = train.get('groups')
    fitted = (groups or train['group_ids'])[:3]
    held_out = test['test_groups']
    expected_count = 21 if groups is not None else 9
    assert len(held_out) == expected_count
    if groups is not None:
        assert sorted(groups[3]) == sorted(held_out)
    flattened = sum(fitted, []) + held_out
    assert len(flattened) == len(set(flattened))

    with np.load(folder / 'predictions.npz', allow_pickle=False) as archive:
        subjects = archive['subjects']
        free, paid = archive['free_correct'], archive['paid_correct']
        assert np.array_equal(np.unique(subjects), np.array(held_out))
        assert len(subjects) == test['test_n']
        for values in (free, paid):
            assert np.isin(values, [0, 1]).all()
        def per_person(values):
            return np.array([values[subjects == who].mean() for who in held_out])
        close(per_person(free).mean(), test['free_accuracy'])
        close(per_person(paid).mean(), test['paid_accuracy'])
        close(per_person(np.maximum(free, paid - 0.1)).mean(), test['oracle_new'])
        for arm, report in test['arms'].items():
            buy, keep = archive[arm], archive['KEEP']
            assert np.isin(buy, [0, 1]).all()
            close(per_person(buy).mean(), report['buy_rate'])
            for price, name in ((0.10, 'new'), (0.45, 'old')):
                score = per_person(np.where(buy, paid - price, free))
                baseline = per_person(np.where(keep, paid - price, free))
                delta = score - baseline
                close(score.mean(), report[name + '_utility'])
                close(delta.mean(), report[name + '_delta'])
                close(delta.min(), report['worst_' + name])
                close(delta, [row['delta_' + name] for row in report['per_subject']])
                if name == 'new':
                    rng = np.random.default_rng(20261126)
                    row_ix = rng.integers(len(delta), size=(10000, len(delta)))
                    interval = np.quantile(delta[row_ix].mean(axis=1), [.025, .975])
                    close(interval, report['bootstrap95'])
            passed = report['new_delta'] > 0 and report['bootstrap95'][0] > 0 and report['worst_old'] >= -.05 - 1e-12
            assert passed == report['pass_all']
    timing = folder / 'cold.json'
    if timing.exists():
        rows = json.loads(timing.read_text())
        expected = {(arm, repeat) for arm in test['arms'] for repeat in range(3)}
        assert len(rows) == len(expected)
        assert {(r['arm'], r['repeat']) for r in rows} == expected
        assert all(r['identical_to_original'] and r['process_seconds'] >= r['fit_select_seconds'] >= 0 for r in rows)
    print(f'Verified seals, five decisions, participant-level utilities and intervals on {expected_count} held-out people.')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
