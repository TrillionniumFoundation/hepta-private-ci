"""Numerical/authority adversarial tests for true train-time sparse Top-1."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from qualification.cell_meta_execution_af import physical_router_audit as soft_review
from qualification.cell_meta_execution_af import physical_router_hard_review as review
from qualification.cell_meta_execution_af import physical_router_hard_train as train
from qualification.cell_meta_execution_af import physical_router_top1 as posthoc
from qualification.cell_meta_execution_af import physical_router_trial as base


class GenuineHardTrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = base.synthetic_panel(seed=41, rule="conditional", rows=64)
        cls.soft = base.run(cls.panel, steps=5)
        cls.post = posthoc.create_report(cls.panel, cls.soft)
        cls.hard = train.produce(cls.panel, cls.soft, cls.post)
        cls.accepted = review.replay(cls.panel, cls.soft, cls.post, cls.hard)

    def reject(self, candidate, word=None, panel=None, soft=None, post=None):
        panel = self.panel if panel is None else panel
        soft = self.soft if soft is None else soft
        post = self.post if post is None else post
        with self.assertRaises((review.HardReplayDenied, soft_review.AuditError)) as caught:
            review.replay(panel, soft, post, candidate)
        if word is not None:
            self.assertIn(word, str(caught.exception))

    def test_all_four_actual_torch_training_accepted(self):
        self.assertEqual(self.accepted["outcome"], "HARD_TRAINED_NUMERIC_REPLAY_NO_AUTHORITY")
        self.assertEqual([v["arm"] for v in self.accepted["comparisons"]], list(base.ARMS))
        self.assertTrue(self.accepted["matched_primary_train_eval_head_rows"])
        self.assertFalse(self.accepted["matched_all_head_forward_rows"])
        self.assertFalse(self.accepted["matched_total_compute"])
        self.assertFalse(self.accepted["production_selection_authorized"])

    def test_matched_real_head_forward_and_sample_rows(self):
        meters = [x["meters"] for x in self.hard["results"]]
        self.assertEqual({x["train_head_0_rows"] + x["train_head_1_rows"] for x in meters}, {960})
        self.assertEqual({x["eval_head_0_rows"] + x["eval_head_1_rows"] for x in meters}, {256})
        self.assertEqual({x["sample_exposures"] for x in meters}, {960})
        self.assertEqual({x["optimizer_steps"] for x in meters}, {10})

    def test_sealed_eval_never_influences_training_weights(self):
        changed = copy.deepcopy(self.panel)
        for name in base.EVAL_PARTITIONS:
            for row in changed["partitions"][name]:
                row["label"] = 1 - row["label"]
        base.validate(changed)
        first = train.train_one(changed, "learned_router", steps=5)
        original = self.hard["results"][2]
        self.assertEqual(first["weights_sha256"], original["weights_sha256"])
        self.assertEqual(first["predictions"], original["predictions"])
        self.assertEqual(first["split_proposed"], original["split_proposed"])
        self.assertNotEqual(train.score_after_seal(changed, first),
                            train.score_after_seal(self.panel, first))

    def test_training_labels_change_learning(self):
        changed = copy.deepcopy(self.panel)
        for row in changed["partitions"]["new_train"]:
            row["label"] = 1 - row["label"]
        result = train.train_one(changed, "learned_router", steps=5)
        self.assertNotEqual(result["weights_sha256"], self.hard["results"][2]["weights_sha256"])

    def test_all_active_heads_have_gradients_from_real_sparse_path(self):
        import torch
        import torch.nn.functional as F
        bank = train.SparseTop1Bank(2, 0, seed=41)
        x = torch.tensor([[-2.0,1.0], [-1.0,-1.0], [.5,.6], [1.0,-.5]])
        bank.clone_parent(x, "learned_router")
        with torch.no_grad():
            bank.weights[1,0] = -2.0
            bank.weights[0,0] = 2.0
        y = torch.tensor([0.0,0.0,1.0,1.0])
        p, selected, (log_prob, entropy) = bank.forward(x, train=True)
        losses = F.binary_cross_entropy(p,y,reduction="none")
        objective = losses.mean() + train.REINFORCE_SCALE*((losses.detach()-.69)*log_prob).mean()
        objective = objective-train.ENTROPY_SCALE*entropy.mean()
        objective.backward()
        self.assertGreater(float(torch.linalg.vector_norm(bank.gate.grad)), 1e-8)
        self.assertEqual(int(selected.numel()), int(p.numel()))
        self.assertEqual(bank.work.train_head_0_rows+bank.work.train_head_1_rows, 4)

    def test_structural_split_is_train_only(self):
        panel = base.synthetic_panel(seed=41,rule="stable",rows=64)
        no = train.train_one(panel,"adaptive_split",steps=5)
        self.assertFalse(no["split_proposed"])
        self.assertEqual(no["meters"]["train_router_rows"], 0)
        condition = self.hard["results"][3]
        self.assertTrue(condition["split_proposed"])
        self.assertEqual(condition["meters"]["learned_gate_optimizer_steps"], 5)

    def test_parent_child_bytes_exact_before_second_stage(self):
        for arm in self.hard["results"]:
            p = review.decode(arm["stage1_parent_fp32"], [5])
            q = review.decode(arm["stage1_child_fp32"], [5])
            if arm["split_proposed"]:
                self.assertEqual(p,q)
            else:
                self.assertEqual(q, [0.]*5)

    def test_old_and_new_train_loss_independently_replayed(self):
        for arm in self.hard["results"]:
            p = review.decode(arm["stage1_parent_fp32"],[5])
            loss=review.old_stage_brier(self.panel["partitions"]["new_train"],p)
            self.assertAlmostEqual(arm["train_only_new_brier"],loss,delta=1e-6)

    def test_fixed_router_executes_predeclared_route_for_all_steps(self):
        arm=self.hard["results"][1]
        expected=[int(r["features"][3]>=0) for k in ("old_train","new_train")
                  for r in self.panel["partitions"][k]]
        for hx in arm["stage2_selected_head_bitsets_le"]:
            self.assertEqual(review.bits(hx,len(expected)),expected)

    def test_no_change_traces_never_route_to_child(self):
        arm=self.hard["results"][0]
        self.assertTrue(all(
            sum(review.bits(b, 128)) == 0 for b in arm["stage2_selected_head_bitsets_le"]))

    def test_fake_final_prediction_fails_replay(self):
        bad=copy.deepcopy(self.hard)
        item=bad["results"][2]["predictions"]["future_1"][0]
        item["probability"] = 0.123456789
        bad["results"][2]["prediction_sha256"] = base.digest(bad["results"][2]["predictions"])
        self.reject(bad,"logit")

    def test_fake_final_selected_expert_rejected(self):
        bad=copy.deepcopy(self.hard)
        item=bad["results"][1]["predictions"]["future_1"][0]
        item["selected_head"] = 1-item["selected_head"]
        bad["results"][1]["prediction_sha256"] = base.digest(bad["results"][1]["predictions"])
        self.reject(bad,"selected Head")

    def test_mutated_model_weights_rejected_with_original_hash(self):
        bad=copy.deepcopy(self.hard)
        o=bad["results"][2]["weights_fp32"]["heads"]
        o["data_le_hex"] = ("00" if o["data_le_hex"][:2] != "00" else "01") + o["data_le_hex"][2:]
        self.reject(bad,"weight")

    def test_relabelled_parent_pretraining_invalidates_split_receipt(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][3]["stage1_parent_fp32"]["data_le_hex"] = "00"*20
        self.reject(bad,"stage1 Brier")

    def test_parent_child_copy_cannot_be_faked(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][3]["stage1_child_fp32"]["data_le_hex"] = "00"*20
        self.reject(bad,"copy parent")

    def test_split_trigger_cannot_be_relabelled(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][3]["split_proposed"] = False
        self.reject(bad,"selection changed")

    def test_router_initialization_must_be_frozen(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][2]["stage1_gate_fp32"]["data_le_hex"] = "00"*20
        self.reject(bad,"initial Router")

    def test_fixed_router_cannot_change_weights(self):
        bad=copy.deepcopy(self.hard)
        # The unchanged edit remains valid; instead mutate final gate and rehash inventory.
        import struct,hashlib
        arm=bad["results"][1]
        arm["weights_fp32"]["gate"]["data_le_hex"] = struct.pack('<5f',0,0,0,1.1,0).hex()
        h=hashlib.sha256()
        for name in ("heads","gate"):
            item=arm["weights_fp32"][name]
            h.update(name.encode()+b'\x00'+base.canonical(item["shape"])+b'\x00'
                     +bytes.fromhex(item["data_le_hex"]))
        arm["weights_sha256"]=h.hexdigest()
        self.reject(bad,"fixed Router")

    def test_train_route_count_forgery_rejected(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][2]["meters"]["train_head_1_rows"]+=1
        self.reject(bad,"train_head_1_rows")

    def test_head_forward_count_cannot_claim_soft_mix(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][1]["meters"]["train_head_0_rows"]+=320
        self.reject(bad,"train_head_0_rows")

    def test_gate_sampling_meter_not_implicit(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][2]["meters"]["sampled_routes"]=0
        self.reject(bad,"sampled_routes")

    def test_optimizer_work_cannot_be_free(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][3]["meters"]["optimizer_steps"]=0
        self.reject(bad,"optimizer_steps")

    def test_fixed_route_trace_cannot_vary(self):
        bad=copy.deepcopy(self.hard)
        trace=bad["results"][1]["stage2_selected_head_bitsets_le"]
        trace[0]='00'*16
        self.reject(bad,"fixed Top-1 Router")

    def test_bitset_padding_rejects_hidden_selection(self):
        # A non-multiple-of-eight trace can hide a forbidden extra route.
        with self.assertRaises(review.HardReplayDenied):
            review.bits('ff',3)

    def test_unknown_critical_field_rejected(self):
        bad=copy.deepcopy(self.hard)
        bad['force_merge']=True
        self.reject(bad,"unknown fields")

    def test_elevated_production_flag_rejected(self):
        bad=copy.deepcopy(self.hard)
        bad["physical_cell_split_permitted"]=True
        self.reject(bad,"authority")

    def test_rounded_future_scores_cannot_be_improved_by_claim(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][1]["retrospective_evaluation"]["future_2"]["brier"]-=.025
        self.reject(bad,"metric")

    def test_soft_report_lineage_and_frozen_controls_required(self):
        bad=copy.deepcopy(self.hard)
        bad["soft_predecessor_sha256"]="1"*64
        self.reject(bad,"predecessor")

    def test_posthoc_frozen_weights_lineage_required(self):
        bad=copy.deepcopy(self.hard)
        bad["posthoc_predecessor_sha256"]="1"*64
        self.reject(bad,"predecessor")

    def test_unregistered_seed_denied(self):
        panel=base.synthetic_panel(seed=59,rule="conditional",rows=64)
        soft=base.run(panel,steps=3)
        post=posthoc.create_report(panel,soft)
        with self.assertRaises(train.HardTrainDenied):
            train.produce(panel,soft,post)

    def test_mismatched_report_source_producer_denied(self):
        bad=copy.deepcopy(self.soft)
        bad["source_panel_sha256"]="1"*64
        with self.assertRaises(soft_review.AuditError):
            train.produce(self.panel,bad,self.post)

    def test_cli_is_create_only_and_independent_review_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p, payload in (("panel.json", self.panel), ("soft.json", self.soft),
                               ("post.json", self.post)):
                (root/p).write_bytes(base.canonical(payload)+b'\n')
            argv=["--panel",str(root/'panel.json'),"--soft-report",str(root/'soft.json'),
                  "--posthoc-report",str(root/'post.json'),"--out",str(root/'hard.json')]
            self.assertEqual(train.main(argv),0)
            self.assertEqual(train.main(argv),2)
            self.assertEqual(review.main(argv[:-2]+["--hard-report",str(root/'hard.json')]),0)
            with self.assertRaises(FileExistsError):
                (root/'hard.json').open('x')

    def test_local_false_future_ood_cannot_be_relabelled(self):
        for key in ("prospective_future_windows_verified","true_ood_verified",
                    "independent_model_origin_verified","external_training_execution_attested"):
            bad=copy.deepcopy(self.hard)
            bad[key]=True
            self.reject(bad,key)

    def test_invalid_cpu_cost_nan_denied(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][2]["meters"]["train_cpu_seconds"]=float('nan')
        self.reject(bad,"train_cpu_seconds")

    def test_total_compute_cannot_be_claimed_from_equal_head_rows(self):
        bad=copy.deepcopy(self.hard)
        bad["total_compute_matched"]=True
        self.reject(bad,"total_compute_matched")

    def test_traces_cannot_skip_training_round(self):
        bad=copy.deepcopy(self.hard)
        bad["results"][0]["stage2_selected_head_bitsets_le"].pop()
        self.reject(bad,"route traces")

    def test_static_packed_branch_has_single_head_output(self):
        data=self.hard["results"][1]
        n=sum(len(self.panel["partitions"][p]) for p in base.EVAL_PARTITIONS)
        self.assertEqual(n,data["meters"]["eval_head_0_rows"]+data["meters"]["eval_head_1_rows"])
        self.assertEqual(data["meters"]["eval_router_rows"],n)

if __name__ == "__main__":
    unittest.main()
