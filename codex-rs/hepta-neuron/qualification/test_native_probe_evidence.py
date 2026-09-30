"""No-model diagnostic regressions; these fixtures are not OS effect receipts."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from native_probe_evidence import evaluate_native_receipt, read_native_receipt

SOURCE = {"commit": "1" * 40, "tree": "2" * 40, "repository_root": "/not-production"}


def packet_fixture():
    one = lambda size, index: [int(i == index) for i in range(size)]
    return {"schema": "hepta.model-native-probe-input.v2", "requestId": "probe.one",
            "replySha256": "a" * 64, "projectionSha256": "b" * 64,
            "headManifestSha256": "c" * 64, "baseSnapshotDigest": "d" * 64, "modelSupported": True,
            "probabilities": {"action": one(6, 2), "target": one(4, 3),
                "disposition": one(6, 0), "postcondition": one(6, 2), "ood": one(2, 0)},
            "targets": [{"referenceId": f"reference.{i}", "generation": 1, "text": f"nonsecret-{i}"} for i in range(4)]}


def receipt_fixture(packet):
    selected = 3
    choice = {"status": "selected", "requestId": packet["requestId"],
        "replySha256": packet["replySha256"], "referenceId": packet["targets"][selected]["referenceId"],
        "text": packet["targets"][selected]["text"], "targetIndex": selected,
        "confidence": 1, "ood": 0, "modelSupported": packet["modelSupported"], "authorityGranted": False}
    return {"schema": "hepta.native-x11-clipboard-qualification.v1",
        "source": {"commit": SOURCE["commit"], "tree": SOURCE["tree"], "dirty": False},
        **{key: "e" * 64 for key in ("frameSha256", "sourceActionDigest", "outcomeDigest", "executableSha256", "xvfbSha256")},
        "readbackSha256": hashlib.sha256(choice["text"].encode()).hexdigest(),
        "elapsedMicros": 1, "finalUseCalls": 1,
        **{key: True for key in ("exactRetryReused", "changedIntentRejected", "observationAfterClose",
            "writerCleanupObserved", "observerCleanupObserved", "changedPrincipalRejected",
            "realOsClipboard", "isolatedDisplay", "backendAndAuthorityAreFixtures")},
        **{key: False for key in ("tcpListenerEnabled", "independentPrincipalObservation",
            "durableCrossProcessRecovery", "productionActivation", "operatorAcceptance")},
        "modelChoice": choice}


class NativeProbeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "receipt.json"
        self.packet = packet_fixture()
        self.receipt = receipt_fixture(self.packet)

    def write(self, value=None):
        self.path.write_text(json.dumps(self.receipt if value is None else value), encoding="utf-8")

    def evaluate(self, code=0, timed_out=False, ood=False, target=3):
        return evaluate_native_receipt(self.path, exit_code=code, timed_out=timed_out,
            packet=self.packet, source=SOURCE, expected_target=target, expected_ood=ood)

    def abstain(self):
        self.packet["probabilities"]["ood"] = [0, 1]
        self.receipt = {"schema": "hepta.native-model-abstention.v1",
            "source": self.receipt["source"], "productionActivation": False, "externalEffect": False,
            "modelChoice": {"status": "abstained", "requestId": self.packet["requestId"],
                "replySha256": self.packet["replySha256"], "modelSupported": self.packet["modelSupported"], "authorityGranted": False,
                "predicted": {"action": 2, "target": 3, "disposition": 0, "postcondition": 2, "ood": 1},
                "confidence": 1, "ood": 1}}

    def test_complete_bound_receipt_passes_without_granting_authority(self):
        self.write(); result = self.evaluate()
        self.assertTrue(result["task_passed"])
        self.assertIs(result["external_effect"], True)
        self.assertIsNone(result["evidence_error"])
        self.assertEqual(result["native_report_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertNotIn("text", result)

    def test_process_failure_after_observation_keeps_effect_but_fails_run(self):
        self.write()
        for code, timeout in [(1, False), (-9, True), (3, False)]:
            with self.subTest(code=code):
                result = self.evaluate(code=code, timed_out=timeout)
                self.assertIs(result["external_effect"], True)
                self.assertFalse(result["task_passed"])
                self.assertEqual(result["evidence_error"], "native_process_incomplete")

    def test_missing_receipt_is_unknown_for_every_exit(self):
        for code in [0, 1, 3, -9]:
            result = self.evaluate(code=code)
            self.assertIsNone(result["external_effect"]); self.assertFalse(result["task_passed"])

    def test_exit_three_is_not_an_abstention_proof(self):
        self.write({})
        result = self.evaluate(code=3, ood=True)
        self.assertFalse(result["task_passed"]); self.assertIsNone(result["external_effect"])

    def test_matching_ood_abstention_has_no_effect(self):
        self.abstain(); self.write(); result = self.evaluate(code=3, ood=True, target=-1)
        self.assertTrue(result["task_passed"]); self.assertIs(result["external_effect"], False)

    def test_abstention_on_supported_task_is_not_success(self):
        self.abstain(); self.write(); result = self.evaluate(code=3)
        self.assertFalse(result["task_passed"]); self.assertIs(result["external_effect"], False)

    def test_failure_after_bound_abstention_does_not_claim_success(self):
        self.abstain(); self.write(); result = self.evaluate(code=1, ood=True)
        self.assertFalse(result["task_passed"]); self.assertIs(result["external_effect"], False)

    def test_wrong_target_is_an_observed_effect_and_failed_task(self):
        self.write(); result = self.evaluate(target=0)
        self.assertIs(result["external_effect"], True); self.assertFalse(result["task_passed"])

    def test_ood_action_is_not_a_pass(self):
        self.write(); result = self.evaluate(ood=True, target=-1)
        self.assertIs(result["external_effect"], True); self.assertFalse(result["task_passed"])

    def test_source_request_reference_and_readback_substitutions_reject(self):
        changes = [("source", "commit", "f" * 40), ("source", "tree", "f" * 40),
            ("source", "dirty", 0), ("modelChoice", "requestId", "other"),
            ("modelChoice", "replySha256", "f" * 64), ("modelChoice", "referenceId", "other"),
            ("modelChoice", "text", "replaced"), ("modelChoice", "confidence", .5)]
        for owner, key, value in changes:
            with self.subTest(owner=owner, key=key):
                mutated = copy.deepcopy(self.receipt); mutated[owner][key] = value; self.write(mutated)
                result = self.evaluate(); self.assertFalse(result["task_passed"]); self.assertIsNone(result["external_effect"])
        self.receipt["readbackSha256"] = "f" * 64; self.write()
        self.assertIsNone(self.evaluate()["external_effect"])

    def test_bool_negative_and_noninteger_target_indices_reject(self):
        for index in [True, False, -1, 4, 3.0, "3"]:
            self.receipt["modelChoice"]["targetIndex"] = index; self.write()
            result = self.evaluate(); self.assertIsNone(result["external_effect"])

    def test_model_pointer_not_the_expected_label_is_checked(self):
        self.packet["probabilities"]["target"] = [1, 0, 0, 0]
        self.write(); result = self.evaluate()
        self.assertFalse(result["task_passed"]); self.assertIsNone(result["external_effect"])

    def test_numeric_boolean_flags_cannot_impersonate_scope(self):
        for key, value in [("realOsClipboard", 1), ("productionActivation", 0),
                           ("backendAndAuthorityAreFixtures", 1), ("operatorAcceptance", 0)]:
            mutated = copy.deepcopy(self.receipt); mutated[key] = value; self.write(mutated)
            self.assertIsNone(self.evaluate()["external_effect"])

    def test_lifecycle_failure_does_not_erase_observed_copy(self):
        for key, value in [("writerCleanupObserved", False), ("exactRetryReused", 1),
                           ("finalUseCalls", True), ("elapsedMicros", -1)]:
            mutated = copy.deepcopy(self.receipt); mutated[key] = value; self.write(mutated)
            result = self.evaluate(); self.assertFalse(result["task_passed"])
            self.assertIs(result["external_effect"], True)

    def test_abstention_must_match_recomputed_model_policy(self):
        self.abstain(); self.packet["probabilities"]["ood"] = [1, 0]; self.write()
        self.assertIsNone(self.evaluate(code=3, ood=True)["external_effect"])

    def test_abstention_predicted_booleans_are_not_indices(self):
        self.abstain(); self.receipt["modelChoice"]["predicted"]["disposition"] = False; self.write()
        self.assertIsNone(self.evaluate(code=3, ood=True)["external_effect"])

    def test_malformed_duplicate_nonfinite_oversized_and_deep_reports_fail_closed(self):
        for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'{}' + b' ' * 32768,
                    b'{', b'\xff', b'[]', b'[' * 2000 + b'0' + b']' * 2000]:
            self.path.write_bytes(raw)
            result = self.evaluate(); self.assertFalse(result["task_passed"]); self.assertIsNone(result["external_effect"])

    def test_symlinks_and_nonregular_files_reject_without_blocking(self):
        other = self.path.with_name("other.json"); other.write_text("{}")
        self.path.symlink_to(other)
        self.assertIsNone(self.evaluate()["external_effect"])
        self.path.unlink(); os.mkfifo(self.path)
        self.assertIsNone(self.evaluate()["external_effect"])

    def test_real_process_exit_without_receipt_remains_unknown(self):
        child = subprocess.run([sys.executable, "-c", "raise SystemExit(3)"], timeout=5)
        result = self.evaluate(code=child.returncode, ood=True)
        self.assertIsNone(result["external_effect"]); self.assertFalse(result["task_passed"])

    def test_real_process_observation_then_error_retains_truth(self):
        child = subprocess.run([sys.executable, "-c",
            "import sys;from pathlib import Path;Path(sys.argv[1]).write_text(sys.stdin.read());raise SystemExit(1)", str(self.path)],
            input=json.dumps(self.receipt), text=True, timeout=5)
        result = self.evaluate(code=child.returncode)
        self.assertIs(result["external_effect"], True); self.assertFalse(result["task_passed"])

    def test_js_policy_and_python_observation_reduction_agree(self):
        module = Path(__file__).resolve().parents[3] / "apps/hepta-native/qualification/model-decision.mjs"
        command = ["node", "--input-type=module", "-e",
            'import fs from "node:fs";const m=await import(process.argv[1]);console.log(JSON.stringify(m.clipboardChoiceFromModel(JSON.parse(fs.readFileSync(0,"utf8")),1)))', module.as_uri()]
        for ood_mass in [0, .05, .051, 1]:
            for confidence in [.94, .95, 1]:
                self.packet = packet_fixture()
                self.packet["probabilities"]["target"] = [1-confidence, 0, 0, confidence]
                self.packet["probabilities"]["ood"] = [1-ood_mass, ood_mass]
                reply = subprocess.run(command, input=json.dumps(self.packet), capture_output=True, text=True, check=True, timeout=5)
                choice = json.loads(reply.stdout)
                if choice["status"] == "abstained":
                    self.receipt = {"schema": "hepta.native-model-abstention.v1", "modelChoice": choice,
                        "source": {"commit": SOURCE["commit"], "tree": SOURCE["tree"], "dirty": False},
                        "productionActivation": False, "externalEffect": False}
                    code, ood = 3, True
                else:
                    self.receipt = receipt_fixture(self.packet); self.receipt["modelChoice"] = choice
                    code, ood = 0, False
                self.write(); self.assertTrue(self.evaluate(code=code, ood=ood)["task_passed"])

    def test_upstream_abstention_is_not_replaced_by_fixed_thresholds(self):
        self.abstain()
        self.packet["probabilities"]["ood"] = [1, 0]
        self.packet["modelSupported"] = False
        self.receipt["modelChoice"].update(modelSupported=False, ood=0)
        self.receipt["modelChoice"]["predicted"]["ood"] = 0
        self.write()
        result = self.evaluate(code=3, ood=True)
        self.assertTrue(result["task_passed"])
        self.assertIs(result["external_effect"], False)

    def test_observed_copy_after_support_denial_remains_an_effect_not_a_pass(self):
        self.packet["modelSupported"] = False
        self.receipt["modelChoice"]["modelSupported"] = False
        self.write()
        result = self.evaluate()
        self.assertIs(result["external_effect"], True)
        self.assertFalse(result["task_passed"])
        self.assertFalse(result["model_policy_respected"])
        self.assertEqual(result["evidence_error"], "native_policy_violation")

    def test_support_substitution_and_truthy_flags_cannot_pass_evidence(self):
        self.packet["modelSupported"] = False
        self.write()
        result = self.evaluate()
        self.assertIsNone(result["external_effect"])
        self.assertEqual(result["evidence_error"], "native_support_mismatch")
        for support in [0, 1, None, "true", [], {}]:
            with self.subTest(support=support):
                self.packet["modelSupported"] = support
                self.receipt["modelChoice"]["modelSupported"] = support
                self.write()
                self.assertFalse(self.evaluate()["task_passed"])
        self.packet.pop("modelSupported")
        self.write()
        self.assertFalse(self.evaluate()["task_passed"])

    def test_old_packet_schema_cannot_acquire_new_evaluation_semantics(self):
        self.packet["schema"] = "hepta.model-native-probe-input.v1"
        self.write()
        result = self.evaluate()
        self.assertFalse(result["task_passed"])
        self.assertEqual(result["evidence_error"], "packet_schema_mismatch")

    def test_model_support_veto_matches_real_javascript_consumer(self):
        module = Path(__file__).resolve().parents[3] / "apps/hepta-native/qualification/model-decision.mjs"
        command = ["node", "--input-type=module", "-e",
            'import fs from "node:fs";const m=await import(process.argv[1]);console.log(JSON.stringify(m.clipboardChoiceFromModel(JSON.parse(fs.readFileSync(0,"utf8")),1)))', module.as_uri()]
        for support in [False, True]:
            self.packet = packet_fixture()
            self.packet["modelSupported"] = support
            reply = subprocess.run(command, input=json.dumps(self.packet), capture_output=True,
                                   text=True, check=True, timeout=5)
            choice = json.loads(reply.stdout)
            self.assertEqual(choice["status"], "selected" if support else "abstained")
            self.assertIs(choice["modelSupported"], support)
            if support:
                self.receipt = receipt_fixture(self.packet)
            else:
                self.receipt = {"schema": "hepta.native-model-abstention.v1", "modelChoice": choice,
                    "source": {"commit": SOURCE["commit"], "tree": SOURCE["tree"], "dirty": False},
                    "productionActivation": False, "externalEffect": False}
            self.write()
            self.assertTrue(self.evaluate(code=0 if support else 3, ood=not support)["task_passed"])


if __name__ == "__main__":
    unittest.main()
