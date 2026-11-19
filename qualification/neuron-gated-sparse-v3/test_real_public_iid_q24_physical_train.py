"""One-tick real-public Q24 task training ABI tests using explicit synthetic inputs.

These tests prove Tensor file/shape/optimization mechanics, NOT actual
pretrained-Encoder or live selected deployed Cell provenance.
"""
from __future__ import annotations

from argparse import Namespace
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from real_public_iid_q24_physical_train import Refused, train, validate_fit
from near_matched_byte_budget import BYTE_CAPS, choose


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(obj):
    return (json.dumps(obj, indent=2, sort_keys=True, allow_nan=False,
                       ensure_ascii=False)+"\n").encode()


def stub_inputs():
    s=h("synthetic-only-Q24-snapshot")
    rows=[]
    for i in range(64):
        rows.append({
            "case_id": f"fixture:fit:{i}",
            "source_text_sha256": h(f"mock text {i}"),
            "feature_q24": [(((i+j)%17)-8)*(1<<21) for j in range(32)],
            "split": "fit", "train_label": i%4,
        })
    source={
        "schema": "hepta.neuron.real-public-q24-iid-fit-inputs.v1",
        "fit_labels_only": True, "holdout_labels_exposed": False,
        "authority": "DENY_ALL", "production_qualification": False,
        "ndu_eligible": False, "feature_dimension": 32,
        "temporal_observation_kind": "UNORDERED_IID_ONE_TICK_PER_CASE_NOT_FUTURE_OR_RETENTION",
        "input_feature_snapshot_sha256": s,
        "rows": rows,
    }
    plan={
        "schema": "hepta.neuron.real-public-q24-iid-predeclared-plan.v1",
        "authority":"DENY_ALL", "decision": "NO_MODEL_PROMOTION",
        "training_execution_performed": False,
        "selected_original_v1_no_change_a0_verified": False,
        "independent_heldout_labels_joined": False,
        "longitudinal_or_future_task_efficacy_claim_permitted": False,
        "same_frozen_feature_source": s,
        "fit_case_count": 64, "heldout_case_count": 32,
        "candidate_mechanisms":["v2","v3","ssm","min_gru"],
        "candidate_private_serialized_byte_budgets": list(BYTE_CAPS),
        "binary_tasks": [
            {"class_id": i, "positive_intent": name,
             "label_rule": "ONE_VS_REST_FROM_FIT_ONLY"}
            for i,name in enumerate((
                "card_arrival","cash_withdrawal_not_recognised",
                "exchange_rate","lost_or_stolen_phone"))
        ],
    }
    return source,plan


@unittest.skipUnless(
    os.environ.get("HEPTA_NEURON_PHYSICAL_TESTS") == "1",
    "real physical Torch+safetensors unit training belongs in pinned CPU job only",
)
class PublicQ24PhysicalIIDTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        fit,plan=stub_inputs()
        cls.fit=cls.root/"fit.json"
        cls.plan=cls.root/"plan.json"
        cls.fit.write_bytes(canonical(fit))
        cls.plan.write_bytes(canonical(plan))
        cls.out=cls.root/"learned"
        cls.kw=dict(
            fit=cls.fit, fit_sha256=hashlib.sha256(cls.fit.read_bytes()).hexdigest(),
            plan=cls.plan, plan_sha256=hashlib.sha256(cls.plan.read_bytes()).hexdigest(),
            output=cls.out, epochs=1, seed=20261016, research_only=True,
        )
        cls.receipt=train(Namespace(**cls.kw))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_full_physical_32_cell_census_and_q24_sha(self):
        from safetensors.torch import load_file
        report=self.receipt
        self.assertEqual(report["physical_models_count"],32)
        self.assertEqual(len(report["models"]),32)
        self.assertEqual(report["task_count"],4)
        self.assertEqual(report["optimizer_steps_each"],4)
        self.assertEqual(report["examples_exposed_per_model"],64)
        self.assertTrue(report["iid_state_reset_per_case"])
        self.assertFalse(report["heldout_labels_exposed_to_trainer"])
        self.assertFalse(report["original_selected_v1_a0_verified"])
        self.assertFalse(report["production_qualification"])
        self.assertEqual(report["decision"],"NO_MODEL_PROMOTION")
        for m in report["models"]:
            p=self.out/m["source_weight_file"]
            raw=p.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),m["weight_sha256"])
            self.assertEqual(len(raw),m["physical_bytes"])
            exact=choose(m["arm"],m["physical_byte_ceiling"])
            self.assertEqual(exact["physical_safetensors_bytes"],m["physical_bytes"])
            self.assertEqual(exact["private_parameter_count"],m["realized_private_parameters"])
            self.assertEqual(
                sum(v.numel() for v in load_file(str(p)).values()),
                m["realized_private_parameters"])

    def test_four_distinct_one_vs_rest_tasks_complete(self):
        self.assertEqual(
            {(r["task_id"],r["physical_byte_ceiling"],r["arm"])
             for r in self.receipt["models"]},
            {(task,cap,arm) for task in range(4)
             for cap in BYTE_CAPS for arm in ("v2","v3","ssm","min_gru")})
        self.assertEqual(len({r["weight_sha256"] for r in self.receipt["models"]}),32)

    def test_train_only_data_and_label_balance_accepted(self):
        fit,plan=stub_inputs()
        rows,sha=validate_fit(fit,plan)
        self.assertEqual(len(rows),64)
        self.assertEqual({r["train_label"] for r in rows},{0,1,2,3})
        self.assertEqual(sha,h("synthetic-only-Q24-snapshot"))

    def test_heldout_row_forbidden_in_fit(self):
        fit,plan=stub_inputs()
        fit["rows"][0]["split"]="heldout"
        with self.assertRaises(Refused):
            validate_fit(fit,plan)

    def test_duplicate_public_feature_refused(self):
        fit,plan=stub_inputs()
        fit["rows"][3]["case_id"]=fit["rows"][2]["case_id"]
        with self.assertRaises(Refused):
            validate_fit(fit,plan)

    def test_boolean_label_not_treated_as_integer(self):
        fit,plan=stub_inputs()
        fit["rows"][0]["train_label"]=True
        with self.assertRaises(Refused):
            validate_fit(fit,plan)

    def test_wrong_frozen_source_digest_denied(self):
        fit,plan=stub_inputs()
        plan["same_frozen_feature_source"]=h("wrong source")
        with self.assertRaises(Refused):
            validate_fit(fit,plan)

    def test_forged_production_or_future_denied(self):
        for key in (
            "selected_original_v1_no_change_a0_verified",
            "longitudinal_or_future_task_efficacy_claim_permitted",
            "training_execution_performed",
        ):
            fit,plan=stub_inputs()
            plan[key]=True
            with self.assertRaises(Refused):
                validate_fit(fit,plan)

    def test_fake_event_time_and_extra_label_denied(self):
        fit,plan=stub_inputs()
        fit["rows"][1]["event_time_utc"]="2026-10-16T00:00:00Z"
        with self.assertRaises(Refused):
            validate_fit(fit,plan)

    def test_false_retrain_overwrite_denied(self):
        with self.assertRaises(FileExistsError):
            train(Namespace(**dict(self.kw,epochs=1)))

    def test_require_explicit_research_only_flag(self):
        with self.assertRaises(Refused):
            train(Namespace(**dict(self.kw,research_only=False)))


if __name__ == "__main__":
    unittest.main()
