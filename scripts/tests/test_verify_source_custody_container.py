import contextlib
import copy
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_source_custody_container as custody


class SourceCustodyContainerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = custody.FOLLOWUP
        self.collection = self.root / self.directory
        self.collection.mkdir(parents=True)
        self.payloads = {
            "objects/first.py": b'raise RuntimeError("must not execute archived source")\n',
            "objects/second.rs": b"original historical source fragment\r\n",
        }
        document = {
            "schema": "historical-followup-source-archive-v1",
            "archived_source_executed": False,
            "scientific_or_runtime_acceptance": False,
            "deployment_or_production_activation": False,
            "source_count": 2,
            "source_bytes": sum(map(len, self.payloads.values())),
            "sources": [],
            "notices": [],
        }
        self.rows = []
        for number, (name, raw) in enumerate(self.payloads.items()):
            fp = custody.identity(raw)
            document["sources"].append(
                {
                    "relative_path": name,
                    "git_blob_sha": fp["oid"],
                    "sha256": fp["sha256"],
                    "bytes": fp["bytes"],
                }
            )
            self.rows.append(
                {
                    "path": self.directory + "/" + name,
                    "member": name,
                    "mode": "100644",
                    **fp,
                    "role": "source",
                    "provenance_pointer": f"/sources/{number}",
                }
            )
        original = (json.dumps(document) + "\n").encode()
        (self.collection / "SOURCE_MANIFEST.json").write_bytes(original)
        self.payloads.update(
            {"SOURCE_MANIFEST.json": original, "README.md": b"Original HOLD record\n"}
        )
        controls = {}
        for name in ("SOURCE_MANIFEST.json", "README.md"):
            fp = custody.identity(self.payloads[name])
            controls[name] = fp["oid"]
            self.rows.append(
                {
                    "path": self.directory + "/" + name,
                    "member": name,
                    "mode": "100644",
                    **fp,
                    "role": "prior_control",
                    "provenance_pointer": None,
                }
            )
        registration = {
            self.directory: {"manifest": "SOURCE_MANIFEST.json", "controls": controls}
        }
        patched = patch.dict(custody.SNAPSHOTS, registration, clear=True)
        patched.start()
        self.addCleanup(patched.stop)
        self.index = {
            "schema": custody.SCHEMA,
            "source_commit": custody.SOURCE_COMMIT,
            "original_directory": self.directory,
            "archive": "source-custody.tar.gz",
            "source_count": 2,
            "source_bytes": document["source_bytes"],
            "member_count": len(self.rows),
            "member_bytes": sum(x["bytes"] for x in self.rows),
            "members": self.rows,
            "source_executed": False,
            "scientific_or_runtime_qualification": False,
        }
        self.write_archive()

    def write_index(self):
        (self.collection / "ARCHIVE_MANIFEST.json").write_text(
            json.dumps(self.index), encoding="utf-8"
        )

    def write_compressed(self, raw):
        (self.collection / "source-custody.tar.gz").write_bytes(raw)
        self.index.update(
            archive_bytes=len(raw), archive_sha256=custody.identity(raw)["sha256"]
        )
        self.write_index()

    def write_archive(self, entries=None, change=None):
        stream = io.BytesIO()
        with tarfile.open(
            fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT
        ) as archive:
            for name, raw in entries if entries is not None else self.payloads.items():
                member = tarfile.TarInfo(name)
                member.mode, member.size, member.mtime = 0o644, len(raw), 0
                if change is not None:
                    change(member)
                archive.addfile(member, io.BytesIO(raw))
        raw = stream.getvalue()
        self.index.update(
            tar_bytes=len(raw), tar_sha256=custody.identity(raw)["sha256"]
        )
        self.write_compressed(gzip.compress(raw, mtime=0))

    def verify(self):
        return custody.verify_container(self.root, self.directory)

    def test_complete_container_returns_exact_sources_without_execution(self):
        expected = {
            self.directory + "/" + name: raw
            for name, raw in self.payloads.items()
            if name.startswith("objects/")
        }
        self.assertEqual(self.verify(), expected)
        self.assertEqual(
            custody.resolve_original_paths(self.root, list(expected)), expected
        )

    def test_missing_and_modified_container_are_rejected(self):
        path = self.collection / "source-custody.tar.gz"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.verify()

    def test_same_length_inner_source_change_is_rejected(self):
        changed = dict(self.payloads)
        raw = changed["objects/first.py"]
        changed["objects/first.py"] = b"!" + raw[1:]
        self.write_archive(changed.items())
        with self.assertRaisesRegex(ValueError, "member identity mismatch"):
            self.verify()

    def test_missing_duplicate_and_unexpected_tar_members_are_rejected(self):
        entries = list(self.payloads.items())
        for variant in (
            entries[:-1],
            entries + [entries[0]],
            entries + [("extra.py", b"extra")],
        ):
            with self.subTest(names=[name for name, _ in variant]):
                self.write_archive(variant)
                with self.assertRaisesRegex(ValueError, "missing|duplicate|unexpected"):
                    self.verify()

    def test_unsafe_tar_member_names_are_rejected(self):
        for name in (
            "../outside",
            "/absolute",
            "objects/../first.py",
            "objects//first.py",
            "objects\\first.py",
        ):
            with self.subTest(name=name):
                self.write_archive([(name, b"source")])
                with self.assertRaisesRegex(ValueError, "unsafe|noncanonical"):
                    self.verify()

    def test_links_special_types_and_changed_modes_are_rejected(self):
        for kind in (
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
            tarfile.DIRTYPE,
            tarfile.CHRTYPE,
        ):
            with self.subTest(kind=kind):

                def change(member):
                    member.type = kind
                    member.linkname = (
                        "outside" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                    )

                self.write_archive(change=change)
                with self.assertRaisesRegex(ValueError, "plain regular file"):
                    self.verify()
        self.write_archive(change=lambda member: setattr(member, "mode", 0o755))
        with self.assertRaisesRegex(ValueError, "mode or size"):
            self.verify()

    def test_manifest_duplicate_missing_and_unknown_records_are_rejected(self):
        original = copy.deepcopy(self.rows)
        for records in (
            original[:-1],
            original + [original[0]],
            [{**original[0], "member": "extra.py"}, *original[1:]],
        ):
            with self.subTest(count=len(records)):
                self.index["members"] = records
                self.index["member_count"] = len(records)
                self.write_index()
                with self.assertRaisesRegex(
                    ValueError, "missing|unexpected|duplicate|inconsistent"
                ):
                    self.verify()

    def test_source_hash_and_original_control_identity_are_bound(self):
        self.rows[0]["sha256"] = "0" * 64
        self.write_index()
        with self.assertRaisesRegex(ValueError, "source manifest binding"):
            self.verify()
        self.rows[0]["sha256"] = custody.identity(self.payloads["objects/first.py"])[
            "sha256"
        ]
        self.rows[-1]["oid"] = "0" * 40
        self.write_index()
        with self.assertRaisesRegex(ValueError, "changed original control"):
            self.verify()

    def test_original_source_manifest_drift_is_rejected(self):
        path = self.collection / "SOURCE_MANIFEST.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "original manifest drift"):
            self.verify()

    def test_duplicate_json_keys_and_unknown_fields_are_rejected(self):
        path = self.collection / "ARCHIVE_MANIFEST.json"
        raw = path.read_text()
        path.write_text('{"schema":"duplicated",' + raw[1:])
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.verify()
        self.index["unexpected"] = True
        self.write_index()
        with self.assertRaisesRegex(ValueError, "transport manifest"):
            self.verify()

    def test_truncated_concatenated_and_over_budget_gzip_are_rejected(self):
        original = (self.collection / "source-custody.tar.gz").read_bytes()
        for variant in (original[:-4], original + gzip.compress(b"second", mtime=0)):
            with self.subTest(bytes=len(variant)):
                self.write_compressed(variant)
                with self.assertRaisesRegex(ValueError, "gzip"):
                    self.verify()
        self.write_compressed(original)
        self.index["tar_bytes"] = 1
        self.write_index()
        with self.assertRaisesRegex(ValueError, "gzip"):
            self.verify()

    def test_boolean_counts_and_declared_budget_overflow_are_rejected(self):
        for field, value in (
            ("member_count", True),
            ("source_bytes", True),
            ("archive_bytes", custody.MAX_ARCHIVE + 1),
            ("tar_bytes", custody.MAX_TAR + 1),
        ):
            with self.subTest(field=field):
                previous = self.index[field]
                self.index[field] = value
                self.write_index()
                with self.assertRaisesRegex(ValueError, "count|limit"):
                    self.verify()
                self.index[field] = previous

    def test_missing_unsafe_duplicate_and_ambiguous_original_paths_are_rejected(self):
        path = self.directory + "/objects/first.py"
        for paths in (
            [path, path],
            [self.directory + "/objects/missing.py"],
            ["../escape"],
            ["library-recovery/unregistered/first.py"],
        ):
            with self.subTest(paths=paths):
                with self.assertRaisesRegex(ValueError, "duplicate|missing|unsafe"):
                    custody.resolve_original_paths(self.root, paths)
        with patch.dict(custody.SNAPSHOTS, {"library-recovery": {}}):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                custody.resolve_original_paths(self.root, [path])

    def test_regular_input_bounds_links_and_path_replacement_are_rejected(self):
        relative = self.directory + "/SOURCE_MANIFEST.json"
        with self.assertRaisesRegex(ValueError, "byte limit"):
            custody.read_regular(self.root, relative, 1)
        source = self.root / relative
        linked = source.with_name("linked.json")
        os.link(source, linked)
        with self.assertRaisesRegex(ValueError, "single-link"):
            self.verify()
        linked.unlink()
        replacement = source.with_name("replacement.json")
        replacement.write_bytes(source.read_bytes())
        original_lstat, calls = Path.lstat, 0

        def replace_on_final_stat(path):
            nonlocal calls
            if path == source:
                calls += 1
                if calls == 2:
                    replacement.replace(source)
            return original_lstat(path)

        with patch.object(Path, "lstat", replace_on_final_stat):
            with self.assertRaisesRegex(ValueError, "input path changed"):
                self.verify()

    def test_symlink_input_is_rejected_without_following_it(self):
        path = self.collection / "source-custody.tar.gz"
        original = path.read_bytes()
        target = self.collection / "target.gz"
        target.write_bytes(original)
        path.unlink()
        try:
            path.symlink_to(target)
        except OSError as error:
            self.skipTest(f"platform cannot create the symlink fixture: {error}")
        with self.assertRaisesRegex(ValueError, "single-link"):
            self.verify()

    def test_cli_reports_data_custody_only_and_optimized_mode_refuses(self):
        output = io.StringIO()
        with (
            patch.object(
                custody,
                "__file__",
                str(self.root / "scripts/verify_source_custody_container.py"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(custody.main([self.directory]), 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "source_count": 2,
                "source_bytes": self.index["source_bytes"],
                "notice_count": 0,
                "all_bytes_match_manifest": True,
                "archived_source_executed": False,
                "research_or_runtime_qualification": False,
            },
        )
        result = subprocess.run(
            [sys.executable, "-O", custody.__file__, self.directory],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"optimized verification refused", result.stderr)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
