"""Unattested observation cannot silently become fixed-identity qualification."""

import json
from pathlib import Path
import tempfile
import unittest

from observed_live import (MODEL_ALIAS, identity_contract, observed_costs,
    require_accounting, response_model_observations, transport_mode)
from representative_audit import audit_actual


class ObservedLiveTests(unittest.TestCase):
    def test_missing_identity_never_downgrades_strict_live(self):
        partial = {"model": MODEL_ALIAS}
        with self.assertRaisesRegex(ValueError, "exact provider/model identity"):
            identity_contract("live", partial, "http://127.0.0.1:18081/v1")
        observed = identity_contract("observed-live", partial, "http://127.0.0.1:18081/v1")
        self.assertEqual(observed["status"], "unattested")
        self.assertFalse(observed["strict_live_qualification_requested"])
        self.assertFalse(observed["automatic_identity_downgrade"])
        self.assertFalse(observed["model_identity_equality_established"])
        for key in ("expected_response_model", "provider_revision", "model_sha256", "identity_evidence_sha256"):
            self.assertIsNone(observed[key])
        self.assertEqual(transport_mode("observed-live"), "live")
        with self.assertRaises(ValueError):
            identity_contract("automatic", {}, "http://127.0.0.1:18081/v1")

    def test_strict_live_still_requires_and_preserves_fixed_evidence(self):
        evidence = {"schema":"hepta.model-identity.v1", "model":MODEL_ALIAS,
            "response_model":"reported-fixture", "provider_revision":"fixture-deployment",
            "model_sha256":"a" * 64, "evidence_sha256":"b" * 64}
        fixed = identity_contract("live", evidence, "http://127.0.0.1:18081/v1", "c" * 64)
        self.assertTrue(fixed["strict_live_qualification_requested"])
        self.assertEqual(fixed["expected_response_model"], evidence["response_model"])
        self.assertEqual(fixed["model_sha256"], evidence["model_sha256"])
        with self.assertRaisesRegex(ValueError, "different requested model alias"):
            identity_contract("observed-live", {"model":"another-model"}, "http://127.0.0.1:18081/v1")

    def test_unknown_usage_is_not_zero_or_a_fabricated_capability_failure(self):
        self.assertEqual(require_accounting("observed-live", False), "partial_unknown")
        for mode in ("live", "replay"):
            with self.assertRaisesRegex(ValueError, "accounting is incomplete"):
                require_accounting(mode, False)
        rows = [self.row(True, 100, {"input_tokens":10,"output_tokens":2,"total_tokens":12}),
                self.row(False, 500, {"input_tokens":20,"output_tokens":3,"total_tokens":23})]
        cost = observed_costs(rows)["by_case_and_lane"][0]
        self.assertEqual(cost["all_attempt_wall_ms_per_observed_success"], 600)
        self.assertEqual(cost["exact_tokens_per_observed_success"]["total_tokens"], 35)
        self.assertEqual(cost["unsuccessful_tasks"], 1)
        incomplete = self.row(False, 50, {"input_tokens":5,"output_tokens":1,"total_tokens":6})
        incomplete["model_accounting"].update(complete=False, exact_usage_total=None, unknown_usage_attempts=1)
        rows.append(incomplete)
        cost = observed_costs(rows)["by_case_and_lane"][0]
        self.assertEqual(cost["all_attempt_wall_ms_per_observed_success"], 650)
        self.assertEqual(cost["known_usage_subtotal"]["total_tokens"], 41)
        self.assertIsNone(cost["exact_usage_total"])
        self.assertIsNone(cost["exact_tokens_per_observed_success"])
        self.assertIsNone(cost["whole_system_cpu_seconds"])
        self.assertIsNone(cost["monetary_cost"])
        self.assertIsNone(observed_costs([incomplete])["by_case_and_lane"][0]["all_attempt_wall_ms_per_observed_success"])

    @staticmethod
    def row(passed, wall, usage):
        return {"case":"edit", "lane":"native", "repeat":0, "status":"passed" if passed else "failed",
            "capability_passed":passed, "attempt_wall_ms":wall,
            "model_accounting":{"complete":True,"known_usage_subtotal":usage,"exact_usage_total":usage,
                "unknown_usage_attempts":0,"attempts":[{"attempt":1,"response_id":"fixture-response",
                    "response_model":None,"usage_state":"fixture"}]}}

    def test_response_model_observations_retain_unknown_fields(self):
        row = self.row(True, 1, {"input_tokens":1,"output_tokens":1,"total_tokens":2})
        observations = response_model_observations([row])
        self.assertEqual(len(observations), 1)
        self.assertIsNone(observations[0]["reported_model"])
        self.assertIsNone(observations[0]["response_status"])

    def test_unattested_mode_keeps_exact_proposal_feedback_and_admission_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            model.mkdir()
            sessions = root / "sessions/original"
            sessions.mkdir(parents=True)
            call = {"type":"function_call","call_id":"original-call","name":"hepta_mcp_lookup",
                "arguments":json.dumps({"package":"hepta-qualification"})}
            feedback = {"type":"function_call_output","call_id":"original-call","output":json.dumps({
                "exit_code":0,"stderr":"","stdout":json.dumps({"result":{"isError":False,"content":[{
                    "type":"text","text":json.dumps({"version":"1.0.0","source":"fixture"})}]}})})}
            for index, (request, response) in enumerate([
                ({"input":[]}, {"model":"observed-provider-A","output":[call],"usage":None}),
                ({"input":[call,feedback]}, {"model":None,"output":[{"type":"message","role":"assistant",
                    "content":[{"type":"output_text","text":"HEPTA_REPRESENTATIVE_OK"}]}],"usage":None}),
            ]):
                (model / f"model-{index:02}.request.json").write_text(json.dumps(request))
                (model / f"model-{index:02}.response.sse").write_text("data: " + json.dumps({"type":"response.completed", "response":response}) + "\n\n")
            admitted = {"call":{key:call[key] for key in ("call_id","name","arguments")}}
            path = sessions / "tool-original.json"
            path.write_text(json.dumps(admitted))
            result = audit_actual(root, "mcp_readonly", "observed-live")
            self.assertEqual(result["provider_models"], ["observed-provider-A", None])
            self.assertEqual(result["actual_usage"], [None, None])
            self.assertFalse(result["strict_live_identity_audit_passed"])
            self.assertFalse(result["usage_is_synthetic"])
            with self.assertRaisesRegex(ValueError, "provider identity"):
                audit_actual(root, "mcp_readonly", "live", "observed-provider-A")
            admitted["call"]["arguments"] = json.dumps({"package":"substituted"})
            path.write_text(json.dumps(admitted))
            with self.assertRaisesRegex(ValueError, "admitted payload"):
                audit_actual(root, "mcp_readonly", "observed-live")


if __name__ == "__main__":
    unittest.main()
