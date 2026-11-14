"""Independent stdlib replay of two *actual* create-only, 25 CPU-second runs.

This checks archived original output bytes/receipts, but cannot authenticate
where the CPU clock came from or prove physical power-loss recovery.
"""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ARCHIVE_SHA256='344eca3b2b2242a99b3c2c42e01e2031f167a47078df04a1ab0989054a99966d'
ARCHIVE_FILE='SEALED_2PAIR_SMOKE_RAW_20261031.tar.gz.b64'
ARMS={'aggregate_count':'copy-s2-aggregate_count-live20261031-smoke01',
      'physical_event_timestamp':'copy-s2-physical_event_timestamp-live20261031-smoke02'}

class UnresolvedSealedSmoke(ValueError):
    pass


def verify_raw_files(raw: dict) -> dict:
    names={'aggregate.stdout.json','timed.stdout.json'} | {v+'.json' for v in ARMS.values()}
    if set(raw)!=names or len(raw)!=4:
        raise UnresolvedSealedSmoke('incomplete or additional original bytes')
    pairs={}
    for arm,run_id in ARMS.items():
        receipt_file=('aggregate' if arm=='aggregate_count' else 'timed')+'.stdout.json'
        try:
            receipt=json.loads(raw[receipt_file]); original=raw[run_id+'.json']; doc=json.loads(original)
        except (KeyError,ValueError,TypeError) as e:
            raise UnresolvedSealedSmoke('invalid original result or receipt') from e
        if (receipt.get('sha256')!=hashlib.sha256(original).hexdigest() or
                receipt.get('bytes')!=len(original) or
                receipt.get('run_id')!=run_id or
                receipt.get('readback_verified') is not True or
                receipt.get('create_only') is not True or
                receipt.get('scientific_superiority_certified') is not False or
                receipt.get('production_activation') is not False or
                receipt.get('all_scientific_blockers_closed') is not False or
                receipt.get('provenance_authenticated') is not False):
            raise UnresolvedSealedSmoke('receipt or original bytes mismatch')
        result=doc.get('result',{})
        if (doc.get('run_id')!=run_id or doc.get('schema')!='hcsn-p2-create-only-run-evidence-v1' or
                doc.get('production_activation') is not False or
                doc.get('all_scientific_blockers_closed') is not False or
                doc.get('provenance_authenticated') is not False or
                result.get('run_id')!=run_id or result.get('task')!='copy' or
                result.get('seed')!=2 or result.get('arm')!=arm or
                result.get('reached_cpu_budget') is not True or
                result.get('reached_step_cap') is not False or
                not 25<=result.get('training_cpu_seconds',0)<26.25 or
                type(result.get('optimizer_steps')) is not int or
                not 0<result['optimizer_steps']<8000):
            raise UnresolvedSealedSmoke('false pairing, budget or scientific authority')
        pairs[arm]=result
    a,b=(pairs[arm] for arm in ('aggregate_count','physical_event_timestamp'))
    for field in ('initial_model_sha256','train_data_sha256','source_sha256'):
        if not a.get(field) or a[field]!=b.get(field):
            raise UnresolvedSealedSmoke('unmatched model/stream/source identity')
    for field in ('id','ood'):
        for key in ('data_sha256','queries','total_events','multi_fire_streams'):
            if a[field][key]!=b[field][key]:
                raise UnresolvedSealedSmoke('unmatched heldout streams')
    rel_cpu=abs(a['training_cpu_seconds']-b['training_cpu_seconds'])/max(a['training_cpu_seconds'],b['training_cpu_seconds'])
    if rel_cpu>0.05:
        raise UnresolvedSealedSmoke('CPU budget mismatch')
    return {'archive_original_bytes_verified':True,'records':2,
            'training_cpu_relative_gap':rel_cpu,
            'aggregate_steps':a['optimizer_steps'],'timed_steps':b['optimizer_steps'],
            'aggregate_ood':a['ood']['accuracy'],'timed_ood':b['ood']['accuracy'],
            'timed_minus_aggregate_ood_pp':100*(b['ood']['accuracy']-a['ood']['accuracy']),
            'full_model_training_replayed_by_auditor':False,
            'independent_sci_confirmation':False,
            'provenance_authenticated':False,
            'production_activation':False,
            'all_scientific_blockers_closed':False}


def audit_bundle(bundle_path: Path) -> dict:
    try:
        data=Path(bundle_path).read_text(encoding='ascii')
        compressed=base64.b64decode(data.strip(),validate=True)
        if hashlib.sha256(compressed).hexdigest()!=ARCHIVE_SHA256 or len(compressed)>15000:
            raise UnresolvedSealedSmoke('bundle gzip hash or limit mismatch')
        tar=gzip.decompress(compressed)
        if len(tar)>50000:
            raise UnresolvedSealedSmoke('bundle inflated length exceeds limit')
        with tarfile.open(fileobj=io.BytesIO(tar),mode='r:') as t:
            entries=t.getmembers()
            if any(not x.isfile() or x.name!=Path(x.name).name or x.size>8000 for x in entries):
                raise UnresolvedSealedSmoke('unsafe/oversized/non-regular archive entry')
            if len({x.name for x in entries})!=len(entries):
                raise UnresolvedSealedSmoke('duplicate archive entry')
            original={x.name:t.extractfile(x).read() for x in entries}
    except (ValueError,OSError,EOFError,tarfile.TarError) as e:
        if isinstance(e,UnresolvedSealedSmoke):raise
        raise UnresolvedSealedSmoke('failed to decode original proof archive') from e
    return verify_raw_files(original)

if __name__=='__main__':
    print(json.dumps(audit_bundle(Path(__file__).with_name(ARCHIVE_FILE)),indent=2,sort_keys=True))
