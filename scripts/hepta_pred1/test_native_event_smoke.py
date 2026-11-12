"""Refusal controls only; positive bridge qualification requires Rust output."""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from .native_event_smoke import PRODUCER_TEST, run_fixture_smoke


@unittest.skipUnless(
    hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK"),
    "Unix native fixture path reader",
)
class NativeEventSmokeRefusalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.fixture = self.root / "fixture"
        self.fixture.mkdir(mode=0o700)
        self.output = self.root / "output"
        self.manifest = {
            "schema": "hepta-pred-native-fixture-v1",
            "source": "native_test_fixture",
            "expected_owner": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
            "fact_file": "native-fact.json",
            "fact_sha256": "0" * 64,
            "producer_test": PRODUCER_TEST,
            "fixture_only": True,
            "independent_effect_labels": 0,
        }

    def test_missing_native_output_fails_without_synthetic_fallback_or_report(self):
        with self.assertRaises(FileNotFoundError):
            run_fixture_smoke(self.fixture, self.output)
        (self.fixture / "manifest.json").write_text(json.dumps(self.manifest))
        with self.assertRaises(FileNotFoundError):
            run_fixture_smoke(self.fixture, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_source_producer_filename_and_label_claims_are_rejected(self):
        for field, value in (
            ("source", "synthetic_fallback"),
            ("producer_test", "unrelated_test"),
            ("fact_file", "../other.json"),
            ("fixture_only", False),
            ("independent_effect_labels", 1),
            ("independent_effect_labels", False),
        ):
            manifest = {**self.manifest, field: value}
            (self.fixture / "manifest.json").write_text(json.dumps(manifest))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                run_fixture_smoke(self.fixture, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_or_non_native_bytes_never_emit_a_bridge_pass(self):
        # Deliberately invalid input; this control must never reach readback.
        raw = b"{}"
        path = self.fixture / "native-fact.json"
        path.write_bytes(raw)
        for digest in ("0" * 64, sha256(raw).hexdigest()):
            manifest = {**self.manifest, "fact_sha256": digest}
            (self.fixture / "manifest.json").write_text(json.dumps(manifest))
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                run_fixture_smoke(self.fixture, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
