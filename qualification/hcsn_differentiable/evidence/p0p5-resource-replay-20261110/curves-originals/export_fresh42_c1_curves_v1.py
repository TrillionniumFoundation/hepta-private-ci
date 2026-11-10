"""Read only the original 42 + seven C1 JSON reports; do no model computation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback
import zipfile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
ORIGINAL = BASE / 'campaign-v2'
C1 = BASE / 'campaign-v2-continuation-c1'
OUT = BASE / 'fresh42-c1-curves-export-v1'
EXPECTED_ORIGINAL = '362bc0345635bb5c9438670c13efa5908140527463aa4f373479235686b5683b'
EXPECTED_C1 = 'f09e2d72f9c8c49fc03c0669713faba46cd634fb26185f33f2ae962c0350c894'
CLOCK_KEYS = ('wall_seconds', 'process_wall_seconds', 'process_cpu_seconds',
    'phase_process_wall_seconds', 'cumulative_process_wall_seconds', 'phase_full_process_cpu_seconds')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def write(path, value, compact=False):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=None if compact else 2,
                               allow_nan=False) + '\n')


def main():
    started, cpu = time.monotonic(), time.process_time()
    OUT.mkdir(exist_ok=False)
    inputs, expected_sources, fits, observations = {}, {}, [], []
    result = {'schema': 'hcsn-original42-c1-readonly-curves-export-v1', 'status': 'started',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'driver': identity(Path(__file__)),
        'forward_calls': 0, 'backward_calls': 0, 'optimizer_steps': 0, 'confirmation_access': False,
        'scientific_admission': 'HOLD', 'automatic_retry': False}

    def read(path, expected=None):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError('nonregular required input: ' + str(path))
        raw = path.read_bytes()
        item = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        if expected is not None and item['sha256'] != expected:
            raise ValueError('input identity mismatch: ' + str(path))
        if str(path) in inputs and inputs[str(path)] != item:
            raise ValueError('input changed during reading: ' + str(path))
        inputs[str(path)] = item
        return json.loads(raw)

    try:
        original = read(ORIGINAL / 'RESULT.json', EXPECTED_ORIGINAL)
        continuation = read(C1 / 'RESULT.json', EXPECTED_C1)
        plan = read(BASE / 'campaign-v2-plan.json', original['plan_sha256'])
        read(Path(plan['prepared']) / 'data-manifest.json', plan['manifest_sha256'])
        assert original['status'] == 'completed_attempt_roster' and len(original['attempts']) == 42
        assert continuation['status'] == 'completed_continuation_roster' and len(continuation['attempts']) == 7
        assert original['source_unchanged'] and continuation['source_unchanged']
        outer_original = {row['name']: row for row in original['attempts']}
        roster = [('original', ORIGINAL, row) for row in original['attempts']]
        roster += [('C1', C1, row) for row in continuation['attempts']]
        for phase, directory, outer in sorted(roster, key=lambda item: (item[0], item[2]['name'])):
            path = directory / outer['name'] / 'result.json'
            report = read(path, outer['result_sha256'])
            report_id = inputs[str(path)]
            fit_plan = read(path.parent / 'plan.json', report['plan_sha256'])
            assert report['source_before'] == report['source_after'] and report['source_unchanged']
            for name, digest in report['source_before'].items():
                if name in expected_sources and expected_sources[name] != digest:
                    raise ValueError('loaded source has conflicting expected identity')
                expected_sources[name] = digest
            parent_report = None
            if phase == 'C1':
                parent_path = ORIGINAL / outer['name'] / 'result.json'
                parent_report = read(parent_path, report['parent_report_sha256'])
                parent_record = read(C1 / 'parent-records' / (outer['name'] + '.json'),
                                     report['parent_outer_record_sha256'])
                assert parent_record == outer_original[outer['name']]
                actual_ceiling = parent_record['hard_wall_seconds']
                parent_cpu_lower = max(parent_report['cpu_seconds'], max(
                    (e['process_cpu_seconds'] for e in parent_report['epochs']), default=0.0))
            else:
                actual_ceiling, parent_cpu_lower = outer['hard_wall_seconds'], None
            base = {'phase': phase, 'name': outer['name'], 'arm': report['arm'], 'seed': report['seed'],
                'report_path': str(path), 'report_sha256': report_id['sha256'], 'report_bytes': report_id['bytes']}
            metadata = {**base, 'plan': fit_plan, 'outer': outer, 'actual_original_hard_wall_seconds': actual_ceiling,
                'status': report['status'], 'stop_reason': report.get('stop_reason'),
                'diagnostic_passed': report.get('memorization', {}).get('passed'),
                'memorization': report.get('memorization'), 'peak_rss_bytes': report.get('peak_rss_bytes'),
                'best_epoch': report.get('best_epoch'), 'best_checkpoint_sha256': report.get('best_checkpoint_sha256'),
                'training_adequacy_established': report['training_adequacy_established'],
                'main_updates': report['main_updates'], 'diagnostic_updates': report.get('diagnostic_updates'),
                'parent_report_sha256': report.get('parent_report_sha256'),
                'parent_full_process_cpu_seconds': report.get('parent_full_process_cpu_seconds'),
                'parent_recorded_fit_cpu_seconds': report.get('parent_recorded_fit_cpu_seconds'),
                'parent_cpu_lower_bound_seconds': parent_cpu_lower,
                'all_report_clock_fields': {k: v for k, v in report.items()
                    if ('wall_seconds' in k or 'cpu_seconds' in k or 'time_to_quality' in k)},
                'selected_development': report.get('selected_development'),
                'source_before': report['source_before'], 'source_unchanged': report['source_unchanged'],
                'common_weights_unchanged': report.get('common_weights_unchanged'),
                'development_before_present': 'development_before' in report}
            fits.append(metadata)
            if 'development_before' in report:
                development = report['development_before']
                observations.append({**base, 'kind': 'development_before', 'epoch': 0,
                    'development': development, 'process_wall_seconds': report.get('development_before_process_wall_seconds'),
                    'process_cpu_seconds': None, 'clock_origin': 'original report development_before_process_wall_seconds; no CPU clock recorded',
                    'original_clock_fields': {k: v for k, v in report.items() if k.startswith('development_before_')}})
            for epoch in report['epochs']:
                assert epoch['complete'] is True
                development = epoch['development']
                assert len(development['confusion_matrix']) == 11
                row = {**base, 'kind': 'complete_epoch', 'epoch': epoch['epoch'],
                    'development': development, 'events': epoch['events'],
                    'original_clock_fields': {k: epoch[k] for k in CLOCK_KEYS if k in epoch},
                    'training_weighted_loss': epoch['training_weighted_loss']}
                row.update({k: epoch[k] for k in CLOCK_KEYS if k in epoch})
                if phase == 'C1':
                    row.update(cumulative_full_process_cpu_seconds=None,
                        cumulative_cpu_lower_bound_seconds=parent_cpu_lower + epoch['phase_full_process_cpu_seconds'],
                        cumulative_cpu_upper_bound_seconds=None,
                        cumulative_cpu_scope='lower bound only: parent full-process exit CPU unknown; retain measured phase CPU; no exact offset imputed')
                observations.append(row)
        assert len(fits) == 49 and len({(r['phase'], r['name']) for r in fits}) == 49
        source_before = {}
        for name, expected in sorted(expected_sources.items()):
            p = Path(name)
            actual = identity(p)
            assert actual['sha256'] == expected, name
            source_before[name] = actual
        source_before[str(Path(__file__).resolve())] = result['driver']
        curves = {'schema': 'hcsn-original42-and-c1-epoch-curves-v1', 'fits': fits,
            'observations': observations, 'declared_elapsed_cutoffs_seconds': [300, 900, 1800],
            'missing_evaluation_policy': 'missing remains null/absent; no zero fill or interpolation',
            'C1_clock_policy': 'original phase and cumulative values preserved, including historical separate-clock sampling; no repair',
            'CPU_policy': 'original epoch CPU is measured process prefix; parent final fit CPU omits imports; C1 cumulative exact CPU unknown, lower bound only',
            'before_development_policy': 'original before-development is an explicit separate observation; C1 has no invented phase-before evaluation',
            'first_crossing_policy': 'first observed complete-epoch crossing, not an exact event time',
            'original_controller': {'identity': inputs[str(ORIGINAL / 'RESULT.json')],
                'costs': {k: v for k, v in original.items() if k.endswith('_seconds')}},
            'C1_controller': {'identity': inputs[str(C1 / 'RESULT.json')],
                'costs': {k: v for k, v in continuation.items() if k.endswith('_seconds')}},
            'scientific_admission': 'HOLD', 'energy_joules': None, 'confirmation_access': False}
        write(OUT / 'CURVES.json', curves, compact=True)
        source_after = {name: identity(Path(name)) for name in source_before}
        input_after = {name: identity(Path(name)) for name in inputs}
        assert source_before == source_after and inputs == input_after
        write(OUT / 'INPUT-SOURCE-IDENTITIES.json', {'inputs_before': inputs, 'inputs_after': input_after,
            'sources_before': source_before, 'sources_after': source_after})
        result.update(status='completed_readonly_export', reports=49,
            original_reports=42, continuation_reports=7,
            complete_epoch_observations=sum(r['kind'] == 'complete_epoch' for r in observations),
            before_development_observations=sum(r['kind'] == 'development_before' for r in observations),
            inputs_unchanged=True, sources_unchanged=True, curves=identity(OUT / 'CURVES.json'))
    except Exception:
        result.update(status='failed_preserved_no_retry', error=traceback.format_exc(),
            retained_input_identities=inputs)
    finally:
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        result.update(export_wall_seconds=time.monotonic() - started,
            export_cpu_seconds=time.process_time() - cpu, full_process_cpu_seconds=time.process_time(),
            children_cpu_seconds=child.ru_utime + child.ru_stime,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            cost_scope='export main entry through JSON/source checks; packaging charged separately below')
        write(OUT / 'RESULT.json', result)
    if result['status'] == 'completed_readonly_export':
        tick, package_cpu = time.monotonic(), time.process_time()
        members = {p.name: p for p in (OUT / 'CURVES.json', OUT / 'INPUT-SOURCE-IDENTITIES.json', OUT / 'RESULT.json', Path(__file__))}
        manifest = {name: identity(path) for name, path in members.items()}
        target = OUT / 'hcsn-original42-c1-curves-20261110-v1.zip'
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for name, path in sorted(members.items()):
                zipped.write(path, name)
            zipped.writestr('MEMBER-MANIFEST.json', json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        with zipfile.ZipFile(target) as zipped:
            assert zipped.testzip() is None
            for name, item in manifest.items():
                raw = zipped.read(name)
                assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
        archive = {'archive': str(target), **identity(target), 'members': len(manifest) + 1,
            'all_member_sha_and_crc_verified': True, 'package_wall_seconds': time.monotonic() - tick,
            'package_cpu_seconds': time.process_time() - package_cpu,
            'whole_main_wall_seconds': time.monotonic() - started,
            'full_process_cpu_seconds': time.process_time(), 'export_result': identity(OUT / 'RESULT.json')}
        write(OUT / 'ARCHIVE-RECEIPT.json', archive)
        print(json.dumps(archive, sort_keys=True), flush=True)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] == 'completed_readonly_export' else 2


if __name__ == '__main__':
    raise SystemExit(main())
