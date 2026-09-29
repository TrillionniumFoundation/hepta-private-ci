"""Feature-probe fault tests on a tiny real torch model, not Laya weights."""
import time
import unittest
import torch
from torch import nn
from laya_training_smoke import OPTIONS, capture, cases
from laya_retrieval import RetrievalDriver, EnteredFailure, Rejected


class SmallModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.scorer = nn.Sequential(nn.LayerNorm(4), nn.Linear(4, 4), nn.GELU(), nn.Linear(4, 1))
        self.fail = False

    def forward(self, x):
        logits = self.scorer(x).squeeze(-1)
        if self.fail:
            raise RuntimeError("injected")
        return logits


class FakeAgent:
    cfg = {"max_len": 512, "head_max_len": 192}
    device = "cpu"
    amp_enabled = False
    _fast = None
    class Tokenizer:
        mask_token = "[MASK]"
        def __call__(self, value, **kwargs):
            return {"input_ids": value.split()}
    tok = Tokenizer()

    def __init__(self):
        with torch.random.fork_rng():
            torch.manual_seed(19)
            self.model = SmallModel().eval()
        self.features = torch.tensor([[[0., 1., 0., 0.], [1., 0., 0., 0.], [0., 0., 1., 0.]]])

    def predict(self, state, questions, **kwargs):
        with torch.no_grad():
            p = torch.softmax(self.model(self.features)[0] / 2, -1)
        values = {key: round(float(v), 4) for key, v in zip(OPTIONS, p)}
        return {"answers": {"source": {"probabilities": values,
                                        "choice": max(values, key=values.get)}}}


class CaptureTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.agent = FakeAgent()
        self.driver = RetrievalDriver(self.agent, "a" * 64, 512, 192)
        self.request = next(cases("train"))[2]

    def run_capture(self, temperature=2, deadline=None):
        return capture(self.agent, self.driver, self.request, temperature,
                       deadline if deadline is not None else time.monotonic() + 10)

    def assert_removed(self):
        self.assertFalse(self.agent.model._forward_pre_hooks)
        self.assertFalse(self.agent.model.scorer._forward_pre_hooks)

    def test_real_scorer_features_reproduce_decoder_without_selected_change(self):
        before = [p.clone() for p in self.agent.model.parameters()]
        features, probabilities, observation = self.run_capture()
        torch.testing.assert_close(features, self.agent.features[0])
        self.assertNotEqual(features.data_ptr(), self.agent.features.data_ptr())
        self.assertAlmostEqual(sum(probabilities), 1, places=6)
        self.assertIsNone(observation["task_success"])
        for old, p in zip(before, self.agent.model.parameters()):
            torch.testing.assert_close(old, p)
        self.assert_removed()

    def test_wrong_temperature_breaks_decoder_parity(self):
        with self.assertRaises(ValueError):
            self.run_capture(temperature=.1)
        self.assert_removed()

    def test_entered_failure_removes_hooks_without_fabricating_features(self):
        self.agent.model.fail = True
        with self.assertRaises(EnteredFailure):
            self.run_capture()
        self.assert_removed()

    def test_expiry_and_busy_remove_hooks_without_changing_admission(self):
        with self.assertRaises(Rejected):
            self.run_capture(deadline=time.monotonic() - 1)
        self.assert_removed()
        self.driver._lock.acquire()
        try:
            with self.assertRaises(Rejected):
                self.run_capture()
        finally:
            self.driver._lock.release()
        self.assert_removed()

    def test_unregistered_observation_is_not_silently_overwritten(self):
        hook = self.agent.model.register_forward_pre_hook(lambda *args: None)
        try:
            with self.assertRaises(ValueError):
                self.run_capture()
            self.assertEqual(len(self.agent.model._forward_pre_hooks), 1)
        finally:
            hook.remove()

    def test_mixed_precision_training_or_accelerated_profile_rejects(self):
        for attribute, value in (("amp_enabled", True), ("device", "cuda"), ("_fast", object())):
            old = getattr(self.agent, attribute)
            try:
                setattr(self.agent, attribute, value)
                with self.assertRaises(ValueError):
                    self.run_capture()
            finally:
                setattr(self.agent, attribute, old)
        self.agent.model.train()
        with self.assertRaises(ValueError):
            self.run_capture()
        self.assert_removed()

    def test_fixture_splits_have_disjoint_groups_and_exogenous_labels(self):
        datasets = {split: tuple(cases(split)) for split in ("train", "future", "retention")}
        self.assertEqual([len(v) for v in datasets.values()], [8, 4, 4])
        self.assertEqual(len({r[0] for rows in datasets.values() for r in rows}), 16)
        self.assertLess(max(r[1] for r in datasets["train"]), min(r[1] for r in datasets["future"]))
        self.assertTrue(all(r[3] in OPTIONS for rows in datasets.values() for r in rows))


if __name__ == "__main__":
    unittest.main()
