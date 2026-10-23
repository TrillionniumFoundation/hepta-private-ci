"""Directory-entry flushing and explicit unsupported-platform behavior."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import durability
from memory_service import MemoryService


class DirectoryDurabilityTests(unittest.TestCase):
    @unittest.skipUnless(
        durability.DIRECTORY_FSYNC_SUPPORTED,
        "directory fsync is unavailable on Windows",
    )
    def test_nested_creation_flushes_every_new_parent_entry(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            target = root / "service" / "artifacts" / "attempt"
            with patch(
                "durability.sync_directory", wraps=durability.sync_directory
            ) as flush:
                durability.create_directory(target, parents=True)
            observed = {call.args[0] for call in flush.call_args_list}
            self.assertTrue(target.is_dir())
            self.assertEqual(
                observed,
                {root, root / "service", root / "service" / "artifacts", target},
            )

    @unittest.skipUnless(
        durability.DIRECTORY_FSYNC_SUPPORTED,
        "directory fsync is unavailable on Windows",
    )
    def test_directory_flush_failure_prevents_source_owner_opening(self):
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "service"
            with patch(
                "durability.os.fsync", side_effect=OSError("directory flush failed")
            ):
                with self.assertRaisesRegex(OSError, "directory flush failed"):
                    MemoryService(target, "scope")
            self.assertFalse((target / "sources.sqlite").exists())
            # Retrying a path created before the failed flush still flushes it.
            with patch(
                "durability.sync_directory", wraps=durability.sync_directory
            ) as flush:
                MemoryService(target, "scope")
            self.assertIn(
                target.parent.resolve(), {call.args[0] for call in flush.call_args_list}
            )

    def test_unsupported_directory_api_is_explicit_and_does_not_claim_recovery(self):
        with patch("durability.DIRECTORY_FSYNC_SUPPORTED", False):
            with patch(
                "durability.os.open",
                side_effect=AssertionError("unsupported API called"),
            ):
                self.assertIs(durability.sync_directory(Path("unused")), False)
            self.assertEqual(
                durability.capabilities(),
                {
                    "directory_fsync": False,
                    "directory_policy": "unsupported_on_windows",
                    "sqlite_synchronous": "FULL",
                    "power_loss_recovery_verified": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
