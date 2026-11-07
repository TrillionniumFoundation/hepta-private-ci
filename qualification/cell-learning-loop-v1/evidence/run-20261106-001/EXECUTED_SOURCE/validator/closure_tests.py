"""Original V13 save/load plus fail-closed bounded content verification."""

from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import numpy as np

from closure_common import ClosureError, ClosureLimits, canonical, reference, sha
from closure_test_support import SyntheticClosure, npy_array, npy_header


class LearningClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = SyntheticClosure(temporary.name)
        self.original = self.fixture.checkpoint.read_bytes()

    def test_original_save_load_complete_binding_without_training_or_inference(self):
        adapter, provenance, _ = reference()
        with ExitStack() as stack:
            for name in (
                "train",
                "predict",
                "predict_proba",
                "features",
                "loss_and_grads",
            ):
                stack.enter_context(
                    mock.patch.object(
                        adapter,
                        name,
                        side_effect=AssertionError("computation forbidden"),
                    )
                )
            receipt = self.fixture.verify()
            restored = adapter.load(io.BytesIO(self.original))
            self.assertEqual(restored.state_hash(), self.fixture.model.state_hash())
            restored.save(self.fixture.checkpoint)
            self.assertEqual(receipt["binding"], self.fixture.verify()["binding"])
        self.assertEqual(
            receipt["checkpoint"],
            {
                "sha256": sha(self.original),
                "bytes": len(self.original),
                "legacy_state_sha256": self.fixture.model.state_hash(),
            },
        )
        self.assertEqual(
            receipt["reference"]["source_commit"], provenance["source_commit"]
        )
        self.assertEqual(receipt["source"]["cut"], self.fixture.source["cut"])
        self.assertEqual(receipt["authority"], "DENY_ALL")
        self.assertTrue(receipt["synthetic"])
        self.assertNotIn("passed", receipt)
        self.assertFalse(
            receipt["training_executed"]
            or receipt["inference_executed"]
            or receipt["adoption_performed"]
        )
        for name, digest in receipt["member_sha256"].items():
            self.assertEqual(receipt["binding"][name], list(bytes.fromhex(digest)))
            self.assertEqual(len(receipt["binding"][name]), 32)

    def test_each_member_digest_changes_with_its_verified_content(self):
        before = self.fixture.verify()["member_sha256"]
        for member in ("weights", "optimizer", "rng", "sampler", "training_cursor"):
            with self.subTest(member=member):
                self.fixture.checkpoint.write_bytes(self.original)
                arrays = self.fixture.arrays()
                if member in ("weights", "optimizer", "sampler"):
                    key = {
                        "weights": "params_W",
                        "optimizer": "m_A",
                        "sampler": "sampler_order",
                    }[member]
                    if member == "sampler":
                        arrays[key] = arrays[key][::-1]
                    else:
                        arrays[key].flat[0] += 0.1
                    self.fixture.save_arrays(arrays)
                elif member == "rng":
                    self.fixture.metadata(
                        lambda metadata: metadata.update(
                            rng_state=np.random.default_rng(99).bit_generator.state
                        )
                    )
                else:
                    self.fixture.metadata(
                        lambda metadata: metadata["sampler"].update(cursor=1)
                    )
                after = self.fixture.verify()["member_sha256"]
                changed = {name for name in before if before[name] != after[name]}
                self.assertEqual(
                    changed,
                    {member, "training_cursor"} if member == "sampler" else {member},
                )

    def test_actual_array_dtype_shape_finite_variance_and_permutation_are_checked(self):
        mutations = {
            "dtype": ("params_A", np.zeros((4, 2), dtype=np.float32)),
            "shape": ("params_A", np.zeros((2, 4), dtype=np.float64)),
            "nan": ("params_A", np.full((4, 2), np.nan)),
            "infinite-moment": ("m_A", np.full((4, 2), np.inf)),
            "negative-variance": ("v_A", np.full((4, 2), -0.1)),
            "permutation": ("sampler_order", np.asarray([0, 0, 2, 3], dtype=np.int64)),
            "order-dtype": ("sampler_order", np.asarray([0, 1, 2, 3], dtype=np.int32)),
        }
        for name, (key, value) in mutations.items():
            with self.subTest(name=name):
                self.fixture.checkpoint.write_bytes(self.original)
                arrays = self.fixture.arrays()
                arrays[key] = value
                self.fixture.save_arrays(arrays)
                with self.assertRaises(ClosureError):
                    self.fixture.verify()

    def test_metadata_closure_cursor_rng_config_and_optimizer_are_checked(self):
        mutations = {
            "missing-rng": lambda data: data.pop("rng_state"),
            "cursor": lambda data: data["sampler"].update(cursor=5),
            "epoch": lambda data: data["sampler"].update(epoch=-1),
            "empty-sampler": lambda data: data["sampler"].update(n=0),
            "bool-step": lambda data: data.update(step=True),
            "missing-metadata": lambda data: data.pop("config"),
            "dimension": lambda data: data["config"].update(input_dim=4097),
            "parameter-bound": lambda data: data["config"].update(
                input_dim=4096, rank=4096
            ),
            "optimizer": lambda data: data["optimizer"].update(beta1=0.8),
            "extra-optimizer": lambda data: data["optimizer"].update(unknown=1),
            "rng-kind": lambda data: data["rng_state"].update(bit_generator="MT19937"),
            "rng-increment": lambda data: data["rng_state"]["state"].update(inc=2),
            "data-id": lambda data: data["sampler"].update(data_id="another-dataset"),
            "fingerprint": lambda data: data["sampler"].update(fingerprint="0" * 64),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                self.fixture.checkpoint.write_bytes(self.original)
                self.fixture.metadata(mutation)
                with self.assertRaises(ClosureError):
                    self.fixture.verify()

    def test_npy_allocation_hazards_are_rejected_before_any_numpy_load(self):
        payloads = {
            "giant-shape": npy_header((1 << 60, 2)),
            "payload-size": npy_header((4, 2), payload=b"x"),
            "object": npy_array(np.asarray([object()], dtype=object)),
            "unsupported-version": npy_header((4, 2), version=(3, 0)),
            "header-bound": b"\x93NUMPY\x01\x00" + (5000).to_bytes(2, "little"),
        }
        for name, payload in payloads.items():
            with self.subTest(name=name):
                self.fixture.checkpoint.write_bytes(self.original)
                self.fixture.replace_member("params_A.npy", payload)
                with mock.patch(
                    "numpy.load",
                    side_effect=AssertionError("allocation before preflight"),
                ):
                    with self.assertRaises(ClosureError):
                        self.fixture.verify()

    def test_raw_zip_inventory_corruption_and_expansion_bounds(self):
        for mode in (
            "truncated",
            "duplicate",
            "missing",
            "unexpected",
            "raw-cap",
            "expanded-cap",
        ):
            with self.subTest(mode=mode):
                self.fixture.checkpoint.write_bytes(self.original)
                options = {}
                if mode == "truncated":
                    self.fixture.checkpoint.write_bytes(self.original[:-13])
                elif mode == "duplicate":
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        with zipfile.ZipFile(self.fixture.checkpoint, "a") as archive:
                            archive.writestr(
                                "params_A.npy", npy_array(np.zeros((4, 2)))
                            )
                elif mode in ("missing", "unexpected"):
                    arrays = self.fixture.arrays()
                    arrays.pop("params_A")
                    if mode == "unexpected":
                        arrays["../params_A"] = np.zeros((4, 2))
                    self.fixture.save_arrays(arrays)
                elif mode == "raw-cap":
                    options["limits"] = ClosureLimits(
                        max_checkpoint_bytes=len(self.original) - 1
                    )
                else:
                    options["limits"] = ClosureLimits(max_zip_uncompressed_bytes=128)
                with self.assertRaises(ClosureError):
                    self.fixture.verify(**options)

    def test_source_encoder_and_dataset_content_drift_are_rejected(self):
        originals = {
            path: path.read_bytes()
            for path in (
                self.fixture.source_path,
                self.fixture.encoder_root / "fixture.bin",
                self.fixture.dataset_path,
            )
        }
        for path, raw in originals.items():
            with self.subTest(path=path.name):
                path.write_bytes(raw + b"changed")
                with self.assertRaises(ClosureError):
                    self.fixture.verify()
                path.write_bytes(raw)
        source = json.loads(self.fixture.source_path.read_bytes())
        source["records"][0]["body"] += "changed"
        with self.assertRaises(ClosureError):
            self.fixture.verify(source_snapshot=source)
        with self.assertRaises(ClosureError):
            self.fixture.verify(mode="reference")

    def test_release_contents_are_bound_without_publication_or_parent_authority(self):
        release = self.fixture.release_manifest()
        receipt = self.fixture.verify(release_manifest_path=release)
        self.assertEqual(receipt["release"]["artifact_id"], sha(release.read_bytes()))
        self.assertFalse(receipt["release"]["publication_checked"])
        value = json.loads(release.read_bytes())
        value["model_sha256"] = "0" * 64
        release.write_bytes(canonical(value))
        with self.assertRaises(ClosureError):
            self.fixture.verify(release_manifest_path=release)

    def test_source_cut_revision_rejects_boolean_and_float_aliases(self):
        for revision in (True, 1.0):
            with self.subTest(revision=repr(revision)):
                source = json.loads(self.fixture.source_path.read_bytes())
                source["cut"]["records"][0]["revision"] = revision
                # Keep the otherwise-valid checkpoint bound to this exact cut:
                # rejection must come from its revision type, not a stale hash.
                self.fixture.model.source_version = sha(canonical(source["cut"]))
                self.fixture.model.save(self.fixture.checkpoint)
                with self.assertRaisesRegex(ClosureError, "source-cut revision"):
                    self.fixture.verify(source_snapshot=source)

    def test_release_cut_rejects_boolean_and_float_aliases(self):
        release = self.fixture.release_manifest()
        original = release.read_bytes()
        for revision in (True, 1.0):
            with self.subTest(revision=repr(revision)):
                value = json.loads(original)
                value["source_cut"]["records"][0]["revision"] = revision
                release.write_bytes(canonical(value))
                with self.assertRaisesRegex(ClosureError, "Release manifest differs"):
                    self.fixture.verify(release_manifest_path=release)

    def test_cli_outputs_content_receipt_only_and_refuses_invalid_input(self):
        command = [
            sys.executable,
            str(Path(__file__).with_name("verify_closure.py")),
            str(self.fixture.checkpoint),
            "--source-snapshot",
            str(self.fixture.source_path),
            "--encoder-manifest",
            str(self.fixture.encoder_path),
            "--encoder-root",
            str(self.fixture.encoder_root),
            "--dataset",
            str(self.fixture.dataset_path),
            "--data-id",
            "synthetic-data-v1",
            "--mode",
            "synthetic-fixture",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["binding"], self.fixture.verify()["binding"]
        )
        self.fixture.checkpoint.write_bytes(b"invalid")
        failed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(failed.stdout, "")


if __name__ == "__main__":
    unittest.main()
