"""Adversarial contract tests. Synthetic rows are not new model capability data."""

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from reader_capacity_original_replay import (
    opened,
    replay,
    run_worker,
    sha,
    strict_identifier,
    strict_json,
)


def make_zip(files):
    contents = dict(files)
    contents["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(value).hexdigest()}  {name}\n"
        for name, value in sorted(files.items())
    ).encode("ascii")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    return buffer.getvalue()


class OriginalReaderCapacityTests(unittest.TestCase):
    def test_response_grammar_is_exact_not_label_hacking(self):
        self.assertEqual(strict_identifier("site_1234abcd [E1]"), "site_1234abcd")
        self.assertEqual(strict_identifier("mode_1234abcd [E1] [E2]."), "mode_1234abcd")
        for malformed in (
            "[site_1234abcd]",
            "Answer: site_1234abcd",
            "site_1234abcd [E0]",
            "site_1234abcd extra",
            "site_1234abcd [E1] or site_1234abcd",
            "site_deadbeef [E1] [injected]",
        ):
            with self.subTest(answer=malformed):
                self.assertIsNone(strict_identifier(malformed))

    def test_duplicate_and_nonfinite_json_are_forbidden(self):
        for content in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                strict_json(content)

    def test_original_file_outer_and_inner_sha256_verified(self):
        payload = make_zip({"one.json": b'{"ok":true}\n'})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.zip"
            path.write_bytes(payload)
            self.assertEqual(
                opened(path, sha(payload), count=1)["one.json"], b'{"ok":true}\n'
            )
            with self.assertRaisesRegex(ValueError, "external original ZIP"):
                opened(path, "f" * 64, count=1)

    def test_inner_edit_with_consistent_new_outer_sha_is_still_rejected(self):
        payload = make_zip({"one.json": b"{}"})
        with zipfile.ZipFile(io.BytesIO(payload)) as original:
            contents = {item: original.read(item) for item in original.namelist()}
        contents["one.json"] = b'{"changed":true}'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for name, value in contents.items():
                    archive.writestr(name, value)
            with self.assertRaisesRegex(ValueError, "inner member SHA256"):
                opened(path, sha(path.read_bytes()), count=1)

    def test_traversal_and_duplicate_zip_members_rejected(self):
        bad = make_zip({"../path_escape.json": b"{}"})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.zip"
            path.write_bytes(bad)
            with self.assertRaisesRegex(ValueError, "invalid original ZIP member"):
                opened(path, sha(bad), count=1)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("one.json", b"{}")
                    archive.writestr("one.json", b"{}")
                    archive.writestr("SHA256SUMS", b"")
            with self.assertRaises(ValueError):
                opened(path, sha(path.read_bytes()), count=2)

    def test_missing_manifest_and_incomplete_census_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("one.json", b"{}")
            with self.assertRaises(ValueError):
                opened(path, sha(path.read_bytes()), count=1)
            payload = make_zip({"one.json": b"{}"})
            path.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "census"):
                opened(path, sha(payload), count=2)

    def test_workers_are_bounded_before_executing_any_process(self):
        with self.assertRaisesRegex(ValueError, "bounded program request"):
            run_worker(
                Path("/nonexistent/executable.py"), {"large": "x" * 30000}, "mode"
            )

    def test_absent_inputs_cannot_create_fake_new_model_results(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.zip"
            with self.assertRaises(ValueError):
                replay(path, path, path)


if __name__ == "__main__":
    unittest.main()
