"""Bounded identities and pre-test selection. No Torch, test data, fit or solver."""
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import stat
import zipfile

SEEDS = (47, 83, 137)
ACTORS = (5, 6, 11, 12, 21, 22)
CAPS = dict(forwards=7, body_ticks=42, paired_queries=336, backwards=0,
            optimizer_steps=0, analytic_solves=0, trace_linear_replays=0,
            scalar_inverse_targets=0)
SLOTS47 = ('ANALYTIC_ROLE_025', 'ANALYTIC_ROLE_100', 'BP_TASK_4',
           'BP_TASK_16', 'WRONG_ROLE', 'RANDOM')
SLOTST = ('RERUN_PROGRAM_025', 'RERUN_PROGRAM_100', 'COPY_SOURCE_DELTA_025',
          'COPY_SOURCE_DELTA_100', 'BP_TASK_4', 'BP_TASK_16')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def save(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write(path, value):
    save(path, encoded(value))


def checked(raw, item):
    if len(raw) != item['bytes'] or sha(raw) != item['sha256']:
        raise ValueError('exact frozen bytes differ')
    return raw


def source_check(binding, here, helper, transfer):
    for directory, group in ((here, 'adapter_files'), (helper, 'helper_files'),
                             (transfer, 'transfer_files')):
        for name, item in binding[group].items():
            checked((directory/name).read_bytes(), item)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bounded_zip(raw, items, member_cap=2097152, total_cap=16777216):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    if len(names) != len(set(names)) or set(names) != set(items):
        raise ValueError('complete ZIP member allowlist differs')
    total = 0
    for item in archive.infolist():
        path, mode = Path(item.filename), item.external_attr >> 16
        if (path.is_absolute() or '..' in path.parts or item.is_dir() or
                item.file_size > member_cap or stat.S_ISLNK(mode) or
                stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
            raise ValueError('unsafe bounded ZIP member')
        total += item.file_size
        if total > total_cap:
            raise ValueError('aggregate decompressed ZIP cap')
    return archive


def admit_archive(path, item):
    raw = checked(Path(path).read_bytes(), item)
    archive = bounded_zip(raw, item['files'])
    for name, spec in item['files'].items():
        checked(archive.read(name), spec)
    return archive


def safe_prefix(prefix):
    path = Path(prefix)
    if path.is_absolute() or '..' in path.parts or not prefix or prefix.endswith('/'):
        raise ValueError('unsafe evidence prefix')
    return prefix


def selection_for_parent(seed, manifest, result, seal, qualification, choose):
    """Run the exact imported frozen selector using only existing selection rows."""
    slots = SLOTS47 if seed == 47 else SLOTST
    expected_status = {47:'COMPLETED', 83:'PARENT_COMPLETED', 137:'REPAIR_COMPLETED'}[seed]
    if qualification.get('passed') is not True or qualification.get('decision_disagreements') != 0:
        raise ValueError('existing exact-parent CPU producer qualification did not pass')
    family, method = ('SENDER_ROLE', 'ANALYTIC_ROLE') if seed == 47 else ('BOUNDARY_PROGRAM', 'RERUN_PROGRAM')
    if result['status'] != expected_status:
        # A failed implementation is never silently converted to a successful
        # KEEP-selected scientific method. The parent baseline remains defined.
        if seed != 137:
            raise ValueError('already fixed predecessor changed its terminal status')
        return dict(seed=seed, family=family, source_method=method,
            original_status=result['status'], slots=list(slots), slot_results=result.get('completed_evaluations', []),
            methods={name:dict(status='UNAVAILABLE', selected=None,
                reason='NO_COMPLETE_REPAIR_SELECTION') for name in ('METHOD','BP')},
            unique_evaluations=[dict(name='KEEP', checkpoint_sha256=manifest['checkpoint']['sha256'],
                parameter_sha256=None, source='PUBLIC_PARENT')],
            original_selection_unavailable=True)
    if seed == 137 and (result['fresh_parent_parity'].get('passed') is not True or
                        result['fresh_parent_parity'].get('decision_disagreements') != 0):
        raise ValueError('independent repair did not preserve qualified parent parity')
    rows = result['evaluations']
    if len(rows) != 7 or [row['name'] for row in rows] != ['KEEP', *slots]:
        raise ValueError('original planned denominator or declaration order differs')
    keep = rows[0]
    if keep.get('protection_passed') is not True or keep['norm'] != 0 or keep['declaration_index'] != 0:
        raise ValueError('original KEEP row differs')
    records = seal['records']
    for index, row in enumerate(rows):
        if row['declaration_index'] != index:
            raise ValueError('original declaration index differs')
        if row.get('status') == 'UNAVAILABLE':
            if row['name'] in records:
                raise ValueError('unavailable slot has a published candidate record')
            continue
        if row.get('status', 'EVALUATED') != 'EVALUATED':
            raise ValueError('unknown evaluation row status')
        if type(row['protection_passed']) is not bool or not math.isfinite(row['norm']) or row['norm'] < 0:
            raise ValueError('invalid original gate or realized norm')
        for split, n in (('train',80),('dev',32),('retain',28)):
            metric = row[split]
            if (metric['n'] != n or type(metric['correct']) is not int or
                    not 0 <= metric['correct'] <= n or
                    any(not math.isfinite(metric[k]) for k in ('accuracy','brier','ce')) or
                    metric['accuracy'] != metric['correct']/n):
                raise ValueError('invalid original selection metric')
        if index and (row['name'] not in records or records[row['name']]['norm'] != row['norm']):
            raise ValueError('original candidate record does not bind evaluated row')
    methods = {}
    unique = [dict(name='KEEP', checkpoint_sha256=manifest['checkpoint']['sha256'],
                   parameter_sha256=None, source='PUBLIC_PARENT')]
    for role, source_method in (('METHOD',method),('BP','BP_TASK')):
        available = [row for row in rows[1:] if row['name'].startswith(source_method+'_')
                     and row.get('status', 'EVALUATED') == 'EVALUATED']
        winner = choose([keep]+[row for row in available if row['protection_passed']])
        original = result['selection'][source_method]
        if winner['name'] != original['selected']:
            raise ValueError('exact original frozen selector disagrees with reported selection')
        if seed in (47,83) and winner['name'] != ('KEEP' if role=='METHOD' else 'BP_TASK_16'):
            raise ValueError('already fixed pre-test47/83 choice changed')
        methods[role] = dict(status='SELECTED_BEFORE_TEST', source_method=source_method,
            selected=winner['name'], evaluated_candidates=len(available), planned_candidate_slots=2,
            original_availability=original.get('status','AVAILABLE'),
            fallback_keep=winner['name']=='KEEP', edited_model_selected=winner['name']!='KEEP',
            original_development_signal=original['development_signal'])
        if winner['name'] != 'KEEP':
            record = records[winner['name']]
            item = dict(name=winner['name'], checkpoint_sha256=record['checkpoint_sha256'],
                parameter_sha256=record['parameter_sha256'], source='EXACT_PREDECESSOR_ARTIFACT')
            if not any((v['checkpoint_sha256'],v['parameter_sha256']) ==
                       (item['checkpoint_sha256'],item['parameter_sha256']) for v in unique):
                unique.append(item)
            else:
                methods[role]['reused_evaluation_name'] = next(v['name'] for v in unique if
                    (v['checkpoint_sha256'],v['parameter_sha256']) ==
                    (item['checkpoint_sha256'],item['parameter_sha256']))
    cap = 2 if seed in (47,83) else 3
    if len(unique)>cap:
        raise ValueError('pre-test unique-checkpoint budget exceeded')
    return dict(seed=seed, family=family, source_method=method, original_status=result['status'],
        slots=list(slots), slot_results=rows[1:], methods=methods, unique_evaluations=unique,
        source_result_counts=result['counts'], original_selection_unavailable=False)


def selection_from_archives(binding, manifests, archives, choose):
    parents=[]
    for seed in SEEDS:
        item = binding['parent_evidence'][str(seed)]
        archive = archives[item['artifact_key']]
        prefix = safe_prefix(item['prefix'])
        result = json.loads(archive.read(prefix+'/RESULT.json'))
        qitem=item['qualification']
        qualification=json.loads(archives[qitem['artifact_key']].read(qitem['member']))
        seal = (json.loads(archive.read(prefix+'/CANDIDATES_SEALED.json'))
                if prefix+'/CANDIDATES_SEALED.json' in archive.namelist() else {})
        row = selection_for_parent(seed, manifests[seed], result, seal, qualification, choose)
        row.update(source_artifact_key=item['artifact_key'], source_prefix=prefix,
                   source_result_sha256=sha(archive.read(prefix+'/RESULT.json')),
                   qualification=qitem)
        for selected in row['unique_evaluations']:
            if selected['source'] == 'PUBLIC_PARENT':
                continue
            name=selected['name']
            pt,values=archive.read(prefix+'/'+name+'.pt'),archive.read(prefix+'/'+name+'.f32le')
            if sha(pt)!=selected['checkpoint_sha256'] or len(values)!=160 or sha(values)!=selected['parameter_sha256']:
                raise ValueError('selected full candidate/actual40 byte identity differs')
            selected.update(checkpoint_bytes=len(pt), parameter_bytes=len(values))
        parents.append(row)
    n=sum(len(row['unique_evaluations']) for row in parents)
    if n>7:
        raise ValueError('aggregate pre-test checkpoint cap')
    return dict(schema='hepta.locked-historical-test-selection.v1', name='LOCKED_HISTORICAL_TEST_AUDIT',
        selection_uses_test=False, new_holdout=False, parent_order=list(SEEDS), parents=parents,
        unique_checkpoints=n, planned_forwards=n, planned_body_ticks=6*n, planned_paired_queries=48*n,
        all_failed_and_missing_source_slots_retained=True)
