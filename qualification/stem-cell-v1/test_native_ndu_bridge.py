import copy
import hashlib
import os
import subprocess
import unittest

from native_ndu_bridge import build_replay, quantize_q32, reference_receipt, replay_wire, run_native_replay


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture(**updates):
    values = dict(objective_sha256=digest("fixed-objective"), subject_id="group:registered-agent",
                  generation=7, episode_sha256=digest("episode"), coefficient_sha256=digest("coefficients"),
                  units_sha256=digest("normalized-task-minus-cost"),
                  terminal_outcome_sha256=digest("independent-outcome-artifact"),
                  observer_sha256=digest("heldout-task-evaluator"), terminal=1,
                  events=[dict(event_sha256=digest(f"event-{index}"), preference_sha256=digest("preference"),
                               instant=instant, discount=.8) for index, instant in enumerate((.5, .25), 1)])
    values.update(updates)
    return build_replay(**values)


class NativeNduBridgeTests(unittest.TestCase):
    def test_published_native_golden_values_and_signed_ties_even(self):
        request = fixture()
        original = copy.deepcopy(request)
        self.assertEqual(reference_receipt(request)["values_q32"], [5755256177, 4509715661, 4294967296])
        self.assertEqual(request, original)
        self.assertEqual([quantize_q32(x / (1 << 33)) for x in (1, 3, -1, -3)], [0, 2, 0, -2])
        for sign in (1, -1):
            request = fixture(terminal=sign)
            for event in request["events"]:
                event["instant_q32"] *= sign
            self.assertEqual(reference_receipt(request)["values_q32"][0], sign * 5755256177)

    def test_fixed_context_and_every_numeric_input_are_digest_bound(self):
        original = fixture()
        baseline = reference_receipt(original)
        for field, value in (("objective_sha256", digest("new-objective")),
                             ("subject_sha256", digest("new-subject")), ("generation", 8),
                             ("observer_sha256", digest("new-observer")), ("terminal_q32", 1)):
            request = copy.deepcopy(original)
            request[field] = value
            receipt = reference_receipt(request)
            self.assertNotEqual(receipt["input_sha256"], baseline["input_sha256"])
            self.assertNotEqual(receipt["evidence_sha256"], baseline["evidence_sha256"])
        for field in ("instant_q32", "discount_q32"):
            request = copy.deepcopy(original)
            request["events"][0][field] -= 1
            self.assertNotEqual(reference_receipt(request)["evidence_sha256"], baseline["evidence_sha256"])

    def test_missing_outcome_invalid_domains_and_context_substitution_reject(self):
        for changes in (dict(terminal_outcome_sha256="0" * 64), dict(observer_sha256="0" * 64),
                        dict(generation=0), dict(generation=True), dict(terminal=float("nan")),
                        dict(events=[]), dict(lower=2, upper=1)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fixture(**changes)
        request = fixture()
        request["events"][0]["generation"] = 8
        with self.assertRaises(ValueError):
            replay_wire(request)
        request = fixture()
        request["events"][1]["event_sha256"] = request["events"][0]["event_sha256"]
        with self.assertRaises(ValueError):
            replay_wire(request)

    def test_projection_and_input_footer_are_explicit(self):
        request = fixture(upper=1)
        receipt = reference_receipt(request)
        self.assertEqual((receipt["values_q32"], receipt["projection_count"]), ([1 << 32] * 3, 2))
        payload, footer = replay_wire(request).rsplit(b"finish ", 1)
        self.assertEqual(footer.strip().decode(), hashlib.sha256(payload).hexdigest())


@unittest.skipUnless(os.environ.get("HEPTA_NDU_GROUP_REPLAY_BINARY"), "native binary not supplied")
class ExecutedNativeNduTests(unittest.TestCase):
    def test_real_native_composition_matches_q32_receipts(self):
        binary = os.environ["HEPTA_NDU_GROUP_REPLAY_BINARY"]
        for request in (fixture(), fixture(upper=1), fixture(generation=8)):
            with self.subTest(generation=request["generation"], upper=request["upper_q32"]):
                receipt = run_native_replay(request, binary)
                self.assertTrue(receipt["reference_match"])
                self.assertFalse(receipt["production_owner_integrated"])
                self.assertFalse(receipt["general_fbsde_solved"])
        wire = replay_wire(fixture()).replace(b"event 1 ", b"event 2 ", 1)
        result = subprocess.run([binary], input=wire, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
