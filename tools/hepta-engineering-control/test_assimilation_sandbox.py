"""Credential-free Debian fixture bridge tests (A1 dormant slice)."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    DebianSandboxAdapter,
    EngineeringError,
    OwnerConsentReceipt,
)


class DebianSandboxAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="hepta-debian-sandbox-")
        self.root = Path(self.tmp.name) / "rootfs"
        (self.root / "etc/systemd/system").mkdir(parents=True)
        (self.root / "var/lib/dpkg").mkdir(parents=True)
        (self.root / "etc/os-release").write_text("ID=debian\nVERSION_ID=13\n", encoding="utf-8")
        (self.root / "var/lib/dpkg/status").write_bytes(b"Package: fixture\nStatus: install ok installed\n")
        (self.root / "etc/systemd/system/api.service").write_text("[Unit]\nAfter=network.target\n", encoding="utf-8")
        self.consent = OwnerConsentReceipt(
            owner_principal="fixture-owner",
            target_identity_digest="a" * 64,
            allowed_operations=("query_version", "query_health", "read_status"),
            allowed_roots=("fixture-root",),
            observed_unix_ns=0,
            expires_unix_ns=200,
            receipt_digest="b" * 64,
        )
        self.adapter = DebianSandboxAdapter(self.root, self.consent, root_label="fixture-root", clock=lambda: 100)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_queries_are_bounded_observations_without_authority(self) -> None:
        version = self.adapter.query_version()
        self.assertEqual(version.operation, "query_version")
        self.assertEqual(json.loads(version.payload), {"id": "debian", "version_id": "13"})
        health = self.adapter.query_health("api.service")
        self.assertEqual(json.loads(health.payload)["service"], "api.service")
        status = self.adapter.read_status()
        body = json.loads(status.payload)
        self.assertEqual(body["bytes"], 46)
        self.assertEqual(status.payload_sha256, hashlib.sha256(status.payload).hexdigest())
        for observation in (version, health, status):
            self.assertFalse(observation.authority_granted)
            self.assertFalse(observation.activation)
            self.assertFalse(observation.network_unrestricted)
            self.assertFalse(observation.production_credentials_exposed)

    def test_adapter_does_not_mutate_fixture(self) -> None:
        before = {
            str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()
        }
        self.adapter.query_version()
        self.adapter.query_health("api.service")
        self.adapter.read_status()
        after = {
            str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_effects_and_scope_expansion_fail_closed(self) -> None:
        with self.assertRaisesRegex(EngineeringError, "operation_widens_authority"):
            self.adapter._check("start_service")
        with self.assertRaisesRegex(EngineeringError, "invalid_service_name"):
            self.adapter.query_health("../../etc.service")
        (self.root / "etc/shadow").write_text("SECRET", encoding="utf-8")
        with self.assertRaisesRegex(EngineeringError, "sandbox_path_outside_adapter"):
            self.adapter._read("etc/shadow", limit=1024)

        query_only = OwnerConsentReceipt(
            owner_principal=self.consent.owner_principal,
            target_identity_digest=self.consent.target_identity_digest,
            allowed_operations=("query_version",),
            allowed_roots=self.consent.allowed_roots,
            observed_unix_ns=0,
            expires_unix_ns=200,
            receipt_digest=self.consent.receipt_digest,
        )
        restricted = DebianSandboxAdapter(self.root, query_only, root_label="fixture-root", clock=lambda: 100)
        with self.assertRaisesRegex(EngineeringError, "operation_not_consented"):
            restricted.read_status()

    def test_symlink_escape_and_root_scope_are_rejected(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside.write_text("outside", encoding="utf-8")
        (self.root / "etc/escape").symlink_to(outside)
        with self.assertRaisesRegex(EngineeringError, "sandbox_path_outside_adapter"):
            self.adapter._read("etc/escape", limit=1024)
        (self.root / "etc/systemd/system/link.service").hardlink_to(outside)
        with self.assertRaisesRegex(EngineeringError, "sandbox_file_rejected"):
            self.adapter._read("etc/systemd/system/link.service", limit=1024)
        with self.assertRaisesRegex(EngineeringError, "sandbox_scope_not_enrolled"):
            DebianSandboxAdapter(self.root, self.consent, root_label="other", clock=lambda: 100)

    def test_expired_consent_and_host_root_are_rejected(self) -> None:
        with self.assertRaisesRegex(EngineeringError, "consent_expired"):
            DebianSandboxAdapter(self.root, self.consent, root_label="fixture-root", clock=lambda: 200)
        with self.assertRaisesRegex(EngineeringError, "sandbox_root_rejected"):
            DebianSandboxAdapter(Path("/"), self.consent, root_label="fixture-root", clock=lambda: 100)


if __name__ == "__main__":
    unittest.main()
