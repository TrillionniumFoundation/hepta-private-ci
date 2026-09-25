#!/usr/bin/env python3
"""Expose an internal-network Synapse listener on a host loopback port.

The Synapse container deliberately has no published Docker port.  This small,
runner-owned process is the only host-side transport: each accepted client is
bridged through a fixed ``docker exec`` command to a Python process in the
Synapse network namespace, where the process connects only to
``127.0.0.1:8008``.  There is no shell interpolation or configurable remote
address in either command.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass


TRANSPORT = "docker-exec-loopback-proxy-v1"
CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# This source is deliberately constant and is hashed by the shell runner.  It
# performs a raw byte bridge; no HTTP parsing or destination supplied by the
# client is accepted here.
BRIDGE_SOURCE = r'''
import os
import select
import socket

peer = socket.create_connection(("127.0.0.1", 8008), timeout=5.0)
peer.setblocking(False)
stdin_open = True
peer_open = True

def write_all(fd, data):
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except BlockingIOError:
            select.select([], [fd], [], 30.0)
            continue
        if written <= 0:
            return False
        view = view[written:]
    return True

try:
    while stdin_open or peer_open:
        readable = []
        if stdin_open:
            readable.append(0)
        if peer_open:
            readable.append(peer)
        if not readable:
            break
        ready, _, _ = select.select(readable, [], [], 30.0)
        if not ready:
            continue
        for item in ready:
            if item == 0:
                data = os.read(0, 65536)
                if not data:
                    stdin_open = False
                    try:
                        peer.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                elif not write_all(peer.fileno(), data):
                    stdin_open = False
            else:
                try:
                    data = peer.recv(65536)
                except BlockingIOError:
                    continue
                if not data:
                    peer_open = False
                    continue
                if not write_all(1, data):
                    peer_open = False
finally:
    peer.close()
'''


def _write_private_json(path: pathlib.Path, payload: dict[str, object]) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise RuntimeError(f"ready file authority is invalid: {path}")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise RuntimeError("ready file parent is not a physical directory")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as output:
            output.write(
                (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
            )
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary_name, path, follow_symlinks=False)
        os.unlink(temporary_name)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


@dataclass(eq=False)
class Session:
    client: socket.socket
    process: subprocess.Popen[bytes]


class Proxy:
    def __init__(self, args: argparse.Namespace) -> None:
        docker = pathlib.Path(args.docker).resolve(strict=True)
        if not docker.is_file() or not os.access(docker, os.X_OK):
            raise RuntimeError("docker authority is not an executable regular file")
        if not CONTAINER_NAME_RE.fullmatch(args.container):
            raise RuntimeError("container name is outside the fixed authority")
        ready = pathlib.Path(args.ready).resolve()
        if not ready.is_absolute():
            raise RuntimeError("ready path must be absolute")
        self.docker = str(docker)
        self.container = args.container
        self.ready_path = ready
        self.listener: socket.socket | None = None
        self.stop_event = threading.Event()
        self.sessions: set[Session] = set()
        self.sessions_lock = threading.Lock()
        self.threads: set[threading.Thread] = set()

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _signal(self, _signum: int, _frame: object) -> None:
        # Signal handlers run on the main thread and may interrupt code while
        # it owns ``sessions_lock``.  Do not acquire that non-reentrant lock
        # here; the run-loop performs the authoritative session snapshot and
        # termination immediately after the listener is closed.
        self.stop_event.set()
        listener = self.listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

    def _start_session(self, client: socket.socket) -> None:
        process: subprocess.Popen[bytes] | None = None
        started_threads: list[threading.Thread] = []
        try:
            process = subprocess.Popen(
                [self.docker, "exec", "-i", self.container, "python3", "-c", BRIDGE_SOURCE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            assert process.stdin is not None and process.stdout is not None
            session = Session(client=client, process=process)
            with self.sessions_lock:
                stopping = self.stop_event.is_set()
                if not stopping:
                    self.sessions.add(session)
            if stopping:
                self._terminate_process(process)
                client.close()
                return
            to_process = threading.Thread(
                target=self._copy_client_to_process,
                args=(session,),
                name="proxy-client-to-synapse",
                daemon=True,
            )
            from_process = threading.Thread(
                target=self._copy_process_to_client,
                args=(session,),
                name="proxy-synapse-to-client",
                daemon=True,
            )
            with self.sessions_lock:
                # Start while holding the same lock used by shutdown
                # snapshots, so no snapshot can contain an unstarted thread.
                to_process.start()
                started_threads.append(to_process)
                self.threads.add(to_process)
                from_process.start()
                started_threads.append(from_process)
                self.threads.add(from_process)
            # A shutdown signal can arrive after the run-loop's first session
            # snapshot but before this worker registers its child.  Poll with
            # a bounded wait so that late registrations still converge during
            # the same shutdown instead of leaving a child behind.
            while process.poll() is None:
                if self.stop_event.is_set():
                    self._terminate_process(process)
                    break
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
            to_process.join(timeout=5.0)
            from_process.join(timeout=5.0)
        except (OSError, RuntimeError) as error:
            print(f"proxy session failed: {error}", file=sys.stderr, flush=True)
            if process is not None:
                self._terminate_process(process)
            try:
                client.close()
            except OSError:
                pass
            for thread in started_threads:
                thread.join(timeout=5.0)
        finally:
            if process is not None:
                with self.sessions_lock:
                    stale = [
                        session
                        for session in self.sessions
                        if session.process is process
                    ]
                    for session in stale:
                        self.sessions.discard(session)
                    # ``difference_update`` mutates ``self.threads`` while
                    # consuming its iterable.  Iterating the set itself is
                    # therefore unsafe (and raises ``RuntimeError: Set
                    # changed size during iteration`` on current Python).
                    # Take a stable snapshot while holding the same lock as
                    # every other thread-set access.
                    stale_threads = tuple(self.threads)
                    self.threads.difference_update(
                        thread
                        for thread in stale_threads
                        if not thread.is_alive()
                    )

    @staticmethod
    def _copy_client_to_process(session: Session) -> None:
        assert session.process.stdin is not None
        try:
            while data := session.client.recv(65536):
                session.process.stdin.write(data)
                session.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                session.process.stdin.close()
            except OSError:
                pass

    @staticmethod
    def _copy_process_to_client(session: Session) -> None:
        assert session.process.stdout is not None
        try:
            # ``BufferedReader.read(n)`` may wait for all n bytes.  HTTP
            # keep-alive responses are intentionally shorter than that, so
            # read whatever the Docker exec pipe has made available.
            while data := os.read(session.process.stdout.fileno(), 65536):
                session.client.sendall(data)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                session.client.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def run(self) -> int:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.settimeout(0.5)
        self.listener = listener
        port = int(listener.getsockname()[1])
        _write_private_json(
            self.ready_path,
            {
                "schema_version": 1,
                "transport": TRANSPORT,
                "host": "127.0.0.1",
                "port": port,
                "pid": os.getpid(),
                "container": self.container,
                "target": "127.0.0.1:8008",
            },
        )
        print(f"R4_PROXY_READY transport={TRANSPORT} host=127.0.0.1 port={port} pid={os.getpid()}", flush=True)
        while not self.stop_event.is_set():
            try:
                client, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stop_event.is_set():
                    break
                raise
            thread = threading.Thread(
                target=self._start_session,
                args=(client,),
                name="proxy-client",
                daemon=True,
            )
            # Keep the thread-set invariant across shutdown: once the thread
            # is visible to the cleanup snapshot it has already been started.
            with self.sessions_lock:
                thread.start()
                self.threads.add(thread)
        try:
            listener.close()
        except OSError:
            pass
        with self.sessions_lock:
            sessions = list(self.sessions)
            threads = list(self.threads)
        for session in sessions:
            session.process.terminate()
            try:
                session.client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                session.client.close()
            except OSError:
                pass
        for thread in threads:
            thread.join(timeout=10.0)
        with self.sessions_lock:
            survivor_sessions = [
                session
                for session in self.sessions
                if session.process.poll() is None
            ]
        if survivor_sessions:
            for session in survivor_sessions:
                session.process.kill()
            raise RuntimeError(
                "proxy child survived graceful shutdown: "
                f"{[session.process.pid for session in survivor_sessions]}"
            )
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--ready", required=True)
    return parser.parse_args()


def main() -> int:
    proxy = Proxy(parse_args())
    signal.signal(signal.SIGTERM, proxy._signal)
    signal.signal(signal.SIGINT, proxy._signal)
    try:
        return proxy.run()
    except BaseException as error:
        print(f"proxy failed closed: {error}", file=sys.stderr, flush=True)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
