"""Adversarial parity audit fixtures, no full checkpoint or target host."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import torch
from safetensors.torch import save
from replacement_gate import EXPECTED, SPLITS
from replacement_head_parity_audit import audit_all, verify_head_artifact, _strict_json


def fixture():
    sha = "a"*64
    registry=json.loads(Path(__file__).with_name("replacement_models.json").read_text())
    rowbase = {k:[{"source_id": f"{k}-{i}", "source_group_id": f"{k}-{i}",
                   "label": i%4,"is_ood":k=="ood", "language":"en",
                   "probabilities": [.25,.25,.25,.25]} for i in range(8)] for k in SPLITS}
    from replacement_gate import score_rows
    scores = {k: {"rows": v, "metrics": score_rows(v)} for k,v in rowbase.items()}
    artifact = save({"weight": torch.zeros((4,256)), "bias": torch.zeros(4)})
    observations={}
    for name in EXPECTED:
        weight_sha=registry["models"][name]["weight_sha256"]
        original = {"checkpoint": {"loaded_weight_sha256":weight_sha},
                    "frozen_selected_rows_sha256":sha,"source_archive_sha256":sha,
                    "observed_forward_calls":40, "scores":copy.deepcopy(scores)}
        parity={"schema":"hepta.neuron.replacement-frozen-head-parity.v1",
                "candidate":name,"mode":"SHADOW_ONLY","authority":"DENY_ALL",
                "production_activation_allowed":False,"independent_observer_attested":False,
                "target_host_qualified":False,"original_policy_unchanged":True,
                "checkpoint_weight_sha256":weight_sha,"frozen_selected_rows_sha256":sha,
                "source_archive_sha256":sha,"projection":"frozen_gaussian_256d_v1",
                "projection_seed":2307,"projection_sha256":sha,"original_feature_width":640,
                "output_width":256,"context_tokens":192,"trained_head_parameter_count":1028,
                "head_artifact_format":"safetensors-f32-linear",
                "head_reloaded_identical_logits":True,
                "head_artifact_bytes":len(artifact),
                "head_artifact_sha256":hashlib.sha256(artifact).hexdigest(),
                "head_training":{"seed":7,"optimizer":"AdamW","steps":200,
                                 "learning_rate":0.05,"head_parameters":1028},
                "temperature":1.,
                "evaluation_scope":"historical_2014_en_only_frozen_encoder_vs_task_head",
                "real_encoder_forward_calls":40,
                "original_full_policy_forward_calls":40 if name.startswith("laya_") else 0,
                "scores":copy.deepcopy(scores)}
        observations[name]=(parity, original, artifact)
    return registry, observations


class Tests(unittest.TestCase):
    def test_five_complete_frozen_arms_require_review(self):
        registry, records=fixture()
        result=audit_all(registry,records)
        self.assertEqual(result["preflight"],"REVIEW_REQUIRED",result['blockers'])
        self.assertEqual(result["authority"],"DENY_ALL")
        self.assertFalse(result["production_activation_allowed"])

    def test_forged_head_bytes_and_training_denied(self):
        registry, records=fixture()
        p,o,b=records["harrier_270m"]
        records["harrier_270m"]=(p,o,b[:-1]+b"z")
        self.assertEqual(audit_all(registry,records)["preflight"],"BLOCKED")
        registry,records=fixture()
        records['laya_typed_421m'][0]['head_training']['steps']=199
        self.assertEqual(audit_all(registry,records)['preflight'],'BLOCKED')

    def test_mixed_gold_rows_denied(self):
        registry,records=fixture()
        records['laya_multi_322m'][0]['scores']['future_2']['rows'][0]['source_id']='foreign'
        self.assertEqual(audit_all(registry,records)['preflight'],'BLOCKED')

    def test_duplicate_json_key_and_nonfinite_fail(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            _strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            _strict_json(b'{"a":NaN}')

    def test_oversized_or_non_finite_tensor_denied(self):
        registry,records=fixture()
        p,o,blob=records['arctic_305m']
        self.assertTrue(verify_head_artifact(blob,p['head_artifact_sha256']))
        self.assertFalse(verify_head_artifact(blob+b'junk',p['head_artifact_sha256']))
        bad=save({"weight":torch.full((4,256),float('nan')),"bias":torch.zeros(4)})
        self.assertFalse(verify_head_artifact(bad, hashlib.sha256(bad).hexdigest()))

if __name__=='__main__': unittest.main()
