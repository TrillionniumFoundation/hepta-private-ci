"""Behavioral tests for fitted policy artifacts and actual typed execution."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from v3.learned_graph import (
    GraphQuery,
    LearnedGraph,
    TypedValue,
    collect_feedback,
    typed_permutation,
)
from v3.codec_reader import write_codec_memories
from v3.numeric_graph import (
    INTENTS,
    SPECS,
    exact_reader,
    make_query,
    numeric_executor,
    numeric_grade,
    target_for,
    write_memory,
)
from v3.route_language import graph_training_rows, partition_anchors
from v3.routing_study import slot_text, train_routing
from v3.semantic_router import REJECT, SemanticRouter, digest


def source_fixture():
    years = list(range(2010, 2020))
    values = [
        [
            int(1000 + 17 * row + 40 * np.sin(month * 1.7) + ((row + month) % 5) * 9)
            for month in range(12)
        ]
        for row in range(len(years))
    ]
    return {
        "domain": "co2",
        "years": years,
        "values": values,
        "fields": list(range(1, 13)),
        "scale": 100,
        "unit": "ppm",
    }


class SemanticRouterTests(unittest.TestCase):
    def test_all_candidate_artifacts_and_selected_duplicate_bytes_are_retained(self):
        class MechanicalEncoder:
            digest = "e" * 64

            def encode(self, texts):
                return np.asarray(
                    [
                        [
                            int(digest(text.encode())[index : index + 2], 16) / 255
                            for index in range(0, 16, 2)
                        ]
                        for text in texts
                    ]
                )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing"
            _, _, receipt = train_routing(
                MechanicalEncoder(),
                source_fixture(),
                path,
                seed=8011,
                source_commit="a" * 40,
                support_digest="b" * 64,
            )
            self.assertEqual(len(receipt["candidates"]), 12)
            self.assertEqual(len(list((path / "candidates").iterdir())), 12)
            actual_candidate_bytes = 0
            for record in receipt["candidates"]:
                artifact = record["artifact"]
                directory = path / artifact["path"]
                for filename, info in artifact["files"].items():
                    payload = (directory / filename).read_bytes()
                    self.assertEqual(
                        info, {"bytes": len(payload), "sha256": digest(payload)}
                    )
                    actual_candidate_bytes += len(payload)
                SemanticRouter.load(
                    directory,
                    expected_encoder_digest=MechanicalEncoder.digest,
                    expected_manifest_digest=artifact["manifest_sha256"],
                )
            self.assertEqual(
                receipt["all_candidate_artifact_bytes"], actual_candidate_bytes
            )
            actual_selected_bytes = 0
            for mode, record in receipt["selected"].items():
                for filename in ("weights.bin", "manifest.json"):
                    selected_payload = (path / mode / filename).read_bytes()
                    self.assertEqual(
                        selected_payload,
                        (path / record["artifact"]["path"] / filename).read_bytes(),
                    )
                    actual_selected_bytes += len(selected_payload)
            self.assertEqual(
                receipt["research_model_artifact_bytes_including_selected_copies"],
                actual_candidate_bytes + actual_selected_bytes,
            )

    def test_qualification_coverage_does_not_count_wrong_accepted_routes(self):
        router = SemanticRouter(
            ("a", "b", REJECT), np.eye(3) * 8, np.zeros(3), encoder_digest="e" * 64
        )
        features = np.array([[1, 0, 0]] * 4 + [[0, 0, 1]], dtype=np.float64)
        receipt = router.calibrate(features, ["a", "a", "b", "b", REJECT])
        self.assertEqual(receipt["selected"]["known_coverage"], 1.0)
        self.assertEqual(receipt["selected"]["known_correct_accepted_rate"], 0.5)
        self.assertFalse(receipt["selected"]["constraints_satisfied"])

    def test_slot_factoring_preserves_unknown_predicate_and_sentence(self):
        row = {
            "domain": "co2",
            "date": "2015-01",
            "utterance": "Forecast Mauna Loa atmospheric carbon dioxide after 2015-01, and explain causality.",
        }
        self.assertEqual(
            slot_text(row), "Forecast [series] after [date], and explain causality."
        )
        row["date"] = "2016-01"
        with self.assertRaisesRegex(ValueError, "slots"):
            slot_text(row)

    def test_actual_optimizer_saved_model_and_selected_rejection(self):
        features = np.tile(np.eye(3), (6, 1))
        labels = ["a", "b", REJECT] * 6
        router, receipt = SemanticRouter.fit(
            features,
            labels,
            classes=("a", "b", REJECT),
            encoder_digest="e" * 64,
            seed=7,
            steps=150,
        )
        self.assertTrue(receipt["parameters_changed"])
        self.assertLess(
            receipt["first_and_last_preupdate_loss"][-1],
            receipt["first_and_last_preupdate_loss"][0],
        )
        selected = router.calibrate(features, labels)
        self.assertTrue(selected["selected"]["constraints_satisfied"])
        self.assertEqual(
            [value.route for value in router.decisions(np.eye(3))], ["a", "b", None]
        )
        with self.assertRaisesRegex(ValueError, "hidden"):
            router.calibrate(features, labels, partition="held")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "router"
            manifest = router.save(
                path, source_commit="a" * 40, support_digest="b" * 64
            )
            loaded, _ = SemanticRouter.load(
                path,
                expected_encoder_digest="e" * 64,
                expected_manifest_digest=manifest["manifest_sha256"],
            )
            np.testing.assert_array_equal(
                loaded.probabilities(features), router.probabilities(features)
            )
            with self.assertRaisesRegex(ValueError, "contract"):
                SemanticRouter.load(path, expected_encoder_digest="d" * 64)
            body = json.loads((path / "manifest.json").read_bytes())
            body["threshold"] = 0.99
            (path / "manifest.json").write_text(json.dumps(body))
            with self.assertRaisesRegex(ValueError, "digest"):
                SemanticRouter.load(path, expected_encoder_digest="e" * 64)


class NumericGraphTests(unittest.TestCase):
    def test_feedback_learns_composition_and_persists_without_target_paths(self):
        source = source_fixture()
        executor = numeric_executor("co2", exact_reader(source))
        examples = []
        for row in graph_training_rows(source, 8011):
            initial, query = make_query(row)
            examples.append(
                (
                    row["id"],
                    row["intent"],
                    initial,
                    query,
                    target_for(source, row["intent"], tuple(row["address"])),
                )
            )
        feedback = collect_feedback(
            executor,
            examples,
            partition="train",
            score_function=lambda actual, target: numeric_grade(
                actual, target, reward_scale=100
            ),
        )
        graph = LearnedGraph(SPECS, INTENTS, ("address",), seed=8011)
        receipt = graph.fit(feedback)
        self.assertTrue(receipt["parameters_changed"])
        self.assertFalse(receipt["target_paths_supplied"])
        self.assertEqual(
            receipt["candidate_executions"],
            len(examples) * len(executor.candidates("address")),
        )
        self.assertGreater(receipt["all_candidate_calls"], len(feedback))
        with self.assertRaisesRegex(ValueError, "hidden"):
            collect_feedback(executor, examples, partition="held")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            LearnedGraph(SPECS, INTENTS, ("address",)).fit(feedback[:-1])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "layout"
            manifest = graph.save(path, source_commit="a" * 40, support_digest="b" * 64)
            loaded, _ = LearnedGraph.load(
                path, expected_manifest_digest=manifest["manifest_sha256"]
            )
            np.testing.assert_array_equal(loaded.weights, graph.weights)
            for address in partition_anchors(source, 8011)["development"]:
                query = GraphQuery("numeric-study", "independent numeric task", "co2")
                for intent in INTENTS:
                    actual, trace = executor.run(
                        loaded.select(intent, "address"),
                        TypedValue("address", address),
                        query,
                        expected_generation=1,
                    )
                    self.assertEqual(actual, target_for(source, intent, address))
                    self.assertEqual(
                        trace["calls"], len(loaded.select(intent, "address"))
                    )

    def test_each_hop_revalidates_owner_and_cross_edges_are_material(self):
        source = source_fixture()
        reads = []
        reader = exact_reader(source)

        def read(coordinates):
            reads.extend(coordinates)
            return reader(coordinates)

        checks = []

        def admission(generation, operation, artifact, frontier):
            checks.append((generation, operation, artifact, frontier))
            if len(checks) == 2:
                raise ValueError("withdrawn between hops")

        executor = numeric_executor(
            "co2",
            read,
            admission_check=admission,
            artifact_bindings={spec.name: "digest" for spec in SPECS},
            source_frontier_digest="frontier",
        )
        query = GraphQuery("numeric-study", "three month mean", "co2")
        initial = TypedValue("address", (2015, 1))
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            executor.run(("c04", "c05", "c06"), initial, query, expected_generation=1)
        self.assertEqual(reads, [])
        self.assertEqual([row[1] for row in checks], ["c04", "c05"])
        executor = numeric_executor("co2", read)
        actual, trace = executor.run(
            ("c04", "c05", "c06"),
            initial,
            query,
            expected_generation=1,
            mode="no_cross_cell_edges",
        )
        self.assertIsNone(actual)
        self.assertEqual(trace["disposition"], "removed_cross_cell_edge")
        self.assertEqual(reads, [])
        with self.assertRaisesRegex(ValueError, "generation"):
            executor.run(("c01",), initial, query, expected_generation=2)
        with self.assertRaisesRegex(ValueError, "another source"):
            executor.run(
                ("c01",),
                initial,
                GraphQuery("numeric-study", "value", "sunspots"),
                expected_generation=1,
            )
        with self.assertRaisesRegex(ValueError, "calendar"):
            executor.run(
                ("c02", "c01"),
                TypedValue("address", (2015, 13)),
                query,
                expected_generation=1,
            )
        self.assertEqual(reads, [])

    def test_parameter_reader_survives_source_removal_and_handles_cross_year_window(
        self,
    ):
        source = source_fixture()
        expected = [source["values"][5][0], source["values"][4][11]]
        with tempfile.TemporaryDirectory() as temp:
            reader, receipt = write_memory(
                source, Path(temp) / "memory", rank=10, seed=8011
            )
            source["values"] = []
            self.assertEqual(reader.read([(2015, 1), (2014, 12)]), expected)
            self.assertEqual(reader.read([(1900, 1), (2015, 13)]), [None, None])
            self.assertFalse(receipt["raw_target_cache"])
            self.assertFalse(receipt["residual_correction"])
            self.assertGreater(receipt["deployed_bytes"], receipt["artifact"]["bytes"])

    def test_typed_permutation_changes_real_semantics_without_type_failure(self):
        source = source_fixture()
        executor = numeric_executor("co2", exact_reader(source))
        initial = TypedValue("address", (2015, 2))
        query = GraphQuery("numeric-study", "mean of three months", "co2")
        result, _ = executor.run(
            ("c04", "c05", "c06"),
            initial,
            query,
            expected_generation=1,
            permutation=typed_permutation(SPECS, 8011),
        )
        self.assertNotEqual(result, target_for(source, "mean3", (2015, 2)))

    def test_lossless_archive_arm_is_separate_and_works_after_source_erasure(self):
        source = source_fixture()
        expected = [source["values"][5][0], source["values"][4][11]]
        with tempfile.TemporaryDirectory() as temp:
            reader, _ = write_memory(source, Path(temp) / "memory", rank=1, seed=8011)
            residual, strong, receipt = write_codec_memories(
                source, reader, Path(temp) / "codecs"
            )
            source["values"] = []
            self.assertEqual(residual.read([(2015, 1), (2014, 12)]), expected)
            self.assertEqual(strong.read([(2015, 1), (2014, 12)]), expected)
            self.assertFalse(receipt["parameter_only"])
            self.assertTrue(receipt["both_readers_materialize_exact_values_in_memory"])
            self.assertEqual(
                receipt["factor_residual"]["resident_decoded_cache_bytes"], 10 * 12 * 5
            )


if __name__ == "__main__":
    unittest.main()
