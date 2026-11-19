"""Preserve the native attention trace and append three immutable draft assets."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time
import traceback
import zipfile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
PROFILE = BASE / 'native-attention-path-v1'
OUT = BASE / 'review-profile-evidence-upload-v1'
REPO = 'TrillionniumFoundation/hepta-private-ci'
RELEASE = 440410488
TAG = 'hcsn-research-20261110-c385'
TARGET = 'd2fd5faaf08f1349d02f10086322b99b3222f2a3'
EXPECTED = [
    (Path('/home/qian-qi/hepta-hcsn-independent-baseline36-c1-20261110-c385-v1.zip'),
     16391589, 'd882d080345c606ca8bff395db192a51da2f8b821db3d71eb6d7a529f3afda13',
     'first independent subset review; overall failed evidence retained'),
    (Path('/home/qian-qi/hepta-hcsn-independent-baseline36-c1-20261110-c385-v2.zip'),
     19356087, 'ef4d8bbb5b72945410e39155728d2b0920d24c46c998b9f0192ab23cf322156d',
     'independent completed baseline36 plus seven C1 chains; not full42'),
]


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')


def pack_profile():
    started = time.monotonic()
    assert sha(PROFILE / 'RESULT.json') == 'cc600b6e8823ae38498c939891117107e15ac7feb4a43d43067a7c343d8fe024'
    assert sha(PROFILE / 'worker-result.json') == '305ffcce56ee044775d39a87197bab10cf419536e4e39ca53043c37b0d11fde2'
    report = json.loads((PROFILE / 'worker-result.json').read_bytes())
    assert report['passed'] and report['source_unchanged'] and report['model_unchanged']
    members = {str(p.relative_to(BASE)): p for p in PROFILE.rglob('*') if p.is_file()}
    for path in (BASE / 'inspect_native_attention_v1.py', BASE / 'training-source-v8.zip'):
        members[path.name] = path
    for original, expected in report['source_before'].items():
        path = Path(original)
        assert sha(path) == expected
        name = str(path.relative_to(BASE)) if path.is_relative_to(BASE) else 'external-loaded-source/' + expected[:20] + '/' + path.name
        if name in members:
            assert sha(members[name]) == expected
        else:
            members[name] = path
    manifest = {name: {'bytes': path.stat().st_size, 'sha256': sha(path), 'original_path': str(path)}
                for name, path in sorted(members.items())}
    path = OUT / 'hcsn-native-attention-path-20261110-v1.zip'
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for name, original in sorted(members.items()):
            assert not name.startswith('/') and '..' not in Path(name).parts and not original.is_symlink()
            zipped.write(original, name)
        zipped.writestr('MEMBER-MANIFEST.json', json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    with zipfile.ZipFile(path) as zipped:
        assert zipped.testzip() is None
        for name, identity in manifest.items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == identity['sha256']
    assert all(sha(p) == manifest[name]['sha256'] for name, p in members.items())
    result = {'name': path.name, 'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path),
        'members': len(manifest) + 1, 'all_member_sha_and_crc_verified': True, 'source_unchanged': True,
        'wall_seconds': time.monotonic() - started, 'scope': 'operator path evidence; no speed/energy superiority credit'}
    write(OUT / 'PROFILE-ARCHIVE-RECEIPT.json', result)
    return path, result


def main():
    OUT.mkdir(exist_ok=False)
    (OUT / 'authenticated-readback').mkdir()
    started, own_cpu = time.monotonic(), time.process_time()
    report = {'schema': 'hcsn-review-profile-draft-assets-v1', 'status': 'started', 'assets': [], 'commands': [],
        'repository': REPO, 'release_id': RELEASE, 'publish_requested': False, 'overwrite_existing_assets': False,
        'automatic_retry': False, 'driver_sha256': sha(Path(__file__)),
        'started_utc': datetime.now(timezone.utc).isoformat(), 'scientific_admission': 'HOLD'}

    def run(label, argv, timeout=120):
        tick = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        row, stdout, stderr = {'label': label, 'argv': argv}, b'', b''
        try:
            completed = subprocess.run(argv, capture_output=True, timeout=timeout)
            stdout, stderr = completed.stdout, completed.stderr
            row.update(status='completed', returncode=completed.returncode)
            if completed.returncode:
                raise RuntimeError(label + ' failed; no blind retry')
            return stdout
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b'', error.stderr or b''
            row['status'] = 'timeout_outcome_unknown'
            raise
        except Exception as error:
            row.setdefault('status', 'command_exception')
            row['error_type'] = type(error).__name__
            raise
        finally:
            (OUT / (label + '.stdout')).write_bytes(stdout)
            (OUT / (label + '.stderr')).write_bytes(stderr)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            row.update(wall_seconds=time.monotonic() - tick,
                children_cpu_seconds=after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest())
            report['commands'].append(row)

    def release(label):
        value = json.loads(run(label, ['/usr/bin/gh', 'api', f'repos/{REPO}/releases/{RELEASE}']))
        assert value['id'] == RELEASE and value['draft'] is True and value['prerelease'] is True
        assert value['tag_name'] == TAG and value['target_commitish'] == TARGET
        return value

    def anonymous(label, url):
        status = run(label, ['/usr/bin/curl', '--disable', '--silent', '--show-error', '--location',
            '--max-time', '60', '--output', '/dev/null', '--write-out', '%{http_code}', url], timeout=70).decode().strip()
        assert status == '404', 'anonymous draft isolation not confirmed'
        return {'url': url, 'http_status': status, 'client_authorization_sent': False}

    try:
        path, archive = pack_profile()
        report['profile_archive'] = archive
        files = EXPECTED + [(path, archive['bytes'], archive['sha256'],
                             'native trained attention checkpoint CPU FP64 forward/backward path; zero optimizer steps')]
        repo = json.loads(run('repo-check', ['/usr/bin/gh', 'api', f'repos/{REPO}', '--jq',
            '{full_name: .full_name, private: .private}']))
        assert repo == {'full_name': REPO, 'private': False}
        report['repository_readback'] = repo
        release('draft-initial')
        report['anonymous_release_before'] = anonymous('anonymous-release-before',
            f'https://api.github.com/repos/{REPO}/releases/{RELEASE}')
        for index, (path, size, digest, purpose) in enumerate(files):
            assert path.stat().st_size == size and sha(path) == digest
            prefix = f'asset-{index:02d}'
            current = release(prefix + '-before')
            found = [a for a in current['assets'] if a['name'] == path.name]
            disposition = 'existing_asset_reconciled_no_overwrite'
            if not found:
                run(prefix + '-upload', ['/usr/bin/gh', 'release', 'upload', TAG, str(path), '--repo', REPO], 300)
                disposition = 'uploaded_once'
                current = release(prefix + '-after')
                found = [a for a in current['assets'] if a['name'] == path.name]
            assert len(found) == 1 and found[0]['size'] == size
            asset = found[0]
            row = {'name': path.name, 'asset_id': asset['id'], 'bytes': size, 'sha256': digest,
                'purpose': purpose, 'disposition': disposition, 'readback_verified': False}
            report['assets'].append(row)
            run(prefix + '-download', ['/usr/bin/gh', 'release', 'download', TAG, '--repo', REPO,
                '--pattern', path.name, '--dir', str(OUT / 'authenticated-readback')], 600)
            actual = OUT / 'authenticated-readback' / path.name
            assert actual.stat().st_size == size and sha(actual) == digest
            row.update(readback_verified=True, authenticated_readback_sha256=sha(actual),
                anonymous_asset_api=anonymous(prefix + '-anonymous-api', asset['url']),
                anonymous_asset_browser=anonymous(prefix + '-anonymous-browser', asset['browser_download_url']))
            print(json.dumps({k:row[k] for k in ('name', 'asset_id', 'bytes', 'sha256')}), flush=True)
        release('draft-final')
        report['anonymous_release_after'] = anonymous('anonymous-release-after',
            f'https://api.github.com/repos/{REPO}/releases/{RELEASE}')
        report['status'] = 'three_assets_uploaded_full_byte_verified_draft_unchanged'
    except Exception:
        report.update(status='failed_or_unknown_no_blind_retry', error=traceback.format_exc())
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(whole_controller_wall_seconds=time.monotonic() - started,
            own_cpu_seconds=time.process_time() - own_cpu, children_cpu_seconds=usage.ru_utime + usage.ru_stime,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            cost_scope='controller wall includes profile packaging, validation and network waits; own/child CPU separate; command wall and package wall are overlapping subsets')
        write(OUT / 'RESULT.json', report)
        print(json.dumps({k:report[k] for k in ('status', 'whole_controller_wall_seconds', 'own_cpu_seconds',
                                             'children_cpu_seconds')}), flush=True)
    return 0 if report['status'] == 'three_assets_uploaded_full_byte_verified_draft_unchanged' else 2


if __name__ == '__main__':
    raise SystemExit(main())
