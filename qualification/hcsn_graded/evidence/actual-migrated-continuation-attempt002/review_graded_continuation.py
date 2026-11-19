"""Independent spectral/folded-law recomputation of every graded value row."""

import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

BASE=Path('/workspace/scratch/c06d659c1e72')
sys.path.insert(0,str(BASE/'short-gap-independent'))
from graded_exploration import GradedKernels
from review_visited_values import finite_phi


def identity(path):
    raw=Path(path).read_bytes();return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def main(output):
    started=time.perf_counter()
    original=BASE/'visited-originals/training-domain-original/run/audit'
    candidate=BASE/'graded-v2/qualification/hcsn_graded/evidence/actual-migrated-continuation-attempt001'
    report=json.loads((candidate/'SUMMARY.json').read_bytes())
    summary=json.loads((original/'SUMMARY.json').read_bytes())
    originals={};sources={str(Path(__file__)):identity(Path(__file__))}
    for module_name in ('graded_exploration','audit_short_gap','review_visited_values'):
        path=Path(sys.modules[module_name].__file__)
        sources[str(path)]=identity(path)
    if identity(original/'SUMMARY.json')['sha256']!='12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822':
        raise ValueError('original summary identity differs')
    reference_path=BASE/'joint-dde/qualification/hcsn_joint_dde/evidence/all-visits-attempt002/ALL_VISITS_128.npz'
    sources[str(reference_path)]=identity(reference_path)
    if sources[str(reference_path)]['sha256']!='a0984f1a06fd47a803259e570f47aed07a48f0d44e44598a25a77a85782016c3':
        raise ValueError('pinned old reference archive differs')
    with np.load(reference_path,allow_pickle=False) as archive:
        old_references={(int(r[0]),int(r[1])):(r[6],r[7]) for r in archive['rows']}
    for arm_index,arm in enumerate(summary['arms']):
        path=original/arm['derived_trace_file']
        observed=identity(path)
        if observed['sha256']!=arm['derived_trace_sha256']:raise ValueError('original trace identity differs')
        sources[str(path)]=observed
        for line in path.read_text().splitlines()[1:-1]:
            row=json.loads(line);originals[arm_index,row['index']]=row
    if len(originals)!=14336:raise ValueError('original full coverage differs')
    panels=[]
    for n in (256,512):
        path=candidate/f'ALL_VISITS_n{n}.npz';observed=identity(path)
        if observed['sha256']!=report['output_sha256'][path.name]:raise ValueError('candidate raw digest differs')
        sources[str(path)]=observed
        with np.load(path,allow_pickle=False) as archive:rows=archive['rows']
        if rows.shape!=(14336,11) or not np.isfinite(rows).all():raise ValueError('raw dimensions differ')
        kernel=GradedKernels(n)
        nodes,weights=kernel.nodes,kernel.weights
        phi=np.r_[1.,(kernel.v@(kernel.coefficient/(.15-kernel.eigen)))/kernel.d,0.]
        continuum_phi=np.array([finite_phi(x,8.,-.11999999999999998,.35,.15) for x in nodes])
        phase_edges=np.linspace(0,.2,9)
        phase=np.array([math.exp(-.15*a)*-math.expm1(-.15*(b-a))/(.15*(b-a)) for a,b in zip(phase_edges[:-1],phase_edges[1:])])
        eta=math.exp(-.15*.2);base=.4/.15
        cache={};maximum=np.zeros(9);seen=set();max_non_cancel=0.
        for item in rows:
            key=(int(item[0]),int(item[1]));visit=originals[key]
            if key in seen:raise ValueError('duplicate candidate visit key')
            seen.add(key)
            p=np.array(visit['posterior'][0]);par=visit['parameters']
            expected_reference,expected_finite=old_references[key]
            if item[4]!=expected_finite or item[5]!=expected_reference:
                raise ValueError('raw old-reference columns differ from pinned original')
            if any(par[k]!=v for k,v in [('mu',-.11999999999999998),('sigma',.35),('discount',.15)]):raise ValueError('fixed physics differs')
            reset=math.log(par['absolute_reset'])-par['log_boundary']
            if reset not in cache:
                def basis(transform):
                    reset_phi=float(np.interp(reset,nodes,transform))
                    reset_value=(base*(1-reset_phi)+reset_phi)/(1-eta*reset_phi)
                    values=base+transform*(1+eta*reset_value-base)
                    return np.r_[weights@values,phase*reset_value]
                cache[reset]=basis(phi),basis(continuum_phi)
            discrete,mapped=[float(p@values) for values in cache[reset]]
            finite,reference=item[4],item[5]
            terms=[discrete-mapped,mapped-finite,finite-reference]
            scale=max(1.,abs(reference))
            independent=np.array([discrete,mapped,finite,reference,abs(discrete-reference)/scale,
                                  sum(map(abs,terms))/scale,*terms])
            maximum=np.maximum(maximum,abs(independent-item[2:]))
            max_non_cancel=max(max_non_cancel,independent[5])
        if seen!=set(originals) or max(maximum)>2e-7:raise ValueError('independent spectral full-row agreement failed')
        panels.append({'intervals':n,'rows_checked':len(rows),'maximum_differences_by_raw_column':maximum.tolist(),
                       'independent_maximum_non_cancelling_scaled_error':max_non_cancel,
                       'one_percent_passed':bool(max_non_cancel<=.01)})
    if any(identity(path)!=expected for path,expected in sources.items()):raise ValueError('source/input mutation')
    result={'schema':'hcsn-independent-graded-migrated-value-review-v1','inputs':sources,'panels':panels,
            'source_and_inputs_unchanged':True,'wall_seconds':time.perf_counter()-started,
            'decomposition':'CTMC versus finite continuum on same folded initial/randomized reset laws; then initial/reset migration; then original-law upper truncation',
            'scope':'independent full-row continuation recomputation using spectral resolvent and separate floating hat integration; no graded physical Jacobian, full filtering or new training admission'}
    with Path(output).open('x') as out:json.dump(result,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='inputs'},sort_keys=True))


if __name__=='__main__':main(sys.argv[1])
