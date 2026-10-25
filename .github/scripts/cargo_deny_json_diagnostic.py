"""One new source-bound diagnostic; never a substitute for required CI."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
from cargo_deny_json_support import JSONObservations, lock_allowlist, default_db_config, revision_receipt
from urllib.parse import urlsplit

SOURCE = '2e259b959339f1709370772c380145834e6bc0b7'
TREE = '010629adca9f5a6f5a2a93842f4d701d9e7d10a4'
ACTION = '82eb9f621fbc699dd0918f3ea06864c14cc84246'  # immutable annotated tag object
ACTION_COMMIT = '3fd3802e88374d3fe9159b834c7714ec57d6c979'
ACTION_TREE = 'f2b8fc397f80f6a28f5b5826d01feacb3512c4f3'
BASE = 'rust:1.85.0-alpine3.20@sha256:f0cef6c65992995b1c7816cb667de95799852e3fbed9d06f95855cbc512a0fd0'
BLOBS = {'Dockerfile': '94f38ebce29aa536404c614879576defbb272c15',
         'entrypoint.sh': 'ba9fa82bb74e75bbf14ab3aa1852e2c601d5234e',
         'action.yml': 'fc4dd3b2553105b018e08d987b06a85a31fc2bf7'}
ORIGINAL_ARGS = ['1.95.0', '', '', '', 'false', '--log-level', 'warn',
        '--manifest-path', './codex-rs/Cargo.toml', '--all-features', 'check', '']
ARGS = ORIGINAL_ARGS.copy()
ARGS[9] = '--all-features --format json'  # NEW command, not original reproduction.
CAP = 2 * 1024 * 1024
HOSTS = {'github.com', 'crates.io', 'index.crates.io', 'static.crates.io',
         'static.rust-lang.org', 'doc.rust-lang.org', 'docs.rs',
         'rustsec.org', 'spdx.org', 'opensource.org', 'creativecommons.org',
         'embarkstudios.github.io', 'www.mozilla.org', 'en.wikipedia.org',
         'www.apache.org', 'www.unicode.org', 'zlib.net', 'cdla.dev',
         'openjdk.org', 'www.boost.org', 'unlicense.org', 'www.openssl.org'}
SECRET = re.compile(rb'(?i)(-----BEGIN[^\r\n]*PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{8}|github_pat_|AKIA[A-Z0-9]{12}|(?:password|token|authorization|credential)\s*[=:]\s*[\"\x27]?[A-Za-z0-9_+/.-]{8})')
URL = re.compile(rb'(?:https?|ssh|git)://[^\s<>\"\x27]+')
ANSI = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')


def suspicious(data):
    data = ANSI.sub(b'', data)
    if SECRET.search(data) or re.search(rb'(?i)authorization\s*[:=]\s*(?:basic|bearer)\s+', data):
        return True
    for raw in URL.findall(data):
        try:
            url = urlsplit(raw.decode('utf-8'))
            if url.username or url.password or url.query or url.hostname not in HOSTS:
                return True
        except (ValueError, UnicodeError):
            return True
    return False


# Declared cargo-deny 0.19.0 docs/registry intersection, NOT binary attestation.
# Registry Git blob: 1714ff8644dda1e8b3381c5bbdaf74d3f86463de.
DIAGNOSTIC_CODES = ('accepted', 'advisory-ignored', 'advisory-not-detected', 'allowed', 'allowed-by-organization', 'allowed-by-wrapper', 'allowed-source', 'banned', 'build-script-not-allowed', 'checksum-match', 'checksum-mismatch', 'default-feature-enabled', 'denied-by-extension', 'detected-executable', 'detected-executable-script', 'duplicate', 'empty-license-field', 'exact-features-mismatch', 'feature-banned', 'feature-not-explicitly-allowed', 'features-enabled', 'gather-failure', 'git-source-underspecified', 'index-cache-load-failure', 'index-failure', 'license-exception-not-encountered', 'license-not-encountered', 'missing-clarification-file', 'no-license-field', 'non-root-path', 'not-allowed', 'notice', 'parse-error', 'path-bypassed', 'path-bypassed-by-glob', 'rejected', 'skipped', 'skipped-by-root', 'skipped-private-workspace-crate', 'source-not-allowed', 'unable-to-check-path', 'unknown-advisory', 'unknown-feature', 'unlicensed', 'unmaintained', 'unmatched-bypass', 'unmatched-glob', 'unmatched-organization', 'unmatched-path-bypass', 'unmatched-skip', 'unmatched-skip-root', 'unmatched-source', 'unmatched-wrapper', 'unnecessary-skip', 'unresolved-workspace-dependency', 'unsound', 'unused-workspace-dependency', 'unused-wrapper', 'vulnerability', 'wildcard', 'workspace-duplicate', 'yanked', 'yanked-ignored', 'yanked-not-detected')
SEVERITIES = ('error', 'warning', 'note')
SGR = re.compile(rb'\x1b\[(?:[0-9]{1,3}(?:;[0-9]{0,3}){0,15})?m')
HEADER = re.compile(rb'^(error|warning|note)\[([^\]\r\n]*)\]:')


class DiagnosticCounts:
    """Bounded lexical observations only; never preserve arbitrary text."""
    LIMIT = 2**32 - 1
    LINE_LIMIT = 65536

    def __init__(self):
        self.counts = {severity: {code: 0 for code in DIAGNOSTIC_CODES}
                       for severity in SEVERITIES}
        self.unknown_code_headers = 0
        self.overlong_lines_skipped = 0
        self.invalid_ansi_lines_skipped = 0
        self.saturated = False
        self.pending = b''
        self.dropping_line = False

    def increment(self, mapping, key):
        if mapping[key] < self.LIMIT:
            mapping[key] += 1
        else:
            self.saturated = True

    def increment_field(self, field):
        value = getattr(self, field)
        if value < self.LIMIT:
            setattr(self, field, value + 1)
        else:
            self.saturated = True

    def line(self):
        if self.dropping_line:
            self.increment_field('overlong_lines_skipped')
        else:
            clean = SGR.sub(b'', self.pending)
            if b'\x1b' in clean:
                self.increment_field('invalid_ansi_lines_skipped')
            else:
                match = HEADER.match(clean)
                if match:
                    severity = match[1].decode('ascii')
                    # Decode no arbitrary bytes, and never emit unknown strings.
                    code = next((value for value in DIAGNOSTIC_CODES
                                 if value.encode('ascii') == match[2]), None)
                    if code is None:
                        self.increment_field('unknown_code_headers')
                    else:
                        self.increment(self.counts[severity], code)
        self.pending = b''
        self.dropping_line = False

    def feed(self, data):
        pieces = data.split(b'\n')
        for index, piece in enumerate(pieces):
            if not self.dropping_line:
                if len(self.pending) + len(piece) > self.LINE_LIMIT:
                    self.pending = b''
                    self.dropping_line = True
                else:
                    self.pending += piece
            if index < len(pieces) - 1:
                self.line()

    def finish(self):
        if self.pending or self.dropping_line:
            self.line()

    def receipt(self, complete):
        return {'schema': 'lexical_diagnostic_header_observations_v1',
                'declared_code_version': '0.19.0', 'binary_version_verified': False,
                'counts': self.counts,
                'unknown_code_headers': self.unknown_code_headers,
                'overlong_lines_skipped': self.overlong_lines_skipped,
                'invalid_ansi_lines_skipped': self.invalid_ansi_lines_skipped,
                'count_saturated': self.saturated, 'summary_complete': complete,
                'known_header_observed': any(value for values in self.counts.values()
                                             for value in values.values()),
                'cargo_substage_success_proven': False}


class Stream:
    def __init__(self, cap=CAP):
        self.cap, self.count = cap, 0
        self.head, self.tail, self.line = b'', b'', b''
        self.digest = hashlib.sha256()
        self.suspect = False
        self.diagnostics = DiagnosticCounts()
        self.json_observer = None

    def feed(self, data):
        self.diagnostics.feed(data)
        if self.json_observer is not None:
            self.json_observer.feed(data)
        self.count += len(data)
        self.digest.update(data)
        self.head += data[:max(0, self.cap - len(self.head))]
        self.tail = (self.tail + data)[-self.cap:]
        # Scan whole lines across chunk boundaries; any overlong line is withheld.
        lines = (self.line + data).split(b'\n')
        for line in lines[:-1]:
            self.suspect |= len(line) > 65536 or suspicious(line)
        self.line = lines[-1]
        if len(self.line) > 65536:
            self.suspect = True
            self.line = self.line[-65536:]

    def finish(self):
        self.diagnostics.finish()
        if self.json_observer is not None:
            self.json_observer.finish()
        self.suspect |= suspicious(self.line)
        self.line = b''
        return {'bytes': self.count, 'sha256': self.digest.hexdigest(),
                'truncated': self.count > 2 * self.cap,
                'head_bytes': min(self.count, self.cap),
                'tail_bytes': min(self.cap, max(0, self.count - self.cap)),
                'layout': 'head_then_tail_no_marker', 'suspected_sensitive': self.suspect}

    def retained(self):
        if self.count <= self.cap:
            return self.head
        return self.head + self.tail[-min(self.cap, self.count - self.cap):]


def minimal_env(home):
    return {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': str(home), 'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0', 'DOCKER_BUILDKIT': '0'}


def capture(argv, env, seconds, disk=None, abort=None, observer=None):
    streams = [Stream(), Stream()]
    streams[1].json_observer = observer
    started = time.monotonic()
    initial_free = shutil.disk_usage(disk).free if disk else None
    result = {'argv': argv, 'exit': None, 'stop': None}
    try:
        proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        result['stop'] = 'launch_failed'
        result['streams'] = [s.finish() for s in streams]
        return result, streams
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, 0)
    selector.register(proc.stderr, selectors.EVENT_READ, 1)
    stopped_at = None
    while selector.get_map() or proc.poll() is None:
        now = time.monotonic()
        if stopped_at is None:
            reason = 'timeout' if now - started > seconds else None
            if disk:
                free = shutil.disk_usage(disk).free
                if free < 4 * 1024**3 or initial_free - free > 8 * 1024**3:
                    reason = 'disk_floor_or_phase_budget'
            if reason:
                result['stop'] = reason
                stopped_at = now
                if abort:
                    abort()
                proc.terminate()
        if stopped_at is not None and now - stopped_at > 3:
            proc.kill()
            # Descendant-held pipes must not turn the bound into an infinite wait.
            result['stop'] = result['stop'] or 'drain_timeout'
            break
        for key, _ in selector.select(0.2):
            data = os.read(key.fileobj.fileno(), 65536)
            if data:
                streams[key.data].feed(data)
            else:
                selector.unregister(key.fileobj)
    selector.close()
    proc.stdout.close()
    proc.stderr.close()
    try:
        result['exit'] = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        result['exit'] = proc.wait(timeout=3)
        result['stop'] = result['stop'] or 'wait_timeout'
    result['streams'] = [s.finish() for s in streams]
    return result, streams


class MetadataFailure(ValueError):
    def __init__(self, result, streams):
        super().__init__('bounded_metadata_failed')
        self.safe = {'exit': result['exit'], 'stop': result['stop'],
                     'stdout_bytes': streams[0].count, 'stderr_bytes': streams[1].count}


def checked(argv, env):
    result, streams = capture(argv, env, 20)
    if result['exit'] != 0 or result['stop'] or any(s.count > 1024 * 1024 for s in streams):
        raise MetadataFailure(result, streams)
    return streams[0].retained()


def git(repo, env, *args):
    return checked(['git', '-C', str(repo), *args], env)


def identity(repo, commit, tree, env):
    if git(repo, env, 'rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('source_commit_mismatch')
    if tree and git(repo, env, 'rev-parse', 'HEAD^{tree}').decode().strip() != tree:
        raise ValueError('source_tree_mismatch')
    if git(repo, env, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('source_dirty')



def action_identity(repo, env):
    # A uses SHA may name an annotated tag object; HEAD names its peeled commit.
    if git(repo, env, 'cat-file', '-t', ACTION).decode().strip() != 'tag':
        raise ValueError('action_tag_object_type_mismatch')
    if git(repo, env, 'rev-parse', ACTION + '^{commit}').decode().strip() != ACTION_COMMIT:
        raise ValueError('action_tag_peel_mismatch')
    identity(repo, ACTION_COMMIT, ACTION_TREE, env)
    body = git(repo, env, 'cat-file', 'tag', ACTION)
    if len(body) > 4096 or hashlib.sha1(b'tag ' + str(len(body)).encode() + b'\0' + body).hexdigest() != ACTION:
        raise ValueError('action_tag_object_hash_mismatch')
    return {'tag_object': ACTION, 'tag_object_sha256': hashlib.sha256(body).hexdigest(),
            'tag_object_bytes': len(body), 'peeled_commit': ACTION_COMMIT,
            'tree': ACTION_TREE}


def snapshot(repo, env):
    digest = hashlib.sha256()
    paths = git(repo, env, 'ls-files', '-z').split(b'\0')
    for raw in filter(None, paths):
        path = repo / os.fsdecode(raw)
        digest.update(raw + b'\0')
        if path.is_symlink():
            digest.update(b'link:' + os.fsencode(os.readlink(path)))
        elif path.is_file():
            with path.open('rb') as handle:
                while data := handle.read(1024 * 1024):
                    digest.update(data)
        else:
            digest.update(b'missing')
    return digest.hexdigest()



def reviewed_source_url(value, kind):
    if not isinstance(value, str):
        return False
    path = r'([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)'
    if kind == 'patch_key':
        match = re.fullmatch(r'ssh://git@github\.com/' + path, value)
    elif kind == 'lock_source':
        match = re.fullmatch(r'git\+https://github\.com/' + path + r'\?rev=[0-9a-f]{40}#[0-9a-f]{40}', value)
    else:
        return False
    return bool(match and match[1] not in {'.', '..'} and match[2] not in {'.', '..'})


def source_sensitive(parsed, filename):
    # Only replace reviewed fields in a PRIVATE SCAN COPY, never source files.
    # Hash each original value so the exception retains its exact binding.
    checked = json.loads(json.dumps(parsed))
    if filename == 'Cargo.toml' and isinstance(checked.get('patch'), dict):
        checked['patch'] = [
            [('reviewed-key-sha256:' + hashlib.sha256(key.encode()).hexdigest())
             if reviewed_source_url(key, 'patch_key') else key, value]
            for key, value in checked['patch'].items()
        ]
    if filename == 'Cargo.lock' and isinstance(checked.get('package'), list):
        for package in checked['package']:
            if isinstance(package, dict) and reviewed_source_url(package.get('source'), 'lock_source'):
                package['source'] = 'reviewed-source-sha256:' + hashlib.sha256(package['source'].encode()).hexdigest()
    return suspicious(json.dumps(checked).encode())


def input_gate(repo, env):
    for raw in filter(None, git(repo, env, 'ls-files', '-z').split(b'\0')):
        path = repo / os.fsdecode(raw)
        if path.name in {'credentials', 'credentials.toml', '.git-credentials'}:
            return False
        if path.name in {'Cargo.toml', 'Cargo.lock', 'deny.toml', 'rust-toolchain.toml'} or '.cargo' in path.parts:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
                return False
            try:
                parsed = tomllib.loads(path.read_text())
            except (ValueError, UnicodeError):
                return False
            if source_sensitive(parsed, path.name):
                return False
    config = repo / '.git/config'
    return (config.is_file() and config.stat().st_size < 65536
            and b'extraheader' not in config.read_bytes().lower()
            and not suspicious(config.read_bytes()))


def publish(directory, records, inputs_ok):
    directory.mkdir(mode=0o700)
    for name, result, streams in records:
        allowed = inputs_ok and not result['stop'] and not any(s.suspect for s in streams)
        result['raw_published'] = allowed
        # inputs_ok also binds unchanged control and confirmed cleanup at caller.
        result['diagnostic_summary_withheld'] = not inputs_ok
        if inputs_ok:
            result['diagnostic_summaries'] = [
                stream.diagnostics.receipt(complete=result['stop'] is None)
                for stream in streams
            ]
        if allowed:
            for label, stream in zip(['stdout', 'stderr'], streams):
                (directory / f'{name}-{label}.bin').write_bytes(stream.retained())


CONTROL_FILES = ['.github/scripts/cargo_deny_json_diagnostic.py',
                 '.github/scripts/cargo_deny_json_support.py',
                 '.github/scripts/test_cargo_deny_json_diagnostic.py',
                 '.github/workflows/cargo-deny-json-diagnostic.yml']


class DiagnosticStop(Exception):
    """Expected phase failure whose original status is already recorded."""


def control_receipt(control, event_sha, workflow_sha, env):
    if not re.fullmatch('[0-9a-f]{40}', event_sha) or workflow_sha != event_sha:
        raise ValueError('control_event_workflow_mismatch')
    identity(control, event_sha, None, env)
    tree = git(control, env, 'rev-parse', 'HEAD^{tree}').decode().strip()
    if not re.fullmatch('[0-9a-f]{40}', tree):
        raise ValueError('control_tree_invalid')
    hashes = {}
    for name in CONTROL_FILES:
        path = control / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
            raise ValueError('control_file_invalid')
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'head': event_sha, 'tree': tree, 'files_sha256': hashes}


def main(source, action, temp, control, event_sha, workflow_sha):
    home = temp / 'host-home'
    home.mkdir(mode=0o700)
    env = minimal_env(home)
    report = {'schema': 1, 'source': SOURCE, 'tree': TREE, 'action': ACTION,
              'base_declared': BASE, 'action_blobs': BLOBS,
              'cargo_deny_declared': '0.19.0',
              'rust_declared': '1.95.0', 'tool_actual': None, 'advisory_revisions': None,
              'image_id': None, 'container_exit': None, 'container_oom': None,
              'inputs_ok': False, 'records': [],
              'historical_failure_reproduced': False,
              'secret_absence_proven': False,
              'differences': ['new_live_upstreams', 'empty_HOME_and_CARGO_HOME',
                              'allowlisted_environment', 'ubuntu22_not_original_ubuntu_latest',
                              'no_host_sysctl_changes',
                              '2cpu_6GiB_256pid_limits', 'fresh_separate_diagnostic', 'NEW_json_format_command_not_original_12args']}
    records = []
    observer = None
    cargo = None
    run = None
    container = 'deny-diag-' + uuid.uuid4().hex
    image = 'deny-diag:' + uuid.uuid4().hex
    exit_code = 125
    container_attempted = False
    cleanup_result = None
    def cleanup():
        nonlocal cleanup_result
        if not container_attempted or cleanup_result is not None:
            return
        # Exactly one attempt. Never retry failed/denied cleanup from finally.
        cleanup_result = {'exit': None, 'stop': 'cleanup_exception'}
        try:
            cleanup_result, _ = capture(['docker', 'rm', '-f', container], env, 10)
        except Exception:
            pass
    try:
        report['stage'] = 'control_identity'
        report['control_before'] = control_receipt(control, event_sha, workflow_sha, env)
        report['stage'] = 'source_identity'
        identity(source, SOURCE, TREE, env)
        report['stage'] = 'action_identity'
        report['action_identity'] = action_identity(action, env)
        report['stage'] = 'action_blobs'
        for name, expected in BLOBS.items():
            data = (action / name).read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if actual != expected:
                raise ValueError('action_blob_mismatch')
        report['stage'] = 'source_snapshot'
        report['source_before'] = snapshot(source, env)
        report['lock_before'] = hashlib.sha256((source / 'codex-rs/Cargo.lock').read_bytes()).hexdigest()
        report['stage'] = 'input_gate'
        report['inputs_ok'] = input_gate(source, env)
        if not report['inputs_ok']:
            raise ValueError('input_credential_or_url_gate')
        report['stage'] = 'json_input_binding'
        observer = JSONObservations(lock_allowlist((source / 'codex-rs/Cargo.lock').read_bytes()))
        report['default_db_config'] = default_db_config((source / 'codex-rs/deny.toml').read_bytes())
        if not report['default_db_config']:
            raise ValueError('unsupported_db_configuration')
        report['stage'] = 'disk_preflight'
        if shutil.disk_usage(temp).free < 12 * 1024**3:
            raise ValueError('insufficient_initial_disk')
        # Minimal build context contains only unchanged official build inputs.
        context = temp / 'build'
        context.mkdir()
        for name in ['Dockerfile', 'entrypoint.sh']:
            shutil.copy2(action / name, context / name)
        report['stage'] = 'image_build'
        build, streams = capture(['docker', 'build', '--tag', image, str(context)], env, 600, temp)
        records.append(('build', build, streams))
        exit_code = build['exit'] if build['exit'] is not None and build['exit'] > 0 else 125
        if build['exit'] != 0 or build['stop']:
            raise DiagnosticStop()
        report['stage'] = 'image_identity'
        value = checked(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], env).decode().strip()
        if not re.fullmatch('sha256:[0-9a-f]{64}', value):
            raise ValueError('image_identity_invalid')
        report['image_id'] = value
        scratch = temp / 'container-home'
        cargo = temp / 'container-cargo'
        scratch.mkdir(mode=0o700)
        cargo.mkdir(mode=0o700)
        argv = ['docker', 'run', '--name', container, '--cpus', '2', '--memory', '6g',
                '--pids-limit', '256', '--workdir', '/github/workspace',
                '--mount', f'type=bind,src={source},dst=/github/workspace',
                '--mount', f'type=bind,src={scratch},dst=/github/home',
                '--mount', f'type=bind,src={cargo},dst=/diagnostic-cargo',
                '--env', 'HOME=/github/home', '--env', 'CARGO_HOME=/diagnostic-cargo',
                '--env', 'GITHUB_WORKSPACE=/github/workspace', '--env', 'CI=true',
                '--env', 'GITHUB_ACTIONS=true', value, *ARGS]
        report['stage'] = 'container_run'
        container_attempted = True
        run, streams = capture(argv, env, 900, temp, cleanup, observer=observer)
        records.append(('run', run, streams))
        exit_code = run['exit'] if run['exit'] is not None and run['exit'] >= 0 else 125
        if run['stop']:
            exit_code = 125
        report['stage'] = 'container_state'
        if not run['stop']:
            try:
                state = checked(['docker', 'inspect', '--format',
                                 '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}',
                                 container], env).decode().strip()
                match = re.fullmatch(r'exited ([0-9]{1,3}) (true|false)', state)
                if match and int(match[1]) <= 255:
                    report['container_exit'] = int(match[1])
                    report['container_oom'] = match[2] == 'true'
                if not match or report['container_exit'] != run['exit'] or report['container_oom']:
                    exit_code = 125
            except Exception:
                exit_code = 125
        report['stage'] = 'source_after'
        report['source_after'] = snapshot(source, env)
        report['lock_after'] = hashlib.sha256((source / 'codex-rs/Cargo.lock').read_bytes()).hexdigest()
        report['source_changed'] = (report['source_after'] != report['source_before'] or bool(git(source, env, 'status', '--porcelain', '--untracked-files=all')))
        if report['source_changed'] and exit_code == 0:
            exit_code = 125
    except DiagnosticStop:
        pass
    except Exception as error:
        # Only fixed stage and numeric/bounded status fields, never raw errors.
        if isinstance(error, MetadataFailure):
            report['metadata_failure'] = error.safe
        report['collector_error'] = True
        exit_code = 125
    finally:
        cleanup()
        report['cleanup_attempted'] = container_attempted
        report['cleanup'] = cleanup_result
        cleanup_ok = not container_attempted or (cleanup_result is not None and cleanup_result['exit'] == 0 and cleanup_result['stop'] is None)
        report['cleanup_confirmed'] = cleanup_ok
        control_ok = False
        if 'control_before' in report:
            try:
                report['control_after'] = control_receipt(control, event_sha, workflow_sha, env)
                control_ok = report['control_before'] == report['control_after']
            except Exception:
                report['control_after'] = None
        report['control_unchanged'] = control_ok
        if not cleanup_ok or not control_ok:
            exit_code = 125
        if 'source_before' in report and 'source_after' not in report:
            try:
                report['source_after'] = snapshot(source, env)
                report['source_changed'] = (report['source_after'] != report['source_before'] or bool(git(source, env, 'status', '--porcelain', '--untracked-files=all')))
            except Exception:
                report['source_after'] = None
                report['source_changed'] = None
        # Only inspect future owned metadata after confirmed removal/stopped container.
        execution_ok = (cleanup_ok and control_ok and report['inputs_ok']
                        and not report.get('collector_error', False)
                        and report.get('lock_after') == report.get('lock_before')
                        and report.get('source_changed') is False
                        and report.get('source_after') == report.get('source_before')
                        and run is not None and run['stop'] is None
                        and report['container_exit'] == run['exit']
                        and report['container_oom'] is False)
        report['advisory_revision_receipt'] = {'status': 'execution_gate', 'commit': None}
        if execution_ok and cargo is not None and report.get('default_db_config'):
            report['advisory_revision_receipt'] = revision_receipt(cargo)
            revision = report['advisory_revision_receipt']['commit']
            report['advisory_revisions'] = [revision] if revision else None
        if observer is not None:
            permitted = execution_ok and bool(report['advisory_revisions'])
            report['json_observations'] = observer.receipt(permitted, run is not None and run['stop'] is None)
        public = temp / 'public'
        publish(public, records, report['inputs_ok'] and cleanup_ok and control_ok)
        # argv includes only fixed public strings and generated job-local paths.
        report['records'] = [dict(phase=name, **result) for name, result, _ in records]
        report['exit_requested'] = exit_code
        (public / 'receipt.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return exit_code


if __name__ == '__main__':
    sys.exit(main(*(Path(p).resolve() for p in sys.argv[1:5]), *sys.argv[5:7]))
