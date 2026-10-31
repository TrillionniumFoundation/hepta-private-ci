"""Synthetic byte/ZIP/receipt fixtures never represent a scientific or provider run."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from . import common as c
from .postseal import review


def archive_fixture(root):
    directory = root / "stage"
    for name in ("upload/payload/raw", "readback/payload/raw", "download_raw"):
        (directory / name).mkdir(parents=True, exist_ok=True)
    original = root / "synthetic_source"
    original.write_bytes(b"synthetic transport fixture, no outcomes\n")
    item = {**c.descriptor(original), "path": "raw/fixture.bin"}
    staged, returned = (
        directory / part / "payload/raw/fixture.bin" for part in ("upload", "readback")
    )
    for path in (staged, returned):
        path.write_bytes(original.read_bytes())
    config = c.write_new(root / "CONFIG.json", {"synthetic_fixture": True})
    binding = {
        "execution_episode": c.EPISODE,
        "sequence": 1,
        "label": "A-17",
        "pipeline_config": config,
        "completed_jobs": ["A-17"],
        "previous_ack": None,
    }
    identity = {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "run_id": "1",
        "run_attempt": "1",
        "head_sha": "1" * 40,
        "job": "synthetic-test-fixture",
    }
    manifest = c.write_new(
        directory / "upload/MANIFEST.json",
        {
            "schema": "hepta.github-actions-archive-manifest.v1",
            "binding": binding,
            "identity": identity,
            "files": [item],
            "payload_bytes": item["bytes"],
            "file_count": 1,
        },
    )
    archive = directory / "download_raw/fixture.zip"
    with zipfile.ZipFile(archive, "w") as saved:
        saved.writestr("payload/", b"")
        saved.write(manifest["path"], "MANIFEST.json")
        saved.write(staged, "payload/raw/fixture.bin")
    archive_item = c.descriptor(archive)
    artifact = {
        "id": 1,
        "name": "hepta-r07-1-1-A-17",
        "bytes": archive_item["bytes"],
        "sha256": archive_item["sha256"],
    }
    waits = []
    for number, operation in enumerate(("upload", "download")):
        value = {
            "operation": operation,
            "pid": 10 + number,
            "waited_pid": 10 + number,
            "wall_seconds": 0.1,
            "user_cpu_seconds": 0.01,
            "system_cpu_seconds": 0.02,
            "peak_rss_bytes": 1024,
            "exit_code": 0,
            "timed_out": False,
            "interruption_type": None,
            "measurement": "os.wait4 direct owned child",
        }
        c.write_new(directory / (operation + ".wait4.json"), value)
        waits.append(value)
    cost = {
        "wait4": waits,
        "wall_seconds": 0.2,
        "cpu_seconds": 0.07,
        "transport_child_cpu_seconds": 0.06,
        "parent_self_cpu_delta_seconds": 0.01,
    }
    proof = {"path": item["path"]}
    for field, path in (
        ("source_device_inode", original),
        ("staged_device_inode", staged),
        ("readback_device_inode", returned),
    ):
        info = path.stat()
        proof[field] = [info.st_dev, info.st_ino]
    ack = {
        "schema": "hepta.github-actions-archive-ack.v1",
        "binding": binding,
        "identity": identity,
        "manifest": manifest,
        "logical_files": [item],
        "items_verified": 1,
        "artifact": artifact,
        "cost": cost,
        "readback": {
            "raw_archive": archive_item,
            "all_sha256_and_bytes_match": True,
            "client": {
                "id": 1,
                "expected_sha256": artifact["sha256"],
                "digest_mismatch": False,
                "raw_archive": True,
            },
            "independent_device_inodes": [proof],
        },
    }
    row = {
        k: ack[k]
        for k in (
            "binding",
            "manifest",
            "logical_files",
            "items_verified",
            "artifact",
            "cost",
        )
    }
    row["ack"] = c.write_new(directory / "ACK.json", ack)
    return row, ack


def rebind(row, ack):
    path = Path(row["ack"]["path"])
    path.write_bytes(c.encode(ack))
    row = deepcopy(row)
    row["ack"] = c.descriptor(path)
    for key in (
        "binding",
        "manifest",
        "logical_files",
        "items_verified",
        "artifact",
        "cost",
    ):
        row[key] = ack[key]
    return row


class PostsealTests(unittest.TestCase):
    def test_actual_frozen_selection_metrics_uses_two_argument_guard_interface(self):
        import numpy as np
        from supplements.parameter_field_fullstudy_20261030 import (
            postseal_supplement as original,
        )
        from operational.parameter_field_five_questions_20261031.finite_head_guard import (
            make_guarded_choose,
        )

        choose = original.frozen_choose(c.SOURCE, original.Inputs(), np)
        head = {
            "baseline": 0,
            "mean": np.zeros(1),
            "scale": np.ones(1),
            "coefficients": np.array([[0.0, 2.0, 0.0, 0.0]]),
            "intercept": np.zeros(4),
            "threshold": 0.1,
            "fit_max_standardized_norm": 10.0,
        }
        result = original.selection_metrics(
            head, np.ones(1), [0.0, 1.0, 0.5, 0.2], make_guarded_choose(choose)
        )
        self.assertEqual(result["choice"]["chosen_action"], 1)
        self.assertTrue(result["chosen_action_is_optimal"])
        self.assertEqual(result["gated_selection_regret"], 0.0)
        self.assertFalse(result["choice"]["certificate"])

    def test_literal_independent_archive_and_closed_wait4(self):
        with tempfile.TemporaryDirectory() as name:
            row, unused = archive_fixture(Path(name))
            tracked = review.Metadata()
            ack = review.verify_ack(tracked, row, row["binding"])
            self.assertEqual(ack["items_verified"], 1)
            tracked.stable()

    def test_raw_download_byte_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            row, ack = archive_fixture(Path(name))
            path = Path(ack["readback"]["raw_archive"]["path"])
            with path.open("ab") as stream:
                stream.write(b"unregistered bytes")
            with self.assertRaisesRegex(ValueError, "Bound file bytes differ"):
                review.verify_ack(review.Metadata(), row, row["binding"])

    def test_mutated_independent_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            row, unused = archive_fixture(root)
            (root / "stage/readback/payload/raw/fixture.bin").write_bytes(
                b"other bytes"
            )
            with self.assertRaises(ValueError):
                review.verify_ack(review.Metadata(), row, row["binding"])

    def test_claimed_same_inode_and_missing_transport_wait_are_rejected(self):
        for mode in ("same_inode", "missing_wait"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                row, ack = archive_fixture(Path(name))
                if mode == "same_inode":
                    proof = ack["readback"]["independent_device_inodes"][0]
                    proof["source_device_inode"] = proof["staged_device_inode"]
                else:
                    ack["cost"]["wait4"] = ack["cost"]["wait4"][:1]
                row = rebind(row, ack)
                with self.assertRaises(ValueError):
                    review.verify_ack(review.Metadata(), row, row["binding"])

    def test_synthetic_binding_or_different_producer_cannot_be_adopted(self):
        with tempfile.TemporaryDirectory() as name:
            row, ack = archive_fixture(Path(name))
            with self.assertRaisesRegex(ValueError, "producer"):
                review.verify_ack(
                    review.Metadata(),
                    row,
                    row["binding"],
                    {**ack["identity"], "run_id": "2"},
                )
            ack["binding"]["synthetic_only"] = True
            row = rebind(row, ack)
            with self.assertRaisesRegex(ValueError, "binding"):
                review.verify_ack(review.Metadata(), row, row["binding"])

    def test_bad_operational_gate_never_enters_original_scientific_gate(self):
        config = {"ops_root": "/work/execution07/ops"}
        with (
            patch.object(
                review,
                "operational_gate",
                side_effect=ValueError("missing terminal ACK"),
            ),
            patch.object(review, "original_supplement") as science,
        ):
            with self.assertRaisesRegex(ValueError, "missing terminal ACK"):
                review.review(config, {}, {}, "/work/execution07/postseal")
            science.assert_not_called()

    def test_wait4_requires_successful_owned_closure_and_exact_argv(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            waited = {
                "pid": 13,
                "exit_code": 0,
                "wall_seconds": 1,
                "user_cpu_seconds": 0.2,
                "system_cpu_seconds": 0.3,
                "cpu_seconds": 0.5,
                "peak_rss_bytes": 10,
            }
            closure = {
                "all_returned_direct_children_reaped": True,
                "accounting_complete_for_attempted_direct_workers": True,
                "attempt_count": 1,
                "returned_children": 1,
                "attempts": [{"argv": ["synthetic", "--fixed"]}],
                "children": [{"wait4": waited}],
                "original_exception": None,
                "receipt_errors": [],
                "cleanup_errors": [],
                "construction_wait4_unavailable": False,
                "binding": {"execution_episode": c.EPISODE},
            }
            c.write_new(root / "001.WAIT4.json", waited)
            c.write_new(root / "CLOSURE.json", closure)
            result = review.wait4(
                review.Metadata(), root, argv=["synthetic", "--fixed"]
            )
            self.assertEqual(result["cpu_seconds"], 0.5)
            with self.assertRaisesRegex(ValueError, "argv"):
                review.wait4(review.Metadata(), root, argv=["synthetic", "--different"])
            waited["exit_code"] = 1
            (root / "001.WAIT4.json").write_bytes(c.encode(waited))
            (root / "CLOSURE.json").write_bytes(c.encode(closure))
            with self.assertRaisesRegex(ValueError, "failed owned wait4"):
                review.wait4(review.Metadata(), root)


if __name__ == "__main__":
    unittest.main()
