"""P7 adversarial/real-origin tests. Requires downloaded original P5 files for full suite.

Use HEPTA_P7_EVIDENCE_ROOT=/path/to/evidence containing public/gold/original/review.
When absent, parser/source-only tests run, but full CI always supplies this root.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import physical_evidence_gate as p7

ROOT_ENV = "HEPTA_P7_EVIDENCE_ROOT"


def original_paths(root: Path):
    return {
        "train-public.json": root/"public"/"train-public.json",
        "held-public.json": root/"public"/"held-public.json",
        "held-private-labels.json": root/"gold"/"held-private-labels.json",
        "completed-original.json": root/"original"/"completed-original.json",
        "frozen-plan.json": root/"original"/"frozen-plan.json",
        "original-starts-and-dones.jsonl": root/"original"/"original-starts-and-dones.jsonl",
        "hepta-p5-sanitized-review.json": root/"review"/"hepta-p5-sanitized-review.json",
    }


class SourceOnlyTests(unittest.TestCase):
    def test_exact_output_grammar(self):
        for token, ans in {"3":3,"<1>":1," FINAL=2 ":2,"final : <0>":0}.items():
            self.assertEqual(p7.parse_answer(token),ans)
        for token in ("class=2", "{2}", "1 OR 2", "1 explanation", "1 <script>", "<think>1</think>",
                      "<1><2>", "<1", "00", "-1", "4", "", "FINAL=2\nanswer 3"):
            self.assertIsNone(p7.parse_answer(token))

    def test_bad_decoding(self):
        for raw in (b'{"a":1,"a":2}',b'{"test":NaN}',b'{"test":Infinity}'):
            with self.assertRaises(Exception):p7.decode(raw)

    def test_reject_missing_files(self):
        with self.assertRaises(p7.EvidenceError):p7.read_evidence({})

    def test_no_production_status_paths(self):
        self.assertEqual(p7.POSTURE,"RESEARCH_ONLY_DENY_ALL")
        self.assertEqual(len(p7.PINNED_SHA256),7)
        self.assertEqual(len(set(p7.PINNED_SHA256.values())),7)
        self.assertEqual(len(p7.POLICIES),7)


@unittest.skipUnless(os.environ.get(ROOT_ENV),"real SHA-pinned P5 artifact path supplied only to CI/explicit local original replay")
class OriginalReplays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.paths=original_paths(Path(os.environ[ROOT_ENV]))
        cls.docs=p7.read_evidence(cls.paths)

    def check_bad(self,edit,pattern="",reseal_completed=False):
        data=copy.deepcopy(self.docs)
        edit(data)
        if reseal_completed:
            # Attack also rewrites the *untrusted* digest in the published reviewer;
            # original journal/semantic checks must still reject the forgery.
            data["hepta-p5-sanitized-review.json"]["completed_original_sha256"]=p7.digest(data["completed-original.json"])
        with self.assertRaisesRegex(p7.EvidenceError,pattern):
            p7.audit(data)

    def test_real_original_full_raw_replay(self):
        result=p7.audit(self.docs)
        self.assertEqual(result["decision"],"OBSERVED_NO_NDU_TASK_COST_LIFT")
        self.assertEqual(result["original_inference_calls"],192)
        self.assertEqual(result["equal_cap"]["thinking_wins"],0)
        self.assertEqual(result["equal_cap"]["thinking_losses"],5)
        self.assertEqual(result["equal_cap"]["thinking_incomplete"],16)
        self.assertEqual([(p["policy"],p["correct"],p["actual_input_output_tokens"])
                          for p in result["policy_results"]],
                         [("direct",5,2155),("fixed_reason",5,2331),("greedy",5,2189),
                          ("neutral",5,2189),("fixed_risk",5,2189),
                          ("ndu_discrete",5,2189),("ordinary_same_profile",5,2189)])
        self.assertTrue(all("accept" not in result[k].lower() for k in ("decision","authority")))

    def test_pinned_digest_fails_if_original_text_tampered(self):
        with tempfile.TemporaryDirectory() as folder:
            copies={k:Path(folder,k) for k in self.paths}
            for k in copies:copies[k].write_bytes(self.paths[k].read_bytes())
            copies["held-public.json"].write_bytes(copies["held-public.json"].read_bytes().replace(b"Fears",b"Fearz"))
            with self.assertRaisesRegex(p7.EvidenceError,"original file digest"):
                p7.read_evidence(copies)

    def test_forced_score_change(self):
        self.check_bad(lambda d:d["hepta-p5-sanitized-review.json"]["seven_policy_results"][0].update(correct=16),
                       "independent reviewer")

    def test_duplicate_original_call(self):
        self.check_bad(lambda d:d["completed-original.json"]["actual_policy_trace"].__setitem__(1, d["completed-original.json"]["actual_policy_trace"][0]),
                       "(unregistered|repeated)",reseal_completed=True)

    def test_counterfeit_checkpoint(self):
        self.check_bad(lambda d:d["completed-original.json"]["physical_model_identity"].update(weights_sha256="0"*64),
                       "identity split")

    def test_held_label_leak(self):
        self.check_bad(lambda d:d["held-public.json"]["rows"][0].update(label=0),"labels leaked")

    def test_false_prospective_claim(self):
        self.check_bad(lambda d:d["held-public.json"]["source"].update(publisher_future_window=True),
                       "source provenance")

    def test_changing_label_rejected(self):
        self.check_bad(lambda d:d["held-private-labels.json"]["rows"][0].update(label=0),
                       "unbalanced held publisher labels")

    def test_resealed_answer_is_not_accepted(self):
        def mutate(d):
            o=d["completed-original.json"]["actual_policy_trace"][0]
            o["answer"]="<2>"
            o["answer_sha256"]=p7.sha(b"<2>")
            o["predicted_class"]=2
        self.check_bad(mutate,"original done-record digest",reseal_completed=True)

    def test_nonfinite_cpu(self):
        self.check_bad(lambda d:d["completed-original.json"]["actual_policy_trace"][0].update(measured_cpu_seconds=float('nan')),
                       "(nonfinite|physical-cost meter)")

    def test_truncated_thinking_claim(self):
        def mutate(d):
            o=next(x for x in d["completed-original.json"]["paired_equalcap_trace"] if x["action"]=="reason")
            o["predicted_class"]=1
        self.check_bad(mutate,"truncated thinking",reseal_completed=True)

    def test_corrupted_journal(self):
        self.check_bad(lambda d:d["original-starts-and-dones.jsonl"].pop(),
                       "truncated/expanded")

    def test_forged_plan(self):
        self.check_bad(lambda d:d["frozen-plan.json"]["selected_request_schedule"][0].update(action="verify"),
                       "P5 independent reviewer mismatches")

    def test_false_saved_compute_claim(self):
        self.check_bad(lambda d:d["hepta-p5-sanitized-review.json"].update(actual_model_savings_proven=True),
                       "falsely asserts")

    def test_equal_cap_seal_drift(self):
        self.check_bad(lambda d:d["completed-original.json"]["paired_equalcap_trace"][1].update(prompt_sha256="0"*64),
                       "unequal original prompt",reseal_completed=True)

    def test_same_profile_policy_drift(self):
        def mutate(d):
            row=next(r for r in d["completed-original.json"]["actual_policy_trace"] if r["policy"]=="ordinary_same_profile")
            row["action"]="verify" if row["action"]=="direct" else "direct"
        self.check_bad(mutate,"(unregistered|repeated|original action|thinking flag)",reseal_completed=True)

    def test_unknown_source_identity(self):
        self.check_bad(lambda d:d["completed-original.json"]["original_train_trace"][0].update(task_id="train-99999"),
                       "TRAIN model trace mismatch",reseal_completed=True)

    def test_journal_order_tamper(self):
        def mutate(d):
            a=d["original-starts-and-dones.jsonl"]
            a[97],a[99]=a[99],a[97]
        self.check_bad(mutate,"original journal order")


if __name__ == "__main__":
    unittest.main()
