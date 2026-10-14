"""Fixed generated state-dependent tasks. No filtering by error or disagreement."""
from itertools import permutations
from four_gate_common import digest, require

SEED = 2026101311
FRAMES = (
    '{a} and {b} exchange items while {c} waits.',
    '{a} exchanges with {b} if {a} holds amber; {c} waits.',
    '{a} exchanges with {b} if {c} holds blue; {c} waits.',
    '{a} exchanges with {b} if {b} holds coral; {c} waits.',
    '{a} takes a copy of the item of {b}; {c} waits.',
    '{a} and {b} exchange on even numbered events; {c} waits.',
)
STRATA = ('constant','self_guard','observer_guard','mixed_guard','copy_outside','time_outside')


def generate():
    names=['Mira','Nolan','Orla']; rows=[]
    for kind in range(6):
        for order in permutations(range(3)):
            for length in (2,3,4):
                for query in range(3):
                    a,b,c=(names[j] for j in order)
                    texts=[FRAMES[(1 if i%2==0 else 3) if kind==3 else kind].format(a=a,b=b,c=c)
                           for i in range(length)]
                    rows.append(dict(stratum=STRATA[kind],public=dict(source_id=f'conditional:{len(rows)}',
                        names=names[:],query=query,events=texts)))
    return rows


def observe(public):
    """Outer simulator; return only a selected effect, never the true predecessor."""
    state=list(range(3)); effects=[]; states=[state[:]]
    for step,text in enumerate(public['events']):
        matched=[]
        for a,b,c in permutations(range(3)):
            for kind,f in enumerate(FRAMES):
                if f.format(a=public['names'][a],b=public['names'][b],c=public['names'][c])==text:
                    matched.append((kind,a,b,c))
        require(len(matched)==1, 'registered source instruction')
        kind,a,b,c=matched[0]; effect=list(range(3))
        active=kind==0 or kind==1 and state[a]==0 or kind==2 and state[c]==1 or kind==3 and state[b]==2 or kind==5 and step%2==1
        if active: effect[a],effect[b]=b,a
        elif kind==4: effect[a]=b
        effects.append(tuple(effect)); state=[state[j] for j in effect]; states.append(state[:])
    def reveal(event,known):
        require(type(event) is int and 0<=event<len(effects), 'source event index')
        return dict(effect=effects[event],source_sha256=digest(public),
                    event_sha256=digest(public['events'][event]),known_sha256=digest(known))
    return reveal,state[public['query']],effects,states
