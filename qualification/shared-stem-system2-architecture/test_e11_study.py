"""E11 execute-then-independent-audit tamper and negative-result tests."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from e11_study import audit, execute, strict_json, REPEATS, STUDIES

ROOT = Path(__file__).resolve().parent
E10 = ROOT / "observations" / "E10_EXACT_PAIRED_PARETO_LOCAL_20261015.json"


class E11Study(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = TemporaryDirectory(prefix="hepta-e11-stochastic-")
        cls.dir = Path(cls.work.name)
        cls.original = cls.dir / "original.json"
        cls.sha = execute(str(cls.original))
        cls.src, _ = strict_json(str(cls.original))

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def mutated(self, edit):
        candidate = json.loads(json.dumps(self.src))
        edit(candidate)
        path = self.dir / (self.id().replace(".", "_") + ".json")
        data = (json.dumps(candidate, sort_keys=True, separators=(",", ":"))+"\n").encode()
        path.write_bytes(data)
        return path, sha256(data).hexdigest()

    def test_full_local_source_seal_and_original_e10_no_go(self):
        out = self.dir / "actual-audit.json"
        got = audit(str(self.original), self.sha, str(out), e10_path=str(E10))
        row, digest = strict_json(str(out))
        self.assertEqual(got, digest)
        self.assertTrue(row["all_exact_dense_and_affine_root_outputs_match"])
        self.assertTrue(row["all_full_binary_stochastic_trees_globally_verified"])
        self.assertEqual(row["registered_case_count"], len(STUDIES))
        self.assertEqual(row["E10_actual_archive_check"]["retrospective_no_go"], True)
        self.assertEqual(row["new_pretrained_forward_count"], 0)
        self.assertEqual(row["root_control_result"], "NO_INCREMENTAL_ANSWER_QUALITY_IN_LINEAR_SPECIAL_CASE")
        self.assertFalse(row["natural_reasoning_efficacy"])
        self.assertFalse(row["production_accepted"])
        self.assertTrue(row["timings_are_self_observed_not_independently_attested"])
        self.assertEqual(row["authority"], "DENY_ALL")

    def test_complete_real_executed_samples_exist(self):
        self.assertEqual(len(self.src["cases"]), len(STUDIES))
        self.assertEqual(self.src["repeat_count"], REPEATS)
        self.assertEqual(self.src["real_pretrained_encoder_forwards"], 0)
        for case in self.src["cases"]:
            self.assertEqual(len(case["root_only_cpu_ns"]), REPEATS)
            self.assertEqual(len(case["exact_dense_cpu_ns"]), REPEATS)
            self.assertTrue(all(v > 0 for v in case["cheap_full_tree_cpu_ns"]))

    def test_bad_source_digest_reject(self):
        with self.assertRaises(ValueError):
            audit(str(self.original), "a"*64, str(self.dir/"bad-digest.json"))

    def test_wrong_root_fails_even_if_resigned(self):
        def change(o):
            o["cases"][0]["root_y"] = "999"
        path, digest = self.mutated(change)
        with self.assertRaises(ValueError):
            audit(str(path), digest, str(self.dir/"bad-root.json"))

    def test_fake_time_or_model_calls_fail(self):
        for name, edit in [
            ("zero_cpu", lambda o: o["cases"][0]["root_only_cpu_ns"].__setitem__(0, 0)),
            ("negative_ns", lambda o: o["cases"][0]["exact_dense_wall_ns"].__setitem__(0, -1)),
            ("actual_model_forward", lambda o: o.__setitem__("real_pretrained_encoder_forwards", 1)),
            ("fake_accept", lambda o: o.__setitem__("production_accepted", True)),
        ]:
            with self.subTest(name=name):
                path, digest = self.mutated(edit)
                with self.assertRaises(ValueError):
                    audit(str(path), digest, str(self.dir/(name+"-audit.json")))

    def test_profile_drift_or_missing_case(self):
        for name, edit in [
            ("case", lambda o: o["cases"].pop()),
            ("model", lambda o: o["cases"][2]["law"].__setitem__("sigma", "0")),
            ("work", lambda o: o["cases"][0].__setitem__("independent_dense_equations", 3)),
            ("invented", lambda o: o.__setitem__("future_semantic_success", 1)),
        ]:
            with self.subTest(name=name):
                path, digest = self.mutated(edit)
                with self.assertRaises(ValueError):
                    audit(str(path), digest, str(self.dir/(name+"-audit.json")))

    def test_deny_new_e10_winner_claim(self):
        src, _ = strict_json(str(E10))
        src["decision"] = "GO_PRODUCTION"
        file = self.dir / "fake-E10.json"
        file.write_text(json.dumps(src))
        with self.assertRaises(ValueError):
            audit(str(self.original), self.sha, str(self.dir/"fake-E10-audit.json"),
                  e10_path=str(file))

    def test_duplicate_json_keys_and_nonfinite_reject(self):
        file = self.dir / "duplicate.json"
        file.write_text('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            strict_json(str(file))
        file.write_text('{"x":NaN}')
        with self.assertRaises(ValueError):
            strict_json(str(file))


if __name__ == "__main__":
    unittest.main()
