import json
import importlib.metadata
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run


class EntryTests(unittest.TestCase):
    def test_metadata_rejection_precedes_local_data_and_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "FROZEN.json"
            frozen.write_text(json.dumps({"numpy": "2.3.5", "sources": {}}))
            with patch.object(run, "FROZEN", frozen), patch.object(run, "MARKER", root / "OPENED"):
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    run.preflight(root / "missing", root / "output")
            self.assertFalse((root / "OPENED").exists())
            self.assertFalse((root / "output").exists())

    def test_no_data_preflight_does_not_consume_once_only_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "FROZEN.json"
            frozen.write_text(json.dumps({"numpy": "2.3.5", "sources": {"a": "b"},
                "threadpoolctl": importlib.metadata.version("threadpoolctl")}))
            with patch.object(run, "FROZEN", frozen), patch.object(run, "MARKER", root / "OPENED"), patch.object(run, "sources", return_value={"a": "b"}):
                with self.assertRaisesRegex(FileNotFoundError, "TRAIN file missing"):
                    run.preflight(root / "missing", root / "output")
                self.assertFalse((root / "OPENED").exists())
                (root / "OPENED").write_text("uncertain previous run")
                with self.assertRaisesRegex(ValueError, "consumed"):
                    run.preflight(root / "missing", root / "output")

    def test_real_smoke_imports_but_never_constructs_or_loads(self):
        from . import data, model
        with patch.object(data, "load_train", side_effect=AssertionError("no data")), patch.object(model, "ContentModel", side_effect=AssertionError("no model")), patch.object(model, "Actor", side_effect=AssertionError("no actor")):
            result = run.smoke()
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["measurement_started"])

    def test_handmade_actor_driver_and_export_use_actual_model_API(self):
        import numpy as np
        from .cost import Budget, cpu_ns
        from .model import Actor
        protocol = json.loads((run.HERE / "protocol.json").read_text())
        # Two optimizer unit steps on hand-made arrays, not the256-step study.
        protocol["policy_updates"] = 2
        features = np.linspace(-.1, .1, 6 * 32).reshape(6, 32)
        targets = np.arange(18).reshape(6, 3) / 18
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            chosen, fits, predictions, original, digest = run.fit_actor(
                features, targets, np.array([0, 1, 2, 0, 1, 2]), 11,
                Budget(output), cpu_ns(), output, protocol)
            restored = Actor.load(output / "actor.npz")
        self.assertEqual(restored.digest(), digest)
        np.testing.assert_array_equal(restored.predict(features), original)
        self.assertEqual(predictions.shape, (6, 3))
        self.assertEqual(chosen.shape, (6,))
        self.assertEqual([f["updates"] for f in fits], [2, 2, 2, 2])

    def test_handmade_shared_labels_are_scored_from_retained_wire(self):
        import numpy as np
        from .cost import Budget, cpu_ns
        from .model import ContentModel
        from .transport import score
        protocol = json.loads((run.HERE / "protocol.json").read_text())
        z = np.linspace(.2, .8, 2 * 784).reshape(2, 784)
        clean = np.full((2, 784), .5)
        labels = np.array([0, 1])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            features, values, byte_count = run.labels_and_features(
                ContentModel(11), z, clean, labels, Budget(output),
                output, cpu_ns(), protocol)
            wire = list((output / "wire").glob("*.json"))
            self.assertEqual(len(wire), 13)
            self.assertEqual(byte_count, sum(p.stat().st_size for p in wire))
            actual = score((output / "wire" / "JT-000000.json").read_bytes(),
                           clean.reshape(2, 28, 28), labels)
            np.testing.assert_array_equal(values["JT"], actual["utility"])
            self.assertEqual(features.shape, (2, 32))
            self.assertEqual(len(json.loads((output / "paired-rows.json").read_text())), 26)


if __name__ == "__main__":
    unittest.main()
