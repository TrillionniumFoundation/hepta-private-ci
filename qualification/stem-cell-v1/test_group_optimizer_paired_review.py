"""Original-byte optimizer pairing negative controls, no Torch/model imports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from group_optimizer_paired_review import review_pair, digest
from test_group_attention_campaign_review import fixture


def materials(folder):
    root=Path(folder); a=root/"sgd"; b=root/"adam"
    for path in (a,b):
        path.mkdir()
        fixture(path)
        protocol=json.loads((path/"protocol.json").read_text())
        report=json.loads((path/"report.json").read_text())
        encoder=json.loads((path/"encoder.json").read_text())
        teacher=json.loads((path/"teacher.json").read_text())
        encoder.update(cpu_ns=150,model_material={"checkpoint_digest":"1"*64})
        teacher["cpu_ns"]=60
        report.update(encoder_cost=encoder,teacher=teacher,
                      actual_lifecycle_cpu_ns=10000,
                      torch_lazy_setup_cost={"cpu_ns":25})
        if path==b:
            protocol["training_profile"]="adam_v1"
            protocol["optimizer_policy"]={
                "core_optimizer_kind":"adam", "core_learning_rate":.008}
            for name in ("core","attention"):
                report["training"][name].update(
                    optimizer_kind="adam", optimizer_learning_rate=.008,
                    optimizer="Adam_unfused_nonforeach_beta_0.9_0.999",
                    optimizer_bytes=128)
        report["protocol_sha256"]=digest(protocol)
        for name,value in (("protocol",protocol),("report",report),
                           ("encoder",encoder),("teacher",teacher)):
            (path/(name+".json")).write_text(json.dumps(value,allow_nan=False))
    return a,b


class PairTests(unittest.TestCase):
    def test_valid_diagnostic_is_not_a_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            a,b=materials(temporary)
            value=review_pair(a,b)
            self.assertTrue(value["paired_structure_passed"])
            self.assertFalse(value["production_promotion_permitted"])
            self.assertFalse(value["causal_optimizer_effect_proved"])
            self.assertEqual(value["comparisons"]["test"]["core_ndu"]["adam_correct_delta"],0)

    def test_prevent_same_dir_and_fake_optimizer_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            a,b=materials(temporary)
            with self.assertRaisesRegex(ValueError,"independently produced"):
                review_pair(a,a)
            report=json.loads((b/"report.json").read_text())
            report["training"]["core"]["optimizer_bytes"]=0
            (b/"report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,"optimization"):
                review_pair(a,b)

    def test_reject_source_or_feature_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            a,b=materials(temporary)
            protocol=json.loads((b/"protocol.json").read_text())
            protocol["train_source_groups"]=["other"]
            report=json.loads((b/"report.json").read_text())
            report["protocol_sha256"]=digest(protocol)
            (b/"protocol.json").write_text(json.dumps(protocol))
            (b/"report.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                review_pair(a,b)
        with tempfile.TemporaryDirectory() as temporary:
            a,b=materials(temporary)
            rows=json.loads((b/"observations.json").read_text())
            rows[0]["feature_sha256"]="e"*64
            (b/"observations.json").write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                review_pair(a,b)


if __name__ == "__main__":
    unittest.main()
