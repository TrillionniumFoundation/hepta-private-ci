"""Independent offline verifier of immutable paired raw prediction receipts.

This recomputes actual Brier/accuracy/NLL and sign-flip p from raw predictions.
Does NOT rely on the training runner's published metric values. Refuse on any
unmatched payload, missing seed, or CPU/parameter identity. NO_GO only.
"""
import base64
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import mean


def digest(x):return hashlib.sha256(x).hexdigest()


class AuditRefusal(ValueError): pass


def verify(prefix):
    prefix=Path(prefix)
    summary_blob=Path(str(prefix)+'.json').read_bytes()
    summary=json.loads(summary_blob)
    raw=gzip.decompress(base64.b64decode(Path(str(prefix)+'.json.gz.b64').read_bytes(),validate=False))
    if digest(raw)!=summary['raw_sha256']:raise AuditRefusal('raw digest mismatch')
    obj=json.loads(raw)
    p=Path(__file__).parent/'PROTOCOL_20261031.json'
    seal=digest(p.read_bytes())
    if seal!=summary['protocol_sha256'] or seal!=obj['protocol_sha256']:
        raise AuditRefusal('protocol digest mismatch')
    rows=obj['rows']
    if len(rows)!=8 or [r['seed'] for r in rows]!=list(range(501,509)):
        raise AuditRefusal('missing/duplicate/unordered paired seeds')
    deltas=[];id_deltas=[];cpu=[]
    for row in rows:
        seed=row['seed']
        receipt=Path(str(prefix)+'_receipts')/f'{seed}.json'
        if digest(receipt.read_bytes())!=summary['per_seed_receipt_sha256'][str(seed)]:
            raise AuditRefusal('per-seed raw receipt mismatch')
        if json.loads(receipt.read_bytes())!=row:
            raise AuditRefusal('aggregated raw receipt differs from sealed seed')
        metric={}
        if set(row['arms'])!={'ordinary','call_put_margin_risk'}:
            raise AuditRefusal('one paired arm missing')
        for arm,armrow in row['arms'].items():
            v=armrow['training'];cpu.append(v['training_and_feature_cpu_seconds'])
            if v['parameters']!=609 or v['updates']<1 or not 2.0<=cpu[-1]<2.1:
                raise AuditRefusal('unexpected trainable parameter or CPU budget')
            metric[arm]={}
            for split in ('iid','ood'):
                labels=row[split+'_labels'];pred=armrow[split]['prediction']
                if len(labels)!=768 or len(pred)!=768 or not all(x in (0,1) for x in labels) or not all(0<=x<=1 and math.isfinite(x) for x in pred):
                    raise AuditRefusal('missing or invalid prediction/label')
                brier=mean((x-y)**2 for x,y in zip(pred,labels))
                acc=mean((x>=.5)==bool(y) for x,y in zip(pred,labels))
                nll=mean(-y*math.log(max(1e-7,min(1,x))) - (1-y)*math.log(max(1e-7,min(1,1-x))) for x,y in zip(pred,labels))
                reported=armrow[split]
                if not all(math.isclose(z,reported[k],abs_tol=2e-12,rel_tol=0) for k,z in (('brier',brier),('accuracy',acc),('nll',nll))):
                    raise AuditRefusal('stored metric disagrees with raw predictions')
                metric[arm][split]=brier
        deltas.append(metric['ordinary']['ood']-metric['call_put_margin_risk']['ood'])
        id_deltas.append(metric['ordinary']['iid']-metric['call_put_margin_risk']['iid'])
    if max(cpu)-min(cpu)>=.1:raise AuditRefusal('not comparable CPU budgets')
    signs=sum(abs(sum((1 if bits & (1<<i) else -1)*v for i,v in enumerate(deltas)))+1e-15>=abs(sum(deltas)) for bits in range(256))/256
    if (not math.isclose(signs,summary['exact_two_sided_signflip_p_ood'],abs_tol=1e-14)
        or not math.isclose(mean(deltas),summary['mean_ood_brier_improvement'],abs_tol=2e-12)
        or not math.isclose(mean(id_deltas),summary['mean_iid_brier_improvement'],abs_tol=2e-12)):
        raise AuditRefusal('published paired statistics disagree with raw prediction audit')
    return {'seed_count':len(rows),'audited_predictions':8*2*2*768,'mean_ood_brier_improvement':mean(deltas),
            'mean_id_brier_improvement':mean(id_deltas),'signflip_p':signs,'cpu_min':min(cpu),'cpu_max':max(cpu),
            'p1_closed':False,'p0_p6_closed':False}

if __name__=='__main__':
    import sys
    if len(sys.argv)!=2:raise SystemExit('usage: ... audit_regime_results PREFIX')
    print(json.dumps(verify(sys.argv[1]),indent=2))
