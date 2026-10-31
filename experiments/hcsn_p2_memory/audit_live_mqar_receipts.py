"""Independent stdlib verifier for two REAL immutable MQAR4 25s training receipts.

Research-only: validates serialized file integrity, same seed/inputs/cost, and
negative efficacy. Does not authenticate source, prove crash persistence or
justify twelve-run sealing/production deployment.
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path

BUNDLE_SHA256='625972ba7bd74b66753c909be0fae6b80c5a271f0c7699938ecee7d97021acf0'
EXPECTED={
 'aggregate_count':'5c1049fc85eb8d5311c11a3be13571f282bef949cb5dec5ce874cf2e95d80b32',
 'physical_event_timestamp':'a1ce98841cab714afc8cf0e58faaf3622397fd3f3d865b1672c6d27567cd5e70',
}

class UnresolvedReceiptAudit(ValueError): pass

def sha(b):return hashlib.sha256(b).hexdigest()

def canonical(obj):return (json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')

def verify_file_bytes(raw,arm):
    if sha(raw)!=EXPECTED[arm]:raise UnresolvedReceiptAudit('wrong original receipt byte digest')
    if raw!=canonical(json.loads(raw)):
        raise UnresolvedReceiptAudit('noncanonical on-disk envelope')
    envelope=json.loads(raw)
    if (envelope.get('key')!=f'mqar4.2.{arm}' or
        envelope.get('schema')!='hcsn-p2-immutable-trial-receipt-v1' or
        envelope.get('production_activation') is not False or
        envelope.get('scientific_gate_closed') is not False):
        raise UnresolvedReceiptAudit('wrong receipt identity or production authority')
    rec=envelope.get('record')
    if not isinstance(rec,dict) or envelope.get('payload_sha256')!=sha(canonical(rec)):
        raise UnresolvedReceiptAudit('incorrect canonical training digest')
    if not (rec.get('schema')=='hcsn-p2-timed-cpu-matched-followup-v2'
            and rec.get('task')=='mqar4' and type(rec.get('seed')) is int
            and rec.get('seed')==2 and rec.get('arm')==arm
            and rec.get('params')==5186
            and rec.get('reached_step_cap') is False
            and rec.get('reached_cpu_budget') is True
            and rec.get('negative_evidence_retained') is True
            and rec.get('unblinded_exploratory_followup') is True
            and rec.get('production_activation') is False
            and rec.get('all_scientific_blockers_closed') is False
            and 25<=rec.get('training_cpu_seconds',0)<=26.25):
        raise UnresolvedReceiptAudit('false trial cost, task, or scientific flag')
    for key in ('initial_model_sha256','train_data_sha256','trained_model_sha256'):
        val=rec.get(key)
        if not isinstance(val,str) or len(val)!=64 or any(c not in '0123456789abcdef' for c in val):
            raise UnresolvedReceiptAudit('invalid model/data SHA shape')
    for panel in ('id','ood'):
        x=rec.get(panel)
        if not isinstance(x,dict) or not (0<=x.get('accuracy',-1)<=1):
            raise UnresolvedReceiptAudit('invalid evaluation panel')
    return rec

def verify_bundle_bytes(raw):
    if sha(raw)!=BUNDLE_SHA256:
        raise UnresolvedReceiptAudit('bundle digest mismatch')
    obj=json.loads(raw)
    if obj.get('schema')!='hcsn-p2-live-mqar-paired-receipts-v1' or obj.get('full_12_seal') is not False or obj.get('production_activation') is not False or obj.get('scientific_gate_closed') is not False:
        raise UnresolvedReceiptAudit('false full-run or production claim')
    files=obj.get('trial_files')
    if not isinstance(files,dict) or set(files)!={f'mqar4.2.{arm}.json' for arm in EXPECTED}:
        raise UnresolvedReceiptAudit('trial evidence missing/extra')
    recs={arm:verify_file_bytes(files[f'mqar4.2.{arm}.json'].encode('ascii'),arm) for arm in EXPECTED}
    a,b=recs['aggregate_count'],recs['physical_event_timestamp']
    for key in ('initial_model_sha256','train_data_sha256','task','seed','params'):
        if a[key]!=b[key]:raise UnresolvedReceiptAudit('nonpaired frozen training input')
    for panel in ('id','ood'):
        for key in ('data_sha256','total_events','queries','multi_fire_streams'):
            if a[panel][key]!=b[panel][key]:raise UnresolvedReceiptAudit('nonpaired ID/OOD inputs')
    gap=abs(a['training_cpu_seconds']-b['training_cpu_seconds'])/max(a['training_cpu_seconds'],b['training_cpu_seconds'])
    if gap>0.05:raise UnresolvedReceiptAudit('unmatched CPU training budget')
    return {'paired_real_training_count':2,'task':'mqar4','seed':2,
            'training_cpu_relative_gap':gap,
            'aggregate_steps':a['optimizer_steps'],
            'physical_steps':b['optimizer_steps'],
            'id_signed_pp':100*(b['id']['accuracy']-a['id']['accuracy']),
            'ood_signed_pp':100*(b['ood']['accuracy']-a['ood']['accuracy']),
            'full_12_seal':False,'scientific_gate_closed':False,
            'production_activation':False}

def load_and_verify(path):
    try:
        payload=gzip.decompress(base64.b64decode(Path(path).read_text().strip(),validate=True))
    except (OSError,ValueError,EOFError) as exc:
        raise UnresolvedReceiptAudit('invalid compressed archive') from exc
    return verify_bundle_bytes(payload)

if __name__=='__main__':
    import sys
    print(json.dumps(load_and_verify(sys.argv[1]),sort_keys=True,indent=2))
