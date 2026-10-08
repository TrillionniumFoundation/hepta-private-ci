"""Runner orchestration tests use explicitly injected fixtures, not pretrained models."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from benchmark_coverage import aggregate, decode_plan
from run_native import run


class FixtureEncoder:
    identity = hashlib.sha256(b"fixture-encoder-not-a-real-model").hexdigest()
    truncated_inputs = 0

    def encode(self, texts):
        rows = []
        for text in texts:
            raw = np.frombuffer(hashlib.sha256(text.encode()).digest()[:8], dtype=np.uint8).astype(np.float32) + 1
            rows.append(raw / np.linalg.norm(raw))
        return np.array(rows, dtype=np.float32)


class FixtureReader:
    identity = hashlib.sha256(b"fixture-reader-not-a-real-model").hexdigest()
    inventory = {"fixture": {"bytes": 0}}
    trainable_parameters = 0

    def __init__(self, fail_adapt=False):
        self.scope = None
        self.fail_adapt = fail_adapt

    def reset(self, scope):
        self.scope = scope

    def answer(self, query, evidence, *, revoked):
        assert query.scope == self.scope
        assert "DO_NOT_LEAK_GOLD" not in query.content
        assert all("DO_NOT_LEAK_GOLD" not in doc.content and doc.scope == self.scope for doc in evidence)
        return "fixture response", {"backend": "fixture"}

    def adapt(self, history, *, steps, revoked):
        assert all(doc.scope == self.scope and "DO_NOT_LEAK_GOLD" not in doc.content for doc in history)
        if self.fail_adapt:
            raise RuntimeError("intentional fixture failure")
        return {"backend": "fixture", "steps": steps}

    def save(self, directory, receipt):
        directory.mkdir()
        payload = json.dumps(receipt).encode()
        (directory / "fixture.json").write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    def load_candidate(self, directory, *, expected_manifest_sha256, scope, allowed_roots, revoked):
        assert hashlib.sha256((directory / "fixture.json").read_bytes()).hexdigest() == expected_manifest_sha256
        assert self.scope == scope and not revoked
        return {"backend": "injected-test-fixture", "scope": scope}


def stage(root, kind):
    if kind == "locomo":
        data = [{"sample_id": str(i), "conversation": {"session_1_date_time": "2024/01/01", "session_1": [
            {"speaker": "A", "dia_id": "D1:1", "text": f"green account {i}"},
            {"speaker": "B", "dia_id": "D1:2", "text": f"blue object {i}"}]},
            "qa": [{"question": f"Which fact {i}?", "answer": "DO_NOT_LEAK_GOLD", "category": 1, "evidence": ["D1:1"]}]}
            for i in range(5)]
    else:
        data = [{"question_id": f"q{i}", "question_type": "knowledge-update", "question": f"Which memory {i}?",
                 "question_date": "2024/01/02", "answer": "DO_NOT_LEAK_GOLD", "answer_session_ids": ["repeated"],
                 "haystack_session_ids": ["repeated", "repeated"], "haystack_dates": ["2024/01/01"] * 2,
                 "haystack_sessions": [[{"role": "user", "content": "first", "has_answer": True}],
                                       [{"role": "user", "content": "second", "has_answer": False}]]} for i in range(3)]
    payload = json.dumps(data).encode()
    (root / f"{kind}.json").write_bytes(payload)
    (root / "staging.json").write_text(json.dumps({kind: {"sha256": hashlib.sha256(payload).hexdigest()}}))


class NativeRunnerTests(unittest.TestCase):
    def test_native_locomo_all_folds_can_collect_without_gold_in_model_inputs(self):
        torch.set_num_threads(2)
        with tempfile.TemporaryDirectory() as name, contextlib.redirect_stdout(io.StringIO()):
            root = Path(name)
            stage(root, "locomo")
            receipts = []
            for fold in range(5):
                out = root / f"fold{fold}"
                run(root, out, "locomo", 1, fold=fold, folds=5, all_questions=True,
                    backends=(FixtureEncoder(), FixtureReader()))
                receipts.append(json.loads((out / "report.json").read_text()))
                self.assertTrue((out / "lesions.json").exists())
            plan = decode_plan(json.loads((out / "coverage-plan.json").read_text()))
            combined = aggregate(plan, receipts, execution_binding=receipts[0]["execution_binding"])
            self.assertTrue(combined["all_native_questions_covered"])
            self.assertEqual(combined["native_question_total"], 5)
            self.assertFalse(combined["production_accepted"])
            self.assertEqual(combined["execution_binding"]["backend_profile"], "injected-test-fixture")

    def test_lme_conflicts_and_training_failure_keep_every_query_and_arm(self):
        with tempfile.TemporaryDirectory() as name, contextlib.redirect_stdout(io.StringIO()):
            root = Path(name)
            stage(root, "longmemeval")
            receipts = []
            for shard in range(4):
                out = root / f"shard{shard}"
                if shard < 3:
                    with self.assertRaisesRegex(RuntimeError, "model executions failed"):
                        run(root, out, "longmemeval", 1, shards=4, shard=shard, all_questions=True,
                            backends=(FixtureEncoder(), FixtureReader(fail_adapt=True)))
                else:
                    run(root, out, "longmemeval", 1, shards=4, shard=shard, all_questions=True,
                        backends=(FixtureEncoder(), FixtureReader(fail_adapt=True)))
                receipts.append(json.loads((out / "report.json").read_text()))
            plan = decode_plan(json.loads((out / "coverage-plan.json").read_text()))
            combined = aggregate(plan, receipts, execution_binding=receipts[0]["execution_binding"])
            self.assertEqual(combined["arms"]["rag_lora"]["failed"], 3)
            self.assertEqual(combined["arms"]["rag_lora"]["planned"], 3)
            self.assertEqual(combined["arms"]["rag"]["succeeded"], 3)
            self.assertTrue(all(row["unresolved_evidence"] for r in receipts for row in r["results"]["rag"]))
            self.assertTrue(combined["all_native_questions_covered"])

class QuarantinedHistoryTests(unittest.TestCase):
    def test_bad_native_turn_keeps_question_and_all_arms_as_failures(self):
        from benchmark_coverage import plan_coverage
        from native import load

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root / "input"
            staged.mkdir()
            stage(staged, "longmemeval")
            path = staged / "longmemeval.json"
            source = json.loads(path.read_text())
            source[1]["haystack_sessions"][0][0]["content"] = None
            payload = json.dumps(source).encode()
            path.write_bytes(payload)
            sha = hashlib.sha256(payload).hexdigest()
            (staged / "staging.json").write_text(json.dumps({"longmemeval": {"sha256": sha}}))
            with self.assertRaises(ValueError):
                load(path, "longmemeval", sha, session_conflicts="retain-versioned", allow_unresolved_evidence=True)
            admitted = load(path, "longmemeval", sha, session_conflicts="retain-versioned", allow_unresolved_evidence=True,
                            invalid_history="quarantine-question")
            self.assertEqual(len(admitted.questions), 3)
            self.assertEqual(set(admitted.ingress_failures), {"longmemeval:q1"})
            query = next(q for q in admitted.questions if q.identity == "longmemeval:q1")
            self.assertEqual(admitted.history(query), ())
            output = root / "out"
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                run(staged, output, "longmemeval", 20, all_questions=True,
                    backends=(FixtureEncoder(), FixtureReader()))
            result = json.loads((output / "report.json").read_text())
            for records in result["results"].values():
                self.assertEqual(len(records), 3)
                rejected = next(r for r in records if r["question_id"] == "longmemeval:q1")
                self.assertEqual(rejected["status"], "failed")
                self.assertIsNone(rejected["diagnostic_token_f1"])
                self.assertEqual(rejected["stage"], "native-history-ingress")
            plan = plan_coverage(admitted, folds=1, shards=1, per_fold_limit=None)
            collected = aggregate(plan, [result], execution_binding=result["execution_binding"])
            self.assertTrue(collected["all_native_questions_covered"])
            self.assertTrue(all(arm["failed"] == 1 for arm in collected["arms"].values()))
