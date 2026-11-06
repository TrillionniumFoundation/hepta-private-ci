"""LoCoMo-only source-family pilot tests; synthetic families are NOT real data."""

from dataclasses import dataclass, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import external_locomo_pilot as pilot
from external_family_population import PublicCorpus, SOURCE_PINS


@dataclass(frozen=True)
class Question:
    identity: str
    family: str
    scope: str
    content: str
    observed_at: str


@dataclass(frozen=True)
class Document:
    identity: str
    root: str
    scope: str
    observed_at: str
    content: str


@dataclass(frozen=True)
class Target:
    answer: str
    evidence: tuple
    category: str = "literal"
    unanswerable: bool = False
    unresolved_evidence: tuple = ()


def synthetic_locomo(families=10, *, duplicate_root=False):
    questions, docs, source_families, labels = [], [], {}, {}
    for i in range(families):
        family = f"conversation-{i:02d}"
        source_families[family] = family
        for j in range(2):
            qid = f"locomo-{i:02d}-{j}"
            root = "SHARED_unsafe" if duplicate_root else f"root-{family}"
            questions.append(
                Question(qid, family, qid, f"Find in conversation {i}", "2025-01-01")
            )
            docs.append(Document(f"{qid}-doc", root, qid, "2024-01-01", "source only"))
            labels[qid] = Target("VERY_PRIVATE_GOLD_" + qid, (f"{qid}-doc",))
    return (
        PublicCorpus(
            "locomo",
            SOURCE_PINS["locomo"],
            tuple(docs),
            tuple(questions),
            source_families,
        ),
        labels,
    )


class LoCoMoNativeFamilyPilotTests(unittest.TestCase):
    def test_ten_native_groups_produce_disjoint_6_2_2_cut(self):
        corpus, _ = synthetic_locomo()
        public, capacity = pilot.precommit_locomo(corpus, source_commit="a" * 40)
        self.assertEqual(capacity["actual_published_family_proxy_groups"], 10)
        self.assertEqual(
            capacity["split_family_proxy_capacity"],
            {"train": 6, "selection": 2, "evaluation": 2},
        )
        self.assertEqual(len(public["splits"]["evaluation"]), 4)
        seen = {}
        for split, rows in public["splits"].items():
            for row in rows:
                self.assertEqual(row["dataset"], "locomo")
                self.assertEqual(
                    seen.setdefault(row["family_proxy_digest"], split), split
                )
        self.assertEqual(len(seen), 10)
        self.assertEqual(public["source_sha256"], {"locomo": SOURCE_PINS["locomo"]})
        self.assertFalse(public["production_accepted"])

    def test_private_labels_only_open_after_public_fsync(self):
        corpus, labels = synthetic_locomo()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pilot"
            opened = []

            def supplier():
                opened.append(True)
                self.assertTrue((output / "public/population.json").is_file())
                public = json.loads((output / "public/population.json").read_text())
                self.assertNotIn("VERY_PRIVATE", json.dumps(public))
                selected = {
                    row["question_id"]
                    for rows in public["splits"].values()
                    for row in rows
                }
                return {qid: labels[qid] for qid in selected}

            receipt = pilot.seal_source_only_pilot(
                corpus,
                source_commit="c" * 40,
                output=output,
                target_supplier=supplier,
            )
            self.assertEqual(len(opened), 1)
            self.assertEqual(receipt["question_count"], 20)
            self.assertFalse(receipt["production_accepted"])
            private = (output / "targets/targets.json").read_text()
            self.assertIn("VERY_PRIVATE_GOLD", private)
            self.assertTrue((Path(tmp) / "pilot-capacity.json").exists())
            with self.assertRaises(FileExistsError):
                pilot.seal_source_only_pilot(
                    corpus,
                    source_commit="c" * 40,
                    output=output,
                    target_supplier=supplier,
                )

    def test_shortfall_refused_without_opening_targets(self):
        corpus, _ = synthetic_locomo(9)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pilot"
            with self.assertRaises(ValueError):
                pilot.seal_source_only_pilot(
                    corpus,
                    source_commit="c" * 40,
                    output=output,
                    target_supplier=lambda: self.fail(
                        "gold opened before source admission"
                    ),
                )
            self.assertFalse(output.exists())

    def test_shared_original_root_across_families_rejected(self):
        corpus, _ = synthetic_locomo(duplicate_root=True)
        with self.assertRaises(ValueError):
            pilot.precommit_locomo(corpus, source_commit="d" * 40)

    def test_source_order_and_labels_cannot_change_public_cut(self):
        corpus, _ = synthetic_locomo()
        public, _ = pilot.precommit_locomo(corpus, source_commit="e" * 40)
        other = replace(
            corpus, documents=corpus.documents[::-1], questions=corpus.questions[::-1]
        )
        again, _ = pilot.precommit_locomo(other, source_commit="e" * 40)
        self.assertEqual(pilot.canonical(public), pilot.canonical(again))

    def test_forged_dataset_source_or_commit_rejected(self):
        corpus, _ = synthetic_locomo()
        corruptions = (
            (replace(corpus, name="longmemeval"), "a" * 40),
            (replace(corpus, source_sha256="0" * 64), "a" * 40),
            (corpus, "wrong"),
            (corpus, "0" * 41),
        )
        for candidate, sha in corruptions:
            with self.subTest(source=sha):
                with self.assertRaises(ValueError):
                    pilot.precommit_locomo(candidate, source_commit=sha)

    def test_unregistered_budget_or_duplicate_questions_rejected(self):
        corpus, _ = synthetic_locomo()
        for limits in (
            dict(train=0, selection=64, evaluation=64),
            dict(train=True, selection=64, evaluation=64),
            dict(train=128, selection=64),
        ):
            with self.assertRaises(ValueError):
                pilot.precommit_locomo(corpus, source_commit="f" * 40, limits=limits)
        duplicate = replace(corpus, questions=corpus.questions + corpus.questions[:1])
        with self.assertRaises(ValueError):
            pilot.precommit_locomo(duplicate, source_commit="f" * 40)

    def test_auditor_cannot_relabel_pilot_as_future_or_production(self):
        corpus, _ = synthetic_locomo()
        public, capacity = pilot.precommit_locomo(corpus, source_commit="1" * 40)
        for label in (
            "model_input_contains_answers",
            "production_accepted",
            "published_benchmarks_are_future_observations",
            "independent_source_authenticity_verified",
            "independent_semantic_judgement",
        ):
            self.assertIs(public[label], False)
        self.assertTrue(capacity["original_two_corpus_gate_not_overridden"])
        self.assertFalse(capacity["quarantined_data_admitted"])
        self.assertEqual(capacity["quarantined_dataset"], "longmemeval")
        self.assertEqual(capacity["genuinely_independent_future_families"], 0)


if __name__ == "__main__":
    unittest.main()
