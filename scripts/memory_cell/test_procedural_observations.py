"""Compiler protocol tests use explicit process doubles, NOT compiler evidence."""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from procedural_observations import capture, checked_outcomes, code, invoke, load_observations


def compiler_double(argv, **kwargs):
    if "--version" in argv:
        return types.SimpleNamespace(stdout=b"rustc FIXTURE-NOT-A-COMPILER\n", returncode=0)
    source = (Path(kwargs["cwd"]) / "source.rs").read_text()
    expected = dict(re.findall(r'cfg\(not\((\w+) = "(\w+)"\)\)', source))
    actual = dict(re.findall(r'(\w+)="(\w+)"', " ".join(argv)))
    ok = all(actual.get(key) == value for key, value in expected.items())
    kwargs["stderr"].write(b"explicit fixture success" if ok else b"explicit fixture failure")
    return types.SimpleNamespace(returncode=0 if ok else 1)


def fixture_capture(path, count=2):
    with patch("procedural_observations.shutil.which", return_value="/fixture/compiler"), patch("procedural_observations.subprocess.run", side_effect=compiler_double):
        return capture(path, count=count)


def rewrite_corpus(root, corpus):
    (root / "corpus.json").write_text(json.dumps(corpus))
    return hashlib.sha256((root / "corpus.json").read_bytes()).hexdigest()


class CompilerObservationTests(unittest.TestCase):
    def test_complete_census_is_reconstructed_from_all_actual_exit_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "observed"
            corpus = fixture_capture(root)
            pinned = hashlib.sha256((root / "corpus.json").read_bytes()).hexdigest()
            observed = load_observations(root, expected_corpus_sha=pinned)
            self.assertEqual(json.loads(json.dumps(corpus)), observed)
            self.assertEqual(corpus["compiler_invocations"], 32)
            self.assertFalse(corpus["independent_observations"])
            self.assertTrue(all("question" not in case for case in corpus["cases"]))
            self.assertEqual(len(list((root / "observations").glob("*/source.rs"))), 32)
            with self.assertRaises(FileExistsError):
                fixture_capture(root)

    def test_mutated_projection_or_exit_result_cannot_become_observed_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "observed"
            original = fixture_capture(root, 1)
            for mutate in (
                lambda x: x["cases"][0]["documents"][0].update(content="invented outcome"),
                lambda x: x["cases"][0]["revisions"]["B"]["records"][0].update(source="pub fn invented() {}"),
                lambda x: x["cases"][0]["revisions"]["B"]["records"][0].update(returncode=True),
                lambda x: x["cases"][0]["revisions"]["B"]["records"].pop(),
            ):
                corpus = copy.deepcopy(original)
                mutate(corpus)
                pinned = rewrite_corpus(root, corpus)
                with self.assertRaises(ValueError):
                    load_observations(root, expected_corpus_sha=pinned)

    def test_component_and_joint_results_must_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture_capture(Path(tmp) / "o", 1)
            rows = data["cases"][0]["revisions"]["B"]["records"]
            self.assertEqual(checked_outcomes(rows, "cedar", "B"), {"transport": "tcp", "format": "json"})
            joint = next(r for r in rows if r["kind"] == "joint" and r["returncode"] == 0)
            joint["returncode"] = 1
            with self.assertRaises(ValueError):
                checked_outcomes(rows, "cedar", "B")

    def test_missing_duplicate_and_foreign_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture_capture(Path(tmp) / "o", 1)
            rows = data["cases"][0]["revisions"]["B"]["records"]
            for bad in (rows[:-1], rows + [rows[0]], [rows[0] | {"revision": "A"}, *rows[1:]]):
                with self.assertRaises(ValueError):
                    checked_outcomes(bad, "cedar", "B")

    def test_only_bounded_static_program_inputs_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, patch("subprocess.run") as call:
            for identity, flags in (("../bad", {"transport": "tcp"}), ("valid", {"transport": "tcp; rm"})):
                with self.assertRaises(ValueError):
                    invoke(Path(tmp), "/compiler", identity, "source", flags)
            call.assert_not_called()
        with self.assertRaises(ValueError):
            code({"unknown": "value"})
        with self.assertRaises(ValueError):
            capture(Path("unused"), count=True)

    def test_timeout_is_retained_and_not_a_negative_training_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["compiler"], 20)):
                with self.assertRaises(ValueError):
                    invoke(root, "/compiler", "timeout", code({"transport": "tcp"}), {"transport": "tcp"})
            row = json.loads((root / "timeout/result.json").read_text())
            self.assertEqual((row["status"], row["returncode"]), ("timeout", None))

    def test_source_output_and_external_pin_are_all_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "o"
            corpus = fixture_capture(root, 1)
            pin = hashlib.sha256((root / "corpus.json").read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                load_observations(root, expected_corpus_sha="0" * 64)
            identity = corpus["cases"][0]["revisions"]["B"]["records"][0]["identity"]
            file = root / "observations" / identity / "stderr.txt"
            file.write_text("changed after the compiler returned")
            with self.assertRaises(ValueError):
                load_observations(root, expected_corpus_sha=pin)


if __name__ == "__main__":
    unittest.main()
