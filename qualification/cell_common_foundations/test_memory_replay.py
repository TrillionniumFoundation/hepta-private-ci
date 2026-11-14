from dataclasses import replace
import sys
import unittest
from unittest import mock

try:
    from .memory_replay import (
        ReplayPool,
        KINDS,
        make_item,
        raw_fingerprints,
        audit_replay_splits,
        replay_specs,
        run_replay_attempt,
    )
except ImportError:
    from memory_replay import (
        ReplayPool,
        KINDS,
        make_item,
        raw_fingerprints,
        audit_replay_splits,
        replay_specs,
        run_replay_attempt,
    )


class MemoryReplayTests(unittest.TestCase):
    def pool(self, capacity=32):
        pool = ReplayPool(
            "synthetic", dict.fromkeys(KINDS, "v1"), seed=4, capacity=capacity
        )
        for i in range(16):
            pool.add(make_item(11, i))
        return pool

    def test_scope_split_version_and_identity_rejections_are_atomic(self):
        pool = self.pool()
        before = pool.checkpoint()
        item = make_item(11, 0)
        for bad in (
            replace(item, split="holdout"),
            replace(item, scope="other"),
            replace(item, version="v2"),
            replace(item, priority=1),
        ):
            with self.assertRaises(ValueError):
                pool.add(bad)
            self.assertEqual(pool.checkpoint(), before)
        pool.add(item)
        self.assertEqual(pool.checkpoint(), before)

    def test_fifo_and_selection_budgets_bound_actual_whole_sequences(self):
        pool = self.pool(5)
        self.assertEqual(
            [e.item_id for e in pool.items],
            [make_item(11, i).item_id for i in range(11, 16)],
        )
        self.assertEqual(pool.select("uniform", 2, 7), [])
        selected = pool.select("uniform", 2, 8)
        self.assertEqual(len(selected), 1)
        self.assertEqual(pool.timesteps, 8)
        self.assertEqual(pool.presentations, 1)
        self.assertEqual(
            pool.numeric_payload_bytes,
            sum(a.nbytes for e in selected for a in e.arrays()),
        )

    def test_restore_preserves_next_random_selection_and_rejects_other_owner_context(
        self,
    ):
        pool = self.pool()
        pool.select("uniform")
        snapshot = pool.checkpoint()
        restored = ReplayPool.restore(snapshot, pool.scope, pool.versions)
        for _ in range(6):
            self.assertEqual(
                [x.item_id for x in pool.select("uniform")],
                [x.item_id for x in restored.select("uniform")],
            )
        self.assertEqual(pool.checkpoint(), restored.checkpoint())
        with self.assertRaises(ValueError):
            ReplayPool.restore(snapshot, "other", pool.versions)

    def test_version_change_evicts_and_error_priority_is_observed_data(self):
        pool = self.pool()
        pool.update_version("procedure", "v2")
        self.assertEqual(pool.select("procedure"), [])
        pool.add(make_item(11, 2, phase=1))
        self.assertEqual(pool.select("procedure")[0].version, "v2")
        item = replace(make_item(31, 3), priority=100.0)
        pool.add(item)
        self.assertEqual(pool.select("error_prioritized")[0].item_id, item.item_id)

    def test_error_stratum_uniform_selection_does_not_consume_priorities(self):
        low = ReplayPool("synthetic", dict.fromkeys(KINDS, "v1"), seed=11)
        high = ReplayPool("synthetic", dict.fromkeys(KINDS, "v1"), seed=11)
        for i in range(16):
            item = make_item(11, i)
            low.add(item)
            high.add(replace(item, priority=100.0 if i == 7 else 0.0))
        for _ in range(8):
            self.assertEqual(
                [e.item_id for e in low.select("error")],
                [e.item_id for e in high.select("error")],
            )
        self.assertEqual(
            high.select("error_prioritized")[0].item_id, make_item(11, 7).item_id
        )

    def test_items_do_not_alias_input_or_returned_arrays(self):
        item = make_item(11, 0)
        before = item.payload()
        item.arrays()[0][:] = 0
        self.assertEqual(item.payload(), before)

    def test_phase_and_split_rng_namespaces_do_not_reuse_raw_observations(self):
        for seed in (11, 29, 47):
            train = [make_item(seed + 800, i, 1, "train") for i in range(16)]
            probe = [make_item(seed + 1800, i, 0, "holdout") for i in range(16)]
            audit = audit_replay_splits(train, probe)
            self.assertTrue(audit["passed"])
            self.assertEqual(audit["cross_split_overlaps"]["input_message_sha256"], [])
            for split in ("train", "probe"):
                for kind in KINDS:
                    self.assertEqual(
                        audit["unique_input_payloads_by_kind"][split][kind], 4
                    )
        with self.assertRaises(ValueError):
            make_item(11, 0, split="test")

    def test_metadata_changes_cannot_hide_identical_raw_payloads(self):
        item = make_item(11, 0)
        relabeled = replace(item, item_id="different-id", split="holdout")
        self.assertEqual(raw_fingerprints(item), raw_fingerprints(relabeled))
        with self.assertRaisesRegex(ValueError, "raw-array overlap"):
            audit_replay_splits([item], [relabeled])
        x, y, f, m = relabeled.arrays()
        conflicting_label = replace(relabeled, episode=(x, -y, f, m))
        self.assertNotEqual(
            raw_fingerprints(item)["supervised_payload_sha256"],
            raw_fingerprints(conflicting_label)["supervised_payload_sha256"],
        )
        with self.assertRaisesRegex(ValueError, "raw-array overlap"):
            audit_replay_splits([item], [conflicting_label])

    def test_runtime_rejects_cross_split_duplicate_before_any_gradient(self):
        module = sys.modules[run_replay_attempt.__module__]

        def duplicated(seed, index, phase=0, split="train"):
            item = make_item(11, index, phase, "train")
            return replace(item, split=split, item_id=f"{split}:{phase}:{index}")

        with (
            mock.patch.object(module, "make_item", side_effect=duplicated),
            mock.patch.object(module, "gradient") as grad,
        ):
            with self.assertRaisesRegex(ValueError, "raw-array overlap"):
                run_replay_attempt(replay_specs((11,))[0])
            grad.assert_not_called()

    def test_attempts_execute_updates_and_keep_paired_data_and_label_budget(self):
        rows = [run_replay_attempt(s) for s in replay_specs((11,))]
        self.assertEqual(len({r["data_digest"] for r in rows}), 1)
        self.assertEqual(len({r["unique_supervision_events"] for r in rows}), 1)
        self.assertEqual(len({r["data_split_audit_digest"] for r in rows}), 1)
        self.assertTrue(all(r["data_split_audit"]["passed"] for r in rows))
        self.assertEqual(rows[0]["replay_presentations"], 0)
        self.assertEqual(rows[0]["total_label_exposures"], 32)
        self.assertEqual(rows[0]["replay_numeric_payload_bytes"], 0)
        for row in rows[1:]:
            self.assertEqual(row["replay_presentations"], 16)
            self.assertEqual(row["replay_timesteps"], 8 * row["replay_presentations"])
            self.assertEqual(row["total_label_exposures"], 48)
            self.assertEqual(row["total_label_exposures"], row["gradient_calls"])
            self.assertEqual(
                row["replay_numeric_payload_bytes"],
                sum(s["numeric_payload_bytes"] for s in row["replay_selections"]),
            )
            self.assertEqual(
                row["replay_numeric_payload_bytes"],
                row["replay_timesteps"]
                * sum(a.nbytes for a in make_item(11, 0).arrays())
                // 8,
            )
            self.assertNotEqual(row["initial_model_digest"], row["final_model_digest"])


if __name__ == "__main__":
    unittest.main()
