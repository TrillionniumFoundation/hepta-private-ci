import json
import unittest
from pathlib import Path
from ood_forward_audit import audit, AuditError

ROOT=Path(__file__).parent
PLAN=(ROOT/"HPCA_V2_OOD_PLAN.json").read_bytes()
REPORT=(ROOT/"ACTUAL_OOD_FORWARD_RESULT.json").read_bytes()

class FrozenPromptConditionGate(unittest.TestCase):
    def mutated(self, callback):
        report=json.loads(REPORT)
        callback(report)
        return json.dumps(report).encode("utf-8")

    def test_reject_shared_but_unregistered_prompt_digests(self):
        def rewrite(report):
            for run in report["runs"]:
                run["predictions"][0]["prompt_sha256"]="f"*64
        with self.assertRaisesRegex(AuditError,"frozen plan prompt"):
            audit(PLAN,self.mutated(rewrite))

    def test_reject_run_seed_arm_alias(self):
        with self.assertRaisesRegex(AuditError,"seed.arm metadata"):
            audit(PLAN,self.mutated(lambda x:x["runs"][2].update(seed=999)))

    def test_reject_claimed_training_source_swap(self):
        with self.assertRaisesRegex(AuditError,"training source"):
            audit(PLAN,self.mutated(lambda x:x.update(original_training_result_sha256="0"*64)))

    def test_original_archive_remains_readable(self):
        x=audit(PLAN,REPORT)
        self.assertEqual(x["original_forward_rows_verified"],216)
        self.assertEqual(x["status"],"HOLD_NO_GO_OPERATOR_ONLY")
