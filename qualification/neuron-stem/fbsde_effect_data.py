"""Declared simulator contexts; no error-conditioned sampling or learned inputs.

The verifier returns the effect at this event's ACTUAL predecessor state. It does
not promise that another occurrence of the same sentence has that same effect.
"""
from itertools import permutations
from four_gate_common import digest, require

SEED = 2026101307
FRAMES = (
    '{a} exchanges parcels with {b}; {c} keeps their parcel.',
    '{a}, {b}, and {c} keep their parcels without any exchange.',
    '{a} gives to {b}, {b} gives to {c}, and {c} gives to {a}.',
    '{a} exchanges with {b} only if {a} currently holds amber; {c} keeps theirs.',
    '{a} copies the parcel held by {b}; {c} keeps theirs.',
)
STRATA = ('swap','identity','cycle','state_dependent','nonbijective','mixed')


def generate():
    names=('Jade','Kian','Lena');rows=[]
    for kind in range(6):
        for order in permutations(range(3)):
            a,b,c=(names[j] for j in order)
            for length in (2,3,4):
                for query in range(3):
                    texts=[FRAMES[(2+i)%3 if kind==5 else kind].format(a=a,b=b,c=c) for i in range(length)]
                    public=dict(source_id=f'effect:{len(rows)}',names=list(names),query=query,events=texts)
                    rows.append(dict(public=public,stratum=STRATA[kind]))
    return rows


def operation(text,names,state):
    require(sorted(names)==sorted(set(names)) and len(names)==3 and len(state)==3, 'simulator coordinates')
    matches=[]
    for a,b,c in permutations(range(3)):
        for kind,frame in enumerate(FRAMES):
            if frame.format(a=names[a],b=names[b],c=names[c])==text: matches.append((kind,a,b,c))
    require(len(matches)==1,'registered simulator instruction')
    kind,a,b,c=matches[0]; effect=list(range(3))
    if kind==0 or kind==3 and state[a]==0: effect[a],effect[b]=b,a
    elif kind==2: effect[a],effect[b],effect[c]=c,a,b
    elif kind==4: effect[a]=b
    return tuple(effect)


def observe(public):
    """Outside the policy: compute ground-truth execution and a selected-only port."""
    held=list(range(3));effects=[]
    for text in public['events']:
        effect=operation(text,public['names'],held);effects.append(effect)
        held=[held[j] for j in effect]
    def reveal(event,known):
        require(type(event) is int and 0<=event<len(effects), 'selected source event')
        return dict(effect=effects[event],source_sha256=digest(public),
                    event_sha256=digest(public['events'][event]),known_sha256=digest(known))
    return reveal,held[public['query']],effects
