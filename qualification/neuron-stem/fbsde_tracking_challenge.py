"""Declared unseen-template challenge. Generated semantics, not human benchmark data.

The source verifier knows this closed grammar explicitly. Do not infer unrestricted
language competence, independent samples or compute savings versus the exact parser.
"""
from itertools import permutations
import random
import re
from four_gate_common import digest, require

SEED = 982451653
# None of these constructions is in training_rows or its calibration simulator.
TEMPLATES = (
    '{c} watches while {a} swaps parcels with {b}.',
    'Only {a} and {b} exchange parcels; {c} keeps theirs.',
    'The parcels of {a} and {b} are exchanged; {c} waits.',
    '{c} is not in the exchange: {a} trades parcels with {b}.',
    '{a} gives their parcel to {b}, who gives theirs to {a}; {c} stays put.',
    'With {c} watching, {b} and {a} trade their parcels.',
)


def exact_pair(sentence, names):
    require(type(names) in (list,tuple) and len(names)==3 and len(set(names))==3 and
            all(type(n) is str and re.fullmatch('[A-Z][a-z]{1,15}',n) for n in names),
            'three unambiguous actor names')
    require(type(sentence) is str and 0<len(sentence)<=512,'bounded source sentence')
    # Separate source interpreter: enumerate this explicitly declared grammar.
    matches=[]
    for a,b,c in permutations(range(3)):
        for template in TEMPLATES:
            if template.format(a=names[a],b=names[b],c=names[c])==sentence:
                matches.append(tuple(sorted((a,b))))
    require(matches and len(set(matches))==1,'unrecognized or ambiguous challenge instruction')
    return matches[0]


def generate(*, seed=SEED, per_family=24):
    require(type(seed) is int and seed>=0 and type(per_family) is int and 1<=per_family<=120,
            'bounded declared challenge')
    rng=random.Random(seed); result=[]
    names=('Ada','Bram','Cleo')
    for family,template in enumerate(TEMPLATES):
        for i in range(per_family):
            length=2+i%6;unique=min(1+i%3,length)
            choices=rng.sample(list(permutations(names)),unique)
            variants=[template.format(a=a,b=b,c=c) for a,b,c in choices]
            order=[j%unique for j in range(length)];rng.shuffle(order)
            result.append({'source_id':f'new-template:{family}:{i}', 'family':family,
                'names':list(names),'query':i%3,'events':[variants[j] for j in order]})
    return result


def task(row):
    require(set(row)=={'source_id','family','names','query','events'},'public source fields')
    require(type(row['query']) is int and 0<=row['query']<3 and
            type(row['events']) is list and 1<=len(row['events'])<=16,'bounded query/event inventory')
    return {'names':tuple(row['names']),'query':row['query'], 'values':('amber','blue','coral'),
        'options':(('A','amber'),('B','blue'),('C','coral')),
        'events':[{'text':s,'pair':exact_pair(s,row['names'])} for s in row['events']],
        'input_sha256':digest(row)}


def input_keys(row,binding):
    # Full original wording + actor coordinates + model/calibration/scope. Never
    # derive epistemic identity from a pooled embedding or an output score.
    return [digest([sentence,row['names'],binding]) for sentence in row['events']]
