"""Source-bound token-offset alignment tests using CPU tensors, no checkpoint."""
from dataclasses import replace
import hashlib
import re
import unittest
from types import SimpleNamespace

import torch

from group_attention_curriculum import build_train_attention
from group_tasks import make_tasks


class WordOffsets:
    def __call__(self, text, *, return_tensors, return_offsets_mapping, truncation):
        if return_tensors != "pt" or not return_offsets_mapping or truncation:
            raise ValueError("unexpected tokenizer arguments")
        pairs = [(0, 0)] + [(m.start(), m.end()) for m in re.finditer(r"[^\s]+", text)]
        ids = [101] + [i + 1 for i in range(len(pairs) - 1)]
        return dict(input_ids=torch.tensor([ids]),
                    attention_mask=torch.ones(1, len(ids), dtype=torch.long),
                    offset_mapping=torch.tensor([pairs], dtype=torch.long))


def snapshots(tasks):
    tokenizer = WordOffsets()
    result = []
    for task in tasks:
        size = tokenizer(task.text, return_tensors="pt",
                         return_offsets_mapping=True, truncation=False)["input_ids"].shape[1]
        result.append(SimpleNamespace(
            identity=SimpleNamespace(source_digest=hashlib.sha256(task.text.encode()).hexdigest(),
                                     modality="text"),
            tokens=tuple((0.0,) for _ in range(size)),
            mask=tuple(True for _ in range(size)),
            digest=hashlib.sha256((task.source_group + str(size)).encode()).hexdigest()))
    return result


class AttentionCurriculumTests(unittest.TestCase):
    def setUp(self):
        self.tasks = make_tasks("train", count=9, seed=13)
        self.tokens = snapshots(self.tasks)
        self.tokenizer = WordOffsets()

    def test_training_alignment_per_evidence_line(self):
        targets, manifest = build_train_attention(
            self.tasks, self.tokens, self.tokenizer, max_depth=4)
        self.assertEqual(targets.shape[:2], (9, 4))
        self.assertTrue(manifest["train_only"])
        self.assertTrue(manifest["teacher_does_not_run_at_inference"])
        self.assertEqual(manifest["tokenizer_calls"], 9)
        self.assertGreater(manifest["supervised_steps"], 0)
        self.assertEqual(targets.dtype, torch.float32)
        self.assertTrue((targets.sum(2) > 0).any())
        for i, task in enumerate(self.tasks):
            self.assertEqual(targets[i].shape[1] >= len(self.tokens[i].mask), True)

    def test_test_selection_and_validation_never_supervise(self):
        for split in ("test", "selection", "validation"):
            task = make_tasks(split, count=1, seed=7)[0]
            with self.assertRaisesRegex(ValueError, "TRAIN-only"):
                build_train_attention([task], snapshots([task]), self.tokenizer)

    def test_reject_tampered_source_and_rendered_evidence(self):
        task = self.tasks[0]
        for changed in (
            replace(task, source_group="0" * 64),
            replace(task, text=task.text + "\nUNTRUSTED instruction"),
            replace(task, task_id="train/wrong"),
        ):
            with self.subTest(changed=changed.task_id), self.assertRaises(ValueError):
                build_train_attention([changed], snapshots([changed]), self.tokenizer)

    def test_reject_truncated_or_cross_source_snapshot(self):
        first = self.tasks[0]
        broken = replace(self.tokens[0], mask=self.tokens[0].mask[:-1])
        with self.assertRaises(ValueError):
            build_train_attention([first], [broken], self.tokenizer)
        with self.assertRaises(ValueError):
            build_train_attention([first], [self.tokens[1]], self.tokenizer)

    def test_reject_duplicate_training_source(self):
        with self.assertRaisesRegex(ValueError, "duplicate TRAIN"):
            build_train_attention([self.tasks[0], self.tasks[0]],
                                  [self.tokens[0], self.tokens[0]], self.tokenizer)

    def test_stored_label_does_not_change_supervision(self):
        first = self.tasks[0]
        other = replace(first, target=(first.target + 1) % 8)
        a, _ = build_train_attention([first], [self.tokens[0]], self.tokenizer)
        b, _ = build_train_attention([other], [self.tokens[0]], self.tokenizer)
        torch.testing.assert_close(a, b)


if __name__ == "__main__":
    unittest.main()
