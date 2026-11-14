#!/usr/bin/env python3
"""Isolated local execution of one exact original CPython HTTP module.

This is a bounded behavior probe, not the upstream CPython test suite. It does
not contact a remote address and does not accept arbitrary downloaded Python.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys

ORIGINAL_SHA256 = "8486d3c54d5ab5a8468703239287e60127d7f2159f5ae6652b33a456a3716444"


class CaptureSocket:
    def __init__(self):
        self.chunks = []

    def sendall(self, chunk):
        if not isinstance(chunk, bytes) or sum(map(len, self.chunks)) + len(chunk) > 16384:
            raise ValueError("unbounded or nonbyte send")
        self.chunks.append(chunk)

    def content(self):
        return b"".join(self.chunks)


def forbid_network(*args, **kwargs):
    raise RuntimeError("external network operations prohibited")


def execute(original_path: Path):
    source = original_path.read_bytes()
    if len(source) > 128 * 1024 or hashlib.sha256(source).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("unregistered original CPython module SHA-256")
    spec = importlib.util.spec_from_file_location("pinned_original_cpython_http_client", original_path)
    if spec is None or spec.loader is None:
        raise ValueError("original Python module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.HTTPConnection.__module__ != "pinned_original_cpython_http_client":
        raise ValueError("incorrect HTTP implementation provenance")
    # No actual TCP connection is ever created. A preconnected in-memory Socket
    # exercises the original implementation's actual send paths.
    socket.socket = forbid_network
    socket.create_connection = forbid_network
    cases = []

    def record(name, value):
        cases.append({"id": name,
                      "captured_base64": base64.b64encode(value).decode("ascii"),
                      "captured_sha256": hashlib.sha256(value).hexdigest(),
                      "captured_bytes": len(value)})

    s1 = CaptureSocket()
    conn = module.HTTPConnection("example.com")
    conn.sock = s1
    conn.request("POST", "/cross-file", body=b"abc", headers={"X-Audit": "yes"})
    record("py-http-01", s1.content())

    s2 = CaptureSocket()
    conn = module.HTTPConnection("example.com")
    conn.sock = s2
    conn.putrequest("GET", "/headers")
    conn.putheader("X-Audit", "provenance")
    conn.endheaders()
    record("py-http-02", s2.content())

    s3 = CaptureSocket()
    conn = module.HTTPConnection("example.com")
    conn.sock = s3
    conn.send(b"DIRECT-PAYLOAD")
    record("py-http-03", s3.content())

    return {"schema": "hepta.original-cpython-http-execution-worker.v1",
            "original_module_sha256": ORIGINAL_SHA256,
            "interpreter": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "isolated": sys.flags.isolated == 1 and sys.flags.no_site == 1,
            "network_calls_allowed": False,
            "upstream_project_suite_executed": False,
            "cases": cases}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise ValueError("expected precisely one source path")
    print(json.dumps(execute(Path(sys.argv[1])), sort_keys=True, separators=(",", ":")))
