"""Post-outcome finite capacity check for threshold-only edits of the original first-date SVD."""
import hashlib
import io
import json
import math
from fractions import Fraction
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from qualification.hcsn_blocker_followup import metrics, selector
from qualification.hcsn_intervention_value import frontend

HERE = Path(__file__).resolve().parent
QUAL = HERE.parents[1]


def archived_bytes(archive, member, digest):
    with ZipFile(archive) as z:
        data = z.read(member)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(member)
    return data


def sign_probability(differences):
    nonzero = [value for value in differences if value]
    wins = sum(value > 0 for value in nonzero)
    return Fraction(sum(math.comb(len(nonzero), i) for i in range(wins, len(nonzero) + 1)), 2 ** len(nonzero))


def load_first_prefix():
    protocol = json.loads((HERE / 'protocol.json').read_text())
    frozen = protocol['frozen_sha256']
    front = json.loads(archived_bytes(QUAL / 'hcsn_intervention_value/evidence/records-04.zip', 'primary/discovery/front_weights.json', frozen['audio_gallery']))
    fit = json.loads(archived_bytes(QUAL / 'hcsn_blocker_followup/evidence/locked_heads.zip', 'fit.json', frozen['old_source_svd']))['full-svd-.1']
    with ZipFile(HERE / 'evaluation.zip') as z:
        sealed = json.loads(z.read('action-seal.json'))['files']
        for name, sig in sealed.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == sig
        assert hashlib.sha256(z.read('camera.npz')).hexdigest() == json.loads(z.read('camera-receipt.json'))['output_sha256']
        rows = json.loads(z.read('roster.json'))
        actions = json.loads(z.read('actions.json'))['svd']['action']
        def arrays(name):
            with np.load(io.BytesIO(z.read(name)), allow_pickle=False) as a:
                return dict(a)
        audio = arrays('audio.npz')['audio']
        free = arrays('free.npz')
        camera = arrays('camera.npz')
    source = np.array([r['group'] for r in rows])
    labels = np.array([r['label'] for r in rows])
    assert np.array_equal([r['query_id'] for r in rows], camera['query_id'])
    probabilities, standardized = frontend.classify(front['final']['audio'], audio)
    assert np.array_equal(probabilities, free['scores'])
    notes = np.random.default_rng(420111).normal(size=(standardized.shape[-1], 8))
    projected = standardized @ np.linalg.qr(notes, mode='reduced')[0]
    x = selector.visible(probabilities, free['gallery_audio'], projected)
    design = np.column_stack((np.clip((x-fit['mean'])/fit['std'], -5, 5), np.ones(len(x))))
    scores = design @ np.r_[fit['beta'], fit['bias']]
    assert np.array_equal(scores > 0.30, actions)
    yfree = probabilities[:, 0].argmax(-1) == labels
    ypaid = camera['probability'][:, 0].argmax(-1) == labels
    data = {'group': source, 'target': labels, 'scores': probabilities, 'read_scores': camera['probability']}
    return design, np.r_[fit['beta'], fit['bias']], data, yfree, ypaid, [r['query_id'] for r in rows]


def analyze():
    design, coefficients, data, yfree, ypaid, rows = load_first_prefix()
    scores = design @ coefficients
    source = data['group']
    normals = np.unique(scores)
    # With strict score > threshold, each group of tied scores enters at once.
    # Put one threshold below the minimum and one at each distinct observed value.
    cases = []
    for threshold in np.r_[np.nextafter(normals[0], -np.inf), normals]:
        buys = scores > threshold
        native = metrics.evaluate(data, buys)
        utility = np.where(buys, 10 * ypaid - 3, 10 * yfree)
        d_free, d_paid = [], []
        for group in sorted(set(source)):
            chosen = source == group
            size = int(chosen.sum())
            d_free.append(Fraction(int(np.sum((utility-10*yfree)[chosen])), 10*size))
            d_paid.append(Fraction(int(np.sum((utility-10*ypaid+3)[chosen])), 10*size))
        gain = [sum(d)/len(d) for d in (d_free, d_paid)]
        p = list(map(sign_probability, (d_free, d_paid)))
        floor = min(d_free)
        practical = 0 < int(buys.sum()) < len(rows) and min(gain) >= Fraction(3, 100) and floor >= -Fraction(1, 20)
        adopted = practical and min(p) <= Fraction(1, 40) and max(p) <= Fraction(1, 20)
        assert adopted == native['adopt']
        assert np.allclose([*map(float, gain), float(floor), *map(float, p)], [native['delta_free'], native['delta_paid'], native['worst_delta_free'], *native['one_sided_sign_p']], rtol=0, atol=1e-12)
        cases.append(dict(buys=int(buys.sum()), delta_free=str(gain[0]), delta_paid=str(gain[1]), worst_free=str(floor), p_free=str(p[0]), p_paid=str(p[1]), floor_pass=bool(floor >= -Fraction(1,20)), practical=bool(practical), adopted=bool(adopted)))
    oracle = metrics.evaluate(data, ypaid & ~yfree)
    oracle_keys = ('n', 'buy', 'utility', 'r1', 'delta_free', 'delta_paid', 'worst_delta_free', 'one_sided_sign_p', 'adopt')
    return dict(hindsight_outcome_upper_bound={k: oracle[k] for k in oracle_keys}, scope='Post-outcome descriptive capacity only. All outcomes were already public. Only the scalar intercept varies; fixed source SVD ranking, fixed actual purchase price 0.30.', cases=len(cases), distinct_scores=len(normals), both_mean_cutoffs=sum(min(Fraction(c['delta_free']), Fraction(c['delta_paid'])) >= Fraction(3,100) for c in cases), floor_pass=sum(c['floor_pass'] for c in cases), practical=sum(c['practical'] for c in cases), adopted=sum(c['adopted'] for c in cases), profiles=cases)


if __name__ == '__main__':
    print(json.dumps(analyze(), indent=2, sort_keys=True))
