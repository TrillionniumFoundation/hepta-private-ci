"""Behavioral packet-boundary tests. All cases here are synthetic fixtures."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .review_packet import build_review_packet
from . import test_source_pool


class ReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_source_pool.CandidateBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.run_admission()
        self.target = tempfile.TemporaryDirectory()
        self.addCleanup(self.target.cleanup)
        self.output = Path(self.target.name) / "review"
        self.pins = {
            "expected_manifest_sha256": self.fixture.bind("manifest.json")["sha256"],
            "expected_history_sha256": self.fixture.bind("history.json")["sha256"],
        }
        for a, b in (
            ("manifest.json", "CANDIDATES.json"),
            ("history.json", "HISTORY.json"),
        ):
            (self.fixture.root / b).write_bytes((self.fixture.root / a).read_bytes())

    def build(self):
        return build_review_packet(self.fixture.root, self.output, **self.pins)

    def test_public_packet_preserves_inputs_and_excludes_gold_and_roles(self):
        result = self.build()
        public = json.loads((self.output / "public/PACKET.json").read_bytes())
        private = json.loads((self.output / "private/IDENTITY_MAP.json").read_bytes())
        identities = {r["blind_id"]: r for r in private["cases"]}
        cases = {c["id"]: c for c in self.fixture.cases}
        for row in public["cases"]:
            self.assertEqual(set(row), {"blind_id", "text", "image"})
            original = cases[identities[row["blind_id"]]["case_id"]]
            for field in ("text", "image"):
                data = (self.output / "public" / row[field]["path"]).read_bytes()
                self.assertEqual(
                    data, (self.fixture.root / original[field]["path"]).read_bytes()
                )
                self.assertEqual(hashlib.sha256(data).hexdigest(), row[field]["sha256"])
        for path in (self.output / "public").glob("*"):
            self.assertNotIn(b"private fixture answer", path.read_bytes())
        self.assertEqual(
            sorted(p.suffix for p in (self.output / "public").glob("*")),
            [".json", ".png", ".png", ".txt", ".txt"],
        )
        self.assertEqual(result["completed_independent_reviews"], 0)
        self.assertFalse(result["scientific_admission"])

    def test_confirmation_is_rejected_before_creating_packet(self):
        p = self.fixture.root / "CANDIDATES.json"
        manifest = json.loads(p.read_bytes())
        manifest["cases"][0]["project_split"] = "confirmation"
        p.write_text(json.dumps(manifest))
        self.pins["expected_manifest_sha256"] = hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "cannot expose confirmation"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_pin_mismatch_and_existing_target_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "external pin"):
            build_review_packet(
                self.fixture.root,
                self.output,
                **{**self.pins, "expected_manifest_sha256": "0" * 64},
            )
        self.build()
        before = (self.output / "public/PACKET.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual((self.output / "public/PACKET.json").read_bytes(), before)

    def test_source_pool_is_never_an_output_destination(self):
        with self.assertRaisesRegex(ValueError, "must not mutate"):
            build_review_packet(
                self.fixture.root, self.fixture.root / "review", **self.pins
            )


if __name__ == "__main__":
    unittest.main()
