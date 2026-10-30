"""Read-only consistency inventory of interrupted BOUNDED-LOCAL receipts.

No payload/config/source imports, live-process probes, locks, writes or dispatch.
Local hashes bind records, not authenticated execution or permission to replay.
"""
from decimal import Decimal
import hashlib
import importlib.util
import os
from pathlib import Path
import re

_SUPPORT = Path(__file__).resolve().parent.parent / 'local-accounting-batch' / 'support.py'
_code = _SUPPORT.read_bytes()
if hashlib.sha256(_code).hexdigest() != '38f886ba9ef875e3b249750202ba893b86b1aa9a70ce38cd4397437ecdce94d0':
    raise ValueError('exact reviewed accounting support required')
_spec = importlib.util.spec_from_file_location('_recovery_support', _SUPPORT)
support = importlib.util.module_from_spec(_spec)
exec(compile(_code, str(_SUPPORT), 'exec'), support.__dict__)
NO_DESCENDANTS = 'forbidden-by-reviewed-worker-contract-not-os-isolation'
MAX_SEGMENTS = 4096
MAX_FILE_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 32 * 1024 * 1024


def reference(value):
    if type(value) is not dict or set(value) != {'path', 'sha256'}:
        raise ValueError('exact metadata reference required')
    if type(value['path']) is not str:
        raise ValueError('reference path must be text')
    support.digest(value['sha256'])
    return value


def identity(value):
    if (type(value) is not dict or set(value) != {'pid', 'birth_ticks', 'boot_id', 'pid_namespace'}
        or type(value['pid']) is not int or value['pid'] <= 0
        or type(value['birth_ticks']) is not int or value['birth_ticks'] < 0
        or any(type(value[k]) is not str or not 0 < len(value[k]) <= 256 for k in ('boot_id', 'pid_namespace'))):
        raise ValueError('exact nonboolean process-birth identity required')
    return tuple(value[k] for k in ('boot_id', 'pid_namespace', 'pid', 'birth_ticks'))


def _exact_sum(values, *, digits=128):
    """Bounded decimal-to-integer scaling; ambient Decimal precision cannot round cost."""
    values = [support.number(x) for x in values]
    if not values:
        return Decimal(0)
    parts = [x.as_tuple() for x in values]
    if any(len(p.digits) > digits or not -128 <= p.exponent <= 128 for p in parts):
        raise ValueError('CPU decimal extent exceeds exact bounded policy')
    exponent = min(p.exponent for p in parts)
    total = sum(int(''.join(map(str, p.digits))) * 10 ** (p.exponent - exponent) for p in parts)
    return Decimal((0, tuple(map(int, str(total))), exponent))


class _ReadSet:
    """Bounded explicit metadata allowlist, detached within one call, never cached across calls."""
    def __init__(self, allowed):
        self.allowed = {str(p) for p in allowed}
        self.reads = {}
        self.bytes = 0

    def read(self, path):
        path = str(path)
        if path not in self.allowed:
            raise ValueError('not an allowlisted metadata path')
        if path in self.reads:
            return support.decode(self.reads[path])
        remaining = MAX_METADATA_BYTES - self.bytes
        if remaining <= 0:
            raise ValueError('metadata extent cap exceeded')
        raw = support.read(path, min(MAX_FILE_BYTES, remaining))
        self.bytes += len(raw)
        if self.bytes > MAX_METADATA_BYTES:
            raise ValueError('metadata extent cap exceeded')
        value = support.decode(raw)
        if type(value) is not dict:
            raise ValueError('metadata object required')
        self.reads[path] = raw
        return value

    def ref(self, path):
        self.read(path)
        return {'path': str(path), 'sha256': support.sha(self.reads[str(path)])}

    def checked(self, expected):
        reference(expected)
        value = self.read(expected['path'])
        if self.ref(expected['path']) != expected:
            raise ValueError('metadata reference changed')
        return value

    def recheck(self):
        # Observed consistency only, not an atomic snapshot or a fence against a live writer.
        for path, raw in self.reads.items():
            if support.read(path, MAX_FILE_BYTES) != raw:
                raise ValueError('metadata changed during inventory')


def _directory_names(path):
    if path.resolve() != path or path.is_symlink() or not path.is_dir():
        raise ValueError('canonical owned metadata directory required')
    values = []
    for child in path.iterdir():
        if len(values) >= MAX_SEGMENTS + 16:
            raise ValueError('bounded directory inventory required')
        if child.is_symlink():
            raise ValueError('metadata directory contains alias')
        values.append((child.name, child.is_dir()))
    return sorted(values)


def _wait(reader, root, segment, scope_ref, source, owner, scope_id):
    base = root / segment
    claim_path = root / 'claims' / segment / 'CLAIM.json'
    claim = reader.read(claim_path)
    claim_ref = reader.ref(claim_path)
    raw = reader.read(base / 'RAW_WAIT.json')
    bound = reader.read(base / 'BOUND_PROCESS.json')
    config_ref = reference(claim.get('config_ref'))  # Binding only: never open a config or payload.
    process_key = identity(raw.get('process'))
    if (claim.get('schema') != 'BOUNDED-LOCAL-CLAIM-v1' or claim.get('segment_id') != segment
        or claim.get('owner') != owner or claim.get('scope_ref') != scope_ref
        or claim.get('source_sha256') != source or claim.get('retry_allowed') is not False
        or raw.get('schema') != 'BOUNDED-LOCAL-RAW-WAIT-v1' or raw.get('segment_id') != segment
        or raw.get('scope_ref') != scope_ref or raw.get('source_sha256') != source
        or raw.get('owner') != owner or raw.get('claim_ref') != claim_ref or raw.get('config_ref') != config_ref
        or raw.get('complete_wait') is not True or raw.get('wait_scope') != 'owned-direct-child'
        or raw.get('descendants') != NO_DESCENDANTS
        or type(raw.get('fork_pid')) is not int or type(raw.get('waited_pid')) is not int
        or process_key == identity(owner) or raw['fork_pid'] != raw.get('waited_pid')
        or raw['fork_pid'] != raw['process']['pid'] or type(raw.get('exit_code')) is not int
        or type(raw.get('wait_status')) is not int or raw['wait_status'] < 0
        or not (os.WIFEXITED(raw['wait_status']) or os.WIFSIGNALED(raw['wait_status']))
        or os.waitstatus_to_exitcode(raw['wait_status']) != raw['exit_code']
        or bound.get('owner') != owner or bound.get('process') != raw['process'] or bound.get('claim_ref') != claim_ref
        or raw['process']['boot_id'] != owner['boot_id'] or raw['process']['pid_namespace'] != owner['pid_namespace']):
        raise ValueError('claim/source/config/owner/birth/actual wait joins failed')
    cpu = _exact_sum((raw['user_cpu_seconds'], raw['system_cpu_seconds']))
    row = {'segment_id': segment, 'status': 'WAITED_WITHOUT_SETTLEMENT',
           'reported_child_cpu_seconds': str(cpu), 'raw_wait': reader.ref(base / 'RAW_WAIT.json'),
           'claim': claim_ref, 'process': raw['process'], 'issue': None}
    if raw['exit_code'] != 0:
        row['status'] = 'WAITED_NONZERO'
    else:
        try:
            settlement = reader.read(base / 'SETTLEMENT.json')
            result_ref = reference(settlement.get('result'))
            if (settlement.get('schema') != 'BOUNDED-LOCAL-SETTLEMENT-v1'
                or settlement.get('status') != 'FULLY_WAITED_EXIT0' or settlement.get('segment_id') != segment
                or settlement.get('scope_ref') != scope_ref or settlement.get('source_sha256') != source
                or settlement.get('scope_id') != scope_id or settlement.get('wait_scope') != 'owned-direct-child'
                or settlement.get('descendants') != NO_DESCENDANTS
                or settlement.get('owner') != owner or settlement.get('process') != raw['process']
                or settlement.get('config_ref') != config_ref or settlement.get('raw_wait') != row['raw_wait']
                or support.number(settlement.get('child_cpu_seconds')) != cpu
                or result_ref['path'] != str(base / 'output' / 'RESULT.json')
                or raw.get('work_release_sent') is not True or raw.get('error') is not None
                or raw.get('cleanup_errors') != []):
                raise ValueError('settlement-to-wait metadata join failed')
            row['status'] = 'SETTLED_METADATA_ONLY'
            row['settlement'] = reader.ref(base / 'SETTLEMENT.json')
        except FileNotFoundError:
            row['issue'] = 'settlement absent; exact child wait remains paid'
        except (ValueError, KeyError, TypeError, OSError, ArithmeticError) as exc:
            row['status'] = 'WAITED_INVALID_SETTLEMENT'
            row['issue'] = str(exc)
    return row, process_key


def inspect_scope(scope_ref, expected_source_sha256):
    """Inspect only explicit metadata; always withhold whole scope and replay authority.

    Caller must provide the original pinned scope reference and source digest.
    Current PID absence, session disappearance and partial checkpoints are not inputs.
    A separately authorized new attempt must retain this uncertainty and its own lock.
    """
    reference(scope_ref)
    support.digest(expected_source_sha256)
    reader = _ReadSet([scope_ref['path']])
    scope = reader.checked(scope_ref)
    ids = scope.get('segment_ids')
    if (scope.get('schema') != 'BOUNDED-LOCAL-SCOPE-v1' or scope.get('production') is not False
        or type(scope.get('scope_id')) is not str or not 0 < len(scope['scope_id']) <= 256
        or scope.get('descendants') != NO_DESCENDANTS
        or type(ids) is not list or not 0 < len(ids) <= MAX_SEGMENTS
        or any(type(x) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,95}', x) is None for x in ids)
        or len(ids) != len(set(ids)) or reference(scope.get('source_manifest'))['sha256'] != expected_source_sha256):
        raise ValueError('exact bounded source/segment scope required')
    root = Path(scope['run_root'])
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('canonical original run root required')
    reader.allowed.add(str(root / 'OWNER.json'))
    for sid in ids:
        reader.allowed.add(str(root / 'claims' / sid / 'CLAIM.json'))
        reader.allowed.update(str(root / sid / n) for n in ('BOUND_PROCESS.json', 'RAW_WAIT.json', 'SETTLEMENT.json'))
    report = {'schema': 'LOCAL-RECOVERY-INVENTORY-v1', 'scope_ref': scope_ref,
              'source_sha256': expected_source_sha256, 'status': 'OBSERVED_METADATA_INVENTORY',
              'records': [], 'unknowns': [], 'reported_child_cpu_sum': '0',
              'parent_inclusive_cpu_seconds': None, 'whole_scope_complete': False,
              'current_liveness': 'UNKNOWN', 'payload_custody': 'NOT_READ_OR_VERIFIED',
              'execution_authenticity': 'LOCAL_RECORD_CONSISTENCY_ONLY',
              'automatic_resume_or_replay_allowed': False, 'unobserved_tail_possible': True}
    try:
        owner_record = reader.read(root / 'OWNER.json')
        owner = owner_record.get('owner'); identity(owner)
        if owner_record.get('schema') != 'BOUNDED-LOCAL-OWNER-v1' or owner_record.get('scope_ref') != scope_ref:
            raise ValueError('owner/scope join failed')
        claims = _directory_names(root / 'claims')
        roots = _directory_names(root)
        claimed = {name for name, directory in claims if directory}
        if any(not directory or name not in ids for name, directory in claims):
            report['unknowns'].append('unexpected claim entries')
        orphans = {name for name, directory in roots if directory and name != 'claims'} - claimed
        if orphans:
            report['unknowns'].append('orphan segment directories: ' + ','.join(sorted(orphans)))
        identities = {}; duplicate = set()
        for sid in ids:
            if sid not in claimed:
                continue
            try:
                row, key = _wait(reader, root, sid, scope_ref, expected_source_sha256, owner, scope['scope_id'])
                if key in identities:
                    duplicate.update((sid, identities[key]))
                identities[key] = sid
            except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
                row = {'segment_id': sid, 'status': 'UNKNOWN_OR_INVALID', 'reported_child_cpu_seconds': None,
                       'issue': str(exc)}
            report['records'].append(row)
        for row in report['records']:
            if row['segment_id'] in duplicate:
                row.update(status='DUPLICATE_PROCESS_IDENTITY', reported_child_cpu_seconds=None)
            if row['status'] != 'SETTLED_METADATA_ONLY':
                report['unknowns'].append(row['segment_id'] + ': ' + row['status'])
        reader.recheck()
        if claims != _directory_names(root / 'claims') or roots != _directory_names(root):
            raise ValueError('directory inventory changed during observation')
        report['reported_child_cpu_sum'] = str(_exact_sum((r['reported_child_cpu_seconds']
            for r in report['records'] if r['reported_child_cpu_seconds'] is not None), digits=512))
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        report['status'] = 'UNKNOWN_SNAPSHOT'
        report['unknowns'].append(str(exc))
        report['reported_child_cpu_sum'] = None
    report['metadata_reads'] = [{'path': p, 'sha256': support.sha(raw)} for p, raw in sorted(reader.reads.items())]
    report['metadata_bytes_read'] = reader.bytes
    return report


if __name__ == '__main__':
    import json
    import sys
    if len(sys.argv) != 4:
        raise SystemExit('usage: inventory.py SCOPE_PATH SCOPE_SHA256 ORIGINAL_SOURCE_SHA256')
    print(json.dumps(inspect_scope({'path': sys.argv[1], 'sha256': sys.argv[2]}, sys.argv[3]), sort_keys=True))
