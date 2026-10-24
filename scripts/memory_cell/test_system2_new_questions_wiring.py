"""Execute native entry with isolated ingress/Encoder/Reader fixture ports."""

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch

import torch

from bundle_reader import PromptBudgetError
from native import digest
from selector_head import Features, Supervision
from system2_frozen_cohort import plan_cohort
from system2_new_questions import run
from test_system2_fewshot_cells import cohort
from test_system2_frozen_cohort import questions


@dataclass(frozen=True)
class Question:
    identity: str
    family: str
    scope: str
    content: str
    observed_at: str


@dataclass(frozen=True)
class Doc:
    identity: str
    root: str
    scope: str
    session: str
    observed_at: str
    content: str


@dataclass(frozen=True)
class Span:
    source_id: str
    root: str
    scope: str
    session: str
    observed_at: str
    start: int
    end: int
    excerpt: str
    source_digest: str


@dataclass(frozen=True)
class Bundle:
    query_digest: str
    source_frontier: str
    selected: tuple
    mode: str
    rounds: int = 1


@dataclass(frozen=True)
class Benchmark:
    questions: tuple
    targets: object
    families: dict
    source_sha256: str = "fixture"

    def history(self, q):
        return [
            Doc(
                q.family + f"/d{i}",
                q.family,
                q.family,
                "s",
                q.observed_at,
                "fixture passage " + str(i),
            )
            for i in range(2)
        ]


class NativeWiringTests(unittest.TestCase):
    def execute_fixture(
        self, tmp, *, incompatible=False, matched=False, token_drift=False
    ):
        qs = tuple(Question(**vars(q)) for q in questions())
        old = {"question_ids": {"train": ["a/q0", "b/q0"], "test": ["a/q1", "b/q1"]}}
        plan = plan_cohort(qs, old)
        support_ids = {q for g in plan["groups"] for q in g["support_ids"]}
        out = Path(tmp) / "result"
        calls = dict(
            labels=[],
            encoded=[],
            reader_calls=0,
            reader_loads=0,
            verified=0,
            compiles=[],
        )

        class Targets(dict):
            def __getitem__(self, key):
                if (
                    key not in support_ids
                    and not (out / "trial/answer-seal.json").is_file()
                ):
                    raise AssertionError(
                        "evaluation label read before all answers sealed"
                    )
                calls["labels"].append(key)
                return SimpleNamespace(
                    unanswerable=False, unresolved_evidence=(), evidence=("native",)
                )

        source = Benchmark(qs, Targets(), {"a": "a", "b": "b"})
        rows, cut = cohort()
        pin = digest({"fixture": True})

        class Encoder:
            def __init__(self, *_):
                pass

            def encode(self, x):
                return [[0.0] for _ in x]

        class Ranker:
            identity = "wrong" if incompatible else "encoder"
            dimension = 2

            def __init__(self, *_):
                pass

            def verify_frozen(self):
                calls["verified"] += 1

        class Window:
            def __init__(self, d):
                self.source_id = d.identity
                self.start = 0
                self.end = len(d.content.encode())
                self.text = d.content
                self.observed_at = d.observed_at

        class Pool:
            def __init__(self, docs):
                self.windows = [Window(d) for d in docs]

            def revalidate(self, *_):
                pass

            def seal(self):
                return "fixture-pool"

        class Cache:
            def __init__(self, *_):
                pass

            def encode(self, q, fam, pool, **_):
                calls["encoded"].append(
                    (q.identity, (out / "trial/snapshot-freeze.json").is_file())
                )
                f = Features(
                    q.identity,
                    fam,
                    "encoder",
                    pool.seal(),
                    tuple(w.source_id for w in pool.windows),
                    frozenset({fam}),
                    torch.tensor([[2.0, 0.0], [-2.0, 0.0]]),
                    torch.tensor([0.0, 1.0]),
                )
                return f, {"fixture": True}

        class Index:
            def query(self, q, *_, **__):
                return source.history(q), {"fixture": True}

        class Reader:
            def __init__(self, *_, **__):
                calls["reader_loads"] += 1

            def compile_input(self, q, bundle, originals, **kw):
                calls["compiles"].append(
                    (q.identity, (out / "trial/snapshot-freeze.json").is_file())
                )
                ids = list(range(100 + 10 * len(bundle.selected)))
                return ids, dict(
                    input_tokens=len(ids),
                    input_ids_digest=digest(ids),
                    token_limit=4096,
                    omitted_evidence_bytes=0,
                    delivered_evidence=[
                        as_span.source_id for as_span in bundle.selected
                    ],
                )

            def answer(self, q, bundle, originals, **kw):
                assert kw["token_limit"] == 4096 and kw["revoked"] == set()
                assert all(s.source_id in originals for s in bundle.selected)
                calls["reader_calls"] += 1
                _, rec = self.compile_input(q, bundle, originals, **kw)
                if token_drift:
                    rec["input_tokens"] += 1
                return "fixture answer", rec | {
                    "fixture": True,
                    "reader_identity": "fixture",
                }

            def verify_frozen(self):
                calls["verified"] += 1

        def train_rows(qs, targets, pools, features, cut):
            if set(targets) != set(cut.question_ids):
                raise AssertionError("unexpected labels provided to fitting port")
            return tuple(Supervision(features[q.identity], (0,)) for q in qs), {
                "fixture": True
            }

        modules = {
            "native": SimpleNamespace(load=lambda *_, **__: source, digest=digest),
            "bundle_reader": SimpleNamespace(
                FrozenBundleReader=Reader, PromptBudgetError=PromptBudgetError
            ),
            "evidence_bundle": SimpleNamespace(
                EvidenceBundle=Bundle, EvidenceSpan=Span
            ),
            "index": SimpleNamespace(RetrievalPolicy=lambda: None),
            "pretrained": SimpleNamespace(
                Encoder=Encoder, file_inventory=lambda _: {"fixture": True}
            ),
            "selector_encoder": SimpleNamespace(FrozenPairEncoder=Ranker),
            "selector_evaluation": SimpleNamespace(
                diagnose=lambda *_: 0.5,
                support_indices=lambda *_: (0,),
                train_rows=train_rows,
            ),
            "selector_windows": SimpleNamespace(
                WindowBudget=lambda: None,
                candidate_windows=lambda docs, *_, **__: Pool(docs),
            ),
            "stem_cell_cache": SimpleNamespace(SharedFeatureCache=Cache),
            "stem_cell_temporal": SimpleNamespace(
                build_as_of_index=lambda *_, **__: (
                    Index(),
                    {"as_of_cut": "fixture-cut"},
                )
            ),
            "stem_cell_trial": SimpleNamespace(READER=pin, RETRIEVER=pin),
        }
        with (
            patch.dict("sys.modules", modules),
            patch(
                "system2_new_questions.audit_content",
                return_value=({48: (rows, cut)}, {"fixture": True}),
            ),
            patch(
                "system2_new_questions.verified_archive",
                return_value={"native/plan.json": json.dumps(old).encode()},
            ),
        ):
            report = run(
                Path(tmp),
                Path(tmp),
                Path(tmp) / "fixture.zip",
                out,
                source_commit="a" * 40,
                evidence_mode="matched3" if matched else "single",
            )
        return report, calls, out, support_ids

    def test_real_native_entry_keeps_support_fit_before_eval_and_reader_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, calls, out, support_ids = self.execute_fixture(tmp)
            self.assertEqual(report["recorded"], 128)
            self.assertEqual(report["failed"], 0)
            self.assertEqual(calls["reader_calls"], 128)
            self.assertEqual(calls["reader_loads"], 1)
            self.assertEqual(calls["verified"], 2)
            self.assertEqual(len(calls["encoded"]), 20)
            self.assertTrue(
                all(
                    frozen == (qid not in support_ids)
                    for qid, frozen in calls["encoded"]
                )
            )
            saved = json.loads((out / "run-summary.json").read_text())
            self.assertEqual(saved["old_question_ids_reused"], 0)
            self.assertFalse(saved["natural_chronology_verified"])
            self.assertNotIn("matched_evidence", report)

    def test_incompatible_encoder_rejected_before_any_fitting_or_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "incompatible"):
                self.execute_fixture(tmp, incompatible=True)
            self.assertFalse((Path(tmp) / "result/trial").exists())

    def test_matched_mode_uses_one_reader_and_real_compile_port_after_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, calls, out, support_ids = self.execute_fixture(tmp, matched=True)
            self.assertEqual(report["recorded"], 128)
            self.assertEqual(report["failed"], 0)
            self.assertEqual(calls["reader_calls"], 128)
            self.assertEqual(calls["reader_loads"], 1)
            self.assertTrue(all(frozen for _, frozen in calls["compiles"]))
            self.assertTrue(
                all(
                    frozen == (qid not in support_ids)
                    for qid, frozen in calls["encoded"]
                )
            )
            self.assertEqual(
                report["matched_evidence"]["verified_evidence_answers"], 112
            )
            answers = [
                json.loads(line)
                for line in (out / "trial/answers.jsonl").read_text().splitlines()
            ]
            for row in answers:
                self.assertEqual(
                    len(row["selected"]), 0 if row["arm"] == "no_evidence" else 2
                )
            self.assertEqual(
                len((out / "prompt-probes.jsonl").read_text().splitlines()), 112
            )

    def test_actual_token_drift_retains_answers_but_fails_matched_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "failed answers"):
                self.execute_fixture(tmp, matched=True, token_drift=True)
            out = Path(tmp) / "result/trial"
            report = json.loads((out / "summary.json").read_text())
            self.assertEqual(report["recorded"], 128)
            self.assertEqual(report["failed"], 112)
            rows = [
                json.loads(line)
                for line in (out / "scored.jsonl").read_text().splitlines()
            ]
            self.assertTrue(all(r["answer"] == "fixture answer" for r in rows))
            self.assertTrue(
                all(r["diagnostic_f1"] is None for r in rows if r["status"] == "failed")
            )


if __name__ == "__main__":
    unittest.main()
