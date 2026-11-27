"""Actual serialized tensor format checks; generated values are not learning."""

import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from common import file_identity
from tensor_capacity import admit, tensor_file
from test_support import adapter, capacity, tensors


class Capacity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_r4_r8_and_two_cells_use_actual_tensor_sums(self):
        first = adapter(self.root, "r4a", 4)
        second = adapter(self.root, "r4b", 4)
        expanded = adapter(self.root, "r8", 8)
        self.assertEqual(
            [
                admit(capacity(items))["used"]["active_values"]
                for items in ([first], [expanded], [first, second])
            ],
            [230400, 460800, 460800],
        )
        with self.assertRaises(ValueError):
            admit(capacity([first, second], ceiling=230400))

    def test_parent_optimizer_gradient_and_base_separate_router_active(self):
        current = adapter(self.root, "active", 8)
        parent = adapter(self.root, "parent", 4)
        parent["role"] = "retained_parent"
        components = [current, parent]
        for role in ("optimizer", "gradient", "frozen_base", "active_router"):
            path = self.root / (role + ".safetensors")
            tensors(path, {role: ("F32", [5], 4)})
            components.append(
                {
                    "id": role,
                    "role": role,
                    "path": str(path),
                    "identity": file_identity(path),
                    "rank": None,
                    "targets": [],
                    "config": None,
                }
            )
        with self.assertRaises(ValueError):
            admit(capacity(components))
        report = admit(capacity(components, ceiling=460805))
        self.assertEqual(report["used"]["active_values"], 460805)
        self.assertEqual(
            {k: v["values"] for k, v in report["roles"].items()},
            {
                "active_adapter": 460800,
                "active_router": 5,
                "retained_parent": 230400,
                "optimizer": 5,
                "gradient": 5,
                "frozen_base": 5,
            },
        )

    def test_shared_file_does_not_reduce_two_logical_cells_capacity(self):
        first = adapter(self.root, "r4", 4)
        alias = copy.deepcopy(first)
        alias["id"] = "second-logical-cell"
        one = admit(capacity([first]))
        both = admit(capacity([first, alias]))
        self.assertEqual(
            both["used"]["active_values"], 2 * one["used"]["active_values"]
        )
        self.assertEqual(
            both["used"]["unique_checkpoint_bytes"],
            one["used"]["unique_checkpoint_bytes"],
        )

    def test_wrong_rank_config_or_checkpoint_pin_refused(self):
        entry = adapter(self.root, "r4", 4)
        entry["rank"] = 8
        with self.assertRaises(ValueError):
            admit(capacity([entry]))
        config = Path(entry["config"]["path"])
        raw = json.loads(config.read_bytes())
        raw["r"] = 8
        config.write_text(json.dumps(raw))
        entry["config"]["identity"] = file_identity(config)
        with self.assertRaises(ValueError):
            admit(capacity([entry]))
        checkpoint = Path(entry["path"])
        checkpoint.write_bytes(checkpoint.read_bytes() + b"x")
        with self.assertRaises(ValueError):
            tensor_file(checkpoint, entry["identity"])
        with self.assertRaises(ValueError):
            tensor_file(checkpoint, file_identity(checkpoint))

    def test_overlap_and_duplicate_json_keys_refused(self):
        path = self.root / "bad.safetensors"
        for header in (
            b'{"a":{"dtype":"F32","shape":[1],"data_offsets":[1,5]}}',
            b'{"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]},"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}',
        ):
            path.write_bytes(struct.pack("<Q", len(header)) + header + b"0000")
            with self.assertRaises(ValueError):
                tensor_file(path, file_identity(path))

    def test_symlink_checkpoint_refused(self):
        entry = adapter(self.root, "r4", 4)
        link = self.root / "link.safetensors"
        link.symlink_to(entry["path"])
        with self.assertRaises(ValueError):
            tensor_file(link, entry["identity"])

    def test_every_declared_target_must_appear(self):
        entry = adapter(self.root, "missing-target", 4)
        tensors(
            entry["path"],
            {
                "layer.0.q_proj.lora_A.weight": ("F32", [4, 576], 4),
                "layer.0.q_proj.lora_B.weight": ("F32", [576, 4], 4),
            },
        )
        entry["identity"] = file_identity(entry["path"])
        with self.assertRaises(ValueError):
            admit(capacity([entry]))
