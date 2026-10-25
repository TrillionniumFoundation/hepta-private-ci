"""Bounded capture and unchanged publication/input screening from reviewed diagnostic."""
import ctypes

import hashlib

import itertools

import json

import os

from pathlib import Path

import re

import selectors

import signal

import shutil

import subprocess

import sys

import time

import tomllib

import uuid

from urllib.parse import urlsplit

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

OWNERSHIP_UNCERTAIN = False


def _no_children():
    try:
        os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return True
    return False


def _subreaper():
    if sys.platform != 'linux':
        raise RuntimeError('linux_required')
    libc = ctypes.CDLL(None, use_errno=True)
    value = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(value), 0, 0, 0) != 0 or value.value not in (0, 1):
        raise RuntimeError('subreaper_query_failed')
    if value.value == 0 and libc.prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('subreaper_setup_failed')


def _cleanup_owned(proc, timeout=5):
    # Leader is still unreaped (WNOWAIT): its PID/PGID cannot be reused before
    # this ONE destructive signal. Permission denial is terminal, never retried.
    receipt = {'owned_pgid': proc.pid, 'confirmed': False, 'signal_attempts': []}
    deadline = time.monotonic() + timeout
    try:
        receipt['signal_attempts'].append('SIGKILL')
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        receipt['worker_exit'] = proc.wait(timeout=max(.01, deadline-time.monotonic()))
        receipt['reaped_descendants'] = []
        while True:
            try:
                child, status = os.waitpid(-proc.pid, os.WNOHANG)
            except ChildProcessError:
                child = -1
            if child > 0:
                receipt['reaped_descendants'].append({'pid': child, 'wait_status': status})
                continue
            if child == -1:
                try:
                    os.killpg(proc.pid, 0)
                except ProcessLookupError:
                    if not _no_children():
                        receipt['error'] = 'unexpected_adopted_children'
                        return receipt
                    receipt['confirmed'] = True
                    return receipt
            if time.monotonic() >= deadline:
                receipt['error'] = 'cleanup_timeout'
                return receipt
            time.sleep(.01)
    except PermissionError:
        receipt['error'] = 'signal_permission_denied'
    except Exception:
        receipt['error'] = 'cleanup_unconfirmed'
    return receipt


def capture(argv, env, seconds, disk=None, abort=None):
    global OWNERSHIP_UNCERTAIN
    streams = [Stream(), Stream()]
    result = {'argv': argv, 'exit': None, 'stop': None, 'cleanup': {'confirmed': False}}
    proc = None
    try:
        if OWNERSHIP_UNCERTAIN:
            raise RuntimeError('prior_cleanup_uncertain')
        _subreaper()
        if not _no_children():
            raise RuntimeError('exclusive_ownership_required')
        initial_free = globals().get('DISK_INITIAL_FREE', shutil.disk_usage(disk).free) if disk else None
        deadline = time.monotonic() + seconds
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, 0)
            selector.register(proc.stderr, selectors.EVENT_READ, 1)
            while True:
                reason = 'timeout' if time.monotonic() >= deadline else None
                if disk:
                    free = shutil.disk_usage(disk).free
                    if free < 4 * 1024**3 or initial_free - free > 8 * 1024**3:
                        reason = 'disk_floor_or_total_budget'
                if reason:
                    result['stop'] = reason
                    break
                for key, _ in selector.select(.05):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if data:
                        streams[key.data].feed(data)
                    else:
                        selector.unregister(key.fileobj)
                # Never poll()/wait() before owned teardown: keep PID reserved.
                exited = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None and not selector.get_map():
                    break
    except PermissionError:
        result['stop'] = 'launch_permission_denied'
    except Exception:
        result['stop'] = 'capture_or_ownership_failed'
    finally:
        if proc is not None:
            result['cleanup'] = _cleanup_owned(proc)
            proc.stdout.close()
            proc.stderr.close()
            if result['cleanup']['confirmed']:
                result['exit'] = result['cleanup']['worker_exit']
            else:
                OWNERSHIP_UNCERTAIN = True
                result['stop'] = result['stop'] or 'cleanup_unconfirmed'
        result['streams'] = [stream.finish() for stream in streams]
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
