"""Reuse the sealed original replay archive; compatibility-fixed bounded asset GET."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
REPLAY = Path('/home/qian-qi/hepta-hcsn-best-full-D-replay-20261110-c385-v1')
PROGRAM = Path('/home/qian-qi/hepta-hcsn-best-full-D-replay-program-20261110-c385-v1')
OUT = BASE / 'best-full-D-asset-upload-v2'
REPO, RELEASE, TAG = 'TrillionniumFoundation/hepta-private-ci', 440410488, 'hcsn-research-20261110-c385'
TARGET = 'd2fd5faaf08f1349d02f10086322b99b3222f2a3'
PROGRAM_SHA = 'a748888f26409ff6f5fff8db8a9266cf67d0a5f5516dc88b566cd3c296fca206'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    return dict(bytes=path.stat().st_size, sha256=sha(path), original_path=str(path))


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def checked_zip(path, members):
    manifest = {name: identity(original) for name, original in sorted(members.items())}
    with ZipFile(path, 'x', compression=ZIP_DEFLATED) as zipped:
        for name, original in sorted(members.items()):
            require(not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name
                    and not original.is_symlink(), 'unsafe archive member')
            zipped.write(original, name)
        zipped.writestr('MEMBER-MANIFEST.json', json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    with ZipFile(path) as zipped:
        require(zipped.testzip() is None and len(zipped.namelist()) == len(set(zipped.namelist())) == len(manifest) + 1,
                'archive CRC/roster mismatch')
        for name, item in manifest.items():
            raw = zipped.read(name)
            require(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'], 'archive member differs')
    require(all(identity(original) == manifest[name] for name, original in members.items()), 'archive source changed')
    return manifest


def package(args):
    prior = BASE / 'best-full-D-archive-upload-v1'
    require(sha(prior / 'RESULT.json') == '91c233ff48bc35cd5cc4a97d372b425d45c11595f24051ea001fc0c4d3abab90', 'prior failure identity differs')
    failed = json.loads((prior / 'RESULT.json').read_bytes())
    require(not failed['assets'] and not any(c['label'] == 'upload-once' for c in failed['commands']), 'prior mutation may have been attempted')
    require(sha(prior / 'ARCHIVE-RECEIPT.json') == 'b15a7ffb3d8b34d7a4a9d9076366dbbf4a3bc48e71e1d980b2ca824f78ec0c20', 'package receipt differs')
    raw = (prior / 'ARCHIVE-RECEIPT.json').read_bytes()
    with (OUT / 'ARCHIVE-RECEIPT.json').open('xb') as stream: stream.write(raw)
    receipt = json.loads(raw)
    path = Path(receipt['archive']['original_path'])
    require(path.stat().st_size == 19144412 and sha(path) == 'ff41e5ef909708a5c2472f6786d0e82b6d69a80d968047de2746bcaf84daaac5', 'existing sealed archive differs')
    with ZipFile(path) as zipped:
        require(zipped.testzip() is None, 'sealed archive CRC differs')
        manifest = json.loads(zipped.read('MEMBER-MANIFEST.json'))
        require(len(zipped.namelist()) == len(set(zipped.namelist())) == len(manifest)+1 == 254, 'sealed archive roster differs')
        for name,item in manifest.items():
            data=zipped.read(name)
            require(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'], 'sealed member differs')
    save(OUT / 'PRIOR-FAILURE.json', failed)
    return path, receipt


def main(args):
    OUT.mkdir(exist_ok=False)
    (OUT / 'authenticated-readback').mkdir()
    start, cpu = time.monotonic(), time.process_time()
    usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = dict(schema='independent-best-D-draft-publication-v2', status='started', commands=[], assets=[],
                  release_id=RELEASE, repository=REPO, publish_requested=False, overwrite_existing_assets=False,
                  automatic_retry=False, scientific_admission='HOLD', driver_sha256=sha(Path(__file__)),
                  started_utc=datetime.now(timezone.utc).isoformat())
    def command(label, argv, timeout=120):
        tick = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        row, stdout, stderr = dict(label=label, argv=argv, timeout_seconds=timeout), b'', b''
        try:
            env = dict(os.environ)
            env.pop('GH_DEBUG', None)
            done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
            stdout, stderr = done.stdout, done.stderr
            row.update(status='completed', returncode=done.returncode)
            require(done.returncode == 0, label + ' failed; no retry')
            return stdout
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b'', error.stderr or b''
            row['status'] = 'timeout_outcome_unknown_no_retry'
            raise
        except Exception as error:
            row.setdefault('status', 'command_exception')
            row['error_type'] = type(error).__name__
            raise
        finally:
            (OUT / (label + '.stdout')).write_bytes(stdout)
            (OUT / (label + '.stderr')).write_bytes(stderr)
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            row.update(wall_seconds=time.monotonic() - tick,
                       waited_child_CPU_seconds=usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime,
                       stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest())
            report['commands'].append(row)
    def release(label):
        value = json.loads(command(label, ['/usr/bin/gh', 'api', f'repos/{REPO}/releases/{RELEASE}']))
        require(value['id'] == RELEASE and value['draft'] is True and value['prerelease'] is True
                and value['tag_name'] == TAG and value['target_commitish'] == TARGET, 'draft identity changed')
        return value
    def assets(label):
        rows = []
        for page in range(1, 11):
            items = json.loads(command(label + '-page-' + str(page), ['/usr/bin/gh', 'api', f'repos/{REPO}/releases/{RELEASE}/assets?per_page=100&page={page}']))
            require(isinstance(items, list), 'asset-list page is not an array')
            rows.extend(items)
            if len(items) < 100:
                break
        else:
            raise ValueError('asset inventory exceeds frozen 1000-member bound; no upload')
        require(len({row['id'] for row in rows}) == len(rows), 'duplicate asset list')
        return rows
    def anonymous(label, url):
        value = command(label, ['/usr/bin/curl', '--disable', '--silent', '--show-error', '--location', '--max-time', '60',
                                '--output', '/dev/null', '--write-out', '%{http_code}', url], 70).decode().strip()
        require(value == '404', 'anonymous draft isolation not established')
        return dict(url=url, HTTP_status=value, authorization_header_sent=False)
    try:
        path, receipt = package(args)
        report['archive_receipt_sha256'] = sha(OUT / 'ARCHIVE-RECEIPT.json')
        report['archive'] = receipt
        release('draft-before')
        report['anonymous_release_before'] = anonymous('anonymous-release-before', f'https://api.github.com/repos/{REPO}/releases/{RELEASE}')
        found = [row for row in assets('asset-list-before') if row['name'] == path.name]
        disposition = 'existing_asset_no_upload'
        if not found:
            save(OUT / 'upload-intent.json', dict(name=path.name, **identity(path), release_id=RELEASE, overwrite=False))
            command('upload-once', ['/usr/bin/gh', 'release', 'upload', TAG, str(path), '--repo', REPO], 300)
            disposition = 'uploaded_once'
            release('draft-after-upload')
            found = [row for row in assets('asset-list-after') if row['name'] == path.name]
        require(len(found) == 1 and found[0]['state'] == 'uploaded' and found[0]['size'] == path.stat().st_size,
                'asset is absent/ambiguous/starter/wrong-size; do not overwrite or retry')
        asset = found[0]
        require(asset.get('digest') in (None, 'sha256:' + sha(path)), 'asset metadata digest differs')
        row = dict(asset_id=asset['id'], name=path.name, bytes=path.stat().st_size, sha256=sha(path),
                   disposition=disposition, authenticated_full_readback_verified=False)
        report['assets'].append(row)
        command('authenticated-download', ['/usr/bin/gh', 'release', 'download', TAG, '--repo', REPO,
                                           '--pattern', path.name, '--dir', str(OUT / 'authenticated-readback')], 600)
        downloaded = OUT / 'authenticated-readback' / path.name
        require(downloaded.stat().st_size == path.stat().st_size and sha(downloaded) == sha(path), 'full authenticated SHA mismatch')
        with ZipFile(downloaded) as zipped:
            require(zipped.testzip() is None, 'authenticated archive CRC failure')
            manifest = json.loads(zipped.read('MEMBER-MANIFEST.json'))
            require(len(zipped.namelist()) == len(set(zipped.namelist())) == len(manifest) + 1, 'authenticated roster mismatch')
            for name, expected in manifest.items():
                raw = zipped.read(name)
                require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'], 'authenticated member mismatch')
        row.update(authenticated_full_readback_verified=True, authenticated_readback_sha256=sha(downloaded),
                   all_members_and_CRC_verified=True,
                   anonymous_asset_API=anonymous('anonymous-asset-api', asset['url']),
                   anonymous_asset_browser=anonymous('anonymous-asset-browser', asset['browser_download_url']))
        release('draft-final')
        report['anonymous_release_after'] = anonymous('anonymous-release-after', f'https://api.github.com/repos/{REPO}/releases/{RELEASE}')
        report['status'] = 'full_replay_asset_verified_draft_unchanged'
    except Exception:
        report.update(status='failed_or_unknown_preserved_no_retry', error=traceback.format_exc())
    finally:
        try:
            final_draft = release('draft-finally-readback')
            report['final_draft_identity_verified'] = dict(id=final_draft['id'], draft=True, tag_name=final_draft['tag_name'])
        except Exception:
            report.update(status='failed_or_unknown_preserved_no_retry', final_draft_readback_error=traceback.format_exc())
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(main_entry_wall_seconds=time.monotonic() - start, computation_CPU_seconds=time.process_time() - cpu,
                      absolute_own_process_CPU_seconds=time.process_time(),
                      waited_children_CPU_seconds=usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime,
                      own_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      finished_utc=datetime.now(timezone.utc).isoformat(), energy_joules=None,
                      cost_scope='Main-entry packaging/network interval; outer wrapper records complete process. Nested package/command times overlap. Replay and validation occurred in previous separately measured processes.')
        save(OUT / 'RESULT.json', report)
        print(json.dumps(dict(status=report['status'], assets=report['assets'], main_entry_wall_seconds=report['main_entry_wall_seconds'])), flush=True)
    return 0 if report['status'] == 'full_replay_asset_verified_draft_unchanged' else 2


if __name__ == '__main__':
    raise SystemExit(main(None))
