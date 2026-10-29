"""Synthetic C operational store checks, with no scientific imports or models."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from .architecture_run_v2 import store_type


class BaseStore:
    def __init__(self, root, work, **kwargs):
        self.arguments = (root, work, kwargs)
        self.checked = []

    def check(self, **kwargs):
        self.checked.append(kwargs)


class ArchitectureRunV2Tests(unittest.TestCase):
    def test_only_registered_storage_values_change(self):
        root = Path("/synthetic-attempt02")
        storage = SimpleNamespace(root=root, cap=2 * 1024**3, reserve=256 * 1024**2, check=Mock(), writer_lock=nullcontext)
        store = store_type(BaseStore, storage)(root / "stage_C", "synthetic work", raw_root=root)
        self.assertEqual(store.arguments, (root / "stage_C", "synthetic work", {
            "raw_root": root, "cap_bytes": 350 * 1024**2, "global_cap_bytes": 2 * 1024**3,
            "reserve_bytes": 256 * 1024**2, "cpu_limit": 43200, "wall_limit": 21600, "microstep_limit": 57536}))
        store.check(additional=17, failure_record=True)
        storage.check.assert_called_once_with(additional=17, c_training=True, check_memory=False)
        self.assertEqual(store.checked, [{"additional": 17, "failure_record": True}])

    def test_wrong_root_is_rejected_before_store_creation(self):
        storage = SimpleNamespace(root=Path("/synthetic-attempt02"), cap=1, reserve=1, check=Mock())
        with self.assertRaisesRegex(ValueError, "root differs"):
            store_type(BaseStore, storage)(Path("/wrong/stage_C"), None, raw_root="/wrong")
        storage.check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
