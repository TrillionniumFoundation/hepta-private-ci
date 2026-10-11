"""No real data/authority: adversarial protocol-only fixture tests."""

from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from hepta_neuron_real_cohort_preflight import (
    COHORT_SCHEMA,
    TRUST_SCHEMA,
    ATTEST_SCHEMA,
    ROLES,
    SPLITS,
    DOMAIN,
    InvalidCohort,
    canonical,
    observation_digest,
    sha_bytes,
    verify,
)

FREEZE = 1_757_000_000_000_000


def dig(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def object_fixture(family="decisions", kind="deployed_learned"):
    sealed = []
    join = []
    members = []
    for i, split in enumerate(SPLITS):
        micros = (
            FREEZE - 50_000_000 + (i * 20_000_000)
            if i < 3
            else FREEZE + (i - 2) * 90_000_000
        )
        row = {
            "id": f"row-{i}",
            "split": split,
            "source_group": f"group-{i}",
            "observed_at_ms": micros // 1000,
        }
        if family == "heads":
            row.update(
                {
                    "features_q24": [10000 + i, 20000 + i],
                    "target_q24": [500, 600, 700, 800],
                }
            )
        else:
            row.update(
                {
                    "state": f"approved-view-{i}",
                    "question": {
                        "type": "choice",
                        "instructions": "Select the route",
                        "criteria": {"a": "A", "b": "B"},
                    },
                    "option_order": ["a", "b"],
                    "language": "en",
                    "domain": "triage",
                    "gold": "a",
                    "is_ood": False,
                }
            )
        sealed.append(row)
        dec, out = dig(f"decision-{i}"), dig(f"terminal-{i}")
        members.extend([dec, out])
        join.append(
            {
                "id": row["id"],
                "episode_id": f"episode-{i}",
                "split": split,
                "source_group": row["source_group"],
                "decision_record_digest": dec,
                "terminal_outcome_record_digest": out,
                "observation_sha256": observation_digest(row, family),
                "observed_at_unix_micros": micros,
                "terminal_at_unix_micros": micros + 1_000_000,
                "terminality": "Terminal",
            }
        )
    baseline = {
        "kind": kind,
        "scope_digest": dig("scope"),
        "objective_digest": dig("objective"),
        "generation": 10,
        "policy_digest": dig("policy"),
        "route_digest": dig("route"),
        "checkpoint_digest": dig("checkpoint"),
        "runtime_receipt_digest": dig("runtime"),
        "artifact_load_receipt_digest": dig("artifact"),
        "source_use_receipt_digest": dig("source-use"),
        "frozen_at_unix_micros": FREEZE,
        "model_manifest_digest": dig("model") if kind == "deployed_learned" else None,
        "weights_digest": dig("weights") if kind == "deployed_learned" else None,
        "code_digest": dig("code") if kind == "deployed_deterministic" else None,
    }
    return {
        "schema": COHORT_SCHEMA,
        "family": family,
        "source": "hepta.learning-ledger.LedgerWriter",
        "dataset": {
            "receipt_schema": "DatasetSnapshotReceiptV3",
            "snapshot_id": "snapshot-1",
            "dataset_digest": dig("dataset"),
            "ledger_head_digest": dig("ledger-head"),
            "objective_digest": dig("objective"),
            "correction_cut_digest": dig("correction"),
            "revocation_cut_digest": dig("revocation"),
            "inclusion_policy_digest": dig("inclusion"),
            "eligible_frontier": 12,
            "outcome_watermark": 12,
            "source_record_digests": sorted(members),
        },
        "no_change": baseline,
        "frozen_plan_digest": dig("frozen-plan"),
        "source_current_revalidated_at_unix_micros": FREEZE + 500_000_000,
        "rows": join,
    }, sealed


class RealCohortGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.paths = {
            k: root / k for k in ("cohort.json", "sealed.jsonl", "trust.json")
        }
        self.payload, self.sealed = object_fixture()
        self.keys = {role: Ed25519PrivateKey.generate() for role in ROLES}
        self.trust = {
            "schema": TRUST_SCHEMA,
            "roles": {
                role: {
                    "key_id": f"key-{role}",
                    "principal_id": f"principal-{role}",
                    "controller_id": f"controller-{role}",
                    "ed25519_public_key_hex": self.keys[role]
                    .public_key()
                    .public_bytes(
                        serialization.Encoding.Raw, serialization.PublicFormat.Raw
                    )
                    .hex(),
                }
                for role in ROLES
            },
        }

    def build(self):
        self.paths["sealed.jsonl"].write_text(
            "".join(json.dumps(row) + "\n" for row in self.sealed)
        )
        self.payload["sealed_dataset_sha256"] = sha_bytes(
            self.paths["sealed.jsonl"].read_bytes()
        )
        packet = {"schema": COHORT_SCHEMA, "payload": self.payload, "attestations": {}}
        h = sha_bytes(canonical(self.payload))
        for role in ROLES:
            a = {
                "schema": ATTEST_SCHEMA,
                "role": role,
                "key_id": "key-" + role,
                "body_sha256": h,
                "signed_at_unix_micros": FREEZE + 600_000_000,
            }
            a["signature_ed25519_hex"] = (
                self.keys[role].sign(DOMAIN + canonical(a)).hex()
            )
            packet["attestations"][role] = a
        self.paths["cohort.json"].write_text(json.dumps(packet))
        self.paths["sealed.jsonl"].write_text(
            "".join(json.dumps(row) + "\n" for row in self.sealed)
        )
        self.paths["trust.json"].write_text(json.dumps(self.trust))
        return sha_bytes(self.paths["trust.json"].read_bytes())

    def run_gate(self):
        trust_digest = self.build()
        return verify(
            self.paths["cohort.json"],
            self.paths["sealed.jsonl"],
            self.paths["trust.json"],
            trust_digest,
        )

    def must_block(self):
        with self.assertRaises(InvalidCohort):
            self.run_gate()

    def test_signed_joins_stay_non_authorizing(self):
        receipt = self.run_gate()
        self.assertEqual(receipt["verified_role_signature_count"], 5)
        self.assertEqual(receipt["row_counts_by_split"], {s: 1 for s in SPLITS})
        self.assertFalse(receipt["physical_data_origin_independently_verified"])
        self.assertFalse(receipt["ndu_net_gain_verified"])
        self.assertFalse(receipt["production_promotion_authorized"])
        self.assertNotIn("gold", json.dumps(receipt))
        self.assertNotIn("approved-view", json.dumps(receipt))

    def test_deterministic_native_nochange_is_supported(self):
        self.payload, self.sealed = object_fixture(kind="deployed_deterministic")
        self.assertEqual(
            self.run_gate()["production_baseline_kind"], "deployed_deterministic"
        )

    def test_head_source_binding_supported(self):
        self.payload, self.sealed = object_fixture(family="heads")
        self.assertEqual(self.run_gate()["row_counts_by_split"]["future_2"], 1)

    def test_laya_test_arm_is_not_actual_production_baseline(self):
        self.payload["no_change"]["kind"] = "laya"
        self.must_block()

    def test_missing_selected_weight_denied(self):
        self.payload["no_change"]["weights_digest"] = None
        self.must_block()

    def test_source_revoked_or_missing_denied(self):
        self.payload["dataset"]["source_record_digests"].remove(
            self.payload["rows"][0]["decision_record_digest"]
        )
        self.must_block()

    def test_nonterminal_outcome_denied(self):
        self.payload["rows"][1]["terminality"] = "Pending"
        self.must_block()

    def test_outcome_before_observation_denied(self):
        row = self.payload["rows"][1]
        row["terminal_at_unix_micros"] = row["observed_at_unix_micros"] - 1
        self.must_block()

    def test_future_before_baseline_denied(self):
        row = self.payload["rows"][3]
        row["observed_at_unix_micros"] = FREEZE - 1_000_000
        self.sealed[3]["observed_at_ms"] = (FREEZE - 1_000_000) // 1000
        self.must_block()

    def test_future_windows_reversed_denied(self):
        a, b = self.payload["rows"][3], self.payload["rows"][4]
        for k in ("observed_at_unix_micros", "terminal_at_unix_micros"):
            a[k], b[k] = b[k], a[k]
        self.sealed[3]["observed_at_ms"] = a["observed_at_unix_micros"] // 1000
        self.sealed[4]["observed_at_ms"] = b["observed_at_unix_micros"] // 1000
        self.must_block()

    def test_cross_split_episode_leak_denied(self):
        self.payload["rows"][3]["episode_id"] = "episode-0"
        self.must_block()

    def test_delayed_future_outcome_cannot_overlap_next_window(self):
        row = self.payload["rows"][3]
        row["terminal_at_unix_micros"] = (
            self.payload["rows"][4]["observed_at_unix_micros"] + 1
        )
        self.must_block()

    def test_delayed_holdout_outcome_cannot_overlap_future_window(self):
        row = self.payload["rows"][2]
        row["terminal_at_unix_micros"] = (
            self.payload["rows"][3]["observed_at_unix_micros"] + 1
        )
        self.must_block()

    def test_source_group_leak_denied(self):
        self.payload["rows"][3]["source_group"] = "group-0"
        self.sealed[3]["source_group"] = "group-0"
        self.must_block()

    def test_sealed_input_changed_after_attested_join_denied(self):
        self.sealed[2]["state"] = "forged-raw-input"
        self.must_block()

    def test_identical_input_reappearing_in_future_window_is_denied(self):
        original = self.sealed[0]
        future = self.sealed[4]
        for key in ("state", "question", "option_order", "language", "domain"):
            future[key] = copy.deepcopy(original[key])
        self.payload["rows"][4]["observation_sha256"] = observation_digest(
            future, "decisions"
        )
        self.must_block()

    def test_sealed_gold_modified_after_independent_signatures_denied(self):
        trust_digest = self.build()
        edited = [dict(row) for row in self.sealed]
        edited[2]["gold"] = "b"
        self.paths["sealed.jsonl"].write_text(
            "".join(json.dumps(row) + "\n" for row in edited)
        )
        with self.assertRaises(InvalidCohort):
            verify(
                self.paths["cohort.json"],
                self.paths["sealed.jsonl"],
                self.paths["trust.json"],
                trust_digest,
            )

    def test_millisecond_microsecond_confusion_denied(self):
        self.sealed[3]["observed_at_ms"] += 1000
        self.must_block()

    def test_duplicate_row_or_event_denied(self):
        self.payload["rows"][4]["terminal_outcome_record_digest"] = self.payload[
            "rows"
        ][3]["terminal_outcome_record_digest"]
        self.must_block()

    def test_trial_data_cannot_control_independent_signer_keys(self):
        self.trust["roles"]["evaluator"]["controller_id"] = "controller-ledger_owner"
        self.must_block()

    def test_trust_pin_cannot_be_bypassed(self):
        digest = self.build()
        self.paths["trust.json"].write_text(self.paths["trust.json"].read_text() + " ")
        with self.assertRaises(InvalidCohort):
            verify(
                self.paths["cohort.json"],
                self.paths["sealed.jsonl"],
                self.paths["trust.json"],
                digest,
            )

    def test_bad_signature_denied_after_repacking(self):
        digest = self.build()
        obj = json.loads(self.paths["cohort.json"].read_text())
        obj["attestations"]["observer"]["signature_ed25519_hex"] = "0" * 128
        self.paths["cohort.json"].write_text(json.dumps(obj))
        with self.assertRaises(InvalidCohort):
            verify(
                self.paths["cohort.json"],
                self.paths["sealed.jsonl"],
                self.paths["trust.json"],
                digest,
            )

    def test_unsafe_self_claimed_future_time_denied(self):
        # Even a newly signed report cannot claim future_2 outcomes at time of revalidation.
        self.payload["source_current_revalidated_at_unix_micros"] = FREEZE + 120_000_000
        self.must_block()

    def test_duplicate_json_fields_and_overflow_denied(self):
        digest = self.build()
        self.paths["cohort.json"].write_text('{"schema":"a","schema":"b"}')
        with self.assertRaises(InvalidCohort):
            verify(
                self.paths["cohort.json"],
                self.paths["sealed.jsonl"],
                self.paths["trust.json"],
                digest,
            )
        self.paths["cohort.json"].write_text('{"schema":1e999}')
        with self.assertRaises(InvalidCohort):
            verify(
                self.paths["cohort.json"],
                self.paths["sealed.jsonl"],
                self.paths["trust.json"],
                digest,
            )


if __name__ == "__main__":
    unittest.main()
