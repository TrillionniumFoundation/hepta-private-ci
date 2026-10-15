#!/usr/bin/env python3
"""Replay actual original, SHA-pinned CPython HTTP behavior under isolated CPU.

An original Git static caller/import/definition edge is necessary but is not
by itself a verified executable behavior. This independently reopens source
bytes, checks all 12 cross-file static links, and invokes only a fixed original
CPython HTTP module with three offline preconnected FakeSocket scenarios.

No pretrained inference, live network, real upstream suite or semantic judge.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile

from memory_original_crossfile_trace import audit as static_audit
from real_source_reader_probe import SOURCE_SHA, REOPEN_SHA, digest, real_source, require, write_once

SCHEMA = "hepta.memory.original-cpython-http-offline-behavior.v1"
ORIGINAL_SHA256 = "8486d3c54d5ab5a8468703239287e60127d7f2159f5ae6652b33a456a3716444"
ORIGINAL_PATH = "Lib/http/client.py"
WORKER_SHA256 = "65778cea0501c39ef8827c91a2fab404cb00dffe6dbe9982dbb3eb59b0b34b35"
EXPECTED = {
    "py-http-01": (b"POST /cross-file HTTP/1.1\r\nHost: example.com\r\nAccept-Encoding: identity\r\n"
                   b"Content-Length: 3\r\nX-Audit: yes\r\n\r\nabc"),
    "py-http-02": (b"GET /headers HTTP/1.1\r\nHost: example.com\r\nAccept-Encoding: identity\r\n"
                   b"X-Audit: provenance\r\n\r\n"),
    "py-http-03": b"DIRECT-PAYLOAD",
}


def strict_json(raw: bytes):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, "duplicate worker JSON field")
            out[k] = v
        return out
    def finite(x):
        raise ValueError("nonfinite worker JSON value")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=finite)


def verify_worker_payload(payload: dict, *, original_sha=ORIGINAL_SHA256) -> dict:
    require(isinstance(payload, dict) and payload.get("schema") == "hepta.original-cpython-http-execution-worker.v1"
            and payload.get("original_module_sha256") == original_sha
            and payload.get("isolated") is True
            and payload.get("network_calls_allowed") is False
            and payload.get("upstream_project_suite_executed") is False,
            "worker execution source/isolation truth not established")
    require(isinstance(payload.get("interpreter"), str) and payload["interpreter"].count(".") == 2,
            "bounded host interpreter identity missing")
    cases = payload.get("cases")
    require(isinstance(cases, list) and len(cases) == len(EXPECTED),
            "exact three-case original HTTP execution required")
    observed = []
    for i, (name, expected) in enumerate(EXPECTED.items()):
        row = cases[i]
        require(isinstance(row, dict) and set(row) == {"id", "captured_base64", "captured_sha256", "captured_bytes"}
                and row["id"] == name and type(row["captured_bytes"]) is int,
                "unexpected or reordered original HTTP behavior receipt")
        raw = base64.b64decode(row["captured_base64"], validate=True)
        require(raw == expected and row["captured_bytes"] == len(raw)
                and row["captured_sha256"] == hashlib.sha256(raw).hexdigest(),
                "independent HTTP bytes differ from original expected protocol")
        observed.append(dict(id=name, bytes=len(raw), stdout_sha256=digest(raw),
                             exact_http_behavior_passed=True))
    require(payload["interpreter"].split(".")[0] == "3",
            "Python 3 isolated worker required")
    return dict(interpreter_major=3, observations=observed)


def _resource_bounds():
    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def offline_original_execution(sources: tuple, *, worker_path: Path | None = None) -> dict:
    files, blobs = sources
    static = static_audit(sources)
    original = blobs.get(("python/cpython", ORIGINAL_PATH))
    require(isinstance(original, bytes) and digest(original) == ORIGINAL_SHA256,
            "fixed CPython implementation original bytes required")
    approved = next((f for f in files if f["repo"] == "python/cpython" and f["path"] == ORIGINAL_PATH), None)
    require(approved is not None and approved["partition"] == "evaluation"
            and approved["sha256"] == ORIGINAL_SHA256,
            "cross-file module from evaluation partition required")
    static_ids = {r["id"] for r in static["cases"] if r["repository_proxy"] == "python/cpython"}
    require(static_ids == set(EXPECTED), "cross-file CPython tests not provenance-bound")
    if worker_path is None:
        worker_path = Path(__file__).with_name("memory_original_http_worker.py")
    require(worker_path.is_file() and not worker_path.is_symlink()
            and 0 < worker_path.stat().st_size < 16 * 1024,
            "fixed bounded worker program required")
    worker_sha256 = digest(worker_path.read_bytes())
    require(worker_sha256 == WORKER_SHA256, "unregistered worker code changed")
    with tempfile.TemporaryDirectory(prefix="hepta-cpython-original-") as td:
        module = Path(td) / "pinned_original_cpython_http_client.py"
        module.write_bytes(original)
        argv = [sys.executable, "-I", "-S", "-B", str(worker_path.resolve()), str(module)]
        completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=12, cwd=td, check=False,
                                   preexec_fn=_resource_bounds)
    require(completed.returncode == 0 and completed.stderr == b""
            and 0 < len(completed.stdout) < 64 * 1024
            and completed.stdout.endswith(b"\n") and len(completed.stdout.splitlines()) == 1,
            "isolated original module failed or emitted ambiguous output")
    worker_payload = strict_json(completed.stdout)
    validated = verify_worker_payload(worker_payload)
    return dict(schema=SCHEMA, original_source_outer_zip_sha256=SOURCE_SHA,
                original_source_independent_reopen_zip_sha256=REOPEN_SHA,
                original_module_sha256=ORIGINAL_SHA256,
                original_crossfile_static_link_count=static["verified_cross_file_static_links"],
                original_cpython_crossfile_edges=len(EXPECTED),
                original_worker_code_sha256=worker_sha256,
                verified_case_outputs_sha256=digest(json.dumps(
                    validated["observations"], sort_keys=True, separators=(",", ":")
                ).encode()),
                isolated_python_major=validated["interpreter_major"],
                host_python_minor_version_not_precommitted=True,
                execution_subprocess_exit_code=completed.returncode,
                network_calls_allowed=False, original_cpython_module_loaded=True,
                actual_original_module_offline_behaviors=3,
                verified_behavior_receipts=validated["observations"],
                upstream_cpython_test_suite_executed=False,
                original_external_project_tests_executed=False,
                pretrained_reader_calls=0,
                cross_language_rust_execution_verified=False,
                independent_semantic_judge=False,
                prospective_evaluation_population=False,
                independent_host_execution_authenticated=False,
                lifecycle_tco=None, production_qualified=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-zip", type=Path, required=True)
    p.add_argument("--reopen-zip", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = offline_original_execution(real_source(args.source_zip, args.reopen_zip))
    write_once(args.output, json.dumps(report, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode() + b"\n")
    print(json.dumps(dict(actual_module_behaviors=3, full_upstream_suite=False,
                          new_model_calls=0, production_qualified=False), sort_keys=True))


if __name__ == "__main__":
    main()
