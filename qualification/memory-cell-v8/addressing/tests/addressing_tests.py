"""Numerical, admission, import and native-fixture boundary tests, not NLP scores."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap
import numpy as np
from addressing.contracts import OPERATIONS, canonical, digest, normalize
from v8_addressing.model import SelectiveIntentModel
from v8_addressing.native_fixture import load_suite, native_fixture, native_request
from v8_addressing.policy import fit_policies


class ToyEncoder:
    """Fixed orthogonal toy features isolate actual numerical fit/serialization."""
    digest = "7" * 64
    base_bytes = 1024
    tokenizer = SimpleNamespace(encode=lambda value: SimpleNamespace(overflowing=[]))

    def encode(self, values):
        result = np.zeros((len(values), 384), dtype=np.float32)
        for index, value in enumerate(values):
            label = next((name for name in (*OPERATIONS, "reject") if value.startswith(name)), "reject")
            result[index, (*OPERATIONS, "reject").index(label)] = 1
        return result


def training_rows():
    return [{"id": f"fit:{operation}:{index}", "text": f"{operation} observation sample {index}",
             "operation": operation, "language": "en", "family": f"fit:{operation}"}
            for operation in (*OPERATIONS, "reject") for index in range(10)]


def suite_value():
    entity = {"entity": "entity:probe", "aliases": ["Probe"], "records": [
        {"kind": "event", "effective_at": 1, "value": 3},
        {"kind": "event", "effective_at": 2, "value": 4},
        {"kind": "semantic", "effective_at": 2, "value": {"factor": 2, "label": "stored"}},
        {"kind": "procedure", "effective_at": 2, "value": {"opcode": "affine", "bias": 1, "limit": 1000}},
    ]}
    rows = []
    for index in range(120):
        operation = OPERATIONS[index % len(OPERATIONS)] if index < 60 else None
        rows.append({"id": f"case:{index}", "family": f"authored:{index}", "language": "en", "entity": "entity:probe",
                     "text": f"{operation or 'unsupported'} observation {index} of Probe", "at": 1, "since": 1,
                     "expected_operation": operation, "category": "known" if operation else "unsupported"})
    return {"schema": "hepta.memory.v8.language-suite.v1", "split": "held", "entities": [entity], "rows": rows}


class AddressingTests(unittest.TestCase):
    def test_real_fits_survive_load_and_corrupt_dimensions_are_rejected(self):
        rows = training_rows()
        model = SelectiveIntentModel(ToyEncoder(), "semantic", 32.0)
        receipt = model.fit(rows)
        self.assertEqual([item["head"] for item in receipt["heads"]], ["operation", "support"])
        predictions = model.hypotheses([row["text"] for row in rows])
        admission = fit_policies(rows, predictions)
        model.policies = admission["policies"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "model"
            identity = model.save(output)
            loaded = SelectiveIntentModel.load(output, ToyEncoder(), identity["manifest_sha256"])
            queries = [name + " new numerical input" for name in OPERATIONS]
            expected = [model.decide(value) for value in model.hypotheses(queries)]
            self.assertEqual(expected, [loaded.decide(value) for value in loaded.hypotheses(queries)])
            self.assertTrue(all(len(value) == 8 for value in expected))
            with np.load(output / "weights.npz", allow_pickle=False) as saved:
                arrays = {name: saved[name] for name in saved.files}
            arrays["support_coef"] = arrays["support_coef"][:, :-1]
            np.savez_compressed(output / "weights.npz", **arrays)
            weights = (output / "weights.npz").read_bytes()
            manifest = json.loads((output / "manifest.json").read_bytes())
            manifest.update(weights_sha256=hashlib.sha256(weights).hexdigest(), weights_bytes=len(weights),
                            numeric_array_bytes=sum(value.nbytes for value in arrays.values()))
            raw = canonical(manifest) + b"\n"
            (output / "manifest.json").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "dimensions"):
                SelectiveIntentModel.load(output, ToyEncoder(), hashlib.sha256(raw).hexdigest())

    def test_independent_calibration_tightens_a_harmful_operation_without_relabeling(self):
        rows = [{"operation": operation} for operation in OPERATIONS] + [{"operation": "reject"}]
        predictions = [{"raw_operation": operation, "score": 0.92, "margin": 0.7} for operation in OPERATIONS]
        predictions.append({"raw_operation": "current", "score": 0.95, "margin": 0.8})
        previous = {operation: {"threshold": 0.5, "margin": 0.05} for operation in OPERATIONS}
        result = fit_policies(rows, predictions, previous=previous)
        self.assertGreater(result["policies"]["current"]["threshold"], 0.95)
        self.assertEqual(result["metrics"]["known_correct"], 5)
        self.assertEqual(result["metrics"]["ood_accepted"], 0)
        self.assertTrue(all(result["policies"][name]["threshold"] >= previous[name]["threshold"]
                            and result["policies"][name]["margin"] == previous[name]["margin"] for name in OPERATIONS))
        self.assertFalse(result["population_risk_established"])

    def test_shadow_entry_point_cannot_read_a_different_owner_scope(self):
        path = Path(__file__).resolve().parents[1] / "qualification_shadow_worker.py"
        spec = importlib.util.spec_from_file_location("shadow_fixture_module", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        frame = {"request": {"scope": module.FIXTURE_SCOPE}, "registry": {"scope": module.FIXTURE_SCOPE}}
        raw = canonical(frame) + b"\n"
        self.assertEqual(module.FixtureInput(io.BytesIO(raw)).readline(10000), raw)
        frame["registry"]["scope"] = "unrelated:owner"
        with self.assertRaisesRegex(ValueError, "reserved fixture scope"):
            module.FixtureInput(io.BytesIO(canonical(frame) + b"\n")).readline(10000)

    def test_native_export_keeps_scoring_labels_out_of_the_real_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_bytes(canonical(suite_value()))
            suite, rows, receipt = load_suite(path, "held")
            output = native_fixture(suite)
            request = native_request(suite["rows"][0], "actual:owner-scope")
            self.assertEqual(set(request), {"schema", "query_id", "scope", "entity", "text", "at", "since", "max_hops", "max_cells"})
            self.assertEqual((request["max_hops"], request["max_cells"]), (8, 8))
            self.assertEqual(output["requests"][5]["expected_value"], 9)
            self.assertEqual(receipt["native_rows_executed"], 0)
            self.assertEqual(len(rows), 120)
            mutated = suite_value()
            mutated["entities"][0]["records"][2]["value"] = {"factor": 2, "bias": 1, "limit": 1000}
            path.write_bytes(canonical(mutated))
            with self.assertRaisesRegex(ValueError, "native typed-arithmetic"):
                load_suite(path, "held")

    def test_held_loader_rejects_overlap_and_conflicting_normalized_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            suite = suite_value()
            path.write_bytes(canonical(suite))
            _, rows, _ = load_suite(path, "held")
            with self.assertRaisesRegex(ValueError, "prior fitting split"):
                load_suite(path, "held", forbidden_texts=[rows[0]["text"]])
            second = json.loads(json.dumps(suite["entities"][0]))
            second.update(entity="entity:second", aliases=["Second"])
            suite["entities"].append(second)
            suite["rows"][60].update(text=suite["rows"][0]["text"].replace("Probe", "Second"), entity="entity:second")
            path.write_bytes(canonical(suite))
            with self.assertRaisesRegex(ValueError, "conflicting intent labels"):
                load_suite(path, "held")

    def test_parser_rejections_remain_native_cases_outside_both_classifier_denominators(self):
        for split in ("calibration", "held"):
            with self.subTest(split=split), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "input.json"
                suite = suite_value()
                suite["split"] = split
                text = "Compare Probe at 2000-01-01 and 2001-01-01."
                suite["rows"][60]["text"] = text
                path.write_bytes(canonical(suite))
                loaded, rows, receipt = load_suite(path, split)
                self.assertEqual(native_fixture(loaded)["requests"][60]["text"], text)
                self.assertEqual((len(loaded["rows"]), len(rows)), (120, 119))
                self.assertEqual(sum(row["operation"] == "reject" for row in rows), 59)
                self.assertEqual(receipt["normalization_rejections"], [{
                    "id": "case:60", "category": "unsupported", "reason": "multiple-historical-cutoffs-not-supported"}])
                self.assertEqual(receipt["normalization_rejection_counts"], {
                    "unsupported": {"multiple-historical-cutoffs-not-supported": 1}})
                rejected_digest = digest(normalize(text))
                self.assertIn(rejected_digest, receipt["all_native_normalized_text_sha256"])
                with self.assertRaisesRegex(ValueError, "prior fitting split"):
                    load_suite(path, split, forbidden_text_digests=[rejected_digest])
                suite["rows"][0]["text"] = text
                path.write_bytes(canonical(suite))
                with self.assertRaisesRegex(ValueError, "multiple-historical-cutoffs-not-supported"):
                    load_suite(path, split)


if __name__ == "__main__":
    unittest.main()
