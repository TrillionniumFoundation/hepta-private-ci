"""Fail-closed corpus population tests; fixtures never count as real tasks."""

from dataclasses import dataclass, replace
from pathlib import Path
import json
import tempfile
import unittest

import external_family_population as p


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
    category: str = "test"
    unanswerable: bool = False
    unresolved_evidence: tuple = ()


def fixture(kind, *, families=16, duplicate_root=False, source_pin=True):
    questions = []
    documents = []
    family_map = {}
    targets = {}
    for i in range(families):
        # Two tasks per registered source family; exact documents are shared
        # only WITHIN the family by construction.
        family = f"{kind}-family-{i:02d}"
        family_map[family] = family
        for j in range(2):
            qid = f"{kind}:q-{i:02d}-{j}"
            questions.append(
                Question(qid, family, qid, f"How about {i}?", "2026-01-01")
            )
            root = (
                "global-reused-root"
                if duplicate_root and i == 0
                else f"{kind}-root-{i}"
            )
            documents.append(
                Document(f"{qid}-doc", root, qid, "2025-01-01", f"Fact {i}")
            )
            targets[qid] = Target(f"VERY_PRIVATE_{kind}_{i}_{j}", (f"{qid}-doc",))
    if duplicate_root:
        # Force exact root overlap ACROSS assigned family buckets.
        first = documents[0]
        cross = next(d for d in documents if d.root != first.root)
        documents[documents.index(cross)] = replace(cross, root=first.root)
    corpus = p.PublicCorpus(
        kind,
        p.SOURCE_PINS[kind] if source_pin else "0" * 64,
        tuple(documents),
        tuple(questions),
        family_map,
    )
    return corpus, targets


class FamilyCutTests(unittest.TestCase):
    def setUp(self):
        self.corpora, self.targets = {}, {}
        for kind in p.SOURCE_PINS:
            self.corpora[kind], subset = fixture(kind)
            self.targets.update(subset)

    def plan(self, **options):
        return p.prepare_population(self.corpora, source_commit="a" * 40, **options)

    def test_family_source_partition_cannot_leak(self):
        report = self.plan()
        for name in p.SOURCE_PINS:
            self.assertEqual(report["corpus_census"][name]["family_proxy_groups"], 16)
            self.assertGreaterEqual(
                report["corpus_census"][name]["split_family_proxies"]["evaluation"], 2
            )
        by_family = {}
        for split, rows in report["splits"].items():
            for row in rows:
                key = row["dataset"], row["family_proxy_digest"]
                if key in by_family:
                    self.assertEqual(by_family[key], split)
                by_family[key] = split
                self.assertNotIn("VERY_PRIVATE", json.dumps(row))

    def test_targets_do_not_affect_precommitted_plan(self):
        original = p.canonical(self.plan())
        self.targets = {
            k: replace(v, answer="CHANGED_ANSWER") for k, v in self.targets.items()
        }
        self.assertEqual(original, p.canonical(self.plan()))

    def test_project_native_does_not_dereference_target_labels(self):
        class GuardedBenchmark:
            name = "locomo"
            source_sha256 = p.SOURCE_PINS["locomo"]
            documents = ()
            questions = ()
            families = {}

            @property
            def targets(self):
                raise AssertionError("a population planner opened gold targets")

        projected = p.PublicCorpus.from_native(GuardedBenchmark())
        self.assertEqual(projected.name, "locomo")

    def test_cross_dataset_shared_original_root_rejected(self):
        a = self.corpora["locomo"]
        b = self.corpora["longmemeval"]
        new_docs = (replace(a.documents[0], root=b.documents[0].root),) + a.documents[
            1:
        ]
        self.corpora["locomo"] = replace(a, documents=new_docs)
        with self.assertRaisesRegex(ValueError, "reused across corpora"):
            self.plan()

    def test_source_file_and_commit_pins_are_required(self):
        name = "locomo"
        replacement, _ = fixture(name, source_pin=False)
        self.corpora[name] = replacement
        with self.assertRaisesRegex(ValueError, "pinned"):
            self.plan()
        self.corpora[name] = fixture(name)[0]
        with self.assertRaisesRegex(ValueError, "commit"):
            p.prepare_population(self.corpora, source_commit="unverified")

    def test_unsafe_cross_family_source_root_rejected(self):
        # Same real source root may not appear across training/evaluation.
        name = "longmemeval"
        corpus, _ = fixture(name)
        public = p.prepare_population(self.corpora, source_commit="a" * 40)
        assignment = {
            row["scope"]: split
            for split, rows in public["splits"].items()
            for row in rows
        }
        first = next(d for d in corpus.documents if assignment.get(d.scope) == "train")
        other = next(
            d for d in corpus.documents if assignment.get(d.scope) == "evaluation"
        )
        docs = tuple(
            replace(d, root=first.root) if d.identity == other.identity else d
            for d in corpus.documents
        )
        self.corpora[name] = replace(corpus, documents=docs)
        with self.assertRaisesRegex(ValueError, "leaks"):
            self.plan()

    def test_immutability_and_labels_opened_after_public_commit(self):
        report = self.plan()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "population"
            calls = []

            def open_labels():
                self.assertTrue((out / "public/population.json").is_file())
                calls.append("after_public")
                return {
                    qid: self.targets[qid]
                    for qid in {
                        row["question_id"]
                        for rows in report["splits"].values()
                        for row in rows
                    }
                }

            manifest = p.publish_and_seal(report, open_labels, out)
            self.assertEqual(calls, ["after_public"])
            self.assertFalse(manifest["production_accepted"])
            public = (out / "public/population.json").read_text()
            self.assertNotIn("VERY_PRIVATE", public)
            self.assertIn("VERY_PRIVATE", (out / "targets/targets.json").read_text())
            self.assertEqual(
                manifest["question_count"], sum(map(len, report["splits"].values()))
            )
            with self.assertRaises(FileExistsError):
                p.publish_and_seal(report, open_labels, out)

    def test_wrong_public_population_label_census_rejects(self):
        report = self.plan()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                p.publish_and_seal(
                    report,
                    lambda: {"not-precommitted": Target("wrong", ())},
                    Path(temp) / "bad",
                )

    def test_unequal_or_wrong_per_family_quota_reject(self):
        for budgets in (
            {"train": 1},
            {"train": True, "selection": 10, "evaluation": 20},
            {"train": 1, "selection": 0, "evaluation": 1},
        ):
            with self.assertRaises(ValueError):
                self.plan(limits=budgets)

    def test_duplicate_native_question_and_orphan_history_reject(self):
        name = "longmemeval"
        orig = self.corpora[name]
        self.corpora[name] = replace(
            orig, questions=orig.questions + (orig.questions[0],)
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.plan()
        self.corpora[name] = replace(orig, documents=orig.documents[1:])
        with self.assertRaisesRegex(ValueError, "without"):
            self.plan()

    def test_reproducible_under_document_question_and_corpus_order(self):
        before = p.canonical(self.plan())
        self.corpora = {
            k: replace(
                v,
                documents=tuple(reversed(v.documents)),
                questions=tuple(reversed(v.questions)),
            )
            for k, v in reversed(list(self.corpora.items()))
        }
        self.assertEqual(before, p.canonical(self.plan()))

    def test_family_capacity_preflight_counts_real_groups_not_question_ids(self):
        census = p.source_only_family_capacity(self.corpora, source_commit="a" * 40)
        self.assertTrue(census["original_published_family_capacity_sufficient"])
        self.assertFalse(census["production_accepted"])
        for kind in p.SOURCE_PINS:
            self.assertEqual(
                census["corpora"][kind]["actual_native_family_proxy_count"], 16
            )
        corpus, _ = fixture("locomo", families=5)
        self.corpora["locomo"] = corpus
        refused = p.source_only_family_capacity(self.corpora, source_commit="a" * 40)
        self.assertFalse(refused["original_published_family_capacity_sufficient"])
        self.assertEqual(
            refused["corpora"]["locomo"]["actual_native_family_proxy_count"], 5
        )
        self.assertEqual(refused["corpora"]["locomo"]["shortfall_from_ten"], 5)
        self.assertTrue(refused["insufficient_source_families_block_promotion"])
        self.assertFalse(refused["independent_source_authenticity_verified"])
        self.assertIsNone(refused["actual_future_observations"])
        self.assertFalse(refused["actual_prospective_window_measured"])

    def test_failed_population_still_seals_source_only_capacity_receipt(self):
        self.corpora["locomo"] = fixture("locomo", families=5)[0]
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "never-publish"
            with self.assertRaisesRegex(ValueError, "family-disjoint"):
                p.preflight_and_prepare(
                    self.corpora, source_commit="a" * 40, output=target
                )
            capacity = target.with_name(target.name + "-capacity.json")
            self.assertFalse(target.exists())
            self.assertTrue(capacity.is_file())
            raw = capacity.read_bytes()
            self.assertEqual(raw, p.canonical(json.loads(raw)) + b"\n")
            self.assertNotIn(b"VERY_PRIVATE", raw)
            self.assertFalse(
                json.loads(raw)["original_published_family_capacity_sufficient"]
            )
            with self.assertRaises(FileExistsError):
                p.preflight_and_prepare(
                    self.corpora, source_commit="a" * 40, output=target
                )

    def test_valid_population_preflight_happens_before_private_targets(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "cut"
            public = p.preflight_and_prepare(
                self.corpora, source_commit="a" * 40, output=output
            )
            receipt = json.loads(
                output.with_name(output.name + "-capacity.json").read_text()
            )
            self.assertTrue(receipt["original_published_family_capacity_sufficient"])
            self.assertTrue(
                all(
                    x["family_capacity_sufficient"] for x in receipt["corpora"].values()
                )
            )
            self.assertFalse(output.exists())
            self.assertNotIn("targets", json.dumps(public))
            self.assertTrue(public["model_input_contains_answers"] is False)

    def test_sharing_one_proxy_cannot_fake_ten_independent_families(self):
        corpus, _ = fixture("locomo", families=16)
        merged = {k: "one-shared-published-origin" for k in corpus.families}
        self.corpora["locomo"] = replace(corpus, families=merged)
        receipt = p.source_only_family_capacity(self.corpora, source_commit="a" * 40)
        self.assertEqual(
            receipt["corpora"]["locomo"]["actual_native_family_proxy_count"], 1
        )
        self.assertFalse(receipt["original_published_family_capacity_sufficient"])
        with self.assertRaisesRegex(ValueError, "ten"):
            self.plan()

    def test_small_family_population_refuses_promotion(self):
        self.corpora["locomo"] = fixture("locomo", families=5)[0]
        with self.assertRaisesRegex(ValueError, "ten"):
            self.plan()


if __name__ == "__main__":
    unittest.main()
