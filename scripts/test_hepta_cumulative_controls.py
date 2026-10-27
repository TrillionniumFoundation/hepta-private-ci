#!/usr/bin/env python3
"""Synthetic metadata attack controls; these tests execute no model or training."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import hepta_cumulative_controls as controls


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ParentBindings(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = SimpleNamespace(
            file_sha=file_sha,
            identity=identity,
            read_json=lambda path: json.loads(Path(path).read_bytes()),
        )
        self.role = "budget-matched-full-tune"
        self.plan = dict(training_steps=10, recipes={self.role: dict(kind="full-tune")})
        self.contract = self.root / "target-contract.json"
        self.contract.write_text("synthetic test contract; not model material\n")
        history = []
        for number in (1, 2):
            path = self.root / str(number)
            path.mkdir()
            (path / "artifact.safetensors").write_bytes(
                b"synthetic non-tensor bytes" + bytes([number])
            )
            artifact = identity(number)
            metadata = dict(
                role=self.role,
                artifact=artifact,
                kind="full-tune",
                contract=controls.CONTRACT,
                experiment=identity(self.plan),
                file_sha256=file_sha(path / "artifact.safetensors"),
            )
            (path / "artifact.json").write_text(json.dumps(metadata))
            receipt = dict(
                outcome="success",
                role=self.role,
                experiment=identity(self.plan),
                training=dict(steps=10, tokens=526, supervised_tokens=40),
            )
            if number == 1:
                receipt.update(
                    schema="llm-runtime-actual-child-v1",
                    phase="train",
                    contract=controls.CONTRACT,
                    artifact=artifact,
                )
            else:
                receipt.update(
                    schema="hepta-cumulative-control-actual-v1",
                    round=number,
                    actual_parent_readback=identity(number - 1),
                    optimizer_reset_each_round=True,
                    authority=controls.NO_AUTHORITY,
                    artifact=metadata,
                )
            (path / "actual-receipt.json").write_text(json.dumps(receipt))
            self.parent = controls.parent_descriptor(
                path, self.contract, self.role, number, history, self.runtime
            )
            history = self.parent["history"]

    def check(self):
        controls.check_parent(self.parent, self.role, 2, self.runtime, self.plan)

    def test_receipts_supply_the_cumulative_counts(self):
        self.check()
        self.parent["cumulative_campaign"]["steps"] = 10
        with self.assertRaisesRegex(ValueError, "cumulative ledger"):
            self.check()

    def test_cross_role_parent_is_rejected(self):
        self.parent["role"] = "fresh-budget-matched-lora"
        with self.assertRaisesRegex(ValueError, "role/round"):
            self.check()

    def test_changed_checkpoint_is_rejected(self):
        (self.root / "2/artifact.safetensors").write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "material changed"):
            self.check()

    def test_changed_receipt_count_cannot_reuse_a_stale_ledger(self):
        entry = self.parent["history"][0]
        path = Path(entry["receipt_path"])
        receipt = json.loads(path.read_bytes())
        receipt["training"]["tokens"] += 1
        path.write_text(json.dumps(receipt))
        entry["receipt_sha256"] = file_sha(path)
        with self.assertRaisesRegex(ValueError, "measured training count"):
            self.check()

    def test_restarted_second_round_cannot_claim_parent_continuation(self):
        entry = self.parent["history"][1]
        path = Path(entry["receipt_path"])
        receipt = json.loads(path.read_bytes())
        receipt["actual_parent_readback"] = identity("different parent")
        path.write_text(json.dumps(receipt))
        entry["receipt_sha256"] = file_sha(path)
        with self.assertRaisesRegex(ValueError, "different parent"):
            self.check()


if __name__ == "__main__":
    unittest.main()
