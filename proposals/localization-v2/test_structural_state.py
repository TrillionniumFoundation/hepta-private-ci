"""Actual CPU training-state continuity checks, not an S4 benefit experiment."""

import base64
import copy
import hashlib
import json
import unittest

import torch

from models import GRUModel
from structural_state import StateTransferError, capture, materialize, migrate
from scripts.ndu_real_runtime.organization_reference_artifacts import encoded


CONTRACT = hashlib.sha256(
    b"development GRU width3 CPU FP64 fresh episode v1"
).hexdigest()


def setup_model():
    model = GRUModel(3).double()
    model.register_buffer("zz_checkpoint_counter", torch.tensor(7, dtype=torch.int64))
    optimizer = torch.optim.AdamW(
        [
            {"params": list(model.core.parameters()), "lr": 0.003},
            {
                "params": list(model.head.parameters()),
                "lr": 0.009,
                "weight_decay": 0.02,
            },
        ],
        foreach=False,
    )
    return model, optimizer


def update(model, optimizer, x, dt):
    optimizer.zero_grad(set_to_none=True)
    logits = model(x, dt)
    loss = (logits - 0.25).square().mean()
    loss.backward()
    gradients = {n: p.grad.clone() for n, p in model.named_parameters()}
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    return logits.detach(), loss.detach(), gradients


class StructuralStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        torch.manual_seed(731)
        cls.model, cls.optimizer = setup_model()
        cls.x = torch.linspace(-1, 1, 200, dtype=torch.float64).reshape(2, 4, 25)
        cls.dt = torch.full((2, 4), 0.01, dtype=torch.float64)
        for _ in range(2):
            update(cls.model, cls.optimizer, cls.x, cls.dt)
        cls.captured = capture(cls.model, cls.optimizer, model_contract_sha256=CONTRACT)

    def assert_training_equal(self, left, right):
        torch.testing.assert_close(
            left[0].state_dict(), right[0].state_dict(), rtol=0, atol=0
        )
        for name, parameter in left[0].named_parameters():
            other = dict(right[0].named_parameters())[name]
            torch.testing.assert_close(
                left[1].state.get(parameter, {}),
                right[1].state.get(other, {}),
                rtol=0,
                atol=0,
            )

    def test_registered_gru_continues_exactly_across_each_operation(self):
        reference = copy.deepcopy((self.model, self.optimizer))
        expected = update(*reference, self.x, self.dt)
        original = self.captured["snapshot"]
        rng = torch.get_rng_state().clone()
        template_model = copy.deepcopy(self.model)
        # Reverse both group and parameter order: positional optimizer loading
        # would silently attach moments to the wrong named parameters.
        template_optimizer = torch.optim.AdamW(
            [
                {"params": list(reversed(list(template_model.head.parameters())))},
                {"params": list(reversed(list(template_model.core.parameters())))},
            ],
            foreach=False,
        )
        split = migrate(original, "split", expected_sha256=self.captured["sha256"])
        for operation in ("no_change", "split", "merge", "rewire"):
            with self.subTest(operation=operation):
                source = split if operation == "merge" else self.captured
                moved = migrate(
                    source["snapshot"], operation, expected_sha256=source["sha256"]
                )
                restored = materialize(
                    moved["snapshot"],
                    template_model,
                    template_optimizer,
                    expected_sha256=moved["sha256"],
                    model_contract_sha256=CONTRACT,
                )
                pair = restored["model"], restored["optimizer"]
                self.assert_training_equal((self.model, self.optimizer), pair)
                actual = update(*pair, self.x, self.dt)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                self.assert_training_equal(reference, pair)
                receipt = moved["receipt"]
                if operation in {"split", "merge"}:
                    self.assertEqual(len(receipt["lineage"]), len(original["manifest"]))
                    self.assertEqual(
                        receipt["tensor_payload_bytes_moved"],
                        sum(self.captured["receipt"]["tensor_payload_bytes"].values()),
                    )
                    self.assertTrue(
                        all(
                            row["from_owner"] != row["to_owner"]
                            for row in receipt["lineage"]
                        )
                    )
                else:
                    self.assertEqual(receipt["lineage"], [])
                    self.assertEqual(receipt["tensor_payload_bytes_moved"], 0)
                    self.assertEqual(
                        moved["snapshot"]["state"]["states"],
                        original["state"]["states"],
                    )
                if operation == "rewire":
                    self.assertEqual(
                        moved["snapshot"]["graph"]["edges"],
                        [["general", "recovery"], ["recovery", "general"]],
                    )
                self.assertIsNone(receipt["physical_transferred_bytes"])
        torch.testing.assert_close(torch.get_rng_state(), rng, rtol=0, atol=0)
        self.assertEqual(
            hashlib.sha256(encoded(original)).hexdigest(), self.captured["sha256"]
        )
        self.assertEqual(len(template_optimizer.state), 0)

    def test_interrupted_partial_transfers_keep_bytes_and_source_ownership(self):
        split = migrate(
            self.captured["snapshot"], "split", expected_sha256=self.captured["sha256"]
        )
        for operation in ("split", "merge", "rewire"):
            source = split if operation == "merge" else self.captured
            before = encoded(source["snapshot"])
            with self.assertRaises(StateTransferError) as caught:
                migrate(
                    source["snapshot"],
                    operation,
                    expected_sha256=source["sha256"],
                    interrupt_after_persist=True,
                )
            receipt = caught.exception.receipt
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["operation"], operation)
            self.assertEqual(len(receipt["checkpoints"]), 1)
            self.assertGreater(receipt["json_bytes_serialized"], len(before))
            self.assertGreater(receipt["cpu_seconds"], 0)
            self.assertGreater(receipt["wall_seconds"], 0)
            self.assertEqual(encoded(source["snapshot"]), before)
            self.assertEqual(len(receipt["lineage"]), 0 if operation == "rewire" else 1)
            partial = json.loads(receipt["checkpoints"][0]["state_json"])
            keys = [
                key
                for state in partial["states"].values()
                for key in state.get("records", {})
            ]
            self.assertEqual(sorted(keys), sorted(source["snapshot"]["manifest"]))
            self.assertEqual(len(keys), len(set(keys)))

    def test_uninitialized_adam_state_and_buffer_roundtrip(self):
        model, optimizer = setup_model()
        source = capture(model, optimizer, model_contract_sha256=CONTRACT)
        self.assertEqual(source["receipt"]["tensor_payload_bytes"]["optimizer"], 0)
        self.assertEqual(source["receipt"]["tensor_payload_bytes"]["buffer"], 8)
        moved = migrate(source["snapshot"], "split", expected_sha256=source["sha256"])
        restored = materialize(
            moved["snapshot"],
            model,
            optimizer,
            expected_sha256=moved["sha256"],
            model_contract_sha256=CONTRACT,
        )
        self.assertEqual(len(restored["optimizer"].state), 0)
        expected = update(model, optimizer, self.x, self.dt)
        actual = update(restored["model"], restored["optimizer"], self.x, self.dt)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assert_training_equal(
            (model, optimizer), (restored["model"], restored["optimizer"])
        )

    def test_identity_graph_and_optimizer_contract_errors_do_not_install(self):
        original = self.captured["snapshot"]
        changed = copy.deepcopy(original)
        changed["graph"]["edges"].append(["recovery", "absent"])
        with self.assertRaises(StateTransferError):
            migrate(
                changed,
                "rewire",
                expected_sha256=hashlib.sha256(encoded(changed)).hexdigest(),
            )
        with self.assertRaises(StateTransferError) as caught:
            migrate(original, "split", expected_sha256="0" * 64)
        self.assertGreater(caught.exception.receipt["json_bytes_serialized"], 0)
        changed = copy.deepcopy(original)
        record = next(iter(changed["state"]["states"]["general"]["records"].values()))
        record["archive"] = base64.b64encode(b"changed").decode()
        with self.assertRaises(StateTransferError):
            migrate(
                changed,
                "split",
                expected_sha256=hashlib.sha256(encoded(changed)).hexdigest(),
            )
        model = copy.deepcopy(self.model)
        one_group = torch.optim.AdamW(model.parameters())
        with self.assertRaises(StateTransferError):
            materialize(
                original,
                model,
                one_group,
                expected_sha256=self.captured["sha256"],
                model_contract_sha256=CONTRACT,
            )
        torch.testing.assert_close(
            self.model.state_dict(), model.state_dict(), rtol=0, atol=0
        )
        self.assertEqual(len(one_group.state), 0)
        self.assertEqual(
            hashlib.sha256(encoded(original)).hexdigest(), self.captured["sha256"]
        )

    def test_capture_rejects_pending_gradients_and_shared_parameter_storage(self):
        model, optimizer = copy.deepcopy((self.model, self.optimizer))
        model(self.x, self.dt).sum().backward()
        with self.assertRaisesRegex(StateTransferError, "cleared-gradient"):
            capture(model, optimizer, model_contract_sha256=CONTRACT)
        optimizer.zero_grad(set_to_none=True)
        model.alias = model.head.weight
        with self.assertRaisesRegex(StateTransferError, "untied"):
            capture(model, optimizer, model_contract_sha256=CONTRACT)
        model, optimizer = copy.deepcopy((self.model, self.optimizer))
        removed = model.core.weight_ih_l0
        removed.requires_grad_(False)
        optimizer.param_groups[0]["params"] = [
            p for p in optimizer.param_groups[0]["params"] if p is not removed
        ]
        self.assertIn(removed, optimizer.state)
        with self.assertRaisesRegex(StateTransferError, "unowned state"):
            capture(model, optimizer, model_contract_sha256=CONTRACT)


if __name__ == "__main__":
    unittest.main()
