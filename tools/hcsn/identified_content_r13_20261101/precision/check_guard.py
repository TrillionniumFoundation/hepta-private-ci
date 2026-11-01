"""Post-freeze guard diagnostics, including an explicit out-of-range example."""

import gzip
import json
from pathlib import Path
import warnings

import numpy as np

import guarded
from fresh import write,check_freeze


def main():
    receipt=check_freeze()
    root=Path(__file__).resolve().parent
    data=json.loads(gzip.decompress((root/'FRESH_RESULTS.json.gz').read_bytes()))
    summaries={}
    for mode in ('single32','double_single'):
        accepted=[]
        for row in data['rows']:
            p,c=row['modes'][mode],row['modes']['mixed64']
            good='error' not in p and not guarded.diagnostics(np.array(p['actual']),np.array(p['jacobian']))
            if good:
                good=(guarded.discrepancy(p['actual'],c['actual'])<=4e-7
                      and guarded.discrepancy(p['jacobian'],c['jacobian'])<=1e-5)
            accepted.append(dict(name=row['name'],guard_accept=good,reference_pass=p['passed']))
        summaries[mode]=dict(accepted=sum(a['guard_accept'] for a in accepted),rows=len(accepted),
            observed_false_accept=sum(a['guard_accept'] and not a['reference_pass'] for a in accepted),
            rows_detail=accepted)
    worst=max(data['rows'],key=lambda r:r['modes']['single32'].get('jacobian_error',float('inf')))
    v,j,meta=guarded.evaluate(worst['theta'],worst['state'],coordinate=worst['coordinate'],prefer='single32',mixed_check=True)
    assert meta['fallback'] and meta['mixed_executed'] and meta['returned_backend']=='mixed64'
    assert np.array_equal(v,np.array(worst['modes']['mixed64']['actual'],np.float32))
    v,j,pure=guarded.evaluate(guarded.stable32.k.BASE,.1,allow_fallback=False)
    assert not pure['mixed_executed'] and not pure['fallback']
    _,_,checked=guarded.evaluate(guarded.stable32.k.BASE,.1,mixed_check=True)
    assert checked['mixed_executed'] and not checked['fallback']
    probes=[]
    for x in (81.,90.):
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            try:
                v,j,report=guarded.evaluate(guarded.stable32.k.BASE,x)
                item=dict(log_distance=x,values=v.tolist(),metadata=report,finite=bool(np.isfinite(j).all()))
            except (ValueError,ArithmeticError) as exc:
                item=dict(log_distance=x,rejected=True,error=str(exc))
            item['warnings']=sorted(set(str(w.message) for w in seen))
        probes.append(item)
    assert probes[0]['metadata']['fallback'] and probes[0]['metadata']['mixed_executed']
    assert probes[1]['rejected']
    write('GUARD_EVIDENCE.json',dict(freeze_sha256=receipt,summary=summaries,
        actual_single32_fallback=dict(name=worst['name'],metadata=meta),pure_example=pure,checked_example=checked,
        range_probes=probes,
        qualification='Post-freeze diagnostic wrapper. Observed agreement with mixed64 is not a certified error bound; mixed_check always runs FP64. Range probes are outside the frozen x<=2 tested range.'))
    print(json.dumps({m:{k:v for k,v in d.items() if k!='rows_detail'} for m,d in summaries.items()},indent=2))
    print(json.dumps(probes,indent=2))


if __name__=='__main__':
    main()
