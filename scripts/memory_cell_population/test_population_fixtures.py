"""Behavioral checks for source pins, temporal boundaries and unseen inputs."""

import copy
import unittest

from population_fixtures import dataset, exact_baseline, source_digest


class PopulationFixtureTests(unittest.TestCase):
    def test_source_program_computes_unseen_inputs_without_probe_gold(self):
        data = dataset(1907)
        for probe in data["transfer_final"]:
            operation = probe["operation"]
            if operation["kind"] != "procedure":
                continue
            self.assertGreaterEqual(operation["input"], 6)
            rule = next(
                r for r in data["sources"] if r.get("rule") == operation["rule"]
            )
            expected = str(
                (rule["multiplier"] * operation["input"] + rule["offset"]) % 11
            )
            altered_probe = {**probe, "value": "corrupted-gold"}
            self.assertEqual(
                exact_baseline(data["sources"], altered_probe["operation"]),
                (expected, [rule["source_digest"]]),
            )

    def test_event_query_obeys_boundaries_and_accounts_for_inspected_sources(self):
        data = dataset(2719)
        entity = "courier E00"
        events = [
            r
            for r in data["sources"]
            if r["kind"] == "episode" and r["entity"] == entity
        ]
        roots = sorted(r["source_digest"] for r in events)
        expected = {
            0: "unknown",
            1: events[0]["location"],
            2: events[0]["location"],
            3: events[1]["location"],
            4: events[1]["location"],
            5: events[2]["location"],
        }
        for day, value in expected.items():
            self.assertEqual(
                exact_baseline(
                    data["sources"],
                    {"kind": "event_asof", "entity": entity, "day": day},
                ),
                (value, roots),
            )

    def test_modified_or_ambiguous_source_is_rejected(self):
        data = dataset(4051)
        sources = copy.deepcopy(data["sources"])
        sources[0]["value"] = "tampered"
        operation = data["source_selection"][0]["operation"]
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            exact_baseline(sources, operation)
        sources[0]["source_digest"] = source_digest(
            {k: v for k, v in sources[0].items() if k != "source_digest"}
        )
        sources.append(data["sources"][0])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            exact_baseline(sources, operation)

    def test_probes_are_disjoint_and_training_has_only_source_derived_answers(self):
        data = dataset(1907)
        sets = [
            data[k]
            for k in (
                "router_training",
                "router_reject_training",
                "source_selection",
                "retention_final",
                "transfer_final",
                "ood_final",
            )
        ]
        questions = [row["question"] for rows in sets for row in rows]
        self.assertEqual(len(questions), len(set(questions)))
        trained_operations = {
            source_digest(p["operation"]) for p in data["router_training"]
        }
        self.assertTrue(
            all(
                source_digest(p["operation"]) not in trained_operations
                for p in data["transfer_final"]
            )
        )
        for fact, probe in zip(
            data["train_facts"], data["router_training"], strict=True
        ):
            value, roots = exact_baseline(data["sources"], probe["operation"])
            self.assertEqual(fact["value"], value)
            self.assertIn(fact["source_digest"], roots)
        roots_by_rule = {}
        for fact, probe in zip(
            data["train_facts"], data["router_training"], strict=True
        ):
            if probe["operation"]["kind"] == "procedure":
                roots_by_rule.setdefault(probe["operation"]["rule"], set()).add(
                    fact["source_digest"]
                )
        self.assertTrue(all(len(roots) == 1 for roots in roots_by_rule.values()))
        self.assertEqual(data, dataset(1907))
        self.assertNotEqual(data["sources_sha256"], dataset(2719)["sources_sha256"])

    def test_dependency_groups_keep_event_histories_and_programs_indivisible(self):
        data = dataset(1907)
        memberships = {}
        for index, group in enumerate(data["partition_groups"]):
            memberships.setdefault(group, []).append(index)
        for indices in memberships.values():
            operations = [data["router_training"][i]["operation"] for i in indices]
            if operations[0]["kind"] == "event_at":
                self.assertEqual({op["day"] for op in operations}, {1, 3, 5})
                self.assertEqual(len({op["entity"] for op in operations}), 1)
            elif operations[0]["kind"] == "procedure":
                self.assertEqual({op["input"] for op in operations}, set(range(6)))
                self.assertEqual(len({op["rule"] for op in operations}), 1)
            else:
                self.assertEqual(len(indices), 1)
        rejection_operations = {
            source_digest(p["operation"]) for p in data["router_reject_training"]
        }
        self.assertTrue(
            all(
                source_digest(p["operation"]) not in rejection_operations
                for p in data["ood_final"]
            )
        )

    def test_unknown_and_malformed_requests_fail_with_explicit_semantics(self):
        data = dataset(4051)
        for probe in data["ood_final"]:
            self.assertEqual(
                exact_baseline(data["sources"], probe["operation"])[0], "unknown"
            )
        for operation in (
            {"kind": "execute", "code": "anything"},
            {"kind": "procedure", "rule": "rule P00", "input": True},
            {"kind": "event_asof", "entity": "courier E00", "day": -1},
            {
                "kind": "semantic",
                "entity": "person N00",
                "relation": "color",
                "value": "leak",
            },
        ):
            with self.assertRaises(ValueError):
                exact_baseline(data["sources"], operation)


if __name__ == "__main__":
    unittest.main()
