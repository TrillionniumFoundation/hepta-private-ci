"""Exact score identities and real-file integration for the v2 controller."""

from copy import deepcopy
import itertools
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import torch

from .controller_v2 import conditional_score_loss, distill_dagger, PROTOCOL_PATH
from .mechanism_data import batch
from .media import utility
from .model import JointGenerator, tensor_digest
from .runtime import ScoreTerm, execute, make_profile


DTYPE = torch.float64


def exact_episodes(z, post_action_baseline=False):
    rows = []
    for first, second, emission in itertools.product(range(2), repeat=3):
        p = z[0].sigmoid()
        q = (z[1] + first * 0.4).sigmoid()
        r = (z[2] + second * 0.3).sigmoid()
        laws = [torch.stack((1 - v, v)) for v in (p, q, r)]
        choices = (first, second, emission)
        scores = [law[choice].log() for law, choice in zip(laws, choices)]
        mass = torch.stack([law[choice] for law, choice in zip(laws, choices)]).prod()
        cost1, cost2 = 0.03 + 0.04 * first, 0.02 + 0.05 * second
        returned = 0.7 * emission + 0.1 * first - 0.15 * second - cost1 - cost2 - 0.01
        before = z[0] * 0.3 + (-0.7 if first else 0.4) if post_action_baseline else z[0] * 0.3
        predictions = (before, z[1] * 0.2 - first * 0.4, z[2] * 0.1 + second * 0.2)
        terms = [ScoreTerm(kind, score, value, prefix) for kind, score, value, prefix in zip(
            ("action", "action", "emission"), scores, predictions, (0, cost1, cost1 + cost2))]
        episode = SimpleNamespace(log_probability=sum(scores), net_return=returned,
                                  critic_values=[before], score_terms=terms)
        rows.append((mass, episode))
    return rows


class ConditionalScoreTests(unittest.TestCase):
    def test_exact_history_dependent_baselines_preserve_population_gradient(self):
        for gamma in (0.0, 2.0):
            z = torch.tensor((0.2, -0.3, 0.4), dtype=DTYPE, requires_grad=True)
            rows = exact_episodes(z)
            score, direct = z.sum() * 0, z.sum() * 0
            for mass, episode in rows:
                loss, _ = conditional_score_loss([episode], gamma=gamma)
                score = score + mass.detach() * loss
                returned = z.new_tensor(episode.net_return)
                moment = -returned if gamma == 0 else torch.expm1(-2 * returned) / 2
                direct = direct + mass * moment
            actual = torch.autograd.grad(score, z, retain_graph=True)[0]
            expected = torch.autograd.grad(direct, z)[0]
            torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)

    def test_independent_residual_loo_preserves_exact_joint_gradient(self):
        z = torch.tensor((0.2, -0.3, 0.4), dtype=DTYPE, requires_grad=True)
        rows = exact_episodes(z)
        score = z.sum() * 0
        for (mass1, first), (mass2, second) in itertools.product(rows, repeat=2):
            loss, _ = conditional_score_loss([first, second], independent_episodes=True)
            score = score + (mass1 * mass2).detach() * loss
        direct = sum(mass * torch.expm1(-2 * z.new_tensor(e.net_return)) / 2 for mass, e in rows)
        actual = torch.autograd.grad(score, z, retain_graph=True)[0]
        expected = torch.autograd.grad(direct, z)[0]
        torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)

    def test_future_dependent_baseline_counterexample_is_biased(self):
        z = torch.tensor((0.2, -0.3, 0.4), dtype=DTYPE, requires_grad=True)
        rows = exact_episodes(z, post_action_baseline=True)
        score = sum(mass.detach() * conditional_score_loss([e])[0] for mass, e in rows)
        direct = sum(mass * torch.expm1(-2 * z.new_tensor(e.net_return)) / 2 for mass, e in rows)
        actual = torch.autograd.grad(score, z, retain_graph=True)[0]
        expected = torch.autograd.grad(direct, z)[0]
        self.assertGreater(abs(float(actual[0] - expected[0])), 0.01)

    def test_incomplete_joint_law_and_dependent_batch_reject(self):
        z = torch.zeros(3, dtype=DTYPE, requires_grad=True)
        episode = exact_episodes(z)[0][1]
        with self.assertRaisesRegex(ValueError, "independent"):
            conditional_score_loss([episode, episode])
        episode.score_terms.pop()
        with self.assertRaisesRegex(ValueError, "reconstruct"):
            conditional_score_loss([episode])


class ControllerFileTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1); torch.manual_seed(17)
        self.model = JointGenerator(width=8)
        self.public, self.target = batch([0], "controller-v2-unit")
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def execute(self, name, **kw):
        return execute(self.model, self.public, lambda x: utility(x, self.target).item(),
            self.root / name, seed=17, context_id="unit", source_id="source.unit", **kw)

    def test_real_trace_score_sum_gradients_and_pre_draw_costs(self):
        episode = self.execute("dynamic")
        torch.testing.assert_close(torch.stack([t.log_probability for t in episode.score_terms]).sum(),
                                   episode.log_probability, rtol=1e-5, atol=1e-4)
        events = episode.record["events"]
        self.assertEqual(episode.score_terms[0].prefix_cost, 0)
        self.assertAlmostEqual(episode.score_terms[-1].prefix_cost,
                              sum(c["amount"] for e in events[:-1] for c in e["costs"]))
        self.assertTrue(all(not t.prior_log_moment.requires_grad for t in episode.score_terms))
        loss, _ = conditional_score_loss([episode])
        loss.backward()
        self.assertTrue(all(p.grad is None for n, p in self.model.named_parameters()
                            if n.startswith(("critic.", "delivery_critic."))))
        for prefix in ("actor.", "core.", "emissions."):
            self.assertGreater(sum(p.grad.abs().sum().item() for n, p in self.model.named_parameters()
                                   if n.startswith(prefix) and p.grad is not None), 0)
        self.assertEqual(len(episode.record["outcome"]["artifact_sha256"]), 4)

    def test_fixed_actions_exclude_forced_scores(self):
        episode = self.execute("fixed", strategy="fixed")
        self.assertEqual([term.kind for term in episode.score_terms], ["emission"])
        deterministic = self.execute("deterministic", strategy="fixed", deterministic_emission=True)
        self.assertEqual(deterministic.score_terms, [])

    def test_dagger_queries_real_student_states_and_freezes_non_actor(self):
        protocol = json.loads(PROTOCOL_PATH.read_text())
        protocol.update(distillation_rounds=2, distillation_sources_per_round=1,
                        distillation_updates_per_round=2)
        original = deepcopy(self.model.state_dict())
        student, report = distill_dagger(self.model, self.root / "dagger", make_profile(), protocol, 17, 8)
        self.assertEqual(report["actual_training_episodes"], 2)
        self.assertFalse(report["promotion"])
        self.assertEqual(tensor_digest(original), tensor_digest(self.model.state_dict()))
        self.assertTrue(all(torch.equal(v, student.state_dict()[k]) for k, v in original.items()
                            if not k.startswith("actor.")))
        self.assertTrue(any(not torch.equal(v, student.state_dict()[k]) for k, v in original.items()
                            if k.startswith("actor.")))
        for path in (self.root / "dagger" / "training").rglob("TRAJECTORY.json"):
            record = json.loads(path.read_text())
            self.assertTrue(record["planner_labels_collected"])
            self.assertEqual(record["strategy"], "greedy")
            self.assertEqual(record["failure"], None)
            self.assertEqual(len(record["outcome"]["artifact_sha256"]), 4)


if __name__ == "__main__":
    unittest.main()
