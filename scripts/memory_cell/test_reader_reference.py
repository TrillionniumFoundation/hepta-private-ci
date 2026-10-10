"""Model-free integrity tests; actual pretrained calls run separately in CI."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest

from reader_reference import catalogue, summarize, verify_files


def item(name, raw=b"ok", lfs=False):
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return Obj(
        rfilename=name,
        size=len(raw),
        blob_id=blob,
        lfs=Obj(sha256=sha) if lfs else None,
    )


def info():
    return Obj(
        sha="a" * 40,
        siblings=[
            item("config.json"),
            item("tokenizer_config.json"),
            item("model.safetensors", lfs=True),
        ],
    )


def record(q="q", arm="empty"):
    return dict(
        question_id=q,
        arm=arm,
        status="succeeded",
        answer="blue [E1]",
        f1=0.5,
        receipt=dict(
            reader_identity="model",
            reader_profile="profile",
            input_tokens=12,
            generated_tokens=3,
            seconds=0.25,
        ),
    )


class ReferenceTests(unittest.TestCase):
    def test_revision_and_required_files_are_checked(self):
        with self.assertRaises(ValueError):
            catalogue(info(), "b" * 40)
        value = info()
        value.siblings.pop()
        with self.assertRaises(ValueError):
            catalogue(value, value.sha)

    def test_duplicate_and_bad_metadata_reject(self):
        for variant in ("duplicate", "bool-size", "digest", "oversize"):
            value = info()
            if variant == "duplicate":
                value.siblings.append(value.siblings[0])
            elif variant == "bool-size":
                value.siblings[0].size = True
            elif variant == "oversize":
                value.siblings[0].size = 13 * 1024**3
            else:
                value.siblings[0].blob_id = "unknown"
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                catalogue(value, value.sha)

    def test_downloaded_bytes_must_match_both_git_and_lfs(self):
        entries = catalogue(info(), "a" * 40)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in entries:
                (root / name).write_bytes(b"ok")
            verify_files(root, entries)
            for name in entries:
                (root / name).write_bytes(b"no")
                with self.assertRaises(ValueError):
                    verify_files(root, entries)
                (root / name).write_bytes(b"ok")

    def test_shards_cannot_escape_staged_catalogue(self):
        value = info()
        raw = json.dumps(dict(weight_map={"w": "../model.safetensors"})).encode()
        value.siblings.append(item("model.safetensors.index.json", raw))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = catalogue(value, value.sha)
            for name in entries:
                (root / name).write_bytes(raw if name.endswith("index.json") else b"ok")
            with self.assertRaises(ValueError):
                verify_files(root, entries)

    def test_symlink_is_not_a_verified_model(self):
        entries = catalogue(info(), "a" * 40)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in entries:
                (root / name).write_bytes(b"ok")
            (root / "config.json").unlink()
            (root / "config.json").symlink_to(root / "tokenizer_config.json")
            with self.assertRaises(ValueError):
                verify_files(root, entries)

    def test_unavailable_stays_in_denominator_and_precision_is_unknown(self):
        rows = [
            record(),
            dict(question_id="missing", arm="empty", status="unavailable"),
        ]
        s = summarize(rows)["empty"]
        self.assertEqual((s["planned"], s["succeeded"], s["unavailable"]), (2, 1, 1))
        self.assertEqual(
            (s["all_planned_f1_lower"], s["all_planned_f1_upper"]), (0.25, 0.75)
        )
        self.assertEqual(
            (s["input_tokens"], s["output_tokens"], s["read_seconds"]), (12, 3, 0.25)
        )
        self.assertIsNone(s["semantic_citation_precision"])

    def test_unknown_cost_or_score_cannot_be_zeroed(self):
        for field, value in (("seconds", float("nan")), ("input_tokens", True)):
            row = record()
            row["receipt"][field] = value
            with self.assertRaises(ValueError):
                summarize([row])
        for value in (None, float("nan"), True):
            row = record()
            row["f1"] = value
            with self.assertRaises(ValueError):
                summarize([row])

    def test_duplicate_or_mixed_reader_rejected(self):
        with self.assertRaises(ValueError):
            summarize([record(), record()])
        row = deepcopy(record(q="other"))
        row["receipt"]["reader_identity"] = "different"
        with self.assertRaises(ValueError):
            summarize([record(), row])
        with self.assertRaises(ValueError):
            summarize([])


if __name__ == "__main__":
    unittest.main()
