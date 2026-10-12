"""Versioned simulator feedback and untouched-frame evaluation; not human evidence.

Feedback labels describe source operations, not final benchmark answers. Exact
matching below belongs to the simulated verifier/scorer, never the neural input.
"""
from itertools import permutations
import random
from four_gate_common import digest, require
from fbsde_tracking import VERBS

PROFILE = 'verified_feedback_learning_v1'
SEED = 104395303
NAMES = ('Gina', 'Hugo', 'Iris')
FAMILIAR = tuple('Then, {a} and {b} '+v+'.' for v in VERBS)
# These four repair frames are already-known research material. They are NOT test.
REPAIR = (
    '{a} and {b} exchange their parcels while {c} watches.',
    '{c} keeps a parcel while {a} exchanges parcels with {b}.',
    'An exchange occurs between {b} and {a}; {c} does not join.',
    'Neither the observer {c} nor anyone else joins the exchange between {a} and {b}.',
)
CALIBRATION = (
    '{a} and {b} swap parcels while {c} stands by.',
    '{c} watches the parcel exchange between {a} and {b}.',
    '{a} exchanges parcels with {b}, leaving {c} out.',
)
HELDOUT = (
    'The parcels held by {a} and {b} are exchanged as {c} looks on.',
    '{c} stays out of it: {b} swaps parcels with {a}.',
    '{a} trades parcels with {b}; {c} watches without participating.',
    'Instead of exchanging with {c}, {b} exchanges parcels with {a}.',
    '{c} is only watching. The exchange takes place between {a} and {b}.',
    'It is {b}, not {c}, who trades parcels with {a}.',
)


def local_rows(frames):
    rows = []
    for family, frame in enumerate(frames):
        for a, b, c in permutations(range(3)):
            text = frame.format(a=NAMES[a], b=NAMES[b], c=NAMES[c])
            rows.append({'text': text, 'names': list(NAMES), 'pair': sorted((a, b)),
                         'source_id': digest(text), 'family': family})
    return rows


def generate():
    # Design does not accept predictions, disagreement, labels or success filters.
    rng = random.Random(SEED); rows = []
    for split, frames, count in (('known_replay', FAMILIAR, 12), ('heldout', HELDOUT, 24)):
        for family, frame in enumerate(frames):
            for i in range(count):
                length = 2+i % 6; unique = min(1+i % 3, length)
                roles = rng.sample(list(permutations(range(3))), unique)
                variants = [frame.format(a=NAMES[a], b=NAMES[b], c=NAMES[c]) for a,b,c in roles]
                order = [j % unique for j in range(length)]; rng.shuffle(order)
                rows.append({'source_id': f'{split}:{family}:{i}', 'split': split,
                    'family': family, 'names': list(NAMES), 'query': i % 3,
                    'events': [variants[j] for j in order]})
    return rows


def task(row):
    names = row['names']
    require(type(names) in (list, tuple) and len(names) == 3 and len(set(names)) == 3,
            'three distinct source coordinates')
    events = []
    for text in row['events']:
        matches = {tuple(sorted((a,b))) for a,b,c in permutations(range(3))
            for frame in FAMILIAR+REPAIR+CALIBRATION+HELDOUT
            if frame.format(a=names[a], b=names[b], c=names[c]) == text}
        require(len(matches) == 1, 'unsupported or ambiguous source operation')
        events.append({'text': text, 'pair': next(iter(matches))})
    return {'names': tuple(names), 'query': row['query'], 'values': ('amber','blue','coral'),
            'options': (('A','amber'),('B','blue'),('C','coral')), 'events': events,
            'input_sha256': digest(row)}
