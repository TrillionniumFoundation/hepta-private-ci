"""Exercise typed exposure checks through actual hash-bound foundation files."""

import copy
import hashlib
import json
import unittest

import hepta_cell_research_foundation as foundation
import hepta_cell_source_registry as registry_adapter
import test_hepta_cell_research_successor as consumer_support


def task(task_id, lineage_group):
    return {
        "task_id": task_id,
        "task_sha256": hashlib.sha256(task_id.encode()).hexdigest(),
        "lineage_group": lineage_group,
    }


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.consumer = consumer_support.ResearchSuccessorTests()
        self.consumer.setUp()
        self.addCleanup(self.consumer.doCleanups)
        self.fixture = self.consumer.fixture
        self.foundation = copy.deepcopy(self.consumer.foundation)
        self.foundation["schema"] = foundation.SCHEMA_V3
        self.registry = {
            "schema": registry_adapter.SCHEMA,
            "joint_configuration_sha256": self.foundation["joint_configuration_sha256"],
            "protocol_sha256": self.foundation["protocol_sha256"],
            "training": [task("train/task-1", "train/family")],
            "tuning": [task("tune/task-1", "tune/family")],
            "selection": [task("select/task-1", "select/family")],
            "successor": task("successor/task-1", "successor/family"),
        }

    def put(self, registry):
        document = copy.deepcopy(self.foundation)
        document["artifacts"]["source_registry"] = self.fixture.bind(
            "source-registry.json", registry
        )
        return self.consumer.put_foundation(document, self.consumer.readback)

    def test_verified_declarations_keep_custody_and_execution_holds(self):
        for unused in ((), ("tuning", "selection")):
            registry = copy.deepcopy(self.registry)
            for split in unused:
                registry[split] = []
            self.put(registry)
            result = self.fixture.assess()
            review = result["foundation"]
            self.assertEqual(
                review["source_registry_review"],
                {
                    "schema": "hepta.cell-source-registry-review.v1",
                    "registry_schema": registry_adapter.SCHEMA,
                    "declaration_integrity": "verified",
                    "declared_split_disjointness_verified": True,
                    "declaration_counts": {
                        **{
                            split: len(registry[split])
                            for split in registry_adapter.SPLITS
                        },
                        "successor": 1,
                    },
                    "declared_successor": registry["successor"],
                    "registry_authenticity_verified": False,
                    "successor_custody_verified": False,
                    "successor_unseen_verified": False,
                },
            )
            for flag in (
                "source_registry_semantics_verified",
                "actual_successor_consumption_verified",
                "consumer_readback_authenticity_verified",
                "evaluator_owner_authenticated",
            ):
                self.assertFalse(review[flag])
            self.assertIn(
                "SOURCE_REGISTRY_CUSTODY_UNVERIFIED",
                result["stages"]["S0"]["blockers"],
            )
            self.assertFalse(result["research_advancement"])
            self.assertFalse(result["stages"]["S0"]["substantive_evidence_ready"])

    def test_aliases_cannot_reuse_task_bytes_across_exposure_sets(self):
        for exposed in registry_adapter.SPLITS:
            with self.subTest(exposed=exposed):
                registry = copy.deepcopy(self.registry)
                registry["successor"]["task_sha256"] = registry[exposed][0][
                    "task_sha256"
                ]
                self.put(registry)
                with self.assertRaisesRegex(ValueError, "duplicate or alias"):
                    self.fixture.assess()
        registry = copy.deepcopy(self.registry)
        registry["tuning"][0]["task_sha256"] = registry["selection"][0]["task_sha256"]
        self.put(registry)
        with self.assertRaisesRegex(ValueError, "duplicate or alias"):
            self.fixture.assess()

    def test_lineage_may_repeat_within_training_but_cannot_cross_any_split(self):
        registry = copy.deepcopy(self.registry)
        registry["training"].append(task("train/task-2", "train/family"))
        self.put(registry)
        self.fixture.assess()
        for exposed in registry_adapter.SPLITS:
            changed = copy.deepcopy(registry)
            changed["successor"]["lineage_group"] = changed[exposed][0]["lineage_group"]
            self.put(changed)
            with self.assertRaisesRegex(ValueError, "lineage crosses"):
                self.fixture.assess()
        registry["selection"][0]["lineage_group"] = "tune/family"
        self.put(registry)
        with self.assertRaisesRegex(ValueError, "lineage crosses"):
            self.fixture.assess()

    def test_duplicate_or_conflicting_task_ids_are_rejected(self):
        for changed_digest in (False, True):
            registry = copy.deepcopy(self.registry)
            repeated = copy.deepcopy(registry["training"][0])
            if changed_digest:
                repeated["task_sha256"] = "f" * 64
            registry["training"].append(repeated)
            self.put(registry)
            with self.assertRaisesRegex(ValueError, "conflicting task ID"):
                self.fixture.assess()
        registry = copy.deepcopy(self.registry)
        registry["training"][0]["task_id"] = registry["successor"]["task_id"]
        self.put(registry)
        with self.assertRaisesRegex(ValueError, "conflicting task ID"):
            self.fixture.assess()

    def test_missing_or_wrong_successor_and_malformed_records_are_rejected(self):
        variants = []
        for value in (None, [], {}, task("another/task", "another/family")):
            variants.append(dict(self.registry, successor=value))
        missing = copy.deepcopy(self.registry)
        del missing["successor"]
        variants += [missing, {}, dict(self.registry, unexpected=True)]
        for field, value in (
            ("task_id", ""),
            ("task_id", "x" * 257),
            ("lineage_group", ""),
            ("lineage_group", "x" * 257),
            ("task_sha256", "f" * 63),
            ("task_sha256", "F" * 64),
            ("unknown", True),
        ):
            changed = copy.deepcopy(self.registry)
            changed["successor"][field] = value
            variants.append(changed)
        for registry in variants:
            with self.subTest(registry=registry):
                self.put(registry)
                with self.assertRaises(ValueError):
                    self.fixture.assess()

    def test_registry_pins_original_bytes_and_strict_json_are_required(self):
        for key in ("joint_configuration_sha256", "protocol_sha256"):
            registry = dict(self.registry, **{key: "f" * 64})
            self.put(registry)
            with self.assertRaisesRegex(ValueError, "source registry conflicts"):
                self.fixture.assess()
        for raw in (
            b'{"schema":"duplicate",' + json.dumps(self.registry).encode()[1:],
            b'{"value": NaN}',
            b"",
        ):
            self.put(raw)
            with self.assertRaises(ValueError):
                self.fixture.assess()
        self.put(self.registry)
        with (self.fixture.artifacts / "source-registry.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(ValueError, "artifact"):
            self.fixture.assess()

    def test_task_count_is_bounded_before_task_validation(self):
        registry = copy.deepcopy(self.registry)
        registry.update(tuning=[], selection=[])
        registry["training"] = [
            task(f"train/task-{index}", "train/family")
            for index in range(registry_adapter.MAX_TASKS - 1)
        ]
        self.put(registry)
        review = self.fixture.assess()["foundation"]["source_registry_review"]
        self.assertEqual(
            sum(review["declaration_counts"].values()), registry_adapter.MAX_TASKS
        )
        registry["training"].append({})
        self.put(registry)
        with self.assertRaisesRegex(ValueError, "at most 4096"):
            self.fixture.assess()
        for invalid in ([], {}, None):
            registry = dict(self.registry, training=invalid)
            self.put(registry)
            with self.assertRaises(ValueError):
                self.fixture.assess()

    def test_legacy_foundations_keep_opaque_registry_semantics(self):
        for schema in (foundation.SCHEMA, foundation.SCHEMA_V2):
            document = copy.deepcopy(self.consumer.foundation)
            document["schema"] = schema
            if schema == foundation.SCHEMA:
                del document["declared_successor"]
            document["artifacts"]["source_registry"] = self.fixture.bind(
                "legacy-registry.bin", b"opaque source bytes, not JSON"
            )
            self.consumer.put_foundation(document, self.consumer.readback)
            result = self.fixture.assess()
            self.assertNotIn("source_registry_review", result["foundation"])
            self.assertNotIn(
                "SOURCE_REGISTRY_CUSTODY_UNVERIFIED",
                result["stages"]["S0"]["blockers"],
            )
            self.assertFalse(result["foundation"]["source_registry_semantics_verified"])


if __name__ == "__main__":
    unittest.main()
