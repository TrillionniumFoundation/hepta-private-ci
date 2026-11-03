"""Small numerical integration checks; these do not claim pretrained efficacy."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))
sys.path.insert(0, str(PACKAGE))
from memory_cells.model import MemoryCell  # noqa: E402
from v2.addressing import AddressIndex, KINDS, address_text  # noqa: E402
from v2.real_routing import fit_router, header, route_queries  # noqa: E402
from v2.real_study import (
    DEFAULT_PROFILE,
    ExactRead,
    ParameterRead,
    ValueCatalog,
    _fresh,
    evaluate,
    run_real,
)  # noqa: E402
from v2.router import RoutingDecision  # noqa: E402
from v2.tasks import ReadQuery, WriteEvent  # noqa: E402


def write(kind, key, value):
    return WriteEvent(
        kind + key, kind, key, value, 1, "2026-01-01T00:00:00Z", "fixture", "/fixture"
    )


def query(task, kind, key, target, inputs=None):
    return ReadQuery(
        task + key,
        task,
        kind,
        key,
        f"Consult {task} for {key}.",
        inputs or {},
        None,
        "test",
        target,
        key,
    )


class BasisEncoder:
    """Answer-free fixture features isolate graph/read mechanics from MiniLM."""

    def __init__(self, texts):
        self.positions = {text: index for index, text in enumerate(texts)}
        self.dim = len(texts)
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return np.eye(self.dim)[[self.positions[text] for text in texts]]


class RealStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = (
            write("semantic", "config.field:limit", "/limit"),
            write("semantic", "module.owner:alpha", "owner-A"),
            write("semantic", "module.owner:beta", "owner-B"),
            write("episodic", "commit.module:abc", "alpha"),
            write("episodic", "module.py", "commit-A"),
            write(
                "procedural", "/limit", {"type": "integer", "minimum": 2, "maximum": 5}
            ),
            write(
                "procedural",
                "/other",
                {"type": "integer", "minimum": 10, "maximum": 20},
            ),
        )
        cls.index = AddressIndex.from_events(cls.events)
        cls.encoder = BasisEncoder(
            [address_text(e.cell_type, e.key, e.revision) for e in cls.events]
        )
        cls.catalogs, cls.models = {}, {}
        for kind in KINDS:
            members = [event for event in cls.events if event.cell_type == kind]
            catalog = ValueCatalog([event.value for event in members])
            cell = MemoryCell(cls.encoder.dim, 8, catalog.classes, seed=8001)
            features = cls.encoder.encode(
                [address_text(e.cell_type, e.key, e.revision) for e in members]
            )
            cell.fit(
                features,
                np.array([catalog.encode(e.value) for e in members]),
                steps=250,
                lr=0.03,
            )
            cls.catalogs[kind], cls.models[kind] = catalog, cell
        cls.queries = [
            query("module_attribute", "semantic", "module.owner:alpha", "owner-A"),
            query("latest_sampled_change", "episodic", "module.py", "commit-A"),
            query("schema_execution", "procedural", "/limit", True, {"value": 4}),
            query("schema_execution", "procedural", "/limit", False, {"value": 30}),
            query(
                "schema_chain", "composition", "config.field:limit", True, {"value": 4}
            ),
            query("commit_owner_chain", "composition", "commit.module:abc", "owner-A"),
        ]
        cls.temporary = tempfile.TemporaryDirectory()
        training = [
            replace(q, split="train", text=q.text.replace("Consult", "Read"))
            for q in cls.queries
        ]
        cls.router, _, _ = fit_router(
            {"fixture": SimpleNamespace(train=training)},
            DEFAULT_PROFILE,
            8001,
            Path(cls.temporary.name) / "router",
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def reader(self):
        return ParameterRead(
            self.index,
            self.encoder,
            {kind: cell.clone() for kind, cell in self.models.items()},
            self.catalogs,
        )

    def test_parameter_rules_execute_inputs_and_typed_graph_edges_matter(self):
        reader, oracle = self.reader(), ExactRead(self.index, self.events)
        correct, rows = evaluate(self.queries, reader, oracle, self.router, "learned")
        self.assertTrue(all(row["correct"] for row in rows))
        self.assertTrue(
            all(
                metric["event_value_identity_accuracy"] == 1
                for metric in correct["tasks"].values()
            )
        )
        self.assertEqual([row["prediction"] for row in rows[2:4]], [True, False])
        no_edges, _ = evaluate(
            self.queries[-2:],
            reader,
            oracle,
            self.router,
            "learned",
            lambda value, kind: None,
        )
        shuffled, _ = evaluate(
            self.queries[-2:],
            reader,
            oracle,
            self.router,
            "learned",
            lambda value, kind: "/other" if kind == "schema_pointer" else "beta",
        )
        self.assertEqual(
            [metric["final_accuracy"] for metric in no_edges["tasks"].values()], [0, 0]
        )
        self.assertEqual(
            [metric["final_accuracy"] for metric in shuffled["tasks"].values()], [0, 0]
        )
        self.assertEqual(correct["tasks"]["commit_owner_chain"]["queries"], 1)

    def test_model_damage_changes_predictions_and_batch_cache_is_not_retained(self):
        reader, oracle = self.reader(), ExactRead(self.index, self.events)
        before, _ = evaluate(self.queries, reader, oracle, self.router)
        calls_before = self.encoder.calls
        for model in reader.models.values():
            model.A[:] = 0
        after, rows = evaluate(self.queries, reader, oracle, self.router)
        self.assertGreater(self.encoder.calls, calls_before)
        self.assertTrue(
            all(metric["final_accuracy"] == 1 for metric in before["tasks"].values())
        )
        self.assertTrue(any(not row["correct"] for row in rows))
        self.assertLess(
            after["tasks"]["module_attribute"]["event_value_identity_accuracy"], 1
        )

    def test_wrong_route_is_not_repaired_with_oracle_type(self):
        class WrongRouter:
            def route(self, requests, mode):
                return [
                    RoutingDecision("procedural", "injected-wrong-route", 1.0, mode)
                    for _ in requests
                ]

        metrics, rows = evaluate(
            self.queries[:1],
            self.reader(),
            ExactRead(self.index, self.events),
            WrongRouter(),
            "learned",
        )
        self.assertIsNone(rows[0]["prediction"])
        self.assertEqual(rows[0]["route"]["route_id"], "procedural")
        self.assertEqual(metrics["unique_address_encodings"], 0)
        self.assertEqual(metrics["tasks"]["module_attribute"]["routing_accuracy"], 0)

    def test_learned_task_header_routing_cannot_see_keys_or_query_metadata(self):
        texts = [
            "Consult module_attribute for key:123.",
            "Consult module_attribute for schema_execution latest_sampled_change.",
        ]
        self.assertEqual(header(texts[0]), header(texts[1]))
        requests = [SimpleNamespace(text=text) for text in texts]
        self.assertEqual(
            [d.route_id for d in route_queries(self.router, requests, "learned")],
            ["semantic", "semantic"],
        )
        self.assertEqual(
            route_queries(
                self.router, [SimpleNamespace(text="unknown address")], "learned"
            )[0].route_id,
            None,
        )

    def test_catalog_persists_class_order_and_distinguishes_boolean_from_integer(self):
        catalog = ValueCatalog([True, 1, {"minimum": 2, "type": "integer"}])
        self.assertNotEqual(catalog.encode(True), catalog.encode(1))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            catalog.save(path)
            loaded = ValueCatalog.load(path)
            self.assertEqual(loaded.values, catalog.values)
            self.assertEqual(loaded.decode(catalog.encode(1)), 1)

    def test_development_run_rejects_formal_seed_before_loading_a_base(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run_real(
                {"seeds": [211]},
                tmp,
                "a" * 40,
                [211],
                "/nonexistent-base",
                development=True,
            )


class FreshEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        artifact = root / "cell"
        artifact.mkdir()
        (artifact / "manifest.json").write_text(
            json.dumps({"manifest_sha256": "a" * 64}), encoding="utf-8"
        )
        encoder = SimpleNamespace(
            encode=lambda texts: np.eye(len(texts)),
            digest="e" * 64,
            source={"files": {"model.onnx": {}, "tokenizer.json": {}}},
        )
        cell = SimpleNamespace(predict=lambda features: features.argmax(axis=1))
        actual = {
            "pid": os.getpid() + 1,
            "predictions": [0, 1],
            "artifact_digest": "a" * 64,
            "encoder_digest": "e" * 64,
            "opened_artifact_files": ["manifest.json", "tensors.npz"],
            "opened_base_files": ["model.onnx", "source.json", "tokenizer.json"],
        }
        return artifact, encoder, cell, actual

    def test_prediction_failure_keeps_actual_expected_and_differences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, encoder, cell, actual = self.fixture(root)
            actual["predictions"] = [1, 1]
            process = subprocess.CompletedProcess([], 0, json.dumps(actual), "")
            directory = root / "read"
            with (
                patch("v2.real_study.subprocess.run", return_value=process),
                self.assertRaisesRegex(ValueError, "evidence retained"),
            ):
                _fresh(
                    artifact,
                    ["one", "two"],
                    cell,
                    encoder,
                    root / "base",
                    directory,
                    cached_features=np.eye(2),
                )
            self.assertEqual(
                json.loads((directory / "actual-result.json").read_bytes()), actual
            )
            self.assertEqual(
                json.loads((directory / "expected.json").read_bytes())["predictions"],
                [0, 1],
            )
            validation = json.loads((directory / "validation.json").read_bytes())
            self.assertFalse(validation["passed"])
            self.assertEqual(
                validation["prediction_mismatches"],
                [{"index": 0, "expected": 0, "actual": 1}],
            )
            self.assertEqual(
                (directory / "stdout.txt").read_text(encoding="utf-8"), process.stdout
            )

    def test_same_request_predictions_cannot_hide_changed_training_batch_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, encoder, cell, actual = self.fixture(root)
            process = subprocess.CompletedProcess([], 0, json.dumps(actual), "")
            directory = root / "read"
            with (
                patch("v2.real_study.subprocess.run", return_value=process),
                self.assertRaisesRegex(
                    ValueError, "training_and_request_batch_features_equal"
                ),
            ):
                _fresh(
                    artifact,
                    ["one", "two"],
                    cell,
                    encoder,
                    root / "base",
                    directory,
                    cached_features=np.eye(2) + 0.001,
                )
            validation = json.loads((directory / "validation.json").read_bytes())
            self.assertTrue(validation["checks"]["predictions_equal"])
            self.assertFalse(
                validation["checks"]["training_and_request_batch_features_equal"]
            )
            self.assertEqual(validation["batch_contract"]["changed_feature_rows"], 2)

    def test_process_failure_keeps_raw_error_and_failed_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, encoder, cell, _ = self.fixture(root)
            directory = root / "read"
            process = subprocess.CompletedProcess([], 2, "", "declared failure\n")
            with (
                patch("v2.real_study.subprocess.run", return_value=process),
                self.assertRaises(ValueError),
            ):
                _fresh(
                    artifact,
                    ["one", "two"],
                    cell,
                    encoder,
                    root / "base",
                    directory,
                    cached_features=np.eye(2),
                )
            self.assertEqual(
                (directory / "stderr.txt").read_text(encoding="utf-8"),
                "declared failure\n",
            )
            self.assertFalse(
                json.loads((directory / "validation.json").read_bytes())["checks"][
                    "process_succeeded"
                ]
            )


if __name__ == "__main__":
    unittest.main()
