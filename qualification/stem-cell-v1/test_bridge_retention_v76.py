"""Isolated V7 historical contract and cross-generation uncertainty tests."""
import math
from pathlib import Path
import tempfile
import unittest

from bridge_original_effect_v76 import (
    SEEDS, score, validate_natural, _parts_by_source, _f1_counts, demand,
)
from bridge_retention_v76 import (
    ARMS_V7, V7_SHA256, v7_bytes, compare_two_generations,
)
from test_bridge_original_effect_v76 import original_shape_fixture


class FrozenV7Contracts(unittest.TestCase):
    def test_exact_v7_identity_and_four_archetypes(self):
        self.assertEqual(len(V7_SHA256),64)
        self.assertEqual(set(ARMS_V7),{"repeat","diverse","anchored","low_lr"})
        self.assertEqual(SEEDS,(41,47,53))

    def test_zip_bytes_missing_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"wrong.zip"
            p.write_bytes(b"not original v7 bytes")
            with self.assertRaises(ValueError):
                v7_bytes(p)
            p2=Path(root)/"alias.zip"
            p2.symlink_to(p)
            with self.assertRaisesRegex(ValueError,"symlink"):
                v7_bytes(p2)

    def test_full_pooled_f1_for_mixed_repeat_labels(self):
        rows=original_shape_fixture()
        v=[float(row["label"]) for row in rows]
        score_all=score(rows,v)
        self.assertEqual(score_all["f1_a"],1.)
        src=validate_natural(rows)
        s=_parts_by_source(rows,v,src)
        counts=tuple(sum(s[g][i] for g in src["groups"]) for i in range(3))
        self.assertEqual(_f1_counts(counts),1.)
        # Bootstrap must treat repeated seeds as correlated over the *same*
        # sixteen source blocks, not 48 independent source observations.
        self.assertEqual(len(src["groups"]),16)

    def test_non_future_and_hard_denial_shape(self):
        self.assertTrue(all(a not in {"production", "final", "heldout"} for a in ARMS_V7))
        rows=original_shape_fixture()
        self.assertTrue(all(r["source_split"]=="train" for r in rows))
        with self.assertRaises(ValueError):
            demand(False,"no production efficacy or authority from original TRAIN panel")

    def test_v7_requires_real_two_generation_archives(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"not-v6"
            q=Path(root)/"not-v7"
            p.write_bytes(b"first")
            q.write_bytes(b"second")
            with self.assertRaises(ValueError):
                compare_two_generations(p,q,replicates=100)
            with self.assertRaisesRegex(ValueError,"bounded"):
                compare_two_generations(p,q,replicates=0)


if __name__=="__main__":
    unittest.main()
