"""Archive completed cloud diagnostics and exact official data; keep draft status."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import traceback
import urllib.request
import zipfile

ROOT = Path('/Users/qianqi/hepta-hcsn-p0p5-20261110-c385/recovery')
OUT = ROOT / 'cloud-p2-draft-upload-v1'
OUT.mkdir(exist_ok=False)
GH = '/opt/homebrew/bin/gh'
REPO = 'TrillionniumFoundation/hepta-private-ci'
RID = 440410488
TAG = 'hcsn-research-20261110-c385'
EXPECTED = {
    'cloud-p2-diagnostics-20261110-v1.zip': (17670639, 'f54585285973bd29c80cbb6fc258bb48513f79e7629296bac3ca2c384a4e76a2'),
    'official-localization-cloud.zip': (6290730, '6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    p = OUT / name
    with p.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def run(argv, label, timeout=600):
    start = time.perf_counter()
    with (OUT / (label + '.stdout')).open('xb') as stdout, (OUT / (label + '.stderr')).open('xb') as stderr:
        try:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            save(label + '.process.json', {'argv': argv, 'status': 'timed_out', 'wall_seconds': time.perf_counter()-start})
            raise
    save(label + '.process.json', {'argv': argv, 'returncode': code, 'wall_seconds': time.perf_counter()-start})
    if code:
        raise RuntimeError(label + ' failed; inspect retained stderr')
    return (OUT / (label + '.stdout')).read_text()


def release(label):
    obj = json.loads(run([GH, 'api', f'repos/{REPO}/releases/{RID}'], label))
    assert obj['id'] == RID and obj['draft'] is True and obj['tag_name'] == TAG
    return obj


start = time.perf_counter()
report = {'schema': 'hcsn-cloud-p2-draft-upload-v1', 'repository': REPO,
          'repository_visibility': 'public', 'release_id': RID, 'tag': TAG,
          'publish_requested': False, 'overwrite_existing_assets': False,
          'runner_sha256': digest(Path(__file__)), 'assets': [],
          'started_utc': datetime.now(timezone.utc).isoformat()}
try:
    before = release('release-before')
    report['draft_before'] = True
    raw = ROOT / 'official-localization-cloud.zip'
    if not raw.exists():
        url = 'https://archive.ics.uci.edu/static/public/196/localization%2Bdata%2Bfor%2Bperson%2Bactivity.zip'
        download_start = time.perf_counter()
        with urllib.request.urlopen(url, timeout=180) as response:
            payload = response.read()
            status = response.status
        assert len(payload) == EXPECTED[raw.name][0]
        assert hashlib.sha256(payload).hexdigest() == EXPECTED[raw.name][1]
        with raw.open('xb') as stream:
            stream.write(payload)
        save('official-data-download.json', {'url': url, 'http_status': status,
             'bytes': len(payload), 'sha256': digest(raw),
             'matches_actual_cloud_training_source': True,
             'wall_seconds': time.perf_counter()-download_start})
    download_dir = OUT / 'authenticated-readback'
    download_dir.mkdir()
    for number, (name, (size, sha)) in enumerate(EXPECTED.items()):
        path = ROOT / name
        assert path.stat().st_size == size and digest(path) == sha
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
        existing = [a for a in before.get('assets', []) if a['name'] == name]
        assert len(existing) <= 1
        if not existing:
            save(f'asset-{number}-upload-intent.json', {'name': name, 'bytes': size, 'sha256': sha})
            run([GH, 'release', 'upload', TAG, str(path), '--repo', REPO], f'asset-{number}-upload')
        after = release(f'asset-{number}-release-after')
        assets = [a for a in after['assets'] if a['name'] == name]
        assert len(assets) == 1 and assets[0]['size'] == size
        asset = assets[0]
        run([GH, 'release', 'download', TAG, '--repo', REPO, '--pattern', name,
             '--dir', str(download_dir)], f'asset-{number}-readback')
        observed = download_dir / name
        assert observed.stat().st_size == size and digest(observed) == sha
        status = run(['/usr/bin/curl', '--disable', '--silent', '--show-error', '--location',
                      '--max-time', '60', '--output', '/dev/null', '--write-out', '%{http_code}',
                      asset['browser_download_url']], f'asset-{number}-anonymous', timeout=70).strip()
        row = {'name': name, 'asset_id': asset['id'], 'size': size, 'sha256': sha,
               'authenticated_readback_matches': True, 'preexisting_reconciled': bool(existing),
               'url': asset['browser_download_url'],
               'anonymous_http_status_without_client_authorization': status}
        report['assets'].append(row)
        save(f'asset-{number}-verified.json', row)
        print(json.dumps(row), flush=True)
    report['draft_after'] = release('release-final')['draft']
    report['anonymous_release_api_status_without_client_authorization'] = run([
        '/usr/bin/curl', '--disable', '--silent', '--show-error', '--location', '--max-time', '60',
        '--output', '/dev/null', '--write-out', '%{http_code}',
        f'https://api.github.com/repos/{REPO}/releases/{RID}'], 'anonymous-release', timeout=70).strip()
    assert report['anonymous_release_api_status_without_client_authorization'] == '404'
    assert all(a['anonymous_http_status_without_client_authorization'] == '404' for a in report['assets'])
    report['status'] = 'uploaded_readback_and_draft_isolation_verified'
except Exception:
    report.update(status='error', detail=traceback.format_exc())
finally:
    report['wall_seconds'] = time.perf_counter() - start
    report['completed_utc'] = datetime.now(timezone.utc).isoformat()
    save('receipt.json', report)
    print(json.dumps(report), flush=True)
raise SystemExit(0 if report['status'] == 'uploaded_readback_and_draft_isolation_verified' else 1)
