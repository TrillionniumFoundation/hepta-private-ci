"""Original endpoint exclusion and bounded file reads use real Unix files."""

from contextlib import ExitStack
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest

if sys.platform == "linux":
    PATH = Path(__file__).with_name("hepta-upgrade-secrets-product")
    SPEC = importlib.util.spec_from_loader(
        "secrets_software_upgrade",
        importlib.machinery.SourceFileLoader("secrets_software_upgrade", str(PATH)),
    )
    upgrade = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(upgrade)
    POLICY_PATH = PATH.with_name("hepta-maintain-secrets-product")
    POLICY_SPEC = importlib.util.spec_from_loader(
        "secrets_policy_maintenance",
        importlib.machinery.SourceFileLoader(
            "secrets_policy_maintenance", str(POLICY_PATH)
        ),
    )
    policy = importlib.util.module_from_spec(POLICY_SPEC)
    POLICY_SPEC.loader.exec_module(policy)


@unittest.skipUnless(
    sys.platform == "linux", "Linux protected service software upgrade"
)
class SoftwareUpgradeTests(unittest.TestCase):
    def test_duplicate_original_intent_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            json.loads(
                '{"original_revision":1,"original_revision":2}',
                object_pairs_hook=upgrade.unique,
            )

    def test_access_time_change_does_not_change_the_original_file_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            path.write_bytes(b"original")
            path.chmod(0o600)
            os.utime(path, ns=(1, path.stat().st_mtime_ns))
            self.assertEqual(
                upgrade.read_file(path, uid=os.geteuid(), mode=0o600, maximum=32),
                b"original",
            )

    def test_links_modes_and_oversized_inputs_cannot_substitute_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            path.write_bytes(b"original")
            path.chmod(0o600)
            link = path.with_name("symlink")
            link.symlink_to(path)
            with self.assertRaises(OSError):
                upgrade.read_file(link, uid=os.geteuid(), mode=0o600, maximum=32)
            hardlink = path.with_name("hardlink")
            os.link(path, hardlink)
            with self.assertRaises(ValueError):
                upgrade.read_file(path, uid=os.geteuid(), mode=0o600, maximum=32)
            hardlink.unlink()
            path.chmod(0o640)
            with self.assertRaises(ValueError):
                upgrade.read_file(path, uid=os.geteuid(), mode=0o600, maximum=32)
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                upgrade.read_file(path, uid=os.geteuid(), mode=0o600, maximum=4)

    def test_second_writer_is_excluded_until_the_original_descriptor_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.stable-writer.lock"
            with ExitStack() as original:
                upgrade.acquire_lock(original, path, os.geteuid(), os.getegid())
                with ExitStack() as second:
                    with self.assertRaises(BlockingIOError):
                        upgrade.acquire_lock(second, path, os.geteuid(), os.getegid())
            with ExitStack() as after_join:
                upgrade.acquire_lock(after_join, path, os.geteuid(), os.getegid())

    def test_existing_wrong_owner_is_rejected_without_reassigning_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.stable-writer.lock"
            path.touch(mode=0o600)
            with ExitStack() as stack:
                with self.assertRaisesRegex(ValueError, "metadata differs"):
                    upgrade.acquire_lock(stack, path, os.geteuid() + 1, os.getegid())
            self.assertEqual(path.stat().st_uid, os.geteuid())

    def test_interrupted_publication_retains_only_its_exact_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.json"
            temporary = path.with_name(path.name + ".upgrade-new")
            temporary.write_bytes(b"different original intent")
            temporary.chmod(0o640)
            # This rejection precedes Root publication and never overwrites the
            # retained bytes, even when the caller has no Root privileges.
            with self.assertRaises(ValueError):
                upgrade.publish(path, b"successor", mode=0o640, gid=os.getegid())
            self.assertEqual(temporary.read_bytes(), b"different original intent")
            self.assertFalse(path.exists())

    def test_pending_software_publication_excludes_new_and_replayed_policy_changes(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            pending = config / "upgrade.pending.json"
            pending.write_bytes(b"retained original software intent")
            with self.assertRaisesRegex(ValueError, "software publication"):
                policy.prepare(config, "renew", 1, 1000)
            with self.assertRaisesRegex(ValueError, "software publication"):
                policy.apply(config)
            self.assertEqual(pending.read_bytes(), b"retained original software intent")
            self.assertFalse((config / "maintenance.pending.json").exists())


if __name__ == "__main__":
    unittest.main()
