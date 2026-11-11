"""Cold-process owner/content join; synthetic data does not qualify efficacy."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from closure_common import ClosureError, ClosureLimits, canonical
from closure_test_support import SyntheticClosure
import selected_use as use_module
from selected_use import original_owner


class SelectedUseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="v13-selected-use-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = SyntheticClosure(self.root)
        self.owner_root = self.root / "owner"
        self.scope = self.fixture.source["cut"]["scope"]
        record = self.fixture.source["records"][0]
        with original_owner(self.owner_root) as owner:
            owner.put(
                self.scope, record["source_id"], record["body"], expected_revision=0
            )
            self.artifact = owner.stage(
                self.scope, self.fixture.source["cut"], self.fixture.model
            )

            def validator(model, records):
                # Executable structural check; explicitly not an efficacy gate.
                output = model.predict_proba(np.zeros((1, 4)))
                return {
                    "passed": bool(
                        np.isfinite(output).all() and output.shape == (1, 2)
                    ),
                    "qualification": "synthetic-structural-only",
                }

            owner.publish(
                self.scope,
                "semantic-cell",
                self.artifact,
                self.fixture.model.encoder_hash,
                expected_epoch=0,
                validator=validator,
            )
        self.features = np.asarray(
            [[0.1, 0.3, 0.4, 0.8], [0.2, 0.7, 0.1, 0.6]], dtype=np.float32
        )
        self.features_path = self.root / "next-task.npz"
        np.savez_compressed(self.features_path, X=self.features)
        self.request = {
            "backend_profile": "v13-residual-adapter",
            "owner_root": str(self.owner_root),
            "scope": self.scope,
            "cell": "semantic-cell",
            "artifact": self.artifact,
            "epoch": 1,
            "encoder_manifest": str(self.fixture.encoder_path),
            "encoder_root": str(self.fixture.encoder_root),
            "training_dataset": str(self.fixture.dataset_path),
            "data_id": "synthetic-data-v1",
            "task_features": str(self.features_path),
            "task_id": "new-task-independent-process",
            "mode": "synthetic-fixture",
        }

    def invoke(self):
        path = self.root / "request.json"
        path.write_bytes(canonical(self.request))
        return subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("selected_use.py")),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_fresh_process_reloads_exact_selected_content_for_next_task(self):
        process = self.invoke()
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertNotEqual(result["worker_pid"], os.getpid())
        self.assertEqual(
            result["result"],
            {
                "predictions": self.fixture.model.predict(self.features).tolist(),
                "epoch": 1,
                "artifact": self.artifact,
                "source_version": self.fixture.model.source_version,
            },
        )
        self.assertEqual(result["binding"], self.fixture.verify()["binding"])
        self.assertTrue(result["live_source_frontier_checked"])
        self.assertTrue(result["inference_executed"])
        self.assertFalse(result["adoption_performed"])
        self.assertEqual(result["authority"], "DENY_ALL")

    def test_wrong_backend_scope_epoch_or_artifact_never_emits_use_receipt(self):
        for key, value in [
            ("backend_profile", "joint-generator"),
            ("scope", "other-scope"),
            ("epoch", 2),
            ("epoch", True),
            ("artifact", "f" * 64),
        ]:
            with self.subTest(key=key, value=value):
                original = self.request[key]
                self.request[key] = value
                result = self.invoke()
                self.request[key] = original
                self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_source_withdrawal_refuses_previous_selected_artifact(self):
        record = self.fixture.source["records"][0]
        with original_owner(self.owner_root) as owner:
            owner.put(
                self.scope,
                record["source_id"],
                record["body"],
                expected_revision=1,
                active=False,
            )
        result = self.invoke()
        self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_corrupt_checkpoint_or_nonfinite_task_input_has_no_receipt(self):
        np.savez_compressed(self.features_path, X=np.full((2, 4), np.nan))
        result = self.invoke()
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        np.savez_compressed(self.features_path, X=self.features)
        (self.owner_root / "artifacts" / self.artifact / "model.npz").write_bytes(
            b"broken"
        )
        result = self.invoke()
        self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_selection_change_before_use_never_predicts_the_replacement(self):
        verify = use_module._verified_checkpoint

        def change_selection(*args, **kwargs):
            verified = verify(*args, **kwargs)
            self.fixture.model.params["b"][0] += 0.2
            with original_owner(self.owner_root) as owner:
                replacement = owner.stage(
                    self.scope, self.fixture.source["cut"], self.fixture.model
                )
                owner.publish(
                    self.scope,
                    "semantic-cell",
                    replacement,
                    self.fixture.model.encoder_hash,
                    expected_epoch=1,
                    validator=lambda model, records: {
                        "passed": bool(
                            np.isfinite(model.predict_proba(self.features)).all()
                        ),
                        "qualification": "synthetic-structural-only",
                    },
                )
            return verified

        with (
            mock.patch.object(
                use_module, "_verified_checkpoint", side_effect=change_selection
            ),
            mock.patch.object(
                type(self.fixture.model),
                "predict",
                side_effect=AssertionError("prediction before permission"),
            ) as predict,
        ):
            with self.assertRaisesRegex(ClosureError, "Selection changed"):
                use_module.selected_use(self.request)
            predict.assert_not_called()

    def test_source_change_before_prediction_is_fenced_by_original_owner(self):
        verify = use_module._verified_checkpoint

        def withdraw(*args, **kwargs):
            verified = verify(*args, **kwargs)
            record = self.fixture.source["records"][0]
            with original_owner(self.owner_root) as owner:
                owner.put(
                    self.scope,
                    record["source_id"],
                    record["body"],
                    expected_revision=1,
                    active=False,
                )
            return verified

        with (
            mock.patch.object(use_module, "_verified_checkpoint", side_effect=withdraw),
            mock.patch.object(
                type(self.fixture.model),
                "predict",
                side_effect=AssertionError("prediction after withdrawal"),
            ) as predict,
        ):
            with self.assertRaisesRegex(RuntimeError, "revoked"):
                use_module.selected_use(self.request)
            predict.assert_not_called()

    def test_use_keeps_verified_bytes_and_does_not_reopen_replaced_checkpoint(self):
        verify = use_module._verified_checkpoint
        expected = self.fixture.model.predict(self.features).tolist()
        path = self.owner_root / "artifacts" / self.artifact / "model.npz"

        def replace_after_verified(*args, **kwargs):
            verified = verify(*args, **kwargs)
            with path.open("wb") as changed:
                changed.truncate(ClosureLimits().max_checkpoint_bytes + 1)
            return verified

        with mock.patch.object(
            use_module, "_verified_checkpoint", side_effect=replace_after_verified
        ):
            result = use_module.selected_use(self.request)
        self.assertEqual(result["result"]["predictions"], expected)
        self.assertLess(result["checkpoint"]["bytes"], path.stat().st_size)

    def test_large_class_tensor_is_bounded_before_each_prediction(self):
        adapter = type(self.fixture.model)
        model = adapter(
            input_dim=4,
            num_classes=4096,
            rank=2,
            seed=7,
            encoder_hash=self.fixture.model.encoder_hash,
            source_version=self.fixture.model.source_version,
        )
        model.sampler = self.fixture.model.sampler
        model.optimizer = self.fixture.model.optimizer
        model.step = self.fixture.model.step
        with original_owner(self.owner_root) as owner:
            artifact = owner.stage(self.scope, self.fixture.source["cut"], model)
            owner.publish(
                self.scope,
                "semantic-cell",
                artifact,
                model.encoder_hash,
                expected_epoch=1,
                validator=lambda candidate, records: {
                    "passed": bool(
                        np.isfinite(candidate.predict_proba(np.zeros((1, 4)))).all()
                    ),
                    "qualification": "synthetic-structural-only",
                },
            )
        self.request.update(epoch=2, artifact=artifact)
        rows = ClosureLimits().max_examples
        np.savez_compressed(self.features_path, X=np.zeros((rows, 4), dtype=np.float32))
        observed = []

        def bounded_probe(candidate, batch):
            observed.append(batch.shape[0])
            self.assertEqual(batch.dtype, np.dtype("float64"))
            self.assertTrue(batch.flags.c_contiguous)
            self.assertLessEqual(
                batch.shape[0] * 4096 * 8 * 4, ClosureLimits().max_array_bytes
            )
            return np.zeros(len(batch), dtype=np.int64)

        with mock.patch.object(adapter, "predict", bounded_probe):
            result = use_module.selected_use(self.request)
        self.assertGreater(len(observed), 1)
        self.assertEqual(sum(observed), rows)
        self.assertEqual(len(result["result"]["predictions"]), rows)
        self.assertEqual(result["prediction_execution"]["batches"], len(observed))

    def test_real_batched_predictions_match_original_adapter(self):
        features = np.tile(self.features, (257, 1))
        np.savez_compressed(self.features_path, X=features)
        result = use_module.selected_use(self.request)
        self.assertGreater(result["prediction_execution"]["batches"], 1)
        self.assertEqual(
            result["result"]["predictions"],
            self.fixture.model.predict(features).tolist(),
        )


if __name__ == "__main__":
    unittest.main()
