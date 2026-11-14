"""Execution admission races and real filesystem bounds, with bounded probes."""

import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import parametric_owner as owner_module
from parametric_owner import Frontier, ParametricOwner
from tensor_contract import bounded_read
from test_parametric_owner import checkpoint


def fifo_reader(path, queue, replace_during_open):
    path = Path(path)
    original_open = os.open

    def replaced(candidate, flags, *args, **kwargs):
        if Path(candidate) == path:
            path.unlink()
            os.mkfifo(path)
        return original_open(candidate, flags, *args, **kwargs)

    try:
        if replace_during_open:
            with patch("tensor_contract.os.open", side_effect=replaced):
                bounded_read(path, 32)
        else:
            bounded_read(path, 32)
    except (ValueError, OSError) as error:
        queue.put(("rejected", str(error)))
    else:
        queue.put(("accepted", ""))


class OwnerAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = ParametricOwner(self.root / "owner.sqlite")
        self.peer = ParametricOwner(self.root / "owner.sqlite")
        self.view = Frontier("scope-a")
        self.directory = self.root / "initial"
        self.pin = checkpoint(self.directory, {"1" * 64})
        self.owner.activate(
            "memory",
            self.directory,
            self.pin,
            scope="scope-a",
            expected_current=None,
            generation=0,
            provider=lambda: self.view,
            allowed_roots={"1" * 64},
        )

    def admit_with_validation_change(self, change):
        original = owner_module._checkpoint
        changed = False

        def validate(*args, **kwargs):
            nonlocal changed
            result = original(*args, **kwargs)
            if not changed:
                changed = True
                change()
            return result

        callback = Mock(return_value="must not run")
        with patch("parametric_owner._checkpoint", side_effect=validate):
            with self.assertRaisesRegex(ValueError, "changed before callback"):
                self.owner.invoke("memory", "scope-a", lambda: self.view, callback)
        callback.assert_not_called()

    def test_peer_withdrawal_during_validation_prevents_callback(self):
        def revoke():
            self.view = Frontier("scope-a", 1, ("1" * 64,))
            callback = Mock()
            with self.assertRaisesRegex(ValueError, "withdrawn"):
                self.peer.invoke("memory", "scope-a", lambda: self.view, callback)
            callback.assert_not_called()

        self.admit_with_validation_change(revoke)
        with self.assertRaisesRegex(ValueError, "rollback"):
            ParametricOwner(self.root / "owner.sqlite").invoke(
                "memory", "scope-a", lambda: Frontier("scope-a"), Mock()
            )

    def test_peer_version_change_during_validation_prevents_callback(self):
        next_directory = self.root / "next"
        next_pin = checkpoint(next_directory, {"1" * 64}, marker=1)

        def replace():
            self.peer.activate(
                "memory",
                next_directory,
                next_pin,
                scope="scope-a",
                expected_current=self.pin,
                generation=1,
                parent_manifest_sha256=self.pin,
                provider=lambda: self.view,
                allowed_roots={"1" * 64},
            )

        self.admit_with_validation_change(replace)
        self.assertEqual(self.owner.current("memory", "scope-a").generation, 1)


class BoundedFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_regular_file_and_bounds(self):
        path = self.root / "regular"
        path.write_bytes(b"exact bytes")
        self.assertEqual(bounded_read(path, 11), b"exact bytes")
        for limit in (10, 0, -1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                bounded_read(path, limit)
        path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "byte bound"):
            bounded_read(path, 11)
        with self.assertRaisesRegex(ValueError, "regular file"):
            bounded_read(self.root, 32)

    def test_symlink_rejected(self):
        target, link = self.root / "target", self.root / "link"
        target.write_bytes(b"data")
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "symlink"):
            bounded_read(link, 32)

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "mkfifo"), "POSIX FIFO probe"
    )
    def test_fifo_and_replacement_race_reject_without_blocking(self):
        context = multiprocessing.get_context("spawn")
        for replace in (False, True):
            with self.subTest(replace_during_open=replace):
                path = self.root / ("replace" if replace else "fifo")
                if replace:
                    path.write_bytes(b"initial regular bytes")
                else:
                    os.mkfifo(path)
                queue = context.Queue()
                process = context.Process(
                    target=fifo_reader, args=(str(path), queue, replace)
                )
                process.start()
                process.join(20)
                blocked = process.is_alive()
                if blocked:
                    process.terminate()
                    process.join(5)
                self.assertFalse(blocked, "regular-file admission blocked on FIFO")
                self.assertEqual(process.exitcode, 0)
                status, reason = queue.get(timeout=5)
                self.assertEqual(status, "rejected", reason)

    def test_regular_inode_replacement_during_open_is_rejected(self):
        path = self.root / "regular"
        replacement = self.root / "replacement"
        path.write_bytes(b"same bytes")
        replacement.write_bytes(b"same bytes")
        original = os.open

        def replaced(candidate, flags, *args, **kwargs):
            if Path(candidate) == path:
                replacement.replace(path)
            return original(candidate, flags, *args, **kwargs)

        with patch("tensor_contract.os.open", side_effect=replaced):
            with self.assertRaisesRegex(ValueError, "identity changed"):
                bounded_read(path, 32)

    def test_mutation_during_read_is_rejected(self):
        path = self.root / "regular"
        path.write_bytes(b"before")
        original = os.fstat
        calls = 0

        def mutate(descriptor):
            nonlocal calls
            calls += 1
            if calls == 2:
                path.write_bytes(b"changed after read")
            return original(descriptor)

        with patch("tensor_contract.os.fstat", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed during bounded read"):
                bounded_read(path, 32)


if __name__ == "__main__":
    unittest.main()
