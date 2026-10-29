"""Finite reader and Cell binding controls; no model or owner is executed."""

import copy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_neural_evidence_diverse_v3 as target
import test_hepta_neural_candidate_transport_v1 as cell_fixture
import test_hepta_neural_study_diverse_v3 as data_fixture
from test_hepta_neural_diverse_v3 import fixture


class DiverseTransportTests(unittest.TestCase):
    write = cell_fixture.CandidateTransportBindings.write
    refresh = cell_fixture.CandidateTransportBindings.refresh
    rejected = cell_fixture.CandidateTransportBindings.rejected

    def setUp(self):
        cell_fixture.CandidateTransportBindings.setUp(self)
        self.events, raw, _, _, context = fixture()
        context["observer"] = self.observation["observer"]
        self.observation = context
        self.training.update(raw)
        self.completion["input"] = raw["input"]
        self.value["schema"] = target.transport.DIVERSE_SCHEMA
        for record in (self.training, self.completion, self.value):
            del record["observation_execution"]
            record[target.work.CONTEXT_KEY] = context
        self.training["schema"] = "llm-runtime-parent-step-actual-" + target.work.SUFFIX
        self.completion["schema"] = (
            "llm-runtime-parent-step-result-" + target.work.SUFFIX
        )
        self.write_trace()

    def write_trace(self):
        raw = b"".join(target.canonical(row) + b"\n" for row in self.events)
        self.training["training"]["objective"]["trace"] = dict(
            self.write(target.work.TRACE, raw), bytes=len(raw)
        )
        self.refresh()

    def test_complete_diverse_trace_with_original_three_member_bindings(self):
        records, payloads = target.transport.preflight(self.value)
        self.assertEqual(records["training"], self.training)
        self.assertEqual(set(payloads), set(target.transport.NAMES))
        for schema in (target.transport.SCHEMA, target.transport.BINARY_SCHEMA):
            changed = copy.deepcopy(self.value)
            changed["schema"] = schema
            self.rejected(changed)

    def test_work_context_and_legacy_step_relabelling_refuse(self):
        for key, value in (
            ("row_exposures", 100),
            ("distinct_source_rows", 10),
            ("physical_microbatch", True),
            ("training_schedule", "00" * 32),
        ):
            old = self.observation[key]
            self.observation[key] = value
            self.refresh()
            with self.subTest(field=key):
                self.rejected()
            self.observation[key] = old
        self.training["training"]["steps"] = 10
        self.refresh()
        self.rejected()

    def test_actual_trace_replay_path_and_missing_source_refuse(self):
        self.events[1], self.events[2] = self.events[2], self.events[1]
        self.write_trace()
        self.rejected()
        self.events[1], self.events[2] = self.events[2], self.events[1]
        self.write_trace()
        del self.training["source"]["binary_diverse60_training_data"]
        self.refresh()
        self.rejected()
        self.training["source"]["binary_diverse60_training_data"] = (
            target.work.DATA_SHA256
        )
        self.training["training"]["objective"]["trace"]["path"] = str(
            self.root / "substitute.jsonl"
        )
        self.refresh()
        self.rejected()

    def test_original_owner_parent_and_resource_limits_are_not_optional(self):
        for field, value in (
            ("stop_reason", "rss-observation-unavailable"),
            ("owned_child_reap_resolved", False),
            ("budget", dict(wall_seconds=1801, rss_bytes=16 * 1024**3)),
        ):
            old = self.completion["supervisor"][field]
            self.completion["supervisor"][field] = value
            self.refresh()
            with self.subTest(field=field):
                self.rejected()
            self.completion["supervisor"][field] = old
        self.training["parent_readback"] = "00" * 32
        self.refresh()
        self.rejected()


class DiverseReaderTests(unittest.TestCase):
    def setUp(self):
        data_fixture.DiverseStudyTests.setUp(self)
        (self.root / "trained").mkdir()
        (self.root / "trained/model-plan.json").write_bytes(self.raw)
        _, self.actual, self.consumed, public, _ = fixture()
        self.actual["source"]["runtime"] = "66" * 32
        self.trained = dict(
            training_data=dict(path="dataset", sha256="11" * 32),
            training=dict(path="actual", sha256="22" * 32),
            source_dataset_digest=self.value["source_dataset_digest"],
        )
        self.consumed.update(
            schema="hepta-neural-diverse-training-consumption-v3",
            training_data=self.trained["training_data"],
            actual_receipt=self.trained["training"],
            actual_trace=self.actual["training"]["objective"]["trace"],
            original_runtime_source_sha256=self.actual["source"]["runtime"],
            experiment=target.work.identity(self.plan),
            optimizer_steps=30,
            distinct_source_rows=60,
            actual_row_exposures=300,
            fixed_training_data_sha256=target.work.DATA_SHA256,
            update_schedule_sha256=target.work.identity(public["update_schedule"]),
            evidence_scope="synthetic negative-control records, no actual training claim",
        )
        self.reader = target.DiverseEvidence(self.root)

    def verify(self):
        self.reader.validate_training_data(
            self.value, self.consumed, self.actual, self.trained, self.root
        )

    def test_exact_sixty_source_dataset_and_three_hundred_consumer_records(self):
        self.verify()
        self.assertEqual(
            (self.reader.training_steps, self.reader.training_source_rows), (30, 60)
        )
        self.assertNotIn("torch", sys.modules)

    def test_consumption_missing_metadata_source_and_digest_relabel_refuse(self):
        for key in (
            "schema",
            "training_data",
            "actual_receipt",
            "actual_trace",
            "original_runtime_source_sha256",
            "experiment",
            "fixed_training_data_sha256",
            "update_schedule_sha256",
        ):
            old = self.consumed.pop(key)
            with self.subTest(missing=key), self.assertRaises((ValueError, KeyError)):
                self.verify()
            self.consumed[key] = "substitute"
            with self.subTest(changed=key), self.assertRaises((ValueError, KeyError)):
                self.verify()
            self.consumed[key] = old

    def test_source_count_consumed_totals_and_old_twenty_record_dataset_refuse(self):
        for key, value in (
            ("optimizer_steps", 10),
            ("distinct_source_rows", 10),
            ("actual_row_exposures", 100),
            ("optimizer_steps", 30.0),
            ("steps", self.consumed["steps"][:100]),
        ):
            old = self.consumed[key]
            self.consumed[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.verify()
            self.consumed[key] = old
        self.value["dataset_receipt"]["snapshot"]["source_record_digests"] = [
            "aa" * 32
        ] * 20
        with self.assertRaises(ValueError):
            self.verify()

    def test_legacy_defaults_retain_ten_rows_twenty_authenticated_records(self):
        for kind, count in (
            (target.original.Evidence, 10),
            (target.binary.BinaryEvidence, 100),
        ):
            legacy = kind(self.root)
            self.assertEqual(
                (legacy.training_steps, legacy.training_source_rows), (10, 10)
            )
            data = dict(
                offered_training_rows=list(range(12)),
                consumed_training_rows=list(range(10)),
                consumed_step_indices=list(range(10)),
                source_dataset_digest="11" * 32,
                dataset_receipt=dict(
                    snapshot=dict(
                        dataset_digest="11" * 32, source_record_digests=list(range(20))
                    )
                ),
            )
            trained = dict(
                training_data="data", training="actual", source_dataset_digest="11" * 32
            )
            consumed = dict(
                training_data="data",
                actual_receipt="actual",
                steps=[dict(input_ids=[1], supervised_tokens=1)] * count,
            )
            legacy.validate_training_data(
                data,
                consumed,
                dict(training=dict(tokens=count, supervised_tokens=count)),
                trained,
                self.root,
            )
            with self.assertRaises(ValueError):
                legacy.validate_training_data(
                    self.value, self.consumed, self.actual, self.trained, self.root
                )

    def test_published_identity_cannot_be_inferred_from_candidate_or_environment(self):
        item = dict(identity=dict(commit="a" * 40, tree="b" * 40))
        with (
            patch.object(target.study_driver, "TRAINING_COMMIT", None),
            self.assertRaises(ValueError),
        ):
            target.published_source(item)
        with (
            patch.object(target.study_driver, "TRAINING_COMMIT", "a" * 40),
            patch.object(target.study_driver, "TRAINING_TREE", "b" * 40),
        ):
            target.published_source(item)
            for key in ("commit", "tree"):
                changed = copy.deepcopy(item)
                changed["identity"][key] = "c" * 40
                with self.subTest(field=key), self.assertRaises(ValueError):
                    target.published_source(changed)

    def test_source_snapshots_collect_all_five_and_fail_closed_on_missing_new_source(
        self,
    ):
        item = dict(identity=dict(commit="a" * 40, tree="b" * 40))
        with (
            patch.object(target.original.ci, "git", return_value=str(self.root)),
            patch.object(target.original, "run_identity", return_value={}),
            patch.object(
                target.original, "collect_source", return_value=item
            ) as collect,
            patch.object(target.original, "save") as save,
            patch.object(target.study_driver, "TRAINING_COMMIT", "a" * 40),
            patch.object(target.study_driver, "TRAINING_TREE", "b" * 40),
        ):
            self.assertEqual(target.source(self.root / "source.json"), 0)
            self.assertEqual(collect.call_count, 5)
            self.assertEqual(
                set(save.call_args.args[1]["repositories"]), target.REPOSITORIES
            )
            collect.side_effect = [
                item,
                item,
                item,
                item,
                ValueError("actual missing new checkout"),
            ]
            self.assertEqual(target.source(self.root / "source.json"), 1)
            self.assertFalse(save.call_args.args[1]["valid"])

    def test_full_source_and_material_completion_reader_must_bind_this_output(self):
        sources = dict(parent_step_v2="aa" * 32, runtime="bb" * 32)
        execution = dict(output=str(self.root), source=dict(sources))
        raw = dict(source=dict(sources))
        trained = dict(
            training=dict(path=str(self.root / "actual-receipt.json"), sha256="cc" * 32)
        )
        with patch.object(target, "published_source"):
            parent_step = SimpleNamespace(
                sources=lambda profile: sources,
                verify_completion=lambda value: "cc" * 32,
            )
            target.complete_lineage(parent_step, execution, raw, trained, self.root)
            for record, field in ((execution, "source"), (raw, "source")):
                saved = record[field]
                record[field] = {"runtime": sources["runtime"]}
                with (
                    self.subTest(record=record),
                    self.assertRaisesRegex(ValueError, "source closure"),
                ):
                    target.complete_lineage(
                        parent_step, execution, raw, trained, self.root
                    )
                record[field] = saved
            execution["output"] = str(self.root / "other-study")
            with self.assertRaisesRegex(ValueError, "exact training output"):
                target.complete_lineage(parent_step, execution, raw, trained, self.root)
            execution["output"] = str(self.root)
            parent_step.verify_completion = lambda value: "dd" * 32
            with self.assertRaisesRegex(ValueError, "candidate material reread"):
                target.complete_lineage(parent_step, execution, raw, trained, self.root)

            def reject_material(value):
                raise ValueError("PARENT_V2_LINEAGE")

            parent_step.verify_completion = reject_material
            with self.assertRaisesRegex(ValueError, "PARENT_V2_LINEAGE"):
                target.complete_lineage(parent_step, execution, raw, trained, self.root)
        context = self.actual["training"]["objective"]["execution"]
        self.actual[target.work.CONTEXT_KEY] = copy.deepcopy(context)
        expected = "d19cec23c9b1baa3540dadb91bdb3ba14652f0ddf2820ec074ea41f9bd1edfc2"
        descriptor = dict(
            source_manifest=dict(training_code_digest=expected),
            ledger=dict(
                binding="d4d75d90272c006cedec9af116520c9fc32d1303163b6c57e77ef50f959895ab"
            ),
        )
        self.assertEqual(
            target.publication_provenance(self.actual, context, descriptor), expected
        )
        self.actual["source"] = dict(reversed(list(self.actual["source"].items())))
        self.assertEqual(
            target.publication_provenance(self.actual, context, descriptor), expected
        )
        for object_, field, value in (
            (descriptor["source_manifest"], "training_code_digest", "44" * 32),
            (
                descriptor["ledger"],
                "binding",
                "7f49dd06095051404b5bbaf14d7f2740bd3ec1ecc48352574a68f4d856697718",
            ),
            (self.actual["source"], "runtime", "77" * 32),
            (self.actual["source"], "binary_diverse60_training_data", "00" * 32),
            (self.actual[target.work.CONTEXT_KEY], "optimizer_steps", 10),
        ):
            saved = object_[field]
            object_[field] = value
            with self.subTest(publication_field=field), self.assertRaises(ValueError):
                target.publication_provenance(self.actual, context, descriptor)
            del object_[field]
            with (
                self.subTest(missing_publication_field=field),
                self.assertRaises((KeyError, ValueError)),
            ):
                target.publication_provenance(self.actual, context, descriptor)
            object_[field] = saved

    def test_future_windows_cannot_reuse_observed_prompts_or_each_other(self):
        windows = [
            [dict(prompt=f"synthetic fixture {i}-{j}") for j in range(512)]
            for i in range(2)
        ]
        target.future_prompts(windows, set())
        with self.assertRaises(ValueError):
            target.future_prompts(
                windows,
                {target.hashlib.sha256(windows[0][0]["prompt"].encode()).hexdigest()},
            )
        windows[1][0] = windows[0][0]
        with self.assertRaises(ValueError):
            target.future_prompts(windows, set())

    def test_actual_isolated_cli_and_original_budget_constants_are_unchanged(self):
        result = subprocess.run(
            [sys.executable, "-I", "-B", target.__file__, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"source,assess,archive", result.stdout)
        self.assertEqual(target.transport.SECONDS, 35)
        self.assertEqual(
            target.COMMANDS["scoped-rust"], target.original.COMMANDS["scoped-rust"]
        )
        self.assertEqual(target.COMMANDS["diverse-chain-controls"], 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)
