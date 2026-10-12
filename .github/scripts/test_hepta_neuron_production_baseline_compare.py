"""Pure synthetic adversarial fixtures; NO real model/host evidence or signing API."""

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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
from test_hepta_neuron_model_trials import (
    fixture as trial_fixture,
    packet as trial_packet,
)
from hepta_neuron_real_cohort_preflight import (
    ATTEST_SCHEMA,
    COHORT_SCHEMA,
    DOMAIN,
    ROLES,
    SPLITS,
    TRUST_SCHEMA,
    InvalidCohort,
    canonical,
    observation_digest,
    sha_bytes,
)
from hepta_neuron_model_trials import (
    ARMS,
    InvalidTrial,
    blind_rows,
    canonical_jsonl,
    sha_file,
    write_new,
)
from hepta_neuron_production_baseline_compare import (
    SCHEMA,
    SIGNATURE_DOMAIN,
    compare_to_production,
)

FREEZE = 1_757_000_000_000_000
TIMES = {
    "train": FREEZE - 700_000_000,
    "calibration": FREEZE - 500_000_000,
    "holdout": FREEZE - 300_000_000,
    "future_1": FREEZE + 200_000_000,
    "future_2": FREEZE + 400_000_000,
}


def dig(s):
    return hashlib.sha256(s.encode()).hexdigest()


class ProductionBaselinePairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.family = "decisions"
        self.build_fixture()

    def build_fixture(self, family="decisions", deterministic=False):
        self.family = family
        self.manifest, self.rows, self.sealed, self.manifest_path = trial_fixture(
            self.root, family
        )
        for i, row in enumerate(self.rows):
            t = TIMES[row["split"]] + i * 1000
            row["observed_at_ms"] = t // 1000
            if family != "heads":
                row["state"] = f"fixture-only-{i}"
            else:
                row["features_q24"][0] = i + 1
        self.sealed.write_text(
            "".join(json.dumps(x, sort_keys=True) + "\n" for x in self.rows)
        )
        self.manifest["dataset_sha256"] = sha_file(self.sealed)
        self.manifest["blind_dataset_sha256"] = sha_bytes(
            canonical_jsonl(blind_rows(self.rows, family))
        )
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.keys = {role: Ed25519PrivateKey.generate() for role in ROLES}
        self.trust = {
            "schema": TRUST_SCHEMA,
            "roles": {
                role: {
                    "key_id": f"key-{role}",
                    "controller_id": f"controller-{role}",
                    "principal_id": f"principal-{role}",
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
        self.trust_path = self.root / "trust.json"
        self.trust_path.write_text(json.dumps(self.trust))
        self.trust_hash = sha_file(self.trust_path)
        members = []
        joined = []
        for i, row in enumerate(self.rows):
            t = row["observed_at_ms"] * 1000
            decision, outcome = dig(f"decision-{i}"), dig(f"outcome-{i}")
            members.extend((decision, outcome))
            joined.append(
                {
                    "id": row["id"],
                    "episode_id": f"episode-{i}",
                    "split": row["split"],
                    "source_group": row["source_group"],
                    "decision_record_digest": decision,
                    "terminal_outcome_record_digest": outcome,
                    "observation_sha256": observation_digest(row, family),
                    "observed_at_unix_micros": t,
                    "terminal_at_unix_micros": t + 10_000_000,
                    "terminality": "Terminal",
                }
            )
        baseline = {
            "kind": "deployed_deterministic" if deterministic else "deployed_learned",
            "scope_digest": dig("scope"),
            "objective_digest": dig("objective"),
            "generation": 10,
            "policy_digest": dig("policy"),
            "route_digest": dig("route"),
            "checkpoint_digest": dig("checkpoint"),
            "runtime_receipt_digest": dig("runtime"),
            "artifact_load_receipt_digest": dig("artifact"),
            "source_use_receipt_digest": dig("source"),
            "frozen_at_unix_micros": FREEZE,
            "model_manifest_digest": None if deterministic else dig("manifest"),
            "weights_digest": None if deterministic else dig("weights"),
            "code_digest": dig("code") if deterministic else None,
        }
        self.cohort_payload = {
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
                "eligible_frontier": 20,
                "outcome_watermark": 20,
                "source_record_digests": sorted(members),
            },
            "no_change": baseline,
            "frozen_plan_digest": dig("plan"),
            "sealed_dataset_sha256": sha_file(self.sealed),
            "source_current_revalidated_at_unix_micros": FREEZE + 600_000_000,
            "rows": joined,
        }
        self.cohort_path = self.root / "cohort.json"
        self.build_cohort()
        self.production_body = {
            "cohort_sha256": sha_file(self.cohort_path),
            "trial_manifest_sha256": sha_file(self.manifest_path),
            "dataset_sha256": self.manifest["dataset_sha256"],
            "blind_dataset_sha256": self.manifest["blind_dataset_sha256"],
            "source_dataset_digest": self.cohort_payload["dataset"]["dataset_digest"],
            "frozen_plan_digest": self.cohort_payload["frozen_plan_digest"],
            "no_change": copy.deepcopy(self.cohort_payload["no_change"]),
            "revalidated_at_unix_micros": self.cohort_payload[
                "source_current_revalidated_at_unix_micros"
            ],
            "observations": [],
        }
        for j in self.cohort_payload["rows"]:
            if j["split"] == "train":
                continue
            idx = self.rows.index(next(r for r in self.rows if r["id"] == j["id"]))
            x = {
                "id": j["id"],
                "split": j["split"],
                "decision_record_digest": j["decision_record_digest"],
                "observation_sha256": j["observation_sha256"],
                "generation": 10,
                "production_runtime_receipt_digest": dig(f"runtime-{idx}"),
                "decision_at_unix_micros": j["observed_at_unix_micros"] + 1000,
            }
            if family == "heads":
                x.update({"drive_q24": [0] * 256, "prediction_q24": [0] * 256})
            else:
                x.update({"disposition": "selected", "selected_option": "yes"})
            self.production_body["observations"].append(x)
        self.baseline_path = self.root / "actual-selected-baseline.json"
        self.build_baseline()
        self.arms = {}
        for arm in ARMS[family]:
            path = self.root / f"{arm}.json"
            if path.exists():
                path.unlink()
            write_new(
                path,
                trial_packet(self.manifest, self.rows, arm, damaged=arm == "typed"),
            )
            self.arms[arm] = path

    def build_cohort(self):
        h = sha_bytes(canonical(self.cohort_payload))
        records = {}
        for role in ROLES:
            s = {
                "schema": ATTEST_SCHEMA,
                "role": role,
                "key_id": "key-" + role,
                "body_sha256": h,
                "signed_at_unix_micros": FREEZE + 700_000_000,
            }
            s["signature_ed25519_hex"] = (
                self.keys[role].sign(DOMAIN + canonical(s)).hex()
            )
            records[role] = s
        self.cohort_path.write_text(
            json.dumps(
                {
                    "schema": COHORT_SCHEMA,
                    "payload": self.cohort_payload,
                    "attestations": records,
                }
            )
        )

    def build_baseline(self):
        signed_at = FREEZE + 710_000_000
        signed = {
            "schema": SCHEMA,
            "role": "baseline_owner",
            "key_id": "key-baseline_owner",
            "signed_at_unix_micros": signed_at,
            "body": self.production_body,
        }
        sig = (
            self.keys["baseline_owner"].sign(SIGNATURE_DOMAIN + canonical(signed)).hex()
        )
        self.baseline_path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "body": self.production_body,
                    "owner_signature": {
                        "role": "baseline_owner",
                        "key_id": "key-baseline_owner",
                        "signed_at_unix_micros": signed_at,
                        "signature_ed25519_hex": sig,
                    },
                }
            )
        )

    def check(self):
        return compare_to_production(
            self.cohort_path,
            self.sealed,
            self.trust_path,
            self.trust_hash,
            self.manifest_path,
            self.baseline_path,
            self.arms,
        )

    def blocked(self):
        with self.assertRaises((InvalidCohort, InvalidTrial)):
            self.check()

    def test_actual_production_baseline_is_distinct_from_laya_control(self):
        v = self.check()
        self.assertEqual(v["family"], "decisions")
        self.assertIn("laya", v["production_baseline_paired_proxies"])
        self.assertEqual(v["production_no_change"]["kind"], "deployed_learned")
        self.assertFalse(v["ndu_net_gain_verified"])
        self.assertFalse(v["production_promotion_authorized"])
        self.assertFalse(v["production_baseline_executed_by_this_process"])
        self.assertIsNone(
            v["production_no_change"]["measured"]["future_1"]["brier_multiclass"]
        )
        self.assertNotIn("fixture-only", json.dumps(v))

    def test_deterministic_baseline_measures_coverage_not_fake_brier(self):
        self.build_fixture("decisions", deterministic=True)
        v = self.check()
        self.assertEqual(v["production_no_change"]["kind"], "deployed_deterministic")
        self.assertIsNone(v["production_no_change"]["measured"]["future_2"]["ece10"])

    def test_head_baseline_paired_mse_is_not_ndu_gain(self):
        self.build_fixture("heads")
        v = self.check()
        self.assertIn("mse", v["production_no_change"]["measured"]["future_1"])
        self.assertFalse(v["selection_authorized"])

    def test_multilingual_baseline_pairs_all_languages(self):
        self.build_fixture("multilingual")
        v = self.check()
        self.assertEqual(v["family"], "multilingual")
        self.assertEqual(v["production_no_change"]["measured"]["future_2"]["count"], 3)

    def test_valid_abstain_excluded_from_paired_accuracy(self):
        row = self.production_body["observations"][-1]
        row["disposition"] = "abstained"
        row["selected_option"] = None
        self.build_baseline()
        v = self.check()
        self.assertEqual(
            v["production_baseline_paired_proxies"]["typed"]["future_2"][
                "baseline_abstentions_or_slow_path_excluded"
            ],
            1,
        )

    def test_false_baseline_choice_denied(self):
        self.production_body["observations"][0]["selected_option"] = "invented"
        self.build_baseline()
        self.blocked()

    def test_wrong_decision_event_denied_even_with_valid_signature(self):
        self.production_body["observations"][0]["decision_record_digest"] = dig(
            "unrelated"
        )
        self.build_baseline()
        self.blocked()

    def test_runtime_receipt_and_generation_required(self):
        self.production_body["observations"][0]["production_runtime_receipt_digest"] = (
            "0" * 64
        )
        self.build_baseline()
        self.blocked()
        self.production_body["observations"][0]["production_runtime_receipt_digest"] = (
            dig("fix")
        )
        self.production_body["observations"][0]["generation"] = 11
        self.build_baseline()
        self.blocked()

    def test_decision_after_terminal_outcome_denied(self):
        j = self.cohort_payload["rows"][1]
        self.production_body["observations"][0]["decision_at_unix_micros"] = (
            j["terminal_at_unix_micros"] + 1
        )
        self.build_baseline()
        self.blocked()

    def test_incomplete_or_duplicate_baseline_events_denied(self):
        self.production_body["observations"].pop()
        self.build_baseline()
        self.blocked()
        self.production_body["observations"].append(
            copy.deepcopy(self.production_body["observations"][0])
        )
        self.build_baseline()
        self.blocked()

    def test_changed_selected_nochange_tuple_denied(self):
        self.production_body["no_change"]["policy_digest"] = dig("different")
        self.build_baseline()
        self.blocked()

    def test_swapped_training_dataset_or_manifest_denied(self):
        self.production_body["trial_manifest_sha256"] = dig("different")
        self.build_baseline()
        self.blocked()

    def test_missing_or_unmatched_laya_arm_denied(self):
        self.arms.pop("typed")
        self.blocked()

    def test_bad_actor_signature_denied(self):
        self.build_baseline()
        p = json.loads(self.baseline_path.read_text())
        p["owner_signature"]["signature_ed25519_hex"] = "0" * 128
        self.baseline_path.write_text(json.dumps(p))
        self.blocked()

    def test_stale_or_wrong_signer_denied(self):
        self.build_baseline()
        p = json.loads(self.baseline_path.read_text())
        p["owner_signature"]["role"] = "evaluator"
        self.baseline_path.write_text(json.dumps(p))
        self.blocked()

    def test_label_and_input_mutation_denied(self):
        rows = [dict(r) for r in self.rows]
        rows[-1]["gold"] = "no"
        self.sealed.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.blocked()

    def test_symlinked_baseline_denied(self):
        original = self.root / "actual-file.json"
        original.write_bytes(self.baseline_path.read_bytes())
        self.baseline_path.unlink()
        self.baseline_path.symlink_to(original)
        self.blocked()

    def test_source_group_uncertainty_is_descriptive_not_selection(self):
        report = self.check()
        for arm in ARMS[self.family]:
            for window in ("holdout", "future_1", "future_2"):
                row = report["production_baseline_paired_proxies"][arm][window]
                confidence = row["paired_uncertainty"]
                self.assertEqual(confidence["method"], "source_group_cluster_bootstrap_percentile_v1")
                self.assertLess(confidence["independent_source_groups"], 8)
                self.assertIsNone(confidence["lower"])
                self.assertIsNone(confidence["upper"])
                self.assertIs(confidence["significance_or_promotion_claim"], False)
        self.assertFalse(report["ndu_net_gain_verified"])
        self.assertFalse(report["production_promotion_authorized"])

    def test_head_source_group_uncertainty_preserves_mse_direction(self):
        self.build_fixture("heads")
        report = self.check()
        row = report["production_baseline_paired_proxies"]["swiglu"]["future_1"]
        confidence = row["paired_uncertainty"]
        self.assertEqual(confidence["statistic"], "candidate_minus_production_no_change_mse")
        self.assertEqual(confidence["benefit_when"], "negative")
        self.assertAlmostEqual(confidence["point_estimate"], row["paired_mean_mse_delta"])

    def test_baseline_window_proxies_do_not_grant_promotion(self):
        for item in self.production_body["observations"]:
            item["selected_option"] = "yes"
        self.build_baseline()
        report = self.check()
        self.assertIs(report["selection_authorized"], False)
        self.assertIs(report["production_promotion_authorized"], False)


if __name__ == "__main__":
    unittest.main()
