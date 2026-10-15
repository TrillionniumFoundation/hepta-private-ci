from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from group_encoder import file_digest
from multirc_data import ReaderCase
from token_native_campaign import ARMS, evaluate, load_critic, profile_bounds, summarize, train
from token_reader import TokenReader
from token_reader_training import TokenBatch


def sample(name, label=0):
    return ReaderCase(name, "q", "a", "question", "answer", ("fact",), label, "train",
                      sha256(name.encode()).hexdigest())


class TinyBank:
    def __init__(self):
        self.features = dict(facts=torch.randn(1, 2, 3, 384), question=torch.randn(1, 2, 384),
            candidate=torch.randn(1, 2, 384), fact_mask=torch.ones(1, 2, 3, dtype=torch.bool),
            question_mask=torch.ones(1, 2, dtype=torch.bool), candidate_mask=torch.ones(1, 2, dtype=torch.bool))

    def restore_local(self, folder):
        pass

    def report(self):
        return dict(fixture_only=True)

    def public(self, case):
        return dict(self.features, sentence_indices=torch.tensor([[0, 1]]),
                    source_sha256=case.source_hash, feature_sha256="a" * 64)

    def dataset(self, cases):
        return TokenBatch(*(torch.cat([self.features[key] for _ in cases]) for key in self.features),
                          targets=torch.tensor([case.label for case in cases]),
                          source_groups=tuple(case.source_hash for case in cases))


class NativeCampaignTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(12)

    def test_actual_three_seed_verifier_fit_offline_targets_and_frozen_critic_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            campaign = base / "main"
            campaign.mkdir()
            (campaign / "all-models-frozen.json").write_text("{}")
            binary = base / "native"
            binary.write_bytes(b"fixture-not-executed-during-fit")
            args = SimpleNamespace(output=base / "native-run", campaign=campaign, native_binary=binary,
                                   snapshot=base, prepared=base, source=base, previous_design=base, steps=1)
            parts = {name: (sample(name + "-0"), sample(name + "-1", 1))
                     for name in ("verifier_fit", "critic_fit", "critic_calibration")}
            model = TokenReader(384, 32).eval().requires_grad_(False)
            model.training_source_groups = ("reader-only",)
            frozen = dict(model_manifests_sha256={str(seed): "m" for seed in (41, 47, 53)})
            inputs = (parts, {"schema": "fixture-membership"}, frozen, {seed: {} for seed in (41, 47, 53)})
            with patch("token_native_campaign.training_inputs", return_value=inputs), \
                 patch("token_native_campaign.native_inventory", return_value={"source": "s"}), \
                 patch("token_native_campaign.load_models", return_value={"recurrent": model}), \
                 patch("token_native_campaign.TokenBank.from_snapshot", return_value=TinyBank()):
                train(args)
            receipt = json.loads((args.output / "all-artifacts-frozen.json").read_text())
            self.assertEqual(set(receipt["artifact_manifests_sha256"]), {"41", "47", "53"})
            self.assertFalse(receipt["final_evaluation_started"])
            folder = args.output / "seed-41"
            artifact = json.loads((folder / "artifacts.json").read_text())
            critic = load_critic(folder, artifact["critic"])
            self.assertEqual(critic.params_sha256, artifact["critic"]["params_sha256"])
            self.assertEqual(set(critic.metadata["source_groups"]["fit"]),
                             {case.source_hash for case in parts["critic_fit"]})
            (folder / "critic.pt").write_bytes(b"substitution")
            with self.assertRaisesRegex(ValueError, "critic file changed"):
                load_critic(folder, artifact["critic"])

    def test_unknown_work_refuses_native_profile_instead_of_inventing_bound(self):
        model = SimpleNamespace(training_source_groups=("reader",))
        verifier = SimpleNamespace(training_source_groups=("verifier",))
        known = dict(empirical_next_hop_maximum=dict(formula_flops=11, wall_ns=13))
        bounds = profile_bounds(model, verifier, [known])
        self.assertEqual((bounds["formula_work_upper"], bounds["duration_upper_ns"]), (44, 100_000_000))
        with self.assertRaisesRegex(ValueError, "freeze/evaluation closed"):
            profile_bounds(model, verifier, [dict(empirical_next_hop_maximum=dict(formula_flops=None, wall_ns=13))])

    def test_unknown_child_cpu_and_native_wall_accounting_survive_summary(self):
        case = sample("summary", 1)
        row = dict(case_id=case.case_id, prediction=1, valid=True, steps=1, native_decisions=1,
            feature_preparation=dict(cpu_ns=2, wall_ns=3),
            request_costs=dict(accounted_cpu_ns=None, self_cpu_ns=5, native_child_cpu_ns=None,
                               wall_ns=11, complete_formula_flops=None))
        report = summarize([case], [row])
        self.assertIsNone(report["cpu_ns"])
        self.assertIsNone(report["formula_flops"])
        self.assertEqual((report["wall_ns"], report["execution_wall_ns"]), (14, 11))
        self.assertEqual(report["f1_a"], 1.)
        self.assertEqual(len(ARMS), 5)

    def test_missing_main_completion_keeps_final_feature_cache_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            native, main = base / "native", base / "main"
            native.mkdir()
            main.mkdir()
            binary = base / "binary"
            binary.write_bytes(b"fixture")
            (main / "all-models-frozen.json").write_text("{}")
            design = dict(source_sha256={"x": "y"}, native_binary_sha256=file_digest(binary),
                          main_freeze_sha256=file_digest(main / "all-models-frozen.json"))
            (native / "design.json").write_text(json.dumps(design))
            (native / "all-artifacts-frozen.json").write_text(json.dumps(dict(source_sha256={"x": "y"}, frozen_ns=42)))
            args = SimpleNamespace(output=native, campaign=main, native_binary=binary)
            with patch("token_native_campaign.training_inputs", return_value=({}, {}, {}, {})), \
                 patch("token_native_campaign.native_inventory", return_value={"x": "y"}), \
                 patch("token_native_campaign.TokenBank.from_snapshot") as loader:
                with self.assertRaisesRegex(ValueError, "must complete before native"):
                    evaluate(args)
                loader.assert_not_called()
                (main / "completion.json").write_text("{}")
                (main / "evaluation-start.json").write_text(json.dumps(dict(started_ns=41)))
                with self.assertRaisesRegex(ValueError, "must freeze before"):
                    evaluate(args)
                loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
