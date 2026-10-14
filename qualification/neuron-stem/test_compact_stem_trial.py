"""Offline, model-weight-free contract tests for strict compact Stem trial."""
import copy
import unittest
from types import SimpleNamespace

from compact_stem_trial import (
    STEMS, FrozenCompactStem, choose_task_rows, pool_states, render_joint,
    validate_profile, weights_digest,
)
from hf_trial import make_head


def cases():
    result = []
    parts = ("train", "train", "calibration", "test", "future", "ood")
    for i, part in enumerate(parts):
        result.append({"case_id": f"case-{i}", "group_id": f"group-{i}",
                       "scope_id": "demo-scope", "task_id": "classify-v1",
                       "split": part, "language": ("zh", "en", "cross")[i % 3],
                       "state": f"independent distinct source {part} {i}",
                       "question": f"Decide item {i}", "options": ["false", "true"],
                       "label": i % 2, "event_time": f"2026-0{i + 1}-01T09:00:00Z"})
    return result


class ContractTests(unittest.TestCase):
    def test_two_models_and_q24_dimension_are_preregistered(self):
        self.assertEqual(set(STEMS), {"mmbert-small", "granite-97m-multilingual-r2"})
        self.assertEqual({s.width for s in STEMS.values()}, {384})
        self.assertEqual(STEMS["granite-97m-multilingual-r2"].pooling, "cls_l2")
        self.assertEqual(STEMS["mmbert-small"].pooling, "masked_mean_l2")
        self.assertEqual(STEMS["mmbert-small"].license, "MIT")

    def test_no_arbitrary_or_unpinned_model(self):
        for name, rev, tokens in (
            ("unauthorized", "a" * 40, 512),
            ("mmbert-small", "main", 512),
            ("granite-97m-multilingual-r2", "A" * 40, 512),
            ("granite-97m-multilingual-r2", "a" * 40, 513),
            ("granite-97m-multilingual-r2", "a" * 40, 0),
        ):
            with self.subTest(model=name, revision=rev[:8], window=tokens), self.assertRaises(ValueError):
                validate_profile(name, rev, tokens)
        self.assertEqual(validate_profile("mmbert-small", "a" * 40, 512).width, 384)

    def test_model_validate_before_torch_load(self):
        with self.assertRaises(ValueError):
            FrozenCompactStem("granite-97m-multilingual-r2", "moving-main")

    def test_joint_and_group_frozen_training_subset(self):
        dataset = cases()
        self.assertIn("Question: Decide item 0", render_joint(dataset[0]))
        self.assertIn("Options: 0: false | 1: true", render_joint(dataset[0]))
        task, chosen, audit = choose_task_rows(dataset, "classify-v1", 2, 11)
        self.assertEqual(len(task), 6)
        self.assertEqual({r["case_id"] for r in chosen}, {"case-0", "case-1"})
        self.assertEqual(audit["cases"], 6)
        self.assertEqual(choose_task_rows(dataset, "classify-v1", 2, 11)[1], chosen)
        with self.assertRaisesRegex(ValueError, "insufficient independent train groups"):
            choose_task_rows(dataset, "classify-v1", 3, 11)
        with self.assertRaises(ValueError):
            choose_task_rows(dataset[:-1], "classify-v1", 2, 11)
        drift = copy.deepcopy(dataset)
        drift[3]["group_id"] = drift[0]["group_id"]
        with self.assertRaisesRegex(ValueError, "group leakage"):
            choose_task_rows(drift, "classify-v1", 2, 11)

    def test_cross_scope_training_is_denied(self):
        rows = cases()
        rows[1]["scope_id"] = "foreign-scope"
        with self.assertRaisesRegex(ValueError, "spans multiple scopes"):
            choose_task_rows(rows, "classify-v1", 1, 11)
        with self.assertRaisesRegex(ValueError, "requires all five"):
            choose_task_rows(rows, "classify-v1", 1, 11, "foreign-scope")

    def test_published_cls_is_not_accidental_mean(self):
        import torch
        x = torch.zeros((1, 3, 384), dtype=torch.float32)
        x[0, 0, 0] = 3
        x[0, 1, 1] = 4
        x[0, 2, 2] = 5  # masked padding must not contribute
        mask = torch.tensor([[1, 1, 0]])
        model_output = SimpleNamespace(last_hidden_state=x)
        cls = pool_states(torch, model_output, mask, "cls_l2")
        mean = pool_states(torch, model_output, mask, "masked_mean_l2")
        self.assertEqual(torch.argmax(cls).item(), 0)
        self.assertGreater(mean[1].item(), mean[0].item())
        self.assertEqual(mean[2].item(), 0.0)
        self.assertAlmostEqual(torch.linalg.vector_norm(cls).item(), 1, places=6)
        self.assertAlmostEqual(torch.linalg.vector_norm(mean).item(), 1, places=6)
        with self.assertRaisesRegex(ValueError, "unregistered pooling"):
            pool_states(torch, model_output, mask, "raw_mean")

    def test_reject_invalid_feature_and_mask(self):
        import torch
        state = torch.ones((1, 3, 384))
        with self.assertRaisesRegex(ValueError, "mask"):
            pool_states(torch, SimpleNamespace(last_hidden_state=state),
                        torch.zeros((1, 3)), "cls_l2")
        with self.assertRaisesRegex(ValueError, "feature"):
            pool_states(torch, SimpleNamespace(last_hidden_state=torch.zeros_like(state)),
                        torch.ones((1, 3)), "cls_l2")
        with self.assertRaisesRegex(ValueError, "hidden width"):
            pool_states(torch, SimpleNamespace(last_hidden_state=torch.ones((1, 3, 385))),
                        torch.ones((1, 3)), "cls_l2")
        state[0, 0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "feature"):
            pool_states(torch, SimpleNamespace(last_hidden_state=state),
                        torch.ones((1, 3)), "cls_l2")

    def test_all_trainable_parameters_fit_complete_budget(self):
        import torch
        from torch import nn
        for name in ("linear", "film", "rank8"):
            for ceiling in (2048, 8192, 16384):
                with self.subTest(head=name, ceiling=ceiling):
                    try:
                        head, count = make_head(torch, nn, name, 384, 2, ceiling)
                    except ValueError:
                        continue
                    self.assertEqual(count, sum(p.numel() for p in head.parameters() if p.requires_grad))
                    self.assertLessEqual(count, ceiling)
                    self.assertEqual(len(weights_digest(head)), 64)
        head, count = make_head(torch, nn, "film", 384, 2, 2048)
        self.assertEqual(count, 1538)


if __name__ == "__main__":
    unittest.main()
