"""Exercise history restoration after assets leave the maintained tree."""

import copy
import gzip
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import restore


class HistoryCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.empty_hooks = self.root / "empty-hooks"
        self.empty_hooks.mkdir()
        self.command("init", "--quiet", "--template=" + str(self.empty_hooks))
        self.source = {
            "qa/stem-bakeoff/evidence/fixture/large.bin": b"original-evidence\n" * 33000,
            "qa/stem-bakeoff/fixture_source.py": b"def answer():\n    return 42\n",
            "qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v2/data/predictors.json":
                b'{"text":"Original public corpus input."}\n',
            "qa/stem-bakeoff/evidence/fixture/README.md": b"Original failed result remains failed.\n",
        }
        for name, data in self.source.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.command("add", ".")
        self.command("commit", "--quiet", "-m", "original evidence")
        self.original = self.command("rev-parse", "HEAD").decode().strip()
        self.rows = []
        for name, data in sorted(self.source.items()):
            self.rows.append({"path": name, "mode": "100644", **restore.identity(data)})
        self.asset = next(row for row in self.rows if row["bytes"] > 512000)
        self.asset["source_commits"] = [self.original]
        self.asset["custody_reason"] = "over_original_blob_size_limit"
        (self.repository / self.asset["path"]).unlink()
        self.command("add", "-u")
        self.command("commit", "--quiet", "-m", "maintain only the history reference")
        self.head = self.command("rev-parse", "HEAD").decode().strip()
        roots = [{
            "path": "qa/stem-bakeoff",
            "tree": self.command("rev-parse", self.original + ":qa/stem-bakeoff").decode().strip(),
        }]
        snapshot = {
            "schema": restore.SNAPSHOT_SCHEMA,
            "name": "cell-v4",
            "source_commit": self.original,
            "roots": roots,
            "files": self.rows,
            "file_count": len(self.rows),
            "total_bytes": sum(row["bytes"] for row in self.rows),
        }
        raw = (json.dumps(snapshot, sort_keys=True) + "\n").encode()
        compressed = gzip.compress(raw, mtime=0)
        self.metadata = self.root / "metadata"
        (self.metadata / "snapshots").mkdir(parents=True)
        (self.metadata / "snapshots/cell-v4.json.gz").write_bytes(compressed)
        self.document = {
            "schema": restore.SCHEMA,
            "repository_blob_limit_bytes": 512000,
            "archived_source_executed_by_restorer": False,
            "scientific_or_runtime_qualification": False,
            "required_original_merge_parents": [self.original],
            "asset_count": 1,
            "asset_total_bytes": self.asset["bytes"],
            "assets": [self.asset],
            "snapshots": [{
                "name": "cell-v4",
                "source_commit": self.original,
                "roots": roots,
                "manifest_path": "snapshots/cell-v4.json.gz",
                "compressed": restore.identity(compressed),
                "uncompressed": restore.identity(raw),
                "file_count": len(self.rows),
                "total_bytes": sum(row["bytes"] for row in self.rows),
            }],
        }

    def command(self, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(self.repository),
             "-c", "user.name=History Custody Fixture",
             "-c", "user.email=fixture@example.invalid",
             "-c", "commit.gpgsign=false",
             "-c", "core.hooksPath=" + str(self.empty_hooks),
             *arguments],
            stderr=subprocess.PIPE,
        )

    def test_original_bytes_survive_removal_from_current_tree(self):
        self.assertFalse((self.repository / self.asset["path"]).exists())
        before = self.command("status", "--porcelain")
        rows, report = restore.verify(self.repository, self.document, self.head)
        output = restore.restore(self.repository, rows, self.root / "restored")
        self.assertEqual(
            (output / self.asset["path"]).read_bytes(), self.source[self.asset["path"]]
        )
        self.assertEqual(report["verified_files"], 1)
        self.assertEqual(self.command("status", "--porcelain"), before)
        self.assertFalse((self.repository / self.asset["path"]).exists())

    def test_snapshot_restores_complete_source_and_data_as_inert_files(self):
        rows, report = restore.verify(
            self.repository, self.document, self.head, "cell-v4", self.metadata
        )
        output = restore.restore(self.repository, rows, self.root / "snapshot")
        actual = {
            p.relative_to(output).as_posix(): p.read_bytes()
            for p in output.rglob("*") if p.is_file()
        }
        self.assertEqual(actual, self.source)
        self.assertEqual(report["verified_bytes"], sum(map(len, self.source.values())))

    def test_wrong_original_path_and_wrong_digest_are_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["assets"][0]["path"] = "qa/stem-bakeoff/evidence/fixture/other.bin"
        with self.assertRaisesRegex(ValueError, "exact asset path"):
            restore.verify(self.repository, changed, self.head)
        changed = copy.deepcopy(self.document)
        changed["assets"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "byte identity"):
            restore.verify(self.repository, changed, self.head)

    def test_escaping_paths_and_duplicate_assets_are_rejected(self):
        for name in ("../escape", "/absolute", "qa/stem-bakeoff/../escape", "qa\\stem-bakeoff\\escape"):
            changed = copy.deepcopy(self.document)
            changed["assets"][0]["path"] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                restore.verify(self.repository, changed, self.head)
        changed = copy.deepcopy(self.document)
        changed["assets"].append(copy.deepcopy(changed["assets"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate asset"):
            restore.verify(self.repository, changed, self.head)

    def test_existing_or_repository_destination_is_never_overwritten(self):
        rows, _ = restore.verify(self.repository, self.document, self.head)
        occupied = self.root / "occupied"
        occupied.mkdir()
        marker = occupied / "keep"
        marker.write_bytes(b"existing user data")
        with self.assertRaisesRegex(ValueError, "new restoration"):
            restore.restore(self.repository, rows, occupied)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            restore.restore(self.repository, rows, self.repository / "new-output")
        self.assertEqual(marker.read_bytes(), b"existing user data")
        self.assertFalse((self.repository / "new-output").exists())

    def test_repository_subdirectory_cannot_bypass_isolated_output(self):
        rows, _ = restore.verify(self.repository, self.document, self.head)
        subdirectory = self.repository / "qa/stem-bakeoff"
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            restore.restore(subdirectory, rows, self.repository / "other-output")
        self.assertFalse((self.repository / "other-output").exists())

    def current_input_document(self):
        document = copy.deepcopy(self.document)
        rows = [row for row in self.rows
                if row["path"].startswith("qa/stem-bakeoff/evidence/fixture/")]
        index = {
            "schema": restore.CURRENT_INPUT_SCHEMA,
            "roots": ["qa/stem-bakeoff/evidence/fixture"],
            "excluded_source_suffixes": list(restore.SOURCE_SUFFIXES),
            "files": rows,
            "file_count": len(rows),
            "total_bytes": sum(row["bytes"] for row in rows),
        }
        raw = (json.dumps(index, sort_keys=True) + "\n").encode()
        compressed = gzip.compress(raw, mtime=0)
        (self.metadata / "current-inputs.json.gz").write_bytes(compressed)
        document["current_inputs"] = {
            "manifest_path": "current-inputs.json.gz",
            "roots": index["roots"],
            "excluded_source_suffixes": list(restore.SOURCE_SUFFIXES),
            "compressed": restore.identity(compressed),
            "uncompressed": restore.identity(raw),
            "file_count": index["file_count"],
            "total_bytes": index["total_bytes"],
        }
        return document

    def test_current_inputs_bind_live_siblings_and_original_asset_without_old_source(self):
        document = self.current_input_document()
        rows, report = restore.verify(
            self.repository, document, self.head, directory=self.metadata,
            current_inputs=True,
        )
        output = restore.restore(self.repository, rows, self.root / "current-inputs")
        self.assertTrue(report["current_input_tree_verified_against_head"])
        self.assertEqual(
            {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()},
            {row["path"] for row in rows},
        )
        self.assertFalse(list(output.rglob("*.py")))
        self.assertEqual(
            (output / self.asset["path"]).read_bytes(), self.source[self.asset["path"]]
        )

    def test_current_inputs_reject_changed_live_data_and_new_unlisted_file(self):
        document = self.current_input_document()
        new_path = self.repository / "qa/stem-bakeoff/evidence/fixture/new.json"
        new_path.write_bytes(b"{}\n")
        self.command("add", ".")
        self.command("commit", "--quiet", "-m", "new maintained input")
        head = self.command("rev-parse", "HEAD").decode().strip()
        with self.assertRaisesRegex(ValueError, "file closure"):
            restore.verify(
                self.repository, document, head, directory=self.metadata,
                current_inputs=True,
            )

    def test_frozen_text_exception_requires_exact_named_original_corpus(self):
        document = copy.deepcopy(self.document)
        row = copy.deepcopy(next(row for row in self.rows
                                 if row["path"] in restore.FROZEN_TEXT_CORPORA))
        row.update(source_commits=[self.original], custody_reason="original_dataset_text")
        document["assets"].append(row)
        document["asset_count"] += 1
        document["asset_total_bytes"] += row["bytes"]
        rows, _ = restore.verify(self.repository, document, self.head)
        self.assertEqual(len(rows), 2)
        changed = copy.deepcopy(document)
        changed["assets"][-1]["custody_reason"] = "over_original_blob_size_limit"
        with self.assertRaisesRegex(ValueError, "invalid source binding"):
            restore.verify(self.repository, changed, self.head)

    def test_snapshot_corruption_and_missing_source_closure_are_rejected(self):
        path = self.metadata / "snapshots/cell-v4.json.gz"
        original = path.read_bytes()
        path.write_bytes(original + b"unexpected trailer")
        with self.assertRaisesRegex(ValueError, "compressed snapshot"):
            restore.verify(self.repository, self.document, self.head, "cell-v4", self.metadata)
        payload = json.loads(gzip.decompress(original))
        payload["files"] = payload["files"][:-1]
        payload["file_count"] -= 1
        payload["total_bytes"] = sum(row["bytes"] for row in payload["files"])
        raw = (json.dumps(payload) + "\n").encode()
        compressed = gzip.compress(raw, mtime=0)
        path.write_bytes(compressed)
        changed = copy.deepcopy(self.document)
        entry = changed["snapshots"][0]
        entry["compressed"] = restore.identity(compressed)
        entry["uncompressed"] = restore.identity(raw)
        entry["file_count"] = payload["file_count"]
        entry["total_bytes"] = payload["total_bytes"]
        with self.assertRaisesRegex(ValueError, "file closure"):
            restore.verify(self.repository, changed, self.head, "cell-v4", self.metadata)

    def test_unretained_parent_and_false_numeric_identity_are_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["required_original_merge_parents"] = [self.head]
        changed["assets"][0]["source_commits"] = [self.head]
        with self.assertRaises(ValueError):
            restore.verify(self.repository, changed, self.original)
        changed = copy.deepcopy(self.document)
        changed["assets"][0]["bytes"] = True
        with self.assertRaisesRegex(ValueError, "bounded file"):
            restore.verify(self.repository, changed, self.head)


if __name__ == "__main__":
    unittest.main()
