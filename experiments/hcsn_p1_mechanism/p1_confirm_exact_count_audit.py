"""Self-contained exact integer-count/Holm audit of the frozen P1 12-seed panel.

Verifies the committed *compact* evidence, not original weights or raw logits.
A SHA-256 link to lossless local 192-job output is retained separately.
"""
from fractions import Fraction
import base64
import gzip
import hashlib
from pathlib import Path
from itertools import product
import json
import math
import re

TASKS=('selective_copy','key_value_overwrite')
ARMS=('ordinary','call','risk','margin','call_risk','call_margin','risk_margin','all_three')

class IncompleteEvidence(ValueError): pass


def p_exact(ds):
    if len(ds)!=12 or any(type(d) is not int for d in ds):
        raise IncompleteEvidence('not 12 integer paired differences')
    target=abs(sum(ds))
    count=sum(abs(sum(x*s for x,s in zip(ds,signs)))>=target
              for signs in product((-1,1),repeat=12))
    return Fraction(count,4096)


def verify(doc):
    if (doc.get('schema')!='hcsn-p1-12seed-exact-count-audit-v1'
            or doc.get('seeds')!=list(range(100,112))
            or doc.get('test_count')!=384 or doc.get('complete_records')!=192
            or doc.get('registered_ood_effect_and_p_pass') is not False
            or doc.get('scientific_gate_closed') is not False
            or doc.get('production_activation') is not False):
        raise IncompleteEvidence('P1 frozen contract or veto mismatch')
    if not re.fullmatch(r'[0-9a-f]{64}',doc.get('full_sha256','')):
        raise IncompleteEvidence('missing full raw evidence identity')
    rows=doc.get('rows')
    if not isinstance(rows,list) or len(rows)!=16:
        raise IncompleteEvidence('incomplete P1 contrast matrix')
    keyed={}
    for row in rows:
        key=(row.get('task'),row.get('arm'))
        if key in keyed or key not in {(t,a) for t in TASKS for a in ARMS}:
            raise IncompleteEvidence('duplicate or unknown arm')
        for field in ('id_correct','ood_correct'):
            data=row.get(field)
            if not isinstance(data,list) or len(data)!=12 or any(
                    type(k) is not int or not 0<=k<=384 for k in data):
                raise IncompleteEvidence('invalid sample correct-count vector')
        cpu=row.get('mean_recorded_cpu_seconds')
        if type(cpu) not in (float,int) or not math.isfinite(cpu) or cpu<=0:
            raise IncompleteEvidence('invalid measured CPU')
        keyed[key]=row
    contrasts=[]
    for t in TASKS:
        base=keyed[t,'ordinary']['ood_correct']
        for arm in ARMS:
            row=keyed[t,arm]
            count=row['ood_correct']
            ds=[v-u for v,u in zip(count,base)]
            if row.get('paired_ood_correct_deltas')!=ds:
                raise IncompleteEvidence('paired count deltas corrupted')
            if abs(row['mean_ood_gain']-sum(ds)/(384*12))>1e-12:
                raise IncompleteEvidence('invalid reported OOD gain')
            if abs(row['mean_id_acc']-sum(row['id_correct'])/(384*12))>1e-12:
                raise IncompleteEvidence('invalid reported ID mean')
            if arm=='ordinary':
                if row.get('exact_p')!='1':
                    raise IncompleteEvidence('ordinary control p not fixed')
            else:
                p=p_exact(ds)
                if Fraction(row.get('exact_p','-1'))!=p:
                    raise IncompleteEvidence('exact signed-count p mismatch')
                contrasts.append((p,t,arm,row))
    if len(contrasts)!=14 or Fraction(2,32)<=Fraction(1,20*14):
        raise IncompleteEvidence('incorrect family or pilot infeasibility')
    contrasts.sort(key=lambda x:(x[0],x[1],x[2]))
    prev=Fraction(0)
    for i,(p,_,_,row) in enumerate(contrasts):
        prev=max(prev,min(Fraction(1),p*(14-i)))
        if Fraction(row.get('holm_adjusted','-1'))!=prev:
            raise IncompleteEvidence('Holm adjustment mismatch')
    full=all(Fraction(keyed[t,'all_three']['holm_adjusted'])<=Fraction(1,20)
             and keyed[t,'all_three']['mean_ood_gain']>=0.02 for t in TASKS)
    if full is not doc['registered_ood_effect_and_p_pass']:
        raise IncompleteEvidence('registered outcome flag disagrees with data')
    return {'rows':16,'paired_comparisons':14,'seed_count':12,
            'full_mechanism_significant':full,
            'five_seed_min_two_sided_p':'1/16',
            'minimum_possible_12seed_two_sided_p':'1/2048',
            'all_scientific_blockers_closed':False}


def load_evidence(path):
    try:
        text=Path(path).read_text().strip()
        raw=gzip.decompress(base64.b64decode(text,validate=True))
    except (ValueError,OSError,EOFError) as exc:
        raise IncompleteEvidence('invalid compressed primary count artifact') from exc
    if hashlib.sha256(raw).hexdigest()!='176f92cb09a898a075e8f560fc27a2de02335082faec510092713dfad61093e8':
        raise IncompleteEvidence('count artifact digest mismatch')
    return json.loads(raw)


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('evidence')
    args=parser.parse_args()
    print(json.dumps(verify(load_evidence(args.evidence)),sort_keys=True))

if __name__=='__main__': main()
