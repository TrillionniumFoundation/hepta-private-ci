"""Hermetic source-label placebo protocol; never count mocks as Qwen results."""

from __future__ import annotations

from hashlib import sha256
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import system2_reader_equal_token_labels as exp


class MockTokenizer:
    """Deliberately token-count-only stub, not a pretrained model tokenizer."""

    def __init__(self, fail_match=False):
        self.fail_match = fail_match

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize and add_generation_prompt
        body = json.loads(messages[1]["content"])
        labels = [s["label"] for s in body["evidence"] if "label" in s]
        length = 35 + len(body["evidence"]) * 7 + (len(labels) * 5)
        if self.fail_match and labels and not all(s.startswith("E") for s in labels):
            length += 1
        return list(range(length))


def base(count=2):
    return [
        dict(role="system", content="Answer only the TAG code or refuse."),
        dict(
            role="user",
            content=json.dumps(
                dict(
                    question="Which TAG?",
                    question_time="2026-08-06",
                    evidence=[
                        dict(
                            label="E" + str(i + 1),
                            observed_at="2026-08-05",
                            text="Device requires TAG-" + str(i),
                        )
                        for i in range(count)
                    ],
                ),
                separators=(",", ":"),
            ),
        ),
    ]


class InputPlaceboTests(unittest.TestCase):
    def test_preplanned_positions_and_no_extra_empty_duplicate(self):
        self.assertEqual(exp.PLANNED, 200)
        self.assertEqual(len(exp.POSITIONS), 10)
        self.assertEqual(len(set(exp.POSITIONS)), 10)
        self.assertEqual(exp.POSITIONS[-1], ("no_evidence", "unlabeled"))
        self.assertEqual((exp.INDICES.start, exp.INDICES.stop), (100, 120))

    def test_label_only_transport_changes_and_preserves_excerpts(self):
        before = base()
        original = json.loads(before[1]["content"])
        variants = {
            name: json.loads(exp.render_view(before, name, alias)[1]["content"])
            for name, alias in [
                ("e_label", None),
                ("neutral_alias", "Z"),
                ("unlabeled", None),
            ]
        }
        self.assertEqual(variants["e_label"], original)
        self.assertEqual(
            [r["label"] for r in variants["neutral_alias"]["evidence"]], ["Z1", "Z2"]
        )
        self.assertTrue(
            all("label" not in r for r in variants["unlabeled"]["evidence"])
        )
        for variant in variants.values():
            self.assertEqual(variant["question"], original["question"])
            self.assertEqual(
                [r["text"] for r in variant["evidence"]],
                [r["text"] for r in original["evidence"]],
            )
            self.assertEqual(
                [r["observed_at"] for r in variant["evidence"]],
                [r["observed_at"] for r in original["evidence"]],
            )
        self.assertEqual(
            before[1]["content"], json.dumps(original, separators=(",", ":"))
        )

    def test_preflight_alias_is_input_token_matched_without_labels(self):
        tok = MockTokenizer()
        for count in (1, 2):
            rows = exp.matched_presentations(tok, base(count))
            self.assertNotEqual(rows["neutral_alias"][0], "E")
            self.assertEqual(len(rows["e_label"][1]), len(rows["neutral_alias"][1]))
            self.assertGreater(len(rows["e_label"][1]), len(rows["unlabeled"][1]))
            self.assertEqual(rows["neutral_alias"][0], exp.ALIAS_LETTERS[0])

    def test_no_equal_token_alias_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no tokenizer-length-matched"):
            exp.matched_presentations(MockTokenizer(fail_match=True), base(2))

    def test_refuse_unknown_profile_and_malformed_source_label(self):
        for profile in ("other", None, ""):
            with self.assertRaises(ValueError):
                exp.render_view(base(), profile)
        bad = base()
        u = json.loads(bad[1]["content"])
        u["evidence"][0]["label"] = "E6"
        bad[1]["content"] = json.dumps(u, separators=(",", ":"))
        with self.assertRaisesRegex(ValueError, "source label"):
            exp.render_view(bad, "e_label")

    def test_no_alias_on_empty_docs(self):
        with self.assertRaises(ValueError):
            exp.render_view(base(0), "neutral_alias", "A")
        self.assertEqual(
            exp.render_view(base(0), "unlabeled")[1]["content"],
            exp.render_view(base(0), "e_label")[1]["content"],
        )

    def test_fake_fixed_cohort_summarizes_paired_answer_and_refusal(self):
        def make(qid):
            return types.SimpleNamespace(question=types.SimpleNamespace(identity=qid))

        cases = [make("q" + str(i)) for i in range(20)]
        rows = []
        for c in cases:
            for arm, view in exp.POSITIONS:
                answer = (
                    "TAG-GOLD"
                    if arm in exp.SUFFICIENT and view != "e_label"
                    else "E1 E2"
                    if arm in exp.SUFFICIENT
                    else "TAG-DECOY"
                    if arm == "decoy_only"
                    else "I do not have enough evidence."
                )
                rows.append(
                    dict(
                        qid=c.question.identity,
                        arm=arm,
                        view=view,
                        status="succeeded",
                        answer=answer,
                        reader=dict(
                            input_tokens=35 if view == "unlabeled" else 45,
                            generated_tokens=5,
                            cpu_time_ns=100,
                        ),
                    )
                )

        def fake_score(_c, arm, txt):
            correct = txt == "TAG-GOLD"
            refusal = txt == "I do not have enough evidence."
            return dict(
                exact_answer=correct,
                appropriate_refusal=arm not in exp.SUFFICIENT and refusal,
                over_refusal=arm in exp.SUFFICIENT and refusal,
                unsupported_tag_copy=arm not in exp.SUFFICIENT
                and txt.startswith("TAG-"),
                label_only_echo=txt.startswith("E1"),
                strict_success=(correct if arm in exp.SUFFICIENT else refusal),
            )

        with patch.object(exp, "score", side_effect=fake_score):
            # Reassign equal E-label and alias input count for correct preflight.
            for row in rows:
                if row["view"] == "neutral_alias":
                    row["reader"]["input_tokens"] = 45
            report = exp.summarize(rows, cases)
            index = {(r["arm"], r["view"]): r for r in report["conditions"]}
            self.assertEqual(
                index["target_decoy_first", "neutral_alias"]["answers"], 20
            )
            self.assertEqual(index["target_decoy_first", "e_label"]["answers"], 0)
            self.assertEqual(
                index["decoy_only", "neutral_alias"]["unsupported_copies"], 20
            )
            self.assertEqual(report["disposition"], "no_safe_reader_adequacy_gain")
            pair = [
                p
                for p in report["paired"]
                if p["arm"] == "target_decoy_first" and p["first"] == "e_label"
            ][0]
            self.assertEqual(
                (
                    pair["both"],
                    pair["first_only"],
                    pair["second_only"],
                    pair["neither"],
                ),
                (0, 0, 20, 0),
            )
            with self.assertRaises(ValueError):
                exp.summarize(rows[:-1], cases)
            with self.assertRaises(ValueError):
                exp.summarize(rows + rows[:1], cases)
            rows[0]["status"] = "failed"
            with self.assertRaisesRegex(ValueError, "failed Reader"):
                exp.summarize(rows, cases)


class FakeBundle:
    def __init__(self, docs):
        self.docs = docs

    def seal(self):
        return "bound-source-seal"

    def validate(self, *args, **kwargs):
        pass

    def delivered(self):
        return [
            dict(
                label="E" + str(i + 1),
                observed_at="2026-08-05",
                excerpt=d.content,
                original_id=d.identity,
            )
            for i, d in enumerate(self.docs)
        ]


class FakeReader:
    def __init__(self):
        self.identity = exp.STRONG_ID
        self.tokenizer = MockTokenizer()
        self.inventory = {"model.safetensors": {"sha256": "a" * 64}}
        self.verified = False

    def verify_frozen(self):
        self.verified = True


@dataclass(frozen=True)
class FakeQuestion:
    identity: str
    content: str
    observed_at: str


def fake_modules():
    case = types.SimpleNamespace(
        question=FakeQuestion("q0", "Which TAG?", "2026-08-06"), answer="TAG-GOLD"
    )
    docs = {
        "target_decoy_first": [
            types.SimpleNamespace(
                identity="target", content="Device requires TAG-GOLD"
            ),
            types.SimpleNamespace(
                identity="decoy", content="Device requires TAG-DECOY"
            ),
        ],
        "target_decoy_last": [
            types.SimpleNamespace(
                identity="decoy", content="Device requires TAG-DECOY"
            ),
            types.SimpleNamespace(
                identity="target", content="Device requires TAG-GOLD"
            ),
        ],
        "decoy_only": [
            types.SimpleNamespace(identity="decoy", content="Device requires TAG-DECOY")
        ],
        "no_evidence": [],
    }
    tag = types.ModuleType("system2_reader_tag_label_order")
    tag.PARENT_SHA = exp.PARENT_SHA
    tag.PROFILE = "credential_tag"
    tag.MAX_NEW_TOKENS = 64
    tag.TOKEN_LIMIT = 1024
    capacity = types.ModuleType("system2_reader_capacity_reference")
    capacity.MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
    capacity.MODEL_REV = "a338b55dd21219a5f4da42bc11a9313d1a27d4cc"
    tag.context = lambda c, a: (c, tuple(docs[a]))
    lex = types.ModuleType("system2_reader_lexical_factorial")
    lex.messages = lambda c, delivered, profile: [
        dict(role="system", content="Answer or refuse"),
        dict(
            role="user",
            content=json.dumps(
                dict(
                    question=c.question.content,
                    question_time=c.question.observed_at,
                    evidence=[
                        dict(
                            label=d["label"],
                            observed_at=d["observed_at"],
                            text=d["excerpt"],
                        )
                        for d in delivered
                    ],
                ),
                separators=(",", ":"),
            ),
        ),
    ]
    lex.transform = lambda c, profile: (types.SimpleNamespace(answer=c.answer), {})
    strong = types.ModuleType("system2_reader_paired_capacity_audit")
    strong.open_strong = lambda p: (
        {
            "reference-inventory.json": json.dumps(
                dict(
                    model_id=capacity.MODEL_ID,
                    revision=capacity.MODEL_REV,
                    model_snapshot_inventory={
                        "model.safetensors": {"sha256": "a" * 64}
                    },
                )
            ).encode()
        },
        dict(reference_reader_identity=exp.STRONG_ID),
        [None] * 160,
    )
    mh = types.ModuleType("system2_multihop_trial")
    mh.evidence = lambda c, d, mode: (FakeBundle(d), {}, "frontier")
    mh.ABSTAIN = "I do not have enough evidence."
    return case, dict(
        system2_reader_tag_label_order=tag,
        system2_reader_lexical_factorial=lex,
        system2_reader_paired_capacity_audit=strong,
        system2_multihop_trial=mh,
        system2_reader_capacity_reference=capacity,
    )


class RunnerTests(unittest.TestCase):
    def test_real_hermetic_runner_seals_before_score_and_recovers_from_failure(self):
        case, modules = fake_modules()
        with (
            tempfile.TemporaryDirectory() as t,
            patch.dict(sys.modules, modules),
            patch.object(exp, "new_cohort", return_value=(case,)),
            patch.object(exp, "PLANNED", len(exp.POSITIONS)),
        ):
            archive = Path(t) / "archive.zip"
            archive.write_bytes(b"stub original pin")
            with patch.object(
                exp, "PARENT_SHA", sha256(archive.read_bytes()).hexdigest()
            ):
                # The historical trial pin is tied to the fake archive only in this unit.
                modules["system2_reader_tag_label_order"].PARENT_SHA = exp.PARENT_SHA
                reader = FakeReader()
                seen = []

                def fake_infer(
                    reader, c, docs, arm, view, alias, ids, bundle, originals, frontier
                ):
                    seen.append((arm, view))
                    answer = (
                        "TAG-GOLD"
                        if arm in exp.SUFFICIENT
                        else "I do not have enough evidence."
                    )
                    return answer, dict(
                        reader_identity=reader.identity,
                        reader_profile="d" * 64,
                        model_id=modules["system2_reader_capacity_reference"].MODEL_ID,
                        revision=modules["system2_reader_capacity_reference"].MODEL_REV,
                        question_digest=exp.digest(asdict(c.question)),
                        generated_ids_digest="e" * 64,
                        input_ids_digest=exp.digest(ids),
                        bundle_digest=bundle.seal(),
                        delivered_evidence=bundle.delivered(),
                        answer_postprocessed=False,
                        trainable_parameters=0,
                        input_tokens=len(ids),
                        generated_tokens=10,
                        cpu_time_ns=100,
                        wall_time_ns=100,
                    )

                out = Path(t) / "run"
                receipt = exp.run(
                    out,
                    reader,
                    parent_archive=archive,
                    source_commit="a" * 40,
                    infer_fn=fake_infer,
                )
                self.assertEqual(len(seen), len(exp.POSITIONS))
                self.assertEqual(receipt["disposition"], "no_safe_reader_adequacy_gain")
                self.assertTrue(reader.verified)
                self.assertEqual(
                    len((out / "raw-answers.jsonl").read_text().splitlines()),
                    len(exp.POSITIONS),
                )
                self.assertEqual(
                    len((out / "input-preflight.jsonl").read_text().splitlines()),
                    len(exp.POSITIONS),
                )
                sealed = json.loads((out / "raw-seal.json").read_text())
                self.assertEqual(
                    sealed["sha256"],
                    sha256((out / "raw-answers.jsonl").read_bytes()).hexdigest(),
                )

                reader2 = FakeReader()

                def fail(*_):
                    raise RuntimeError("model crashed")

                failing = Path(t) / "failed"
                with self.assertRaises(RuntimeError):
                    exp.run(
                        failing,
                        reader2,
                        parent_archive=archive,
                        source_commit="b" * 40,
                        infer_fn=fail,
                    )
                self.assertTrue((failing / "failure.json").exists())
                self.assertTrue((failing / "input-seal.json").exists())
                self.assertFalse((failing / "raw-seal.json").exists())
                self.assertEqual(
                    len((failing / "raw-answers.jsonl").read_text().splitlines()), 1
                )

    def test_invalid_source_commit_and_parent_pin_abort_before_input(self):
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "bad.zip"
            a.write_bytes(b"incorrect archive")
            reader = FakeReader()
            with self.assertRaises(ValueError):
                exp.run(Path(t) / "bad1", reader, parent_archive=a, source_commit="bad")
            _, modules = fake_modules()
            with patch.dict(sys.modules, modules):
                with self.assertRaisesRegex(ValueError, "zip pin"):
                    exp.run(
                        Path(t) / "bad2",
                        reader,
                        parent_archive=a,
                        source_commit="a" * 40,
                    )


if __name__ == "__main__":
    unittest.main()
