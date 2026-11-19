"""Small stdlib-only provenance/time-gate regressions; no scientific execution."""

import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from .evidence_guard import (account_identity, archive_members, canonical, compare_scientific_parent,
                             digest, pinned, registration, require, tool_object, verify_budget_record)


def budget_fixture():
    reg = registration()
    checkpoint = b"control fixture only; not a model checkpoint"
    result = dict(status="completed", device="cpu", optimizer_updates_completed=400, updates_registered=400,
                  state_count=81, expected_parameter_count=2890, sequence_length=64, batch_size=64,
                  data_seed=931117, initialization_seed=931119, validation_seed=931123, batch_order_seed=931127,
                  learning_rate=.003, formal_training_fits=0, task_datasets_read=False, task_gain_established=False,
                  wall_seconds=100., within_480_second_probe_window=True,
                  source_pins=reg["external_budget"]["probe_source_pins"], bundle_sha256=reg["bundle_sha256"],
                  bundle_metadata_sha256=reg["bundle_metadata_sha256"], environment=reg["cpu_execution_environment"],
                  validation=dict(count=512), checkpoint_sha256=digest(checkpoint))
    stage = dict(returncode=0, timed_out=False, timeout_seconds=540, child_wait_completed=True,
                 owned_process_group_alive=False, worker_children_stopped=True, pid=123, pgid=123)
    rows = [dict(event="non_task_optimizer_update_completed", update=i, examples=64) for i in range(1, 401)]
    rows += [dict(event="evaluation_batch_completed", phase="non_task_validation", count=64, cumulative_examples=i)
             for i in range(64, 513, 64)]
    rows += [dict(event="non_task_probe_terminal", status="completed")]
    return reg, result, stage, rows, checkpoint


def encoded(rows):
    return b"".join(canonical(row) + b"\n" for row in rows)


class CpuControlTests(unittest.TestCase):
    def test_complete_409_row_fixture_preserves_other_events(self):
        reg, result, stage, rows, checkpoint = budget_fixture()
        self.assertEqual(len(rows), 409)
        verify_budget_record(result, stage, encoded(rows), checkpoint, reg)

    def test_exact_450_and_changed_checkpoint_rejected(self):
        reg, result, stage, rows, checkpoint = budget_fixture()
        result["wall_seconds"] = 450.
        with self.assertRaisesRegex(ValueError, "time gate"):
            verify_budget_record(result, stage, encoded(rows), checkpoint, reg)
        result["wall_seconds"] = 449.999
        verify_budget_record(result, stage, encoded(rows), checkpoint, reg)
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            verify_budget_record(result, stage, encoded(rows), checkpoint + b"changed", reg)

    def test_missing_duplicate_update_and_validation_gap_rejected(self):
        reg, result, stage, rows, checkpoint = budget_fixture()
        variants = [rows[1:], copy.deepcopy(rows), copy.deepcopy(rows)]
        variants[1][2]["update"] = 2
        variants[2][-2]["cumulative_examples"] = 511
        for variant in variants:
            with self.subTest(kind=variant[-2]):
                with self.assertRaises(ValueError):
                    verify_budget_record(result, stage, encoded(variant), checkpoint, reg)

    def test_foreign_environment_and_live_child_rejected(self):
        reg, result, stage, rows, checkpoint = budget_fixture()
        changed = copy.deepcopy(result)
        changed["environment"]["cpu_threads"] = 2
        with self.assertRaisesRegex(ValueError, "environment"):
            verify_budget_record(changed, stage, encoded(rows), checkpoint, reg)
        stage["owned_process_group_alive"] = True
        with self.assertRaisesRegex(ValueError, "stopped"):
            verify_budget_record(result, stage, encoded(rows), checkpoint, reg)

    def test_auth_expiry_refresh_preserves_identity_but_new_user_does_not(self):
        first = dict(authenticated=True, username="fixture", user_id=1, method="oauth",
                     verification="official_token_introspection", scope="resources.admin:*", expires_unix=1.)
        refreshed = dict(first, expires_unix=2.)
        self.assertEqual(account_identity(first), account_identity(refreshed))
        changed = dict(refreshed, user_id=2)
        with self.assertRaises(ValueError):
            require(account_identity(first) == account_identity(changed), "Foreign provider account")
        with self.assertRaises(ValueError):
            account_identity(dict(first, authenticated=False))

    def test_archive_traversal_and_duplicate_members_rejected(self):
        for names in (("../foreign.json",), ("evidence/value.json", "evidence/value.json")):
            buffer = io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(buffer, "w") as archive:
                    for name in names:
                        archive.writestr(name, b"{}")
            with self.assertRaises(ValueError):
                archive_members(buffer.getvalue())

    def test_scientific_and_remaining_budget_changes_rejected(self):
        parent = dict(study_id="parent", train_updates=400, training_seeds=[1, 2, 3, 4],
                      runtime_feasibility_policy=dict(provider="colab", execution_gpu_index=0,
                                                      minimum_remaining_before_operation_seconds=720))
        child = dict(parent, study_id="child", runtime_feasibility_policy=dict(
            parent["runtime_feasibility_policy"], provider="kaggle", execution_gpu_index=None))
        compare_scientific_parent(parent, child)
        with self.assertRaises(ValueError):
            compare_scientific_parent(parent, dict(child, train_updates=399))
        changed = copy.deepcopy(child)
        changed["runtime_feasibility_policy"]["minimum_remaining_before_operation_seconds"] = 719
        with self.assertRaises(ValueError):
            compare_scientific_parent(parent, changed)

    def test_real_atime_read_allowed_but_changed_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "proof.json"
            target.write_bytes(b"{}\n")
            os.utime(target, ns=(1, target.stat().st_mtime_ns))
            pin = dict(path="proof.json", bytes=3, sha256=digest(b"{}\n"))
            self.assertEqual(pinned(root, pin), b"{}\n")
            target.write_bytes(b"[]\n")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                pinned(root, pin)

    def test_native_readback_text_is_not_a_nested_tool_envelope(self):
        nested = {}
        for _ in range(20):
            nested = {"observer_data": nested}
        snapshot = dict(snapshot_scope="actual readback", files=[dict(text=json.dumps(nested))])
        envelope = dict(content=[dict(type="text", text=json.dumps(snapshot))])
        predicate = lambda x: isinstance(x.get("files"), list) and "snapshot_scope" in x
        self.assertEqual(tool_object(envelope, predicate), snapshot)
        envelope["content"].append(dict(type="text", text=json.dumps(dict(snapshot, snapshot_scope="foreign"))))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            tool_object(envelope, predicate)


if __name__ == "__main__":
    unittest.main()
