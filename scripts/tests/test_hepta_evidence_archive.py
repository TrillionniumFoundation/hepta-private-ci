"""Exercise byte preservation, source completeness, and archive rejection."""

import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "hepta_evidence_archive.py"
SPEC = importlib.util.spec_from_file_location("evidence_archive", SCRIPT)
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


class EvidenceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Evidence fixture")
        self.git("config", "user.email", "evidence@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.files = {
            "evidence/empty": b"",
            "evidence/original.log": b"FAILED\r\nUNKNOWN\x00\xff\n",
            "evidence/unicode.txt": "中文\n".encode(),
            "evidence/nested/binary.dat": bytes(range(256)) * 5,
        }
        for name, data in self.files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("add", ".")
        (self.repo / "evidence/empty").chmod(0o755)
        self.git("update-index", "--chmod=+x", "evidence/empty")
        self.git("commit", "-qm", "original evidence")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.output = self.root / "archive"
        self.index = archive.pack(self.repo, self.revision, "evidence", self.output, 128)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True,
                                       stderr=subprocess.PIPE)

    def write_index(self):
        (self.output / "index.json").write_bytes(archive.encoded(self.index))

    def entries(self):
        return json.loads(gzip.decompress((self.output / "m00000.json.gz").read_bytes()))

    def rewrite_entries(self, entries):
        raw = archive.encoded(entries)
        data = archive.compressed(raw)
        (self.output / "m00000.json.gz").write_bytes(data)
        self.index["members"] = [{
            "name": "m00000.json.gz", "bytes": len(data), "sha256": archive.digest(data),
            "decoded_bytes": len(raw), "decoded_sha256": archive.digest(raw),
        }]
        self.index["member_count"] = len(entries)
        self.index["total_bytes"] = sum(entry["bytes"] for entry in entries)
        listing = [{key: entry[key] for key in ("path", "mode", "git_blob")}
                   for entry in entries]
        self.index["source_listing_sha256"] = archive.digest(archive.encoded(listing))
        self.write_index()

    def payload(self):
        return gzip.decompress(b"".join((self.output / part["name"]).read_bytes()
                                      for part in self.index["parts"]))

    def rewrite_payload(self, raw):
        for part in self.index["parts"]:
            (self.output / part["name"]).unlink()
        data = archive.compressed(raw)
        (self.output / "p00000.bin").write_bytes(data)
        self.index["parts"] = [{"name": "p00000.bin", "bytes": len(data),
                                "sha256": archive.digest(data)}]
        self.index["payload_bytes"] = len(data)
        self.index["payload_sha256"] = archive.digest(data)
        self.write_index()

    def test_exact_source_restore_keeps_binary_crlf_empty_files_and_modes(self):
        target = self.root / "restored"
        result = archive.verify(self.output, self.repo, self.revision, target)
        restored = {str(path.relative_to(target)).replace("\\", "/"): path.read_bytes()
                    for path in target.rglob("*") if path.is_file()}
        self.assertEqual(restored, self.files)
        self.assertEqual(result["member_count"], len(self.files))
        self.assertEqual({row["path"]: row["mode"] for row in self.entries()},
                         dict.fromkeys(self.files, "100644") | {"evidence/empty": "100755"})
        self.assertGreater(len(self.index["parts"]), 1)

    def test_archive_is_reproducible_and_source_is_unmodified(self):
        other = self.root / "second"
        archive.pack(self.repo, self.revision, "evidence", other, 128)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()},
                         {p.name: p.read_bytes() for p in other.iterdir()})
        self.assertEqual({name: (self.repo / name).read_bytes() for name in self.files}, self.files)

    def test_modified_or_missing_source_never_creates_a_valid_index(self):
        source = self.repo / "evidence/original.log"
        for action in (lambda: source.write_bytes(b"changed"), source.unlink):
            action()
            destination = self.root / ("bad-" + str(source.exists()))
            with self.assertRaises(archive.ArchiveError):
                archive.pack(self.repo, self.revision, "evidence", destination)
            self.assertFalse((destination / "index.json").exists())

    def test_corrupt_part_is_rejected_before_creating_restore_target(self):
        part = self.output / self.index["parts"][0]["name"]
        data = bytearray(part.read_bytes())
        data[-1] ^= 1
        part.write_bytes(data)
        target = self.root / "restored"
        with self.assertRaisesRegex(archive.ArchiveError, "integrity mismatch"):
            archive.verify(self.output, destination=target)
        self.assertFalse(target.exists())

    def test_missing_extra_and_reordered_parts_fail(self):
        part = self.output / self.index["parts"][0]["name"]
        data = part.read_bytes()
        part.unlink()
        with self.assertRaises(archive.ArchiveError):
            archive.verify(self.output)
        part.write_bytes(data)
        (self.output / "unlisted.bin").write_bytes(b"extra")
        with self.assertRaises(archive.ArchiveError):
            archive.verify(self.output)
        (self.output / "unlisted.bin").unlink()
        self.index["parts"].reverse()
        self.write_index()
        with self.assertRaises(archive.ArchiveError):
            archive.verify(self.output)

    def test_rehashed_payload_cannot_replace_a_member(self):
        data = bytearray(self.payload())
        data[2] ^= 1
        self.rewrite_payload(data)
        with self.assertRaisesRegex(archive.ArchiveError, "member integrity mismatch"):
            archive.verify(self.output)

    def test_truncation_and_unlisted_trailing_bytes_fail(self):
        data = self.payload()
        for changed in (data[:-1], data + b"extra"):
            self.rewrite_payload(changed)
            with self.assertRaises(archive.ArchiveError):
                archive.verify(self.output)

    def test_unsafe_and_duplicate_paths_cannot_escape_restore(self):
        original = self.entries()
        for name in ("../escape", "/absolute", "evidence/../escape", "evidence\\escape",
                     "evidence/C:drive", "outside/entry"):
            with self.subTest(name=name):
                entries = json.loads(json.dumps(original))
                entries[0]["path"] = name
                self.rewrite_entries(entries)
                target = self.root / "restored"
                with self.assertRaises(archive.ArchiveError):
                    archive.verify(self.output, destination=target)
                self.assertFalse(target.exists())
        self.rewrite_entries([original[0], *original])
        with self.assertRaises(archive.ArchiveError):
            archive.verify(self.output)

    def test_source_repository_detects_omitted_original_members(self):
        self.git("rm", "evidence/empty")
        self.git("commit", "-qm", "incomplete evidence")
        revision = self.git("rev-parse", "HEAD").strip()
        other = self.root / "incomplete"
        index = archive.pack(self.repo, revision, "evidence", other)
        index["source_revision"] = self.revision
        (other / "index.json").write_bytes(archive.encoded(index))
        archive.verify(other)
        with self.assertRaisesRegex(archive.ArchiveError, "exact original Git subtree"):
            archive.verify(other, self.repo, self.revision)

    def test_wrong_source_and_existing_destination_are_rejected(self):
        with self.assertRaisesRegex(archive.ArchiveError, "unexpected source"):
            archive.verify(self.output, expected_source="f" * 40)
        with self.assertRaisesRegex(archive.ArchiveError, "unexpected original source listing"):
            archive.verify(self.output, expected_listing="f" * 64)
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "keep").write_bytes(b"retained")
        with self.assertRaisesRegex(archive.ArchiveError, "must not exist"):
            archive.verify(self.output, destination=destination)
        self.assertEqual((destination / "keep").read_bytes(), b"retained")

    def test_invalid_sizes_modes_and_duplicate_json_keys_fail(self):
        entries = self.entries()
        for key, value in (("bytes", True), ("bytes", -1), ("mode", "120000")):
            changed = json.loads(json.dumps(entries))
            changed[0][key] = value
            self.rewrite_entries(changed)
            with self.assertRaises(archive.ArchiveError):
                archive.verify(self.output)
        (self.output / "index.json").write_text('{"format":1,"format":2}')
        with self.assertRaisesRegex(archive.ArchiveError, "duplicate JSON key"):
            archive.verify(self.output)

    def test_manifest_shards_cover_every_member_and_are_bounded(self):
        for number in range(30):
            (self.repo / "evidence" / f"entry-{number:03d}").write_bytes(b"")
        self.git("add", ".")
        self.git("commit", "-qm", "many members")
        revision = self.git("rev-parse", "HEAD").strip()
        output = self.root / "shards"
        with mock.patch.object(archive, "MAX_INDEX", 2500):
            index = archive.pack(self.repo, revision, "evidence", output)
            self.assertGreater(len(index["members"]), 1)
            self.assertEqual(archive.verify(output, self.repo)["member_count"], 34)
            with mock.patch.object(archive, "MAX_MANIFEST_BYTES", 2500):
                with self.assertRaisesRegex(archive.ArchiveError, "total manifest bytes"):
                    archive.verify(output)

    def test_checkout_budget_checks_actual_git_bytes_and_paths(self):
        self.assertEqual(archive.check_tree(self.repo, self.revision, 190, 512_000,
                                            "evidence")["files_checked"], 4)
        large = self.repo / "evidence" / "large.bin"
        large.write_bytes(b"x" * 512_001)
        self.git("add", ".")
        self.git("commit", "-qm", "oversized file at a short path")
        with self.assertRaisesRegex(archive.ArchiveError, "checkout budget violations"):
            archive.check_tree(self.repo, "HEAD", 190, 512_000, "evidence")
        large.write_bytes(b"bounded")
        self.git("add", ".")
        blob = self.git("hash-object", "-w", "evidence/large.bin").strip()
        self.git("update-index", "--add", "--cacheinfo", f"100644,{blob},evidence/{'x' * 190}")
        tree = self.git("write-tree").strip()
        with self.assertRaisesRegex(archive.ArchiveError, "checkout budget violations"):
            archive.check_tree(self.repo, tree, 190, 512_000, "evidence")

    def test_cli_verifies_without_materializing_original_paths(self):
        (self.repo / "evidence").rename(self.root / "original-files")
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "verify", str(self.output),
                                 "--repo", str(self.repo), "--expected-source", self.revision],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["member_count"], 4)


if __name__ == "__main__":
    unittest.main()
