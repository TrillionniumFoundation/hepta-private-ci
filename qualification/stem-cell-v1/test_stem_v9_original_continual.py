"""Source-only V9 adversarial tests, no model download, no fake model receipt."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from stem_v9_original_continual import (
    OLD, NEW, HELD, ARMS, SEEDS, SCHEMA, TOP_K, HEAD_PARAMETERS,
    digest, emit_once, file_sha, jbytes, lexical_bm25, parse_source_only,
    parse_train_labels, weak_gold, topk,
)


def fixture():
    families = OLD + NEW + HELD
    out = []
    for fam in families:
        out.append({"sample_id": fam,
                    "conversation": {"session_1": [
                        {"speaker": "A", "dia_id": f"D1:{i+1}",
                         "text": f"word{i} item{i%7} stable original example"}
                        for i in range(100)]},
                    "qa": [
                        {"question": f"Where is item{i%7} located?", "answer": "PRIVATE_ANSWER",
                         "evidence": [f"D1:{i%100 + 1}"], "category": 3}
                        for i in range(100)],
                    "observation": {"publisher": "PRIVATE_LABELS"}})
    return out


class SourceContract(unittest.TestCase):
    def setUp(self):
        self.raw = fixture()
        self.s = parse_source_only(self.raw)

    def test_complete_source_and_split(self):
        self.assertEqual(set(self.s["families"]), set(OLD + NEW + HELD))
        self.assertEqual(sum(len(f["questions"]) for f in self.s["families"].values()), 1000)
        self.assertFalse(self.s["production_authorized"])

    def test_source_never_contains_answer_or_evidence(self):
        public = json.dumps(self.s)
        self.assertNotIn("PRIVATE_ANSWER", public)
        self.assertNotIn("PRIVATE_LABELS", public)
        self.assertNotIn('"evidence"', public)
        self.assertNotIn('"category"', public)
        self.assertEqual(self.s["source_contains_publisher_gold"], False)

    def test_train_roster_never_admits_heldout(self):
        tr = parse_train_labels(self.raw, self.s)
        self.assertEqual(len(tr["labels"]), 600)
        self.assertTrue(all(qid.startswith(OLD + NEW) for qid in tr["labels"]))
        self.assertNotIn("PRIVATE_ANSWER", json.dumps(tr))
        self.assertFalse(tr["heldout_labels_present"])

    def test_weak_unknowns_count_conservatively(self):
        self.raw[-1]["qa"][0]["evidence"] = ["MISSING_SOURCE"]
        self.raw[-2]["qa"][0]["evidence"] = []
        weak = weak_gold(self.raw, self.s)
        self.assertIsNone(weak[HELD[-1] + "/q0"])
        self.assertIsNone(weak[HELD[-2] + "/q0"])
        self.assertEqual(len(weak), 400)

    def test_invalid_train_support_is_not_invented(self):
        self.raw[0]["qa"][0]["evidence"] = ["MISSING_SOURCE"]
        tr = parse_train_labels(self.raw, self.s)
        self.assertEqual(tr["labels"][OLD[0] + "/q0"], [])

    def test_refuse_missing_family(self):
        with self.assertRaises(ValueError):
            parse_source_only(self.raw[:-1])

    def test_refuse_duplicate_family(self):
        data = copy.deepcopy(self.raw)
        data[1]["sample_id"] = data[0]["sample_id"]
        with self.assertRaises(ValueError):
            parse_source_only(data)

    def test_refuse_duplicate_source_id(self):
        data = copy.deepcopy(self.raw)
        data[0]["conversation"]["session_1"][2]["dia_id"] = "D1:1"
        with self.assertRaises(ValueError):
            parse_source_only(data)

    def test_refuse_malformed_source(self):
        data = copy.deepcopy(self.raw)
        del data[0]["conversation"]["session_1"][3]["text"]
        with self.assertRaises(ValueError):
            parse_source_only(data)

    def test_refuse_missing_question(self):
        data = copy.deepcopy(self.raw)
        data[0]["qa"][0]["question"] = ""
        with self.assertRaises(ValueError):
            parse_source_only(data)

    def test_protocol_fixed(self):
        self.assertEqual(ARMS, ("frozen", "new_only", "low_lr", "equal_budget_replay"))
        self.assertEqual(SEEDS, (41, 47, 53))
        self.assertEqual(TOP_K, 3)
        self.assertEqual(HEAD_PARAMETERS, 6914)
        self.assertIn("shadow", SCHEMA)


class AdmissionAndBaseline(unittest.TestCase):
    def test_lexical_retrieval_hits_only_actual_tokens(self):
        d = [{"id": "D1", "text": "cat cat sat"}, {"id": "D2", "text": "dog ran away"},
             {"id": "D3", "text": "blue bird"}]
        s = lexical_bm25("cat sat", d)
        self.assertEqual(topk(s, d)[0], "D1")

    def test_topk_stable_source_id_tie(self):
        d = [{"id": "z"}, {"id": "a"}, {"id": "b"}]
        self.assertEqual(topk([0, 0, 0], d), ["a", "b", "z"])

    def test_topk_reject_nan(self):
        with self.assertRaises(ValueError):
            topk([0, 1, float("nan")], [{"id": str(i)} for i in range(3)])

    def test_topk_refuses_shrunken_source_candidates(self):
        with self.assertRaises(ValueError):
            topk([0, 1], [{"id": "a"}, {"id": "b"}])

    def test_digest_reject_nonfinite(self):
        with self.assertRaises(ValueError):
            digest({"x": float("inf")})

    def test_create_once_and_byte_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seal.json"
            payload = {"schema": "local-negative", "future_windows": 0}
            emit_once(path, payload)
            before = file_sha(path)
            with self.assertRaises(FileExistsError):
                emit_once(path, payload)
            self.assertEqual(file_sha(path), before)
            self.assertEqual(json.loads(path.read_bytes()), payload)

    def test_json_determinism(self):
        self.assertEqual(jbytes({"a": 1, "b": 2}), jbytes({"b": 2, "a": 1}))


if __name__ == "__main__":
    unittest.main()
