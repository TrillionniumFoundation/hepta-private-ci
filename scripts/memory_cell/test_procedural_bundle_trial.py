"""Explicit encoder/reader doubles; no pretrained score or independent review."""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from bundle_trial import read, run_reader
from native import Document, Question, digest
from procedural_bundle_trial import audit, configuration, oracle_conditions, plan_trial
from test_bundle_trial import TestReaderDouble
from test_procedural_observations import fixture_capture


class EncoderDouble:
    identity = "fixture-not-pretrained"

    def encode(self, texts):
        vectors = []
        for text in texts:
            vector = np.array([text.lower().count(word) + 1 for word in ("transport", "format", "revision b", "revision a")], dtype=np.float32)
            vectors.append(vector / np.linalg.norm(vector))
        return np.asarray(vectors)


class ProceduralBundleTests(unittest.TestCase):
    def prepare(self, root):
        data = root / "observed"
        fixture_capture(data, 1)
        pin = hashlib.sha256((data / "corpus.json").read_bytes()).hexdigest()
        out = root / "plan"
        with patch.dict("os.environ", {"HEPTA_MEMORY_TESTED_COMMIT": "a" * 40}):
            plan = plan_trial(data, None, out, corpus_sha=pin, encoder=EncoderDouble())
        ready = json.loads((out / "READY.json").read_text())
        return plan, out, ready

    def test_old_and_current_revisions_survive_all_nonoracle_selections(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, output, _ = self.prepare(Path(tmp))
            case = plan["cases"][0]
            self.assertEqual(len(case["originals"]), 4)
            self.assertEqual(len(case["conditions"]), 13)
            full = case["conditions"]["observed_complete"]
            self.assertEqual(len(full["delivered_evidence"]), 2)
            self.assertTrue(all("revision B" in s["excerpt"] for s in full["delivered_evidence"]))
            for name in ("observed_missing_transport", "observed_missing_format"):
                self.assertEqual(len(case["conditions"][name]["delivered_evidence"]), 1)
                self.assertTrue(case["conditions"][name]["world_answerability_unchanged"])
            self.assertEqual(len(case["conditions"]["ranked4"]["delivered_evidence"]), 4)
            self.assertEqual(case["conditions"]["ranked4"]["bundle_digest"], case["conditions"]["ranked4_large"]["bundle_digest"])
            self.assertEqual(len(list(output.glob("*.sqlite"))), 1)

    def test_census_generated_before_scoring_and_model_text_is_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, planned, ready = self.prepare(root)
            model = TestReaderDouble()
            original_read = read

            def delayed(path, expected=None):
                if path.name == "labels.json":
                    self.assertEqual(len(model.calls), 13)
                    self.assertEqual(len((root / "execution/raw-answers.jsonl").read_text().splitlines()), 13)
                return original_read(path, expected)

            with patch("bundle_trial.read", side_effect=delayed):
                result = run_reader(planned / "plan.json", planned / "labels.json", model, root / "execution",
                                    plan_sha=ready["plan_sha256"], labels_sha=ready["labels_sha256"])
            self.assertEqual(result["raw_census"], 13)
            report = audit(planned / "plan.json", planned / "labels.json", root / "execution", root / "audit.json",
                           plan_sha=ready["plan_sha256"], labels_sha=ready["labels_sha256"])
            self.assertFalse(report["answer_commands_executed"])
            self.assertFalse(report["production_accepted"])
            self.assertEqual(sum(v["planned"] for v in report["arms"].values()), 13)
            rows = json.loads((root / "execution/scored-answers.json").read_text())
            rows[0]["answer"] = "changed answer"
            (root / "execution/scored-answers.json").write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                audit(planned / "plan.json", planned / "labels.json", root / "execution", root / "bad.json",
                      plan_sha=ready["plan_sha256"], labels_sha=ready["labels_sha256"])

    def test_configuration_parser_is_conservative_not_a_shell(self):
        for text in ("tcp json", "transport: TCP, format: JSON [E1] [E2]."):
            self.assertEqual(configuration(text), "tcp json")
        for text in ("not tcp json", "udp tcp json", "tcp json; rm -rf /", "I do not have enough evidence."):
            self.assertIsNone(configuration(text))

    def test_oracle_keeps_original_bytes_and_rejects_missing_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, _, _ = self.prepare(Path(tmp))
            case = copy.deepcopy(plan["cases"][0])
            query = Question(**case["question"])
            originals = {d["identity"]: Document(**(d | {"assets": tuple(d["assets"])})) for d in case["originals"]}
            result = oracle_conditions(query, originals, case["frontier"])
            for source in result["observed_complete"]["delivered_evidence"]:
                self.assertEqual(source["excerpt"], originals[source["original_id"]].content)
            del originals["cedar/B/format"]
            with self.assertRaises(ValueError):
                oracle_conditions(query, originals, case["frontier"])


if __name__ == "__main__":
    unittest.main()
