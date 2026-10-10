"""Exercise native receipt capture through the complete runner, not a wire fixture."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from native import digest
from native_citation import ROOT_PROFILE
from run_native import run
from test_native_runner import FixtureEncoder, FixtureReader, stage


class AuditableReader(FixtureReader):
    def answer(self, query, evidence, *, revoked):
        answer, _ = super().answer(query, evidence, revoked=revoked)
        return answer, {
            "input_ids_sha256": digest((query.identity, [d.content for d in evidence])),
            "delivered_evidence": [
                {
                    "label": f"E{i}",
                    "id": d.identity,
                    "root": d.root,
                    "excerpt": f"[E{i}] {d.content}",
                    "partial": False,
                }
                for i, d in enumerate(evidence, start=1)
            ],
        }


class EmptyReader(AuditableReader):
    def answer(self, query, evidence, *, revoked):
        _, receipt = super().answer(query, evidence, revoked=revoked)
        return " \n", receipt


class NativeRunnerCitationTests(unittest.TestCase):
    def test_actual_native_root_shapes_produce_reviewable_unsigned_requests(self):
        with (
            tempfile.TemporaryDirectory() as name,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(name)
            stage(root, "locomo")
            run(
                root,
                root / "out",
                "locomo",
                1,
                fold=0,
                folds=5,
                all_questions=True,
                backends=(FixtureEncoder(), AuditableReader()),
            )
            report = json.loads((root / "out/report.json").read_text())
            for rows in report["results"].values():
                self.assertEqual(len(rows), 1)
                queue = rows[0]["citation_audit"]
                self.assertEqual(queue["source_root_profile"], ROOT_PROFILE)
                self.assertEqual(
                    queue["schema"], "hepta.memory-citation.native-queue.v1"
                )
                self.assertIsNone(queue["judgement"])
                self.assertIsNone(queue["evaluator_signature"])
                self.assertNotIn("DO_NOT_LEAK_GOLD", json.dumps(queue))

    def test_terminal_without_answer_is_failed_in_every_arm(self):
        with (
            tempfile.TemporaryDirectory() as name,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(name)
            stage(root, "locomo")
            with self.assertRaisesRegex(RuntimeError, "4 model executions failed"):
                run(
                    root,
                    root / "out",
                    "locomo",
                    1,
                    fold=0,
                    folds=5,
                    all_questions=True,
                    backends=(FixtureEncoder(), EmptyReader()),
                )
            report = json.loads((root / "out/report.json").read_text())
            for rows in report["results"].values():
                self.assertEqual([r["status"] for r in rows], ["failed"])
                self.assertIsNone(rows[0]["diagnostic_token_f1"])
                self.assertIsNone(rows[0]["hypothesis"])
