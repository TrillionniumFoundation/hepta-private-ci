"""Reconstruct the fixed TRAIN-only readout and compare four released panels.

Run from any directory with NumPy and SciPy installed:
    python verify_train_return_independent.py > /tmp/independent.json
    cmp /tmp/independent.json train-return-independent.json

All paths are resolved from this script in a complete repository checkout.
"""
import json
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from math import comb
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from scipy.special import expit


STUDY = Path(__file__).resolve().parent
QUALIFICATION = STUDY.parent.parent
HISTORICAL = QUALIFICATION / 'hcsn_blocker_followup/evidence'
SEAL_SHA = '6ae738217ea463d48a5aac72b0b46c52dd9fdfabec4a3aed9e947cd20c340dae'
REFERENCES = {
    'fit.json': '5ab2265238dd1085e26e6c57bc2cf3f3d0f5a70b7128d30efe0eb546231a51de',
    'primary/discovery/front_weights.json': '8feca0900f68d8041a963b449b8b641f1d8b9bf747ad823a968f7efcf429bd66',
    'archive_manifest.json': 'f6d9d2a961e57d8d0e4be363c7feb250e6384737f3e3502568bc0c449c94bfb0',
    'audio.npz': 'f4d1cd97b64b80cd8dfee99b61d6bf5b6caa2c5bbe8e66d66251e7e33f660480',
    'roster.json': 'd4a0146197403ffe5e425e09593968329fde5db7e063f1add87df6ee190edcd9',
    'camera.npz': 'c72730270654a850e5c5939e327d24eeae3d6d2a04eec3fda349f8f83f14e5fb',
}
PRICE = Fraction(3, 10)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(blob, expected, label):
    require(sha256(blob).hexdigest() == expected, f'Digest mismatch for {label}')
    return blob


def member(path, name, expected):
    with ZipFile(path) as archive:
        blob = checked(archive.read(name), expected, name)
    if name.endswith('.npz'):
        with np.load(BytesIO(blob), allow_pickle=False) as npz:
            return {key: npz[key].copy() for key in npz.files}
    return json.loads(blob)


def frozen_design(raw_audio, front, svd):
    """Take the first physical prefix after rebuilding binary audio and gallery outputs."""
    audio = front['final']['audio']
    gallery = front['reference']['audio']
    standardized = np.clip((raw_audio - audio['center']) / audio['scale'], -8, 8)
    coefficients = np.asarray(audio['linear'])
    probability = expit(2 * (standardized @ coefficients[:-1] + coefficients[-1]))
    normalized_gallery = np.clip((raw_audio - gallery['center']) / gallery['scale'], -8, 8)
    distances = np.stack(
        [np.square(normalized_gallery - prototype).mean(axis=-1) for prototype in gallery['gallery']],
        axis=-1,
    )
    gallery_probability = expit(distances[:, :, 0] - distances[:, :, 1])[:, 0]
    probability = probability[:, 0]
    margin, gallery_margin = 2 * probability - 1, 2 * gallery_probability - 1
    generator = np.random.default_rng(420111)
    projection, _ = np.linalg.qr(generator.normal(size=(52, 8)), mode='reduced')
    features = np.column_stack((
        margin, abs(margin), margin**2, probability >= .5, gallery_margin, abs(gallery_margin),
        abs(margin - gallery_margin), margin * gallery_margin,
        (probability >= .5) != (gallery_probability >= .5), margin * abs(margin),
        (standardized @ projection)[:, 0, :],
    ))
    design = np.column_stack((np.clip((features - svd['mean']) / svd['std'], -5, 5),
                              np.ones(len(features))))
    free_rank = np.column_stack((1 - probability, probability)).argmax(axis=1)
    return design, free_rank


def sign_probability(contrasts):
    total = sum(x != 0 for x in contrasts)
    positive = sum(x > 0 for x in contrasts)
    return Fraction(sum(comb(total, j) for j in range(positive, total + 1)), 2**total)


def score(raw, camera, roster, front, svd, edit):
    ids = raw['query_id'].tolist()
    camera_ids = camera['query_id'].tolist()
    by_id = {row['query_id']: row for row in roster}
    require(len(ids) == len(roster) == len(camera_ids) == len(set(ids)) == len(by_id),
            'Duplicate or missing roster row')
    require(set(ids) == set(by_id) == set(camera_ids), 'Mismatched query IDs')
    label = np.array([by_id[key]['label'] for key in ids])
    groups = [by_id[key]['group'] for key in ids]
    require(np.array_equal(label, raw['label']) and groups == raw['group'].tolist(),
            'Mismatched targets or groups')
    design, free_rank = frozen_design(raw['audio'], front, svd)
    paid_rank = camera['probability'][[camera_ids.index(key) for key in ids], 0, :].argmax(axis=1)
    coefficients = [Fraction(float(v)) + d
                    for v, d in zip([*svd['beta'], svd['bias']], edit, strict=True)]
    margins = [sum(Fraction(float(x)) * coef for x, coef in zip(row, coefficients, strict=True)) - PRICE
               for row in design]
    rows = {}
    for i, query_id in enumerate(ids):
        free_hit = bool(free_rank[i] == label[i])
        paid_hit = bool(paid_rank[i] == label[i])
        buy = margins[i] > 0
        hit = paid_hit if buy else free_hit
        rows[query_id] = dict(group=groups[i], buy=buy, free_hit=free_hit, paid_hit=paid_hit,
                              hit=hit, utility_tenths=10 * int(hit) - 3 * int(buy),
                              margin=str(margins[i]))

    sources = {}
    for group in sorted(set(groups)):
        values = [r for r in rows.values() if r['group'] == group]
        n = len(values)
        require(n == 4, f'Unexpected window count for {group}')
        utility = Fraction(sum(r['utility_tenths'] for r in values), 10 * n)
        free = Fraction(sum(r['free_hit'] for r in values), n)
        paid = Fraction(sum(r['paid_hit'] for r in values), n) - PRICE
        sources[group] = dict(n=n, buy=sum(r['buy'] for r in values), value=utility,
                              accuracy=Fraction(sum(r['hit'] for r in values), n),
                              delta_free=utility - free, delta_paid=utility - paid)

    def macro(key):
        return sum(s[key] for s in sources.values()) / len(sources)

    buy_count = sum(r['buy'] for r in rows.values())
    df, dp = macro('delta_free'), macro('delta_paid')
    worst = min(s['delta_free'] for s in sources.values())
    p = [sign_probability([s[key] for s in sources.values()]) for key in ('delta_free', 'delta_paid')]
    n = len(rows)
    bought = {
        'rescue': sum(r['buy'] and not r['free_hit'] and r['paid_hit'] for r in rows.values()),
        'harm': sum(r['buy'] and r['free_hit'] and not r['paid_hit'] for r in rows.values()),
        'already_right': sum(r['buy'] and r['free_hit'] and r['paid_hit'] for r in rows.values()),
        'both_wrong': sum(r['buy'] and not r['free_hit'] and not r['paid_hit'] for r in rows.values()),
    }
    missed = sum(not r['buy'] and not r['free_hit'] and r['paid_hit'] for r in rows.values())
    passes = (0 < buy_count < n and min(df, dp) >= Fraction(3, 100) and worst >= -Fraction(1, 20)
              and min(p) <= Fraction(1, 40) and max(p) <= Fraction(1, 20))
    metrics = dict(n=n, buy=buy_count, r1=macro('accuracy'), utility=macro('value'),
                   buy_rate=Fraction(buy_count, n), delta_free=df, delta_paid=dp,
                   worst_delta_free=worst, one_sided_sign_p=p, adopt=passes, bought=bought,
                   missed_rescues=missed, oracle_buy_gain=Fraction(7 * (missed + bought['rescue']), 10 * n),
                   break_even_price_vs_free=(Fraction(bought['rescue'] - bought['harm'], buy_count)
                                             if buy_count else None))
    return dict(metrics=metrics, sources=sources, windows=rows, min_absolute_margin=str(min(map(abs, margins))),
                design_sha256=sha256(design.astype('<f8').tobytes()).hexdigest())


def compare(actual, published, name):
    """Validate every published field other than timing, before emitting the independent result."""
    require(published['rows'] == len(actual['windows']) and published['sources'] == len(actual['sources']),
            f'{name} counts')
    actions = {key: int(row['buy']) for key, row in actual['windows'].items()}
    require(actions == published['actions'], f'{name} actions')
    require(actual['min_absolute_margin'] == published['min_absolute_margin'], f'{name} minimum margin')
    errors = []

    def visit(a, b, path):
        if isinstance(a, dict):
            require(a.keys() == b.keys(), f'{name} {path} keys')
            for key in a:
                visit(a[key], b[key], path + '/' + key)
        elif isinstance(a, list):
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                visit(x, y, path + f'/{i}')
        elif isinstance(a, Fraction):
            error = abs(float(a) - b)
            require(error <= 1e-12, f'{name} {path} error {error}')
            errors.append(error)
        else:
            require(a == b, f'{name} {path} differs')

    visit(dict(actual['metrics'], sources=actual['sources']), published['score'], 'score')
    return dict(actions_equal=len(actions), sources_equal=len(actual['sources']),
                min_absolute_margin_exact=True, max_reported_float_error=max(errors))


def evaluate():
    seal = json.loads(checked((STUDY / 'train-return-seal.json').read_bytes(), SEAL_SHA, 'TRAIN seal'))
    require(seal['fit_partition'] == 'train' and Fraction(seal['edit_unit']) == Fraction(1, 10**9)
            and len(seal['edit_numerators']) == 19, 'Unexpected TRAIN parameter schema')
    delta = [Fraction(n, 10**9) for n in seal['edit_numerators']]
    fit = member(HISTORICAL / 'locked_heads.zip', 'fit.json', REFERENCES['fit.json'])['full-svd-.1']
    front_name = 'primary/discovery/front_weights.json'
    front = member(QUALIFICATION / 'hcsn_intervention_value/evidence/records-04.zip',
                   front_name, REFERENCES[front_name])
    manifest = json.loads(checked((HISTORICAL / 'archive_manifest.json').read_bytes(),
                                  REFERENCES['archive_manifest.json'], 'archive manifest'))['archives']
    digests = dict(REFERENCES)
    panels = {}
    for split in ('train', 'dev', 'test'):
        files = {}
        for key, ext in (('features', 'npz'), ('semantic', 'npz'), ('roster', 'json')):
            name = f'media/{key}/{split}.{ext}'
            (archive, digest), = [(a, m['files'][name]['sha256'])
                                 for a, m in manifest.items() if name in m['files']]
            digests[name] = digest
            files[key] = member(HISTORICAL / archive, name, digest)
        require(set(files['features']['split'].tolist()) == {split}, 'Incorrect split in archive')
        panels[split] = score(files['features'], files['semantic'], files['roster'], front, fit, delta)
    require(all(digests[name] == digest for name, digest in seal['inputs'].items()), 'TRAIN inputs drifted')
    archive = STUDY / 'evaluation.zip'
    roster = member(archive, 'roster.json', REFERENCES['roster.json'])
    audio = member(archive, 'audio.npz', REFERENCES['audio.npz'])
    for key in ('query_id', 'label', 'group'):
        audio[key] = np.asarray([row[key] for row in roster])
    panels['third_cohort'] = score(audio, member(archive, 'camera.npz', REFERENCES['camera.npz']),
                                  roster, front, fit, delta)
    require(panels['third_cohort']['design_sha256'] ==
            '798dd120ee328d4181f8ee3e1cc7671885b6223280f6d7e2fbbaa30407efb494', 'Fresh design drifted')
    # The published evaluator is read only after all four independent results are complete.
    report_blob = (STUDY / 'train-return-results.json').read_bytes()
    published = json.loads(report_blob)
    require(published['weight_sha256'] == SEAL_SHA, 'Results use a different head')
    agreement = {k: compare(v, published['panels'][k], k) for k, v in panels.items()}
    return dict(train_seal_sha256=SEAL_SHA, edit_l1=sum(map(abs, delta)), edit_nonzero=sum(map(bool, delta)),
                program_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                reported_results_sha256=sha256(report_blob).hexdigest(), inputs_sha256=digests,
                agreement=agreement, panels=panels)


if __name__ == '__main__':
    print(json.dumps(evaluate(), indent=2, sort_keys=True, default=str))
