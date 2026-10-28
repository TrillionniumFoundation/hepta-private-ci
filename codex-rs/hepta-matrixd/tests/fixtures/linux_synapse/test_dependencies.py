"""Actual file-link custody regressions; these do not simulate a Synapse run."""

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from . import dependencies
from .dependencies import copy_seed, dependency_inventory
from .files import inventory


class DependencyLinks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-seed-links-")
        self.root = Path(self.temporary.name).resolve()
        self.seed = self.root / "seed"
        self.checkout = self.seed / "git/checkouts/nucleo/revision"
        (self.checkout / "matcher").mkdir(parents=True)
        self.license = self.checkout / "LICENSE"
        self.license.write_bytes(b"actual locked dependency license\n")
        self.link = self.checkout / "matcher/LICENSE"
        self.link.symlink_to("../LICENSE")

    def tearDown(self):
        self.temporary.cleanup()

    def test_actual_relative_license_link_survives_complete_copy_and_readback(self):
        executable = self.checkout / "tool"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o751)
        (self.seed / ".package-cache").write_bytes(b"mutable bookkeeping")
        expected = dependency_inventory(self.seed)
        destination = self.root / "copied"
        self.assertEqual(copy_seed(self.seed, destination, expected), expected)
        copied = destination / self.link.relative_to(self.seed)
        self.assertTrue(copied.is_symlink())
        self.assertEqual(os.readlink(copied), "../LICENSE")
        self.assertEqual(copied.read_bytes(), self.license.read_bytes())
        self.assertEqual(stat.S_IMODE((destination / executable.relative_to(self.seed)).stat().st_mode), 0o751)
        self.assertFalse((destination / ".package-cache").exists())
        self.assertEqual(dependency_inventory(destination), dependency_inventory(self.seed))
        with self.assertRaisesRegex(ValueError, "Symlink in evidence tree"):
            inventory(self.seed)

    def test_link_text_and_file_mode_drift_reject_before_destination_creation(self):
        expected = dependency_inventory(self.seed)
        alternate = self.checkout / "COPYING"
        alternate.write_bytes(self.license.read_bytes())
        self.link.unlink()
        self.link.symlink_to("../COPYING")
        with self.assertRaisesRegex(ValueError, "frozen ledger"):
            copy_seed(self.seed, self.root / "drift", expected)
        self.assertFalse((self.root / "drift").exists())
        expected = dependency_inventory(self.seed)
        self.license.chmod(0o711)
        with self.assertRaisesRegex(ValueError, "frozen ledger"):
            copy_seed(self.seed, self.root / "mode-drift", expected)
        self.assertFalse((self.root / "mode-drift").exists())

    def test_chained_regular_links_preserve_each_exact_target(self):
        second = self.checkout / "COPYING"
        second.symlink_to("LICENSE")
        self.link.unlink()
        self.link.symlink_to("../COPYING")
        expected = dependency_inventory(self.seed)
        destination = self.root / "chained"
        copy_seed(self.seed, destination, expected)
        self.assertEqual(os.readlink(destination / second.relative_to(self.seed)), "LICENSE")
        self.assertEqual(os.readlink(destination / self.link.relative_to(self.seed)), "../COPYING")
        self.assertEqual((destination / self.link.relative_to(self.seed)).read_bytes(), self.license.read_bytes())

    def test_dangling_cyclic_absolute_and_escaping_links_are_rejected(self):
        outside = self.root / "outside"
        outside.write_bytes(b"outside unchanged")
        for target in ("missing", "LICENSE", str(outside), "../../../../../outside"):
            with self.subTest(target=target):
                self.link.unlink()
                self.link.symlink_to(target)
                with self.assertRaises((ValueError, OSError)):
                    dependency_inventory(self.seed)
                self.assertEqual(outside.read_bytes(), b"outside unchanged")

    def test_file_dot_suffix_is_rejected_but_legal_directory_dot_is_preserved(self):
        self.link.unlink()
        self.link.symlink_to("../LICENSE/.")
        with self.assertRaises(NotADirectoryError):
            self.link.read_bytes()
        with self.assertRaisesRegex(ValueError, "nonphysical directory"):
            dependency_inventory(self.seed)
        with self.assertRaises(ValueError):
            copy_seed(self.seed, self.root / "bad-dot", {})
        self.assertFalse((self.root / "bad-dot").exists())
        self.link.unlink()
        self.link.symlink_to(".././LICENSE")
        destination = self.root / "legal-dot"
        copy_seed(self.seed, destination, dependency_inventory(self.seed))
        copied = destination / self.link.relative_to(self.seed)
        self.assertEqual(os.readlink(copied), ".././LICENSE")
        self.assertEqual(copied.read_bytes(), self.license.read_bytes())

    def test_directory_links_and_special_targets_are_rejected(self):
        fifo = self.checkout / "pipe"
        os.mkfifo(fifo)
        for target in ("..", "../pipe"):
            with self.subTest(target=target):
                self.link.unlink()
                self.link.symlink_to(target)
                with self.assertRaises(ValueError):
                    dependency_inventory(self.seed)
        fifo.unlink()
        self.link.unlink()
        self.link.symlink_to("../LICENSE")
        redirect = self.checkout / "redirect"
        redirect.symlink_to("matcher", target_is_directory=True)
        with self.assertRaises(ValueError):
            dependency_inventory(self.seed)

    def test_seed_and_destination_ancestor_links_are_rejected_without_external_writes(self):
        expected = dependency_inventory(self.seed)
        outside = self.root / "outside"
        outside.mkdir()
        redirect = self.root / "redirect"
        redirect.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            copy_seed(self.seed, redirect / "new", expected)
        source_alias = self.root / "source-alias"
        source_alias.symlink_to(self.seed, target_is_directory=True)
        with self.assertRaises(ValueError):
            dependency_inventory(source_alias)
        self.assertEqual(list(outside.iterdir()), [])

    def test_credentials_config_bin_and_symlink_bookkeeping_remain_forbidden(self):
        for name in ("credentials.toml", "config.toml", "bin", ".unknown"):
            with self.subTest(name=name):
                path = self.seed / name
                path.mkdir()
                with self.assertRaisesRegex(ValueError, "only registry/git"):
                    dependency_inventory(self.seed)
                path.rmdir()
        bookkeeping = self.seed / ".package-cache"
        bookkeeping.symlink_to(self.license.relative_to(self.seed))
        with self.assertRaisesRegex(ValueError, "bookkeeping"):
            dependency_inventory(self.seed)

    def test_source_link_mutation_during_copy_cannot_pass_readback(self):
        alternate = self.checkout / "COPYING"
        alternate.write_bytes(self.license.read_bytes())
        expected = dependency_inventory(self.seed)
        original_copy = dependencies.copy_file
        changed = False
        def mutate_after_copy(*args, **kwargs):
            nonlocal changed
            result = original_copy(*args, **kwargs)
            if not changed:
                self.link.unlink()
                self.link.symlink_to("../COPYING")
                changed = True
            return result
        with mock.patch.object(dependencies, "copy_file", side_effect=mutate_after_copy):
            with self.assertRaisesRegex(ValueError, "readback verification"):
                copy_seed(self.seed, self.root / "changed", expected)

    def test_existing_destination_cannot_be_overwritten(self):
        destination = self.root / "existing"
        destination.mkdir()
        sentinel = destination / "sentinel"
        sentinel.write_bytes(b"retain")
        with self.assertRaises(FileExistsError):
            copy_seed(self.seed, destination, dependency_inventory(self.seed))
        self.assertEqual(sentinel.read_bytes(), b"retain")


if __name__ == "__main__":
    unittest.main()
