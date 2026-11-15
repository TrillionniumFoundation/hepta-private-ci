"""Append original terminal 42-fit evidence to the existing unpublished draft."""
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
OUT = BASE / 'fresh42-terminal-upload-v1'
ARCHIVE_RECEIPT = BASE / 'fresh42-terminal-archives-v1/ARCHIVE-RECEIPT.json'
REPO = 'TrillionniumFoundation/hepta-private-ci'
RELEASE = 440410488
TAG = 'hcsn-research-20261110-c385'
TARGET = 'd2fd5faaf08f1349d02f10086322b99b3222f2a3'


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')


def main():
    OUT.mkdir(exist_ok=False)
    (OUT / 'authenticated-readback').mkdir()
    started, own_cpu = time.monotonic(), time.process_time()
    report = {'schema': 'hcsn-original-fresh42-draft-assets-v1', 'status': 'started', 'assets': [], 'commands': [],
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
        archive = json.loads(ARCHIVE_RECEIPT.read_bytes())
        assert archive['status'] == 'completed_all42_originals_archived_all_member_hashes_verified'
        assert archive['original_result_sha256'] == '362bc0345635bb5c9438670c13efa5908140527463aa4f373479235686b5683b'
        assert archive['archiver_sha256'] == '10b509c5dc4bc080fc40817a8e0f02fde1c1beae396c05f11427a3ea3b5bfa3b'
        assert archive['archived_fit_count'] == 42 and len(archive['assets']) == 8
        report['archive_receipt_sha256'] = sha(ARCHIVE_RECEIPT)
        report['archive_costs_separate'] = {k: archive[k] for k in
            ('whole_wall_seconds', 'own_cpu_seconds', 'full_process_cpu_seconds')}
        files = [(Path(row['path']), row['bytes'], row['sha256'],
            'Original terminal 42-fit stage; six HCSN resource-censored; all failures retained; scientific HOLD')
            for row in [archive['small_handoff']] + archive['assets']]
        assert len({path.name for path, _, _, _ in files}) == 9
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
        report['status'] = 'nine_original42_assets_full_byte_verified_draft_unchanged'
    except Exception:
        report.update(status='failed_or_unknown_no_blind_retry', error=traceback.format_exc())
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(whole_controller_wall_seconds=time.monotonic() - started,
            own_cpu_seconds=time.process_time() - own_cpu, children_cpu_seconds=usage.ru_utime + usage.ru_stime,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            cost_scope='controller wall includes archive verification and all network waits; prior archive process charged separately; command wall is overlapping subset; own and child CPU separate')
        write(OUT / 'RESULT.json', report)
        print(json.dumps({k:report[k] for k in ('status', 'whole_controller_wall_seconds', 'own_cpu_seconds',
                                             'children_cpu_seconds')}), flush=True)
    return 0 if report['status'] == 'nine_original42_assets_full_byte_verified_draft_unchanged' else 2


if __name__ == '__main__':
    raise SystemExit(main())
