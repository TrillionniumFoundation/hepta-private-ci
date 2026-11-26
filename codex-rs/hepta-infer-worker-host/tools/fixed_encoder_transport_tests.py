"""Real Unix transport checks; no Root bootstrap or model authority is created."""

import ast
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def functions():
    source = Path(__file__).with_name("hepta_fixed_nomic_encoder.py")
    parsed = ast.parse(source.read_bytes())
    selected = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in {"send_response", "serve"}
    ]
    namespace = {
        "Path": Path,
        "socket": socket,
        "os": os,
        "stat": stat,
        "json": json,
        "now_ms": lambda: time.time_ns() // 1_000_000,
        "decode_json": json.loads,
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace


class FinalTransportTests(unittest.TestCase):
    def test_last_frame_socket_survives_native_post_read_validation_until_peer_eof(
        self,
    ):
        namespace = functions()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "encoder.sock"
            cfg = {
                "schema": "hepta.fixed-nomic-encoder.v2",
                "socket_path": str(path),
                "max_requests": 1,
                "timeout_ms": 500,
                "expires_at_ms": time.time_ns() // 1_000_000 + 2000,
            }
            request = {"pair_id": "public.one", "source_row_sha256": "a" * 64}
            encoded, errors = [], []
            namespace["protected_path"] = lambda *args, **kwargs: SimpleNamespace(
                stat=lambda: SimpleNamespace(st_gid=975, st_mode=0o40750)
            )
            namespace["authorize"] = lambda *args: (os.getpid(), "same-peer")

            def encode(*args):
                encoded.append(request)
                return {"features_q24": [1, 2]}

            namespace["encode"] = encode
            original_stat = Path.stat

            def claimed_socket_owner(value, *args, **kwargs):
                if value == path:
                    actual = original_stat(value, *args, **kwargs)
                    return SimpleNamespace(
                        st_gid=975,
                        st_uid=0,
                        st_mode=actual.st_mode,
                        st_dev=actual.st_dev,
                        st_ino=actual.st_ino,
                    )
                return original_stat(value, *args, **kwargs)

            def worker():
                try:
                    namespace["serve"](cfg, {}, None, {"public.one": request}, "pin")
                except Exception as error:
                    errors.append(error)

            with patch.object(Path, "stat", claimed_socket_owner):
                thread = threading.Thread(target=worker)
                thread.start()
                try:
                    deadline = time.monotonic() + 1
                    while not path.exists() and time.monotonic() < deadline:
                        time.sleep(0.001)
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.settimeout(1)
                        client.connect(str(path))
                        before = path.lstat()
                        peer = client.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, 12
                        )
                        client.sendall(json.dumps(request).encode() + b"\n")
                        self.assertEqual(
                            json.loads(client.recv(4096)),
                            {"features_q24": [1, 2], "run_tuple": {}},
                        )
                        time.sleep(0.05)
                        after = path.lstat()
                        self.assertEqual(
                            (before.st_dev, before.st_ino), (after.st_dev, after.st_ino)
                        )
                        self.assertEqual(
                            peer,
                            client.getsockopt(
                                socket.SOL_SOCKET, socket.SO_PEERCRED, 12
                            ),
                        )
                        self.assertTrue(thread.is_alive())
                    thread.join(1)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(path.exists())
                    self.assertEqual(encoded, [request])
                    self.assertEqual(errors, [])
                finally:
                    thread.join(3)

    def test_expiry_bounds_drain_without_peer_eof_or_extra_request_budget(self):
        namespace = functions()
        server, client = socket.socketpair()
        config = {"timeout_ms": 500, "expires_at_ms": time.time_ns() // 1_000_000 + 40}
        with server, client:
            started = time.monotonic()
            worker = threading.Thread(
                target=namespace["send_response"], args=(server, b"{}\n", config, 0)
            )
            worker.start()
            self.assertEqual(client.recv(32), b"{}\n")
            worker.join(0.5)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - started, 0.5)

    def test_extra_frame_after_quota_is_rejected_without_decoding(self):
        namespace = functions()
        server, client = socket.socketpair()
        with server, client:
            client.sendall(b'{"another":"request"}\n')
            with self.assertRaisesRegex(ValueError, "exhausted encoder quota"):
                namespace["send_response"](
                    server,
                    b"{}\n",
                    {
                        "timeout_ms": 500,
                        "expires_at_ms": time.time_ns() // 1_000_000 + 1000,
                    },
                    0,
                )
            self.assertEqual(client.recv(32), b"{}\n")

    def test_nonfinal_frame_never_waits_for_peer_eof(self):
        namespace = functions()
        server, client = socket.socketpair()
        with server, client:
            namespace["send_response"](server, b"{}\n", {}, 1)
            self.assertEqual(client.recv(32), b"{}\n")


if __name__ == "__main__":
    unittest.main()
