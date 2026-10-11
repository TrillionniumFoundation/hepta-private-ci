"""Mandatory Torch CPU mechanism tests, NOT pretrained-model efficacy evidence.

Run explicitly so the existing dependency-free offline suite remains dependency
free. The dedicated workflow installs Torch and invokes this module; no skips.
"""
import os
from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn

from four_gate_capture import capture_cpu, tensor_digest
from four_gate_common import canonical, digest
from test_four_gate_fixtures import schedule_fixture


def toy_encoder():
    class Encoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.linear = nn.Linear(4, 8, bias=False)

        def forward(self, input_ids, attention_mask):
            return self.linear(input_ids.float())

    return Encoder().eval().requires_grad_(False)


def prepare(rows, arm):
    values = [[int(row["state_sha256"][:6], 16) % 7, 1,
               row["cell_id"] % 3 if arm != "feature_reuse" else 0, 1] for row in rows]
    ids = torch.tensor(values, dtype=torch.long)
    return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}


class CpuCaptureTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(7)
        torch.set_num_threads(1)
        self.model = toy_encoder()
        self.schedule = schedule_fixture(64, repeats=True)
        self.heads = {i: nn.Linear(8, 2).eval() for i in range(64)}

    def capture(self, arm="feature_reuse", **kwargs):
        return capture_cpu(self.model, prepare, lambda value: value,
                           self.heads, self.schedule, arm=arm,
                           pipeline_sha256=digest(["FIXTURE", arm]), **kwargs)

    def test_actual_forward_hooks_distinguish_batching_and_reuse(self):
        joint = self.capture("joint_batch")
        shared = self.capture()
        self.assertEqual(len(joint["encoder_forwards"]), 2)
        self.assertEqual(len(shared["encoder_forwards"]), 1)
        self.assertEqual(sum(len(e["keys"]) for e in joint["encoder_forwards"]), 64)
        self.assertEqual(sum(len(e["keys"]) for e in shared["encoder_forwards"]), 1)
        self.assertEqual(len(shared["requests"]), 64)
        self.assertGreater(shared["observed_inference_cost"]["cpu_ns"], 0)
        self.assertIsNone(shared["observed_inference_cost"]["energy_uj"])
        self.assertFalse(shared["native_worker_execution_authenticated"])
        self.assertFalse(shared["production_promotion_permitted"])

    def test_request_latency_includes_previous_batch_queueing(self):
        data = self.capture("joint_batch", max_batch_size=1)
        starts = {row["start_ns"] for row in data["requests"]}
        self.assertEqual(len(starts), 1)
        last = data["requests"][-1]
        self.assertGreater(last["end_ns"] - last["start_ns"],
                           data["encoder_forwards"][-1]["end_ns"] -
                           data["encoder_forwards"][-1]["start_ns"])
        self.assertEqual(data["arrival_policy"], "all_rows_queued_at_capture_start")

    def test_all_four_scales_physically_tick_every_toy_head(self):
        for n in (64, 256, 1024, 4096):
            with self.subTest(cells=n):
                self.schedule = schedule_fixture(n, repeats=True)
                self.heads = {i: nn.Linear(8, 2).eval() for i in range(n)}
                data = self.capture()
                self.assertEqual(len({r["cell_id"] for r in data["requests"]}), n)
                self.assertEqual(len(data["encoder_forwards"]), 1)
                self.assertTrue(all(r["outcome"] == "succeeded" for r in data["requests"]))

    def test_no_repeated_inputs_does_not_manufacture_savings(self):
        self.schedule = schedule_fixture(64, repeats=False)
        data = self.capture()
        self.assertEqual(sum(len(e["keys"]) for e in data["encoder_forwards"]), 64)

    def test_same_bytes_different_scope_reencode(self):
        for row in self.schedule[32:]:
            row["scope"] = "other-scope"
        self.assertEqual(len(self.capture()["encoder_forwards"]), 2)

    def test_generation_change_reencodes(self):
        for row in self.schedule[32:]:
            row["generation"] = 2
        self.assertEqual(len(self.capture()["encoder_forwards"]), 2)

    def test_aliased_cell_heads_rejected(self):
        self.heads[1] = self.heads[0]
        with self.assertRaisesRegex(ValueError, "alias"):
            self.capture()

    def test_unfrozen_encoder_rejected(self):
        self.model.requires_grad_(True)
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.capture()

    def test_invalid_pool_output_does_not_emit_success_and_removes_hooks(self):
        with self.assertRaisesRegex(ValueError, "pooled output"):
            capture_cpu(self.model, prepare, lambda value: value[:0], self.heads,
                        self.schedule, arm="feature_reuse", pipeline_sha256=digest("fixture"))
        self.assertEqual(len(self.model._forward_hooks), 0)
        self.assertEqual(len(self.model._forward_pre_hooks), 0)

    def test_actual_prequential_head_update_preserves_frozen_control(self):
        # Known synthetic linear task; weights really update, but no statement
        # about future Hepta outcomes or pretrained language ability follows.
        head = nn.Linear(2, 2)
        nn.init.zeros_(head.weight)
        nn.init.zeros_(head.bias)
        frozen = nn.Linear(2, 2)
        frozen.load_state_dict(head.state_dict())
        frozen.requires_grad_(False)
        before = tensor_digest(head.weight)
        optimizer = torch.optim.SGD(head.parameters(), lr=.2)
        feature = torch.tensor([[1., 0.], [0., 1.]])
        losses = []
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "prelabel.jsonl"
            with journal.open("xb") as stream:
                for event in range(32):
                    logits = head(feature)
                    probabilities = logits.detach().softmax(-1)
                    if event == 0:
                        self.assertTrue(torch.equal(logits.detach(), frozen(feature)))
                    record = {"fixture_event": event, "probabilities": probabilities.tolist(),
                              "preupdate_head_sha256": tensor_digest(head.weight)}
                    stream.write(canonical(record) + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                    # Revealed only after the pre-label journal write above.
                    labels = torch.tensor([0, 1])
                    loss = nn.functional.cross_entropy(logits, labels)
                    losses.append(loss.item())
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
            self.assertEqual(len(journal.read_bytes().splitlines()), 32)
        self.assertLess(losses[-1], losses[0])
        self.assertNotEqual(tensor_digest(head.weight), before)
        self.assertEqual(tensor_digest(frozen.weight), before)
        self.assertTrue(torch.equal(head(feature).argmax(-1), torch.tensor([0, 1])))


if __name__ == "__main__":
    unittest.main()
