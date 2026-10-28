"""Independent read-only review of sealed fixed-input diagnostic artifacts; no Torch."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import numpy as np


ROOT = Path('/workspace/scratch/e8a4dc33549f')
REPO = ROOT / 'hepta'
PORT = REPO / 'experiments/multimodal_output_portfolio'
SOURCE = PORT / 'field_bridge_v5_20261027_review/historical_fixed_inputs_20261028'
RUN = ROOT / 'v5_fixed_inputs_diagnostic_20261028'
FIRST = ROOT / 'v5_dispatch_diagnostic_20261028'
CASES = ('unset_before', 'default', 'avx2', 'avx512', 'unset_after')
OBSERVERS = ('reward', 'audit')
FIELDS = ('text_fact', 'relation', 'image_fact', 'crossmodal_disagreement', 'pixel_mse')
TENSORS = ('observation_pixels', 'observation_mask', 'observation_text_tokens',
           'target_pixels', 'target_text_tokens', 'target_labels', 'latent_noise')
OUTFIELDS = ('image_logits', 'text_logits', 'token_ids', 'digit_logits')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path):
    return {'bytes': Path(path).stat().st_size, 'sha256': sha(path)}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def load_npz(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
    with np.load(path, allow_pickle=False) as saved:
        assert len(saved.files) == len(set(saved.files))
        return {key: saved[key].copy() for key in saved.files}


def array_identity(value):
    assert value.flags.c_contiguous and np.isfinite(value).all()
    return {'dtype': value.dtype.str, 'shape': list(value.shape), 'bytes': value.nbytes,
            'sha256': hashlib.sha256(value.tobytes()).hexdigest()}


def compare(left, right):
    assert left.dtype == right.dtype and left.shape == right.shape
    assert np.isfinite(left).all() and np.isfinite(right).all()
    mask, delta = left != right, left - right
    return {'exact': bool(np.array_equal(left, right)), 'bitwise_exact': array_identity(left) == array_identity(right),
            'shape': list(left.shape), 'dtype': str(left.dtype), 'different_values': int(mask.sum()),
            'max_abs_difference': float(np.abs(delta).max()), 'mean_difference': float(delta.mean()),
            'indices': np.argwhere(mask).tolist(), 'left': left[mask].tolist(), 'right': right[mask].tolist(),
            'delta': delta[mask].tolist(), 'convention': 'left minus right', 'tolerance': None}


def compact(left, right):
    value = compare(left, right)
    return {**{key: value[key] for key in ('exact', 'bitwise_exact', 'different_values',
              'max_abs_difference', 'mean_difference')},
            'different_rows': int(np.any(left != right, axis=0).sum()),
            'observer_mean_difference': (left - right).mean(axis=1).tolist(),
            'both_observer_delta_vectors_identical': bool(np.array_equal((left - right)[0], (left - right)[1]))}


def main():
    protocol = read(SOURCE / 'PROTOCOL.json')
    summary = read(RUN / 'SUMMARY.json')
    summary_identity = identity(RUN / 'SUMMARY.json')
    assert summary['execution_complete'] and summary['diagnostic_interpretable']
    assert summary['scientific_status'] == 'FAIL' and not summary['admission']
    assert summary['historical_raw_file_recovered'] is False and summary['historical_gate_changed'] is False
    assert not summary['new_holdout_authorized'] and summary['raw_upload_attempts'] == 0
    assert summary['selected_capability'] is None and summary['error'] is None
    sources = summary['source_registration']
    assert sources['commit'] == '8e09fee8a59f2de40acbb2595f01f648fe8b1ed8'
    assert len(sources['files']) == 6
    for name, expected in sources['files'].items():
        path = REPO / name
        raw = path.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert expected == {'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': blob}
        tree = subprocess.check_output(['git', 'ls-tree', sources['commit'], '--', name], cwd=REPO,
            env={**os.environ, 'GIT_NO_LAZY_FETCH': '1'}, text=True).strip()
        assert tree == '100644 blob ' + blob + '\t' + name
    roots = {'repository': REPO, 'run': ROOT / 'v5_run', 'assets': ROOT / 'assets_v5/original',
             'runtime': ROOT / 'runtime_v5', 'first_attempt': FIRST, 'workspace': ROOT}
    inputs = {}
    for name, record in protocol['inputs'].items():
        path = roots[record['root']] / record['path']
        assert identity(path) == {key: record[key] for key in ('bytes', 'sha256')}
        inputs[name] = path
    freeze = read(inputs['scientific_source_freeze'])['files']
    assert len(freeze) == 64
    for name, expected in freeze.items():
        assert sha(PORT / name) == expected
    assert read(inputs['original_failed_audit'])['integrity_status'] == 'FAIL'
    first_summary = read(inputs['first_attempt_summary'])
    assert not first_summary['execution_complete'] and not first_summary['diagnostic_interpretable']
    registration, start = read(RUN / 'REGISTRATION.json'), read(RUN / 'START.json')
    assert registration['source_registration'] == start['source_registration'] == sources
    assert registration['protocol_sha256'] == start['protocol_sha256'] == sha(SOURCE / 'PROTOCOL.json')
    assert registration['cases'] == start['cases'] == list(CASES)
    assert registration['cpuinfo_sha256'] == sha(RUN / 'CPUINFO.txt')
    preparation = read(RUN / 'prepare/RESULT.json')
    assert preparation == summary['preparation']['result'] and preparation['status'] == 'COMPLETE'
    assert identity(RUN / 'prepare/RESULT.json') == summary['preparation']['result_file'] == start['preparation_result']
    assert preparation['model_instances'] == preparation['model_calls'] == 0
    assert preparation['resources'] == preparation['independent_call_profile'] == {}
    assert preparation['forbidden_calls'] == [] and preparation['observed_capability'] == 'AVX512'
    assert preparation['parent_record_sha256'] == sha(RUN / 'REGISTRATION.json')
    manifest_path = RUN / 'input_snapshot/MANIFEST.json'
    assert identity(manifest_path) == start['input_manifest'] == preparation['snapshot']['manifest']
    manifest = read(manifest_path)
    assert manifest['source_registration'] == sources and manifest['model_calls'] == 0
    assert manifest['all_input_sha256'] == start['all_input_sha256'] == hashlib.sha256(canonical(manifest['batches'])).hexdigest()
    panels = read(inputs['current_panel_identities'])
    assert manifest['panel_identities'] == panels
    assert [(r['panel'], r['batch_index']) for r in manifest['batches']] == [(name, i) for name, count in (('task', 16), ('clean', 4)) for i in range(count)]
    snapshot_files, numeric_bytes = {'MANIFEST.json'}, 0
    for row in manifest['batches']:
        path = RUN / 'input_snapshot' / row['file']['path']
        snapshot_files.add(path.name)
        assert identity(path) == {key: row['file'][key] for key in ('bytes', 'sha256')}
        arrays = load_npz(path)
        assert tuple(arrays) == TENSORS
        assert {key: array_identity(value) for key, value in arrays.items()} == row['arrays']
        numeric_bytes += sum(value.nbytes for value in arrays.values())
        expected = panels[row['panel']]['batches'][row['batch_index']]
        assert {key: row[key] for key in expected} == expected
        for names, field in ((TENSORS[:3], 'public_sha256'), (TENSORS[3:6], 'target_sha256')):
            assert hashlib.sha256(b''.join(arrays[key].tobytes() for key in names)).hexdigest() == expected[field]
    assert {p.name for p in manifest_path.parent.iterdir()} == snapshot_files
    assert numeric_bytes == manifest['numeric_tensor_bytes'] == 49_520_640
    snapshot_bytes = sum(p.stat().st_size for p in manifest_path.parent.iterdir())
    assert snapshot_bytes == preparation['snapshot']['total_snapshot_bytes'] <= 64 * 1024 ** 2
    current, old = load_npz(inputs['current_endpoint_arrays']), load_npz(inputs['old_endpoint_arrays'])
    current_raw = {panel: load_npz(inputs['current_' + panel + '_raw']) for panel in ('task', 'clean')}
    components, raw_arrays, case_reports, total_resources, profile_totals = {}, {}, {}, {}, {}
    field_comparisons, field_inventory = 0, 0
    assert [item['phase'] for item in summary['cases']] == list(CASES)
    for item in summary['cases']:
        case, result = item['phase'], item['result']
        assert result == read(RUN / case / 'RESULT.json') and result['status'] == 'COMPLETE'
        assert item['exit_code'] == 0 and item['resource_accounting_complete']
        assert item['result_file'] == identity(RUN / case / 'RESULT.json')
        for suffix in ('stdout', 'stderr'):
            assert item[suffix] == identity(RUN / (case + '.' + suffix))
        assert result['source_registration'] == sources and result['protocol_sha256'] == sha(SOURCE / 'PROTOCOL.json')
        assert result['parent_record_sha256'] == sha(RUN / 'START.json')
        assert result['input_manifest'] == start['input_manifest'] and result['all_input_sha256'] == manifest['all_input_sha256']
        assert result['parameter_identities'] == result['final_parameter_identities'] == protocol['parameter_identities']
        config = result['configuration_identity']
        assert config['sha256'] == result['final_configuration_sha256'] == hashlib.sha256(canonical(config['value'])).hexdigest()
        assert result['observed_capability'] in protocol['expected_capabilities'][case]
        assert result['forbidden_calls'] == []
        expected = protocol['per_case_budget']['unset' if case.startswith('unset_') else 'explicit']
        assert result['actual_totals'] == item['registered_call_upper_bound'] == expected
        assert result['independent_call_profile'] == {'generator_pipeline_started': expected['generator_panel_calls'],
            'generator_decode_calls': expected['generator_panel_calls'], 'observer_forward_calls': expected['observer_calls']}
        for key, value in result['resources'].items():
            total_resources[key] = total_resources.get(key, 0) + value
        for key, value in result['independent_call_profile'].items():
            profile_totals[key] = profile_totals.get(key, 0) + value
        for module, row in result['imported_sources'].items():
            path = Path(row['path'])
            expected_sha = freeze.get(path.relative_to(PORT).as_posix(), sources['files'].get(path.relative_to(REPO).as_posix(), {}).get('sha256'))
            assert sha(path) == row['sha256'] == expected_sha
            assert 'historical_dispatch_20261028' not in str(path)
        case_reports[case] = {'result_file': identity(RUN / case / 'RESULT.json'),
            'capability': result['observed_capability'], 'actual_totals': result['actual_totals'],
            'cpu_ns': result['cpu_ns'], 'wall_ns': result['wall_ns'], 'panels': {}}
        components[case], raw_arrays[case] = {}, {}
        for panel, count in (('task', 2048), ('clean', 512)):
            record = result['panels'][panel]
            for kind in ('raw', 'components', 'forward_fields'):
                path = RUN / case / record[kind]['path']
                assert identity(path) == {key: record[kind][key] for key in ('bytes', 'sha256')}
            raw = load_npz(RUN / case / record['raw']['path'])
            assert raw['pixels_u8'].dtype == np.uint8 and raw['pixels_u8'].shape == (count, 1, 28, 56)
            assert np.array_equal(raw['source_ids'], current_raw[panel]['source_ids'])
            assert np.array_equal(raw['conditions'], current_raw[panel]['conditions'])
            values = np.stack([raw['values_' + name] for name in OBSERVERS])
            assert compare(values, old['original_' + panel]) == record['vs_old_v3']
            assert compare(values, current['frozen_' + panel]) == record['vs_current_v5']
            with gzip.open(RUN / case / record['components']['path'], 'rt') as stream:
                component = json.load(stream)
            assert len(component['rows']) == len(component['hashes']) == len(component['fixed_v5_raw_mse']) == count
            for index, (row, hashes) in enumerate(zip(component['rows'], component['hashes'], strict=True)):
                part = panels[panel]['batches'][index // 128]
                assert row['row'] == index and row['batch'] == index // 128
                assert row['noise_seed'] == part['noise_seed'] and row['condition'] == part['condition']
                pixel, caption = raw['pixels_u8'][index].tobytes(), str(raw['captions_utf8'][index]).encode()
                assert hashlib.sha256(pixel).hexdigest() == hashes['pixel_sha256']
                assert hashlib.sha256(caption).hexdigest() == hashes['caption_utf8_sha256']
                assert hashlib.sha256(pixel + caption).hexdigest() == raw['output_sha256'][index]
                for observer in OBSERVERS:
                    fields = row['observers'][observer]
                    loss = sum(protocol['utility_weights'][key] * fields[key] for key in FIELDS)
                    assert loss == fields['joint_loss'] and 1 - 2 * loss == fields['utility']
                    assert fields['utility'] - row['refinement_charge'] == fields['charged_utility'] == raw['values_' + observer][index]
            forward = read(RUN / case / record['forward_fields']['path'])
            assert forward['returned_fields'] == list(OUTFIELDS) and len(forward['batches']) == count // 128
            for index, row in enumerate(forward['batches']):
                assert row['batch'] == index and row['noise_seed'] == panels[panel]['batches'][index]['noise_seed']
                assert set(row['fields']) == set(OUTFIELDS)
                field_inventory += 4
                if case.startswith('unset_'):
                    assert set(row['parity']) == set(OUTFIELDS)
                    for name in OUTFIELDS:
                        assert row['parity'][name]['bitwise_exact']
                        assert row['parity'][name]['fixed_noise'] == row['parity'][name]['original_forward'] == row['fields'][name]
                        field_comparisons += 1
                else:
                    assert row['parity'] is None
            historical = protocol['historical_raw_identities'][panel]
            matched = all(record['raw'][key] == historical[key] for key in ('bytes', 'sha256'))
            assert matched == record['vs_historical_raw']['full_sha256_and_bytes_exact']
            assert not matched
            if case.startswith('unset_'):
                for kind in ('raw', 'components'):
                    assert identity(RUN / case / record[kind]['path']) == identity(inputs['first_' + case + '_' + panel + '_' + kind])
                assert identity(RUN / case / record['raw']['path']) == identity(inputs['current_' + panel + '_raw'])
            raw_arrays[case][panel], components[case][panel] = raw, component
            case_reports[case]['panels'][panel] = {'raw_file': record['raw'], 'historical_raw_match': matched,
                'vs_old': compact(values, old['original_' + panel]), 'vs_current': compact(values, current['frozen_' + panel])}
    assert field_comparisons == 160 and field_inventory == 400
    assert total_resources == summary['observed_resources']
    assert profile_totals == {'generator_pipeline_started': 140, 'generator_decode_calls': 140, 'observer_forward_calls': 400}
    assert summary['actual_totals'] == protocol['complete_budget'] == {'generator_panel_calls': 140,
        'generator_examples': 17920, 'observer_calls': 400, 'observer_digit_examples': 51200}
    assert summary['resource_accounting_complete'] and not summary['unknown_resource_cases']
    controls = {}
    for panel in ('task', 'clean'):
        controls[panel] = {}
        for suffix in ('.npz', '_components.json.gz', '_forward_fields.json'):
            assert identity(RUN / 'unset_before' / (panel + suffix)) == identity(RUN / 'unset_after' / (panel + suffix))
            controls[panel][suffix] = identity(RUN / 'unset_before' / (panel + suffix))
    for case in CASES:
        for panel in ('task', 'clean'):
            baseline, observed = components['unset_before'][panel], components[case][panel]
            original_raw, raw = raw_arrays['unset_before'][panel], raw_arrays[case][panel]
            values = np.asarray([[1 - 2 * sum(protocol['utility_weights'][key] *
                (float(mse) if key == 'pixel_mse' else row['observers'][observer][key]) for key in FIELDS)
                - row['refinement_charge'] for row, mse in zip(baseline['rows'], observed['fixed_v5_raw_mse'], strict=True)]
                for observer in OBSERVERS], dtype=np.float64)
            reported = summary['fixed_raw_mse_only_arithmetic'][panel][case]
            assert compare(values, old['original_' + panel]) == reported['vs_old_v3']
            assert compare(values, current['frozen_' + panel]) == reported['vs_current_v5']
            pixel_delta = raw['pixels_u8'].astype(np.int16) - original_raw['pixels_u8'].astype(np.int16)
            primitive_counts = {observer: {key: sum(a['observers'][observer][key] != b['observers'][observer][key]
                for a, b in zip(observed['rows'], baseline['rows'], strict=True)) for key in baseline['rows'][0]['observers'][observer]}
                for observer in OBSERVERS}
            case_reports[case]['panels'][panel].update(
                changed_pixel_rows=int(np.any(pixel_delta != 0, axis=(1, 2, 3)).sum()),
                changed_pixel_values=int((pixel_delta != 0).sum()), nonzero_pixel_differences=np.unique(pixel_delta[pixel_delta != 0]).tolist(),
                changed_primitive_rows={observer: {k: v for k, v in fields.items() if v} for observer, fields in primitive_counts.items()},
                changed_hash_rows={key: sum(a[key] != b[key] for a, b in zip(observed['hashes'], baseline['hashes'], strict=True))
                                   for key in baseline['hashes'][0]},
                fixed_current_pixel_mse_differing_rows=sum(a != b for a, b in zip(observed['fixed_v5_raw_mse'], baseline['fixed_v5_raw_mse'], strict=True)),
                mse_only_vs_old=compact(values, old['original_' + panel]),
                mse_only_vs_current=compact(values, current['frozen_' + panel]))
    metadata = summary['metadata_storage']
    actual_metadata = sum(path.stat().st_size for path in RUN.rglob('*') if path.is_file()
                          and path.relative_to(RUN).parts[0] not in (*CASES, 'input_snapshot'))
    assert metadata['summary_bytes'] == summary_identity['bytes']
    assert metadata['total_metadata_bytes'] == actual_metadata <= 16 * 1024 ** 2
    assert metadata['within_bound']
    disk_records = summary['disk_checks'] + [preparation['disk_before']] + [item['result']['disk_before'] for item in summary['cases']]
    for disk in disk_records:
        assert disk['passed'] and disk['required_bytes'] == disk['remaining_output_bound_bytes'] + disk['reserve_bytes']
        assert disk['allocatable_bytes'] >= disk['required_bytes']
        assert disk['allocatable_bytes'] == disk['f_bfree_bytes'] if disk['effective_uid'] == 0 else disk['allocatable_bytes'] == disk['f_bavail_bytes']
    assert identity(RUN / 'SUMMARY.json') == summary_identity
    assert 'torch' not in sys.modules
    report = {'schema': 'hepta.v5.fixed-inputs-independent-scientific-review.1', 'review_status': 'PASS',
        'scope': 'Independent read-only byte/array/receipt analysis; no model inference, preparation or scientific gate change.',
        'source_registration': sources, 'summary': {'path': str(RUN / 'SUMMARY.json'), **summary_identity},
        'bound_inputs_verified': len(inputs), 'frozen_dependencies_verified': len(freeze),
        'snapshot': {'manifest': identity(manifest_path), 'all_input_sha256': manifest['all_input_sha256'],
            'npz_files': 20, 'numeric_arrays': 140, 'numeric_tensor_bytes': numeric_bytes, 'total_snapshot_bytes': snapshot_bytes,
            'all_cases_same_manifest_and_aggregate_hash': True, 'full_file_and_array_hashes_recomputed': True},
        'controls': {'unset_original_forward_bitwise_field_comparisons': field_comparisons,
            'all_case_output_field_records': field_inventory, 'unset_repeated_files': controls,
            'unset_first_attempt_raw_and_components_exact': True, 'unset_current_v5_full_raw_bytes_exact': True},
        'actual_totals': summary['actual_totals'], 'independent_profile_totals': profile_totals,
        'first_attempt_actual_totals': protocol['first_attempt']['actual_totals'],
        'combined_two_attempt_totals': {key: summary['actual_totals'][key] + protocol['first_attempt']['actual_totals'][key]
                                      for key in summary['actual_totals']},
        'cases': case_reports, 'metadata_bytes': actual_metadata, 'disk_gates_verified': len(disk_records),
        'scientific_status': 'FAIL', 'admission': False, 'historical_raw_file_recovered': False,
        'newly_reconstructed_historical_raw_matching_cases': {'task': [], 'clean': []},
        'selected_capability': None, 'new_holdout_authorized': False, 'raw_upload_attempts': 0,
        'original_failed_audit': identity(inputs['original_failed_audit']),
        'first_attempt_failed_summary': identity(inputs['first_attempt_summary']),
        'limitations': ['Only seed17 frozen original action0 endpoints were tested; learned ordinary48 paths and other seeds were not replayed.',
            'Inference uses saved unset-constructed public/target/latent inputs. It is a conditional dispatch intervention, not original per-dispatch RNG replay.',
            'This records current-host dispatch sensitivity; it does not identify the historical CPU, backend configuration or original mismatch cause.',
            'ATen native capability is not a universal ISA limit for MKL/oneDNN or other linked libraries.',
            'Original-forward tensor equality is independently checked through complete registered hash receipts; raw floating logits were not retained and no neural calls were repeated in this review.',
            'The historical raw files remain unavailable; no generated whole-file identity matched them. Original scientific FAIL and raw-custody approval block remain.'],
        'new_model_calls_this_review': 0, 'torch_imported': False}
    target = ROOT / 'V5_FIXED_INPUTS_SCIENTIFIC_REVIEW_20261028.json'
    with target.open('x') as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': {'path': str(target), **identity(target)}, 'summary': summary_identity,
        'snapshot_bytes': snapshot_bytes, 'actual_totals': summary['actual_totals'], 'field_parities': field_comparisons,
        'cases': {case: {panel: {key: info[key] for key in ('vs_old', 'vs_current', 'changed_pixel_rows',
            'fixed_current_pixel_mse_differing_rows')} for panel, info in row['panels'].items()}
            for case, row in case_reports.items()}}, sort_keys=True))


if __name__ == '__main__':
    main()
