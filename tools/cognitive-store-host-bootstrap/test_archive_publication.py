#!/usr/bin/env python3
"""Real file/dir-fd, AEAD and signature regressions; native owner is a named mock.

These tests exercise the normal archive/restore functions, not a test-only
publisher. They do not establish native SQLite, hardware durability or erasure.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import archive
from archive_publication import PinnedDirectory, open_directory
from test_archive import fixture, restore_plan


class PublicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source, self.key, _, _, _, _, self.plan, _ = fixture(self.root)
        self.parent = self.root / "outputs"
        self.parent.mkdir(mode=0o700)
        self.plan["output_path"] = str(self.parent / "archive")
        self.verifier = self.root / "unused-native-verifier"
        patcher = mock.patch.object(archive, "native_check", autospec=True)
        self.checker = patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, reauthorize=lambda: None):
        return archive.make_archive(self.plan, self.key, self.verifier, reauthorize)

    def restore(self, report, reauthorize=lambda: None):
        plan = restore_plan(self.plan, report, self.parent)
        return archive.restore_archive(plan, self.key, self.verifier, reauthorize)

    def test_native_check_cannot_bless_changed_restore_bytes(self):
        report = self.create()
        def corrupt(image, *unused):
            with image.open("r+b") as stream:
                stream.write(b"changed-after-owner-check")
        self.checker.side_effect = corrupt
        with self.assertRaisesRegex(ValueError, "after owner verification"):
            self.restore(report)
        self.assertFalse((self.parent / "restored.sqlite3").exists())

    def test_reauthorization_cannot_replace_staged_bytes(self):
        report = self.create()
        def changed():
            for image in self.parent.glob(".cognitive*/*sqlite3"):
                with image.open("r+b") as stream:
                    stream.write(b"changed-during-reauthorization")
        with self.assertRaisesRegex(ValueError, "after owner verification"):
            self.restore(report, changed)
        self.assertFalse((self.parent / "restored.sqlite3").exists())

    def test_replaced_parent_never_creates_an_archive_inside_live_fleet(self):
        fleet = Path(self.plan["live_fleet_root"])
        def replace():
            self.parent.rename(self.root / "retained-output-parent")
            self.parent.symlink_to(fleet, target_is_directory=True)
        with self.assertRaises((OSError, ValueError, archive.PublicationIndeterminate)):
            self.create(replace)
        self.assertEqual(list(fleet.iterdir()), [])
        self.assertFalse((self.root / "retained-output-parent" / "archive").exists())

    def test_replaced_archive_name_never_publishes_manifest_into_live_fleet(self):
        fleet = Path(self.plan["live_fleet_root"])
        calls = 0
        def replace():
            nonlocal calls
            calls += 1
            if calls == 2:
                target = Path(self.plan["output_path"])
                target.rename(self.parent / "retained-archive")
                target.symlink_to(fleet, target_is_directory=True)
        with self.assertRaises((OSError, ValueError, archive.PublicationIndeterminate)):
            self.create(replace)
        self.assertEqual(list(fleet.iterdir()), [])
        self.assertFalse((self.parent / "retained-archive" / "manifest.json").exists())
        self.assertTrue(list((self.parent / "retained-archive").iterdir()))

    def test_parent_replacement_during_restore_does_not_follow_redirect(self):
        report = self.create()
        fleet = Path(self.plan["live_fleet_root"])
        def replace():
            self.parent.rename(self.root / "retained-output-parent")
            self.parent.symlink_to(fleet, target_is_directory=True)
        with self.assertRaises((OSError, ValueError, archive.PublicationIndeterminate)):
            self.restore(report, replace)
        self.assertEqual(list(fleet.iterdir()), [])

    def test_changed_source_leaf_during_link_is_indeterminate_not_success(self):
        report = self.create()
        real_link = os.link
        def raced(source, destination, **kwargs):
            source_fd = kwargs["src_dir_fd"]
            os.unlink(source, dir_fd=source_fd)
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=source_fd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"substituted-at-publication")
            return real_link(source, destination, **kwargs)
        with mock.patch.object(archive.os, "link", side_effect=raced):
            with self.assertRaises(archive.PublicationIndeterminate):
                self.restore(report)
        self.assertEqual((self.parent / "restored.sqlite3").read_bytes(), b"substituted-at-publication")
        with self.assertRaises(ValueError):
            self.restore(report)

    def test_replaced_published_inode_after_fsync_is_indeterminate(self):
        report = self.create()
        real_sync = archive.sync_directory
        def raced(path, **kwargs):
            real_sync(path, **kwargs)
            target = self.parent / "restored.sqlite3"
            target.rename(self.parent / "retained-restored.sqlite3")
            target.write_bytes(b"replacement")
        with mock.patch.object(archive, "sync_directory", side_effect=raced):
            with self.assertRaises(archive.PublicationIndeterminate):
                self.restore(report)
        self.assertEqual((self.parent / "retained-restored.sqlite3").read_bytes(), self.source.read_bytes())
        self.assertEqual((self.parent / "restored.sqlite3").read_bytes(), b"replacement")

    def test_manifest_path_replacement_after_commit_is_indeterminate(self):
        real_write = archive.write_new
        def raced(path, content, **kwargs):
            real_write(path, content, **kwargs)
            if path.name == "manifest.json":
                target = Path(self.plan["output_path"])
                target.rename(self.parent / "retained-archive")
                target.symlink_to(Path(self.plan["live_fleet_root"]), target_is_directory=True)
        with mock.patch.object(archive, "write_new", side_effect=raced):
            with self.assertRaises(archive.PublicationIndeterminate):
                self.create()
        self.assertTrue((self.parent / "retained-archive" / "manifest.json").is_file())
        self.assertEqual(list(Path(self.plan["live_fleet_root"]).iterdir()), [])

    def test_sync_uses_retained_descriptor_and_failures_preserve_image(self):
        report = self.create()
        def failed(path, *, directory_fd):
            self.assertEqual(os.fstat(directory_fd).st_ino, self.parent.stat().st_ino)
            raise OSError(errno.EIO, "injected sync failure")
        with mock.patch.object(archive, "sync_directory", side_effect=failed):
            with self.assertRaises(archive.PublicationIndeterminate):
                self.restore(report)
        self.assertEqual((self.parent / "restored.sqlite3").read_bytes(), self.source.read_bytes())

    def test_private_parent_mode_change_stops_publication(self):
        def changed():
            self.parent.chmod(0o777)
        try:
            with self.assertRaises(ValueError):
                self.create(changed)
        finally:
            self.parent.chmod(0o700)
        self.assertFalse((self.parent / "archive").exists())

    def test_success_cleans_only_private_stage_and_preserves_source(self):
        original = self.source.read_bytes()
        self.restore(self.create())
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.parent.iterdir()), ["archive", "restored.sqlite3"])
        self.assertEqual(list(Path(self.plan["live_fleet_root"]).iterdir()), [])

    def test_oversized_staged_image_never_has_manifest(self):
        def grow(image, *unused):
            with image.open("ab") as stream:
                stream.write(b"x")
        self.checker.side_effect = grow
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse((self.parent / "archive" / "manifest.json").exists())


class DirectoryPrimitiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_intermediate_symlink_is_rejected(self):
        real = self.root / "real"
        real.mkdir(mode=0o700)
        (real / "private").mkdir(mode=0o700)
        (self.root / "redirect").symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            open_directory(self.root / "redirect" / "private")

    def test_fifo_directory_is_rejected_without_waiting(self):
        path = self.root / "fifo"
        os.mkfifo(path, 0o600)
        with self.assertRaises(OSError):
            open_directory(path)

    def test_unsafe_leaf_names_are_rejected(self):
        with PinnedDirectory.open(self.root) as directory:
            for name in ("", ".", "..", "../other", "child/other", "nul\0"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    directory.absent(name)

    def test_failed_opens_do_not_leak_descriptors(self):
        before = len(list(Path("/proc/self/fd").iterdir()))
        for _ in range(20):
            with self.assertRaises(OSError):
                open_directory(self.root / "missing" / "child")
        self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before)

    def test_existing_symlink_is_not_a_free_destination(self):
        (self.root / "claimed").symlink_to(self.root / "missing")
        with PinnedDirectory.open(self.root) as directory:
            with self.assertRaises(ValueError):
                directory.absent("claimed")

    def test_scratch_cleanup_preserves_unregistered_files(self):
        with PinnedDirectory.open(self.root) as parent, parent.scratch() as stage:
            retained = stage.path
            (retained / "not-owned-by-cleanup").write_bytes(b"retain")
        self.assertEqual((retained / "not-owned-by-cleanup").read_bytes(), b"retain")

    def test_scratch_cleanup_does_not_remove_replacement_directory(self):
        with PinnedDirectory.open(self.root) as parent, parent.scratch() as stage:
            path = stage.path
            path.rename(self.root / "old-stage")
            path.mkdir(mode=0o700)
            (path / "marker").write_bytes(b"other owner")
        self.assertEqual((path / "marker").read_bytes(), b"other owner")

    def test_scratch_cleanup_preserves_same_name_replacement_inode(self):
        with PinnedDirectory.open(self.root) as parent, parent.scratch() as stage:
            path = stage.path / "cognitive_1.sqlite3"
            with stage.writer(path.name) as stream:
                stream.write(b"original private copy")
            path.rename(self.root / "retained-private-copy")
            path.write_bytes(b"unregistered replacement")
        self.assertEqual(path.read_bytes(), b"unregistered replacement")
        self.assertEqual((self.root / "retained-private-copy").read_bytes(), b"original private copy")

    def test_writer_does_not_follow_existing_symlink(self):
        marker = self.root / "marker"
        marker.write_bytes(b"keep")
        (self.root / "link").symlink_to(marker)
        with PinnedDirectory.open(self.root) as directory:
            with self.assertRaises(FileExistsError):
                directory.writer("link")
        self.assertEqual(marker.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
