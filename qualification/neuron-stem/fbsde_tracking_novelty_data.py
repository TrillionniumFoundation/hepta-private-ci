"""Predeclared simulator calibration/held-out frames, never BBH or human data.

Generation renders a known latent operation. Only the source-side verifier and
post-prediction scorer read that operation. This is a process-level information
contract, not an OS isolation or independent natural-language adjudication.
"""
from itertools import permutations
import random
from four_gate_common import digest, require
from fbsde_tracking import VERBS

FAMILIAR = tuple('Then, {a} and {b} '+v+'.' for v in VERBS)
CALIBRATION = (
    '{a} and {b} exchange their parcels while {c} watches.',
    '{c} keeps a parcel while {a} exchanges parcels with {b}.',
    'An exchange occurs between {b} and {a}; {c} does not join.',
    'Neither the observer {c} nor anyone else joins the exchange between {a} and {b}.',
)
HELDOUT = (
    '{c} observes {b} trading parcels with {a}.',
    'Parcels pass both ways between {a} and {b}; {c} is uninvolved.',
    '{b} trades a parcel with {a} instead of {c}.',
    'While {c} waits, the exchange is between {a} and {b}.',
)
NAMES = ('Dara', 'Elio', 'Faye')
SEED = 86028121


def local_rows(frames):
    rows = []
    for family, frame in enumerate(frames):
        for perm in permutations(range(3)):
            a,b,c = perm
            text = frame.format(a=NAMES[a], b=NAMES[b], c=NAMES[c])
            rows.append({'text': text, 'names': list(NAMES), 'pair': sorted((a,b)), 'family': family})
    return rows


def generate():
    """No model prediction, model agreement or error controls inclusion."""
    result = []; rng = random.Random(SEED)
    for split, frames, count in (('retention', FAMILIAR, 12), ('heldout', HELDOUT, 24)):
        for family, frame in enumerate(frames):
            for i in range(count):
                length = 2+i%6; unique = min(1+i%3, length)
                roles = rng.sample(list(permutations(range(3))), unique)
                variants = [frame.format(a=NAMES[a], b=NAMES[b], c=NAMES[c]) for a,b,c in roles]
                order = [j%unique for j in range(length)]; rng.shuffle(order)
                result.append({'source_id': f'{split}:{family}:{i}', 'split': split, 'family': family,
                               'names': list(NAMES), 'query': i%3, 'events': [variants[j] for j in order]})
    return result


def exact_pair(sentence, names):
    matches = set()
    for a,b,c in permutations(range(3)):
        for frame in FAMILIAR+CALIBRATION+HELDOUT:
            if frame.format(a=names[a], b=names[b], c=names[c]) == sentence:
                matches.add(tuple(sorted((a,b))))
    require(len(matches) == 1, 'unsupported or ambiguous declared sentence')
    return next(iter(matches))


def task(row):
    return {'names': tuple(row['names']), 'query': row['query'], 'values': ('amber','blue','coral'),
            'options': (('A','amber'),('B','blue'),('C','coral')),
            'events': [{'text': t, 'pair': exact_pair(t,row['names'])} for t in row['events']],
            'input_sha256': digest(row)}
