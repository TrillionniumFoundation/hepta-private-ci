"""V8 checkpoint provenance, diagnostic transforms and once-only boundaries."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from binding_campaign_utils import write
from bridge_reader import build_reader
from endpoint_campaign import train
from endpoint_campaign_utils import (ARMS,SupportDeletedBank,learning_change,load_model,
    save_initialization,save_model,support_transform,teacher_reference)
from endpoint_reader import endpoint_identity,load_bridge_warmup
from group_loop import parameter_digest as typed_digest
from reader_features import tensor_digest
from token_protocol import build_binding_cases
from token_reader_training import TokenBatch


class FixtureBank:
    """Four short fact rows with no tokenizer or pretrained Encoder involved."""
    payload_tokens = 62
    def __init__(self,cases):
        self.tokens = {text:(1,2) for case in cases for text in case.facts}
    def batch(self,cases):
        size = len(cases)
        return TokenBatch(facts=torch.arange(size*4*2*8).reshape(size,4,2,8).float()+1,
            question=torch.ones(size,2,8),candidate=torch.full((size,1,8),2.),
            fact_mask=torch.ones(size,4,2,dtype=torch.bool),question_mask=torch.ones(size,2,dtype=torch.bool),
            candidate_mask=torch.ones(size,1,dtype=torch.bool),targets=torch.tensor([c.label for c in cases]),
            source_groups=tuple(c.source_hash for c in cases))


class EndpointCampaignTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.cases = build_binding_cases("train",groups=1,seed=3)
        self.core = build_reader("bridge",41).eval().requires_grad_(False)
        self.core.training_source_groups = ("fixture-warmup-source",)

    def test_all_variant_checkpoints_roundtrip_without_downgrading_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for arm in ARMS:
                model = load_bridge_warmup(self.core,arm,seed=41)
                folder = root/arm
                initial = save_initialization(folder,model,self.core,41)
                for row in initial["tensors"]:
                    if row["role"] == "common":
                        self.assertEqual(row["sha256"],tensor_digest(self.core.state_dict()[row["name"]]))
                save_model(folder,model,dict(fixture=True,model_arm=arm),seed=41,
                           initial_digest=initial["execution_parameter_sha256"])
                restored,manifest = load_model(folder,expected_arm=arm)
                self.assertEqual(endpoint_identity(restored),endpoint_identity(model))
                self.assertEqual(typed_digest(restored),typed_digest(model))
                self.assertEqual(manifest["training_source_groups"],list(model.training_source_groups))
                with self.assertRaisesRegex(ValueError,"arm differs"):
                    load_model(folder,expected_arm="other")

    def test_support_deletion_changes_only_two_verified_fact_rows(self):
        bank = FixtureBank(self.cases)
        transform = support_transform(self.cases)
        wrapper = SupportDeletedBank(bank,transform)
        original,result = bank.batch(self.cases),wrapper.batch(self.cases)
        for i,row in enumerate(transform["cases"]):
            support = row["deleted_fact_positions"]
            self.assertEqual(len(support),2)
            self.assertTrue(torch.equal(result.facts[i,support],torch.zeros_like(result.facts[i,support])))
            self.assertFalse(result.fact_mask[i,support].any())
            retained = [j for j in range(4) if j not in support]
            self.assertTrue(torch.equal(original.facts[i,retained],result.facts[i,retained]))
            self.assertTrue(torch.equal(original.fact_mask[i,retained],result.fact_mask[i,retained]))
        for name in ("question","candidate","question_mask","candidate_mask","targets"):
            self.assertTrue(torch.equal(getattr(original,name),getattr(result,name)))
        self.assertEqual(original.source_groups,result.source_groups)
        self.assertEqual(len(wrapper.observations),1)
        self.assertIsNone(result.evidence_targets)
        self.assertEqual(len(wrapper.observations[0]["transformed_feature_sha256"]),6)

    def test_support_deletion_rejects_multichunk_facts_and_changed_support(self):
        bank = FixtureBank(self.cases)
        transform = support_transform(self.cases)
        bank.tokens[self.cases[0].facts[0]] = tuple(range(63))
        with self.assertRaisesRegex(ValueError,"single-chunk"):
            SupportDeletedBank(bank,transform).batch(self.cases)
        bad = copy.deepcopy(transform)
        bad["cases"][0]["deleted_fact_positions"] = [0]
        with self.assertRaisesRegex(ValueError,"source identity"):
            SupportDeletedBank(FixtureBank(self.cases),bad).batch(self.cases)

    def test_learning_change_separates_common_and_new_output_weight_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)/"endpoint"
            model = load_bridge_warmup(self.core,"endpoint",seed=41)
            initial = save_initialization(folder,model,self.core,41)
            with torch.no_grad():
                model.endpoint_branch.output.weight[0,0] = .25
                model.project.weight[0,0] += .125
            save_model(folder,model,dict(fixture=True),seed=41,initial_digest=initial["execution_parameter_sha256"])
            delta = learning_change(folder,model)
            self.assertEqual(delta["groups"]["common"]["changed_tensors"],1)
            self.assertEqual(delta["groups"]["extra"]["changed_tensors"],1)
            output = next(r for r in delta["tensors"] if r["name"] == "endpoint_branch.output.weight")
            self.assertEqual(output["before_nonzeros"],0)
            self.assertEqual(output["after_nonzeros"],1)
            self.assertAlmostEqual(output["l2"],.25)

    def test_reused_teacher_is_validated_without_a_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/"seed-41"
            folder.mkdir()
            values = torch.arange(len(self.cases)*2).reshape(len(self.cases),2).float()
            raw = values.numpy().tobytes()
            (folder/"teacher-logits.bin").write_bytes(raw)
            record = dict(execution_parameter_sha256="typed",training_parameter_sha256="legacy",file_sha256="weight")
            teacher = dict(shape=[len(self.cases),2],dtype="torch.float32",case_ids=[c.case_id for c in self.cases],
                raw_file="teacher-logits.bin",raw_file_sha256=tensor_digest(values),raw_logits_sha256=tensor_digest(values),
                model_execution_parameter_sha256="typed",model_training_parameter_sha256="legacy",
                warmup_weight_file_sha256="weight",logits=values.tolist())
            write(folder,"teacher.json",teacher)
            loaded,_ = teacher_reference(SimpleNamespace(previous_v7=root),41,self.cases,record)
            self.assertTrue(torch.equal(loaded,values))
            (folder/"teacher-logits.bin").write_bytes(raw[:-1]+b"x")
            with self.assertRaisesRegex(ValueError,"teacher reference"):
                teacher_reference(SimpleNamespace(previous_v7=root),41,self.cases,record)

    def test_started_training_attempt_is_rejected_before_encoder_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root,"training-start.json",{})
            with patch("endpoint_campaign.checked_design",return_value=({}, {}, {}, ())), \
                    patch("endpoint_campaign.load_bank") as bank:
                with self.assertRaises(FileExistsError):
                    train(SimpleNamespace(output=root))
                bank.assert_not_called()

    def test_incomplete_preparation_cannot_start_training_or_load_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root,previous_v7=root/"old")
            write(root,"design.json",dict(runtime_source_sha256={},protocol_sha256="fixed",
                previous_v7_design_sha256="fixed",previous_v7_training_completion_sha256="fixed",
                reused_cache_files_sha256={},prepared_files_sha256={},historical=dict(observations={})))
            inputs = (dict(extended_cache_files_sha256={}),{}, {}, ())
            with patch("endpoint_campaign_utils.old_inputs",return_value=inputs), \
                    patch("endpoint_campaign_utils.source_inventory",return_value={}), \
                    patch("endpoint_campaign_utils.file_digest",return_value="fixed"), \
                    patch("endpoint_campaign.load_bank") as bank:
                with self.assertRaises(FileNotFoundError):
                    train(args)
                write(root,"preparation-completion.json",dict(design_sha256="fixed",
                    exact_initial_probability_equality={"41":False,"47":True,"53":True},
                    actual_initial_candidate_observations=1536,initial_panels_sha256={}))
                with self.assertRaisesRegex(ValueError,"preparation did not bind"):
                    train(args)
                bank.assert_not_called()
                self.assertFalse((root/"training-start.json").exists())


if __name__ == "__main__":
    unittest.main()
