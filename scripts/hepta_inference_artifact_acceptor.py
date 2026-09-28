#!/usr/bin/env python3
"""Read-only verification of the immutable inference read-only matrix artifacts.

Run this verifier from an independently reviewed, trusted checkout. Candidate
archives are data: never extract them, import them or execute any file in them.
Artifact integrity is NOT independent proof of test execution or authorization
for activation. A same-UID candidate can fabricate its own recorder output.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_TAR_ENTRIES = 50_000
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
EXPECTED = {
    "01-state": ["python3", "scripts/hepta-inference-control-current-state.py", "check"],
    "02-actor": ["python3", "scripts/hepta-inference-control-actor-migrate.py", "check"],
    "03-regressions": ["python3", "-m", "unittest", "-v", "scripts.test_hepta_inference_hardening", "scripts.test_hepta_ci_source_identity"],
    "04-lane-b": ["python3", "scripts/hepta-lane-b-truth.py", "verify"],
    "05-maps": ["python3", "scripts/hepta-implementation-maps.py", "verify"],
    "06-metadata": ["cargo", "metadata", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "--format-version", "1"],
    "07-tests": ["cargo", "test", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-hepta-infer-core", "-p", "codex-hepta-infer-worker-host", "-p", "codex-hepta-types"],
    "08-crash": ["cargo", "test", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-hepta-infer-core", "--test", "process_crash_recovery", "--", "--test-threads=1"],
    "09-clippy": ["cargo", "clippy", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-hepta-infer-core", "-p", "codex-hepta-infer-worker-host", "-p", "codex-hepta-types", "--all-targets", "--all-features", "--", "-D", "warnings"],
    "10-format": ["cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--package", "codex-hepta-infer-core", "--package", "codex-hepta-infer-worker-host", "--package", "codex-hepta-types", "--", "--check"],
    "11-soak": ["cargo", "test", "--locked", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-hepta-infer-core", "post_compaction_multi_generation_curve", "--", "--ignored", "--nocapture", "--test-threads=1"],
}
TEST_COMMANDS = {"03-regressions", "07-tests", "08-crash", "11-soak"}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def object_id(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def load_json(data):
    value = json.loads(data, object_pairs_hook=pairs)
    need(isinstance(value, dict), "JSON object required")
    return value


def safe_name(name):
    need(isinstance(name, str) and name and "\\" not in name and "\0" not in name, "invalid archive name")
    path = PurePosixPath(name)
    need(not path.is_absolute() and all(part not in ("", ".", "..") for part in name.split("/")), "archive path escape")
    return path


def git_tree_from_archive(data, tested):
    """Recompute Git identity without materializing archive paths or symlinks."""
    root = {}
    seen = set()
    count = total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        need(archive.pax_headers.get("comment") == tested, "source archive commit identity")
        for member in archive:
            count += 1
            need(count <= MAX_TAR_ENTRIES, "source archive entry limit")
            path = safe_name(member.name.rstrip("/") if member.isdir() else member.name)
            key = str(path)
            need(key not in seen, "duplicate tar entry")
            seen.add(key)
            total += member.size
            need(0 <= member.size <= MAX_MEMBER_BYTES and total <= MAX_TOTAL_BYTES, "source archive byte limit")
            node = root
            for part in path.parts[:-1]:
                node = node.setdefault(part, {})
                need(isinstance(node, dict), "file/directory collision")
            leaf = path.name
            if member.isdir():
                need(isinstance(node.setdefault(leaf, {}), dict), "directory/file collision")
                continue
            need(leaf not in node, "duplicate source path")
            if member.issym():
                payload = member.linkname.encode("utf-8", errors="surrogateescape")
                need(len(payload) <= 4096, "symlink size limit")
                mode = "120000"
            else:
                need(member.isfile(), "unsupported source entry")
                handle = archive.extractfile(member)
                need(handle is not None, "missing tar member bytes")
                payload = handle.read(MAX_MEMBER_BYTES + 1)
                need(len(payload) == member.size, "truncated source member")
                mode = "100755" if member.mode & 0o111 else "100644"
            node[leaf] = (mode, object_id("blob", payload))

    def tree(node):
        entries = []
        for name, value in node.items():
            raw_name = name.encode("utf-8", errors="surrogateescape")
            if isinstance(value, dict):
                mode, digest, order = "40000", tree(value), raw_name + b"/"
            else:
                mode, digest = value
                order = raw_name
            entries.append((order, mode.encode() + b" " + raw_name + b"\0" + bytes.fromhex(digest)))
        return object_id("tree", b"".join(value for _, value in sorted(entries)))
    return tree(root)


def read_zip(path, expected_digest):
    need(path.is_file() and path.stat().st_size <= MAX_ZIP_BYTES, "ZIP size limit")
    data = path.read_bytes()
    need(bool(SHA256.fullmatch(expected_digest)) and sha256(data) == expected_digest, "ZIP digest mismatch")
    result = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        need(len(archive.infolist()) <= 256, "ZIP entry limit")
        for member in archive.infolist():
            name = member.filename
            safe_name(name)
            need(not member.is_dir() and not stat.S_ISLNK(member.external_attr >> 16), "unsupported ZIP member")
            need(not member.flag_bits & 1 and name not in result, "encrypted or duplicate ZIP member")
            total += member.file_size
            need(member.file_size <= MAX_MEMBER_BYTES and total <= MAX_TOTAL_BYTES, "ZIP byte limit")
            result[name] = archive.read(member)
    return result


def validate_bundle(files, *, lane, source, base, tested, tree, run_id, attempt):
    for value in (source, base, tested, tree):
        need(isinstance(value, str) and bool(SHA1.fullmatch(value)), "invalid Git identity")
    need(lane in {"source-head", "base-merge"}, "invalid lane")
    need(tested == source if lane == "source-head" else tested != source, "lane/tested mismatch")
    need(str(run_id).isdigit() and int(run_id) > 0 and str(attempt).isdigit() and int(attempt) > 0, "invalid run identity")
    need("source-input.tar.gz" in files and "toolchain.txt" in files, "missing source/toolchain artifact")
    need(git_tree_from_archive(files["source-input.tar.gz"], tested) == tree, "source archive tree mismatch")
    toolchain = files["toolchain.txt"].decode()
    need("rustc 1.95.0" in toolchain and "cargo 1.95.0" in toolchain, "wrong toolchain")
    for label in ("image_os=", "image_version=", "workflow_sha="):
        need(any(line.startswith(label) and line[len(label):].strip() for line in toolchain.splitlines()), "missing runner provenance")
    names = {"commands/" + name + ".json" for name in EXPECTED}
    actual = {name for name in files if name.startswith("commands/") and name.endswith(".json")}
    need(actual == names, "command inventory mismatch")
    records = []
    for name, command in EXPECTED.items():
        path = "commands/" + name + ".json"
        raw = files[path]
        record = load_json(raw)
        need(record.get("schema_version") == 1 and record.get("command") == command, "command/schema mismatch: " + name)
        for field, value in (("source_sha", source), ("tested_sha", tested), ("base_sha", base),
                             ("lane", lane), ("run_id", str(run_id)), ("run_attempt", str(attempt))):
            need(record.get(field) == value, "record identity mismatch: " + field)
        need(record.get("status") == "passed", "command did not pass: " + name)
        for field in ("exit_code", "command_exit_code", "returncode"):
            need(type(record.get(field)) is int and record[field] == 0, "command exit mismatch: " + field)
        need(record.get("timed_out") is False and record.get("output_limit_exceeded") is False, "incomplete command")
        need(type(record.get("observed_failed_tests")) is int and record["observed_failed_tests"] == 0, "failed-test count")
        if name in TEST_COMMANDS:
            need(type(record.get("observed_passed_tests")) is int and record["observed_passed_tests"] > 0, "zero-test execution")
        for snapshot in (record.get("before"), record.get("after")):
            need(isinstance(snapshot, dict), "missing source snapshot")
            need(snapshot.get("commit") == tested and snapshot.get("tree") == tree and snapshot.get("dirty") is False, "source mutation")
            if lane == "base-merge":
                need(snapshot.get("parents") == [base, source], "merge parent mismatch")
        need(record["before"] == record["after"], "source snapshot drift")
        start = datetime.fromisoformat(record["started_at"])
        end = datetime.fromisoformat(record["finished_at"])
        need(start.tzinfo is not None and end.tzinfo is not None and end >= start, "invalid command timestamps")
        elapsed = record.get("elapsed_seconds")
        need(type(elapsed) in (float, int) and 0 <= elapsed < 7200, "invalid command duration")
        log_name = record.get("log_file")
        need(isinstance(log_name, str) and "/" not in log_name and "\\" not in log_name, "invalid log name")
        safe_name(log_name)
        log = files.get("commands/" + log_name)
        need(isinstance(log, bytes), "missing command log")
        need(type(record.get("log_bytes")) is int and record["log_bytes"] == len(log), "log size mismatch")
        need(record.get("log_sha256") == sha256(log), "log digest mismatch")
        records.append({"name": name, "recordSha256": sha256(raw), "logSha256": sha256(log)})
    return {"schema": "hepta.inference-artifact-integrity.v1", "lane": lane,
            "sourceSha": source, "baseSha": base, "testedSha": tested, "tree": tree,
            "runId": str(run_id), "runAttempt": str(attempt), "commands": records,
            "artifactIntegrityVerified": True, "independentExecutionProved": False,
            "independentAcceptance": False, "activation": False, "release": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    for name in ("zip-sha256", "lane", "source", "base", "tested", "tree", "run-id", "attempt"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        files = read_zip(args.archive, args.zip_sha256)
        result = validate_bundle(files, lane=args.lane, source=args.source, base=args.base,
                                 tested=args.tested, tree=args.tree, run_id=args.run_id, attempt=args.attempt)
        result["zipSha256"] = args.zip_sha256
        result["checkedAt"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(result, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError, EOFError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise SystemExit("INFERENCE_ARTIFACT_REJECTED: " + str(exc)) from exc


if __name__ == "__main__":
    main()
