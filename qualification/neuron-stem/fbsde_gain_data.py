"""New generated test frames, frozen before scoring; NOT independent human data."""
from itertools import permutations
import random
import re
from four_gate_common import digest, require
from fbsde_outcome_data import NAMES, FRAMES as OLD_FRAMES, operation as old_operation

PROFILE='gain_weighted_routing_v1'
SEED=86028157
FRAMES=(
    '{c} watches the parcel exchange; {a} gives theirs to {b}, and {b} gives theirs to {a}.',
    'Keeping the same parcel is {c}, unlike {a} and {b}, who trade with each other.',
    'It is {b}, not {c}, that {a} trades parcels with.',
    'Only {a} and {b} switch parcels, while {c} merely describes the switch.',
    'The parcels move from {a} to {b} and from {b} to {a}, with none moving to {c}.',
    'The parcel of {c} is not involved: the swap is between {b} and {a}.',
    'After watching {c} stand aside, {a} swaps parcels with {b}.',
    '{a} ends up with what {b} had, {b} with what {a} had; {c} stays as before.',
)


def generate(old_rows):
    rng=random.Random(SEED); rows=[]
    for family,frame in enumerate(FRAMES):
        for i in range(24):
            n=2+i%6; unique=min(1+i%3,n)
            roles=rng.sample(list(permutations(range(3))),unique)
            texts=[frame.format(a=NAMES[a],b=NAMES[b],c=NAMES[c]) for a,b,c in roles]
            order=[j%unique for j in range(n)];rng.shuffle(order)
            rows.append({'source_id':f'gain-test:{family}:{i}','split':'test','family':family,
                'names':list(NAMES),'query':i%3,'events':[texts[j] for j in order]})
    # Old retention is deliberately a REPLAY, never called a new independent split.
    rows.extend(dict(r) for r in old_rows if r['split']=='retention')
    old={digest(t) for r in old_rows for t in r['events']}
    new={digest(t) for r in rows if r['split']=='test' for t in r['events']}
    require(not old & new, 'new test text overlaps prior exposed source')
    return rows


# Compile the exact registered grammar once; no model or test labels involved.
_PATTERNS=[]
for _frame in FRAMES:
    _parts=[];_seen=set()
    for _part in re.split(r'(\{[abc]\})',_frame):
        if _part.startswith('{'):
            _role=_part[1]
            _parts.append(f'(?P={_role})' if _role in _seen else f'(?P<{_role}>[A-Z][a-z]+)')
            _seen.add(_role)
        else:_parts.append(re.escape(_part))
    _PATTERNS.append(re.compile(''.join(_parts)))


def operation(text,names):
    require(tuple(names)==NAMES, 'source coordinate system')
    pairs=set()
    for pattern in _PATTERNS:
        match=pattern.fullmatch(text)
        if match and len(set(match.groupdict().values()))==3 and set(match.groupdict().values())==set(names):
            pairs.add(tuple(sorted((names.index(match['a']),names.index(match['b'])))))
    if not pairs:return old_operation(text,names)
    require(len(pairs)==1,'ambiguous generated instruction')
    return next(iter(pairs))


def target(src):
    holders=list(range(3))
    for text in src['events']:
        a,b=operation(text,src['names']); holders[a],holders[b]=holders[b],holders[a]
    return holders[src['query']]
