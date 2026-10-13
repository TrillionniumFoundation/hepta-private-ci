"""Fail-closed guard for Hepta's durable Matrix E2E store during SDK upgrade.

No network, model weights or production authority. This rejects weakening
encrypted session persistence merely to make Cargo's SQLite solver pass.
"""
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MatrixDurableStoreGuard(unittest.TestCase):
    def test_matrix_sdk_still_requires_real_sqlite(self):
        with (ROOT / "codex-rs/Cargo.toml").open("rb") as fh:
            ws = tomllib.load(fh)
        dep = ws["workspace"]["dependencies"]["matrix-sdk"]
        self.assertIn("sqlite", dep["features"])
        self.assertIn("e2e-encryption", dep["features"])
        self.assertFalse(dep["default-features"])
        self.assertEqual(dep["version"], "0.19.0")

    def test_owner_continues_to_use_durable_encrypted_matrix_store(self):
        source = (ROOT / "codex-rs/hepta-matrix-sdk/src/sdk.rs").read_text(
            encoding="utf-8"
        )
        for guard in (
            ".sqlite_store_with_cache_path(",
            ".remove_kv_data(StateStoreDataKey::SyncToken)",
            "persist_session(",
            "MatrixDurableStore",
            "sync_durable_once",
        ):
            with self.subTest(guard=guard):
                self.assertIn(guard, source)
        config = (ROOT / "codex-rs/hepta-matrix-sdk/src/config.rs").read_text(
            encoding="utf-8"
        )
        self.assertIn("matrix-sdk-0.18", config)
        # A separate, independently reviewed migration is necessary before
        # changing this path. Never overwrite or silently recycle old keys.

    def test_deny_config_does_not_ignore_known_blockers(self):
        deny = (ROOT / "codex-rs/deny.toml").read_text(encoding="utf-8")
        for advisory in (
            "RUSTSEC-2026-0318",
            "RUSTSEC-2026-0319",
            "RUSTSEC-2024-0449",
        ):
            with self.subTest(advisory=advisory):
                self.assertNotIn(advisory, deny)


if __name__ == "__main__":
    unittest.main()
