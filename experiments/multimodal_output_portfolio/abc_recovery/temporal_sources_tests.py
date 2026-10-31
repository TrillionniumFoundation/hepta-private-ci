"""Synthetic tests for provenance gates and actual retained ZIP bytes."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
import zipfile

from .temporal_sources import RangeReader, entry, freeze_selection, pick_clip, read_member
from .temporal_source_repair import verify_original_tar


class MemoryResponse(io.BytesIO):
    def __init__(self, value, first, last, total, corrupt_range=False):
        super().__init__(value)
        self.status = 206
        self.headers = {"Content-Range": f"bytes {first}-{last}/{total + int(corrupt_range)}", "ETag": "stable"}

    def geturl(self):
        return "https://zenodo.org/api/records/3625687/files/test.zip/content"


class TemporalSourceTests(unittest.TestCase):
    def fixture(self, output, corrupt_range=False):
        memory = io.BytesIO()
        values = {"s1/z.mpg": b"actual chosen bytes" * 20, "s1/a.mpg": b"second bytes" * 20,
                  "__MACOSX/s1/._z.mpg": b"not a source", "s2/z.mpg": b"wrong speaker"}
        with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in values.items():
                archive.writestr(name, value)
        raw = memory.getvalue()

        def transport(request, timeout):
            first, last = map(int, request.headers["Range"].removeprefix("bytes=").split("-"))
            return MemoryResponse(raw[first:last + 1], first, last, len(raw), corrupt_range)

        budget = {"requests": 0, "transferred_bytes": 0,
                  "limits": {"maximum_range_bytes": 100000, "maximum_total_transferred_bytes": 1000000,
                             "maximum_member_bytes": 2000, "maximum_member_compressed_bytes": 2000}}
        meta = {"key": "test.zip", "size": len(raw), "links": {"self": MemoryResponse(b"", 0, 0, 0).geturl()}}
        (output / "ranges").mkdir()
        reader = RangeReader(meta, output, budget, transport)
        return reader, budget, values

    def test_exact_byte_replay_and_freeze_before_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            reader, budget, values = self.fixture(output)
            with zipfile.ZipFile(reader) as archive:
                chosen, count = pick_clip(archive.infolist(), 1)
                self.assertEqual(count, 2)
                with self.assertRaisesRegex(ValueError, "frozen"):
                    read_member(archive, reader, entry(chosen), output / "early.mpg")
                self.assertFalse((output / "early.mpg").exists())
                requests_before = budget["requests"]
                freeze_selection(output, "protocol-pin", "metadata-pin", [{"clip": entry(chosen)}], budget)
                actual = read_member(archive, reader, entry(chosen), output / "kept.mpg")
                self.assertEqual((output / "kept.mpg").read_bytes(), values[chosen.filename])
                self.assertEqual(actual["sha256"], hashlib.sha256(values[chosen.filename]).hexdigest())
                rows = [json.loads(line) for line in (output / "range-requests.jsonl").read_text().splitlines()]
                self.assertTrue(all(row["phase"] == "zip_directory" for row in rows[:requests_before]))
                self.assertTrue(all(row["phase"] == "selected_member_payload" for row in rows[requests_before:]))
                self.assertEqual(sum(row["bytes"] for row in rows), budget["transferred_bytes"])
                for row in rows:
                    self.assertEqual(hashlib.sha256((output / row["retained_response"]).read_bytes()).hexdigest(), row["sha256"])
                with self.assertRaises(FileExistsError):
                    read_member(archive, reader, entry(chosen), output / "kept.mpg")
                (output / "selected-source-manifest.json").write_text("changed registration")
                with self.assertRaisesRegex(ValueError, "frozen"):
                    read_member(archive, reader, entry(chosen), output / "late.mpg")

    def test_invalid_remote_content_range_cannot_be_parsed_as_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            reader, budget, _ = self.fixture(output, corrupt_range=True)
            with self.assertRaisesRegex(ValueError, "Range response mismatch"):
                zipfile.ZipFile(reader)
            receipt = json.loads((output / "range-requests.jsonl").read_text())
            self.assertIn("error", receipt)
            self.assertGreater(budget["transferred_bytes"], 0)
            self.assertTrue((output / receipt["retained_response"]).is_file())

    def test_author_annotation_content_required_beyond_matching_filenames(self):
        buffer = io.BytesIO()
        original = b"0 2500 sil\n2500 22500 blue\n22500 75000 sil\n"
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo("align/source.align")
            info.size = len(original)
            archive.addfile(info, io.BytesIO(original))
        gate = {"source_original_ticks_per_second": 25000, "zenodo_ticks_per_second": 1000}
        recovered, report = verify_original_tar(buffer.getvalue(), b"0 100 sil\n100 900 blue\n900 3000 sil\n",
                                                "source", ["source"], gate)
        self.assertEqual(recovered, original)
        self.assertTrue(report["selected_words_and_boundaries_match_exactly"])
        strict = {"source_original_ticks_per_second": 25000, "zenodo_ticks_per_second": 25000,
                  "require_exact_original_bytes": True}
        _, identity = verify_original_tar(buffer.getvalue(), original, "source", ["source"], strict)
        self.assertTrue(identity["original_and_zenodo_bytes_identical"])
        with self.assertRaisesRegex(ValueError, "content or clock"):
            verify_original_tar(buffer.getvalue(), original.replace(b"\n", b"\r\n"), "source", ["source"], strict)
        for changed in (b"0 100 sil\n100 900 red\n900 3000 sil\n",
                        b"0 100 sil\n100 901 blue\n901 3000 sil\n"):
            with self.assertRaisesRegex(ValueError, "content or clock"):
                verify_original_tar(buffer.getvalue(), changed, "source", ["source"], gate)
        with self.assertRaisesRegex(ValueError, "universe"):
            verify_original_tar(buffer.getvalue(), b"0 100 sil\n100 900 blue\n900 3000 sil\n",
                                "source", ["source", "missing"], gate)


if __name__ == "__main__":
    unittest.main()
