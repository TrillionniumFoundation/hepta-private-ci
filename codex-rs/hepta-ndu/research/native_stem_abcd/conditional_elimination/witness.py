"""R24 exact archive-derived feasible-witness impossibility proof.

This is an *additional posthoc result*, not a new R24 efficacy arm or refit.
A point sampled from an older fitted solution is a feasible theta and therefore
provides a rigorous upper bound on the global optimum of the SAME known law.
"""
import argparse,csv,hashlib,json
from fractions import Fraction as F
from pathlib import Path
import numpy as np
import eliminate as e
ORIGINAL_ARCHIVE_SHA256='75b7f84db4fa749c48b502c4ff1fe23af02e8b7fa5fd045f99c487e80c1f1d99'
ORIGINAL_WEIGHTS_SHA256='cb548fed6aa074b8494cc47d4860d6f18ba82c40810f4279429d8936559148c5'

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def floor_to(q,p=12):
 s=10**p;v=q*s;return F(v.numerator//v.denominator,s)
def ceil_to(q,p=12):return -floor_to(-q,p)

def run(source,output,archive=None,original_index=None):
    if archive is not None and digest(archive)!=ORIGINAL_ARCHIVE_SHA256:
        raise ValueError('R21 archival ZIP sha256 mismatch')
    if original_index is not None and digest(original_index)!=ORIGINAL_WEIGHTS_SHA256:
        raise ValueError('R21 original hexadecimal weight CSV sha256 mismatch')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    with Path(source).open(newline='') as stream:
        records=list(csv.DictReader(stream))
    if len(records)!=3 or set(int(r['width']) for r in records)!={2,3,4}:
        raise ValueError('wrong witness census')
    out=[]
    for r in sorted(records,key=lambda x:int(x['width'])):
        width=int(r['width']);name=r['name']
        weight=np.asarray([float.fromhex(k) for k in r['binary64_hex_vector'].split('|')],dtype='<f8')
        if len(weight)!=width:raise ValueError('witness parameter mismatch')
        if hashlib.sha256(weight.tobytes()).hexdigest()!=r['tensor_sha256']:
            raise ValueError('forged witness tensor sha256')
        witness=tuple((F.from_float(float(z)),F.from_float(float(z))) for z in weight)
        cand=tuple((F(v),F(v)) for v in e.old.CANDIDATES[width])
        witness_l,witness_u=e.old.cost_bounds(witness)
        candidate_l,candidate_u=e.old.cost_bounds(cand)
        lb=candidate_l-witness_u
        # This is a lower bound on *the candidate's* global excess: J_c-J*.
        impossible=bool(lb>e.old.TARGET)
        out.append(dict(width=width,witness_name=name,witness_sha256=r['tensor_sha256'],
                        archived_binary64_hex=r['binary64_hex_vector'],
                        archived_candidate=e.old.CANDIDATES[width],
                        candidate_cost_lower=str(candidate_l),candidate_cost_upper=str(candidate_u),
                        witness_cost_lower=str(witness_l),witness_cost_upper=str(witness_u),
                        globally_valid_excess_lower=str(lb),
                        guaranteed_excess_lower_floor_12=str(floor_to(lb)),
                        candidate_lower_floor_12=str(floor_to(candidate_l)),
                        witness_upper_ceil_12=str(ceil_to(witness_u)),
                        frozen_cost_threshold=str(e.old.TARGET),
                        candidate_certification_mathematically_impossible=impossible,
                        no_optimization_or_retraining_performed=True))
    (output/'WITNESS_PROOF.json').write_text(json.dumps(dict(
        source_sha256=digest(source),original_archive_sha256=ORIGINAL_ARCHIVE_SHA256,
        original_weight_csv_sha256=ORIGINAL_WEIGHTS_SHA256,
        witness_selection='posthoc historic R21 lowest observed float cost, validity of each bound independent of this selection',
        exact_dyadic_weights=True,exact_rational_bound_proof=True,
        archived_weights_can_only_be_used_on_original_known_population=True,
        records=out),indent=2,sort_keys=True)+'\n')
    with (output/'WITNESS_SUMMARY.csv').open('x',newline='') as fp:
        w=csv.DictWriter(fp,fieldnames=['width','witness_name','candidate_lower_floor_12',
            'witness_upper_ceil_12','guaranteed_excess_lower_floor_12',
            'candidate_certification_mathematically_impossible'])
        w.writeheader();w.writerows({key:r[key] for key in w.fieldnames} for r in out)
    print(json.dumps([dict(width=r['width'],lower_bound=float(F(r['globally_valid_excess_lower'])),
                            impossible=r['candidate_certification_mathematically_impossible']) for r in out]))
    return out

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True);p.add_argument('--archive',type=Path)
 p.add_argument('--original-index',type=Path)
 a=p.parse_args();run(a.input,a.out,a.archive,a.original_index)
