#!/usr/bin/env python3
"""Bounded, checksum-verified NDU evidence transport. No activation authority.

A checksum is integrity, not independent acceptance. Aggregate only receipts
from a trusted Actions run. Live projection histories must never be truncated.
"""
from __future__ import annotations
import argparse
import base64
import gzip
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile

MANIFEST = "evidence-manifest.json"
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 2048
SUITES = {"source", "core", "callers", "product", "lint", "host"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bounded_read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > MAX_FILE:
            raise ValueError("unsafe or oversized evidence file")
        data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise ValueError("evidence grew beyond bound")
        return data


def inventory(root: Path) -> dict[str, dict]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence root must be a real directory")
    files = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in evidence")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if name == MANIFEST:
            continue
        data = bounded_read(path)
        total += len(data)
        if total > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError("evidence envelope capacity")
        files[name] = {"bytes": len(data), "sha256": digest(data)}
    if not files:
        raise ValueError("empty evidence")
    return files


def seal(root: Path) -> dict:
    record = {"schema": "hepta.ndu.evidence-manifest.v1", "files": inventory(root)}
    with (root / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return record


def verify(root: Path) -> dict:
    record = json.loads(bounded_read(root / MANIFEST))
    if record.get("schema") != "hepta.ndu.evidence-manifest.v1" or record.get("files") != inventory(root):
        raise ValueError("evidence checksum, size or closed-world inventory mismatch")
    return record


def trusted_runner():
    # The publisher executes its trusted workflow revision, never downloaded
    # candidate code. This imports only the checked-in qualification contract.
    spec = importlib.util.spec_from_file_location("ndu_evidence_runner", Path(__file__).with_name("hepta-ndu-qualification.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_commands(suite: str, sha: str, tree: str) -> dict:
    return {name: command for name, _, command in trusted_runner().commands(suite, sha, tree)}


def canonical_command(command: list) -> list:
    if not isinstance(command, list) or not all(isinstance(value, str) for value in command):
        raise ValueError("command must be an argument vector")
    # Only the two literal checkout-derived target paths vary between hosts.
    endings = ("/codex-rs/target", "/codex-rs/target/release/ndu-mounted-filesystem-qualification")
    return ["<checkout>" + next(end for end in endings if arg.endswith(end))
            if arg.startswith("/") and any(arg.endswith(end) for end in endings) else arg
            for arg in command]


def aggregate(root: Path, source: str, base: str, merge: str) -> dict:
    if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (source, base, merge)):
        raise ValueError("full Git identities required")
    observed = {}
    for receipt_path in root.rglob("suite-receipt.json"):
        verify(receipt_path.parent)
        receipt = json.loads(bounded_read(receipt_path))
        key = (receipt.get("lane"), receipt.get("suite"))
        if key in observed or key[0] not in {"source-head", "synthetic-merge"} or key[1] not in SUITES:
            raise ValueError("duplicate or foreign qualification suite")
        expected = source if key[0] == "source-head" else merge
        if receipt.get("schema") != "hepta.ndu.suite-receipt.v1" or receipt.get("sourceSha") != expected or receipt.get("passed") is not True or receipt.get("sourceUnchanged") is not True:
            raise ValueError("unpassed or wrong-source qualification")
        if re.fullmatch(r"[0-9a-f]{40}", receipt.get("sourceTree", "")) is None:
            raise ValueError("missing source tree")
        if key[0] == "synthetic-merge" and receipt.get("parents") != [base, source]:
            raise ValueError("wrong synthetic parents")
        commands = receipt.get("commands")
        if not isinstance(commands, list) or not commands or any(type(item.get("exitCode")) is not int or item["exitCode"] != 0 for item in commands):
            raise ValueError("unexecuted or failed commands")
        expected_commands_by_name = expected_commands(key[1], expected, receipt["sourceTree"])
        if len(commands) != len(expected_commands_by_name) or {item.get("name") for item in commands} != set(expected_commands_by_name):
            raise ValueError("qualification command coverage mismatch")
        for item in commands:
            if canonical_command(item.get("command")) != canonical_command(expected_commands_by_name[item["name"]]):
                raise ValueError("qualification command or strict-filter substitution")
            log = item.get("log", "")
            if Path(log).name != log or not log or digest(bounded_read(receipt_path.parent / log)) != item.get("logSha256"):
                raise ValueError("missing or substituted command log")
        if key[1] == "host":
            host = receipt.get("hostReceipt") or {}
            mounted = receipt.get("mountedFilesystemReceipt") or {}
            if host.get("identityValidated") is not True or host.get("performancePassed") is not True or mounted.get("identityValidated") is not True:
                raise ValueError("missing validated native host observations")
            host_id = receipt.get("host")
            if not isinstance(host_id, str) or not host_id or len(host_id) > 256:
                raise ValueError("missing execution host identity")
            # Re-read native bytes with trusted validation, including numerical
            # SLO thresholds. A summary's true bits and a resealed digest are
            # not a substitute for the observed full-envelope/fault records.
            runner = trusted_runner()
            actual_host = runner.validate_host_receipt(receipt_path.parent / "named-host.json", expected, receipt["sourceTree"], key[0], expected_host=host_id)
            actual_mounted = runner.validate_mounted_receipt(receipt_path.parent / "mounted-filesystem/mounted-filesystem.json", expected, receipt["sourceTree"], key[0], expected_host=host_id)
            if actual_host != host or actual_mounted != mounted:
                raise ValueError("native evidence digest or observed result substitution")
        observed[key] = receipt
    if set(observed) != {(lane, suite) for lane in ("source-head", "synthetic-merge") for suite in SUITES}:
        raise ValueError("all twelve independently executed suites are required")
    for lane in ("source-head", "synthetic-merge"):
        if len({observed[(lane, suite)]["sourceTree"] for suite in SUITES}) != 1:
            raise ValueError("suite source tree drift")
    return {"schema": "hepta.ndu.aggregate-evidence.v1", "sourceSha": source, "baseSha": base, "mergeSha": merge, "passed": True, "productionActivation": False, "suites": [observed[key] for key in sorted(observed)]}


def pack(root: Path, output: Path) -> None:
    record = verify(root)
    if output.resolve() == root.resolve() or root.resolve() in output.resolve().parents:
        raise ValueError("archive must be outside evidence root")
    with output.open("xb") as out, gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w|") as archive:
        for name in sorted(set(record["files"]) | {MANIFEST}):
            data = bounded_read(root / name)
            if name != MANIFEST and digest(data) != record["files"][name]["sha256"]:
                raise ValueError("evidence changed during archive")
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o600, 0
            archive.addfile(info, io.BytesIO(data))


def aws(*args: str) -> dict:
    result = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout)


def publish(path: Path, bucket: str, key: str, kms: str, account: str) -> dict:
    if not re.fullmatch(r"[0-9]{12}", account) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or not re.fullmatch(r"ndu-evidence/[a-z0-9/_.-]{1,512}", key) or not re.fullmatch(r"arn:aws:kms:[a-z0-9-]+:" + account + r":key/[a-zA-Z0-9-]+", kms):
        raise ValueError("explicit approved account/bucket/key/KMS ARN required")
    data = bounded_read(path)
    sha = digest(data)
    if aws("sts", "get-caller-identity").get("Account") != account:
        raise ValueError("unexpected AWS account")
    if aws("s3api", "get-bucket-versioning", "--bucket", bucket, "--expected-bucket-owner", account).get("Status") != "Enabled":
        raise ValueError("versioned evidence bucket required")
    reconciled = False
    try:
        result = aws("s3api", "put-object", "--bucket", bucket, "--key", key, "--body", str(path), "--if-none-match", "*", "--server-side-encryption", "aws:kms", "--ssekms-key-id", kms, "--checksum-algorithm", "SHA256", "--checksum-sha256", base64.b64encode(bytes.fromhex(sha)).decode(), "--expected-bucket-owner", account)
        version = result.get("VersionId")
    except (OSError, subprocess.SubprocessError, ValueError):
        # A timeout or 412 does not prove absence. Never issue an unconditional
        # overwrite or another PUT in this invocation. Reconcile the exact key
        # and read an identified version; only byte-for-byte success can settle.
        version = None
    if not isinstance(version, str) or not version or version == "null":
        try:
            head = aws("s3api", "head-object", "--bucket", bucket, "--key", key, "--expected-bucket-owner", account)
            version = head.get("VersionId")
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise RuntimeError("NDU-PUB-003: publication outcome unresolved; preserve the same key and bytes") from error
        if not isinstance(version, str) or not version or version == "null":
            raise RuntimeError("NDU-PUB-003: no identified version to reconcile")
        reconciled = True
    # A fixed .readback name made even successful retries fail after a prior
    # readback. Private per-attempt space also avoids aliasing another attempt.
    with tempfile.TemporaryDirectory(prefix="ndu-readback-", dir=path.parent) as temporary:
        target = Path(temporary) / "version"
        result = aws("s3api", "get-object", "--bucket", bucket, "--key", key, "--version-id", version, "--expected-bucket-owner", account, str(target))
        if digest(bounded_read(target)) != sha or result.get("VersionId") != version or result.get("ServerSideEncryption") != "aws:kms" or result.get("SSEKMSKeyId") != kms:
            raise ValueError("NDU-PUB-004: versioned KMS readback conflicts with requested bytes or identity")
    # Version identity and readback do not establish Object Lock/retention.
    return {"schema": "hepta.ndu.evidence-publication.v1", "bucket": bucket, "key": key, "versionId": version, "sha256": sha, "kmsKeyArn": kms, "readbackVerified": True, "reconciledExistingVersion": reconciled, "productionActivation": False}



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["seal", "verify", "aggregate", "pack", "publish"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source")
    parser.add_argument("--base")
    parser.add_argument("--merge")
    args = parser.parse_args()
    if args.operation == "seal": result = seal(args.root)
    elif args.operation == "verify": result = verify(args.root)
    elif args.operation == "aggregate": result = aggregate(args.root, args.source, args.base, args.merge)
    elif args.operation == "pack":
        if args.output is None: parser.error("--output required")
        pack(args.root, args.output)
        return
    else:
        result = publish(args.root, os.environ.get("NDU_EVIDENCE_BUCKET", ""), os.environ.get("NDU_EVIDENCE_KEY", ""), os.environ.get("NDU_EVIDENCE_KMS_ARN", ""), os.environ.get("NDU_EVIDENCE_ACCOUNT", ""))
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream: json.dump(result, stream, indent=2); stream.write("\n")
    else: print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
