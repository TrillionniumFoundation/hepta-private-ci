"""One explicitly approved orphan-data-ref push. Never run from an unfrozen plan.

Raw Git streams and URLs remain in memory. The transport index, archive hashes,
planned commit, exit classifications and exact-ref observations are durable.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
if sys.flags.optimize:
    raise RuntimeError('Optimization cannot disable transport integrity assertions')
SOURCE = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/source-h3')
REPOSITORY = 'TrillionniumFoundation/hepta-private-ci'
REF = 'refs/heads/evidence/actual-elf-transport-20261105-93bfc-01'
COMMIT = '6db78eca53a5acdda0d96873d3f4cd65863426f0'
TREE = 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
ROOT = Path('/home/qian-qi/work/hepta-actual-elf-git-transport-20261105-93bfc-01')
MAX_RAW = 670306272
MAX_TEXT = 893742124
MAX_PART = 4194304
MAX_PARTS = 162
GUARD_SHA = 'e55f5ca1200b2c9fc5af4158c42f460e71f3815166a962a5b892acfe9477b1d1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def read_source(path, expected_bytes=None, expected_sha=None, keep=True, limit=None):
    assert path.is_absolute() and path.parent.resolve() == path.parent
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
        assert limit is None or before.st_size <= limit
        if expected_bytes is not None:
            assert before.st_size == expected_bytes
        chunks = []
        total = 0
        sha = hashlib.sha256()
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            sha.update(block)
            if keep:
                chunks.append(block)
        after = os.fstat(stream.fileno())
    assert identity(before) == identity(after) and total == before.st_size
    assert expected_sha is None or sha.hexdigest() == expected_sha
    return (b''.join(chunks) if keep else None,
            {'bytes': total, 'sha256': sha.hexdigest(), 'file_identity': list(identity(before))})


def origin_matches(value):
    if any(char in value for char in ('\r', '\n', '\0')):
        return False
    if '://' in value:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and parsed.hostname == 'github.com'
                and parsed.password is None and parsed.username is None
                and parsed.port in (None, 443)
                and not parsed.query and not parsed.fragment
                and parsed.path.lstrip('/').removesuffix('.git') == REPOSITORY)
    return False


def safe_error(stderr):
    value = stderr.lower()
    if any(token in value for token in (b'authentication failed', b'permission denied', b'403', b'401', b'could not read username')):
        return 'existing_identity_or_write_access_denied'
    if any(token in value for token in (b'stale info', b'already exists', b'rejected')):
        return 'ref_lease_or_remote_rejection'
    if any(token in value for token in (b'timed out', b'failed to connect', b'could not resolve', b'connection')):
        return 'network_or_transport_error'
    return 'unclassified_git_error_raw_withheld'


class Transport:
    def __init__(self, plan):
        self.plan = plan
        self.started = time.monotonic()
        self.deadline = self.started + 1200
        self.base_env = dict(os.environ)
        for key in tuple(self.base_env):
            if key.startswith('GIT_TRACE') or key == 'GIT_CURL_VERBOSE':
                self.base_env.pop(key)
        for key in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_INDEX_FILE'):
            assert not self.base_env.get(key), 'unexpected inherited repository redirection'
        self.base_env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0',
                             GIT_ASKPASS='/bin/false', SSH_ASKPASS='/bin/false',
                             GCM_INTERACTIVE='Never', PYTHONDONTWRITEBYTECODE='1',
                             GIT_NO_LAZY_FETCH='1')
        self.report = {'schema': 'actual-archive-orphan-git-transport-v1',
                       'repository': REPOSITORY, 'ref': REF, 'push_attempts': 0,
                       'status': 'PREPARING_UNPUBLISHED', 'operations': [],
                       'full_cloud_byte_readback': False, 'source_or_native_qualification': False,
                       'raw_origin_or_credentials_logged_or_saved': False,
                       'native_reexecution': False, 'existing_refs_mutated': False,
                       'automatic_retry': False}
        self.repo = ROOT / 'repository.git'
        self.env = dict(self.base_env)
        self.git_prefix = ['git', '--git-dir=' + str(self.repo)]

    def persist(self, name, obj):
        path = ROOT / name
        raw = (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def command(self, name, arguments, timeout, data=None, env=None, allowed=(0,)):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('transport total deadline')
        started = time.monotonic()
        process = subprocess.Popen(arguments, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env or self.env, start_new_session=True)
        timed_out = False
        try:
            out, err = process.communicate(data, timeout=min(timeout, remaining))
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = process.communicate(timeout=10)
        record = {'operation': name, 'seconds': time.monotonic() - started,
                  'returncode': process.returncode, 'timed_out': timed_out,
                  'stdout_bytes': len(out), 'stderr_bytes': len(err),
                  'classification': None if process.returncode == 0 else safe_error(err)}
        self.report['operations'].append(record)
        if timed_out or process.returncode not in allowed:
            raise RuntimeError(name + ': ' + ('timeout' if timed_out else record['classification']))
        return out

    def local_source_git(self, arguments, allowed=(0,)):
        return self.command('source-git-readonly', ['git', '-C', str(SOURCE), *arguments], 10,
                            env=self.base_env, allowed=allowed)

    def config_hashes(self):
        values = {}
        for path, expected in self.plan['protected_configurations'].items():
            raw, record = read_source(Path(path), expected_sha=expected, limit=1024 * 1024)
            values[path] = record['sha256']
        return values

    def source_guard(self):
        path = SOURCE / 'scripts/hepta_ci_exec.py'
        raw, _ = read_source(path, expected_sha=GUARD_SHA, limit=1024 * 1024)
        sys.path.insert(0, str(path.parent))
        try:
            spec = importlib.util.spec_from_file_location('transport_existing_ci_guard', path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            exec(compile(raw, str(path), 'exec'), module.__dict__)
            observed = module.identity(repository=SOURCE)
        finally:
            sys.path.pop(0)
            sys.modules.pop('transport_existing_ci_guard', None)
        assert observed['commit'] == COMMIT and observed['tree'] == TREE and not observed['dirty']
        return observed

    def configure_existing_auth(self):
        origin = self.local_source_git(['remote', 'get-url', 'origin']).decode().strip()
        push_origin = self.local_source_git(['remote', 'get-url', '--push', 'origin']).decode().strip()
        assert origin_matches(origin) and origin == push_origin, 'unvalidated existing origin route'
        self.env['HEPTA_TRANSPORT_ORIGIN'] = origin
        self.env['HEPTA_TRANSPORT_ORIGINAL_GIT_CONFIG_ENV'] = json.dumps({k: v for k, v in self.base_env.items() if k.startswith('GIT_CONFIG_')})
        self.git_prefix += ['--config-env=remote.transport.url=HEPTA_TRANSPORT_ORIGIN']
        if origin.startswith('https://'):
            raw = self.local_source_git(['config', '--null', '--get-urlmatch', 'http', origin], allowed=(0, 1))
            count = int(self.env.get('GIT_CONFIG_COUNT', '0'))
            for entry in raw.split(b'\0'):
                if not entry:
                    continue
                key, value = entry.split(b'\n', 1)
                key = key.decode('utf-8').lower()
                assert key.startswith('http.') and not any(c in key for c in '\r\n\0')
                if key in ('http.cookiefile', 'http.savecookies'):
                    raise ValueError('cookie-writing or cookie-file route not authorized')
                self.env['GIT_CONFIG_KEY_' + str(count)] = key
                self.env['GIT_CONFIG_VALUE_' + str(count)] = value.decode('utf-8')
                count += 1
            self.env['GIT_CONFIG_COUNT'] = str(count)
            bridge = ROOT / 'credential_get_only.py'
            self.git_prefix += ['-c', 'credential.helper=', '-c',
                                'credential.helper=!' + shlex.join([sys.executable, str(bridge)]),
                                '-c', 'credential.useHttpPath=true',
                                '-c', 'http.followRedirects=false', '-c', 'http.saveCookies=false']
            self.report['auth_route'] = 'existing-source HTTPS settings in process memory; get-only credential bridge'
            # Some existing routes authenticate through an HTTP header. Do not
            # demand a credential-helper response when that route already exists.
            has_auth_header = any(entry.split(b'\n', 1)[0].lower() == b'http.extraheader'
                                  and entry.split(b'\n', 1)[1].strip().lower().startswith(b'authorization:')
                                  for entry in raw.split(b'\0') if b'\n' in entry)
            if has_auth_header:
                self.report['credential_preflight'] = 'existing_authorization_header_present_not_logged'
            else:
                response = self.command('existing-get-only-credential-preflight',
                    [sys.executable, str(bridge), 'get'], 20,
                    data=('protocol=https\nhost=github.com\npath=' + REPOSITORY + '.git\n\n').encode())
                pairs = [line.split(b'=', 1) for line in response.splitlines() if line]
                assert len(pairs) == 2 and {row[0] for row in pairs} == {b'username', b'password'}
                assert all(len(row) == 2 and row[1] for row in pairs)
                self.report['credential_preflight'] = 'existing_helper_returned_credential_in_memory_only_not_write_authorization'
                del pairs, response
        # Re-resolve in the isolated repository as well, catching inherited URL
        # rewrites and alternate push routing without printing their contents.
        for args in (['remote', 'get-url', 'transport'], ['remote', 'get-url', '--push', 'transport']):
            observed = self.command('validate-isolated-origin-route', self.git_prefix + args, 10).decode().strip()
            assert observed == origin and origin_matches(observed)

    def require_no_unreviewed_hooks(self):
        raw = self.command('inspect-effective-hook-configuration',
            self.git_prefix + ['config', '--get', 'core.hooksPath'], 10, allowed=(0, 1))
        assert raw == b'', 'inherited hooks configuration requires separate review; never overridden'
        hook_dir = self.repo / 'hooks'
        assert not hook_dir.is_symlink(), 'unexpected hook-directory link'
        existing = [] if not hook_dir.exists() else [entry for entry in hook_dir.iterdir()
                                                     if not entry.name.endswith('.sample')]
        assert not existing, 'existing local hooks require review; never disabled'
        self.report['hooks'] = 'no_effective_hooks_path_and_no_existing_local_hooks_no_override'

    def private_config_identity(self):
        path = self.repo / 'config'
        raw, record = read_source(path, limit=65536)
        # This file is generated by plain git init only. The exact-byte before/
        # after comparison detects any persistence of later command/env settings.
        assert b'[remote ' not in raw and b'[credential' not in raw and b'[http' not in raw
        return record['sha256']

    def remote_head(self, name):
        raw = self.command(name, self.git_prefix + ['ls-remote', '--heads', 'transport', REF], 60)
        if not raw:
            return None
        match = re.fullmatch(rb'([0-9a-f]{40})\t' + re.escape(REF.encode()) + rb'\n', raw)
        assert match is not None, 'unexpected exact-ref readback'
        return match.group(1).decode('ascii')

    def store_blob(self, data):
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        returned = self.command('write-private-bare-object', self.git_prefix + ['hash-object', '-w', '--stdin'], 30, data=data).decode().strip()
        assert returned == actual
        return actual

    def run(self):
        p = self.plan
        assert p['frozen'] and p['publication_authorized']
        assert p['repository'] == REPOSITORY and p['destination_ref'] == REF
        assert p['expected_ref_before'] is None and p['route'] == 'canonical-base64-no-newline-per-original-part'
        assert p['repository_visibility']['repository_id'] == '1320694176'
        assert p['repository_visibility']['required'] == 'public'
        assert p['repository_visibility']['observed'] == 'public', 'fixed public archival destination not verified'
        assert p['limits'] == {'outer_seconds': 1200, 'push_seconds': 900, 'ls_remote_seconds': 60,
                               'max_parts': MAX_PARTS, 'max_part_raw_bytes': MAX_PART,
                               'total_raw_bytes': MAX_RAW, 'total_envelope_bytes': MAX_TEXT}
        ROOT.mkdir(mode=0o700, exist_ok=False)
        bridge = Path(__file__).with_name('credential_get_only.py').read_bytes()
        assert digest(bridge) == p['credential_bridge_sha256']
        with (ROOT / 'credential_get_only.py').open('xb') as stream:
            stream.write(bridge)
        self.report['configurations_before'] = self.config_hashes()
        self.report['source_before'] = self.source_guard()
        self.command('init-new-isolated-bare', ['git', 'init', '--bare', '--template=', str(self.repo)], 30, env=self.base_env)
        self.report['isolated_config_before_sha256'] = self.private_config_identity()
        self.require_no_unreviewed_hooks()
        self.configure_existing_auth()
        self.require_no_unreviewed_hooks()
        assert self.remote_head('exact-ref-must-be-absent') is None, 'dedicated transport ref already exists'
        self.report['remote_ref_before'] = None
        index = {'schema': 'actual-archive-base64-git-transport-index-v1',
                 'repository': REPOSITORY, 'destination_ref': REF, 'orphan_data_only': True,
                 'source_or_native_qualification': False,
                 'route_plan_sha256': self.report['plan_sha256'],
                 'route': p['route'], 'archives': [], 'envelopes': []}
        blobs = {}
        raw_total = text_total = 0
        for archive in p['archives']:
            phase = archive['phase']
            root = Path(archive['source_root'])
            assert phase in ('H1', 'H2', 'H3')
            assert root == Path('/home/qian-qi/work/hepta-' + phase.lower() + '-actual-elf-export-20261105-93bfc-01')
            assert Path(archive['completion_path']) == root / 'completion.json'
            assert Path(archive['part_root']) == root
            completion, _ = read_source(Path(archive['completion_path']),
                                        expected_bytes=archive['completion_bytes'],
                                        expected_sha=archive['completion_sha256'], limit=65536)
            actual = json.loads(completion)
            assert actual['status'] == 'COMPLETE' and actual['parts'] == archive['parts']
            assert actual['archive_bytes'] == archive['archive_bytes'] and actual['archive_sha256'] == archive['archive_sha256']
            assert actual['actual_parts_concatenation_verified'] and actual['all_archive_members_independently_decompressed_and_hashed']
            archive_path = Path(actual['archive_path'])
            assert archive_path.parent == root and str(archive_path) == archive['archive_path']
            assert actual['archive_index_sha256'] == archive['archive_index_sha256']
            _, archive_observation = read_source(archive_path, expected_bytes=archive['archive_bytes'],
                                                expected_sha=archive['archive_sha256'], keep=False)
            completion_path = 'archives/' + phase + '/' + phase + '-export-completion.json'
            blobs[completion_path] = self.store_blob(completion)
            combined = hashlib.sha256()
            offset = 0
            for expected_index, part in enumerate(archive['parts']):
                assert part['index'] == expected_index and part['offset'] == offset
                assert Path(part['name']).name == part['name'] and 0 < part['bytes'] <= MAX_PART
                raw, observation = read_source(Path(archive['part_root']) / part['name'], expected_bytes=part['bytes'],
                                               expected_sha=part['sha256'], limit=MAX_PART)
                combined.update(raw)
                offset += len(raw)
                raw_total += len(raw)
                text = base64.b64encode(raw)
                assert base64.b64decode(text, validate=True) == raw and b'\n' not in text
                text_total += len(text)
                path = 'archives/' + phase + '/parts/' + part['name'] + '.b64'
                blob = self.store_blob(text)
                assert path not in blobs
                blobs[path] = blob
                index['envelopes'].append({'phase': phase, 'original_part': part,
                                          'transport_path': path, 'transport_bytes': len(text),
                                          'transport_sha256': digest(text), 'transport_git_blob': blob,
                                          'source_read_observation': observation})
            assert offset == archive['archive_bytes'] and combined.hexdigest() == archive['archive_sha256']
            index['archives'].append({'phase': phase, 'completion_path': completion_path,
                                      'completion_bytes': len(completion), 'completion_sha256': digest(completion),
                                      'archive_bytes': offset, 'archive_sha256': combined.hexdigest(),
                                      'archive_read_observation': archive_observation,
                                      'original_native_outcome': actual['original_run_outcome'],
                                      'capture_limits': actual['capture_limits'],
                                      'archive_index_sha256': actual['archive_index_sha256']})
        assert len(index['envelopes']) == MAX_PARTS and raw_total == MAX_RAW and text_total == MAX_TEXT
        raw_index = (json.dumps(index, sort_keys=True, indent=2) + '\n').encode()
        assert len(raw_index) < 1024 * 1024
        blobs['transport-index.json'] = self.store_blob(raw_index)
        self.command('initialize-private-index', self.git_prefix + ['read-tree', '--empty'], 10)
        records = b''.join(('100644 ' + oid + '\t' + path).encode() + b'\0' for path, oid in sorted(blobs.items()))
        self.command('write-private-index', self.git_prefix + ['update-index', '-z', '--index-info'], 30, data=records)
        tree = self.command('write-data-only-tree', self.git_prefix + ['write-tree'], 30).decode().strip()
        listing = self.command('compare-exact-data-only-tree', self.git_prefix + ['ls-tree', '-r', '-z', tree], 30)
        expected = b''.join(('100644 blob ' + oid + '\t' + path).encode() + b'\0' for path, oid in sorted(blobs.items()))
        assert listing == expected and len(blobs) == MAX_PARTS + 4
        assert sorted(blobs) == p['expected_transport_paths']
        assert all(path == 'transport-index.json' or path.startswith(('archives/H1/', 'archives/H2/', 'archives/H3/')) for path in blobs)
        commit_env = dict(self.env, GIT_AUTHOR_NAME='Hepta Evidence Transport',
                          GIT_AUTHOR_EMAIL='evidence-transport@users.noreply.github.com',
                          GIT_COMMITTER_NAME='Hepta Evidence Transport',
                          GIT_COMMITTER_EMAIL='evidence-transport@users.noreply.github.com',
                          GIT_AUTHOR_DATE=p['commit_date'], GIT_COMMITTER_DATE=p['commit_date'])
        commit = self.command('write-orphan-data-commit', self.git_prefix + ['commit-tree', tree], 30,
                              data=b'Preserve exact completed H1 H2 H3 archive bytes only.\n', env=commit_env).decode().strip()
        commit_body = self.command('verify-orphan-commit', self.git_prefix + ['cat-file', '-p', commit], 10)
        assert commit_body.startswith(('tree ' + tree + '\n').encode()) and not re.search(rb'^parent ', commit_body, re.M)
        assert self.config_hashes() == self.report['configurations_before']
        assert self.source_guard() == self.report['source_before']
        self.persist('transport-index.json', index)
        self.persist('prepared-data-commit.json', {'commit': commit, 'tree': tree, 'parents': [],
                                                  'ref': REF, 'expected_old': None,
                                                  'paths': blobs, 'raw_bytes': raw_total, 'envelope_bytes': text_total,
                                                  'index_sha256': digest(raw_index)})
        self.report.update(planned_commit=commit, planned_tree=tree, transport_blob_count=len(blobs),
                           total_raw_bytes=raw_total, total_envelope_bytes=text_total)
        print(json.dumps({'phase': 'prepared-orphan-data-commit', 'commit': commit, 'tree': tree, 'ref': REF}), flush=True)
        self.persist('push-intent.json', {'schema': 'single-empty-lease-push-intent-v1',
            'commit': commit, 'tree': tree, 'ref': REF, 'expected_old': None,
            'plan_sha256': self.report['plan_sha256'],
            'attempt': 1, 'automatic_retry': False,
            'crash_or_uncertain_outcome': 'Read this exact ref and compare this commit; never repeat push automatically.'})
        self.report['push_attempts'] = 1
        try:
            self.command('single-empty-lease-push', self.git_prefix + ['push', '--porcelain',
                         '--force-with-lease=' + REF + ':', 'transport', commit + ':' + REF], 900)
            self.report['push_command_succeeded'] = True
        except Exception as error:
            self.report['push_command_succeeded'] = False
            self.report['push_error_type'] = type(error).__name__
        try:
            remote = self.remote_head('single-exact-ref-readback')
            self.report['remote_ref_after'] = remote
            self.report['status'] = 'REF_PUBLISHED_CLOUD_BYTE_READBACK_PENDING' if remote == commit else 'PUSH_NOT_CONFIRMED'
        except Exception as error:
            self.report['status'] = 'PUSH_OUTCOME_UNKNOWN_NO_RETRY'
            self.report['readback_error_type'] = type(error).__name__
        return self.report['status'] == 'REF_PUBLISHED_CLOUD_BYTE_READBACK_PENDING'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    parser.add_argument('--expected-script-sha256', required=True)
    args = parser.parse_args()
    plan_raw = args.plan.read_bytes()
    assert re.fullmatch('[0-9a-f]{64}', args.expected_plan_sha256)
    assert re.fullmatch('[0-9a-f]{64}', args.expected_script_sha256)
    assert digest(plan_raw) == args.expected_plan_sha256
    assert digest(Path(__file__).read_bytes()) == args.expected_script_sha256
    plan = json.loads(plan_raw)
    assert plan['script_sha256'] == args.expected_script_sha256
    # A blocked/unreviewed plan cannot even create the private repository.
    assert plan['frozen'] and plan['publication_authorized']
    assert plan['repository_visibility']['repository_id'] == '1320694176'
    assert plan['repository_visibility']['observed'] == plan['repository_visibility']['required'] == 'public'
    transport = Transport(plan)
    transport.report['plan_sha256'] = digest(plan_raw)
    transport.report['script_sha256'] = args.expected_script_sha256
    passed = False
    try:
        passed = transport.run()
    except Exception as error:
        transport.report['status'] = 'FAILED_NO_AUTOMATIC_RETRY'
        transport.report['exception_type'] = type(error).__name__
    finally:
        try:
            transport.report['configurations_after'] = transport.config_hashes()
            transport.report['source_after'] = transport.source_guard()
            transport.report['protected_unchanged'] = (
                transport.report.get('configurations_before') == transport.report['configurations_after']
                and transport.report.get('source_before') == transport.report['source_after'])
            if transport.repo.exists():
                transport.report['isolated_config_after_sha256'] = transport.private_config_identity()
                assert (transport.report.get('isolated_config_before_sha256')
                        == transport.report['isolated_config_after_sha256'])
            if not transport.report['protected_unchanged']:
                passed = False
                transport.report['integrity_after_failed'] = True
        except Exception as error:
            passed = False
            transport.report['postcheck_error_type'] = type(error).__name__
        transport.report['elapsed_seconds'] = time.monotonic() - transport.started
        transport.report['plan_sha256'] = digest(plan_raw)
        if ROOT.exists():
            transport.persist('transport-terminal.json', transport.report)
        print(json.dumps(transport.report, sort_keys=True, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
