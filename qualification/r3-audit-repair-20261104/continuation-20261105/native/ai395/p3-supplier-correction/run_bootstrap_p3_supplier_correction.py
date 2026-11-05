import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone

ROOT = Path('/home/qq/work/hepta-audit-b16-20261105')
SOURCE = ROOT / 'source'
TOOLS = ROOT / 'tools'
EVIDENCE = ROOT / 'evidence/bootstrap-P3-supplier-correction-v1'
COMMIT = '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
TREE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'
GUARD_BLOB = '967ef896907e698a07e8028e049a47e934570b1d'
GUARD_SHA = '189adc8deb54a5c53a444de491407b5c4fb3da359cac3a53942cca06adc94f77'
PLAN_SHA = '8fffcd480b6708b16e6bf98182679de5f82f5e5c4567478258aaa37f704a85d8'
records = []
commands = []
observations = []
baseline = None
env = dict(os.environ)
env.update({'RUSTUP_HOME': str(TOOLS / 'rustup-home'), 'CARGO_HOME': str(ROOT / 'cargo-home'),
            'RUSTUP_TOOLCHAIN': '1.95.0', 'GIT_TERMINAL_PROMPT': '0',
            'GCM_INTERACTIVE': 'never', 'PYTHONDONTWRITEBYTECODE': '1'})

def now():
    return datetime.now(timezone.utc).isoformat()

def bytes_id(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def file_id(path):
    path = Path(path)
    s = path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1, f'not regular independent file: {path}'
    return {'path': str(path), 'mode': oct(stat.S_IMODE(s.st_mode)), 'dev': s.st_dev,
            'inode': s.st_ino, **bytes_id(path.read_bytes())}

def capacity():
    s = os.statvfs(ROOT)
    r = {'at': now(), 'available_bytes': s.f_bavail * s.f_frsize,
         'f_bavail': s.f_bavail, 'f_frsize': s.f_frsize, 'minimum_bytes': 64000000000}
    assert r['available_bytes'] >= r['minimum_bytes'], f'capacity guard: {r}'
    return r

def save(name, data):
    if isinstance(data, str):
        data = data.encode()
    p = EVIDENCE / name
    with p.open('xb') as f:
        f.write(data)
    result = file_id(p)
    records.append(result)
    return result

def save_json(name, value):
    return save(name, json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n')

def git(argv, index=None):
    e = dict(env)
    e['GIT_OPTIONAL_LOCKS'] = '0'
    if index is not None:
        e['GIT_INDEX_FILE'] = str(index)
    result = subprocess.run(['/usr/bin/git', '-C', str(SOURCE), *argv], env=e,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=120)
    assert result.returncode == 0, f'guard git {argv}: {result.returncode}: {result.stderr.decode(errors="replace")}'
    return result.stdout

def source_guard(label):
    assert ROOT.resolve() == ROOT and SOURCE.resolve() == SOURCE
    ordinary = file_id(SOURCE / '.git/index')
    assert {k: ordinary[k] for k in ('bytes', 'sha256')} == {k: baseline['ordinary_index'][k] for k in ('bytes', 'sha256')}, 'new-host ordinary index drift'
    head = git(['rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines()
    assert head == [COMMIT, TREE], f'source HEAD drift: {head}'
    index = EVIDENCE / (label + '.index')
    git(['read-tree', TREE], index)
    git(['add', '-u', '--'], index)
    actual = git(['write-tree'], index).decode().strip()
    assert actual == TREE, f'whole source tree drift: {actual}'
    others = git(['ls-files', '--others', '--exclude-standard', '-z'], index)
    assert not others, 'untracked source input; do not remove'
    checked = []
    for old in baseline['guarded_files']:
        current = file_id(SOURCE / old['relative_path'])
        assert all(current[k] == old[k] for k in ('bytes', 'sha256', 'git_blob')), old['relative_path']
        checked.append(current)
    assert file_id(SOURCE / '.git/index')['sha256'] == ordinary['sha256']
    return save_json(label + '.guard.json', {'head': head[0], 'head_tree': head[1], 'working_tree': actual,
                     'ordinary_index': ordinary, 'guarded_files': checked, 'untracked': [], 'capacity': capacity()})

def run(label, argv, timeout=120):
    item = {'label': label, 'argv': argv, 'cwd': str(SOURCE), 'started_at': now(),
            'timeout_seconds': timeout, 'capacity_before': capacity(), 'guard_before': source_guard(label + '-before')}
    save_json(label + '.command.json', item)
    start = time.monotonic()
    timed_out = False
    try:
        r = subprocess.run(argv, cwd=SOURCE, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, check=False)
        code, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        code, out, err, timed_out = None, e.stdout or b'', e.stderr or b'', True
    item.update({'completed_at': now(), 'duration_seconds': time.monotonic() - start,
                 'exit_code': code, 'timed_out': timed_out, 'stdout': save(label + '.stdout.original', out),
                 'stderr': save(label + '.stderr.original', err), 'capacity_after': capacity(),
                 'guard_after': source_guard(label + '-after')})
    commands.append(item)
    save_json(label + '.status.json', item)
    print(json.dumps({'stage': 'P3', 'label': label, 'exit_code': code,
                      'stdout_bytes': len(out), 'stderr_bytes': len(err)}, sort_keys=True), flush=True)
    assert code == 0, f'{label}: exit {code}; preserved raw stderr'
    return out

def download(label, url, destination, expected_size=None, expected_sha=None, max_size=150000000):
    assert url.startswith('https://')
    before = capacity()
    source_before = source_guard(label + '-before')
    request = urllib.request.Request(url, headers={'User-Agent': 'hepta-audit-cold-bootstrap',
                                                  'Accept': 'application/vnd.github+json' if url.startswith('https://api.github.com/') else 'application/octet-stream'})
    meta = {'label': label, 'official_requested_url': url, 'destination': str(destination),
            'started_at': now(), 'capacity_before': before, 'guard_before': source_before}
    save_json(label + '.request.json', meta)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            redirected = urlsplit(response.geturl())
            assert redirected.scheme == 'https'
            assert redirected.hostname in {'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
                                           'objects.githubusercontent.com', 'github-releases.githubusercontent.com'}, 'unexpected official asset redirect host'
            meta.update({'http_status': response.status, 'final_host': redirected.hostname,
                         'content_length_header': response.headers.get('Content-Length')})
            total = 0
            with Path(destination).open('xb') as f:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    assert total <= max_size, 'download maximum exceeded'
                    f.write(block)
        actual = file_id(destination)
        meta['actual'] = actual
        assert expected_size is None or actual['bytes'] == expected_size, 'official asset byte length mismatch'
        assert expected_sha is None or actual['sha256'] == expected_sha, 'official asset checksum mismatch'
    except Exception as e:
        meta['error'] = {'type': type(e).__name__, 'status': getattr(e, 'code', None),
                         'message': str(e) if not isinstance(e, urllib.error.URLError) else str(getattr(e, 'reason', e))}
        raise
    finally:
        meta.update({'completed_at': now(), 'duration_seconds': time.monotonic() - start,
                     'capacity_after': capacity(), 'guard_after': source_guard(label + '-after')})
        observations.append(meta)
        save_json(label + '.status.json', meta)
    print(json.dumps({'stage': 'P3', 'label': label, 'bytes': actual['bytes'], 'sha256': actual['sha256']}, sort_keys=True), flush=True)
    return actual

def release(owner, repository, tag, label):
    path = EVIDENCE / (label + '.release.original.json')
    download(label, f'https://api.github.com/repos/{owner}/{repository}/releases/tags/{tag}', path,
             max_size=4000000)
    data = json.loads(path.read_bytes())
    assert data['tag_name'] == tag and not data['draft'], 'release/tag identity mismatch'
    assert data['html_url'] == f'https://github.com/{owner}/{repository}/releases/tag/{tag}'
    return data

def asset(release_data, name):
    matches = [a for a in release_data['assets'] if a['name'] == name]
    assert len(matches) == 1, f'official release asset missing or ambiguous: {name}'
    return matches[0]

def archive_tool(tool, data, label):
    item = asset(data, tool['candidate_asset'])
    digest = item.get('digest')
    expected_archive_sha = digest.split(':', 1)[1] if digest and digest.startswith('sha256:') else None
    archive = TOOLS / 'downloads' / item['name']
    download(label, item['browser_download_url'], archive, item['size'], expected_archive_sha)
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        assert len(members) <= 512
        for m in members:
            p = PurePosixPath(m.name)
            assert not p.is_absolute() and '..' not in p.parts and (m.isfile() or m.isdir()), 'unsafe/unexpected archive member'
        selected = [m for m in members if m.isfile() and PurePosixPath(m.name).name == tool['name']]
        assert len(selected) == 1, 'allowlisted tool member not unique'
        assert selected[0].size < 150000000
        data_bytes = tar.extractfile(selected[0]).read()
        member_id = bytes_id(data_bytes)
        assert member_id['sha256'] == tool['expected_installed_sha256_from_frozen_tool_contract'], 'installed tool supply pin mismatch'
        installed = TOOLS / 'bin' / tool['name']
        with installed.open('xb') as f:
            f.write(data_bytes)
        installed.chmod(0o700)
        save_json(label + '.archive-selection.json', {'archive': file_id(archive),
                  'members': [{'name': m.name, 'bytes': m.size, 'type': m.type.decode('ascii', errors='replace')} for m in members],
                  'selected': selected[0].name, 'installed': file_id(installed), 'official_asset_id': item['id']})
    return installed

import gzip
import tomllib

raw = sys.stdin.buffer.read()
request = json.loads(raw)
terminal = {'schema': 'hepta-ai395-cold-bootstrap-P3-official-origin-correction-v1',
            'host': 'ai395', 'stage': 'P3', 'root_guard': GUARD_BLOB,
            'started_at': now(), 'request': bytes_id(raw), 'build_or_test_execution': False,
            'source_mutation': False, 'original_failure_preserved': True, 'errors': []}
created = False
success = False
try:
    assert request['stage'] == 'P3-supplier-correction'
    assert request['root_execution_guard_blob'] == GUARD_BLOB
    assert hashlib.sha256(request['root_execution_guard_text'].encode()).hexdigest() == GUARD_SHA
    assert hashlib.sha256(request['approved_plan_text'].encode()).hexdigest() == PLAN_SHA
    assert json.loads(request['root_execution_guard_text'])['execute']
    assert request['root_official_origin_correction_authorized'] is True
    assert os.getuid() == 1000 and ROOT.resolve() == ROOT and SOURCE.resolve() == SOURCE
    assert not os.path.lexists(EVIDENCE)
    for name in ['RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GIT_INDEX_FILE']:
        assert not os.environ.get(name), f'unexpected injection environment name: {name}'
    capacity()
    prior_source = (ROOT / 'evidence/bootstrap-P1-v1/source-baseline.json').read_bytes()
    assert bytes_id(prior_source) == request['P1_source_baseline_identity']
    baseline = json.loads(prior_source)
    p2_path = ROOT / 'evidence/bootstrap-P2-version-continuation-v1/terminal.json'
    p2_data = p2_path.read_bytes()
    assert bytes_id(p2_data) == request['P2_success_terminal_identity']
    assert json.loads(p2_data)['success'] and json.loads(p2_data)['ready_for_P3']
    tool_path = ROOT / 'evidence/bootstrap-P2-version-continuation-v1/installed-tools.json'
    tool_data = tool_path.read_bytes()
    assert bytes_id(tool_data) == request['installed_tools_identity']
    tools_doc = json.loads(tool_data)
    for old in tools_doc['tools']:
        actual = file_id(old['path'])
        assert all(actual[key] == old[key] for key in ['bytes', 'sha256', 'git_blob']), old['name']
    failed_path = ROOT / 'evidence/bootstrap-P3-v1/terminal.json'
    failed_bytes = failed_path.read_bytes()
    assert bytes_id(failed_bytes) == request['failed_P3_terminal_identity']
    failed = json.loads(failed_bytes)
    assert not failed['success'] and not failed['commands'] and len(failed['downloads']) == 1
    assert 'official release asset missing or ambiguous' in failed['errors'][0]['message']
    for record in failed['records']:
        actual = file_id(record['path'])
        assert all(actual[key] == record[key] for key in ['bytes', 'sha256', 'git_blob'])
    action_path = SOURCE / '.github/actions/setup-rusty-v8/action.yml'
    action = file_id(action_path)
    assert action['git_blob'] == '449ab653fd10c07a8a2453b6efe095205157a8ee'
    assert action_path.read_text() == request['current_source_action_text']
    old_receipt = request['original_ROG_supply_receipt_text'].encode()
    assert bytes_id(old_receipt)['sha256'] == '9929de3e38709fe80e3c1f3c3961ad6e9206439ed80a3226db0b2102bba756b9'
    EVIDENCE.mkdir(mode=0o700)
    created = True
    save('request.original.json', raw)
    save('original-ROG-supply-receipt.json', old_receipt)
    save('current-source-action.original.yml', action_path.read_bytes())
    save('prior-failed-terminal.original.json', failed_bytes)
    terminal['initial_guard'] = source_guard('initial')
    terminal['installed_tools_receipt'] = file_id(tool_path)
    lock = tomllib.loads((SOURCE / 'codex-rs/Cargo.lock').read_text())
    v8 = [value for value in lock['package'] if value['name'] == 'v8']
    assert len(v8) == 1 and v8[0]['version'] == '150.4.0'
    save_json('locked-v8-package.json', {'source_tree': TREE, 'lock': file_id(SOURCE / 'codex-rs/Cargo.lock'),
                                       'package': v8[0], 'action': action})
    folder = TOOLS / 'rusty-v8'
    for owned_directory in [folder, TOOLS / 'dotslash-cache']:
        info = owned_directory.lstat()
        assert stat.S_ISDIR(info.st_mode) and owned_directory.resolve() == owned_directory
        assert not list(owned_directory.iterdir()), 'prior failed stage directory no longer empty; do not overwrite'
    released = release('openai', 'codex', 'rusty-v8-v150.4.0', '01-codex-built-v8-release')
    base_url = 'https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0/'
    pins = {
        'librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz':
            (29366352, 'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583'),
        'src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs':
            (39884, '7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506'),
    }
    checksum_name = 'rusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.sha256'
    checksum_asset = asset(released, checksum_name)
    assert checksum_asset['browser_download_url'] == base_url + checksum_name
    assert checksum_asset['size'] == 262
    checksum_path = folder / checksum_name
    checksum = download('02-official-checksums', checksum_asset['browser_download_url'], checksum_path,
                        262, '6774b42c9424c098c72a805c08d4e94be17c591cf02b1dc2633060255a8a61be')
    lines = checksum_path.read_text().replace('\r', '').splitlines()
    assert len(lines) == 2
    parsed = {}
    for line in lines:
        digest, name = line.split()
        assert name not in parsed
        parsed[name] = digest
    assert parsed == {name: pin[1] for name, pin in pins.items()}, 'official manifest does not equal original variant supply pins'
    assets = []
    for number, (name, (expected_size, expected_sha)) in enumerate(pins.items(), 3):
        item = asset(released, name)
        assert item['browser_download_url'] == base_url + name and item['size'] == expected_size
        official_digest = item.get('digest')
        assert official_digest in (None, 'sha256:' + expected_sha), 'GitHub official metadata digest differs'
        actual = download(f'{number:02d}-v8-asset', item['browser_download_url'], folder / name,
                          expected_size, expected_sha, max_size=1200000000)
        assets.append({'official_asset_id': item['id'], 'name': name,
                       'official_digest': official_digest, 'checksum_manifest': checksum,
                       'observed': actual})
    names = list(pins)
    archive = folder / names[0]
    before = capacity()
    count = 0
    digest = hashlib.sha256()
    header = b''
    with gzip.open(archive, 'rb') as stream:
        while block := stream.read(1024 * 1024):
            if not header:
                header = block[:8]
            count += len(block)
            assert count <= 5000000000
            digest.update(block)
    assert header == b'!<arch>\n'
    binding = folder / names[1]
    binding.read_text(encoding='utf-8')
    receipt = {'schema': 'hepta-ai395-official-v8-prerequisite-v2', 'host': 'ai395', 'source_tree': TREE,
               'locked_v8': v8[0], 'source_action': action, 'release_owner': 'openai/codex',
               'release_tag': released['tag_name'], 'release_id': released['id'],
               'assets': assets, 'official_checksums': checksum, 'gzip_crc_read_complete': True,
               'archive_uncompressed_bytes': count, 'archive_uncompressed_sha256': digest.hexdigest(),
               'decompression_capacity_before': before, 'decompression_capacity_after': capacity(),
               'environment': {'RUSTY_V8_ARCHIVE': str(archive), 'RUSTY_V8_SRC_BINDING_PATH': str(binding),
                               'DOTSLASH_CACHE': str(TOOLS / 'dotslash-cache')},
               'build_or_test_execution': False, 'test_qualification': False,
               'prior_wrong_origin_failure': file_id(failed_path),
               'origin_correction_authorized_by_root': True,
               'variant_unchanged': 'ptrcomp_sandbox_release_x86_64-unknown-linux-gnu'}
    terminal['artifact_receipt'] = save_json('v8-prerequisites.json', receipt)
    terminal['final_guard'] = source_guard('final')
    terminal['capacity_final'] = capacity()
    success = True
except Exception as error:
    terminal['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
finally:
    terminal.update({'success': success, 'ready_for_P4': success, 'completed_at': now(),
                     'commands': commands, 'downloads': observations, 'records': list(records)})
    if created:
        result = save_json('terminal.json', terminal)
        print(json.dumps({'stage': 'P3', 'success': success, 'ready_for_P4': success,
                          'terminal': result, 'errors': terminal['errors']}, sort_keys=True), flush=True)
    else:
        print(json.dumps(terminal, sort_keys=True), flush=True)
sys.exit(0 if success else 1)
