"""Training visits are original source exposure, not generated QA success."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from native import digest
from experience_memory import source_examples
from source_probe_exposure import verified_visits
from source_write_coverage import audit_coverage
from source_write_schedule import prepare
from test_experience_memory import source


class SourceTokenizer:
    eos_token_id = 2

    def apply_chat_template(self, messages, **_):
        body = json.loads(messages[1]["content"])
        return [7, 8, 9 + sum(map(ord, body["question"])) % 50]

    def encode(self, content, add_special_tokens=False):
        return [11 + ord(c) % 70 for c in content]


class ProbeExposureTests(unittest.TestCase):
    def setUp(self):
        self.docs = (
            source("a", "site_a", scope="a"),
            source("b", "site_b", scope="b"),
        )
        self.tokenizer = SourceTokenizer()
        self.training = self.record(maximum_steps=1)

    def record(self, maximum_steps=1, curriculum="single_hop"):
        if curriculum == "single_hop":
            examples, dispositions = source_examples(
                self.docs,
                revision=2,
                allowed_roots={d.root for d in self.docs},
                revoked=set(),
            )
            curriculum_receipt = None
        else:
            from source_composition_curriculum import combine_source_examples

            examples, dispositions, curriculum_receipt = combine_source_examples(
                self.docs,
                revision=2,
                allowed_roots={d.root for d in self.docs},
                revoked=set(),
            )
        prepared, plan = prepare(
            self.tokenizer,
            examples,
            maximum_steps=maximum_steps,
            token_ceiling=65536,
        )
        return dict(
            revision=2,
            curriculum=curriculum,
            loss_backend="full",
            roots=sorted({d.root for d in self.docs}),
            scopes=plan["scopes"],
            source_supervision=examples,
            dispositions=dispositions,
            curriculum_receipt=curriculum_receipt,
            write_schedule=plan,
            training_digest=digest((examples, prepared)),
            write_curriculum_coverage=audit_coverage(
                examples,
                prepared,
                plan,
                curriculum=curriculum,
            ),
            steps=plan["planned_steps"],
            losses=[1.0] * plan["planned_steps"],
            input_tokens=plan["planned_input_tokens"],
            supervised_tokens=plan["planned_supervised_tokens"],
        )

    def test_absent_loss_backend_cannot_claim_a_legacy_training_visit(self):
        # A missing provenance field is NOT an implicit full-loss receipt.
        missing = deepcopy(self.training)
        missing.pop("loss_backend")
        with self.assertRaisesRegex(ValueError, "registered source-written curriculum"):
            verified_visits(self.docs, self.tokenizer, missing)

    def test_unvisited_scope_not_mislabeled_training_recall(self):
        visits, schedule_digest = verified_visits(
            self.docs,
            self.tokenizer,
            self.training,
        )
        self.assertEqual(len(visits), 2)
        self.assertEqual(sorted(visits.values()), [0, 1])
        self.assertEqual(schedule_digest, digest(self.training["write_schedule"]))

    def test_every_source_question_exposed_when_budget_suffices(self):
        training = self.record(maximum_steps=2)
        visits, _ = verified_visits(self.docs, self.tokenizer, training)
        self.assertEqual(sorted(visits.values()), [1, 1])

    def test_two_hop_curriculum_requires_its_exact_schedule(self):
        training = self.record(maximum_steps=1, curriculum="source_two_hop")
        visits, _ = verified_visits(self.docs, self.tokenizer, training)
        self.assertEqual(sum(visits.values()), 1)
        training["curriculum"] = "single_hop"
        with self.assertRaises(ValueError):
            verified_visits(self.docs, self.tokenizer, training)

    def test_tampering_training_receipt_or_source_fails_closed(self):
        for name in (
            "visits",
            "schedule",
            "training_digest",
            "steps",
            "tokens",
            "source_supervision",
            "loss",
            "roots",
            "curriculum_coverage",
        ):
            with self.subTest(name=name):
                training = deepcopy(self.training)
                if name == "visits":
                    training["write_schedule"]["visits_per_example"][1] = 1
                elif name == "schedule":
                    training["write_schedule"]["entries"] = [1]
                elif name == "training_digest":
                    training["training_digest"] = "0" * 64
                elif name == "steps":
                    training["steps"] = 2
                elif name == "tokens":
                    training["input_tokens"] += 1
                elif name == "source_supervision":
                    training["source_supervision"] = []
                elif name == "loss":
                    training["losses"] = []
                elif name == "roots":
                    training["roots"] = ["wrong"]
                elif name == "curriculum_coverage":
                    training["write_curriculum_coverage"]["by_kind"] = {}
                with self.assertRaises(ValueError):
                    verified_visits(self.docs, self.tokenizer, training)
        changed = (
            replace(self.docs[0], content=self.docs[0].content + "changed"),
            self.docs[1],
        )
        with self.assertRaises(ValueError):
            verified_visits(changed, self.tokenizer, self.training)

    def test_boolean_budget_and_nan_loss_rejected(self):
        for name, value in (("maximum_steps", True), ("token_ceiling", 999999)):
            trial = deepcopy(self.training)
            trial["write_schedule"][name] = value
            with self.assertRaises(ValueError):
                verified_visits(self.docs, self.tokenizer, trial)
        trial = deepcopy(self.training)
        trial["losses"] = [float("nan")]
        with self.assertRaises(ValueError):
            verified_visits(self.docs, self.tokenizer, trial)


class ProbeIntegrationTests(unittest.TestCase):
    def test_unvisited_question_is_never_counted_as_training_recall(self):
        from source_recall_probe import probe
        from test_source_recall_probe import FakeReader

        docs = (
            source("a", "site_a", scope="a"),
            source("b", "site_b", scope="b"),
        )
        tokenizer = SourceTokenizer()
        examples, dispositions = source_examples(
            docs, revision=2, allowed_roots={d.root for d in docs}, revoked=set()
        )
        prepared, schedule = prepare(
            tokenizer, examples, maximum_steps=1, token_ceiling=65536
        )
        training = dict(
            revision=2,
            curriculum="single_hop",
            loss_backend="full",
            roots=sorted({d.root for d in docs}),
            scopes=schedule["scopes"],
            source_supervision=examples,
            dispositions=dispositions,
            curriculum_receipt=None,
            write_schedule=schedule,
            training_digest=digest((examples, prepared)),
            write_curriculum_coverage=audit_coverage(
                examples, prepared, schedule, curriculum="single_hop"
            ),
            steps=1,
            losses=[1.0],
            input_tokens=schedule["planned_input_tokens"],
            supervised_tokens=schedule["planned_supervised_tokens"],
        )
        reader = FakeReader(docs)
        reader.tokenizer = tokenizer
        with tempfile.TemporaryDirectory() as directory:
            result = probe(
                reader,
                docs,
                Path(directory) / "probe",
                snapshot_sha="a" * 64,
                writer_source="b" * 40,
                source_commit="c" * 40,
                training=training,
                generate=lambda *_: ("no match", 2, 0.1),
            )
            self.assertTrue(result["training_exposure_verified"])
            self.assertEqual(result["visited_source_questions"], 1)
            self.assertEqual(result["unvisited_source_questions"], 1)
            self.assertFalse(result["input_is_trained_source_question"])
            lines = [
                json.loads(line)
                for line in (Path(directory) / "probe" / "raw-answers.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(
                sorted({r["source_example_optimizer_visits"] for r in lines}), [0, 1]
            )
            self.assertEqual(result["by_exposure"]["base"]["unvisited"]["planned"], 1)
            self.assertEqual(result["by_exposure"]["memory"]["visited"]["planned"], 1)


if __name__ == "__main__":
    unittest.main()
