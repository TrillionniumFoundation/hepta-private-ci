#!/usr/bin/python3
"""Offline rejection tests for the actual tool-only selector and creation boundary."""

import importlib
import io
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

SOURCE = Path(sys.argv.pop(1)).resolve(strict=True)
sys.path.insert(0, str(SOURCE))
supply = importlib.import_module("tool_supply")


def elf(machine=62):
    raw = bytearray(64)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", raw, 16, 3, machine, 1)
    return bytes(raw)


def member(
    name="./usr/bin/ssh-keygen",
    raw=None,
    kind=tarfile.REGTYPE,
    uid=0,
    gid=0,
    mode=0o755,
    linkname="",
):
    item = tarfile.TarInfo(name)
    item.uid, item.gid, item.mode, item.type = uid, gid, mode, kind
    item.linkname = linkname
    raw = elf() if raw is None else raw
    item.size = len(raw) if kind == tarfile.REGTYPE else 0
    return item, raw


def payload(items):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for item, raw in items:
            archive.addfile(item, io.BytesIO(raw) if item.isreg() else None)
    return output.getvalue()


class SelectionTests(unittest.TestCase):
    def test_exact_member_bytes_are_preserved_on_both_architectures(self):
        for architecture, machine in (("amd64", 62), ("arm64", 183)):
            raw = elf(machine) + b"opaque distribution bytes"
            original = [member(raw=raw), member("usr/share/doc/notice", b"notice")]
            for roots in ([], [member(".", kind=tarfile.DIRTYPE)]):
                data = payload(roots + original)
                self.assertEqual(supply.select_tool(data, architecture), raw)

    def test_symlink_hardlink_and_special_tool_members_are_rejected(self):
        for kind in (
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
            tarfile.FIFOTYPE,
            tarfile.DIRTYPE,
        ):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                supply.select_tool(
                    payload([member(kind=kind, linkname="foreign")]), "amd64"
                )

    def test_duplicate_tool_and_concatenated_archives_are_rejected(self):
        original = payload([member()])
        for data in (
            payload([member(), member("usr/bin/ssh-keygen")]),
            original + original,
            original + payload([member("usr/share/doc/extra", b"extra")]),
        ):
            with self.subTest(bytes=len(data)), self.assertRaises(RuntimeError):
                supply.select_tool(data, "amd64")

    def test_standard_end_blocks_and_zero_padding_are_preserved(self):
        # One regular 64-byte fixture occupies its 512-byte header and data block.
        prefix = payload([member()])[:1024]
        for zeros in (1024, 9216, 14336):
            self.assertEqual(supply.select_tool(prefix + b"\0" * zeros, "amd64"), elf())
        for data in (prefix + b"\0" * 512, prefix + b"\0" * 1024 + b"x"):
            with self.subTest(bytes=len(data)), self.assertRaises(RuntimeError):
                supply.select_tool(data, "amd64")
        for root in ("/", "././"):
            with self.subTest(root=root), self.assertRaises(RuntimeError):
                supply.select_tool(
                    payload([member(root, kind=tarfile.DIRTYPE), member()]), "amd64"
                )

    def test_owner_write_and_setid_changes_are_rejected(self):
        changes = (
            {"uid": 1000},
            {"gid": 1000},
            {"mode": 0o777},
            {"mode": 0o775},
            {"mode": 0o4755},
            {"mode": 0o2755},
            {"mode": 0o644},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                supply.select_tool(payload([member(**change)]), "amd64")

    def test_wrong_architecture_class_endian_and_non_elf_are_rejected(self):
        for raw in (
            elf(183),
            b"plain data",
            elf()[:4] + b"\x01" + elf()[5:],
            elf()[:5] + b"\x02" + elf()[6:],
        ):
            with self.subTest(raw=raw[:20]), self.assertRaises(RuntimeError):
                supply.select_tool(payload([member(raw=raw)]), "amd64")

    def test_noncanonical_and_replaced_ancestor_paths_are_rejected(self):
        for name in (
            "/usr/bin/ssh-keygen",
            "usr/../usr/bin/ssh-keygen",
            "usr//bin/ssh-keygen",
            "usr/bin/ssh-keygen/",
            "././usr/bin/ssh-keygen",
        ):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                supply.select_tool(payload([member(name)]), "amd64")
        with self.assertRaises(RuntimeError):
            supply.select_tool(
                payload([member("usr/bin", kind=tarfile.SYMTYPE), member()]), "amd64"
            )

    def test_missing_truncated_and_oversized_inputs_are_rejected(self):
        for data in (
            payload([member("usr/bin/other")]),
            payload([member()])[:530],
            payload([member(raw=b"x" * (supply.MAX_TOOL + 1))]),
            b"x" * (supply.MAX_TAR + 1),
        ):
            with (
                self.subTest(bytes=len(data)),
                self.assertRaises((RuntimeError, tarfile.TarError)),
            ):
                supply.select_tool(data, "amd64")


class CreationTests(unittest.TestCase):
    def test_new_file_preserves_bytes_mode_and_single_object(self):
        with tempfile.TemporaryDirectory(prefix="rbe-tool-create-") as temporary:
            target = Path(temporary).resolve() / "ssh-keygen"
            raw = elf() + b"not executed"
            supply.create_exclusive(target, raw, 0o755)
            metadata = target.lstat()
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(
                (
                    metadata.st_uid,
                    metadata.st_gid,
                    metadata.st_nlink,
                    stat.S_IMODE(metadata.st_mode),
                ),
                (os.geteuid(), os.getegid(), 1, 0o755),
            )

    def test_existing_file_symlink_and_hardlink_are_never_overwritten(self):
        for kind in ("file", "symlink", "hardlink"):
            with (
                self.subTest(kind=kind),
                tempfile.TemporaryDirectory(prefix="rbe-tool-foreign-") as temporary,
            ):
                root = Path(temporary).resolve()
                original, target = root / "foreign", root / "ssh-keygen"
                original.write_bytes(b"foreign original")
                if kind == "file":
                    target.write_bytes(b"existing target")
                elif kind == "symlink":
                    target.symlink_to(original)
                else:
                    os.link(original, target)
                before = target.lstat()
                with self.assertRaises(FileExistsError):
                    supply.create_exclusive(target, elf(), 0o755)
                self.assertEqual(target.lstat(), before)
                self.assertEqual(original.read_bytes(), b"foreign original")
                self.assertEqual(
                    target.read_bytes(),
                    b"existing target" if kind == "file" else b"foreign original",
                )

    def test_parent_alias_or_world_writable_directory_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="rbe-tool-parent-") as temporary:
            root = Path(temporary).resolve()
            real = root / "real"
            real.mkdir()
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                supply.create_exclusive(alias / "ssh-keygen", elf(), 0o755)
            real.chmod(0o777)
            with self.assertRaises(RuntimeError):
                supply.create_exclusive(real / "ssh-keygen", elf(), 0o755)
            self.assertEqual(list(real.iterdir()), [])


class DependencyTests(unittest.TestCase):
    def inspect(self, stdout, *, status=0, stderr=b"", owner=0, mode=0o644):
        def command(argv, *, success):
            self.assertEqual(argv, ["/usr/bin/ldd", "/staged/ssh-keygen"])
            self.assertFalse(success)
            return subprocess.CompletedProcess(argv, status, stdout, stderr)

        def snapshot(path):
            return {
                "logical": path,
                "resolved": path,
                "uid": owner,
                "gid": 0,
                "mode": mode,
                "bytes": 8,
                "sha256": "recorded fixture bytes",
            }

        return supply.dependency_files(Path("/staged/ssh-keygen"), command, snapshot)

    def test_complete_existing_dependency_paths_are_retained(self):
        lines = (
            b"linux-vdso.so.1 (0x1234)\n"
            b"libc.so.6 => /lib/libc.so.6 (0x3456)\n"
            b"/lib/ld-linux-x86-64.so.2 (0x789a)\n"
        )
        actual = self.inspect(lines)
        self.assertEqual(
            [x["logical"] for x in actual],
            ["/lib/ld-linux-x86-64.so.2", "/lib/libc.so.6"],
        )

    def test_missing_unknown_duplicate_and_unprotected_dependencies_are_rejected(self):
        valid = b"libc.so.6 => /lib/libc.so.6 (0x3456)\n"
        for data in (
            b"libmissing.so => not found\n",
            b"unrecognized loader output\n",
            valid + valid,
            b"linux-vdso.so.1 (0x1234)\n",
        ):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                self.inspect(data)
        for change in (
            {"status": 1},
            {"stderr": b"loader failed"},
            {"owner": 1000},
            {"mode": 0o666},
        ):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.inspect(valid, **change)


if __name__ == "__main__":
    unittest.main(verbosity=2)
