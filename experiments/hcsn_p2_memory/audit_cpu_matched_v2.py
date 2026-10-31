"""Independent no-drop audit of unblinded P2 equal-process-CPU follow-up.

Only Python stdlib; does not import the training model or comparator. The
compressed artifact expands to the exact 12 lossless training records.
This verifies bookkeeping, not scientific efficacy or CPU clock calibration.
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import statistics

RAW_SHA256='e1dafffc43f22e2ed774b414be860d36ab2e17fcb9a16d1b332f80c3e45e471f'
SCHEMA='hcsn-p2-timed-cpu-matched-followup-v2-12-record-audit'
RECORD_SCHEMA='hcsn-p2-timed-cpu-matched-followup-v2'
TASKS=('copy','mqar4')
SEEDS=(2,3,4)
ARMS=('aggregate_count','physical_event_timestamp')

class UnresolvedAudit(ValueError):
    pass


def _sha(text):
    return hashlib.sha256(text).hexdigest()


def load_raw(path):
    """Read exact compressed evidence and reject missing/altered bytes."""
    try:
        text=Path(path).read_text(encoding='ascii')
        compressed=base64.b64decode(text.strip(),validate=True)
        raw=gzip.decompress(compressed)
        if len(raw)>1_000_000 or _sha(raw)!=RAW_SHA256:
            raise UnresolvedAudit('lossless raw evidence hash/size mismatch')
        return json.loads(raw)
    except (OSError,UnicodeError,ValueError,TypeError,OverflowError,EOFError) as exc:
        if isinstance(exc,UnresolvedAudit):
            raise
        raise UnresolvedAudit('unreadable or inconsistent lossless raw evidence') from exc


def audit(payload):
    """Recompute paired deltas independently, never infer causal superiority."""
    if not isinstance(payload,dict) or payload.get('schema')!=SCHEMA or (payload.get('production_activation') is not False or
            payload.get('all_scientific_blockers_closed') is not False):
        raise UnresolvedAudit('bad evidence root or scientific admission flags')
    records=payload.get('records')
    if not isinstance(records,list) or len(records)!=12:
        raise UnresolvedAudit('incomplete or additional training records')
    indexed={}
    for rec in records:
        if not isinstance(rec,dict) or rec.get('schema')!=RECORD_SCHEMA:
            raise UnresolvedAudit('unrecognized individual record')
        key=tuple(rec.get(k) for k in ('task','seed','arm'))
        if (key in indexed or key[0] not in TASKS or type(key[1]) is not int or key[1] not in SEEDS or key[2] not in ARMS):
            raise UnresolvedAudit('missing/duplicate/unregistered run')
        indexed[key]=rec
        cpu=rec.get('training_cpu_seconds')
        steps=rec.get('optimizer_steps')
        if (rec.get('params')!=5186 or rec.get('training_cpu_budget_seconds')!=25.0 or
                rec.get('reached_cpu_budget') is not True or rec.get('reached_step_cap') is not False or
                type(cpu) not in (float,int) or not 25<=cpu<=26.25 or
                type(steps) is not int or not 0<steps<8000 or
                rec.get('production_activation') is not False or
                rec.get('all_scientific_blockers_closed') is not False or
                rec.get('unblinded_exploratory_followup') is not True or
                rec.get('negative_evidence_retained') is not True):
            raise UnresolvedAudit('budget, capacity or authority violation')
        for hash_field in ('initial_model_sha256','trained_model_sha256','train_data_sha256'):
            s=rec.get(hash_field)
            if not isinstance(s,str) or len(s)!=64 or any(c not in '0123456789abcdef' for c in s):
                raise UnresolvedAudit('invalid source/model/data digest')
        for panel in ('id','ood'):
            entry=rec.get(panel)
            if (not isinstance(entry,dict) or entry.get('queries')!=(128 if key[0]=='copy' else 512) or
                    type(entry.get('correct')) is not int or not 0<=entry['correct']<=entry['queries'] or
                    abs(entry.get('accuracy',-1)-entry['correct']/entry['queries'])>2e-7 or
                    type(entry.get('cpu_seconds')) not in (float,int) or entry['cpu_seconds']<0 or
                    type(entry.get('total_events')) is not int or entry['total_events']<=0 or
                    type(entry.get('multi_fire_streams')) is not int or not 0<=entry['multi_fire_streams']<=128):
                raise UnresolvedAudit('corrupted heldout metric/cost/event counts')
    if set(indexed)!={(t,s,a) for t in TASKS for s in SEEDS for a in ARMS}:
        raise UnresolvedAudit('incomplete factorial pairing')
    computed=[]
    for task in TASKS:
        for seed in SEEDS:
            a,b=(indexed[(task,seed,arm)] for arm in ARMS)
            for k in ('initial_model_sha256','train_data_sha256'):
                if a[k]!=b[k]:
                    raise UnresolvedAudit('paired model or raw physical data changed')
            for panel in ('id','ood'):
                for k in ('data_sha256','total_events','queries','multi_fire_streams'):
                    if a[panel].get(k)!=b[panel].get(k):
                        raise UnresolvedAudit('paired eval population/streams differ')
            gap=abs(a['training_cpu_seconds']-b['training_cpu_seconds'])/max(a['training_cpu_seconds'],b['training_cpu_seconds'])
            if gap>0.05:
                raise UnresolvedAudit('not within frozen 5% process-CPU budget')
            d={'task':task,'seed':seed,'training_cpu_relative_gap':gap,
               'id_signed_pp':100*(b['id']['accuracy']-a['id']['accuracy']),
               'ood_signed_pp':100*(b['ood']['accuracy']-a['ood']['accuracy'])}
            computed.append(d)
            # Also check the saved summary rather than trusting it. Exact float
            # arithmetic order matches the original on scalar accuracy values.
            saved=[c for c in payload.get('comparisons',[]) if c.get('task')==task and c.get('seed')==seed]
            if len(saved)!=1 or saved[0].get('equal_cpu_within_five_percent') is not True:
                raise UnresolvedAudit('missing or false paired comparison')
            for k in ('training_cpu_relative_gap','id_signed_pp','ood_signed_pp'):
                if abs(saved[0].get(k,float('inf'))-d[k])>1e-12:
                    raise UnresolvedAudit('paired summary differs from raw data')
    if len(payload.get('comparisons',[]))!=6:
        raise UnresolvedAudit('extra or omitted paired comparisons')
    table=[]
    for t in TASKS:
        for panel in ('id','ood'):
            def mean_arm(arm):
                return statistics.mean(indexed[(t,s,arm)][panel]['accuracy'] for s in SEEDS)*100
            aa=mean_arm(ARMS[0]);bb=mean_arm(ARMS[1])
            table.append({'task':t,'split':panel,'aggregate_pct':aa,
                          'timed_pct':bb,'timed_minus_aggregate_pp':bb-aa,
                          'paired_seeds':len(SEEDS)})
    return {'complete':True,'record_count':12,'pairs':6,'cpu_gap_max_pct':max(x['training_cpu_relative_gap'] for x in computed)*100,
            'table':table,'scientific_gate_closed':False,
            'independent_replication':False,'production_activation':False,
            'notes':'exploratory, unblinded, no frozen independent confirm, no GPU, no full-host failure test'}


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('raw_b64',type=Path)
    args=ap.parse_args()
    print(json.dumps(audit(load_raw(args.raw_b64)),indent=2,sort_keys=True))

if __name__=='__main__':
    main()
