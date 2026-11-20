"""Collect fixed resume2/template bytes only; execute no recovery or controls."""
import collections
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path('/workspace/scratch/e9e051ab0825')
D = ROOT / 'metrics_integration/execution-readout-intake-diagnostic-6'
spec = importlib.util.spec_from_file_location('intake_helpers', D / 'prepare_input_index.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
OUT = D / 'input-index-preparation-3'


def dump(name, value):
    with (OUT / name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    OUT.mkdir(exist_ok=False)
    previous = []
    parent_pins = []
    for name in ['input-index-preparation-1/CURRENT_INPUT_INDEX.json',
                 'input-index-preparation-2/ADDITIONAL_INPUT_INDEX.json']:
        j, pin = h.get_json(D / name)
        previous.extend(j['files'])
        parent_pins.append(pin)
    assert len(previous) == 509 and len({x['workspace_path'] for x in previous}) == 509
    prior_by_key = collections.defaultdict(list)
    for row in previous:
        prior_by_key[h.key(row)].append(row)
    rows = {}
    manifests = []
    symlinks = []

    def add(path, group, expected=None):
        _, pin = h.read_file(path)
        if expected:
            for k in ['bytes', 'sha256', 'git_blob']:
                if k in expected:
                    assert pin[k] == expected[k]
        row = rows.setdefault(pin['workspace_path'], {**pin, 'groups': []})
        assert h.same_identity(row, pin)
        if group not in row['groups']:
            row['groups'].append(group)

    def add_manifest(dirname, group, extras):
        base = ROOT / dirname
        doc, pin = h.get_json(base / 'REVIEW_MANIFEST.json')
        add(base / 'REVIEW_MANIFEST.json', group)
        for row in doc['files']:
            p = Path(row['path'])
            assert not p.is_absolute() and '..' not in p.parts
            add(base / p, group, row)
        for name in extras:
            add(base / name, group)
        manifests.append({'manifest': pin, 'members_verified': len(doc['files']),
                          'named_root_readbacks_outside_original_manifest': list(extras)})
        return doc, pin

    dirname = 'e6_owner_work/historical_startup_recovery/material_resume_2'
    resume, resume_pin = add_manifest(dirname, 'resume2_static_candidate_not_executed',
                       ['ROOT_BINDING_READBACK.json', 'ROOT_PARTIAL_METADATA_READBACK.json'])
    assert resume_pin['sha256'] == 'c94beb3acad83e6660a793ad3445eff9ea954971cbbbe0418b478b5179b5b930'
    for p in sorted((ROOT / dirname / 'offline-controls-1').rglob('*')):
        if p.is_symlink():
            s = p.lstat()
            symlinks.append({'workspace_path': str(p.relative_to(ROOT)),
                             'kind': 'symlink', 'literal_link_target': os.readlink(p),
                             'mode': s.st_mode, 'bytes': s.st_size, 'target_opened': False})
        elif p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            add(p, 'existing_offline_mechanism_fixture_no_rerun')
    fmt, fmt_pin = add_manifest('e6_owner_work/historical_startup_format/rev2',
                               'format_template2_not_actual_format', ['ROOT_TEMPLATE_DELTA_REVIEW.json'])
    assert fmt_pin['sha256'] == '53917e2e8da5b24d18b012f26e263ae65cb082391e3079cc75470f37f72a593f'
    add(ROOT / 'metrics_integration/AUTOMATION_PRE_RESUME2_PEEK.json', 'existing_root_automation_peek_no_new_scheduling_action')

    new_bodies = collections.defaultdict(list)
    checked_reuse = {}
    for row in rows.values():
        k = h.key(row)
        if k in prior_by_key:
            old = sorted(prior_by_key[k], key=lambda x:x['workspace_path'])[0]
            if old['workspace_path'] not in checked_reuse:
                _, observed = h.read_file(ROOT / old['workspace_path'])
                assert h.same_identity(old, observed)
                checked_reuse[old['workspace_path']] = old
            row['storage'] = {'kind': 'previous_preparatory_index_exact_body',
                              'prior_workspace_path': old['workspace_path'],
                              'qualification_inherited': False}
        else:
            row['storage'] = {'kind': 'new_local_original_body_not_yet_archived',
                              'body_id': row['sha256'], 'future_repository_path': None}
            new_bodies[k].append(row['workspace_path'])
    old_paths = {x['workspace_path'] for x in previous}
    assert not old_paths.intersection(rows)
    controls, control_pin = h.get_json(ROOT / dirname / 'offline-controls-1/RESULT.json')
    assert controls['passed'] is True and len(controls['controls']) == 11
    assert controls['host_actions'] == 0 and controls['network_requests'] == 0
    composition = {'previous_input_indexes': parent_pins, 'previous_logical_file_count': 509,
                   'additional_rows': len(rows), 'new_logical_paths': len(rows),
                   'composed_logical_file_count': 509 + len(rows),
                   'old_indexes_unchanged': True, 'final_pack_or_freeze': False}
    dump('ADDITIONAL_STATIC_INPUT_INDEX.json', {
        'status': 'FIXED_STATIC_SUCCESSOR_INPUTS_ONLY_NOT_EXECUTION_OR_FINAL_PACK',
        'composition': composition, 'files': sorted(rows.values(), key=lambda x:x['workspace_path']),
        'storage_counts': dict(collections.Counter(x['storage']['kind'] for x in rows.values())),
        'new_unique_body_count': len(new_bodies), 'new_unique_body_bytes': sum(k[0] for k in new_bodies),
        'synthetic_fixture_nonregular_metadata': symlinks,
        'oversized_originals_pending_exact_representation': [x['workspace_path'] for x in rows.values() if x['bytes'] > 480000],
        'host_network_git_control_test_compile_native_model_actions': 0,
    })
    dump('STATIC_SUCCESSOR_RECEIPT.json', {
        'status': 'STATIC_REVISION_INTAKE_NO_RUNTIME_SUCCESS_CLAIM',
        'manifest_checks': manifests, 'original_resume1_blocked_and_unexecuted_preserved': True,
        'review_manifest': resume_pin,
        'existing_offline_controls': {'result': control_pin, 'cases': 11,
            'wall_seconds': controls['wall_seconds'], 'reruns_by_this_reviewer': 0,
            'actual_material_or_https_qualification': False},
        'review_claim': 'Private transport error boundaries and fatal-stop-before-log are proposed in a separate revision; independent successor peer and actual runtime are separate receipts.',
        'successor_peer': None, 'actual_material_owner': None, 'actual_material_result': None,
        'actual_format_result_and_seal': None, 'actual_compile': None,
        'fmt_template': fmt_pin,
        'limitations': ['Root partial readback is metadata comparison, not a new read of partial bodies.',
                        'Format template output2 path and static candidate bytes are not actual material result/seal pins.'],
        'old_557_and_formal_reports_not_written': True, 'pack_executed': False,
    })
    print(json.dumps({'output': str(OUT), 'composition': composition,
                     'new_unique_body_count': len(new_bodies),
                     'new_unique_body_bytes': sum(k[0] for k in new_bodies)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
