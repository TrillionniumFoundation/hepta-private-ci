from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import candidate_coverage as coverage


def bindings():
    return {name: coverage.digest(name) for name in coverage.BINDINGS}


def source(name, states, role="train"):
    return {
        "source_id": name,
        "role": role,
        "state_ids": [coverage.digest(s) for s in states],
    }


def record(name, state, *, positives=(0,), selected=0, role="train", count=2):
    return {
        "source_id": name,
        "role": role,
        "state_id": coverage.digest(state),
        "observation_id": name + "/" + state,
        "observation_sha256": coverage.digest([name, state]),
        "generator_sha256": bindings()["generator_sha256"],
        "bindings_sha256": coverage.digest(bindings()),
        "candidates": {
            "sha256": coverage.digest([name, state, "candidates"]),
            "count": count,
            "positive_indices": list(positives),
            "selection": {"index": selected},
            "pre_cap_unique_count": None,
        },
    }


class CandidateCoverageTests(unittest.TestCase):
    def summarize(self, rows, sources):
        return coverage.summarize(rows, sources, bindings=bindings())

    def test_source_balancing_and_duplicate_state_invariance(self):
        sources = [source("private-a", ["s0", "s1", "s2"]), source("private-b", ["s3"])]
        rows = [
            record("private-a", s, selected=i % 2)
            for i, s in enumerate(["s0", "s1", "s2"])
        ]
        rows.append(record("private-b", "s3", positives=()))
        result = self.summarize(rows, sources)
        self.assertEqual(result["source_equal_means"]["oracle_ceiling"], 0.5)
        self.assertAlmostEqual(result["source_equal_means"]["selected_accuracy"], 1 / 3)
        self.assertAlmostEqual(result["source_equal_means"]["selection_gap"], 1 / 6)
        repeated = {
            **rows[0],
            "observation_id": "repeat",
            "observation_sha256": coverage.digest("repeat"),
        }
        again = self.summarize(rows + [rows[0], repeated], sources)
        self.assertEqual(again["sources"], result["sources"])
        self.assertEqual(again["source_equal_means"], result["source_equal_means"])
        self.assertEqual(
            (again["observed_states"], again["duplicate_state_records"]), (4, 2)
        )
        self.assertNotIn("private-a", json.dumps(again))
        self.assertNotIn("private-b", json.dumps(again))

    def test_missing_source_or_registered_state_never_disappears(self):
        sources = [source("a", ["s0", "s1"]), source("b", ["s2"])]
        result = self.summarize([record("a", "s0")], sources)
        self.assertEqual(
            (
                result["registered_sources"],
                result["registered_states"],
                result["missing_sources"],
            ),
            (2, 3, 1),
        )
        self.assertEqual(
            result["source_equal_means"],
            dict(oracle_ceiling=None, selected_accuracy=None, selection_gap=None),
        )
        self.assertEqual(sum(s["missing_states"] for s in result["sources"]), 2)
        empty = self.summarize([], sources)
        self.assertEqual((empty["observed_states"], empty["missing_sources"]), (0, 2))
        self.assertEqual(empty["source_equal_means"], result["source_equal_means"])

    def test_unknown_labels_selection_and_explicit_abstention_differ(self):
        sources, rows = [source("a", ["s0"])], [record("a", "s0")]
        rows[0]["candidates"]["positive_indices"] = None
        self.assertIsNone(
            self.summarize(rows, sources)["source_equal_means"]["oracle_ceiling"]
        )
        rows[0]["candidates"]["positive_indices"] = [0]
        rows[0]["candidates"]["selection"] = None
        self.assertEqual(
            self.summarize(rows, sources)["source_equal_means"],
            dict(oracle_ceiling=1.0, selected_accuracy=None, selection_gap=None),
        )
        rows[0]["candidates"]["selection"] = {"index": None}
        self.assertEqual(
            self.summarize(rows, sources)["source_equal_means"],
            dict(oracle_ceiling=1.0, selected_accuracy=0.0, selection_gap=1.0),
        )
        rows[0]["candidates"] = None
        result = self.summarize(rows, sources)
        self.assertEqual(
            (
                result["sources"][0]["observed_states"],
                result["sources"][0]["candidate_evidence_unknown"],
            ),
            (1, 1),
        )
        self.assertIsNone(result["source_equal_means"]["selected_accuracy"])

    def test_empty_candidates_remain_in_the_quality_denominator(self):
        sources = [source("a", ["s0", "s1"])]
        rows = [
            record("a", "s0"),
            record("a", "s1", count=0, positives=(), selected=None),
        ]
        result = self.summarize(rows, sources)
        self.assertEqual(
            result["source_equal_means"],
            dict(oracle_ceiling=0.5, selected_accuracy=0.5, selection_gap=0.0),
        )
        self.assertEqual(result["sources"][0]["empty_candidate_sets"], 1)

    def test_cap_saturation_requires_original_count_to_prove_truncation(self):
        sources, rows = [source("a", ["s0"])], [record("a", "s0", count=128)]
        for original, truncated, unknown in ((None, 0, 1), (128, 0, 0), (129, 1, 0)):
            rows[0]["candidates"]["pre_cap_unique_count"] = original
            value = self.summarize(rows, sources)["sources"][0]
            self.assertEqual(
                (
                    value["at_cap_states"],
                    value["known_truncated_states"],
                    value["truncation_unknown"],
                ),
                (1, truncated, unknown),
            )
        rows[0]["candidates"]["pre_cap_unique_count"] = 127
        with self.assertRaises(ValueError):
            self.summarize(rows, sources)

    def test_conflicting_state_or_reused_observation_is_rejected(self):
        sources, rows = [source("a", ["s0"])], [record("a", "s0")]
        changed = deepcopy(rows[0])
        changed["observation_sha256"] = coverage.digest("changed")
        with self.assertRaises(ValueError):
            self.summarize(rows + [changed], sources)
        changed["observation_id"] = "new-observation"
        changed["candidates"]["selection"]["index"] = 1
        with self.assertRaises(ValueError):
            self.summarize(rows + [changed], sources)
        changed["candidates"] = None
        with self.assertRaises(ValueError):
            self.summarize(rows + [changed], sources)

    def test_roles_identity_and_unregistered_states_are_rejected(self):
        sources, rows = [source("a", ["s0"])], [record("a", "s0")]
        for field, value in (
            ("role", "future"),
            ("role", "development"),
            ("state_id", coverage.digest("other")),
            ("source_id", "other"),
            ("generator_sha256", "0" * 64),
            ("raw_text", "PRIVATE"),
        ):
            changed = deepcopy(rows)
            changed[0][field] = value
            with self.assertRaises(ValueError):
                self.summarize(changed, sources)
        with self.assertRaises(ValueError):
            self.summarize([], [source("a", ["s0"], role="confirmation")])
        with self.assertRaises(ValueError):
            self.summarize(rows, sources + sources)
        result = self.summarize(
            [record("a", "s0", role="development")],
            [source("a", ["s0"], role="development")],
        )
        self.assertEqual(result["source_equal_means"]["oracle_ceiling"], 1.0)

    def test_bad_indices_and_counts_do_not_create_false_coverage(self):
        sources, rows = [source("a", ["s0"])], [record("a", "s0")]
        for field, value in (
            ("positive_indices", [True]),
            ("positive_indices", [0, 0]),
            ("positive_indices", [2]),
            ("selection", {"index": 2}),
            ("count", True),
            ("count", 129),
            ("pre_cap_unique_count", True),
        ):
            changed = deepcopy(rows)
            changed[0]["candidates"][field] = value
            with self.assertRaises(ValueError):
                self.summarize(changed, sources)

    def test_all_producer_bindings_are_required_on_every_record(self):
        sources, rows = [source("a", ["s0"])], [record("a", "s0")]
        for name in coverage.BINDINGS:
            changed = bindings()
            changed[name] = coverage.digest("replacement")
            with self.assertRaises(ValueError):
                coverage.summarize(rows, sources, bindings=changed)

    def make_manifest(self, root, rows):
        raw = b"".join((json.dumps(row) + "\n").encode() for row in rows)
        (root / "records.jsonl").write_bytes(raw)
        manifest = dict(
            schema=coverage.SCHEMA,
            sources=[source("private-source", ["s0"])],
            bindings=bindings(),
            candidate_cap=128,
            diagnostic_sha256=coverage.sha(Path(coverage.__file__).read_bytes()),
            records=dict(
                path="records.jsonl", bytes=len(raw), sha256=coverage.sha(raw)
            ),
        )
        return (json.dumps(manifest) + "\n").encode()

    def test_pinned_cli_and_create_only_redacted_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = self.make_manifest(root, [record("private-source", "s0")])
            manifest, output = root / "manifest.json", root / "report.json"
            manifest.write_bytes(raw)
            argv = [
                sys.executable,
                str(Path(coverage.__file__)),
                "--root",
                tmp,
                "--manifest",
                str(manifest),
                "--expected-manifest-sha256",
                coverage.sha(raw),
                "--output",
                str(output),
            ]
            first = subprocess.run(argv, capture_output=True, check=False, text=True)
            self.assertEqual((first.returncode, first.stderr), (0, ""))
            report = output.read_bytes()
            self.assertNotIn(b"private-source", report)
            self.assertEqual(
                json.loads(report)["source_equal_means"]["oracle_ceiling"], 1.0
            )
            second = subprocess.run(argv, capture_output=True, check=False, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), report)

    def test_manifest_source_and_input_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = self.make_manifest(root, [record("private-source", "s0")])
            with self.assertRaises(ValueError):
                coverage.audit(root, raw, "0" * 64)
            changed = json.loads(raw)
            changed["diagnostic_sha256"] = "0" * 64
            changed_raw = json.dumps(changed).encode()
            with self.assertRaises(ValueError):
                coverage.audit(root, changed_raw, coverage.sha(changed_raw))
            (root / "records.jsonl").write_bytes(b"PRIVATE")
            with self.assertRaises(ValueError):
                coverage.audit(root, raw, coverage.sha(raw))
            raw = self.make_manifest(root, [])
            report = coverage.audit(root, raw, coverage.sha(raw))
            self.assertIsNone(report["source_equal_means"]["oracle_ceiling"])

    def test_invalid_role_is_rejected_before_opening_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = self.make_manifest(root, [])
            manifest = json.loads(raw)
            manifest["sources"][0]["role"] = "future"
            raw = json.dumps(manifest).encode()
            with patch.object(
                coverage, "read_pin", side_effect=AssertionError("must not read")
            ) as reader:
                with self.assertRaises(ValueError):
                    coverage.audit(root, raw, coverage.sha(raw))
            reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
