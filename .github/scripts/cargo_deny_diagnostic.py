"""One new source-bound diagnostic; never a substitute for required CI."""
import hashlib
import itertools
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
from urllib.parse import urlsplit

SOURCE = '2e259b959339f1709370772c380145834e6bc0b7'
TREE = '010629adca9f5a6f5a2a93842f4d701d9e7d10a4'
ACTION = '82eb9f621fbc699dd0918f3ea06864c14cc84246'
BASE = 'rust:1.85.0-alpine3.20@sha256:f0cef6c65992995b1c7816cb667de95799852e3fbed9d06f95855cbc512a0fd0'
BLOBS = {'Dockerfile': '94f38ebce29aa536404c614879576defbb272c15',
         'entrypoint.sh': 'ba9fa82bb74e75bbf14ab3aa1852e2c601d5234e',
         'action.yml': 'fc4dd3b2553105b018e08d987b06a85a31fc2bf7'}
ARGS = ['1.95.0', '', '', '', 'false', '--log-level', 'warn',
        '--manifest-path', './codex-rs/Cargo.toml', '--all-features', 'check', '']
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


class Stream:
    def __init__(self, cap=CAP):
        self.cap, self.count = cap, 0
        self.head, self.tail, self.line = b'', b'', b''
        self.digest = hashlib.sha256()
        self.suspect = False

    def feed(self, data):
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


def capture(argv, env, seconds, disk=None, abort=None):
    streams = [Stream(), Stream()]
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


def checked(argv, env):
    result, streams = capture(argv, env, 20)
    if result['exit'] != 0 or result['stop'] or any(s.count > 1024 * 1024 for s in streams):
        raise ValueError('bounded_metadata_failed')
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


def advisory_revisions(cargo):
    """Read only bounded known git metadata, never config, objects or whole caches."""
    root = cargo / 'advisory-dbs'
    if root.is_symlink() or not root.is_dir():
        return None
    entries = list(itertools.islice(root.iterdir(), 9))
    if len(entries) > 8:
        return None
    revisions = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            return None
        gitdir = entry / '.git' if (entry / '.git').is_dir() else entry
        if gitdir.is_symlink():
            return None
        head = gitdir / 'HEAD'
        if head.is_symlink() or not head.is_file() or head.stat().st_size > 256:
            return None
        text = head.read_text().strip()
        if text.startswith('ref: refs/heads/'):
            ref = text[5:]
            if not re.fullmatch(r'refs/heads/[A-Za-z0-9_-]+', ref):
                return None
            target = gitdir / ref
            if any(p.is_symlink() for p in [gitdir / 'refs', gitdir / 'refs/heads', target]):
                return None
            text = target.read_text().strip() if target.is_file() and target.stat().st_size <= 256 else ''
        if not re.fullmatch('[0-9a-f]{40}', text):
            return None
        revisions.append(text)
    return sorted(revisions) or None


def publish(directory, records, inputs_ok):
    directory.mkdir(mode=0o700)
    for name, result, streams in records:
        allowed = inputs_ok and not result['stop'] and not any(s.suspect for s in streams)
        result['raw_published'] = allowed
        if allowed:
            for label, stream in zip(['stdout', 'stderr'], streams):
                (directory / f'{name}-{label}.bin').write_bytes(stream.retained())


CONTROL_FILES = ['.github/scripts/cargo_deny_diagnostic.py',
                 '.github/scripts/test_cargo_deny_diagnostic.py',
                 '.github/workflows/cargo-deny-diagnostic.yml']


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
                              '2cpu_6GiB_256pid_limits', 'fresh_separate_diagnostic']}
    records = []
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
        report['control_before'] = control_receipt(control, event_sha, workflow_sha, env)
        identity(source, SOURCE, TREE, env)
        identity(action, ACTION, None, env)
        for name, expected in BLOBS.items():
            data = (action / name).read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if actual != expected:
                raise ValueError('action_blob_mismatch')
        report['source_before'] = snapshot(source, env)
        report['lock_before'] = hashlib.sha256((source / 'codex-rs/Cargo.lock').read_bytes()).hexdigest()
        report['inputs_ok'] = input_gate(source, env)
        if not report['inputs_ok']:
            raise ValueError('input_credential_or_url_gate')
        if shutil.disk_usage(temp).free < 12 * 1024**3:
            raise ValueError('insufficient_initial_disk')
        # Minimal build context contains only unchanged official build inputs.
        context = temp / 'build'
        context.mkdir()
        for name in ['Dockerfile', 'entrypoint.sh']:
            shutil.copy2(action / name, context / name)
        build, streams = capture(['docker', 'build', '--tag', image, str(context)], env, 600, temp)
        records.append(('build', build, streams))
        exit_code = build['exit'] if build['exit'] is not None and build['exit'] > 0 else 125
        if build['exit'] != 0 or build['stop']:
            raise DiagnosticStop()
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
        container_attempted = True
        run, streams = capture(argv, env, 900, temp, cleanup)
        records.append(('run', run, streams))
        exit_code = run['exit'] if run['exit'] is not None and run['exit'] >= 0 else 125
        if run['stop']:
            exit_code = 125
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
        try:
            report['advisory_revisions'] = advisory_revisions(cargo)
        except (OSError, UnicodeError):
            report['advisory_revisions'] = None
        report['source_after'] = snapshot(source, env)
        report['lock_after'] = hashlib.sha256((source / 'codex-rs/Cargo.lock').read_bytes()).hexdigest()
        report['source_changed'] = (report['source_after'] != report['source_before'] or bool(git(source, env, 'status', '--porcelain', '--untracked-files=all')))
        if report['source_changed'] and exit_code == 0:
            exit_code = 125
    except DiagnosticStop:
        pass
    except Exception:
        # Never echo exceptions containing raw child output, paths or credentials.
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
        public = temp / 'public'
        publish(public, records, report['inputs_ok'] and cleanup_ok and control_ok)
        # argv includes only fixed public strings and generated job-local paths.
        report['records'] = [dict(phase=name, **result) for name, result, _ in records]
        report['exit_requested'] = exit_code
        (public / 'receipt.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return exit_code


if __name__ == '__main__':
    sys.exit(main(*(Path(p).resolve() for p in sys.argv[1:5]), *sys.argv[5:7]))
