"""Synthetic persistence, fresh-process continuation and fail-closed controls."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np

from cell_learning_models import canonical
from cell_optimizer_checkpoint import (file_sha, load_optimizer_checkpoint,
                                       save_optimizer_checkpoint, layout, MAX_BYTES)
from cell_resumable_training import ResumableMicrobatchAdam, array_sha
from test_cell_resumable_training import fixture


def save(owner, path):
    return save_optimizer_checkpoint(owner, path, expected_plan_sha256=owner.plan_sha256)


def load(path, receipt, **extra):
    return load_optimizer_checkpoint(path, expected_manifest_sha256=receipt["manifest_sha256"],
        expected_plan_sha256=receipt["plan_sha256"], expected_input_sha256=receipt["input_sha256"], **extra)


def reseal(path, receipt, meta):
    meta["archive_sha256"] = file_sha(path/"state.npz")
    meta["archive_bytes"] = (path/"state.npz").stat().st_size
    (path/"checkpoint.json").write_bytes(canonical(meta)+b"\n")
    return {**receipt, "manifest_sha256": file_sha(path/"checkpoint.json")}


class OptimizerCheckpointTests(unittest.TestCase):
    def test_restart_at_initial_midblock_boundary_and_final_all_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("linear", "gated", "residual"):
                args, options = fixture(mode)
                full = ResumableMicrobatchAdam(*args, **options)
                full.advance(expected_plan_sha256=full.plan_sha256)
                for cut in (0, 1, 5, 8, 14, 15):
                    with self.subTest(mode=mode, cut=cut):
                        split = ResumableMicrobatchAdam(*args, **options)
                        split.advance(cut, expected_plan_sha256=split.plan_sha256)
                        path = Path(directory)/f"{mode}-{cut}"
                        receipt = save(split, path)
                        restored = load(path, receipt)
                        restored.advance(expected_plan_sha256=restored.plan_sha256)
                        self.assertEqual(full.progress(), restored.progress())
                        for name, value in full.snapshot()[1].items():
                            np.testing.assert_array_equal(value, restored.snapshot()[1][name])

    def test_fresh_process_restores_without_original_in_memory_inputs(self):
        args, options = fixture()
        full, split = (ResumableMicrobatchAdam(*args, **options) for _ in range(2))
        full.advance(expected_plan_sha256=full.plan_sha256)
        split.advance(7, expected_plan_sha256=split.plan_sha256)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint, final = Path(directory)/"partial", Path(directory)/"final"
            receipt = save(split, checkpoint)
            code = ("import json,sys; from cell_optimizer_checkpoint import load_optimizer_checkpoint,save_optimizer_checkpoint; "
                "r=json.loads(sys.argv[2]); s=load_optimizer_checkpoint(sys.argv[1],expected_manifest_sha256=r['manifest_sha256'],"
                "expected_plan_sha256=r['plan_sha256'],expected_input_sha256=r['input_sha256']); "
                "s.advance(expected_plan_sha256=s.plan_sha256); print(json.dumps(save_optimizer_checkpoint(s,sys.argv[3],"
                "expected_plan_sha256=s.plan_sha256)))")
            child = subprocess.run([sys.executable, "-c", code, str(checkpoint), json.dumps(receipt), str(final)],
                check=True, capture_output=True, text=True, timeout=30)
            restored = load(final, json.loads(child.stdout))
            self.assertEqual(full.progress(), restored.progress())
            for name, value in full.snapshot()[1].items():
                np.testing.assert_array_equal(value, restored.snapshot()[1][name])

    def test_zeroing_moments_changes_the_resumed_trajectory(self):
        args, options = fixture()
        part = ResumableMicrobatchAdam(*args, **options)
        part.advance(3, expected_plan_sha256=part.plan_sha256)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"checkpoint"
            receipt = save(part, path)
            correct, reset = (load(path, receipt) for _ in range(2))
            for value in (*reset._core._m.values(), *reset._core._v.values()): value[:] = 0
            correct.advance(expected_plan_sha256=correct.plan_sha256)
            reset.advance(expected_plan_sha256=reset.plan_sha256)
            self.assertNotEqual(correct.progress()["trajectory_sha256"], reset.progress()["trajectory_sha256"])
            self.assertFalse(np.array_equal(correct.snapshot()[1]["p_W"], reset.snapshot()[1]["p_W"]))

    def test_external_pins_and_restore_budget_fail_before_np_load(self):
        args, options = fixture()
        owner = ResumableMicrobatchAdam(*args, **options)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"checkpoint"
            receipt = save(owner, path)
            for key in ("manifest_sha256", "plan_sha256", "input_sha256"):
                with self.subTest(key=key), mock.patch("cell_optimizer_checkpoint.np.load") as numeric:
                    with self.assertRaises(ValueError): load(path, {**receipt, key: "0"*64})
                    numeric.assert_not_called()
            with mock.patch("cell_optimizer_checkpoint.np.load") as numeric:
                with self.assertRaises(ValueError): load(path, receipt, max_restore_tensor_bytes=4096)
                numeric.assert_not_called()

    def test_hostile_npy_header_rejected_before_numeric_allocation(self):
        args, options = fixture()
        owner = ResumableMicrobatchAdam(*args, **options)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"checkpoint"
            receipt = save(owner, path)
            meta = json.loads((path/"checkpoint.json").read_bytes())
            with zipfile.ZipFile(path/"state.npz") as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            hostile = io.BytesIO()
            np.lib.format.write_array_header_1_0(hostile,
                {"descr": "<f8", "fortran_order": False, "shape": (10**12, 7, 2)})
            members["p_W.npy"] = hostile.getvalue()
            with zipfile.ZipFile(path/"state.npz", "w") as archive:
                for name, value in members.items(): archive.writestr(name, value)
            receipt = reseal(path, receipt, meta)
            with mock.patch("cell_optimizer_checkpoint.np.load") as numeric:
                with self.assertRaises(ValueError): load(path, receipt)
                numeric.assert_not_called()

    def test_population_and_total_payload_guards_precede_np_load(self):
        args, options = fixture()
        owner = ResumableMicrobatchAdam(*args, **options)
        with tempfile.TemporaryDirectory() as directory:
            for count, width, classes, message in ((1025, 7, 2, "populations"), (1024, 4096, 128, "uncompressed")):
                path = Path(directory)/str(count)
                receipt = save(owner, path)
                meta = json.loads((path/"checkpoint.json").read_bytes())
                plan, inputs = meta["plan"], meta["plan"]["inputs"]
                inputs["cell_ids"], inputs["cell_tasks"] = [f"cell-{i}" for i in range(count)], ["task"]*count
                inputs["arrays"]["labels"]["shape"] = [count, 6]
                for key in ("raw", "normalized"): inputs["arrays"][key]["shape"] = [6, width]
                plan["model"].update(width=width, classes=classes, initial_parameter_digests=["a"*64]*count)
                plan["limits"]["max_parameters"] = 1000000
                plan["input_sha256"] = hashlib.sha256(canonical(inputs)).hexdigest()
                meta["plan_sha256"] = hashlib.sha256(canonical(plan)).hexdigest()
                receipt.update(input_sha256=plan["input_sha256"], plan_sha256=meta["plan_sha256"])
                receipt = reseal(path, receipt, meta)
                with mock.patch("cell_optimizer_checkpoint.np.load") as numeric:
                    with self.assertRaisesRegex(ValueError, message): load(path, receipt)
                    numeric.assert_not_called()

    def test_step_vector_and_negative_variance_rejected(self):
        args, options = fixture()
        owner = ResumableMicrobatchAdam(*args, **options)
        owner.advance(1, expected_plan_sha256=owner.plan_sha256)
        with tempfile.TemporaryDirectory() as directory:
            for changed in ("steps", "v_W"):
                path = Path(directory)/changed
                receipt = save(owner, path)
                meta = json.loads((path/"checkpoint.json").read_bytes())
                with np.load(path/"state.npz", allow_pickle=False) as archive:
                    arrays = {name: archive[name] for name in archive.files}
                arrays[changed].flat[0] = 0 if changed == "steps" else -1
                np.savez_compressed(path/"state.npz", **arrays)
                meta["arrays"][changed]["sha256"] = array_sha(arrays[changed])
                with self.assertRaises(ValueError): load(path, reseal(path, receipt, meta))

    def test_unvisited_parameters_cannot_rebind_the_original_initial_state(self):
        args, options = fixture()
        with tempfile.TemporaryDirectory() as directory:
            for cursor, index in ((0, 0), (1, 2)):
                owner = ResumableMicrobatchAdam(*args, **options)
                owner.advance(cursor, expected_plan_sha256=owner.plan_sha256)
                path = Path(directory)/str(cursor)
                receipt = save(owner, path)
                meta = json.loads((path/"checkpoint.json").read_bytes())
                with np.load(path/"state.npz", allow_pickle=False) as archive:
                    arrays = {name: archive[name] for name in archive.files}
                arrays["p_W"][index, 0, 0] += .1
                np.savez_compressed(path/"state.npz", **arrays)
                meta["arrays"]["p_W"]["sha256"] = array_sha(arrays["p_W"])
                with self.assertRaisesRegex(ValueError, "unvisited Cell"):
                    load(path, reseal(path, receipt, meta))

    def test_unrestorable_checkpoint_rejected_before_snapshot_or_directory(self):
        args, options = fixture()
        owner = ResumableMicrobatchAdam(*args, **options)
        expected, total, _ = layout(owner.plan)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"checkpoint"
            with mock.patch("cell_optimizer_checkpoint.layout", return_value=(expected, total, MAX_BYTES+1)):
                with mock.patch.object(owner, "snapshot") as snapshot:
                    with self.assertRaisesRegex(ValueError, "cannot be restored"): save(owner, path)
                    snapshot.assert_not_called()
            self.assertFalse(path.exists())

    def test_links_partial_files_and_overwrite_rejected(self):
        args, options = fixture()
        owner = ResumableMicrobatchAdam(*args, **options)
        with tempfile.TemporaryDirectory() as directory:
            path, alias = Path(directory)/"checkpoint", Path(directory)/"alias"
            receipt = save(owner, path)
            with self.assertRaises(ValueError): save(owner, path)
            alias.symlink_to(path, target_is_directory=True)
            with self.assertRaises(ValueError): load(alias, receipt)
            (path/"checkpoint.json").unlink()
            with self.assertRaises(ValueError): load(path, receipt)


if __name__ == "__main__":
    unittest.main()
