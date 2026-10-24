import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from full_cell_matrix import (
    _digest_bytes,
    evaluate_reader_gate,
    enumerate_matrix,
    main,
    plan,
    resource_estimate,
)
from reader_originals_attestation import SCHEMA, canonical_sha, source_fingerprint


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def original_case(qid, condition, grounded, refusal):
    # Ephemeral deterministic TEST originals. They are not independent reviews
    # and MUST NEVER be used to qualify a real Reader.
    def source(name):
        content = f"Original fixture {name} for {qid}."
        return dict(
            identity=f"{qid}-{name}",
            root=f"root-{qid}-{name}",
            scope=qid,
            session=f"session-{qid}",
            observed_at="2026-01-01T00:00:00+00:00",
            content=content,
            start=0,
            end=len(content.encode("utf-8")),
        )

    choices = {
        "no_evidence": [],
        "ordinary_retrieval": [source("b")],
        "human_sufficient": [source("a"), source("b")],
        "critical_premise_removed": [source("b")],
    }
    answer = (
        "fixture grounded answer [E1]"
        if grounded
        else "I do not have enough evidence."
        if refusal
        else "fixture ungrounded answer"
    )
    return dict(
        item_id=qid,
        condition=condition,
        question_record=dict(
            identity=qid,
            family="fixture",
            scope=qid,
            content="Which evidence supports the fact?",
            observed_at="2026-01-02T00:00:00+00:00",
        ),
        input_ids=[ord(c) for c in qid + condition],
        raw_answer=answer,
        delivered_sources=choices[condition],
    )


def original_fixture(gate):
    return dict(
        schema=SCHEMA,
        cohort=list(gate["cohort"]),
        model_binding=copy.deepcopy(gate["model_binding"]),
        items=[
            original_case(
                row["item_id"],
                row["condition"],
                row["grounded_and_cited"],
                row["exact_refusal"],
            )
            for row in gate["reviewed_items"]
        ],
    )


def gate_fixture():
    trust = {
        "schema": "hepta.reader.trust.v1",
        "independent_reviewers": [],
    }
    ids = [f"q-{i}" for i in range(20)]
    binding = {
        name: f"{chr(97 + index) * 64}"
        for index, name in enumerate(
            ("weights_sha256", "tokenizer_sha256", "prompt_sha256", "dataset_sha256")
        )
    }
    binding.update(revision="model-r1", decode_budget=64)
    gate = {
        "schema": "hepta.reader-gate.v2",
        "cohort": ids,
        "model_binding": binding,
        "independent_review": {"trust_manifest_sha256": ""},
        "capabilities": {"modalities": ["text"], "inference": ["no_recurrent"]},
        "conditions": {
            "no_evidence": {
                "item_ids": ids,
                "total": 20,
                "grounded_and_cited": 0,
                "exact_refusal": 19,
            },
            "ordinary_retrieval": {
                "item_ids": ids,
                "total": 20,
                "grounded_and_cited": 7,
                "exact_refusal": 3,
            },
            "human_sufficient": {
                "item_ids": ids,
                "total": 20,
                "grounded_and_cited": 18,
                "exact_refusal": 0,
            },
            "critical_premise_removed": {
                "item_ids": ids,
                "total": 20,
                "grounded_and_cited": 0,
                "exact_refusal": 20,
            },
        },
    }
    # Synthetic, ephemeral review receipts exercise SIGNATURE CODE only;
    # they are not real human/source judgments and confer no production trust.
    rows = []
    for condition in (
        "no_evidence",
        "ordinary_retrieval",
        "human_sufficient",
        "critical_premise_removed",
    ):
        summary = gate["conditions"][condition]
        for i, qid in enumerate(ids):
            grounded = i < summary["grounded_and_cited"]
            refusal = (
                summary["grounded_and_cited"]
                <= i
                < summary["grounded_and_cited"] + summary["exact_refusal"]
            )
            original = original_case(qid, condition, grounded, refusal)
            delivered = [source_fingerprint(x) for x in original["delivered_sources"]]
            rows.append(
                dict(
                    item_id=qid,
                    condition=condition,
                    question_sha256=canonical_sha(original["question_record"]),
                    prompt_input_ids_sha256=canonical_sha(original["input_ids"]),
                    raw_answer_sha256=canonical_sha(original["raw_answer"]),
                    delivered_source_sha256=delivered,
                    cited_source_sha256=[delivered[0]] if grounded else [],
                    grounded_and_cited=grounded,
                    exact_refusal=refusal,
                )
            )
    gate["reviewed_items"] = rows
    reviewed = {
        name: gate[name]
        for name in (
            "schema",
            "cohort",
            "model_binding",
            "conditions",
            "capabilities",
            "reviewed_items",
        )
    }
    reviewed_digest = fingerprint(reviewed)
    roster = {"schema": "hepta.reader.authorized-reviewers.v1", "reviewers": []}
    signed = b"hepta.reader-gate.v2.ed25519\x00" + bytes.fromhex(reviewed_digest)
    for identifier in ("reviewer-a", "reviewer-b"):
        # Ephemeral keys exist only in the test process. Never publish a
        # private key, or call fixture signatures real human review.
        key = Ed25519PrivateKey.generate()
        public = (
            key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )
        roster["reviewers"].append(
            dict(
                id=identifier,
                public_key_hex=public,
                authorized=True,
                independent_of_model_owner=True,
                independent_of_dataset_owner=True,
            )
        )
        trust["independent_reviewers"].append(
            dict(
                id=identifier,
                revoked=False,
                signature_hex=key.sign(signed).hex(),
            )
        )
    trust["reviewed_gate_content_sha256"] = reviewed_digest
    trust["authorized_reviewer_roster_sha256"] = fingerprint(roster)
    trust["originals_sha256"] = fingerprint(original_fixture(gate))
    gate["independent_review"]["trust_manifest_sha256"] = fingerprint(trust)
    return gate, trust, roster


class FullCellMatrixTests(unittest.TestCase):
    def test_matrix_has_all_declared_axes(self):
        rows = enumerate_matrix(cells=4)
        self.assertEqual(len(rows), 4 * 4 * 4 * 4 * 3)
        self.assertEqual(len({row["config_id"] for row in rows}), len(rows))

    def test_resource_estimate_does_not_call_nominal_parameters_flops(self):
        row = resource_estimate(
            "shared_421m_plus_head", "gated", "video", "system2_ndu", "split_merge", 32
        )
        self.assertIsNone(row["active_flops"])
        self.assertIsNone(row["peak_memory_bytes"])
        self.assertIsNone(row["energy_joules"])
        self.assertEqual(
            row["parameter_budget"]["incremental_cell_parameters"], 2_000_000
        )

    def test_replicated_stem_costs_more_than_shared(self):
        shared = resource_estimate(
            "shared_421m_plus_head", "gated", "text", "no_recurrent", "no_split", 32
        )
        copied = resource_estimate(
            "replicated_421m", "gated", "text", "no_recurrent", "no_split", 32
        )
        self.assertGreater(
            copied["parameter_budget"]["unique_parameters"],
            shared["parameter_budget"]["unique_parameters"] * 20,
        )

    def test_reader_gate_requires_external_model_bound_trust_and_same_cohort(self):
        gate, trust, roster = gate_fixture()
        self.assertFalse(evaluate_reader_gate(gate, trust).passed)
        self.assertEqual(
            evaluate_reader_gate(
                gate, trust, trusted_review_sha256=fingerprint(trust)
            ).reason,
            "out-of-band-reviewer-roster-required",
        )
        self.assertTrue(
            evaluate_reader_gate(
                gate,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=roster,
                trusted_roster_sha256=fingerprint(roster),
                original_sources=original_fixture(gate),
                trusted_originals_sha256=fingerprint(original_fixture(gate)),
            ).passed
        )
        self.assertFalse(evaluate_reader_gate(gate).passed)
        gate["conditions"]["ordinary_retrieval"]["item_ids"] = ["different"] * 20
        self.assertFalse(evaluate_reader_gate(gate, trust).passed)

    def test_self_attested_manifest_alone_never_enables_model_experiments(self):
        gate, trust, roster = gate_fixture()
        self.assertEqual(
            evaluate_reader_gate(gate, trust).reason, "out-of-band-trust-pin-required"
        )
        self.assertEqual(
            evaluate_reader_gate(gate, trust, trusted_review_sha256="a" * 64).reason,
            "out-of-band-trust-pin-mismatch",
        )
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(
                Path(directory), cells=2, reader_gate=gate, trust_manifest=trust
            )
            self.assertEqual(summary["blocked_reader_records"], 768)
            self.assertEqual(summary["planned_neural_records"], 0)

    def test_edited_scores_are_not_the_same_independent_review(self):
        gate, trust, roster = gate_fixture()
        approved = fingerprint(trust)
        forged = copy.deepcopy(gate)
        forged["conditions"]["human_sufficient"]["grounded_and_cited"] = 20
        self.assertEqual(
            evaluate_reader_gate(forged, trust, trusted_review_sha256=approved).reason,
            "review-not-bound-to-observed-reader-results",
        )
        altered = copy.deepcopy(trust)
        reviewed = {
            name: forged[name]
            for name in (
                "schema",
                "cohort",
                "model_binding",
                "conditions",
                "capabilities",
                "reviewed_items",
            )
        }
        altered["reviewed_gate_content_sha256"] = fingerprint(reviewed)
        forged["independent_review"]["trust_manifest_sha256"] = fingerprint(altered)
        self.assertEqual(
            evaluate_reader_gate(
                forged, altered, trusted_review_sha256=approved
            ).reason,
            "out-of-band-trust-pin-mismatch",
        )

    def test_forged_capability_and_duplicate_reviewer_are_rejected(self):
        gate, trust, roster = gate_fixture()
        bad = copy.deepcopy(gate)
        bad["capabilities"]["modalities"] = ["text", "text"]
        self.assertEqual(
            evaluate_reader_gate(
                bad, trust, trusted_review_sha256=fingerprint(trust)
            ).reason,
            "invalid-reader-capabilities",
        )
        double = copy.deepcopy(trust)
        double["independent_reviewers"].append(
            copy.deepcopy(double["independent_reviewers"][0])
        )
        gated = copy.deepcopy(gate)
        gated["independent_review"]["trust_manifest_sha256"] = fingerprint(double)
        self.assertEqual(
            evaluate_reader_gate(
                gated, double, trusted_review_sha256=fingerprint(double)
            ).reason,
            "no-current-independent-reviewer-in-trust-manifest",
        )

    def test_manifest_sha_and_self_named_reviewer_do_not_prove_independence(self):
        gate, trust, roster = gate_fixture()
        self.assertEqual(
            evaluate_reader_gate(
                gate, trust, trusted_review_sha256=fingerprint(trust)
            ).reason,
            "out-of-band-reviewer-roster-required",
        )
        self.assertEqual(
            evaluate_reader_gate(
                gate,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=roster,
                trusted_roster_sha256="0" * 64,
            ).reason,
            "reviewer-roster-pin-mismatch",
        )
        fake = copy.deepcopy(roster)
        fake["reviewers"][0]["id"] = "self-claimed-reviewer"
        self.assertEqual(
            evaluate_reader_gate(
                gate,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=fake,
                trusted_roster_sha256=fingerprint(fake),
            ).reason,
            "reviewer-roster-pin-mismatch",
        )

    def test_valid_manifest_with_forged_signature_fails_closed(self):
        gate, trust, roster = gate_fixture()
        trust["independent_reviewers"][0]["signature_hex"] = "00" * 64
        gate["independent_review"]["trust_manifest_sha256"] = fingerprint(trust)
        self.assertEqual(
            evaluate_reader_gate(
                gate,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=roster,
                trusted_roster_sha256=fingerprint(roster),
            ).reason,
            "reviewer-signature-verification-failed",
        )

    def test_one_signer_or_unapproved_signer_cannot_unlock_full_matrix(self):
        gate, trust, roster = gate_fixture()
        one = copy.deepcopy(trust)
        one["independent_reviewers"] = one["independent_reviewers"][:1]
        gated = copy.deepcopy(gate)
        gated["independent_review"]["trust_manifest_sha256"] = fingerprint(one)
        self.assertEqual(
            evaluate_reader_gate(
                gated,
                one,
                trusted_review_sha256=fingerprint(one),
                reviewer_roster=roster,
                trusted_roster_sha256=fingerprint(roster),
            ).reason,
            "no-current-independent-reviewer-in-trust-manifest",
        )
        unknown = copy.deepcopy(trust)
        unknown["independent_reviewers"][0]["id"] = "attacker"
        gated["independent_review"]["trust_manifest_sha256"] = fingerprint(unknown)
        self.assertEqual(
            evaluate_reader_gate(
                gated,
                unknown,
                trusted_review_sha256=fingerprint(unknown),
                reviewer_roster=roster,
                trusted_roster_sha256=fingerprint(roster),
            ).reason,
            "missing-or-unauthorized-reviewer-signature",
        )

    def test_relabelled_or_duplicate_roster_key_fails_closed(self):
        gate, trust, roster = gate_fixture()
        duplicate = copy.deepcopy(roster)
        duplicate["reviewers"][1]["public_key_hex"] = duplicate["reviewers"][0][
            "public_key_hex"
        ]
        changed = copy.deepcopy(trust)
        changed["authorized_reviewer_roster_sha256"] = fingerprint(duplicate)
        gated = copy.deepcopy(gate)
        gated["independent_review"]["trust_manifest_sha256"] = fingerprint(changed)
        self.assertEqual(
            evaluate_reader_gate(
                gated,
                changed,
                trusted_review_sha256=fingerprint(changed),
                reviewer_roster=duplicate,
                trusted_roster_sha256=fingerprint(duplicate),
            ).reason,
            "duplicated-authorized-reviewer-key",
        )
        revoked = copy.deepcopy(roster)
        revoked["reviewers"][0]["authorized"] = False
        changed["authorized_reviewer_roster_sha256"] = fingerprint(revoked)
        gated["independent_review"]["trust_manifest_sha256"] = fingerprint(changed)
        self.assertEqual(
            evaluate_reader_gate(
                gated,
                changed,
                trusted_review_sha256=fingerprint(changed),
                reviewer_roster=revoked,
                trusted_roster_sha256=fingerprint(revoked),
            ).reason,
            "invalid-authorized-reviewer-roster",
        )

    def test_signatures_are_bound_to_cohort_model_and_original_scores(self):
        gate, trust, roster = gate_fixture()
        wrong = copy.deepcopy(gate)
        wrong["model_binding"]["revision"] = "model-r2"
        self.assertEqual(
            evaluate_reader_gate(
                wrong,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=roster,
                trusted_roster_sha256=fingerprint(roster),
            ).reason,
            "review-not-bound-to-observed-reader-results",
        )

    def test_unqualified_plan_blocks_every_record_and_leaves_scores_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(Path(directory), cells=2)
            self.assertEqual(summary["blocked_reader_records"], 768)
            self.assertEqual(summary["neural_calls"], 0)
            rows = [
                json.loads(line)
                for line in (Path(directory) / "matrix-plan.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertTrue(all(row["status"] == "blocked_reader_gate" for row in rows))
            self.assertTrue(
                all(value is None for row in rows for value in row["metrics"].values())
            )

    def test_passed_reader_gate_only_admits_bound_capability(self):
        gate, trust, roster = gate_fixture()
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(
                Path(directory),
                cells=2,
                reader_gate=gate,
                trust_manifest=trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=roster,
                trusted_roster_sha256=fingerprint(roster),
                original_sources=original_fixture(gate),
                trusted_originals_sha256=fingerprint(original_fixture(gate)),
            )
            self.assertEqual(
                summary["reader_gate"]["authorized_reviewer_roster_digest"],
                fingerprint(roster),
            )
            self.assertEqual(summary["planned_neural_records"], 48)
            self.assertEqual(summary["blocked_capability_records"], 720)

    def test_unicode_originals_use_one_specified_canonical_digest(self):
        # JSON's default ASCII escaping MUST NOT differ from the source
        # attestation's UTF-8 canonical serialization for natural transcripts.
        for value in (
            {"source": "设备 🎯", "answer": "[E1]"},
            {"query": "日本語", "evidence": ["中文", "😀"]},
        ):
            self.assertEqual(_digest_bytes(value), canonical_sha(value))

    def test_cli_never_admits_originals_without_separate_raw_file_pin(self):
        # Synthetic key fixtures test only structural enforcement, not real
        # independent reviews, valid authority or real production decisions.
        gate, trust, roster = gate_fixture()
        originals = original_fixture(gate)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for name, value in (
                ("gate.json", gate),
                ("trust.json", trust),
                ("roster.json", roster),
                ("originals.json", originals),
            ):
                path = root / name
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                files.append(str(path))
            env = {
                "HEPTA_READER_TRUST_SHA256": fingerprint(trust),
                "HEPTA_REVIEWER_ROSTER_SHA256": fingerprint(roster),
                "HEPTA_READER_ORIGINALS_SHA256": canonical_sha(originals),
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(
                    ValueError, "out-of-band-original-file-pin-required"
                ):
                    main(["full_cell_matrix.py", str(root / "not-started"), *files])
            self.assertFalse((root / "not-started").exists())

    def test_cli_rejects_duplicate_json_fields_before_any_gate_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "gate.json"
            gate.write_text('{"schema":"hepta.reader-gate.v2","schema":"other"}')
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                main(["full_cell_matrix.py", str(root / "not-started"), str(gate)])
            self.assertFalse((root / "not-started").exists())


if __name__ == "__main__":
    unittest.main()
