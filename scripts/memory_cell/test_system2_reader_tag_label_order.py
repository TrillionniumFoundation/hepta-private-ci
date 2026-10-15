"""Source mechanics, authentic-source schema, and crash accounting; no Qwen inference."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_evidence import digest
from system2_multihop_trial import ABSTAIN
import system2_reader_tag_label_order as probe
from system2_reader_lexical_factorial import messages


class FrozenBundle:
    def __init__(self, question, docs, arm):
        self.question, self.docs, self.arm = question, docs, arm

    def validate(self, *_args, **_kwargs):
        if len({d.identity for d in self.docs}) != len(self.docs):
            raise ValueError("duplicate original source")

    def delivered(self):
        return [
            dict(
                label="E" + str(i + 1),
                original_id=d.identity,
                excerpt=d.content,
                observed_at=d.observed_at,
            )
            for i, d in enumerate(self.docs)
        ]

    def seal(self):
        return digest(
            (
                self.question.identity,
                self.arm,
                [(d.identity, d.content) for d in self.docs],
            )
        )


def fake_evidence(case, docs, arm):
    b = FrozenBundle(case.question, docs, arm)
    return b, {d.identity: d for d in docs}, digest(arm)


class FakeReader:
    identity = probe.STRONG_READER_ID
    inventory = {"pinned": "old-source"}
    tokenizer = type(
        "FakeTokenizer", (), dict(chat_template="hermetic-registered-template")
    )()

    def verify_frozen(self):
        return None


def fake_open(_path):
    inventory = json.dumps({"model_snapshot_inventory": FakeReader.inventory}).encode()
    return (
        dict(**{"reference-inventory.json": inventory}),
        dict(reference_reader_identity=FakeReader.identity),
        {i: i for i in range(160)},
    )


def fake_infer(reader, case, docs, arm, presentation):
    variant, _ = probe.context(case, arm)
    bundle, _, _ = fake_evidence(variant, docs, "tag-label:" + arm + ":" + presentation)
    label = variant.answer if arm in probe.POSITIVE else ABSTAIN
    profile = probe.native_digest(
        (
            probe.MODEL_ID,
            probe.MODEL_REV,
            probe.PROFILE,
            probe.system_instruction(probe.PROFILE),
            probe.MAX_NEW_TOKENS,
            reader.tokenizer.chat_template,
        )
    )
    return label, dict(
        reader_identity=reader.identity,
        reader_profile=profile,
        model_id=probe.MODEL_ID,
        revision=probe.MODEL_REV,
        input_ids_digest="a" * 64,
        generated_ids_digest="b" * 64,
        question_digest=probe.native_digest(probe.asdict(variant.question)),
        bundle_digest=bundle.seal(),
        delivered_evidence=bundle.delivered(),
        answer_postprocessed=False,
        trainable_parameters=0,
        input_tokens=76 if presentation == "labeled" else 68,
        generated_tokens=8,
        cpu_time_ns=10_000,
        production_accepted=False,
    )


class TagLabelTests(unittest.TestCase):
    def test_exact_20_fresh_worlds_with_disjoint_question_identities(self):
        cases = probe.cohort()
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({c.question.identity for c in cases}), 20)
        self.assertTrue(all(c.question.content.endswith("?") for c in cases))
        from system2_reader_lexical_factorial import base_cases

        self.assertFalse(
            {c.question.identity for c in cases}
            & {c.question.identity for c in base_cases()}
        )

    def test_180_registered_positions_and_unique_empty_input(self):
        self.assertEqual(probe.PLANNED, 180)
        self.assertEqual(len(probe.POSITIONS), 9)
        self.assertNotIn(("no_evidence", "labeled"), probe.POSITIONS)

    def test_same_two_sources_appear_in_exact_opposite_order(self):
        for c in probe.cohort():
            _, first = probe.context(c, "target_decoy_first")
            _, last = probe.context(c, "target_decoy_last")
            self.assertEqual(
                [d.identity for d in first], [d.identity for d in last[::-1]]
            )
            self.assertEqual(len(first), 2)
            self.assertTrue(all("TAG-" in d.content for d in first))

    def test_no_target_fact_leaks_into_negative_controls(self):
        for c in probe.cohort():
            transformed, _ = probe.context(c, "single_fact")
            for arm in ("decoy_only", "no_evidence"):
                _, docs = probe.context(c, arm)
                self.assertNotIn(transformed.required_id, [d.identity for d in docs])
                self.assertEqual(len(docs), int(arm == "decoy_only"))

    def test_labeled_variant_matches_existing_factorial_messages(self):
        c = probe.cohort()[0]
        variant, docs = probe.context(c, "target_decoy_first")
        delivered = fake_evidence(variant, docs, "tag-label")[0].delivered()
        self.assertEqual(
            probe.render(variant, delivered, "labeled"),
            messages(variant, delivered, probe.PROFILE),
        )

    def test_only_label_field_changes_within_each_matched_pair(self):
        for c in probe.cohort():
            for arm in probe.ARMS[:-1]:
                v, docs = probe.context(c, arm)
                delivered = fake_evidence(v, docs, "tag-label")[0].delivered()
                a = probe.render(v, delivered, "labeled")
                b = probe.render(v, delivered, "unlabeled")
                self.assertEqual(a[0], b[0])
                p, q = json.loads(a[1]["content"]), json.loads(b[1]["content"])
                self.assertEqual(p["question"], q["question"])
                self.assertEqual(p["question_time"], q["question_time"])
                self.assertEqual(len(p["evidence"]), len(q["evidence"]))
                self.assertEqual(
                    [
                        {k: v for k, v in row.items() if k != "label"}
                        for row in p["evidence"]
                    ],
                    q["evidence"],
                )

    def test_no_online_selector_access_to_gold_answer(self):
        c = probe.cohort()[0]
        for arm in probe.ARMS:
            self.assertEqual(
                probe.choose(c, arm),
                probe.choose(replace(c, answer="NO-GOLD-AVAILABLE"), arm),
            )

    def test_correct_answer_and_refusal_are_distinct(self):
        c = probe.cohort()[0]
        v, _ = probe.context(c, "single_fact")
        yes = probe.grade(c, "single_fact", v.answer)
        no = probe.grade(c, "decoy_only", ABSTAIN)
        self.assertTrue(yes["strict_success"])
        self.assertTrue(no["strict_success"])
        self.assertFalse(no["exact_answer"])
        self.assertFalse(probe.grade(c, "single_fact", ABSTAIN)["strict_success"])
        self.assertTrue(probe.grade(c, "decoy_only", v.answer)["unsupported_tag_copy"])
        self.assertFalse(probe.grade(c, "decoy_only", v.answer)["strict_success"])

    def test_literal_E_echo_is_not_a_correct_tag_or_refusal(self):
        c = probe.cohort()[0]
        for response in ("E1", "E1\nE2", "E2, E1"):
            r = probe.grade(c, "single_fact", response)
            self.assertTrue(r["label_only_echo"])
            self.assertFalse(r["exact_answer"])
        self.assertFalse(probe.grade(c, "single_fact", "TAG-FAKE99")["strict_success"])

    def test_strict_complete_census_and_paired_question_counts(self):
        rows = []
        for c in probe.cohort():
            for arm, presentation in probe.POSITIONS:
                v, _ = probe.context(c, arm)
                rows.append(
                    dict(
                        qid=c.question.identity,
                        arm=arm,
                        presentation=presentation,
                        status="succeeded",
                        answer=v.answer if arm in probe.POSITIVE else ABSTAIN,
                        reader=dict(
                            input_tokens=80, generated_tokens=8, cpu_time_ns=10
                        ),
                    )
                )
        summary, pairs, disposition = probe.contrasts(rows, probe.cohort())
        self.assertEqual(len(summary), len(probe.POSITIONS))
        self.assertEqual(len(pairs), 4 * 5)
        self.assertEqual(disposition, "independent_natural_confirmation_required")
        self.assertEqual(sum(r["strict_successes"] for r in summary), 180)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            probe.contrasts(rows[:-1], probe.cohort())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            probe.contrasts(rows + rows[:1], probe.cohort())

    def test_unknown_presentation_and_unregistered_arm_fail(self):
        c = probe.cohort()[0]
        v, docs = probe.context(c, "single_fact")
        delivery = fake_evidence(v, docs, "test")[0].delivered()
        with self.assertRaises(ValueError):
            probe.render(v, delivery, "no-labels")
        with self.assertRaises(ValueError):
            probe.context(c, "missing")

    def test_full_fake_trial_seals_before_scoring(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "trial"
            source = Path(d) / "hermetic-original.zip"
            source.write_bytes(b"strict local-only archived-source stand-in")
            pin = hashlib.sha256(source.read_bytes()).hexdigest()
            with (
                patch.object(probe, "PARENT_SHA", pin),
                patch.object(probe, "open_strong", fake_open),
                patch.object(probe, "evidence", fake_evidence),
            ):
                receipt = probe.run(
                    out,
                    FakeReader(),
                    parent_archive=source,
                    source_commit="b" * 40,
                    infer_fn=fake_infer,
                )
            self.assertEqual(receipt["completed"], 180)
            raw = (out / "raw-answers.jsonl").read_bytes()
            seal = json.loads((out / "raw-seal.json").read_text())
            self.assertEqual(seal["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(seal["rows"], 180)
            self.assertFalse(seal["scoring_started"])
            self.assertEqual(len((out / "starts.jsonl").read_text().splitlines()), 180)

    def test_failed_trial_retains_unknown_work_and_no_success_seal(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "trial"
            source = Path(d) / "hermetic-original.zip"
            source.write_bytes(b"strict local-only archived-source stand-in")
            pin = hashlib.sha256(source.read_bytes()).hexdigest()

            def broken(*_args):
                raise RuntimeError("injected Reader outage")

            with (
                patch.object(probe, "PARENT_SHA", pin),
                patch.object(probe, "open_strong", fake_open),
                patch.object(probe, "evidence", fake_evidence),
            ):
                with self.assertRaises(RuntimeError):
                    probe.run(
                        out,
                        FakeReader(),
                        parent_archive=source,
                        source_commit="b" * 40,
                        infer_fn=broken,
                    )
            self.assertFalse((out / "raw-seal.json").exists())
            self.assertTrue((out / "failure.json").is_file())
            self.assertEqual(
                json.loads((out / "failure.json").read_text())["planned"], 180
            )
            fail = json.loads((out / "raw-answers.jsonl").read_text())
            self.assertEqual(fail["status"], "failed")
            self.assertTrue(fail["work_may_be_incomplete"])

    def test_source_pin_fails_closed_before_model_inference(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.zip"
            bad.write_bytes(b"not the original source")
            output = Path(d) / "output"
            with self.assertRaisesRegex(ValueError, "archive mismatch"):
                probe.run(
                    output, FakeReader(), parent_archive=bad, source_commit="a" * 40
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
