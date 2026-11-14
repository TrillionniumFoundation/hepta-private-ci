"""Focused model-free semantic replay and forged trace denials."""
import copy
import unittest
from group_trace_semantic_audit import digest, verify_trace_semantics


def record(mode, status, guesses, answer, family="dependency"):
    steps = len(guesses)
    entries, statuses = [], []
    for i, guess in enumerate(guesses):
        feedback = ("missing_evidence" if answer is None else "supported"
                    if ord(guess) - 65 == answer else "unsupported_" + family)
        accept = feedback == "supported" and (mode == "ndu" or i == steps-1)
        entries += [dict(kind="propose", output_digest=digest(guess)),
                    dict(kind="verify", output_digest=digest([accept, feedback]))]
        statuses.append(feedback)
        if i < steps-1 or status.startswith("ndu_stop:"):
            entries.append(dict(kind="value", output_digest=digest({"step": i})))
    value_entries = [e for e in entries if e["kind"] == "value"]
    decisions = ([dict(estimate_id=e["output_digest"],
                       continue_computation=(i < len(value_entries)-1
                                             or not status.startswith("ndu_stop:")),
                       reason=(status.split(":", 1)[1] if status.startswith("ndu_stop:")
                               else "supported_net_gain"))
                  for i, e in enumerate(value_entries)] if mode == "ndu" else [])
    return dict(schema="hepta.group.system2-full-trace.v2",
                proposed_candidates=guesses, final_candidate=guesses[-1],
                verifier_statuses=statuses, trace=entries, ndu_decisions=decisions)


class TraceSemanticAuditTests(unittest.TestCase):
    def test_realistic_fixed_depth_and_ndu_stop(self):
        fixed = dict(steps=4, execution_mode="fixed",
                     execution_status="verifier_accepted_not_independent_eval")
        data = record("fixed", fixed["execution_status"], ["H","A","G","B"], 1)
        self.assertTrue(verify_trace_semantics(fixed, data, 1, "dependency"))
        ndu = dict(steps=1, execution_mode="ndu",
                   execution_status="ndu_stop:no_supported_net_gain")
        data = record("ndu", ndu["execution_status"], ["H"], None)
        self.assertTrue(verify_trace_semantics(ndu, data, None, "dependency"))

    def test_rehashing_changed_candidate_cannot_keep_old_feedback(self):
        row = dict(steps=4, execution_mode="fixed",
                   execution_status="verifier_accepted_not_independent_eval")
        data = record("fixed", row["execution_status"], ["H","A","G","B"], 1)
        data["proposed_candidates"][0] = "B"
        data["trace"][0]["output_digest"] = digest("B")
        with self.assertRaisesRegex(ValueError, "verifier feedback"):
            verify_trace_semantics(row, data, 1, "dependency")

    def test_ndu_stop_reason_and_value_identity_are_bound(self):
        row = dict(steps=1, execution_mode="ndu",
                   execution_status="ndu_stop:no_supported_net_gain")
        baseline = record("ndu", row["execution_status"], ["H"], None)
        tampered = copy.deepcopy(baseline)
        tampered["ndu_decisions"][0]["reason"] = "invented_win"
        with self.assertRaisesRegex(ValueError, "stopping reason"):
            verify_trace_semantics(row, tampered, None, "dependency")
        tampered = copy.deepcopy(baseline)
        tampered["ndu_decisions"][0]["estimate_id"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "estimate differs"):
            verify_trace_semantics(row, tampered, None, "dependency")

    def test_reject_unsupported_early_ndu_accept(self):
        row = dict(steps=1, execution_mode="ndu",
                   execution_status="verifier_accepted_not_independent_eval")
        fake = record("ndu", row["execution_status"], ["A"], None)
        with self.assertRaisesRegex(ValueError, "terminal System2 status"):
            verify_trace_semantics(row, fake, None, "dependency")


if __name__ == "__main__":
    unittest.main()
