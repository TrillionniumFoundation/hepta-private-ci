#!/usr/bin/env python3
"""Authenticated, bounded cold-generation archive/restore for the existing owner.

This is trusted-host maintenance, not a second SQLite writer. Inputs and outputs
must be outside the live fleet. A pinned native cognitive-store checker verifies
both the archived and restored cold image against the independently signed cut.
No source, active pointer, historical row, backup or encryption key is deleted.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from lifecycle import canonical, digest, exact, identifier, integer, load_bounded
from lifecycle import no_duplicates, no_float, require, sha256, validate_trust, verify_signature

SCHEMA = "hepta.cognitive.cold-archive.v1"
PLAN_SCHEMA = "hepta.cognitive.archive-plan.v1"
DOMAIN = b"hepta.cognitive.cold-archive.v1\0"
CHUNK_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_VERIFIER_BYTES = 512 * 1024 * 1024
HEADER_KEYS = {"schema", "archive_plan_sha256", "owner_agent_id", "writer_generation",
               "anchor", "image_sha256", "image_bytes", "key_id", "key_sha256",
               "salt_hex", "chunk_bytes"}
PLAN_KEYS = {"schema", "request_id", "action", "owner_agent_id", "writer_generation", "anchor",
             "image_sha256", "image_bytes", "key_id", "key_sha256", "policy_sha256",
             "created_at", "expires_at", "input_path", "output_path", "live_fleet_root",
             "verifier_sha256", "archive_sha256"}


class OwnerCutRejected(ValueError):
    """The approved owner executed and returned an explicit current-cut denial."""


class PublicationIndeterminate(RuntimeError):
    """Publication may have occurred. Preserve its path and reconcile, never replay."""


def path_value(value: str) -> Path:
    require(isinstance(value, str) and 0 < len(value.encode()) <= 4096, "invalid bounded path")
    path = Path(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts,
            "path must be absolute and normalized")
    return path


def validate_anchor(value: dict, owner: str) -> None:
    exact(value, {"profile", "owner_agent_id", "schema_digest", "state_digest"})
    require(value["profile"] == "hepta:cognitive:exact-current-cut:v1" and
            value["owner_agent_id"] == owner, "unsupported or foreign owner cut")
    digest(value["schema_digest"])
    digest(value["state_digest"])


def validate_plan(plan: dict, now: int, *, require_live: bool = True) -> None:
    exact(plan, PLAN_KEYS)
    require(plan["schema"] == PLAN_SCHEMA and plan["action"] in {"archive", "restore"},
            "unsupported archive operation")
    identifier(plan["request_id"])
    require(str(uuid.UUID(plan["owner_agent_id"])) == plan["owner_agent_id"], "invalid Agent identity")
    integer(plan["writer_generation"])
    integer(plan["image_bytes"])
    require(plan["image_bytes"] <= MAX_IMAGE_BYTES, "cold image exceeds existing owner profile")
    integer(plan["created_at"])
    integer(plan["expires_at"])
    require(plan["created_at"] <= now and plan["created_at"] < plan["expires_at"],
            "archive plan is future or has an invalid validity interval")
    if require_live:
        require(now < plan["expires_at"], "archive plan is stale or future")
    validate_anchor(plan["anchor"], plan["owner_agent_id"])
    identifier(plan["key_id"])
    for key in ("image_sha256", "key_sha256", "policy_sha256", "verifier_sha256"):
        digest(plan[key])
    if plan["action"] == "archive":
        require(plan["archive_sha256"] is None, "new archive must not reuse an archive identity")
    else:
        digest(plan["archive_sha256"])
    source, destination, fleet = (path_value(plan[key]) for key in
                                   ("input_path", "output_path", "live_fleet_root"))
    require(fleet.resolve(strict=True) == fleet and fleet.is_dir(), "live fleet identity is redirected")
    require(source != destination and not source.is_relative_to(destination) and
            not destination.is_relative_to(source), "input/output paths overlap")
    for path in (source, destination):
        require(not path.is_relative_to(fleet) and not fleet.is_relative_to(path),
                "archive maintenance cannot read or publish inside the live fleet")


def identity(metadata: os.stat_result) -> tuple:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns)


@contextmanager
def read_file(path: Path, maximum: int, *, secret: bool = False):
    require(path.is_absolute() and path.resolve(strict=True) == path, "file path is redirected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                "file must be single-link and regular")
        require(before.st_size <= maximum and not (before.st_mode & 0o022),
                "file is oversized or writable by an untrusted group")
        if secret:
            require(before.st_mode & 0o077 == 0, "key must not be group/world accessible")
        yield stream
        require(identity(before) == identity(os.fstat(stream.fileno())), "file changed during read")
        current = os.stat(path, follow_symlinks=False)
        require(identity(before) == identity(current), "file path was replaced during read")


def read_bytes(path: Path, maximum: int, *, secret: bool = False) -> bytes:
    with read_file(path, maximum, secret=secret) as stream:
        content = stream.read(maximum + 1)
    require(len(content) <= maximum, "file exceeds byte budget")
    return content


def parse_json(content: bytes) -> object:
    return json.loads(content, object_pairs_hook=no_duplicates,
                      parse_float=no_float, parse_constant=no_float)


def private_parent(path: Path) -> Path:
    parent = path.parent
    require(parent.is_absolute() and parent.resolve(strict=True) == parent, "output parent is redirected")
    metadata = parent.stat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid() and
            metadata.st_mode & 0o077 == 0, "output parent must be an owned private directory")
    require(not os.path.lexists(path), "destination exists; reconcile it instead of replaying")
    return parent


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def hash_stream(stream) -> tuple[str, int]:
    hasher = hashlib.sha256()
    length = 0
    for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
        length += len(chunk)
        require(length <= MAX_VERIFIER_BYTES, "stream exceeds hash budget")
        hasher.update(chunk)
    return hasher.hexdigest(), length


def native_check(image: Path, anchor: dict, verifier: Path, expected_binary_sha256: str) -> None:
    """Execute the exact retained Linux ELF descriptor, not a subsequently resolved path."""
    require(sys.platform == "linux", "native archive verifier requires the qualified Linux profile")
    with read_file(verifier, MAX_VERIFIER_BYTES) as executable:
        require(executable.read(4) == b"\x7fELF", "owner verifier must be a native ELF executable")
        executable.seek(0)
        binary_digest, _ = hash_stream(executable)
        require(binary_digest == expected_binary_sha256, "owner verifier binary is not the approved artifact")
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            result = subprocess.run(
                [f"/proc/self/fd/{executable.fileno()}", "--image", str(image)],
                input=canonical(anchor), stdout=output, stderr=errors,
                pass_fds=(executable.fileno(),), timeout=300, check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
            require(result.returncode in {0, 2}, "native owner verification did not execute successfully")
            require(output.tell() <= 16384, "native owner report exceeds bounds")
            output.seek(0)
            report = parse_json(output.read(16385))
    if result.returncode == 2:
        exact(report, {"schema", "disposition", "write_authority"})
        require(report["schema"] == "hepta.cognitive.archive-owner-check.v1" and
                report["disposition"] == "access_denied" and report["write_authority"] is False,
                "native failure is not an authenticated current-cut denial")
        raise OwnerCutRejected("native owner explicitly rejected the requested current cut")
    exact(report, {"schema", "anchor", "exact_cut_verified", "write_authority"})
    require(report["schema"] == "hepta.cognitive.archive-owner-check.v1" and
            report["anchor"] == anchor and report["exact_cut_verified"] is True and
            report["write_authority"] is False, "native owner verification report does not match")


def derived_cipher(key: bytes, header: dict) -> AESGCM:
    # A fresh 256-bit archive salt derives a separate key. Segment nonces are
    # unique counters within that key and never depend on caller-supplied text.
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=bytes.fromhex(header["salt_hex"]),
                   info=DOMAIN + bytes.fromhex(sha256(header))).derive(key)
    return AESGCM(derived)


def associated_data(header: dict, index: int, length: int) -> bytes:
    return DOMAIN + bytes.fromhex(sha256(header)) + struct.pack(">QQ", index, length)


def source_header(plan: dict) -> dict:
    return {"schema": SCHEMA, "archive_plan_sha256": sha256(plan),
            **{key: plan[key] for key in ("owner_agent_id", "writer_generation", "anchor",
                                         "image_sha256", "image_bytes", "key_id", "key_sha256")},
            "salt_hex": os.urandom(32).hex(), "chunk_bytes": CHUNK_BYTES}


def validate_manifest(manifest: dict, plan: dict) -> dict:
    exact(manifest, {"header", "segments"})
    header = manifest["header"]
    exact(header, HEADER_KEYS)
    require(header["schema"] == SCHEMA and type(header["chunk_bytes"]) is int and
            header["chunk_bytes"] == CHUNK_BYTES, "unsupported archive framing")
    integer(header["writer_generation"])
    integer(header["image_bytes"])
    validate_anchor(header["anchor"], header["owner_agent_id"])
    digest(header["salt_hex"])
    digest(header["archive_plan_sha256"])
    for key in ("owner_agent_id", "writer_generation", "anchor", "image_sha256", "image_bytes",
                "key_id", "key_sha256"):
        require(header[key] == plan[key], "archive differs from current restore authority")
    segments = manifest["segments"]
    count = (plan["image_bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES
    require(isinstance(segments, list) and len(segments) == count, "missing or excessive archive segments")
    seen = set()
    for index, segment in enumerate(segments):
        exact(segment, {"index", "plaintext_bytes", "ciphertext_sha256"})
        require(type(segment["index"]) is int and segment["index"] == index, "segment ordering changed")
        expected = min(CHUNK_BYTES, plan["image_bytes"] - index * CHUNK_BYTES)
        require(type(segment["plaintext_bytes"]) is int and segment["plaintext_bytes"] == expected,
                "segment length changed")
        digest(segment["ciphertext_sha256"])
        require(segment["ciphertext_sha256"] not in seen, "duplicate ciphertext identity")
        seen.add(segment["ciphertext_sha256"])
    return header


def load_key(path: Path, plan: dict) -> bytes:
    key = read_bytes(path, 32, secret=True)
    require(len(key) == 32 and hashlib.sha256(key).hexdigest() == plan["key_sha256"],
            "encryption key does not match the independently authorized key")
    require(not path.is_relative_to(path_value(plan["live_fleet_root"])), "key is in the rollback domain")
    return key


def copy_cold_image(source: Path, target: Path, plan: dict) -> None:
    # Even an empty sidecar is rejected: the owner must first produce a cold,
    # checkpointed image. This tool never checkpoints or repairs a live store.
    for suffix in ("-wal", "-shm", "-journal"):
        require(not os.path.lexists(Path(str(source) + suffix)), "source has SQLite sidecars")
    hasher = hashlib.sha256()
    length = 0
    with read_file(source, plan["image_bytes"]) as original, target.open("xb") as staged:
        os.fchmod(staged.fileno(), 0o600)
        for chunk in iter(lambda: original.read(CHUNK_BYTES), b""):
            length += len(chunk)
            require(length <= plan["image_bytes"], "source grew beyond authorized size")
            hasher.update(chunk)
            staged.write(chunk)
        staged.flush()
        os.fsync(staged.fileno())
    require(length == plan["image_bytes"] and hasher.hexdigest() == plan["image_sha256"],
            "source bytes differ from independently authenticated checkpoint")
    for suffix in ("-wal", "-shm", "-journal"):
        require(not os.path.lexists(Path(str(source) + suffix)), "source became live during staging")


def make_archive(plan: dict, key: bytes, verifier: Path, reauthorize) -> dict:
    source, destination = path_value(plan["input_path"]), path_value(plan["output_path"])
    parent = private_parent(destination)
    with tempfile.TemporaryDirectory(prefix=".cognitive-archive-stage-", dir=parent) as temporary:
        staged = Path(temporary) / "cognitive_1.sqlite3"
        copy_cold_image(source, staged, plan)
        native_check(staged, plan["anchor"], verifier, plan["verifier_sha256"])
        reauthorize()
        # Reserve the output name without overwriting an older operation. A
        # partial directory remains evidence, but has no committed manifest.
        destination.mkdir(mode=0o700)
        header = source_header(plan)
        cipher = derived_cipher(key, header)
        segments = []
        encrypted_source_digest = hashlib.sha256()
        with staged.open("rb") as stream:
            for index in range((plan["image_bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES):
                chunk = stream.read(CHUNK_BYTES)
                encrypted_source_digest.update(chunk)
                encrypted = cipher.encrypt(index.to_bytes(12, "big"), chunk,
                                           associated_data(header, index, len(chunk)))
                encrypted_digest = hashlib.sha256(encrypted).hexdigest()
                write_new(destination / encrypted_digest, encrypted)
                segments.append({"index": index, "plaintext_bytes": len(chunk),
                                 "ciphertext_sha256": encrypted_digest})
        require(encrypted_source_digest.hexdigest() == plan["image_sha256"], "staged image changed during encryption")
        manifest = {"header": header, "segments": segments}
        validate_manifest(manifest, plan)
        reauthorize()
        try:
            write_new(destination / "manifest.json", canonical(manifest))
            sync_directory(destination)
            sync_directory(parent)
        except OSError as error:
            raise PublicationIndeterminate("archive commit durability unknown; preserve destination") from error
    return {"archive_sha256": sha256(manifest), "segments": len(segments), "result": "archived"}


@contextmanager
def archive_directory(source: Path):
    require(source.is_absolute() and source.resolve(strict=True) == source,
            "archive path is redirected")
    descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISDIR(before.st_mode) and not before.st_mode & 0o022,
                "archive directory is not a protected directory")
        yield
        require(source.resolve(strict=True) == source and
                identity(before) == identity(os.fstat(descriptor)) ==
                identity(source.stat(follow_symlinks=False)),
                "archive directory changed during verification")
    finally:
        os.close(descriptor)


def decode_archive_image(source: Path, staged: Path, plan: dict, key: bytes,
                         verifier: Path) -> dict:
    """Shared cold-image oracle for restore AND acknowledgement-loss observation.

    Writes only a fresh private scratch image. Never publishes a destination,
    repairs an archive, or interprets missing content as proof of non-execution.
    """
    with archive_directory(source):
        manifest_bytes = read_bytes(source / "manifest.json", MAX_MANIFEST_BYTES)
        manifest = parse_json(manifest_bytes)
        require(canonical(manifest) == manifest_bytes, "archive manifest is not canonical")
        header = validate_manifest(manifest, plan)
        if plan["action"] == "archive":
            require(header["archive_plan_sha256"] == sha256(plan),
                    "archive belongs to another original operation")
        else:
            require(sha256(manifest) == plan["archive_sha256"],
                    "archive manifest differs from independently retained digest")
        expected_names = {"manifest.json", *(item["ciphertext_sha256"] for item in manifest["segments"])}
        observed_names = set()
        with os.scandir(source) as entries:
            for entry in entries:
                require(len(observed_names) < len(expected_names) and entry.name in expected_names and
                        entry.is_file(follow_symlinks=False), "archive contains unregistered files")
                observed_names.add(entry.name)
        require(observed_names == expected_names, "archive inventory is incomplete")
        cipher = derived_cipher(key, header)
        hasher = hashlib.sha256()
        with staged.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            for segment in manifest["segments"]:
                content = read_bytes(source / segment["ciphertext_sha256"], CHUNK_BYTES + 16)
                require(hashlib.sha256(content).hexdigest() == segment["ciphertext_sha256"],
                        "archive segment digest mismatch")
                index, length = segment["index"], segment["plaintext_bytes"]
                require(len(content) == length + 16, "ciphertext framing mismatch")
                plain = cipher.decrypt(index.to_bytes(12, "big"), content,
                                       associated_data(header, index, length))
                hasher.update(plain)
                stream.write(plain)
            stream.flush()
            os.fsync(stream.fileno())
        require(staged.stat().st_size == plan["image_bytes"] and
                hasher.hexdigest() == plan["image_sha256"], "restored bytes differ from checkpoint")
        native_check(staged, plan["anchor"], verifier, plan["verifier_sha256"])
    return manifest


def restore_archive(plan: dict, key: bytes, verifier: Path, reauthorize) -> dict:
    source, destination = path_value(plan["input_path"]), path_value(plan["output_path"])
    parent = private_parent(destination)
    with tempfile.TemporaryDirectory(prefix=".cognitive-restore-stage-", dir=parent) as temporary:
        staged = Path(temporary) / "cognitive_1.sqlite3"
        manifest = decode_archive_image(source, staged, plan, key, verifier)
        reauthorize()
        try:
            # link is an atomic no-replace publication on the same filesystem.
            # Remove only our private staging link, NEVER an existing output.
            os.link(staged, destination, follow_symlinks=False)
            staged.unlink()
            sync_directory(parent)
        except FileExistsError:
            raise
        except OSError as error:
            raise PublicationIndeterminate("restore publication durability unknown; preserve destination") from error
    return {"archive_sha256": plan["archive_sha256"], "segments": len(manifest["segments"]),
            "result": "restored_cold_image"}


def authorize(plan_path: Path, trust_path: Path, expected_plan: str, expected_trust: str,
              *, observation_path: Path | None = None, expected_observation: str | None = None) -> dict:
    now = int(time.time())
    trust = load_bounded(trust_path)
    digest(expected_plan)
    digest(expected_trust)
    require(sha256(trust) == expected_trust, "host trust digest changed")
    validate_trust(trust, now)
    plan = verify_signature(load_bounded(plan_path), trust["coordinator"])
    require(sha256(plan) == expected_plan, "signed plan differs from requested archive operation")
    # Historical truth is inspected only under a separately signed, currently
    # live observation request. Expired operation authority is never renewed by
    # a flag, by its own signature, or by finding an apparently valid output.
    require((observation_path is None) == (expected_observation is None),
            "observation plan and its independently retained digest must be supplied together")
    if observation_path is not None:
        from archive_observation import validate_observation
        digest(expected_observation)
        observation = verify_signature(load_bounded(observation_path), trust["coordinator"])
        require(sha256(observation) == expected_observation, "observation differs from requested operation")
        validate_observation(observation, plan, now)
    validate_plan(plan, now, require_live=observation_path is None)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--trusted-owners", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-trust-sha256", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--owner-verifier", type=Path, required=True)
    parser.add_argument("--reconcile-plan", type=Path)
    parser.add_argument("--expected-reconcile-plan-sha256")
    args = parser.parse_args()
    require(sys.platform == "linux", "archive operations require the Linux descriptor profile")
    def reauthorize():
        return authorize(args.plan, args.trusted_owners,
                         args.expected_plan_sha256, args.expected_trust_sha256,
                         observation_path=args.reconcile_plan,
                         expected_observation=args.expected_reconcile_plan_sha256)
    plan = reauthorize()
    key = load_key(args.key_file, plan)
    if args.reconcile_plan is not None:
        from archive_observation import observe_publication
        # authorize already authenticated this exact signed observation. Reread
        # and compare again; do not use an unbound scratch-path replacement.
        observation = load_bounded(args.reconcile_plan)["payload"]
        require(sha256(observation) == args.expected_reconcile_plan_sha256,
                "observation changed before use")
        report = observe_publication(plan, observation, key, args.owner_verifier, reauthorize)
        print(json.dumps(report, sort_keys=True))
        if not report["artifact_verified"]:
            raise SystemExit(3)
        return
    operation = make_archive if plan["action"] == "archive" else restore_archive
    report = operation(plan, key, args.owner_verifier, reauthorize)
    print(json.dumps({"schema": "hepta.cognitive.archive-operation-report.v1",
                      "plan_sha256": sha256(plan), "anchor": plan["anchor"], **report,
                      "source_preserved": True, "grants_authority": False,
                      "production_activated": False, "physical_erasure_proved": False,
                      "hot_history_pruned": False, "target_host_qualified": False}, sort_keys=True))


if __name__ == "__main__":
    # The observation helper must share this module's typed owner-denial error,
    # including when the entrypoint was invoked as a script rather than imported.
    sys.modules.setdefault("archive", sys.modules[__name__])
    try:
        main()
    except OwnerCutRejected:
        print(json.dumps({"schema": "hepta.cognitive.archive-operation-report.v1",
                          "result": "owner_cut_rejected", "grants_authority": False}))
        raise SystemExit(2)
