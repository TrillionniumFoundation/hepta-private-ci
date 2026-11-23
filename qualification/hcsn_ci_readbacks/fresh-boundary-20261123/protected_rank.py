"""Test exact score-preserving edits on the SVD head's already-correct TRAIN decisions."""
from fractions import Fraction
import hashlib
import json
from math import isqrt
from pathlib import Path

import numpy as np
from train_return_edit import historical_inputs

HERE = Path(__file__).resolve().parent
P = 65537


def residue(value):
    numerator, denominator = float(value).as_integer_ratio()
    return numerator * pow(denominator, -1, P) % P


def full_column_minor(rows):
    assert P > 1 and all(P % n for n in range(2, isqrt(P)+1))
    a = [[residue(entry) for entry in row] for row in rows]
    order = list(range(len(a)))
    width = len(a[0])
    for col in range(width):
        pivot = next(r for r in range(col,len(a)) if a[r][col])
        if pivot != col:
            a[pivot], a[col] = a[col], a[pivot]
            order[pivot], order[col] = order[col], order[pivot]
        multiplier = a[col][col]
        inverse = pow(multiplier,-1,P)
        for i in range(col+1,len(a)):
            factor = a[i][col] * inverse % P
            for j in range(col,width):
                a[i][j] = (a[i][j] - factor*a[col][j]) % P
    # Elimination on the selected rows in their original matrix order may differ
    # in sign from an elimination that swapped discarded rows. Re-evaluate that
    # square minor directly so the printed determinant has a unique convention.
    selected = sorted(order[:width])
    minor = [[residue(entry) for entry in rows[k]] for k in selected]
    determinant = 1
    for col in range(width):
        pivot = next(r for r in range(col,width) if minor[r][col])
        if pivot != col:
            minor[pivot], minor[col] = minor[col], minor[pivot]
            determinant = -determinant
        value = minor[col][col]
        determinant = determinant*value % P
        for j in range(col+1,width):
            scale = minor[j][col]*pow(value,-1,P) % P
            minor[j] = [(x-scale*y)%P for x,y in zip(minor[j],minor[col],strict=True)]
    assert determinant % P
    return selected, determinant % P


def verify():
    x,w,data,free,paid,hashes = historical_inputs('train')
    purchase = x @ w > .30
    target = paid & ~free
    mask = purchase == target
    protected = x[mask]
    basis,det = full_column_minor(protected)
    wexact = list(map(lambda v:Fraction(float(v)),w))
    sealed = (HERE/'train-return-seal.json').read_bytes()
    assert hashlib.sha256(sealed).hexdigest() == '6ae738217ea463d48a5aac72b0b46c52dd9fdfabec4a3aed9e947cd20c340dae'
    delta = [Fraction(n,10**9) for n in json.loads(sealed)['edit_numerators']]
    changes=[]; updated=[]
    for row in x:
        exact=list(map(lambda v:Fraction(float(v)),row))
        changes.append(sum(a*b for a,b in zip(exact,delta,strict=True)))
        updated.append(sum(a*b for a,b in zip(exact,wexact,strict=True))+changes[-1] > Fraction(3,10))
    assert np.array_equal(updated,target)
    ids=np.asarray(data['query_id'])
    return {'inputs':hashes, 'training_rows':len(x), 'protected_rows':len(protected), 'columns_including_bias':x.shape[1],
            'protected_condition':'Original SVD first-prefix purchase action agrees with the realized immediate net-benefit-maximizing decision at price 0.30 on TRAIN.',
            'prime':P, 'ordered_minor_query_ids':ids[mask][basis].tolist(), 'minor_determinant_mod_prime':det,
            'exact_protected_rank':len(basis), 'exact_score_preserving_dimension':x.shape[1]-len(basis),
            'smallest_singular_value':float(np.linalg.svd(protected,compute_uv=False)[-1]),
            'edited_protected_action_count_unchanged':int(np.sum((np.array(updated)==purchase) & mask)),
            'edited_protected_scores_changed':sum(bool(changes[i]) for i in np.flatnonzero(mask)),
            'corrected_prior_wrong_actions':int(np.sum((np.array(updated)==target) & ~mask)),
            'correct_new_actions':int(np.sum(np.array(updated)==target)),
            'interpretation':'Exact score preservation on these 27 rows forces delta=0 for this 19-parameter linear head. Holding their discrete decisions fixed permits movement. This is a rank diagnostic inspired by null-space editing, not a run of an LLM editor or a bound on an approximate projector in another architecture.'}


if __name__ == '__main__':
    print(json.dumps(verify(),indent=2,sort_keys=True))
