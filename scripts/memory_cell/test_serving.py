"""Consumer boundary tests. Test doubles never count as a real model benchmark."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from serving_worker import CODE_FILES, FIELDS, code_digest, validate_job


def job():
    value = {
        key: hashlib.sha256(key.encode()).hexdigest()
        for key in FIELDS
        if key.endswith("digest")
    }
    value.update(
        schema="hepta.memory-serving.job.v1",
        request_id="request.1",
        subject_id="agent.1",
        destination_id="node.1",
        route_generation=7,
        question="What did the permitted memory teach?",
        question_time="2026-10-09T00:00:00Z",
        deadline_unix_millis=123456,
    )
    return value


class ServingTests(unittest.TestCase):
    def test_exact_bound_request_roundtrip_and_no_plaintext_replay_channel(self):
        value = job()
        self.assertEqual(validate_job(json.dumps(value).encode()), value)
        for key in (
            "history",
            "training_text",
            "shell",
            "model_path",
            "grant",
            "signing_key",
        ):
            changed = dict(value, **{key: "untrusted"})
            with self.assertRaises(ValueError):
                validate_job(json.dumps(changed).encode())

    def test_duplicate_fields_bad_types_and_noncanonical_identity_reject(self):
        value = job()
        raw = json.dumps(value).encode()
        with self.assertRaises(ValueError):
            validate_job(b'{"schema":"other",' + raw[1:])
        for key, bad in [
            ("route_generation", True),
            ("deadline_unix_millis", 0),
            ("runtime_digest", "0" * 64),
            ("base_digest", "A" * 64),
            ("question", " "),
            ("question_time", "\0"),
            ("question", "a" * 16385),
        ]:
            with (
                self.subTest(key=key, value=str(bad)[:20]),
                self.assertRaises(ValueError),
            ):
                validate_job(json.dumps(dict(value, **{key: bad})).encode())
        with self.assertRaises(ValueError):
            validate_job(b" " * (256 * 1024 + 1))

    def test_source_tuple_detects_each_dependency_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for key in CODE_FILES:
                (root / key).write_text(key)
            expected = code_digest(root)
            for key in CODE_FILES:
                (root / key).write_text(key + "changed")
                self.assertNotEqual(code_digest(root), expected)
                (root / key).write_text(key)
            (root / CODE_FILES[0]).unlink()
            (root / CODE_FILES[0]).symlink_to(root / CODE_FILES[1])
            with self.assertRaises(ValueError):
                code_digest(root)
