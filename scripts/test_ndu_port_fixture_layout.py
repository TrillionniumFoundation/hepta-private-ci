"""Exercise actual mode restoration and reject incomplete or unsafe fixture layouts."""

import copy
import os
from pathlib import Path
import stat
import tempfile
import unittest

import ndu_port_fixture_layout as layout


class FixtureLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        self.source.mkdir(mode=0o700)
        (self.source / "empty").mkdir(mode=0o700)
        (self.source / "sdk").mkdir(mode=0o700)
        (self.source / "session.json").write_bytes(b"private session bytes")
        (self.source / "session.json").chmod(0o600)
        (self.source / "sdk/store.db").write_bytes(b"database bytes")
        (self.source / "sdk/store.db").chmod(0o600)
        self.manifest = layout.snapshot_layout(self.source)

    def test_normalized_transport_restores_exact_modes_and_keeps_original_unchanged(
        self,
    ):
        for path in (self.source, *self.source.rglob("*")):
            path.chmod(0o755 if path.is_dir() else 0o644)
        transported = layout.snapshot_layout(self.source)
        destination = self.base / "restored"
        self.assertEqual(
            layout.restore_copy(self.source, destination, self.manifest), transported
        )
        self.assertEqual(layout.snapshot_layout(destination), self.manifest)
        self.assertEqual(
            stat.S_IMODE((destination / "session.json").stat().st_mode), 0o600
        )
        self.assertEqual(
            stat.S_IMODE((self.source / "session.json").stat().st_mode), 0o644
        )
        self.assertEqual(layout.snapshot_layout(self.source), transported)
        self.assertTrue((destination / "empty").is_dir())
        self.assertNotEqual(
            (destination / "session.json").stat().st_ino,
            (self.source / "session.json").stat().st_ino,
        )

    def test_missing_or_extra_empty_directory_is_rejected_before_copy(self):
        (self.source / "empty").rmdir()
        with self.assertRaisesRegex(ValueError, "directory set"):
            layout.restore_copy(self.source, self.base / "missing", self.manifest)
        self.assertFalse((self.base / "missing").exists())
        (self.source / "empty").mkdir(mode=0o700)
        (self.source / "extra").mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "directory set"):
            layout.restore_copy(self.source, self.base / "extra", self.manifest)
        self.assertFalse((self.base / "extra").exists())

    def test_symlink_hardlink_and_special_file_are_rejected(self):
        link = self.source / "unsafe"
        link.symlink_to(self.source / "session.json")
        with self.assertRaisesRegex(ValueError, "single-link regular"):
            layout.snapshot_layout(self.source)
        link.unlink()
        os.link(self.source / "session.json", link)
        with self.assertRaisesRegex(ValueError, "single-link regular"):
            layout.snapshot_layout(self.source)
        link.unlink()
        os.mkfifo(link)
        with self.assertRaisesRegex(ValueError, "single-link regular"):
            layout.snapshot_layout(self.source)

    def test_noncanonical_paths_missing_parents_and_unsafe_modes_are_rejected(self):
        mutations = (
            lambda value: value["files"].update(
                {"../outside": value["files"]["session.json"]}
            ),
            lambda value: value["directories"].pop("sdk"),
            lambda value: value["files"]["session.json"].update(mode=0o4600),
            lambda value: value["files"]["session.json"].update(mode=0o400),
            lambda value: value["files"]["session.json"].update(mode=True),
            lambda value: value.update(root_mode=0o7777),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                invalid = copy.deepcopy(self.manifest)
                mutate(invalid)
                destination = self.base / f"invalid-{index}"
                with self.assertRaises(ValueError):
                    layout.restore_copy(self.source, destination, invalid)
                self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
