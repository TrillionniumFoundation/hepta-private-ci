"""Write-once, self-checking P2 v2 trial receipts with atomic link publication.

Unlike Path.write_text, publication cannot overwrite an old trial even under
competing writers. A file is staged on the same filesystem, fsynced, hardlinked
into its create-only final name, directory-fsynced, and verified on read. An
incomplete stage after process death is NOT considered a published trial.
This is crash-*consistency engineering* in a local filesystem, not immunity to
malicious privileged mutation, remote durability, source authentication, or a
scientific training/negative-transfer fix.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat

SCHEMA = 'hcsn-p2-timed-cpu-matched-followup-v2'
ENVELOPE = 'hcsn-p2-immutable-trial-receipt-v1'
SEAL_SCHEMA = 'hcsn-p2-immutable-twelve-trial-seal-v1'
TASKS = ('copy','mqar4')
SEEDS = (2,3,4)
ARMS = ('aggregate_count','physical_event_timestamp')
MAX_BYTES = 1_000_000


class UnresolvedReceipt(ValueError):
    pass


@dataclass(frozen=True)
class Receipt:
    key: str
    payload_sha256: str
    file_sha256: str
    bytes: int
    production_activation: bool = False
    scientific_gate_closed: bool = False


def _canonical(obj):
    try:
        data = (json.dumps(obj, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False)+'\n').encode('ascii')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise UnresolvedReceipt('noncanonical or nonfinite evidence') from exc
    if len(data) > MAX_BYTES:
        raise UnresolvedReceipt('oversized trial evidence')
    return data


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _key(rec):
    if not isinstance(rec,dict) or rec.get('schema') != SCHEMA:
        raise UnresolvedReceipt('unexpected trial schema')
    task,seed,arm=rec.get('task'),rec.get('seed'),rec.get('arm')
    if task not in TASKS or type(seed) is not int or seed not in SEEDS or arm not in ARMS:
        raise UnresolvedReceipt('unregistered task, seed or arm')
    if (rec.get('production_activation') is not False or
        rec.get('all_scientific_blockers_closed') is not False or
        rec.get('unblinded_exploratory_followup') is not True or
        rec.get('negative_evidence_retained') is not True or
        rec.get('params') != 5186 or
        rec.get('reached_step_cap') is not False or
        rec.get('reached_cpu_budget') is not True):
        raise UnresolvedReceipt('invalid cost/authority/scientific flags')
    cpu=rec.get('training_cpu_seconds')
    if type(cpu) not in (int,float) or not math.isfinite(cpu) or not 25<=cpu<=26.25:
        raise UnresolvedReceipt('invalid actual process CPU budget')
    for name in ('initial_model_sha256','trained_model_sha256','train_data_sha256'):
        v=rec.get(name)
        if type(v) is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
            raise UnresolvedReceipt('unverified training digest shape')
    if not all(isinstance(rec.get(k),dict) for k in ('id','ood')):
        raise UnresolvedReceipt('missing ID or OOD evidence')
    return f'{task}.{seed}.{arm}'


def _dir(root):
    root=Path(root)
    if root.is_symlink():
        raise UnresolvedReceipt('symlinked evidence root refused')
    root.mkdir(parents=True,exist_ok=True)
    records=root/'records'
    if records.is_symlink():
        raise UnresolvedReceipt('symlinked records directory refused')
    records.mkdir(exist_ok=True)
    if not records.is_dir():
        raise UnresolvedReceipt('not a directory')
    return records


def _atomic_create(records, final_name, data, *, crash_hook=None):
    """Atomic create-only, with test-only hook for real subprocess death."""
    if '/' in final_name or final_name.startswith('.') or '\x00' in final_name:
        raise UnresolvedReceipt('invalid create-only final name')
    fd=os.open(records,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    stage='.stage-'+secrets.token_hex(16)
    staged=False; published=False
    try:
        h=os.open(stage,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                  0o600,dir_fd=fd)
        staged=True
        try:
            with os.fdopen(h,'wb',closefd=True) as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            raise
        if crash_hook is not None:
            crash_hook('after_file_fsync')
        try:
            os.link(stage,final_name,src_dir_fd=fd,dst_dir_fd=fd,
                    follow_symlinks=False)
        except FileExistsError as exc:
            raise UnresolvedReceipt('trial already exists; overwrite forbidden') from exc
        published=True
        if crash_hook is not None:
            crash_hook('after_create_only_link')
        os.fsync(fd)
        os.unlink(stage,dir_fd=fd)
        staged=False
        os.fsync(fd)
    finally:
        # Only clean a stage when there is no committed final or exception.
        # A hard process kill skips this cleanup, preserving an audit-visible
        # orphan while leaving the final path absent (or fully written).
        if staged and crash_hook is None:
            try: os.unlink(stage,dir_fd=fd)
            except FileNotFoundError: pass
        os.close(fd)
    return published


def publish(root, record, *, crash_hook=None) -> Receipt:
    """Publish a registered training result without modifying existing bytes."""
    key=_key(record)
    raw=_canonical(record)
    envelope={'schema':ENVELOPE,'key':key,
              'payload_sha256':_sha(raw),'record':record,
              'production_activation':False,'scientific_gate_closed':False}
    data=_canonical(envelope)
    records=_dir(root)
    _atomic_create(records,key+'.json',data,crash_hook=crash_hook)
    return Receipt(key,_sha(raw),_sha(data),len(data))


def _read_exact(records,filename):
    fd=os.open(records,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        try:
            f=os.open(filename,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        except (FileNotFoundError,OSError) as exc:
            raise UnresolvedReceipt('missing or nonregular immutable trial') from exc
        with os.fdopen(f,'rb') as handle:
            info=os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES or info.st_nlink!=1:
                raise UnresolvedReceipt('unexpected trial inode/size/link count')
            raw=handle.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise UnresolvedReceipt('oversized immutable trial')
        return raw
    finally:
        os.close(fd)


def read(root,key):
    """Reject altered, malformed, duplicate-key or noncanonical evidence."""
    if key not in {f'{t}.{s}.{a}' for t in TASKS for s in SEEDS for a in ARMS}:
        raise UnresolvedReceipt('unregistered receipt name')
    records=_dir(root)
    raw=_read_exact(records,key+'.json')
    try:
        entry=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise UnresolvedReceipt('corrupt immutable JSON') from exc
    if (_canonical(entry)!=raw or not isinstance(entry,dict) or
        entry.get('schema')!=ENVELOPE or entry.get('key')!=key or
        entry.get('production_activation') is not False or
        entry.get('scientific_gate_closed') is not False):
        raise UnresolvedReceipt('noncanonical or untrusted receipt envelope')
    record=entry.get('record')
    if _key(record)!=key or _sha(_canonical(record))!=entry.get('payload_sha256'):
        raise UnresolvedReceipt('receipt does not bind its registered record')
    return Receipt(key,entry['payload_sha256'],_sha(raw),len(raw)),record


def audit(root, *, require_complete=True):
    """Detect stage or extra files; verify all published records on new read."""
    records=_dir(root)
    present={p.name for p in records.iterdir()}
    expected={f'{t}.{s}.{a}.json' for t in TASKS for s in SEEDS for a in ARMS}
    if present-expected:
        raise UnresolvedReceipt('unexpected files, symlinks or crash-stage orphans')
    if require_complete and present != expected:
        raise UnresolvedReceipt('missing a registered 12-run trial')
    results=[]
    for name in sorted(present):
        receipt,_=read(root,name[:-5])
        results.append(receipt)
    return tuple(results)


def seal(root):
    """Publish an immutable twelve-file manifest after strict read-back audit."""
    results=audit(root)
    records=_dir(root)
    index={'schema':SEAL_SCHEMA,
           'entries':[{'key':r.key,'file_sha256':r.file_sha256,
                       'payload_sha256':r.payload_sha256} for r in results],
           'record_count':12,'production_activation':False,
           'all_scientific_blockers_closed':False}
    data=_canonical(index)
    # Seal is deliberately in parent directory, not within records.
    _atomic_create(Path(root),'seal.json',data)
    return _sha(data)


def verify_seal(root):
    """Check a historical sealed snapshot in a new process, no silent repair."""
    raw=_read_exact(Path(root),'seal.json')
    try: doc=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise UnresolvedReceipt('corrupted seal') from exc
    if (_canonical(doc)!=raw or doc.get('schema')!=SEAL_SCHEMA or
        doc.get('record_count')!=12 or
        doc.get('production_activation') is not False or
        doc.get('all_scientific_blockers_closed') is not False):
        raise UnresolvedReceipt('invalid sealed evidence')
    receipts=audit(root)
    current=[{'key':r.key,'file_sha256':r.file_sha256,
              'payload_sha256':r.payload_sha256} for r in receipts]
    if current!=doc.get('entries'):
        raise UnresolvedReceipt('sealed evidence changed after publication')
    return {'sealed_sha256':_sha(raw),'record_count':12,
            'all_records_unchanged':True,
            'production_activation':False,'all_scientific_blockers_closed':False}


def recover_stages(root, *, quiescent: bool):
    """Explicit post-crash reconciliation; caller guarantees no active writers.

    Linked self-checking stages are finalized by unlinking the old hardlink;
    uncommitted self-checking stages are moved to *quarantine* and never
    silently promoted to published training outcomes. No automatic recovery
    is attempted while producers could be concurrently publishing.
    """
    if quiescent is not True:
        raise UnresolvedReceipt('explicit quiescent writer state required')
    records=_dir(root)
    names=sorted(p.name for p in records.iterdir() if p.name.startswith('.stage-'))
    if not names:
        return ()
    fd=os.open(records,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    outcomes=[]
    try:
        for name in names:
            suffix=name[7:]
            if len(suffix)!=32 or any(c not in '0123456789abcdef' for c in suffix):
                raise UnresolvedReceipt('unexpected malformed stage name')
            f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
            with os.fdopen(f,'rb') as handle:
                info=os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES
                        or not 1<=info.st_nlink<=2):
                    raise UnresolvedReceipt('bad staged inode or size')
                raw=handle.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise UnresolvedReceipt('oversized staged evidence')
            try:
                entry=json.loads(raw)
            except (ValueError,UnicodeError) as exc:
                raise UnresolvedReceipt('noncanonical staged evidence') from exc
            if (not isinstance(entry,dict) or _canonical(entry)!=raw or
                entry.get('schema')!=ENVELOPE or
                entry.get('production_activation') is not False or
                entry.get('scientific_gate_closed') is not False):
                raise UnresolvedReceipt('invalid staged evidence envelope')
            rec=entry.get('record')
            key=_key(rec)
            if entry.get('key')!=key or entry.get('payload_sha256')!=_sha(_canonical(rec)):
                raise UnresolvedReceipt('staged record binding mismatch')
            final=key+'.json'
            try:
                current=os.stat(final,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:
                current=None
            if current is not None:
                if (current.st_ino!=info.st_ino or current.st_dev!=info.st_dev
                        or not stat.S_ISREG(current.st_mode)):
                    raise UnresolvedReceipt('stage and committed final diverge')
                os.unlink(name,dir_fd=fd)
                os.fsync(fd)
                outcomes.append((key,'FINALIZED_ALREADY_LINKED'))
            else:
                quarantine=Path(root)/'quarantine'
                if quarantine.is_symlink():
                    raise UnresolvedReceipt('symlinked quarantine refused')
                quarantine.mkdir(exist_ok=True)
                dst=quarantine/name
                if dst.exists():
                    raise UnresolvedReceipt('quarantine collision')
                os.rename(records/name,dst)
                qfd=os.open(quarantine,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try: os.fsync(qfd)
                finally: os.close(qfd)
                os.fsync(fd)
                outcomes.append((key,'QUARANTINED_UNCOMMITTED'))
    finally:
        os.close(fd)
    return tuple(outcomes)
