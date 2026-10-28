"""Real-source lineage, temporal cuts and held-input program execution checks."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from v2.tasks import (
    SOURCE_HASHES,
    build_real_tasks,
    canonical,
    compose,
    exact_predict,
    execute_rule,
    load_sources,
    read_store,
    reference_valid,
    schema_rules,
)


SOURCES = Path(__file__).resolve().parents[1] / "sources"


class TaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = build_real_tasks(source_dir=SOURCES, development_seed=8001)
        cls.raw, cls.sources = load_sources(SOURCES)

    def test_real_snapshots_are_verified_and_lineage_is_present(self):
        self.assertEqual({s["source_id"] for s in self.sources}, set(SOURCE_HASHES))
        self.assertEqual({s["license"] for s in self.sources}, {"Apache-2.0"})
        modules = {m["id"]: m for m in self.raw["MODULES.json"]["modules"]}
        extracted = {}
        for event in self.tasks["semantic"].events:
            field, module_id = event.key.removeprefix("module.").split(":", 1)
            self.assertEqual(event.value, modules[module_id][field])
            self.assertTrue(event.source_pointer.startswith("/modules/"))
            extracted.setdefault(module_id, {})[field] = event.value
        self.assertEqual(set(extracted), set(modules))

    def test_source_tampering_is_rejected_without_using_worktree_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in SOURCE_HASHES:
                shutil.copyfile(SOURCES / name, Path(directory) / name)
            (Path(directory) / "config.schema.json").write_bytes(b"{}")
            with self.assertRaisesRegex(ValueError, "pinned source mismatch"):
                load_sources(directory)

    def test_selection_test_keys_and_effective_inputs_are_disjoint(self):
        for task in self.tasks.values():
            self.assertTrue(task.train and task.selection and task.test)
            self.assertFalse(
                {q.key for q in task.selection} & {q.key for q in task.test}
            )
            training = {(q.key, canonical(q.inputs), q.as_of) for q in task.train}
            if task is self.tasks["procedural"] or task is self.tasks["episodic"]:
                for query in task.selection + task.test:
                    self.assertNotIn(
                        (query.key, canonical(query.inputs), query.as_of), training
                    )
            for query in task.train + task.selection + task.test:
                self.assertEqual(
                    set(query.public_input()),
                    {"task", "cell_type", "key", "text", "inputs", "as_of"},
                )
                self.assertNotIn("target", query.public_input())

    def test_exact_and_chained_baselines_recover_source_truth(self):
        for bundle in self.tasks.values():
            for queries in (bundle.train, bundle.selection, bundle.test):
                self.assertEqual(
                    exact_predict(bundle, queries), [q.target for q in queries]
                )

    def test_temporal_queries_resolve_actual_observed_changes(self):
        bundle = self.tasks["episodic"]
        history = self.raw["github-history.json"]["frozen_commits"]
        commits = {c["sha"]: c for c in history}
        for event in bundle.events:
            self.assertIn(event.key, commits[event.value]["changed_paths"])
            self.assertEqual(event.timestamp, commits[event.value]["timestamp"])
        versions = {}
        for event in bundle.events:
            versions.setdefault(event.key, set()).add(event.value)
        self.assertTrue(all(len(values) > 1 for values in versions.values()))
        sample = bundle.events[0]
        self.assertIsNone(
            read_store(bundle.events, "episodic", sample.key, "1900-01-01T00:00:00Z")
        )
        self.assertEqual(
            read_store(bundle.events, "episodic", sample.key),
            max(
                (e for e in bundle.events if e.key == sample.key),
                key=lambda e: e.revision,
            ).value,
        )

    def test_rule_execution_checks_unseen_values_and_exact_boundaries(self):
        rules = schema_rules(self.raw["config.schema.json"])
        self.assertTrue(rules)
        for rule in rules.values():
            if rule["type"] == "integer":
                values = [None, True, "3", 0.25, 10**400]
                for bound in (rule.get("minimum"), rule.get("maximum")):
                    if bound is not None:
                        values.extend([bound - 1, bound, float(bound), bound + 1])
            else:
                values = rule["enum"] + [None, True, 3, "__not_a_member__"]
            self.assertEqual(
                [execute_rule(rule, v) for v in values],
                [reference_valid(rule, v) for v in values],
            )
        for invalid in (
            {"type": "object"},
            {"type": "integer", "minimum": "bad"},
            {"type": "integer", "minimum": 3, "maximum": 2},
            {"type": "integer", "$ref": "other"},
        ):
            with self.assertRaises(ValueError):
                execute_rule(invalid, 1)

    def test_edges_contain_only_connections_and_removal_abstains(self):
        bundle = self.tasks["composition"]
        for edge in bundle.metadata["edges"]:
            self.assertEqual(
                set(edge), {"source_node", "output_type", "target_node", "input_port"}
            )
        self.assertEqual(
            exact_predict(bundle, edge_transform=lambda value, kind: None),
            [None] * len(bundle.test),
        )
        query = next(q for q in bundle.test if q.task == "schema_chain")

        class PublicOnly:
            def __getattr__(self, name):
                if name == "target":
                    raise AssertionError("candidate read a hidden target")
                return getattr(query, name)

        def reader(kind, key, cut):
            return read_store(bundle.events, kind, key, cut)

        self.assertEqual(compose(PublicOnly(), reader), query.target)

    def test_development_partitions_do_not_change_the_real_source_facts(self):
        other = build_real_tasks(source_dir=SOURCES, development_seed=8003)
        for name in self.tasks:
            first, second = self.tasks[name], other[name]
            self.assertEqual(first.events, second.events)
            self.assertEqual(first.sources, second.sources)
            self.assertFalse(first.metadata["seed_changes_real_source_observations"])
        self.assertNotEqual(
            [q.inputs for q in self.tasks["procedural"].test],
            [q.inputs for q in other["procedural"].test],
        )
        json.dumps(
            {name: bundle.to_dict() for name, bundle in self.tasks.items()},
            allow_nan=False,
        )


if __name__ == "__main__":
    unittest.main()
