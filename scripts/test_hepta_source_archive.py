"""Exercise archive integrity against real Git objects and hostile tar members."""

import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

import hepta_source_archive as checker


@unittest.skipUnless(
    os.name == "posix", "descriptor-relative source verification is POSIX-only"
)
class SourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.artifacts = self.root / "artifacts"
        self.source.mkdir()
        self.artifacts.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "archive-test@example.invalid")
        self.git("config", "user.name", "Archive test")
        (self.source / "src").mkdir()
        (self.source / "src/code.py").write_bytes(b"print('bound')\r\n")
        (self.source / "data.bin").write_bytes(b"\0\xff\r\nraw\0bytes")
        (self.source / "run.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
        (self.source / "run.sh").chmod(0o755)
        (self.source / "src/data-link").symlink_to("../data.bin")
        (self.source / ("long-" + "x" * 120 + ".txt")).write_bytes(b"long name\n")
        (self.source / "unicode-\u6e90.txt").write_bytes(b"UTF-8 path\n")
        self.commit()
        self.archive = self.artifacts / "source.tar"
        self.freeze()
        self.original = self.archive.read_bytes()

    def git(self, *args):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.source), *args], stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")

    def identity(self):
        return {
            "commit": self.git("rev-parse", "HEAD"),
            "tree": self.git("rev-parse", "HEAD^{tree}"),
        }

    def pin(self, path):
        raw = path.read_bytes()
        return {
            "path": path.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def freeze(self, prefix=""):
        args = ["archive", "--format=tar", "-o", str(self.archive)]
        if prefix:
            args.append("--prefix=" + prefix + "/")
        self.git(*args, "HEAD")
        self.binding = {
            "schema": checker.SCHEMA,
            "tested_source": self.identity(),
            "archive": self.pin(self.archive),
            "archive_prefix": prefix,
        }

    def verify(self):
        return checker.verify(self.binding, self.source, self.artifacts)

    def rewrite(self, transform):
        self.archive.write_bytes(self.original)
        with tarfile.open(self.archive) as archive:
            records = [
                (
                    member,
                    archive.extractfile(member).read() if member.isfile() else None,
                )
                for member in archive
            ]
        with tarfile.open(self.archive, "w", format=tarfile.PAX_FORMAT) as archive:
            for member, raw in transform(records):
                archive.addfile(member, io.BytesIO(raw) if raw is not None else None)
        self.binding["archive"] = self.pin(self.archive)

    def test_complete_raw_bytes_modes_links_prefix_and_gzip(self):
        for prefix in ("", "outer/source"):
            with self.subTest(prefix=prefix):
                self.freeze(prefix)
                self.archive.write_bytes(
                    gzip.compress(self.archive.read_bytes(), mtime=0)
                )
                self.binding["archive"] = self.pin(self.archive)
                report = self.verify()
                self.assertTrue(report["integrity_verified"])
                self.assertEqual(report["archive_format"], "tar.gz")
                inventory = {item["path"]: item for item in report["files"]}
                self.assertEqual(len(inventory), 6)
                self.assertEqual(inventory["run.sh"]["git_mode"], "100755")
                self.assertEqual(inventory["src/data-link"]["git_mode"], "120000")
                self.assertEqual(
                    inventory["data.bin"]["sha256"],
                    hashlib.sha256(b"\0\xff\r\nraw\0bytes").hexdigest(),
                )

    def test_duplicate_missing_extra_and_extra_directory_are_rejected(self):
        extra = tarfile.TarInfo("extra.txt")
        extra.size = 1
        directory = tarfile.TarInfo("unused")
        directory.type = tarfile.DIRTYPE
        changes = [
            lambda xs: xs + [xs[-1]],
            lambda xs: xs[:-1],
            lambda xs: xs + [(extra, b"x")],
            lambda xs: xs + [(directory, None)],
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                self.rewrite(change)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_file_bytes_modes_link_targets_and_hardlinks_are_checked(self):
        for mutation in (
            "bytes",
            "mode",
            "target",
            "hardlink",
            "special_mode",
            "contiguous",
        ):

            def change(records):
                for member, raw in records:
                    if mutation == "bytes" and member.name == "data.bin":
                        raw = b"X" + raw[1:]
                    elif mutation == "mode" and member.name == "run.sh":
                        member.mode = 0o644
                    elif mutation == "target" and member.issym():
                        member.linkname = "../else.bin"
                    elif mutation == "hardlink" and member.name == "data.bin":
                        member.type, member.linkname, member.size, raw = (
                            tarfile.LNKTYPE,
                            "run.sh",
                            0,
                            None,
                        )
                    elif mutation == "special_mode" and member.name == "run.sh":
                        member.mode = 0o4755
                    elif mutation == "contiguous" and member.name == "data.bin":
                        member.type = tarfile.CONTTYPE
                    yield member, raw

            with self.subTest(mutation=mutation):
                self.rewrite(change)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_noncanonical_and_escaping_paths_never_extract(self):
        for name in (
            "../escaped",
            "/escaped",
            "src/../../escaped",
            "./data.bin",
            "src//data.bin",
            "C:/escaped",
            "src\\escaped",
        ):

            def change(records):
                records[-1][0].name = name
                return records

            with self.subTest(path=name):
                self.rewrite(change)
                with self.assertRaisesRegex(ValueError, "archive path"):
                    self.verify()
                self.assertFalse((self.root / "escaped").exists())

    def test_exact_tree_with_an_escaping_symlink_is_refused(self):
        link = self.source / "src/data-link"
        link.unlink()
        link.symlink_to("../../escaped")
        self.commit()
        self.freeze()
        with self.assertRaisesRegex(ValueError, "escaping symlink"):
            self.verify()

    def test_prefix_does_not_hide_outside_members(self):
        self.binding["archive_prefix"] = "envelope"
        with self.assertRaisesRegex(ValueError, "outside the explicit archive prefix"):
            self.verify()

    def test_git_export_ignore_and_export_subst_are_not_exclusions(self):
        (self.source / ".gitattributes").write_text("data.bin export-ignore\n")
        self.commit()
        self.freeze()
        with self.assertRaisesRegex(ValueError, "missing.*tracked paths"):
            self.verify()
        (self.source / ".gitattributes").write_text("src/code.py export-subst\n")
        (self.source / "src/code.py").write_text("$Format:%H$\n")
        self.commit()
        self.freeze()
        with self.assertRaisesRegex(ValueError, "archive file.*differs"):
            self.verify()

    def test_truncation_concatenated_archives_and_decompression_bound(self):
        with tarfile.open(self.archive) as archive:
            last = archive.getmembers()[-1]
            end = last.offset_data + (last.size + 511) // 512 * 512
        cases = [
            self.original[:end],
            self.original + self.original,
            gzip.compress(self.original) + gzip.compress(self.original),
            gzip.compress(self.original + bytes(1024 * 1024)),
        ]
        for raw in cases:
            with self.subTest(bytes=len(raw)):
                self.archive.write_bytes(raw)
                self.binding["archive"] = self.pin(self.archive)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_archive_byte_pin_and_config_pin_are_independent(self):
        good = copy.deepcopy(self.binding)
        for key, value in (("sha256", "0" * 64), ("bytes", len(self.original) - 1)):
            self.binding = copy.deepcopy(good)
            self.binding["archive"][key] = value
            with self.assertRaises(ValueError):
                self.verify()
        self.binding = good
        config = self.artifacts / "runtime.json"
        config.write_bytes(b'{"budget":12}\n')
        self.binding["runtime_configuration"] = self.pin(config)
        self.assertEqual(self.verify()["runtime_configuration"], self.pin(config))
        config.write_bytes(b'{"budget":13}\n')
        with self.assertRaisesRegex(ValueError, "artifact bytes"):
            self.verify()

    def test_source_pins_dirty_files_and_unknown_exclusions_fail_closed(self):
        good = copy.deepcopy(self.binding)
        for key in ("commit", "tree"):
            self.binding = copy.deepcopy(good)
            self.binding["tested_source"][key] = "0" * 40
            with self.assertRaisesRegex(ValueError, "exact tested"):
                self.verify()
        self.binding = good
        self.binding["exclude"] = ["data.bin"]
        with self.assertRaisesRegex(ValueError, "exclusions are unsupported"):
            self.verify()
        del self.binding["exclude"]
        (self.source / "extra.py").write_text("untracked")
        with self.assertRaisesRegex(ValueError, "untracked"):
            self.verify()

    def test_release_with_different_tree_remains_an_independent_observation(self):
        tested = self.identity()
        (self.source / "src/code.py").write_text("different release\n")
        self.commit()
        release = self.identity()
        self.git("checkout", "-q", tested["commit"])
        self.binding["release_source"] = release
        report = self.verify()
        self.assertEqual(report["release_observation"], release)
        self.assertNotEqual(release["tree"], report["tested_source"]["tree"])
        self.assertTrue(report["integrity_verified"])
        for claim in (
            "test_execution_authenticated",
            "ci_authenticated",
            "publication_authenticated",
            "runtime_use_authenticated",
            "production_qualification",
            "research_advancement",
            "authority_granted",
        ):
            self.assertIs(report[claim], False)

    def test_archive_symlink_and_fifo_paths_are_refused(self):
        target = self.artifacts / "real.tar"
        self.archive.rename(target)
        self.archive.symlink_to(target.name)
        with self.assertRaises((OSError, ValueError)):
            self.verify()
        self.archive.unlink()
        os.mkfifo(self.archive)
        with self.assertRaises(ValueError):
            self.verify()

    def test_cli_failure_emits_only_integrity_failure(self):
        binding = self.artifacts / "binding.json"
        output = self.artifacts / "result.json"
        self.binding["archive"]["sha256"] = "0" * 64
        binding.write_text(json.dumps(self.binding))
        run = subprocess.run(
            [
                sys.executable,
                "-B",
                checker.__file__,
                "--binding",
                str(binding),
                "--source-root",
                str(self.source),
                "--artifact-root",
                str(self.artifacts),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        report = json.loads(output.read_text())
        self.assertFalse(report["integrity_verified"])
        self.assertFalse(report["test_execution_authenticated"])
        self.assertFalse(report["production_qualification"])
        self.assertIn("artifact bytes", report["error"])


if __name__ == "__main__":
    unittest.main()
