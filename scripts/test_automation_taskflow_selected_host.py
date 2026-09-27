from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "automation_taskflow_selected_host",
    Path(__file__).with_name("automation_taskflow_selected_host.py"),
)
assert SPEC is not None and SPEC.loader is not None
selected = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selected)


class SelectedHostEvidenceTests(unittest.TestCase):
    def write_json(self, path: Path, value: object, mode: int) -> bytes:
        raw = (json.dumps(value, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        path.chmod(mode)
        return raw

    def test_receipt_binds_actual_files_and_rust_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root).resolve()
            tzdb = root / "tzdb"
            tzdb.mkdir()
            (tzdb / "tzdata.zi").write_text("# version 2026z\n")
            (tzdb / "Asia").mkdir()
            (tzdb / "Asia" / "Tokyo").write_bytes(b"zone-bytes")
            tzdb_sha = selected.tzdb_tree_digest(tzdb)

            profile = root / "profile.json"
            profile_raw = self.write_json(
                profile,
                {
                    "timezone_id": "Asia/Tokyo",
                    "tzdb_digest": tzdb_sha,
                    "valid_from_utc_ms": 1,
                    "valid_until_utc_ms": 10_000,
                    "initial_offset_seconds": 32400,
                    "transitions": [],
                },
                0o444,
            )
            revocations = root / "revocations.json"
            revocations_raw = self.write_json(
                revocations,
                {"authority_epoch": 4, "revision": 7, "revoked_grant_ids": []},
                0o600,
            )
            effect = root / "effect.json"
            effect_value = {
                "provider_scope": "provider.fixture",
                "destination_id": "provider:fixture",
                "final_use_scope_sha256": "1" * 64,
                "dispatch_url": "https://provider.invalid/dispatch",
                "lookup_url_template": "https://provider.invalid/status/{key}",
                "headers": {"authorization": "secret"},
                "timeout_ms": 1000,
                "contract_id": "fixture-contract",
                "contract_sha256": "2" * 64,
                "contract_authority_epoch": 3,
                "contract_signature_hex": "3" * 128,
                "contract_verifying_key_hex": "4" * 64,
                "final_use_signer_id": "fixture-signer",
                "final_use_verifying_key_hex": "5" * 64,
                "final_use_revocations_file": str(revocations),
                "schema_version": 1,
            }
            effect_raw = self.write_json(effect, effect_value, 0o600)
            terminal = root / "terminal.json"
            terminal_value = {
                "schema_version": 1,
                "observer_id": "app-server-observer",
                "agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
                "protocol": "thread/queue/reconcile+thread/turns/list@v2",
            }
            terminal_raw = self.write_json(terminal, terminal_value, 0o600)

            timezone_rust = root / "timezone-rust.json"
            self.write_json(
                timezone_rust,
                {
                    "profileSha256": selected.sha256_bytes(profile_raw),
                    "tzdbSha256": tzdb_sha,
                    "rustConsumed": True,
                    "sqliteRuntimeVersion": "3.50.0",
                    "timezoneId": "Asia/Tokyo",
                    "transitionCount": 0,
                },
                0o600,
            )
            effect_rust = root / "effect-rust.json"
            self.write_json(
                effect_rust,
                {
                    "effectHostSha256": selected.sha256_bytes(effect_raw),
                    "revocationsSha256": selected.sha256_bytes(revocations_raw),
                    "terminalObserverSha256": selected.sha256_bytes(terminal_raw),
                    "productConfigurationLoaded": True,
                },
                0o600,
            )
            args = SimpleNamespace(
                candidate_sha="a" * 40,
                target_profile="fixture",
                tzdb_root=str(tzdb),
                expected_tzdb_sha256=tzdb_sha,
                timezone_profile=str(profile),
                effect_host=str(effect),
                terminal_observer=str(terminal),
                timezone_rust_receipt=str(timezone_rust),
                effect_rust_receipt=str(effect_rust),
            )
            with mock.patch.object(
                selected,
                "git",
                side_effect=lambda *parts: "a" * 40
                if parts == ("rev-parse", "HEAD")
                else "b" * 40,
            ):
                receipt = selected.build_receipt(args)
            self.assertEqual(receipt["commit"], "a" * 40)
            self.assertEqual(receipt["tzdb"]["sha256"], tzdb_sha)
            self.assertFalse(receipt["deploymentQualificationComplete"])
            self.assertEqual(
                receipt["inputs"]["effectHostFileSha256"],
                selected.sha256_bytes(effect_raw),
            )

    def test_tzdb_digest_changes_when_zone_bytes_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root).resolve()
            zone = root / "zone"
            zone.write_bytes(b"first")
            first = selected.tzdb_tree_digest(root)
            zone.write_bytes(b"second")
            self.assertNotEqual(first, selected.tzdb_tree_digest(root))

    def test_tzdb_digest_binds_symlink_topology(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root).resolve()
            (root / "zone-a").write_bytes(b"same")
            (root / "zone-b").write_bytes(b"same")
            os.symlink("zone-a", root / "alias")
            first = selected.tzdb_tree_digest(root)
            (root / "alias").unlink()
            os.symlink("zone-b", root / "alias")
            self.assertNotEqual(first, selected.tzdb_tree_digest(root))

    def test_protected_files_reject_group_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            path = Path(raw_root).resolve() / "secret.json"
            path.write_text("{}")
            path.chmod(0o640)
            with self.assertRaisesRegex(ValueError, "group/world"):
                selected.read_file(path, protected=True)


if __name__ == "__main__":
    unittest.main()
