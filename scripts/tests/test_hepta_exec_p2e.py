"""Synthetic adversarial tests of the auditor; not Rust execution evidence."""
from pathlib import Path
import copy
import importlib.util
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("p2e", ROOT / "scripts/hepta_exec_p2e.py")
p2e = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p2e)
CORPUS = ROOT / "qualification/codex-exec-p2e/corpus.json"


class AuditorTests(unittest.TestCase):
    def setUp(self):
        self.corpus = p2e.load_corpus(CORPUS)
        self.hepta = {c["id"]: {"id": c["id"], "accepted": c["hepta_accepts"],
                               "effect_authority": False} for c in self.corpus["cases"]}
        self.native = {c["id"]: {"id": c["id"], "accepted": c["native_accepts"],
                                "projection": p2e.expected_projection(c)} for c in self.corpus["cases"]}

    def test_complete_synthetic_rows_only_test_the_auditor(self):
        result = p2e.audit(self.corpus, self.hepta, self.native, self.native)
        self.assertEqual(result["cases"], 50)
        self.assertFalse(result["physical_dispatch"])
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["performance_measured"])

    def test_missing_native_row_rejects(self):
        del self.native["minimal"]
        with self.assertRaises(ValueError):
            p2e.audit(self.corpus, self.hepta, self.native, self.native)

    def test_extra_case_rejects(self):
        self.hepta["invented"] = self.hepta["minimal"]
        with self.assertRaises(ValueError):
            p2e.audit(self.corpus, self.hepta, self.native, self.native)

    def test_accepted_authority_or_integer_false_rejects(self):
        for authority in (True, 0, None, "false"):
            with self.subTest(authority=authority):
                self.hepta["minimal"]["effect_authority"] = authority
                with self.assertRaises(ValueError):
                    p2e.audit(self.corpus, self.hepta, self.native, self.native)

    def test_unknown_result_field_rejects(self):
        self.native["minimal"]["privileged"] = False
        with self.assertRaises(ValueError):
            p2e.audit(self.corpus, self.hepta, self.native, self.native)

    def test_native_semantic_change_rejects(self):
        changed = copy.deepcopy(self.native)
        changed["minimal"]["projection"]["sandbox"] = {"pretend": "enforced"}
        with self.assertRaises(ValueError):
            p2e.audit(self.corpus, self.hepta, self.native, changed)

    def test_native_acceptance_change_rejects(self):
        changed = copy.deepcopy(self.native)
        changed["empty_argv"]["accepted"] = False
        with self.assertRaises(ValueError):
            p2e.audit(self.corpus, self.hepta, self.native, changed)

    def test_corpus_tamper_and_symlink_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.json"
            changed.write_bytes(CORPUS.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                p2e.load_corpus(changed)
            link = Path(directory) / "link.json"
            link.symlink_to(CORPUS)
            with self.assertRaises(ValueError):
                p2e.load_corpus(link)

    def test_duplicate_json_rejects(self):
        with self.assertRaises(ValueError):
            json.loads('{"id":1,"id":2}', object_pairs_hook=p2e.unique_object)

    def test_native_logs_need_unique_rows_and_success_footer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.log"
            row = 'P2E_NATIVE_ROW {"id":"minimal","accepted":true,"projection":null}\n'
            path.write_text(row)
            with self.assertRaises(ValueError):
                p2e.rows(path, "P2E_NATIVE_ROW ")
            path.write_text(row * 2 + "test result: ok. 1 passed; 0 failed\n")
            with self.assertRaises(ValueError):
                p2e.rows(path, "P2E_NATIVE_ROW ")
            path.write_text("test probe ... " + row + "test result: ok. 1 passed; 0 failed\n")
            self.assertEqual(set(p2e.rows(path, "P2E_NATIVE_ROW ")), {"minimal"})


if __name__ == "__main__":
    unittest.main()
