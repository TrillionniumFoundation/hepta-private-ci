"""Synthetic strict-wire and held-directory behavior, no provider execution."""

import copy
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qualification.hcsn_training import joint_protocol as wire  # noqa: E402
from qualification.hcsn_training.joint_store import Root  # noqa: E402
from qualification.hcsn_training.joint_test_support import JournalFixture, private_file  # noqa: E402


class WireAndStoreBehavior(JournalFixture):
    def test_canonical_descriptor_and_distinct_joint_domain(self):
        self.assertEqual(wire.descriptor(self.descriptor), self.reference)
        raw = self.target["key"].encode() + b"\0" + self.target["payload_sha256"].encode()
        self.assertNotEqual(self.target["job_id"], wire.sha(b"hepta.hcsn.job.v1\0" + raw))
        for changed in (wire.encoded(dict(reversed(list(self.reference.items())))), self.descriptor + b"\n"):
            with self.subTest(raw=changed[:30]), self.assertRaises(ValueError):
                wire.descriptor(changed)

    def test_boolean_unknown_duplicate_and_oversized_requests_refused(self):
        variants = []
        for field, value in (("schema_version", True), ("request_bytes", True), ("predecessor_bytes", 2**64)):
            changed = copy.deepcopy(self.reference)
            changed["manifest"][field] = value
            variants.append(wire.encoded(changed))
        changed = copy.deepcopy(self.reference)
        changed["manifest"]["extra"] = None
        variants.append(wire.encoded(changed))
        variants.append(self.descriptor.replace(b'{"manifest":', b'{"manifest":null,"manifest":', 1))
        variants.append(b" " * (wire.COMMAND_CAP + 1))
        for raw in variants:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                wire.descriptor(raw)
        for root in (dict(self.expected, uid=True), dict(self.expected, inode=0), dict(self.expected, device=-1)):
            with self.subTest(root=root), self.assertRaises(ValueError):
                wire.root_identity(root)

    def test_marker_must_preexist_and_is_never_repaired(self):
        self.root.close()
        marker = self.path / "layout.json"
        marker.unlink()
        with self.assertRaises(FileNotFoundError):
            Root(self.path, self.expected)
        self.assertFalse(marker.exists())
        private_file(marker, wire.LAYOUT + b"\n")
        with self.assertRaises(ValueError):
            Root(self.path, self.expected)
        self.assertEqual(marker.read_bytes(), wire.LAYOUT + b"\n")

    def test_root_replacement_refused_even_at_same_path(self):
        old = self.path.with_name("retained-old-root")
        self.path.rename(old)
        self.path.mkdir(mode=0o700)
        private_file(self.path / "layout.json", wire.LAYOUT)
        with self.assertRaises(ValueError):
            self.root.check()
        with self.assertRaises(ValueError):
            self.root.child("jobs", create=True)
        self.assertFalse((self.path / "jobs").exists())
        self.assertFalse((old / "jobs").exists())

    def test_symlink_hardlink_and_mode_refused(self):
        journal = self.root.child("probe", create=True)
        journal.write("original", b"kept")
        os.link(journal.path / "original", journal.path / "alias")
        with self.assertRaises(ValueError):
            journal.read("original")
        (journal.path / "pointer").symlink_to("original")
        with self.assertRaises(ValueError):
            journal.read("pointer")
        journal.write("wrong-mode", b"retained")
        os.chmod(journal.path / "wrong-mode", 0o644)
        with self.assertRaises(ValueError):
            journal.read("wrong-mode")

    def test_exclusive_partial_record_cannot_be_overwritten(self):
        journal = self.root.child("probe", create=True)
        journal.write("partial.json", b'{"incomplete":')
        with self.assertRaises(FileExistsError):
            journal.write("partial.json", dict(incomplete=False))
        self.assertEqual(journal.read("partial.json"), b'{"incomplete":')
        with self.assertRaises(ValueError):
            wire.decode(journal.read("partial.json"))

    def test_held_child_replacement_refused(self):
        journal = self.root.child("probe", create=True)
        journal.path.rename(self.path / "old-probe")
        (self.path / "probe").mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            journal.write("never-created", b"value")
        self.assertFalse((self.path / "probe/never-created").exists())
        self.assertFalse((self.path / "old-probe/never-created").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
