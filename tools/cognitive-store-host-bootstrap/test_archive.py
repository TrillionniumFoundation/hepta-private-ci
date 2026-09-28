#!/usr/bin/env python3
"""Real Ed25519/HKDF/AEAD and filesystem tests; protocol tests stub only the owner.

--owner-image additionally exercises the actual Cargo-built owner checker, invoked
by the Rust integration test. No private key or fixture receipt is production evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import archive
import lifecycle

OWNER = "00000000-0000-4000-8000-00000000ca81"


def signed(payload, key):
    result = {"payload": payload, "signer_id": "coordinator", "key_epoch": 1}
    result["signature_hex"] = key.sign(lifecycle.signing_bytes(result)).hex()
    return result


def public(key, name):
    return {"signer_id": name, "key_epoch": 1, "revoked": False,
            "public_key_hex": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()}


def fixture(root, image=None, anchor=None, verifier=None):
    source = root / "cognitive_1.sqlite3"
    source.write_bytes(image or (b"secret-history-and-tombstone" * 40970 + b"tail"))
    source.chmod(0o600)
    fleet = root / "live-fleet"
    fleet.mkdir(mode=0o700)
    key = os.urandom(32)
    key_file = root / "key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    now = int(time.time())
    signer = Ed25519PrivateKey.generate()
    trust = {"schema": "hepta.cognitive.lifecycle-trust.v1", "revision": 1, "valid_until": now + 3600,
             "coordinator": public(signer, "coordinator"),
             "owners": [public(Ed25519PrivateKey.generate(), "storage-owner")]}
    plan = {"schema": archive.PLAN_SCHEMA, "request_id": "archive-test-1", "action": "archive",
            "owner_agent_id": OWNER if anchor is None else anchor["owner_agent_id"], "writer_generation": 1,
            "anchor": anchor or {"profile": "hepta:cognitive:exact-current-cut:v1", "owner_agent_id": OWNER,
                                  "schema_digest": "a" * 64, "state_digest": "b" * 64},
            "image_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "image_bytes": source.stat().st_size,
            "key_id": "external-archive-key", "key_sha256": hashlib.sha256(key).hexdigest(),
            "policy_sha256": "c" * 64, "created_at": now - 1, "expires_at": now + 1800,
            "input_path": str(source), "output_path": str(root / "archive"), "live_fleet_root": str(fleet),
            "verifier_sha256": "d" * 64 if verifier is None else hashlib.sha256(verifier.read_bytes()).hexdigest(),
            "archive_sha256": None}
    trust_path, plan_path = root / "trust.json", root / "plan.json"
    trust_path.write_bytes(lifecycle.canonical(trust))
    plan_path.write_bytes(lifecycle.canonical(signed(plan, signer)))
    return source, key, key_file, signer, trust, trust_path, plan, plan_path


def restore_plan(plan, receipt, root):
    result = copy.deepcopy(plan)
    result.update(action="restore", request_id="restore-test-1", input_path=plan["output_path"],
                  output_path=str(root / "restored.sqlite3"), archive_sha256=receipt["archive_sha256"])
    return result


class ArchiveProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.source, self.key, self.key_file, self.signer, self.trust, self.trust_path,
         self.plan, self.plan_path) = fixture(self.root)
        self.owner = mock.patch.object(archive, "native_check", autospec=True)
        self.checker = self.owner.start()
        self.addCleanup(self.owner.stop)
        self.verifier = self.root / "unused-owner-binary"

    def authorize(self):
        return archive.authorize(self.plan_path, self.trust_path, lifecycle.sha256(self.plan),
                                 lifecycle.sha256(self.trust))

    def create(self):
        self.authorize()
        return archive.make_archive(self.plan, self.key, self.verifier, self.authorize)

    def restore(self, receipt, *, plan=None, key=None, reauthorize=None):
        plan = plan or restore_plan(self.plan, receipt, self.root)
        return archive.restore_archive(plan, key or self.key, self.verifier, reauthorize or (lambda: None))

    def manifest(self):
        path = self.root / "archive" / "manifest.json"
        return path, json.loads(path.read_bytes())

    def rewrite_manifest(self, data):
        path, _ = self.manifest()
        path.write_bytes(lifecycle.canonical(data))
        return {"archive_sha256": lifecycle.sha256(data)}

    def test_archive_restore_preserves_all_bytes_and_source(self):
        original = self.source.read_bytes()
        receipt = self.create()
        restored = self.restore(receipt)
        self.assertEqual(restored["result"], "restored_cold_image")
        self.assertEqual((self.root / "restored.sqlite3").read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertGreater(receipt["segments"], 1)
        self.assertEqual(self.checker.call_count, 2)
        self.assertEqual((self.root / "restored.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_published_segments_do_not_contain_plaintext(self):
        self.create()
        for path in (self.root / "archive").iterdir():
            self.assertNotIn(b"secret-history-and-tombstone", path.read_bytes())

    def test_real_signed_plan_and_key_load(self):
        self.assertEqual(self.authorize(), self.plan)
        self.assertEqual(archive.load_key(self.key_file, self.plan), self.key)

    def test_signature_drift_is_rejected(self):
        envelope = json.loads(self.plan_path.read_bytes())
        envelope["payload"]["request_id"] = "tampered"
        self.plan_path.write_bytes(lifecycle.canonical(envelope))
        with self.assertRaises(ValueError):
            self.authorize()
        self.assertFalse((self.root / "archive").exists())

    def test_wrong_requested_plan_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            archive.authorize(self.plan_path, self.trust_path, "e" * 64, lifecycle.sha256(self.trust))

    def test_trust_replacement_is_rejected(self):
        changed = copy.deepcopy(self.trust)
        changed["revision"] += 1
        self.trust_path.write_bytes(lifecycle.canonical(changed))
        with self.assertRaises(ValueError):
            self.authorize()

    def test_revoked_coordinator_is_rejected_even_with_current_pin(self):
        self.trust["coordinator"]["revoked"] = True
        self.trust_path.write_bytes(lifecycle.canonical(self.trust))
        with self.assertRaises(ValueError):
            self.authorize()

    def test_expired_plan_is_rejected(self):
        with mock.patch.object(archive.time, "time", return_value=self.plan["expires_at"]):
            with self.assertRaises(ValueError):
                self.authorize()

    def test_final_revocation_prevents_manifest_publication(self):
        checks = 0
        def reauthorize():
            nonlocal checks
            checks += 1
            if checks == 2:
                raise ValueError("revoked before publication")
        with self.assertRaisesRegex(ValueError, "revoked"):
            archive.make_archive(self.plan, self.key, self.verifier, reauthorize)
        self.assertTrue((self.root / "archive").is_dir())
        self.assertFalse((self.root / "archive" / "manifest.json").exists())

    def test_native_owner_rejection_prevents_output(self):
        self.checker.side_effect = ValueError("stale current cut")
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse((self.root / "archive").exists())

    def test_staged_image_change_before_encryption_is_detected(self):
        def corrupt(image, *args):
            with image.open("r+b") as stream:
                stream.write(b"WRONG")
        self.checker.side_effect = corrupt
        with self.assertRaisesRegex(ValueError, "during encryption"):
            self.create()
        self.assertFalse((self.root / "archive" / "manifest.json").exists())

    def test_source_digest_mismatch_prevents_output(self):
        self.source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse((self.root / "archive").exists())

    def test_source_growth_rejected_before_copy(self):
        self.source.write_bytes(self.source.read_bytes() + b"x")
        with self.assertRaises(ValueError):
            self.create()

    def test_even_empty_wal_shm_journal_rejected(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                path = Path(str(self.source) + suffix)
                path.touch()
                with self.assertRaises(ValueError):
                    self.create()
                path.unlink()

    def test_source_symlink_rejected(self):
        original = self.root / "original"
        self.source.rename(original)
        self.source.symlink_to(original)
        with self.assertRaises(ValueError):
            self.create()

    def test_source_hardlink_rejected(self):
        os.link(self.source, self.root / "other-link")
        with self.assertRaises(ValueError):
            self.create()

    def test_fifo_rejected_without_blocking(self):
        self.source.unlink()
        os.mkfifo(self.source, 0o600)
        with self.assertRaises(ValueError):
            self.create()

    def test_key_mode_and_key_identity_are_enforced(self):
        self.key_file.chmod(0o644)
        with self.assertRaises(ValueError):
            archive.load_key(self.key_file, self.plan)
        self.key_file.chmod(0o600)
        self.key_file.write_bytes(b"z" * 32)
        with self.assertRaises(ValueError):
            archive.load_key(self.key_file, self.plan)

    def test_key_size_is_bounded(self):
        self.key_file.write_bytes(b"k" * 33)
        with self.assertRaises(ValueError):
            archive.load_key(self.key_file, self.plan)

    def test_duplicate_archive_does_not_overwrite_or_replay(self):
        first = self.create()
        manifest_before = (self.root / "archive" / "manifest.json").read_bytes()
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(manifest_before, (self.root / "archive" / "manifest.json").read_bytes())
        self.assertEqual(first["archive_sha256"], hashlib.sha256(manifest_before).hexdigest())

    def test_restore_never_overwrites_existing_destination(self):
        receipt = self.create()
        destination = self.root / "restored.sqlite3"
        destination.write_bytes(b"existing authoritative object")
        with self.assertRaises(ValueError):
            self.restore(receipt)
        self.assertEqual(destination.read_bytes(), b"existing authoritative object")

    def test_corrupt_ciphertext_prevents_restore_publication(self):
        receipt = self.create()
        _, manifest = self.manifest()
        path = self.root / "archive" / manifest["segments"][0]["ciphertext_sha256"]
        content = bytearray(path.read_bytes())
        content[0] ^= 1
        path.write_bytes(content)
        with self.assertRaises(ValueError):
            self.restore(receipt)
        self.assertFalse((self.root / "restored.sqlite3").exists())

    def test_aead_rejects_rehashed_tampered_ciphertext(self):
        self.create()
        _, manifest = self.manifest()
        item = manifest["segments"][0]
        old = self.root / "archive" / item["ciphertext_sha256"]
        content = bytearray(old.read_bytes())
        content[-1] ^= 1
        old.unlink()
        item["ciphertext_sha256"] = hashlib.sha256(content).hexdigest()
        replacement = old.parent / item["ciphertext_sha256"]
        replacement.write_bytes(content)
        receipt = self.rewrite_manifest(manifest)
        with self.assertRaises(InvalidTag):
            self.restore(receipt)

    def test_wrong_decryption_key_is_rejected(self):
        receipt = self.create()
        with self.assertRaises(InvalidTag):
            self.restore(receipt, key=b"x" * 32)

    def test_manifest_pin_rejects_tampering(self):
        receipt = self.create()
        _, manifest = self.manifest()
        manifest["header"]["salt_hex"] = "e" * 64
        self.rewrite_manifest(manifest)
        with self.assertRaises(ValueError):
            self.restore(receipt)

    def test_reordered_segments_are_rejected(self):
        self.create()
        _, manifest = self.manifest()
        manifest["segments"].reverse()
        with self.assertRaises(ValueError):
            self.restore(self.rewrite_manifest(manifest))

    def test_missing_segment_file_is_rejected(self):
        receipt = self.create()
        _, manifest = self.manifest()
        (self.root / "archive" / manifest["segments"][0]["ciphertext_sha256"]).unlink()
        with self.assertRaises(ValueError):
            self.restore(receipt)

    def test_unknown_archive_file_is_rejected(self):
        receipt = self.create()
        (self.root / "archive" / "unregistered-payload").write_bytes(b"hidden")
        with self.assertRaises(ValueError):
            self.restore(receipt)

    def test_segment_symlink_is_rejected(self):
        receipt = self.create()
        _, manifest = self.manifest()
        path = self.root / "archive" / manifest["segments"][0]["ciphertext_sha256"]
        outside = self.root / "outside"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.restore(receipt)

    def test_manifest_bool_integer_is_rejected(self):
        self.create()
        _, manifest = self.manifest()
        manifest["header"]["writer_generation"] = True
        with self.assertRaises(ValueError):
            self.restore(self.rewrite_manifest(manifest))

    def test_duplicate_or_missing_segment_rejected(self):
        self.create()
        _, manifest = self.manifest()
        manifest["segments"].pop()
        with self.assertRaises(ValueError):
            self.restore(self.rewrite_manifest(manifest))

    def test_current_restore_cut_must_match_archive(self):
        receipt = self.create()
        plan = restore_plan(self.plan, receipt, self.root)
        plan["anchor"]["state_digest"] = "f" * 64
        with self.assertRaises(ValueError):
            self.restore(receipt, plan=plan)

    def test_archive_cannot_be_relabelled_to_another_owner(self):
        receipt = self.create()
        plan = restore_plan(self.plan, receipt, self.root)
        plan["owner_agent_id"] = "00000000-0000-4000-8000-00000000ca82"
        with self.assertRaises(ValueError):
            self.restore(receipt, plan=plan)

    def test_live_fleet_and_path_overlap_denied(self):
        for key, value in (("output_path", str(self.root / "live-fleet" / "cold")),
                           ("input_path", str(self.root / "live-fleet" / "cold")),
                           ("output_path", str(self.source / "child"))):
            with self.subTest(key=key, value=value):
                changed = {**self.plan, key: value}
                with self.assertRaises(ValueError):
                    archive.validate_plan(changed, int(time.time()))

    def test_final_restore_revocation_leaves_no_published_image(self):
        receipt = self.create()
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.restore(receipt, reauthorize=mock.Mock(side_effect=ValueError("revoked")))
        self.assertFalse((self.root / "restored.sqlite3").exists())

    def test_archive_directory_fsync_failure_retains_ambiguous_manifest(self):
        with mock.patch.object(archive, "sync_directory", side_effect=OSError("fsync")):
            with self.assertRaises(archive.PublicationIndeterminate):
                self.create()
        self.assertTrue((self.root / "archive" / "manifest.json").is_file())
        with self.assertRaises(ValueError):
            self.create()

    def test_restore_fsync_failure_retains_published_image(self):
        receipt = self.create()
        with mock.patch.object(archive, "sync_directory", side_effect=OSError("fsync")):
            with self.assertRaises(archive.PublicationIndeterminate):
                self.restore(receipt)
        self.assertEqual((self.root / "restored.sqlite3").read_bytes(), self.source.read_bytes())

    def test_restore_publication_race_does_not_overwrite(self):
        receipt = self.create()
        real_link = os.link
        def raced(source, destination, **kwargs):
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                 0o600, dir_fd=kwargs["dst_dir_fd"])
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"concurrent owner")
            return real_link(source, destination, **kwargs)
        with mock.patch.object(archive.os, "link", side_effect=raced):
            with self.assertRaises(FileExistsError):
                self.restore(receipt)
        self.assertEqual((self.root / "restored.sqlite3").read_bytes(), b"concurrent owner")

    def test_unknown_fields_and_noncanonical_json_rejected(self):
        receipt = self.create()
        path, manifest = self.manifest()
        path.write_bytes(json.dumps(manifest, indent=2).encode())
        with self.assertRaises(ValueError):
            self.restore(receipt)
        manifest["extra"] = 1
        with self.assertRaises(ValueError):
            self.restore(self.rewrite_manifest(manifest))
        for content in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1.0}'):
            with self.assertRaises(ValueError):
                archive.parse_json(content)

    def test_replaced_path_is_detected_after_descriptor_read(self):
        with self.assertRaisesRegex(ValueError, "changed|replaced"):
            with archive.read_file(self.source, archive.MAX_IMAGE_BYTES) as stream:
                original = self.root / "old-source"
                self.source.rename(original)
                self.source.write_bytes(stream.read())

    def test_live_fleet_symlink_is_not_a_scope_boundary(self):
        fleet = self.root / "live-fleet"
        fleet.rmdir()
        fleet.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            archive.validate_plan(self.plan, int(time.time()))

    def test_untrusted_output_parent_rejected(self):
        self.root.chmod(0o777)
        try:
            with self.assertRaises(ValueError):
                self.create()
        finally:
            self.root.chmod(0o700)


class NativeVerifierAdmissionTests(unittest.TestCase):
    def test_a_script_is_not_accepted_as_native_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fake-owner"
            path.write_bytes(b"#!/bin/sh\nexit 0\n")
            path.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "native ELF"):
                archive.native_check(path, {}, path, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_wrong_binary_digest_is_rejected(self):
        executable = Path(shutil.which("true")).resolve()
        with self.assertRaisesRegex(ValueError, "approved artifact"):
            archive.native_check(executable, {}, executable, "f" * 64)

    def test_success_exit_without_owner_report_is_rejected(self):
        executable = Path(shutil.which("true")).resolve()
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            archive.native_check(executable, {}, executable, hashlib.sha256(executable.read_bytes()).hexdigest())


def owner_integration(image: Path, anchor_path: Path, verifier: Path) -> None:
    """Real owner path: signed CLI archive -> AEAD segments -> signed CLI restore -> owner."""
    with tempfile.TemporaryDirectory(prefix="cognitive-archive-owner-") as temporary:
        root = Path(temporary).resolve()
        anchor = json.loads(anchor_path.read_bytes())
        # Test-only coherent backup of the live fixture, including its WAL.
        # Product archive commands accept cold images and never open SQLite.
        cold = root / "fixture-cold.sqlite3"
        with sqlite3.connect(image.as_uri() + "?mode=ro", uri=True) as live:
            destination = sqlite3.connect(cold)
            try:
                live.backup(destination)
            finally:
                destination.close()
        source, key, key_file, signer, trust, trust_path, plan, plan_path = fixture(
            root, cold.read_bytes(), anchor, verifier)
        scratch = root / "observation-scratch"
        scratch.mkdir(mode=0o700)
        def run(payload, expected_code=0, *, observe=False):
            extra = []
            if observe:
                permit = {"schema": "hepta.cognitive.archive-observation-plan.v1",
                          "request_id": "owner-publication-observation",
                          "operation_plan_sha256": lifecycle.sha256(payload),
                          "purpose": "reconcile_publication", "created_at": int(time.time()),
                          "expires_at": int(time.time()) + 600, "scratch_parent": str(scratch)}
                permit_path = root / "observation.json"
                permit_path.write_bytes(lifecycle.canonical(signed(permit, signer)))
                extra = ["--reconcile-plan", str(permit_path),
                         "--expected-reconcile-plan-sha256", lifecycle.sha256(permit)]
            plan_path.write_bytes(lifecycle.canonical(signed(payload, signer)))
            result = subprocess.run(
                [sys.executable, str(Path(archive.__file__).resolve()), "--plan", str(plan_path),
                 "--trusted-owners", str(trust_path), "--expected-plan-sha256", lifecycle.sha256(payload),
                 "--expected-trust-sha256", lifecycle.sha256(trust), "--key-file", str(key_file),
                 "--owner-verifier", str(verifier), *extra], capture_output=True, text=True, timeout=600, check=False)
            if result.returncode != expected_code:
                raise AssertionError(f"real owner archive command failed: {result.stderr}")
            return json.loads(result.stdout)
        receipt = run(plan)
        restored_plan = restore_plan(plan, receipt, root)
        restored = run(restored_plan)
        assert Path(restored_plan["output_path"]).read_bytes() == source.read_bytes()
        assert restored["anchor"] == anchor and not restored["physical_erasure_proved"]
        assert not restored["production_activated"] and not restored["hot_history_pruned"]
        # Exercise the SAME CLI, decoder and actual pinned Rust owner after a
        # lost response. These observations never republish or adopt a writer.
        observed_archive = run(plan, observe=True)
        observed_restore = run(restored_plan, observe=True)
        assert observed_archive["artifact_sha256"] == receipt["archive_sha256"]
        assert observed_restore["artifact_sha256"] == plan["image_sha256"]
        for observed in (observed_archive, observed_restore):
            assert observed["artifact_verified"]
            assert not observed["replay_authorized"] and not observed["publication_durability_proved"]
        stale_observation = copy.deepcopy(restored_plan)
        stale_observation["anchor"]["state_digest"] = "f" * 64
        observed_denial = run(stale_observation, expected_code=2, observe=True)
        assert observed_denial["result"] == "owner_cut_rejected"
        assert Path(restored_plan["output_path"]).read_bytes() == source.read_bytes()
        assert not list(scratch.iterdir())
        # A validly signed but stale requested cut must be rejected by the actual
        # native owner, not by a stub or a string-matching expected error.
        stale = copy.deepcopy(plan)
        stale["output_path"] = str(root / "stale-archive")
        stale["anchor"]["state_digest"] = "f" * 64
        denied = run(stale, expected_code=2)
        assert denied["result"] == "owner_cut_rejected" and not denied["grants_authority"]
        assert not Path(stale["output_path"]).exists()
    print("real-owner archive/restore: passed; host acceptance and erasure remain unproved")


if __name__ == "__main__":
    if len(sys.argv) == 7 and sys.argv[1::2] == ["--owner-image", "--anchor", "--verifier"]:
        owner_integration(Path(sys.argv[2]), Path(sys.argv[4]), Path(sys.argv[6]))
    else:
        unittest.main()
