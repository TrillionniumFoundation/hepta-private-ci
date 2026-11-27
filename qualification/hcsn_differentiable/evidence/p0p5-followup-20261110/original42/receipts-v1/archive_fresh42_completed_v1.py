"""Archive the terminal original 42-fit experiment; no training or source mutation."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
import traceback
import zipfile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
ROOT = BASE / 'campaign-v2'
OUT = BASE / 'fresh42-terminal-archives-v1'
RESULT_SHA = '362bc0345635bb5c9438670c13efa5908140527463aa4f373479235686b5683b'
PLAN_SHA = 'e13f97aafdaf66548f016f2dcc3a38dd7e641a2ea83d52b8bea89f4c7e0cf114'
CAPSULE_SHA = '288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102'
DATA_SHA = '0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    return {'bytes': path.stat().st_size, 'sha256': sha(path), 'original_path': str(path)}


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')


def tree(path):
    if not path.is_dir():
        raise ValueError('missing directory: ' + str(path))
    return {str(p.relative_to(BASE)): p for p in sorted(path.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts}


def package(name, members):
    tick, cpu = time.monotonic(), time.process_time()
    for name_in_zip, path in members.items():
        if (path.is_symlink() or not path.is_file() or name_in_zip.startswith('/')
                or '..' in Path(name_in_zip).parts or '\\' in name_in_zip):
            raise ValueError('unsafe or nonregular archive member')
    manifest = {name: identity(path) for name, path in sorted(members.items())}
    target = OUT / name
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for member, path in sorted(members.items()):
            zipped.write(path, member)
        zipped.writestr('MEMBER-MANIFEST.json', json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    with zipfile.ZipFile(target) as zipped:
        if zipped.testzip() is not None or len(zipped.namelist()) != len(manifest) + 1:
            raise ValueError('archive CRC or count mismatch')
        for member, expected in manifest.items():
            digest, size = hashlib.sha256(), 0
            with zipped.open(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                    size += len(block)
            if size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
                raise ValueError('archive member hash mismatch: ' + member)
    if any(identity(path) != manifest[member] for member, path in members.items()):
        raise ValueError('original changed while packaging')
    row = {'path': str(target), 'name': name, **identity(target), 'members': len(manifest) + 1,
        'uncompressed_payload_bytes': sum(row['bytes'] for row in manifest.values()),
        'all_member_sha_and_crc_verified': True, 'originals_unchanged': True,
        'wall_seconds': time.monotonic() - tick, 'cpu_seconds': time.process_time() - cpu}
    print(json.dumps(row, sort_keys=True), flush=True)
    return row


def main():
    started, cpu_started = time.monotonic(), time.process_time()
    OUT.mkdir(exist_ok=False)
    receipt = {'schema': 'hcsn-original-fresh42-terminal-archive-v1', 'status': 'started',
        'assets': [], 'started_utc': datetime.now(timezone.utc).isoformat(),
        'archiver_sha256': sha(Path(__file__)), 'scientific_admission': 'HOLD',
        'confirmation_access': False, 'sources_modified': False, 'new_training_started': False,
        'energy_joules': None, 'independent_validation': 'separate; packaging is integrity verification',
        'host_nice': os.getpriority(os.PRIO_PROCESS, 0)}
    try:
        assert sha(ROOT / 'RESULT.json') == RESULT_SHA
        assert sha(BASE / 'campaign-v2-plan.json') == PLAN_SHA
        assert sha(BASE / 'training-source-v8.zip') == CAPSULE_SHA
        report = json.loads((ROOT / 'RESULT.json').read_bytes())
        plan = json.loads((BASE / 'campaign-v2-plan.json').read_bytes())
        assert report['status'] == 'completed_attempt_roster' and report['source_unchanged']
        roster = {(a, s, lr) for a in plan['arms'] for s in plan['seeds'] for lr in plan['learning_rates']}
        assert len(report['attempts']) == 42
        assert roster == {(r['arm'], r['seed'], r['learning_rate']) for r in report['attempts']}
        commands = [json.loads(line) for line in (ROOT / 'commands.jsonl').read_bytes().splitlines()]
        terminal = {row['name']: row for row in commands if row.get('status') != 'started'}
        assert len(terminal) == 42
        rows, external, context, small = [], {}, {}, {}
        for outer in sorted(report['attempts'], key=lambda r: r['name']):
            name, arm = outer['name'], outer['arm']
            assert outer == terminal[name]
            assert outer['status'] in ('completed', 'failed')
            directory = ROOT / name
            result_path, fit_plan_path = directory / 'result.json', directory / 'plan.json'
            assert sha(result_path) == outer['result_sha256']
            fit, fit_plan = json.loads(result_path.read_bytes()), json.loads(fit_plan_path.read_bytes())
            expected_status = 'budget_exhausted' if arm == 'hcsn' else 'completed_development'
            assert fit['status'] == expected_status
            assert fit['source_before'] == fit['source_after'] and fit['source_unchanged']
            assert fit['common_weights_unchanged']
            assert sha(fit_plan_path) == fit['plan_sha256']
            assert sha(directory / 'events.jsonl') == fit['events_sha256']
            checkpoints = {}
            for filename, field in (('initial.pt', 'initialization_sha256'),
                    ('best.pt', 'best_checkpoint_sha256'), ('last.pt', 'last_checkpoint_sha256'),
                    ('memorization.pt', 'memorization_checkpoint_sha256'),
                    ('interrupted.pt', 'interrupted_checkpoint_sha256')):
                if field in fit:
                    checkpoints[filename] = identity(directory / filename)
                    assert checkpoints[filename]['sha256'] == fit[field]
            for original, expected in fit['source_before'].items():
                path = Path(original)
                assert sha(path) == expected, original
                member = (str(path.relative_to(BASE)) if path.is_relative_to(BASE)
                          else 'external-loaded-source/' + expected[:20] + '/' + path.name)
                context[member] = path
                external[original] = {'archive_path': member, 'sha256': expected}
            best_row = next(r for r in fit['epochs'] if r['epoch'] == fit['best_epoch'])
            assert best_row['development']['macro_f1_11_classes'] == max(
                r['development']['macro_f1_11_classes'] for r in fit['epochs'])
            memo = fit.get('memorization', {})
            row = {'name': name, 'arm': arm, 'seed': outer['seed'], 'learning_rate': outer['learning_rate'],
                'status': fit['status'], 'stop_reason': fit.get('stop_reason'),
                'result': identity(result_path), 'plan': identity(fit_plan_path),
                'checkpoints': checkpoints, 'outer': outer,
                'complete_epochs': len(fit['epochs']), 'main_updates': fit['main_updates'],
                'diagnostic_updates': fit['diagnostic_updates'], 'memorization_passed': memo.get('passed'),
                'adequate': fit['training_adequacy_established'], 'best_epoch': fit['best_epoch'],
                'best_observed_development': best_row['development'],
                'best_observed_process_wall_seconds': best_row['process_wall_seconds'],
                'best_observed_process_cpu_seconds': best_row['process_cpu_seconds'],
                'selected_development': fit.get('selected_development'),
                'last_development': fit['epochs'][-1]['development'],
                'time_to_quality_inner_seconds': fit.get('time_to_quality_seconds'),
                'first_observed_quality_process_wall_seconds': fit.get('process_time_to_quality_seconds'),
                'quality_crossing_scope': 'first observed complete-epoch check; not exact crossing time',
                'fit_entry_cpu_seconds': fit['cpu_seconds'], 'process_wall_seconds': fit['process_wall_seconds'],
                'peak_rss_bytes': fit['peak_rss_bytes'], 'source_unchanged': fit['source_unchanged'],
                'common_weights_unchanged': fit['common_weights_unchanged'],
                'model': fit.get('model'), 'module_parameters': fit.get('module_parameters')}
            if arm == 'hcsn':
                row['soft_wall_limit_exceeded'] = fit['wall_seconds'] >= fit_plan['wall_seconds']
                row['rss_limit_not_exceeded'] = fit['peak_rss_bytes'] <= fit_plan['rss_bytes']
                row['trace_files'] = {}
                for path in directory.glob('*.jsonl'):
                    if path.name == 'events.jsonl':
                        continue
                    with path.open('rb') as stream:
                        stream.seek(max(0, path.stat().st_size - 131072))
                        last = stream.read().splitlines()[-1]
                    row['trace_files'][path.name] = {**identity(path), 'last_json_record': json.loads(last)}
                for path in (result_path, fit_plan_path):
                    small[str(path.relative_to(BASE))] = path
            rows.append(row)
        summary = {'schema': 'hcsn-original-fresh42-terminal-summary-v1', 'rows': rows,
            'original_campaign_result_sha256': RESULT_SHA, 'source_capsule_sha256': CAPSULE_SHA,
            'plan_sha256': PLAN_SHA, 'data_manifest_sha256': DATA_SHA,
            'source_unchanged': report['source_unchanged'], 'scientific_admission': 'HOLD',
            'confirmation_access': False, 'energy_joules': None,
            'original_only': True, 'c1_scope': 'seven subsequent chains separately archived; not rewritten here',
            'hcsn_scope': 'all six resource-censored; complete epoch checkpoints and partial interrupted checkpoints retained',
            'costs': {k: report[k] for k in ('whole_wall_seconds', 'sum_attempt_wall_seconds',
                'children_cpu_seconds', 'controller_cpu_seconds', 'training_adequacy_passed_fits')},
            'cpu_scope': 'aggregate children CPU includes complete processes; per-fit final cpu_seconds omits startup; epoch prefix CPU is full process prefix',
            'budget_scope': 'actual per-fit ceiling min(14400,15000-dispatch); HCSN six each received14400; all measured costs retained'}
        write(OUT / 'SUMMARY.json', summary)
        write(OUT / 'EXTERNAL-SOURCE-MAP.json', external)
        runtime = {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
            'resolved_executable_sha256': sha(Path(sys.executable).resolve()), 'packages': {}}
        for name in ('torch', 'numpy', 'mpmath', 'ncps', 'spikingjelly', 'einops', 'torchvision'):
            try:
                distribution = importlib.metadata.distribution(name)
            except importlib.metadata.PackageNotFoundError:
                runtime['packages'][name] = {'installed': False}
                continue
            record = distribution.read_text('RECORD')
            runtime['packages'][name] = {'version': distribution.version,
                'record_sha256': hashlib.sha256(record.encode()).hexdigest() if record else None}
            if record:
                path = OUT / (name + '-installed-RECORD.txt')
                with path.open('x') as stream:
                    stream.write(record)
                context['archive-operation/' + path.name] = path
        write(OUT / 'RUNTIME-IDENTITY.json', runtime)
        for name in ('SUMMARY.json', 'EXTERNAL-SOURCE-MAP.json', 'RUNTIME-IDENTITY.json'):
            context['archive-operation/' + name] = OUT / name
        for path in (ROOT / 'RESULT.json', ROOT / 'commands.jsonl', ROOT / 'locked-plan.json',
                     BASE / 'campaign-v2-plan.json', BASE / 'training-source-v8.zip',
                     BASE / 'native_launch_campaign_v2.py', Path(__file__)):
            context[str(path.relative_to(BASE))] = path
        context.update(tree(BASE / 'run-source-v8'))
        context.update(tree(BASE / 'campaign-v2-launch'))
        prepared = Path(plan['prepared'])
        assert sha(prepared / 'data-manifest.json') == DATA_SHA
        for name in ('data-manifest.json', 'frontend.json'):
            context['data-identity/' + name] = prepared / name
        small.update({str(p.relative_to(BASE)): p for p in
            (ROOT / 'RESULT.json', ROOT / 'commands.jsonl', BASE / 'campaign-v2-plan.json',
             OUT / 'SUMMARY.json', BASE / 'run-source-v8/SOURCE_MANIFEST.json')})
        receipt['small_handoff'] = package('hcsn-fresh42-terminal-small-20261110-v1.zip', small)
        receipt['assets'].append(package('hcsn-fresh42-original-context-20261110-v1.zip', context))
        for arm in ['hcsn'] + [a for a in plan['arms'] if a != 'hcsn']:
            members = {}
            for row in rows:
                if row['arm'] != arm:
                    continue
                members.update(tree(ROOT / row['name']))
                for suffix in ('.stdout', '.stderr'):
                    path = ROOT / (row['name'] + suffix)
                    members[str(path.relative_to(BASE))] = path
            members['original-context/SUMMARY.json'] = OUT / 'SUMMARY.json'
            receipt['assets'].append(package('hcsn-fresh42-original-' + arm + '-20261110-v1.zip', members))
        receipt.update(status='completed_all42_originals_archived_all_member_hashes_verified',
            source_files_unchanged=True, original_result_sha256=RESULT_SHA,
            summary=identity(OUT / 'SUMMARY.json'), archived_fit_count=len(rows))
    except Exception:
        receipt.update(status='failed_preserved_no_retry_or_deletion', error=traceback.format_exc())
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt.update(whole_wall_seconds=time.monotonic() - started,
            own_cpu_seconds=time.process_time() - cpu_started, full_process_cpu_seconds=time.process_time(),
            children_cpu_seconds=usage.ru_utime + usage.ru_stime,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            cost_scope='main-entry wall includes integrity checks and all archive work; per-archive times are overlapping subsets')
        write(OUT / 'ARCHIVE-RECEIPT.json', receipt)
        print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt['status'] == 'completed_all42_originals_archived_all_member_hashes_verified' else 2


if __name__ == '__main__':
    raise SystemExit(main())
