"""New pre-execution frames; renderer truth is withheld from every runtime model."""
from itertools import permutations
import random
import re
from four_gate_common import digest, require
from fbsde_gain_data import generate as old_generate, operation as old_operation

SEED = 2026101341
FRAMES = (
    '{c} abstains from trading; {b} and {a} pass their parcels to each other.',
    'The two traders are {a} and {b}. Watching but not trading is {c}.',
    'Excluding {c}, the exchange involves {b} together with {a}.',
    '{a} trades with {b} instead of {c}; only their two parcels change hands.',
    'While {c} records the transaction, {b} swaps a parcel with {a}.',
    '{b} receives the parcel from {a} and returns their own to {a}; {c} keeps theirs.',
    'No parcel passes to {c}. The trading pair is {a} with {b}.',
    'Leaving {c} outside the transaction, the parcels of {b} and {a} change places.',
)


def generate(parent_rows):
    rng = random.Random(SEED); names = ('Gina', 'Hugo', 'Iris'); rows = []
    for family in range(8):
        for i in range(24):
            length = 2+i%6; unique = min(1+i%3, length); frames = 1+(i//3)%unique
            roles = rng.sample(list(permutations(range(3))), unique)
            texts = [FRAMES[(family+j%frames)%8].format(a=names[a], b=names[b], c=names[c])
                     for j, (a,b,c) in enumerate(roles)]
            order = [j%unique for j in range(length)]; rng.shuffle(order)
            rows.append(dict(source_id=f'role-test:{family}:{i}', split='test', family=family,
                             names=list(names), query=i%3, events=[texts[j] for j in order]))
    old = old_generate(parent_rows)
    rows.extend(dict(r, split='diagnostic_replay' if r['split']=='test' else 'retention') for r in old)
    oldtexts = {digest(t) for r in old+parent_rows for t in r['events']}
    require(not oldtexts & {digest(t) for r in rows if r['split']=='test' for t in r['events']},
            'new frames overlap exposed source')
    return rows


PATTERNS = []
for frame in FRAMES:
    seen = set(); parts = []
    for part in re.split(r'(\{[abc]\})', frame):
        if part.startswith('{'):
            role = part[1]; parts.append(f'(?P={role})' if role in seen else f'(?P<{role}>[A-Z][a-z]+)'); seen.add(role)
        else: parts.append(re.escape(part))
    PATTERNS.append(re.compile(''.join(parts)))


def operation(text, names):
    matches = set()
    for pattern in PATTERNS:
        m = pattern.fullmatch(text)
        if m and len(set(m.groupdict().values()))==3 and set(m.groupdict().values())==set(names):
            matches.add(tuple(sorted((names.index(m['a']), names.index(m['b'])))))
    if not matches: return old_operation(text, names)
    require(len(matches)==1, 'ambiguous verification source')
    return next(iter(matches))
