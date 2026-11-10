"""Seal exact replay evidence, then append one asset to the existing draft."""
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
OUT = BASE / 'best-full-D-archive-upload-v1'
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
    started, cpu = time.monotonic(), time.process_time()
    boot, launch = BASE / 'best-full-D-replay-bootstrap-v1', BASE / 'best-full-D-replay-launch-v1'
    for path, expected in [(REPLAY / 'SUMMARY.json', args.summary_sha), (boot / 'receipt.json', args.bootstrap_sha),
                           (launch / 'receipt.json', args.launch_sha)]:
        require(sha(path) == expected, 'terminal replay input differs')
    summary = json.loads((REPLAY / 'SUMMARY.json').read_bytes())
    bootstrap = json.loads((boot / 'receipt.json').read_bytes())
    launch_receipt = json.loads((launch / 'receipt.json').read_bytes())
    plan = json.loads((PROGRAM / 'PLAN.json').read_bytes())
    require(bootstrap['status'] == launch_receipt['status'] == 'completed' and bootstrap['program_sha256'] == PROGRAM_SHA,
            'replay has not reached acknowledged terminal state')
    require(summary['execution_status'] == 'completed_fixed_roster' and [x['name'] for x in summary['entries']] == plan['fit_roster'],
            'declared six-fit roster is incomplete')
    for directory, manifest_name, wrapped in [(REPLAY, 'MANIFEST.json', True), (PROGRAM, 'MANIFEST.json', True)]:
        manifest = json.loads((directory / manifest_name).read_bytes())['files']
        require({str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()} == set(manifest) | {manifest_name},
                'unindexed original output/program file')
        for name, item in manifest.items():
            p = directory / name
            require(p.stat().st_size == item['bytes'] and sha(p) == item['sha256'], 'frozen member changed')
    require(sha(PROGRAM / 'MANIFEST.json') == '8cd0fdcf94a5af733173d6fc513b2b379df8bdd9f28604116658fe40a7c19e12',
            'program manifest changed')
    members = {}
    for prefix, directory in [('replay', REPLAY), ('program', PROGRAM), ('bootstrap', boot), ('launch', launch)]:
        for path in directory.rglob('*'):
            if path.is_file():
                members[prefix + '/' + str(path.relative_to(directory))] = path
    members['publication/archive_upload_native.py'] = Path(__file__)
    source_archive = BASE / 'training-source-v8.zip'
    require(sha(source_archive) == plan['source_capsule_sha256'], 'actual v8 source capsule differs')
    members['v8-source/training-source-v8.zip'] = source_archive
    model_archive = BASE / 'fresh42-terminal-archives-v1/hcsn-fresh42-original-hcsn-20261110-v1.zip'
    require(model_archive.stat().st_size == 101021344 and sha(model_archive) == 'ca70f9cb216df636300e2da8e03a2596169aa4aaf7f1945dc614587049d63493',
            'previously verified original model archive differs')
    models = []
    with ZipFile(model_archive) as originals:
        for entry in summary['entries']:
            name, result = entry['name'], entry['result']
            require(sha(REPLAY / name / 'RESULT.json') == entry['result_sha256'], 'fit result binding differs')
            before = json.loads((REPLAY / name / 'input-identities-before.json').read_bytes())
            after = json.loads((REPLAY / name / 'input-identities-after.json').read_bytes())
            require(before == after and all(sha(p) == digest for p, digest in before.items()), 'replay source/input changed later')
            for filename in ('best.pt', 'initial.pt'):
                path = BASE / 'campaign-v2' / name / filename
                member = f'campaign-v2/{name}/{filename}'
                digest = hashlib.sha256(originals.read(member)).hexdigest()
                require(digest == before[str(path)], 'model archive member differs from actual replay input')
                models.append(dict(name=name, filename=filename, sha256=digest, archive_member=member))
            for source, digest in before.items():
                if source.endswith('.py'):
                    p = Path(source)
                    rel = str(p.relative_to(BASE / 'run-source-v8')) if p.is_relative_to(BASE / 'run-source-v8') else 'external/' + digest[:20] + '/' + p.name
                    members['loaded-source/' + rel] = p
    prepared = Path(plan['prepared'])
    for name in ('data-manifest.json', 'frontend.json', 'selection.json'):
        members['prepared-D/' + name] = prepared / name
    for entry in plan['dev_entries']:
        path = prepared / entry['path']
        require(sha(path) == entry['sha256'], 'D episode changed')
        members['prepared-D/' + entry['path']] = path
    bindings = dict(schema='independent-best-D-original-model-binding-v1', model_files_copied=False,
                    archive=dict(name=model_archive.name, bytes=101021344,
                                 sha256='ca70f9cb216df636300e2da8e03a2596169aa4aaf7f1945dc614587049d63493',
                                 previously_full_authenticated_readback_asset_id=732598130, release_id=RELEASE),
                    models=models, scientific_admission='HOLD', confirmation_E_access=False)
    save(OUT / 'ORIGINAL-MODEL-BINDINGS.json', bindings)
    costs = dict(schema='independent-best-D-replay-cost-scopes-v1', controller_complete=launch_receipt,
                 bootstrap_including_controller=bootstrap, local_validation=json.loads((PROGRAM / 'VALIDATION.json').read_bytes()),
                 per_fit=[dict(name=x['name'], outer=x['outer']) for x in summary['entries']],
                 exploratory_local_tests=dict(passed=16, process_wall_seconds=None, process_CPU_seconds=None,
                                               reason='First tool-only exploratory test run; no separate complete process cost retained.'),
                 additive_scope='Bootstrap and controller/per-fit timers overlap; do not sum them. Local validation is additional. Archive/upload process is separately recorded after this package is sealed.',
                 energy_joules=None, scientific_admission='HOLD')
    save(OUT / 'COSTS.json', costs)
    for name in ('ORIGINAL-MODEL-BINDINGS.json', 'COSTS.json'):
        members[name] = OUT / name
    archive = OUT / 'hcsn-best-full-D-independent-replay-20261110-v1.zip'
    manifest = checked_zip(archive, members)
    save(OUT / 'MEMBER-MANIFEST.json', manifest)
    small = {name: path for name, path in members.items() if name.split('/')[0] in ('replay', 'program', 'bootstrap', 'launch', 'publication') and not name.endswith('.pt')}
    for name in ('ORIGINAL-MODEL-BINDINGS.json', 'COSTS.json', 'MEMBER-MANIFEST.json'):
        small['archive-context/' + name] = OUT / name
    small_archive = OUT / 'hcsn-best-full-D-small-originals-20261110-v1.zip'
    checked_zip(small_archive, small)
    receipt = dict(status='packaged_all_six_readonly_replays', archive=identity(archive), small_handoff=identity(small_archive),
                   members=len(manifest) + 1, originals_unchanged=True, all_member_sha_and_crc_verified=True,
                   summary_sha256=args.summary_sha, copied_original_models=False,
                   original_controller_container_zip_preserved_native_not_reuploaded=bootstrap['replay_archive'],
                   replay_file_member_coverage='Every original replay-directory file is included byte-for-byte under replay/; this combined archive is a distinct container.',
                   package_wall_seconds=time.monotonic() - started, package_CPU_seconds=time.process_time() - cpu,
                   scientific_admission='HOLD', training_adequacy_established=False)
    save(OUT / 'ARCHIVE-RECEIPT.json', receipt)
    return archive, receipt


def main(args):
    OUT.mkdir(exist_ok=False)
    (OUT / 'authenticated-readback').mkdir()
    start, cpu = time.monotonic(), time.process_time()
    usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = dict(schema='independent-best-D-draft-publication-v1', status='started', commands=[], assets=[],
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
        pages = json.loads(command(label, ['/usr/bin/gh', 'api', '--paginate', '--slurp', f'repos/{REPO}/releases/{RELEASE}/assets?per_page=100']))
        require(isinstance(pages, list) and all(isinstance(page, list) for page in pages), 'asset list pagination unavailable')
        rows = [row for page in pages for row in page]
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
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('summary-sha', 'bootstrap-sha', 'launch-sha'):
        parser.add_argument('--' + name, required=True)
    raise SystemExit(main(parser.parse_args()))
