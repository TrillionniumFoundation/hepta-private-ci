"""Preregistered renderer splits for outcome-labelled depth routing research.

Old explored frames become ROUTER training/selection. New frames stay evaluation
only. Labels are supplied by the renderer/verifier, not human future outcomes.
"""
from itertools import permutations
import random
from four_gate_common import digest, require
from fbsde_tracking_feedback_data import HELDOUT, REPAIR, CALIBRATION, FAMILIAR

PROFILE = 'outcome_depth_routing_v1'
SEED = 49979687
NAMES = ('Gina', 'Hugo', 'Iris')
FRAMES = {
    'train': HELDOUT[:4] + REPAIR[:2],
    'selection': HELDOUT[4:] + CALIBRATION[:1],
    'test': (
        'Watching from the side is {c}; it is {a} who exchanges parcels with {b}.',
        'The exchange involves {b} together with {a}, but leaves {c} holding the same parcel.',
        '{a} hands a parcel to {b} and receives a parcel back; {c} does neither.',
        'Although {c} observes the activity, the two exchanging parcels are {a} and {b}.',
        'No parcel changes hands for {c}: {b} and {a} exchange theirs.',
        '{b} takes the parcel of {a}, whose new parcel comes from {b}; {c} only observes.',
        'It is not {c} who exchanges with {a}; the other participant is {b}.',
        'The parcel held by {a} goes to {b}, and the one held by {b} goes to {a}; {c} waits.',
    ),
    'retention': FAMILIAR,
}
PER_FRAME = {'train': 48, 'selection': 32, 'test': 24, 'retention': 12}


def generate():
    rng = random.Random(SEED); rows = []
    for split, frames in FRAMES.items():
        for family, frame in enumerate(frames):
            for i in range(PER_FRAME[split]):
                n = 2 + i % 6; unique = min(1 + i % 3, n)
                roles = rng.sample(list(permutations(range(3))), unique)
                variants = [frame.format(a=NAMES[a], b=NAMES[b], c=NAMES[c]) for a,b,c in roles]
                order = [j % unique for j in range(n)]; rng.shuffle(order)
                rows.append({'source_id': f'{split}:{family}:{i}', 'split': split,
                    'family': family, 'names': list(NAMES), 'query': i % 3,
                    'events': [variants[j] for j in order]})
    inventories = {s: {digest(t) for r in rows if r['split']==s for t in r['events']} for s in FRAMES}
    require(all(not inventories[a] & inventories[b] for a in FRAMES for b in FRAMES if a < b),
            'raw event leakage between renderer splits')
    return rows


def operation(text, names):
    require(tuple(names)==NAMES, 'registered source coordinates')
    pairs = {tuple(sorted((a,b))) for a,b,c in permutations(range(3))
        for frames in FRAMES.values() for frame in frames
        if frame.format(a=names[a],b=names[b],c=names[c])==text}
    require(len(pairs)==1, 'unsupported or ambiguous simulator operation')
    return next(iter(pairs))


def target(source):
    holders = list(range(3))
    for text in source['events']:
        a,b = operation(text,source['names']); holders[a],holders[b] = holders[b],holders[a]
    return holders[source['query']]


def reward(record, label):
    require(type(label) is int and 0 <= label < 3, 'source target')
    return (0 if record['holder'] is None else 1 if record['holder']==label else -1) - .02*len(record['checks'])
