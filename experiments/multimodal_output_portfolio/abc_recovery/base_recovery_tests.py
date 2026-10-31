"""Source-bound recovery and noninvasive progress regression tests."""

import unittest

import torch

from ..v6.data import SourceSplit
from ..v6.neural import parameter_hash
from ..v6.observer import fit_observer
from .base_recovery import fit_observer_progress, ids_sha, legacy_audit_ids


class RecoveryTests(unittest.TestCase):
    def test_legacy_half_requires_original_identity_and_disjoint_roles(self):
        ids = [f"source-{i}" for i in range(20)]
        manifest = {"split_seed": 7, "roles": {
            "excluded_v6_train": {"source_ids": ids}, "audit": {"source_ids": ["new-source"]}}}
        protocol = {"observer_sources": 8, "dataset_manifest": {"split_seed": 7, "splits": {
            "train": {"count": 2}, "validation": {"count": 2},
            "evaluator": {"count": 8, "identity_sha256": ids_sha(ids[4:12])}}}}
        expected = tuple(ids[8:12])
        self.assertEqual(legacy_audit_ids(manifest, protocol, ids_sha(expected)), expected)
        manifest["roles"]["audit"]["source_ids"] = [ids[8]]
        with self.assertRaisesRegex(ValueError, "overlaps"):
            legacy_audit_ids(manifest, protocol, ids_sha(expected))
        manifest["roles"]["audit"]["source_ids"] = ["new-source"]
        ids[4], ids[5] = ids[5], ids[4]
        with self.assertRaisesRegex(ValueError, "evaluator source"):
            legacy_audit_ids(manifest, protocol, ids_sha(expected))

    def test_progress_tracing_preserves_fitter_parameters_and_iterations(self):
        torch.set_num_threads(2)
        generator = torch.Generator().manual_seed(71)
        images = torch.randint(256, (125, 1, 28, 28), generator=generator, dtype=torch.uint8)
        labels = torch.randint(10, (125,), generator=generator)
        source = SourceSplit(images, labels, tuple(map(str, range(125))), tuple(map(str, range(125))))
        original, old_report = fit_observer(source, steps=3, seed=91)
        steps = []
        traced, new_report = fit_observer_progress(source, 3, 91, steps.append, interval=1)
        self.assertEqual(steps, [1, 2, 3])
        self.assertEqual(parameter_hash(original), parameter_hash(traced))
        self.assertEqual({k: v for k, v in old_report.items() if k != "wall_ns"},
                         {k: v for k, v in new_report.items() if k != "wall_ns"})


if __name__ == "__main__":
    unittest.main()
