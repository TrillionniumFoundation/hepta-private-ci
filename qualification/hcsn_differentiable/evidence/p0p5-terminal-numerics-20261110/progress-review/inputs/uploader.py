"""One bounded, no-clobber publication of completed numerical evidence to a draft."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import subprocess
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

REPO = 'TrillionniumFoundation/hepta-private-ci'
RELEASE, TAG = 440410488, 'hcsn-research-20261110-c385'
TARGET = 'd2fd5faaf08f1349d02f10086322b99b3222f2a3'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def identity(path):
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def zip_check(path, original=False):
    with ZipFile(path) as zipped:
        names = zipped.namelist()
        require(len(names) == len(set(names)), 'duplicate ZIP names')
        require(sum(i.file_size for i in zipped.infolist()) <= 2 * 1024**3, 'ZIP expansion bound')
        for item in zipped.infolist():
            p = PurePosixPath(item.filename)
            require(not p.is_absolute() and '..' not in p.parts and '\\' not in item.filename
                    and (item.external_attr >> 16) & 0o170000 != 0o120000, 'unsafe ZIP name/type')
        require(zipped.testzip() is None, 'ZIP CRC failure')
        if original:
            rows = json.loads(zipped.read('postmortem/ORIGINAL-MANIFEST.json'))
        else:
            rows = [dict(member=k, **v) for k, v in json.loads(zipped.read('MEMBER-MANIFEST.json')).items()]
        for row in rows:
            h, size = hashlib.sha256(), 0
            with zipped.open(row['member']) as stream:
                for block in iter(lambda: stream.read(1048576), b''):
                    h.update(block)
                    size += len(block)
            require(size == row['bytes'] and h.hexdigest() == row['sha256'], 'ZIP member identity mismatch')


def main(args):
    require(sha(args.plan) == args.plan_sha256, 'input plan SHA mismatch')
    plan = json.loads(args.plan.read_bytes())
    require(plan['schema'] == 'terminal-numerics-draft-upload-input-v1', 'wrong plan schema')
    out = Path(plan['output'])
    out.mkdir(exist_ok=False)
    (out / 'authenticated-readback').mkdir()
    start, cpu, usage0 = time.monotonic(), time.process_time(), resource.getrusage(resource.RUSAGE_CHILDREN)
    source_before = sha(Path(__file__))
    report = {'schema': 'terminal-numerics-draft-upload-result-v1', 'status': 'started', 'commands': [],
              'assets': [], 'release_id': RELEASE, 'repository': REPO, 'draft_only': True,
              'publish_requested': False, 'overwrite': False, 'automatic_retry': False,
              'source_sha256': source_before, 'plan_sha256': args.plan_sha256,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'scientific_admission': 'HOLD'}

    def command(label, argv, timeout=120):
        tick, before = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
        row, stdout, stderr = {'label': label, 'argv': argv, 'timeout_seconds': timeout}, b'', b''
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
            (out / (label + '.stdout')).write_bytes(stdout)
            (out / (label + '.stderr')).write_bytes(stderr)
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            row.update(wall_seconds=time.monotonic() - tick,
                       waited_child_CPU_seconds=usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime,
                       stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest())
            report['commands'].append(row)

    def release(label):
        r = json.loads(command(label, ['/usr/bin/gh', 'api', f'repos/{REPO}/releases/{RELEASE}']))
        require(r['id'] == RELEASE and r['draft'] is True and r['prerelease'] is True
                and r['tag_name'] == TAG and r['target_commitish'] == TARGET, 'draft identity changed')
        return r

    def assets(label):
        rows = []
        for page in range(1, 11):
            items = json.loads(command(label + '-page-' + str(page), ['/usr/bin/gh', 'api',
                               f'repos/{REPO}/releases/{RELEASE}/assets?per_page=100&page={page}']))
            require(isinstance(items, list), 'asset list schema')
            rows.extend(items)
            if len(items) < 100:
                break
        else:
            raise ValueError('asset inventory exceeds frozen limit')
        require(len({r['id'] for r in rows}) == len(rows), 'duplicate asset ids')
        return rows

    def anonymous(label, url):
        status = command(label, ['/usr/bin/curl', '--disable', '--silent', '--show-error', '--location',
                         '--max-time', '60', '--output', '/dev/null', '--write-out', '%{http_code}', url], 70).decode().strip()
        require(status == '404', 'anonymous draft isolation not established')
        return {'url': url, 'HTTP_status': status, 'authorization_header_sent': False}

    try:
        inputs = {row['member']: (Path(row['path']), {'bytes': row['bytes'], 'sha256': row['sha256']})
                  for row in plan['receipt_inputs']}
        require(len(inputs) == len(plan['receipt_inputs']) and len(inputs) <= 30, 'receipt input roster')
        for p, expected in inputs.values():
            require(p.is_file() and not p.is_symlink() and expected['bytes'] <= 16777216
                    and identity(p) == expected, 'external receipt identity')
        collection = json.loads(Path(plan['collection_receipt']).read_bytes())
        bootstrap = json.loads(Path(plan['bootstrap_receipt']).read_bytes())
        require(any(p == Path(plan['collection_receipt']) for p, _ in inputs.values())
                and any(p == Path(plan['bootstrap_receipt']) for p, _ in inputs.values()), 'unbound receipt path')
        original = Path(plan['original_archive']['path'])
        expected = {k: plan['original_archive'][k] for k in ('bytes', 'sha256')}
        require(collection['metadata_collection_status'] == 'completed'
                and bootstrap['status'] == 'completed_metadata_collection', 'collection not complete')
        require(all(collection['archive'][k] == expected[k] for k in expected)
                and all(bootstrap['archive'][k] == expected[k] for k in expected), 'collection archive binding')
        require(original.is_file() and not original.is_symlink() and identity(original) == expected, 'original archive identity')
        zip_check(original, original=True)
        (out / 'PLAN.json').write_bytes(args.plan.read_bytes())
        (out / 'uploader.py').write_bytes(Path(__file__).read_bytes())
        inputs['upload/PLAN.json'] = (out / 'PLAN.json', identity(out / 'PLAN.json'))
        inputs['upload/uploader.py'] = (out / 'uploader.py', identity(out / 'uploader.py'))
        name = plan['receipt_asset_name']
        require(Path(name).name == name and name.endswith('.zip'), 'receipt asset basename')
        package = out / name
        with ZipFile(package, 'x', ZIP_DEFLATED, compresslevel=9) as zipped:
            for member, (path, _) in sorted(inputs.items()):
                require(not PurePosixPath(member).is_absolute() and '..' not in PurePosixPath(member).parts,
                        'unsafe receipt member')
                zipped.write(path, member)
            zipped.writestr('MEMBER-MANIFEST.json', json.dumps({k: v for k, (_, v) in inputs.items()}, sort_keys=True) + '\n')
        zip_check(package)
        save(out / 'PACKAGE-RECEIPT.json', {'original_archive': {'path': str(original), **expected},
                                         'receipt_archive': {'path': str(package), **identity(package)}})
        release('draft-before')
        report['anonymous_release_before'] = anonymous('anonymous-release-before', f'https://api.github.com/repos/{REPO}/releases/{RELEASE}')
        for index, path in enumerate((original, package)):
            prefix, intended = str(index), identity(path)
            found = [r for r in assets(prefix + '-inventory-before') if r['name'] == path.name]
            disposition = 'existing_same_name_no_upload'
            if not found:
                save(out / (prefix + '-upload-intent.json'), {'name': path.name, **intended, 'release_id': RELEASE})
                command(prefix + '-upload-once', ['/usr/bin/gh', 'release', 'upload', TAG, str(path), '--repo', REPO], 300)
                disposition = 'uploaded_once'
                release(prefix + '-draft-after-upload')
                found = [r for r in assets(prefix + '-inventory-after') if r['name'] == path.name]
            require(len(found) == 1 and found[0]['state'] == 'uploaded' and found[0]['size'] == intended['bytes'],
                    'asset absent/ambiguous/starter/wrong size; no overwrite')
            asset = found[0]
            require(asset.get('digest') in (None, 'sha256:' + intended['sha256']), 'server digest differs')
            row = {'asset_id': asset['id'], 'name': path.name, **intended, 'disposition': disposition,
                   'authenticated_full_readback_verified': False}
            report['assets'].append(row)
            command(prefix + '-authenticated-download', ['/usr/bin/gh', 'release', 'download', TAG, '--repo', REPO,
                    '--pattern', path.name, '--dir', str(out / 'authenticated-readback')], 600)
            downloaded = out / 'authenticated-readback' / path.name
            require(identity(downloaded) == intended, 'authenticated byte readback mismatch')
            zip_check(downloaded, original=index == 0)
            row.update(authenticated_full_readback_verified=True, authenticated_readback_sha256=sha(downloaded),
                       CRC_and_members_verified=True, anonymous_asset_API=anonymous(prefix + '-anonymous-api', asset['url']),
                       anonymous_asset_browser=anonymous(prefix + '-anonymous-browser', asset['browser_download_url']))
        require(all(identity(p) == expected_i for p, expected_i in inputs.values()) and identity(original) == expected,
                'publication inputs changed')
        report['status'] = 'both_assets_authenticated_verified_draft_unchanged'
    except Exception:
        report.update(status='failed_or_unknown_preserved_no_retry', error=traceback.format_exc())
    finally:
        try:
            final = release('draft-finally')
            report['final_draft_identity'] = {'id': final['id'], 'draft': True, 'tag_name': final['tag_name']}
            report['anonymous_release_after'] = anonymous('anonymous-release-after', f'https://api.github.com/repos/{REPO}/releases/{RELEASE}')
        except Exception:
            report.update(status='failed_or_unknown_preserved_no_retry', final_draft_error=traceback.format_exc())
        if sha(Path(__file__)) != source_before or sha(args.plan) != args.plan_sha256:
            report.update(status='failed_or_unknown_preserved_no_retry', source_or_plan_changed=True)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(main_entry_wall_seconds=time.monotonic() - start, own_CPU_seconds=time.process_time() - cpu,
                      own_absolute_CPU_seconds=time.process_time(),
                      waited_children_CPU_seconds=usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime,
                      own_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      finished_utc=datetime.now(timezone.utc).isoformat(), energy_joules=None,
                      cost_scope='Outer GNU includes interpreter/imports plus packaging/network. Inner command/package times overlap; original audit and collector are separate already-measured jobs.')
        save(out / 'RESULT.json', report)
        print(json.dumps({k: report[k] for k in ('status', 'assets', 'main_entry_wall_seconds')}), flush=True)
    return 0 if report['status'] == 'both_assets_authenticated_verified_draft_unchanged' else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    raise SystemExit(main(parser.parse_args()))
