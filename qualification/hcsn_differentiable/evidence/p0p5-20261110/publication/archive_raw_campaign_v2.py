"""Archive already completed native experiments without changing their files."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
import zipfile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
ROOT = BASE / 'campaign-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(path, members):
    started = time.monotonic()
    members = sorted(set(members))
    manifest = {str(p.relative_to(BASE)): {'sha256': sha(p), 'bytes': p.stat().st_size}
                for p in members}
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in members:
            archive.write(p, str(p.relative_to(BASE)))
        archive.writestr('MEMBER-MANIFEST.json', json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        for name, identity in manifest.items():
            content = archive.read(name)
            assert len(content) == identity['bytes']
            assert hashlib.sha256(content).hexdigest() == identity['sha256']
    return {'path': str(path), 'name': path.name, 'bytes': path.stat().st_size,
            'sha256': sha(path), 'members': len(members), 'pack_verify_wall_seconds': time.monotonic()-started}


def main():
    report = json.loads((ROOT / 'RESULT.json').read_text())
    plan = json.loads((ROOT / 'locked-plan.json').read_text())
    expected = {(a, s, lr) for a in plan['arms'] for s in plan['seeds'] for lr in plan['learning_rates']}
    actual = {(r['arm'], r['seed'], r['learning_rate']) for r in report['attempts']}
    assert expected == actual and len(report['attempts']) == 36
    out = BASE / 'evidence-archives-v2'
    out.mkdir(exist_ok=False)
    summary = {key: report[key] for key in ('source_unchanged', 'whole_wall_seconds',
        'sum_attempt_wall_seconds', 'children_cpu_seconds', 'training_adequacy_passed_fits')}
    summary.update(rows=[], interpretation='Raw output-coordinate regime; no fair physical-mechanism ranking',
        confirmation_access=False, scientific_admission='HOLD', energy_joules=None)
    for path in sorted(ROOT.glob('*/result.json')):
        fit = json.loads(path.read_text())
        memo = fit.get('memorization', {})
        after = memo.get('after', {})
        development = fit.get('selected_development', {})
        summary['rows'].append({'name': path.parent.name, 'arm': fit['arm'], 'seed': fit['seed'],
            'status': fit['status'], 'epochs': len(fit['epochs']), 'stop': fit.get('stop_reason'),
            'adequate': fit['training_adequacy_established'], 'memorization_passed': memo.get('passed'),
            'memo_accuracy': after.get('accuracy'), 'memo_f1': after.get('macro_f1_present_classes'),
            'D_f1': development.get('macro_f1_11_classes'), 'D_accuracy': development.get('accuracy'),
            'D_nll': development.get('nll'), 'time_to_quality_inner': fit.get('time_to_quality_seconds'),
            'time_to_quality_outer': fit.get('process_time_to_quality_seconds'),
            'source_unchanged': fit['source_unchanged'],
            'common_weights_unchanged': fit.get('common_weights_unchanged'), 'result_sha256': sha(path)})
    assert len(summary['rows']) == 36
    (BASE / 'campaign-v1-summary.json').write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n')
    runtime = {'python_version': sys.version, 'python_executable': sys.executable,
               'python_resolved_executable_sha256': sha(Path(sys.executable).resolve()),
               'platform': platform.platform(), 'packages': {}}
    for name in ('torch', 'numpy', 'mpmath', 'ncps', 'spikingjelly', 'einops', 'torchvision'):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            runtime['packages'][name] = {'installed': False, 'reason': 'no metadata in the actual interpreter; package not used by these cores'}
            continue
        record = distribution.read_text('RECORD')
        runtime['packages'][name] = {'version': distribution.version,
            'record_sha256': hashlib.sha256(record.encode()).hexdigest() if record else None}
        if record:
            (out / (name + '-installed-RECORD.txt')).write_text(record)
    (out / 'native-environment-identity.json').write_text(json.dumps(runtime, sort_keys=True, indent=2) + '\n')
    assets = []
    for arm in plan['arms']:
        members = []
        for path in sorted(ROOT.glob(arm + '-s*')):
            members.extend([p for p in path.rglob('*') if p.is_file()] if path.is_dir() else [path])
        row = package(out / ('raw-core-v1-' + arm + '.zip'), members)
        assets.append(row)
        print(json.dumps(row), flush=True)
    common = [p for p in ROOT.iterdir() if p.is_file() and not p.name.endswith(('.stdout', '.stderr'))]
    common += [p for p in BASE.iterdir() if p.is_file() and (
        p.name.startswith(('campaign-v1', 'campaign-source-v1', 'training-source-v', 'source-v'))
        or p.name == 'actual-frozen-heads.json')]
    common += [p for p in out.iterdir() if p.is_file() and p.suffix != '.zip']
    for directory in ('preflight-v2', 'profile-v1', 'hcsn-cost-v1', 'draft-release-v1'):
        common += [p for p in (BASE / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name != 'existing-release-check.stdout']
    assets.append(package(out / 'raw-core-v1-context-costs-sources.zip', common))
    receipt = {'schema': 'hcsn-raw-core-evidence-archives-v1', 'assets': assets,
        'summary_sha256': sha(BASE / 'campaign-v1-summary.json'),
        'raw_roster_count': len(summary['rows']), 'source_unchanged': report['source_unchanged'],
        'scientific_admission': 'HOLD', 'release_target': 440410488,
        'visibility': 'public repository unpublished draft, accessible to push-permission users'}
    (out / 'ARCHIVE-MANIFEST.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: summary[k] for k in summary if k != 'rows'}), flush=True)


if __name__ == '__main__':
    main()
