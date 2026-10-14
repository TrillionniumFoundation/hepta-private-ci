"""Real physical Encoder adapter boundary tests; no synthetic pretrained execution."""
import tempfile
from pathlib import Path
from hashlib import sha256
import unittest

from amcn_core import Evidence, Refused
from amcn_native import build_inputs, run_train_once


def sha(text):
    return sha256(text.encode()).hexdigest()


def row(name, split):
    content = "observed lock acquisition was circular"
    ev = Evidence(name, "root-" + name, "lab", 1, content, sha(content), "g1")
    return {"row_id": name, "question": "What caused the circular lock?",
            "evidence": ev, "family": split + "-source-family", "split": split}


class RealOwnerAdapterBoundary(unittest.TestCase):
    def test_exact_question_and_source_binding(self):
        rows = [row("t1", "train"), row("f1", "future_a")]
        prepared, cases = build_inputs(rows, scope="lab", generation="g1")
        self.assertEqual([r.input_sha256 for r in prepared],
                         [c.input_digest for c in cases])
        self.assertIn("source_content_sha256", cases[0].text)
        self.assertIn("What caused", cases[0].text)
        self.assertNotIn("label", cases[0].text)
        modified = list(rows)
        changed = dict(modified[1])
        changed["question"] = "What happened afterward?"
        modified[1] = changed
        self.assertNotEqual(build_inputs(modified, scope="lab", generation="g1")[0][1].input_sha256,
                            prepared[1].input_sha256)

    def test_no_pretrained_snapshot_no_execution_or_artifact(self):
        rows = [row("t1", "train"), row("t2", "train")]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "sealed"
            with self.assertRaises(Exception):
                run_train_once(Path(temp) / "missing_model",
                               {"kind": "encoder", "files": {}}, rows,
                               {"t1": 1, "t2": 0},
                               scope="lab", generation="g1",
                               output_dir=target)
            self.assertFalse(target.exists())

    def test_unregistered_fields_and_cross_scope_fail(self):
        rows = [row("t1", "train"), row("f1", "future_a")]
        broken = [dict(rows[0], label=1), rows[1]]
        with self.assertRaises(Refused):
            build_inputs(broken, scope="lab", generation="g1")
        with self.assertRaises(Refused):
            build_inputs(rows, scope="foreign", generation="g1")
        with self.assertRaises(Refused):
            build_inputs(rows, scope="lab", generation="g2")


if __name__ == "__main__":
    unittest.main()
