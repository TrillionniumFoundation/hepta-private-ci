import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


HERE = Path(__file__).resolve().parent
TRAIN = module("laya_training", HERE / "laya_cell_candidate.py")
BACKEND = module("laya_backend", HERE.parent.parent / "hepta-infer-worker-host/python/laya_cell.py")


class QualificationBoundaryTests(unittest.TestCase):
    def fixture(self):
        rows = [{"id": f"row-{i}", "episode": f"episode-{i}", "observed_at": i + 1,
                 "features_q24": [0, 0, 0, 0], "target": i % 2,
                 "split": ("train", "calibration", "holdout")[i // 2]} for i in range(6)]
        return {"schema": "hepta.laya.qualification-rows.v1", "qualification_only": True, "rows": rows}
    def load(self, value, digest=None):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "rows.json"
            raw = json.dumps(value).encode()
            path.write_bytes(raw)
            return TRAIN.load_rows(path, digest or hashlib.sha256(raw).hexdigest())

    def test_exact_frozen_rows_are_accepted_without_loading_a_model(self):
        raw, rows = self.load(self.fixture())
        self.assertEqual(len(rows), 6)
        self.assertEqual(json.loads(raw)["rows"], rows)

    def test_replacement_bytes_and_non_qualification_input_reject(self):
        with self.assertRaises(ValueError):
            self.load(self.fixture(), "0" * 64)
        value = self.fixture()
        value["qualification_only"] = False
        with self.assertRaises(ValueError):
            self.load(value)

    def test_duplicate_identity_episode_leakage_and_time_reversal_reject(self):
        for kind in ("identity", "episode", "time", "label", "unknown"):
            value = copy.deepcopy(self.fixture())
            if kind == "identity": value["rows"][1]["id"] = "row-0"
            if kind == "episode": value["rows"][5]["episode"] = "episode-0"
            if kind == "time": value["rows"][5]["observed_at"] = 1
            if kind == "label": value["rows"][0]["target"] = True
            if kind == "unknown": value["rows"][0]["authority"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.load(value)

    def test_actual_feature_values_are_not_replaced_by_a_digest(self):
        first = BACKEND.state_for([0, 0, 0, 0])
        last = BACKEND.state_for([1 << 24] * 4)
        self.assertNotEqual(first, last)
        self.assertEqual(json.loads(last)["support_coverage"], 1.0)

    def test_unknown_feature_shapes_bool_and_nonfinite_json_reject(self):
        for features in ([0] * 3, [0] * 5, [False, 0, 0, 0], [-1, 0, 0, 0], [1 << 25, 0, 0, 0]):
            with self.subTest(features=features), self.assertRaises(ValueError):
                BACKEND.bounded_features(features)
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                BACKEND.strict_json(raw)


if __name__ == "__main__":
    unittest.main()
