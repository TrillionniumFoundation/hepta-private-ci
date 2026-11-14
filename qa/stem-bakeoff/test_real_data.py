"""Exercise acquisition failures and archive-backed cohort replay without a network."""

import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import fetch_real_checkpoint as fetch
import prepare_news_cohorts as news


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "source.zip"
        self.destination = self.root / "cohorts"
        ordinary = next(f"Publisher {n}" for n in range(100) if not news.publisher_is_ood(f"Publisher {n}"))
        ood = next(f"Publisher {n}" for n in range(100) if news.publisher_is_ood(f"Publisher {n}"))
        lines = []
        for split, month in news.WINDOWS.items():
            stamp = int(datetime.fromisoformat(month + "-10").replace(tzinfo=timezone.utc).timestamp() * 1000)
            for category in news.LABELS:
                for duplicate in range(2):
                    identity = f"{split}-{category}-{duplicate}"
                    parts = [identity, f"Independent news {identity}", "https://example.org/" + identity,
                             ood if split == "ood" else ordinary, category, "story-" + identity,
                             "example.org", str(stamp + duplicate)]
                    lines.append("\t".join(parts) + "\n")
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("newsCorpora.csv", "".join(lines))
        patch = mock.patch.object(news, "ARCHIVE_SHA256", news.sha(self.archive.read_bytes()))
        patch.start()
        self.addCleanup(patch.stop)
        self.manifest = news.prepare_archive(self.archive, self.destination,
                                            {name: 4 for name in news.WINDOWS})

    def load(self):
        payload = (self.destination / "manifest.json").read_bytes()
        return news.load_cohorts(self.destination, archive=self.archive,
                                expected_manifest_sha256=news.sha(payload))

    def rewrite(self, split, rows, *, repin):
        payload = b"".join(news.canonical(row) + b"\n" for row in rows)
        (self.destination / f"{split}.jsonl").write_bytes(payload)
        if repin:
            self.manifest["splits"][split] = news._summary(rows, payload)
            (self.destination / "manifest.json").write_bytes(news.canonical(self.manifest) + b"\n")

    def test_prepare_load_replays_rows_and_preserves_scope(self):
        manifest, cohorts = self.load()
        self.assertEqual(manifest, self.manifest)
        self.assertEqual([len(cohorts[name]) for name in news.WINDOWS], [4] * 5)
        self.assertEqual(news.load_cohorts(self.destination), (manifest, cohorts))
        self.assertFalse(manifest["dataset_pretraining_contamination_excluded"])
        self.assertIn("task-head", manifest["temporal_semantics"])

    def test_jsonl_tamper_is_rejected_even_after_self_repin(self):
        _, cohorts = self.load()
        cohorts["train"][0]["text"] = "A fabricated title absent from the pinned archive"
        self.rewrite("train", cohorts["train"], repin=False)
        with self.assertRaisesRegex(ValueError, "manifest pin"):
            self.load()
        self.rewrite("train", cohorts["train"], repin=True)
        with self.assertRaisesRegex(ValueError, "source replay"):
            self.load()

    def test_reordered_valid_source_rows_cannot_self_repin(self):
        _, cohorts = self.load()
        self.rewrite("future_1", list(reversed(cohorts["future_1"])), repin=True)
        with self.assertRaisesRegex(ValueError, "source replay"):
            self.load()

    def test_manifest_external_pin_and_contamination_claim_are_checked(self):
        with self.assertRaisesRegex(ValueError, "external pin"):
            news.load_cohorts(self.destination, expected_manifest_sha256="0" * 64)
        self.manifest["dataset_pretraining_contamination_excluded"] = True
        (self.destination / "manifest.json").write_bytes(news.canonical(self.manifest) + b"\n")
        with self.assertRaisesRegex(ValueError, "claims disagree"):
            self.load()

    def test_actual_rows_enforce_story_title_time_class_and_publisher_isolation(self):
        _, cohorts = self.load()
        changes = [
            ("source_group_id", cohorts["train"][0]["source_group_id"]),
            ("text", cohorts["train"][0]["text"].upper()),
            ("timestamp_ms", cohorts["train"][0]["timestamp_ms"]),
            ("label", True),
            ("publisher", cohorts["ood"][0]["publisher"]),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                changed = copy.deepcopy(cohorts)
                changed["calibration"][0][key] = value
                with self.assertRaises(ValueError):
                    news.validate_cohorts(changed)

    def test_publisher_partition_uses_same_canonical_name(self):
        for text in ("Publisher 1", "  PUBLISHER\t1  ", "Ｐｕｂｌｉｓｈｅｒ １"):
            self.assertEqual(news.publisher_is_ood(text), news.publisher_is_ood("publisher 1"))

    def test_corrupted_source_or_file_alias_rejected(self):
        self.archive.write_bytes(b"untrusted archive")
        with self.assertRaisesRegex(ValueError, "pinned UCI"):
            self.load()
        other_output = self.root / "must-not-exist"
        with self.assertRaises(ValueError):
            news.prepare_archive(self.archive, other_output)
        self.assertFalse(other_output.exists())
        os.link(self.destination / "train.jsonl", self.root / "aliased.jsonl")
        with self.assertRaisesRegex(ValueError, "unaliased"):
            self.load()


class BrokenResponse(io.BytesIO):
    def read(self, size=-1):
        if self.tell():
            raise OSError("connection dropped")
        return super().read(1)


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkpoint"
        self.revision = "a" * 40
        self.files = {"config.json": b'{"model_type":"fixture"}',
                      "tokenizer.json": b'{"fixture":true}', "model.safetensors": b"fixture weights"}
        siblings = []
        for name, payload in self.files.items():
            row = {"rfilename": name, "size": len(payload),
                   "blobId": hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()}
            if name == "model.safetensors":
                row["lfs"] = {"sha256": news.sha(payload)}
            siblings.append(row)
        self.metadata = {"sha": self.revision, "siblings": siblings}
        self.bad_name, self.bad_body = None, None
        spec = {"repository": "fixture/checkpoint", "revision": self.revision,
                "weight_sha256": news.sha(self.files["model.safetensors"])}
        patch = mock.patch.dict(fetch.CANDIDATES, {"granite97m": spec})
        patch.start()
        self.addCleanup(patch.stop)
        request_patch = mock.patch.object(fetch, "_request", side_effect=self.request)
        request_patch.start()
        self.addCleanup(request_patch.stop)

    def request(self, url):
        if "/api/" in url:
            return io.BytesIO(json.dumps(self.metadata).encode())
        name = url.split(f"/resolve/{self.revision}/", 1)[1]
        if name == self.bad_name:
            return self.bad_body() if callable(self.bad_body) else io.BytesIO(self.bad_body)
        return io.BytesIO(self.files[name])

    def run_fetch(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return fetch.fetch_checkpoint("granite97m", self.root)

    def test_successful_download_is_idempotent_with_mutable_api_counters(self):
        first = self.run_fetch()
        self.metadata["downloads"] = 100
        self.assertEqual(self.run_fetch(), first)
        self.assertEqual({p.name for p in self.root.iterdir()}, set(self.files))
        self.assertFalse(first["quality_qualified"])

    def test_failed_download_cleans_only_its_partial_and_can_retry(self):
        for bad in (lambda: BrokenResponse(b"broken"), b"too long" * 100, b"x" * len(self.files["config.json"])):
            with self.subTest(body=type(bad).__name__):
                self.bad_name, self.bad_body = "config.json", bad
                with self.assertRaises((OSError, ValueError)):
                    self.run_fetch()
                self.assertFalse((self.root / "config.json.partial").exists())
                self.assertFalse((self.root / "config.json").exists())
        self.bad_name = None
        self.run_fetch()

    def test_preexisting_partial_and_wrong_final_are_preserved(self):
        self.root.mkdir()
        partial = self.root / "config.json.partial"
        partial.write_bytes(b"untrusted partial")
        with self.assertRaises(FileExistsError):
            self.run_fetch()
        self.assertEqual(partial.read_bytes(), b"untrusted partial")
        partial.unlink()
        final = self.root / "config.json"
        final.write_bytes(b"wrong final")
        with self.assertRaises(ValueError):
            self.run_fetch()
        self.assertEqual(final.read_bytes(), b"wrong final")

    def test_revision_and_weight_pin_mismatch_precede_destination_creation(self):
        self.metadata["sha"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "immutable revision"):
            self.run_fetch()
        self.assertFalse(self.root.exists())
        self.metadata["sha"] = self.revision
        self.metadata["siblings"][-1]["lfs"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source pin"):
            self.run_fetch()
        self.assertFalse(self.root.exists())

    def test_unverified_extra_and_hardlinked_files_are_rejected(self):
        self.root.mkdir()
        extra = self.root / "unexpected.bin"
        extra.write_bytes(b"unregistered bytes")
        with self.assertRaisesRegex(ValueError, "unverified"):
            self.run_fetch()
        self.assertFalse(self.root.with_name(self.root.name + ".acquisition.json").exists())
        extra.unlink()
        os.link(self.root / "config.json", self.root.parent / "alias.json")
        with self.assertRaisesRegex(ValueError, "unaliased"):
            self.run_fetch()


if __name__ == "__main__":
    unittest.main()
