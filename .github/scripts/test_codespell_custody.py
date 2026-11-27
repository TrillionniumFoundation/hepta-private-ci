import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import codespell_custody


class CodespellCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = "library-recovery/captured/objects/original.txt"
        self.payload = b"Original captured source spelling.\n"
        source = self.root / self.path
        source.parent.mkdir(parents=True)
        source.write_bytes(self.payload)
        (self.root / ".github").mkdir()
        self.manifest = {
            "schema": codespell_custody.SCHEMA,
            "files": {self.path: hashlib.sha256(self.payload).hexdigest()},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root / codespell_custody.MANIFEST).write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )

    def test_only_exact_named_original_is_excluded(self):
        other = self.root / "library-recovery/captured/current-guide.txt"
        other.write_bytes(b"Ordinary maintenance guide.\n")
        self.assertEqual(codespell_custody.verified_skip(self.root), f"./{self.path}")

    def test_binary_archive_shard_requires_matching_unchanged_bytes(self):
        for binary_path in sorted(codespell_custody.BINARY_ARCHIVE_PATHS):
            with self.subTest(binary_path=binary_path):
                payload = b"\x00\xffOriginal binary archive shard.\n"
                source = self.root / binary_path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(payload)
                self.manifest["files"] = {
                    self.path: hashlib.sha256(self.payload).hexdigest(),
                    binary_path: hashlib.sha256(payload).hexdigest(),
                }
                self.write_manifest()
                self.assertEqual(
                    codespell_custody.verified_skip(self.root),
                    ",".join(f"./{path}" for path in sorted((self.path, binary_path))),
                )
                source.write_bytes(payload + b"Changed.")
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    codespell_custody.verified_skip(self.root)

    def test_binary_archive_exemption_does_not_cover_neighboring_paths(self):
        prefix = (
            "qualification/memory-cell-mem6/run-001/raw-transfer/"
            "complete-20261111-ed353/"
        )
        for suffix in (
            "missing-000049879393.part",
            "missing-000046379393.part",
            "missing-000046379392.part.py",
            "missing-000046379392.part/../README.md",
            "missing-000049879392.part.py",
            "missing-*.part",
            "missing-000049879392.part/../README.md",
            "../complete-20261111-ed353/missing-000049879392.part",
        ):
            with self.subTest(suffix=suffix):
                self.manifest["files"] = {prefix + suffix: "0" * 64}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "exact repository path"):
                    codespell_custody.verified_skip(self.root)

    def test_changed_original_is_rejected(self):
        (self.root / self.path).write_bytes(self.payload + b"Changed.\n")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            codespell_custody.verified_skip(self.root)

    def test_upstream_attribution_requires_original_and_display_to_match_their_pins(
        self,
    ):
        relative = codespell_custody.FSDD_README
        display_path = self.root / relative
        display_path.parent.mkdir(parents=True)
        original = b"Upstream attribution. \n\n"
        display = b"Upstream attribution.\n"
        archive_path = self.root / (relative + ".evidence.gz")
        display_path.write_bytes(display)
        archive_path.write_bytes(gzip.compress(original))
        self.manifest["files"] = {relative: hashlib.sha256(original).hexdigest()}
        self.write_manifest()
        with (
            patch.dict(
                codespell_custody.QUALIFICATION_SOURCE_SHA256, self.manifest["files"]
            ),
            patch.object(
                codespell_custody,
                "FSDD_README_VIEW_SHA256",
                hashlib.sha256(display).hexdigest(),
            ),
        ):
            self.assertEqual(
                codespell_custody.verified_skip(self.root), f"./{relative}"
            )
            display_path.write_bytes(display + b"Altered.\n")
            with self.assertRaisesRegex(ValueError, "display digest mismatch"):
                codespell_custody.verified_skip(self.root)
            display_path.write_bytes(display)
            archive_path.write_bytes(gzip.compress(b"Altered original."))
            with self.assertRaisesRegex(ValueError, "archived source digest mismatch"):
                codespell_custody.verified_skip(self.root)

    def test_consolidation_binary_names_do_not_exempt_sources_or_neighbor_shards(self):
        prefix = "qa/repository-consolidation/20261118/round-03/"
        for suffix in (
            "evidence.tar.gz.part-0004.py",
            "evidence.tar.gz.part-0009/../restore_evidence.py",
            "evidence.tar.gz.part-0005",
            "evidence.tar.gz.part-*",
            "restore_evidence.py",
        ):
            with self.subTest(suffix=suffix):
                self.manifest["files"] = {prefix + suffix: "0" * 64}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "exact repository path"):
                    codespell_custody.verified_skip(self.root)

    def test_missing_original_is_rejected(self):
        (self.root / self.path).unlink()
        with self.assertRaises(FileNotFoundError):
            codespell_custody.verified_skip(self.root)

    def test_path_patterns_and_escape_forms_are_rejected(self):
        for path in (
            "library-recovery/**",
            "library-recovery/captured/?.txt",
            "library-recovery/captured/[ab].txt",
            "library-recovery/captured/a,b.txt",
            "library-recovery/captured/a\nb.txt",
            "library-recovery/../README.md",
            "library-recovery/captured/./a.txt",
            "library-recovery//captured/a.txt",
            "/library-recovery/captured/a.txt",
            "library-recovery\\captured\\a.txt",
            "scripts/current.py",
        ):
            with self.subTest(path=path):
                self.manifest["files"] = {path: "0" * 64}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "exact repository path"):
                    codespell_custody.verified_skip(self.root)

    def test_duplicate_manifest_keys_are_rejected(self):
        for raw in (
            '{"schema":"one","schema":"two","files":{}}',
            '{"schema":"hepta.codespell-custody.v1","files":{"x":"a","x":"b"}}',
        ):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                    codespell_custody.parse_manifest(raw)

    def test_invalid_manifest_and_digest_are_rejected(self):
        for document in (
            [],
            {},
            {"schema": "other", "files": {}},
            {"schema": codespell_custody.SCHEMA, "files": {}},
            {**self.manifest, "extra": True},
        ):
            with self.subTest(document=document):
                with self.assertRaisesRegex(
                    ValueError, "invalid Codespell custody manifest"
                ):
                    codespell_custody.parse_manifest(json.dumps(document))
        for digest in ("0" * 63, "A" * 64, True, None):
            with self.subTest(digest=digest):
                self.manifest["files"] = {self.path: digest}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "exact SHA-256"):
                    codespell_custody.verified_skip(self.root)

    def test_directory_and_symbolic_link_are_rejected(self):
        source = self.root / self.path
        source.unlink()
        source.mkdir()
        with self.assertRaisesRegex(ValueError, "regular single-link file"):
            codespell_custody.verified_skip(self.root)
        source.rmdir()
        target = self.root / "target.txt"
        target.write_bytes(self.payload)
        source.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "regular single-link file"):
            codespell_custody.verified_skip(self.root)
        source.unlink()
        source.parent.rmdir()
        source.parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            codespell_custody.verified_skip(self.root)

    def test_read_is_bounded_and_replacement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            codespell_custody.read_regular(self.root, self.path, 1)
        source = self.root / self.path
        replacement = source.with_name("replacement.txt")
        replacement.write_bytes(self.payload)
        original_lstat = Path.lstat
        calls = 0

        def replace_on_final_stat(path):
            nonlocal calls
            if path == source:
                calls += 1
                if calls == 2:
                    replacement.replace(source)
            return original_lstat(path)

        with patch.object(Path, "lstat", replace_on_final_stat):
            with self.assertRaisesRegex(ValueError, "changed while reading"):
                codespell_custody.read_regular(self.root, self.path, 1024)

    def test_failed_verification_does_not_emit_skip_output(self):
        destination = self.root / "output"
        destination.write_text("previous=value\n", encoding="utf-8")
        script_path = self.root / ".github/scripts/codespell_custody.py"
        with (
            patch.object(codespell_custody, "__file__", str(script_path)),
            patch.object(
                codespell_custody, "verified_skip", side_effect=ValueError("drift")
            ),
        ):
            self.assertEqual(
                codespell_custody.main(["--github-output", str(destination)]), 1
            )
        self.assertEqual(destination.read_text(encoding="utf-8"), "previous=value\n")

    def test_registered_qualification_input_requires_frozen_digest(self):
        path = (
            "qualification/hcsn_differentiable/evidence/"
            "p0p5-ci-launch-closure-20261110/codespell-fix/original-red.stdout"
        )
        expected = "bb3963bb62ee320e71703f057b98c1e71ceae250421f0b076e838ed7704ddd13"
        document = {"schema": codespell_custody.SCHEMA, "files": {path: expected}}
        try:
            actual = codespell_custody.parse_manifest(json.dumps(document))
        except ValueError:
            actual = None
        self.assertEqual(actual, {path: expected})
        for changed in ("0" * 64, expected[:-1] + "0"):
            with self.subTest(digest=changed):
                document["files"] = {path: changed}
                with self.assertRaisesRegex(ValueError, "registered SHA-256"):
                    codespell_custody.parse_manifest(json.dumps(document))

    def test_qualification_registration_does_not_admit_adjacent_paths(self):
        digest = "bb3963bb62ee320e71703f057b98c1e71ceae250421f0b076e838ed7704ddd13"
        prefix = (
            "qualification/hcsn_differentiable/evidence/"
            "p0p5-ci-launch-closure-20261110/codespell-fix/"
        )
        for path in (
            prefix + "new-result.stdout",
            prefix + "original-red.stdout*",
            prefix + "../original-red.stdout",
            "qualification/current.py",
        ):
            with self.subTest(path=path):
                document = {"schema": codespell_custody.SCHEMA, "files": {path: digest}}
                with self.assertRaisesRegex(ValueError, "exact repository path"):
                    codespell_custody.parse_manifest(json.dumps(document))

    def test_each_frozen_registration_rejects_rebinding_and_neighbor_paths(self):
        for path, expected in codespell_custody.QUALIFICATION_SOURCE_SHA256.items():
            with self.subTest(path=path):
                document = {
                    "schema": codespell_custody.SCHEMA,
                    "files": {path: expected},
                }
                self.assertEqual(
                    codespell_custody.parse_manifest(json.dumps(document)),
                    {path: expected},
                )
                replacement = ("1" if expected[0] == "0" else "0") + expected[1:]
                document["files"] = {path: replacement}
                with self.assertRaisesRegex(ValueError, "registered SHA-256"):
                    codespell_custody.parse_manifest(json.dumps(document))
                for adjacent in (path + ".new", path + "*", path + "/../README.md"):
                    document["files"] = {adjacent: expected}
                    with self.assertRaisesRegex(ValueError, "exact repository path"):
                        codespell_custody.parse_manifest(json.dumps(document))


if __name__ == "__main__":
    unittest.main()
