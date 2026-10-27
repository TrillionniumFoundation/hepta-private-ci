#!/usr/bin/env python3
"""Small archive attack controls, with no model or remote artifacts."""

import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.request
import zipfile

import hepta_cumulative_source as source


class RetainedSource(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = self.root / "input.zip"
        self.output = self.root / "output"
        self.output.mkdir()

    def test_selected_bytes_are_verified_again_before_consumption(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("chosen/checkpoint", b"selected")
            archive.writestr("not-selected", b"unused")
        members = source.extract(self.archive, self.output, {"chosen/checkpoint"})
        self.assertFalse((self.output / "not-selected").exists())
        path = source.pinned_member(
            self.output, dict(files=members), "chosen/checkpoint"
        )
        self.assertEqual(path.read_bytes(), b"selected")
        path.write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "evidence member changed"):
            source.pinned_member(self.output, dict(files=members), "chosen/checkpoint")

    def test_traversal_cannot_write_outside_the_owned_output(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("../escaped", b"no")
        with self.assertRaisesRegex(ValueError, "unsafe archive member"):
            source.extract(self.archive, self.output, None)
        self.assertFalse((self.root / "escaped").exists())

    def test_pinned_member_and_expansion_budgets_are_enforced_before_writes(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("one", b"12345")
            archive.writestr("two", b"67890")
        with self.assertRaisesRegex(ValueError, "archive member bound"):
            source.extract(self.archive, self.output, None, maximum_members=1)
        with self.assertRaisesRegex(ValueError, "archive expansion bound"):
            source.extract(
                self.archive, self.output, None, maximum_uncompressed_bytes=9
            )
        self.assertEqual(list(self.output.iterdir()), [])
        observed = source.extract(
            self.archive,
            self.output,
            None,
            maximum_members=2,
            maximum_uncompressed_bytes=10,
        )
        self.assertEqual(set(observed), {"one", "two"})

    def test_link_members_are_not_materialized(self):
        entry = zipfile.ZipInfo("checkpoint")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr(entry, "../outside")
        with self.assertRaisesRegex(ValueError, "nonregular archive member"):
            source.extract(self.archive, self.output, None)
        self.assertFalse((self.output / "checkpoint").exists())

    def test_missing_selected_checkpoint_cannot_count_as_verified(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("different", b"unused")
        with self.assertRaisesRegex(ValueError, "required checkpoint missing"):
            source.extract(self.archive, self.output, {"needed"})

    def test_replaced_index_digest_is_rejected(self):
        path = self.output / "receipt.json"
        path.write_bytes(b"new receipt")
        index = dict(
            files={
                "receipt.json": dict(
                    bytes=11, sha256=hashlib.sha256(b"old receipt").hexdigest()
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "evidence member changed"):
            source.pinned_member(self.output, index, "receipt.json")

    def fake_pin(self):
        pin = dict(
            schema="hepta-cumulative-original-run-pin-v1",
            repository=source.REPOSITORY,
            run_id=123,
            source_sha="a" * 40,
            artifacts={
                "records": dict(
                    id=456,
                    name="records",
                    bytes=10,
                    sha256=hashlib.sha256(b"0123456789").hexdigest(),
                )
            },
        )
        path = self.root / "pin.json"
        path.write_text(json.dumps(pin))
        return pin, SimpleNamespace(pin=path, output=self.root / "fetched")

    def test_authenticated_metadata_redirect_fails_before_any_second_request(self):
        _, args = self.fake_pin()
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://api.github.com/redacted",
            302,
            "Found",
            {"Location": "https://different.example/object"},
            io.BytesIO(),
        )
        with (
            mock.patch.dict(source.os.environ, {"GH_TOKEN": "synthetic-test-token"}),
            mock.patch.object(
                urllib.request, "build_opener", return_value=opener
            ) as build,
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("unowned opener used"),
            ),
            self.assertRaises(urllib.error.HTTPError),
        ):
            source.fetch(args)
        build.assert_called_once_with(source.NoRedirect)
        self.assertEqual(opener.open.call_count, 1)
        record = json.loads((args.output / "source-retention.json").read_bytes())
        self.assertEqual(
            (record["status"], record["stage"]), ("failed", "records-metadata")
        )
        self.assertNotIn("synthetic-test-token", json.dumps(record))

    def test_partial_archive_is_recorded_and_signed_object_receives_no_token(self):
        pin, args = self.fake_pin()
        artifact = pin["artifacts"]["records"]
        metadata = dict(
            workflow_run=dict(id=123, head_sha=pin["source_sha"]),
            name=artifact["name"],
            expired=False,
            size_in_bytes=10,
            digest="sha256:" + artifact["sha256"],
        )
        calls = []

        def response(data):
            result = io.BytesIO(data)
            result.status = 200
            return result

        def opened(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                return response(json.dumps(metadata).encode())
            if len(calls) == 2:
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://objects.example/synthetic-signed-object"},
                    io.BytesIO(),
                )
            self.assertIsInstance(request, str)
            return response(b"short")

        opener = mock.Mock(open=opened)
        with (
            mock.patch.dict(source.os.environ, {"GH_TOKEN": "synthetic-test-token"}),
            mock.patch.object(urllib.request, "build_opener", return_value=opener),
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("unowned opener used"),
            ),
            self.assertRaisesRegex(ValueError, "ZIP checksum"),
        ):
            source.fetch(args)
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            calls[0].get_header("Authorization"), "Bearer synthetic-test-token"
        )
        record = json.loads((args.output / "source-retention.json").read_bytes())
        self.assertEqual(
            (record["status"], record["stage"]), ("failed", "records-archive-download")
        )
        observed = record["archives"][0]
        self.assertEqual(
            (observed["bytes"], observed["sha256"]),
            (5, hashlib.sha256(b"short").hexdigest()),
        )
        self.assertFalse(observed["complete_zip_verified"])
        self.assertNotIn("objects.example", json.dumps(record))

    def test_object_redirect_cannot_downgrade_https_or_create_a_second_fetch(self):
        pin, args = self.fake_pin()
        artifact = pin["artifacts"]["records"]
        metadata = dict(
            workflow_run=dict(id=123, head_sha=pin["source_sha"]),
            name="records",
            expired=False,
            size_in_bytes=10,
            digest="sha256:" + artifact["sha256"],
        )
        calls = []

        def opened(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                result = io.BytesIO(json.dumps(metadata).encode())
                result.status = 200
                return result
            if len(calls) == 2:
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://objects.example/synthetic-signed-object"},
                    io.BytesIO(),
                )
            self.assertIsInstance(request, str)
            raise urllib.error.HTTPError(
                request,
                302,
                "Found",
                {"Location": "http://downgrade.invalid/object"},
                io.BytesIO(),
            )

        with (
            mock.patch.dict(source.os.environ, {"GH_TOKEN": "synthetic-test-token"}),
            mock.patch.object(
                urllib.request, "build_opener", return_value=mock.Mock(open=opened)
            ),
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("unowned opener used"),
            ),
            self.assertRaises(urllib.error.HTTPError),
        ):
            source.fetch(args)
        self.assertEqual(len(calls), 3)
        record = json.loads((args.output / "source-retention.json").read_bytes())
        self.assertEqual(
            (record["status"], record["stage"]), ("failed", "records-archive-download")
        )
        self.assertEqual(record["archives"][0]["bytes"], 0)
        self.assertFalse(record["archives"][0]["complete_zip_verified"])
        self.assertNotIn("downgrade.invalid", json.dumps(record))


if __name__ == "__main__":
    unittest.main()
