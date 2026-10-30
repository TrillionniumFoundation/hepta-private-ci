"""Independent Linux PTY echo observation, not a Rust/macOS/Windows test."""
import json
import os
import select
import subprocess
import sys
import termios
import time

MARKER = b"__codex_pty_ready__"


def read_until(fd, predicate):
    data = bytearray()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if readable:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            data.extend(chunk)
            if predicate(data):
                return bytes(data)
    raise RuntimeError(f"probe observation timed out: {bytes(data)!r}")


def observe(name, command):
    master, slave = os.openpty()
    gate_read, gate_write = os.pipe()
    child = None
    try:
        attrs = termios.tcgetattr(slave)
        attrs[3] |= termios.ECHO | termios.ICANON
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        code = (
            "import os,sys; gate=int(sys.argv[1]); os.read(gate,1); "
            "os.close(gate); exec(sys.stdin.readline())"
        )
        child = subprocess.Popen(
            [sys.executable, "-I", "-S", "-u", "-c", code, str(gate_read)],
            stdin=slave, stdout=slave, stderr=slave, pass_fds=(gate_read,),
        )
        os.close(gate_read)
        gate_read = None
        os.close(slave)
        slave = None
        os.write(master, command)
        # The independent pipe is still closed: the child cannot execute input.
        echoed = read_until(master, lambda data: data.endswith(b"\n"))
        blocked_echo_contains_marker = MARKER in echoed
        os.write(gate_write, b"x")
        os.close(gate_write)
        gate_write = None
        executed = read_until(master, lambda data: MARKER in data)
        code = child.wait(timeout=2)
        assert code == 0, code
        assert blocked_echo_contains_marker == (name == "original_literal")
        return {
            "case": name,
            "echo_before_execution_hex": echoed.hex(),
            "marker_in_echo_before_gate_release": blocked_echo_contains_marker,
            "output_after_gate_release_hex": executed.hex(),
            "exit_code": code,
        }
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        for fd in (master, slave, gate_read, gate_write):
            if fd is not None:
                os.close(fd)


def main():
    started = time.monotonic()
    observations = [
        observe("original_literal", b"print('__codex_pty_ready__')\n"),
        observe("split_literal", b"print('__codex_' + 'pty_ready__')\n"),
    ]
    print(json.dumps({
        "scope": "independent Linux PTY echo ordering only",
        "rust_tests_run": False,
        "macos_tests_run": False,
        "windows_tests_run": False,
        "observations": observations,
        "owned_children_reaped_and_descriptors_closed": True,
        "elapsed_seconds": time.monotonic() - started,
    }, indent=2))


if __name__ == "__main__":
    main()
