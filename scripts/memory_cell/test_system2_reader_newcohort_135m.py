"""Frozen 135M Reader same-new-questions comparator: no model knowledge leaks."""

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from native import digest
from system2_multihop_evidence import parse_relation
from system2_multihop_trial import ABSTAIN, evidence
from system2_onehop_label_ablation import SYSTEM, prompt_messages
from system2_reader_capacity_reference import ARMS, cohorts, selected, READER_IDENTITY
from system2_reader_newcohort_135m import (
    NEW_CALLS,
    SCHEMA,
    original_prompt_parity,
    load_baseline_archives,
    plan,
    presentation_for,
    run,
    score,
)


class FakeShared:
    identity = READER_IDENTITY
    inventory = {"model.safetensors": {"sha256": "fake-only-not-a-model"}}

    def __init__(self):
        self.verified = 0

    def verify_frozen(self):
        self.verified += 1


class FakeWrapper:
    """Symbolic fake used to test runner behavior; never model evidence."""

    def __init__(self, shared, presentation):
        self.shared = shared
        self.presentation = presentation
        self.profile = "fixed-test-profile-" + presentation
        self.calls = 0

    def compile_input(
        self, query, bundle, originals, *, frontier, revoked, token_limit
    ):
        bundle.validate(query, originals, frontier=frontier, revoked=revoked)
        self.asserted_limit = token_limit
        content = json.dumps(
            prompt_messages(query, bundle.delivered(), self.presentation),
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        tokens = list(content)
        assert 0 < len(tokens) <= 1024
        receipt = dict(
            bundle_digest=bundle.seal(),
            query_digest=digest(asdict(query)),
            input_ids_digest=digest(tokens),
            input_tokens=len(tokens),
            token_limit=token_limit,
            delivered_evidence=bundle.delivered(),
        )
        return tokens, receipt

    def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
        self.calls += 1
        _, receipt = self.compile_input(
            query,
            bundle,
            originals,
            frontier=frontier,
            revoked=revoked,
            token_limit=token_limit,
        )
        device = query.content.split("device ")[1].rstrip("?")
        matching = []
        for d in bundle.delivered():
            row = originals[d["original_id"]]
            rel = parse_relation(row)
            if rel and rel[0] == "device" and rel[1] == device and rel[2] == "token":
                matching.append(rel[3])
        answer = matching[0] if len(set(matching)) == 1 and matching else ABSTAIN
        receipt.update(
            reader_identity=self.shared.identity,
            reader_profile=self.profile,
            answer_postprocessed=False,
            trainable_parameters=0,
            generated_tokens=9,
            generated_ids_digest=digest([ord(x) for x in answer]),
        )
        return answer, receipt


def fake_fixture():
    shared = FakeShared()
    wrappers = {p: FakeWrapper(shared, p) for p in ("labeled", "unlabeled")}
    groups = cohorts()
    by_key = {}
    for case in groups["exposed_20"]:
        for arm in ARMS:
            p = presentation_for(arm)
            docs = selected(case, arm)
            bundle, originals, frontier = evidence(case, docs, "answer-only:" + arm)
            _, rec = wrappers[p].compile_input(
                case.question,
                bundle,
                originals,
                frontier=frontier,
                revoked=set(),
                token_limit=1024,
            )
            rec.update(
                reader_identity=shared.identity,
                reader_profile=wrappers[p].profile,
                generated_ids_digest=digest([1, 2, 3]),
            )
            by_key[case.question.identity, arm, p] = dict(
                status="succeeded",
                selected=[d.identity for d in docs],
                reader=rec,
                answer=case.answer if arm in ARMS[:2] else ABSTAIN,
            )
    return shared, wrappers, groups, dict(by_key=by_key, raw_sha256="f" * 64)


class SameQuestionReaderTests(unittest.TestCase):
    def test_cohorts_and_profile_have_no_leak(self):
        groups = cohorts()
        self.assertEqual(
            [len(groups[n]) for n in ("exposed_20", "fixed_new_20")], [20, 20]
        )
        self.assertFalse(
            {c.question.identity for c in groups["exposed_20"]}
            & {c.question.identity for c in groups["fixed_new_20"]}
        )
        self.assertEqual(NEW_CALLS, 80)
        self.assertEqual(presentation_for("no_evidence"), "unlabeled")
        for arm in ARMS[:-1]:
            self.assertEqual(presentation_for(arm), "labeled")
        for case in groups["fixed_new_20"]:
            forged = replace(case, answer="TOK-0000000")
            for arm in ARMS:
                self.assertEqual(selected(case, arm), selected(forged, arm))

    def test_one_shared_system_message_and_invariant_evidence(self):
        groups = cohorts()
        case = groups["fixed_new_20"][0]
        docs = selected(case, "target_decoy_two_first")
        bundle, _, _ = evidence(case, docs, "answer-only:target_decoy_two_first")
        messages = prompt_messages(case.question, bundle.delivered(), "labeled")
        self.assertEqual(messages[0]["content"], SYSTEM)
        self.assertEqual(len(messages), 2)
        self.assertIn(docs[0].content, messages[1]["content"])
        self.assertIn(docs[1].content, messages[1]["content"])
        self.assertNotIn(case.answer, messages[0]["content"])

    def test_archived_old_80_source_prompt_parity_without_old_model_calls(self):
        shared, wrappers, groups, parent = fake_fixture()
        receipt = original_prompt_parity(groups, parent, wrappers, shared)
        self.assertEqual(len(receipt), 80)
        self.assertTrue(all(x["new_model_calls"] == 0 for x in receipt))
        self.assertTrue(all(x["model_calls_reused"] == 1 for x in receipt))
        self.assertEqual(sum(w.calls for w in wrappers.values()), 0)
        recorded = plan(groups, "a" * 40, shared, parent["raw_sha256"], receipt)
        self.assertEqual(recorded["actual_new_135m_model_calls"], 80)
        self.assertEqual(recorded["original_135m_model_calls_reused"], 80)
        self.assertTrue(recorded["different_model_tokenizer_and_compute_not_matched"])
        self.assertFalse(recorded["production_accepted"])
        self.assertEqual(recorded["schema"], SCHEMA)
        with self.assertRaises(ValueError):
            plan(groups, "bad-commit", shared, parent["raw_sha256"], receipt)

    def test_tampering_old_digest_blocks_any_new_model_call(self):
        shared, wrappers, groups, parent = fake_fixture()
        key = next(iter(parent["by_key"]))
        parent["by_key"][key]["reader"]["input_ids_digest"] = "00" * 32
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "blocked"
            with self.assertRaisesRegex(ValueError, "old exact encoded"):
                run(
                    output,
                    shared,
                    cardinality_archive="unused",
                    label_archive="unused",
                    source_commit="a" * 40,
                    groups=groups,
                    wrappers=wrappers,
                    original=parent,
                )
            self.assertFalse(output.exists())
            self.assertEqual(sum(w.calls for w in wrappers.values()), 0)

    def test_missing_old_response_fails_closed(self):
        shared, wrappers, groups, parent = fake_fixture()
        parent["by_key"].pop(next(iter(parent["by_key"])))
        with self.assertRaisesRegex(ValueError, "missing previously completed"):
            original_prompt_parity(groups, parent, wrappers, shared)

    def test_receipt_only_bundle_binding_is_admitted_without_model_calls(self):
        # The completed hosted label study persists bundle_digest in the
        # Reader receipt, NOT as a duplicate top-level row field.
        shared, wrappers, groups, parent = fake_fixture()
        self.assertTrue(
            all("bundle_digest" not in row for row in parent["by_key"].values())
        )
        parity = original_prompt_parity(groups, parent, wrappers, shared)
        self.assertEqual(len(parity), NEW_CALLS)
        self.assertEqual(sum(w.calls for w in wrappers.values()), 0)

    def test_tampered_reader_only_bundle_drift_fails_closed(self):
        shared, wrappers, groups, parent = fake_fixture()
        key = next(iter(parent["by_key"]))
        parent["by_key"][key]["reader"]["bundle_digest"] = "forged-bundle"
        with self.assertRaisesRegex(ValueError, "old exact encoded"):
            original_prompt_parity(groups, parent, wrappers, shared)
        self.assertEqual(sum(w.calls for w in wrappers.values()), 0)

    @unittest.skipUnless(
        os.environ.get("HEPTA_CARDINALITY_ARCHIVE")
        and os.environ.get("HEPTA_LABEL_ARCHIVE"),
        "pinned original 140-call and label archives not staged",
    )
    def test_real_label_archive_binds_historical_receipts_without_top_level(self):
        original = load_baseline_archives(
            os.environ["HEPTA_CARDINALITY_ARCHIVE"], os.environ["HEPTA_LABEL_ARCHIVE"]
        )
        self.assertEqual(len(original["by_key"]), 140)
        old = cohorts()["exposed_20"]
        for case in old:
            for arm in ARMS:
                presentation = presentation_for(arm)
                row = original["by_key"][case.question.identity, arm, presentation]
                self.assertNotIn("bundle_digest", row)
                selected_docs = selected(case, arm)
                bundle, _, _ = evidence(case, selected_docs, "answer-only:" + arm)
                self.assertEqual(row["reader"]["bundle_digest"], bundle.seal())
                self.assertEqual(row["selected"], [d.identity for d in selected_docs])
                self.assertEqual(
                    row["reader"]["delivered_evidence"], bundle.delivered()
                )

    def test_bad_old_source_scope_fails_closed(self):
        shared, wrappers, groups, parent = fake_fixture()
        key = next(iter(parent["by_key"]))
        parent["by_key"][key]["bundle_digest"] = "counterfeit"
        with self.assertRaisesRegex(ValueError, "old exact encoded"):
            original_prompt_parity(groups, parent, wrappers, shared)

    def test_complete_80_real_runner_with_fake_reader_and_seals(self):
        shared, wrappers, groups, parent = fake_fixture()
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "study"
            report = run(
                output,
                shared,
                cardinality_archive="unused",
                label_archive="unused",
                source_commit="b" * 40,
                groups=groups,
                wrappers=wrappers,
                original=parent,
            )
            self.assertEqual(
                (report["planned_new"], report["recorded_new"], report["failed_new"]),
                (80, 80, 0),
            )
            self.assertEqual(report["historical_old_responses_reused"], 80)
            self.assertEqual(sum(w.calls for w in wrappers.values()), 80)
            self.assertEqual(shared.verified, 2)
            self.assertEqual(
                len((output / "starts.jsonl").read_text().splitlines()), 80
            )
            self.assertEqual(
                len((output / "raw-answers.jsonl").read_text().splitlines()), 80
            )
            self.assertEqual(
                len(json.loads((output / "original-prompt-parity.json").read_text())),
                80,
            )
            seal = json.loads((output / "raw-seal.json").read_text())
            self.assertEqual(
                seal["sha256"],
                hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest(),
            )
            self.assertFalse(seal["posthoc_scoring_started"])
            self.assertTrue(
                all(r["conditional_success"] == 20 for r in report["by_arm"])
            )
            self.assertFalse(report["production_accepted"])
            self.assertTrue(report["larger_reader_needs_separate_pinned_archive"])

    def test_missing_duplicate_and_unsupported_copy_scored_separately(self):
        shared, wrappers, groups, parent = fake_fixture()
        rows = []
        for group, cases_ in groups.items():
            for case in cases_:
                for arm in ARMS:
                    rows.append(
                        dict(
                            qid=case.question.identity,
                            cohort=group,
                            arm=arm,
                            selected=[d.identity for d in selected(case, arm)],
                            status="succeeded",
                            answer=case.answer if arm in ARMS[:2] else ABSTAIN,
                        )
                    )
        self.assertEqual(len(score(rows, groups)), 8)
        with self.assertRaises(ValueError):
            score(rows[:-1], groups)
        with self.assertRaises(ValueError):
            score(rows + [rows[0]], groups)
        for r in rows:
            if r["arm"] == "decoy_one":
                case = next(
                    c
                    for cs in groups.values()
                    for c in cs
                    if c.question.identity == r["qid"]
                )
                r["answer"] = (
                    case.answer
                )  # unsupported correct literal; NOT a true success
        result = score(rows, groups)
        self.assertTrue(
            all(
                row["conditional_success"] == 0
                for row in result
                if row["arm"] == "decoy_one"
            )
        )
        self.assertTrue(
            all(
                row["unsupported_token_copies"] == 20
                for row in result
                if row["arm"] == "decoy_one"
            )
        )

    def test_failure_preserves_observed_cpu_and_never_seals(self):
        shared, wrappers, groups, parent = fake_fixture()
        # The model has already produced three real attempts before injection.
        called = [0]
        for w in wrappers.values():
            old = w.answer

            def wrap(*args, original=old, **kwargs):
                called[0] += 1
                if called[0] == 4:
                    raise RuntimeError("injected model failure")
                return original(*args, **kwargs)

            w.answer = wrap
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "study"
            with self.assertRaisesRegex(RuntimeError, "injected model failure"):
                run(
                    output,
                    shared,
                    cardinality_archive="unused",
                    label_archive="unused",
                    source_commit="c" * 40,
                    groups=groups,
                    wrappers=wrappers,
                    original=parent,
                )
            rows = list(
                map(json.loads, (output / "raw-answers.jsonl").read_text().splitlines())
            )
            self.assertEqual(len(rows), 4)
            self.assertEqual(
                [r["status"] for r in rows], ["succeeded"] * 3 + ["failed"]
            )
            self.assertTrue(rows[-1]["unknown_inflight_work"])
            self.assertIn("process_cpu_ns", rows[-1])
            self.assertFalse((output / "raw-seal.json").exists())
            self.assertFalse((output / "summary.json").exists())
            failure = json.loads((output / "run-failure.json").read_text())
            self.assertEqual(failure["planned_new"], 80)
            self.assertEqual(failure["completed_new"], 3)
            self.assertTrue(failure["inflight_and_missing_work_not_free"])

    def test_corrupt_reader_identity_prevents_registration(self):
        shared, wrappers, groups, parent = fake_fixture()
        shared.identity = "wrong-reference"
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "bad"
            with self.assertRaises(ValueError):
                run(
                    output,
                    shared,
                    cardinality_archive="unused",
                    label_archive="unused",
                    source_commit="d" * 40,
                    groups=groups,
                    wrappers=wrappers,
                    original=parent,
                )
            self.assertFalse(output.exists())

    @unittest.skipUnless(
        os.environ.get("HEPTA_CARDINALITY_ARCHIVE")
        and os.environ.get("HEPTA_LABEL_ARCHIVE"),
        "pinned original 140-call and label archives not staged",
    )
    def test_two_real_archives_match_external_sha_and_all_140_original_answers(self):
        original = load_baseline_archives(
            os.environ["HEPTA_CARDINALITY_ARCHIVE"], os.environ["HEPTA_LABEL_ARCHIVE"]
        )
        self.assertEqual(
            (original["verified_files"], len(original["by_key"])), (25, 140)
        )


if __name__ == "__main__":
    unittest.main()
