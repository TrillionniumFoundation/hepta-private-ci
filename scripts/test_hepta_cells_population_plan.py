"""Population policy checks; these do not measure learned task competence."""

from dataclasses import FrozenInstanceError, replace
import unittest

from hepta_cells.component_types import Budget, CellError, Partition, digest
from hepta_cells.population import CellSpec, LINEAGES, PopulationPlan


class _SpoofedString(str):
    """Hostile string value with a wire spelling different from its equality."""

    def __new__(cls, actual, impersonated):
        value = str.__new__(cls, actual)
        value.impersonated = impersonated
        return value

    def __eq__(self, other):
        return other == self.impersonated

    def __hash__(self):
        return hash(self.impersonated)


def population_cells():
    cells = []
    for lineage in LINEAGES:
        semantic = lineage in ("PERC", "MEM", "VERIFY")
        temporal = lineage in ("PRED", "CTRL", "ACT")
        cells.append(
            CellSpec(
                cell_id=lineage.lower(),
                lineage=lineage,
                family=(
                    "shared_semantic"
                    if semantic
                    else "stateful_temporal"
                    if temporal
                    else "deterministic"
                ),
                kernel="shared_head"
                if semantic
                else "gru"
                if temporal
                else "tool_wrapper",
                initial_identity=digest(["initial", lineage]),
                objective="local-objective:" + lineage.lower(),
                trainable=(
                    "heads"
                    if lineage == "MEM"
                    else "kernel_and_heads"
                    if lineage == "PRED"
                    else "frozen"
                ),
                update_rule=digest(["rule", lineage])
                if lineage in ("MEM", "PRED")
                else None,
                evaluation_profile=digest(["evaluation", lineage])
                if lineage in ("MEM", "PRED")
                else None,
            )
        )
    return tuple(cells)


class PopulationPlanTests(unittest.TestCase):
    def setUp(self):
        self.cells = population_cells()
        self.plan = PopulationPlan("principal:one", "agent:one", self.cells)

    def test_canonical_order_roundtrip_and_detached_records(self):
        reordered = PopulationPlan("principal:one", "agent:one", self.cells[::-1])
        self.assertEqual(self.plan, reordered)
        self.assertEqual(self.plan.digest, reordered.digest)
        record = self.plan.record()
        self.assertEqual(PopulationPlan.from_record(record), self.plan)
        record["cells"][0]["budget"]["max_work_units"] = 1
        record["cells"].pop()
        self.assertEqual(self.plan, reordered)
        with self.assertRaises(FrozenInstanceError):
            self.plan.cells[0].budget.max_work_units = 2
        with self.assertRaises(CellError):
            replace(self.plan, cells=list(self.plan.cells))

    def test_repeated_runs_keep_one_logical_update_point_and_owner_scope(self):
        first = Partition("principal:one", "agent:one", "mem", "run:one")
        second = replace(first, run_id="run:two")
        self.assertEqual(self.plan.spec(first), self.plan.spec(second))
        for partition in (
            replace(first, principal_id="principal:other"),
            replace(first, agent_id="agent:other"),
            replace(first, cell_id="mem:unregistered"),
        ):
            with self.subTest(partition=partition), self.assertRaises(CellError):
                self.plan.spec(partition)

    def test_extra_plastic_instances_consume_cap_even_with_same_lineage(self):
        memory = self.plan.spec(
            Partition("principal:one", "agent:one", "mem", "run:one")
        )
        extra = replace(memory, cell_id="mem:second")
        with self.assertRaises(CellError):
            replace(self.plan, cells=self.cells + (extra,))
        admitted = replace(self.plan, cells=self.cells + (extra,), max_plastic_cells=3)
        self.assertEqual(admitted.lineage_counts["MEM"], 2)
        with self.assertRaises(CellError):
            replace(
                admitted, cells=admitted.cells + (replace(extra, cell_id="mem:third"),)
            )
        with self.assertRaises(CellError):
            replace(self.plan, cells=self.cells + (memory,))

    def test_frozen_instances_can_scale_without_enabling_updates(self):
        frozen = replace(
            self.plan.cells[0],
            cell_id="extra:act",
            trainable="frozen",
            update_rule=None,
            evaluation_profile=None,
        )
        expanded = replace(self.plan, cells=self.cells + (frozen,))
        self.assertEqual(sum(cell.plastic for cell in expanded.cells), 2)
        all_frozen = tuple(
            replace(cell, trainable="frozen", update_rule=None, evaluation_profile=None)
            for cell in self.cells
        )
        self.assertEqual(
            sum(
                cell.plastic
                for cell in replace(
                    self.plan, cells=all_frozen, max_plastic_cells=0
                ).cells
            ),
            0,
        )

    def test_lineage_coverage_and_population_bounds(self):
        cases = (
            {"cells": self.cells[:-1]},
            {
                "cells": self.cells[:-1]
                + (replace(self.cells[0], cell_id="perc:second"),)
            },
            {
                "cells": self.cells
                + tuple(
                    replace(self.cells[0], cell_id=f"extra:{i}") for i in range(122)
                )
            },
            {"max_plastic_cells": -1},
            {"max_plastic_cells": 4},
            {"max_plastic_cells": True},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(CellError):
                replace(self.plan, **changes)

    def test_kernel_family_and_training_policy_cannot_be_relabelled(self):
        semantic = self.cells[0]
        temporal = self.cells[2]
        for source, changes in (
            (semantic, {"lineage": "ACT"}),
            (semantic, {"trainable": "kernel_and_heads"}),
            (semantic, {"trainable": "cell_adapter_and_heads"}),
            (semantic, {"update_rule": digest("unused-rule")}),
            (temporal, {"kernel": "hcsn"}),
            (temporal, {"kernel": "shared_head"}),
            (temporal, {"lineage": "LEARN"}),
            (temporal, {"update_rule": None}),
            (temporal, {"evaluation_profile": "0" * 64}),
            (temporal, {"family": "deterministic", "kernel": "numerical"}),
        ):
            with self.subTest(changes=changes), self.assertRaises(CellError):
                replace(source, **changes)

    def test_complete_policy_changes_change_commitment(self):
        for changes in (
            {"objective": "different-loss"},
            {"initial_identity": digest("different-parameters")},
            {"budget": Budget(max_work_units=100)},
            {"min_observations": 2},
            {"total_work_units": 2000000},
        ):
            changed = replace(self.cells[0], **changes)
            self.assertNotEqual(
                replace(self.plan, cells=(changed,) + self.cells[1:]).digest,
                self.plan.digest,
            )

    def test_strict_record_fields_and_bounded_types(self):
        for alter in (
            lambda record: record.update(extra=True),
            lambda record: record.pop("max_plastic_cells"),
            lambda record: record.update(schema="hepta.cell.population-plan.v2"),
            lambda record: record["cells"][0].update(extra=True),
            lambda record: record["cells"][0].pop("update_rule"),
            lambda record: record["cells"][0]["budget"].update(extra=1),
            lambda record: record["cells"][0]["budget"].update(max_work_units=True),
            lambda record: record["cells"][0].update(min_observations=True),
            lambda record: record["cells"][0].update(total_work_units=0),
            lambda record: record["cells"][0].update(lineage=["PERC"]),
            lambda record: record["cells"][0].update(objective="x" * 129),
        ):
            record = self.plan.record()
            alter(record)
            with self.subTest(record=record), self.assertRaises(CellError):
                PopulationPlan.from_record(record)

    def test_reject_python_string_subclasses_in_stable_cell_identity(self):
        # A subclass can compare equal to a legal lineage while encoding other bytes.
        source = self.cells[0]
        cases = (
            ("lineage", _SpoofedString("UNLISTED", "PERC")),
            ("kernel", _SpoofedString("UNLISTED", "shared_head")),
            ("family", _SpoofedString("UNLISTED", "shared_semantic")),
            ("trainable", _SpoofedString("UNLISTED", "frozen")),
            ("cell_id", _SpoofedString("other-cell", source.cell_id)),
            (
                "initial_identity",
                _SpoofedString(source.initial_identity, source.initial_identity),
            ),
            ("objective", _SpoofedString(source.objective, source.objective)),
        )
        for field, value in cases:
            with self.subTest(field=field), self.assertRaises(CellError):
                replace(source, **{field: value})
        plastic = next(cell for cell in self.cells if cell.plastic)
        for field in ("update_rule", "evaluation_profile"):
            # A real plastic cell must reject inherited subclasses too.
            canonical = getattr(plastic, field)
            with self.subTest(field=field), self.assertRaises(CellError):
                replace(plastic, **{field: _SpoofedString(canonical, canonical)})

    def test_reject_spoofed_population_owner_and_wire_record_keys(self):
        for field in ("principal_id", "agent_id"):
            canonical = getattr(self.plan, field)
            with self.subTest(field=field), self.assertRaises(CellError):
                replace(self.plan, **{field: _SpoofedString("other-owner", canonical)})
        outer = self.plan.record()
        outer.pop("schema")
        outer[_SpoofedString("fake-schema-key", "schema")] = (
            "hepta.cell.population-plan.v1"
        )
        with self.assertRaises(CellError):
            PopulationPlan.from_record(outer)
        nested = self.cells[0].record()
        nested[_SpoofedString("fake-cell-key", "lineage")] = nested.pop("lineage")
        with self.assertRaises(CellError):
            type(self.cells[0]).from_record(nested)
        budget = self.cells[0].record()
        detail = budget["budget"]
        detail[_SpoofedString("fake-budget-key", "max_work_units")] = detail.pop(
            "max_work_units"
        )
        with self.assertRaises(CellError):
            type(self.cells[0]).from_record(budget)

    def test_population_policy_refuses_subclassed_plan(self):
        import sqlite3
        from hepta_cells.population_owner import PopulationPolicy

        class DerivedPlan(PopulationPlan):
            pass

        with sqlite3.connect(":memory:") as database:
            database.row_factory = sqlite3.Row
            database.execute("CREATE TABLE cells(partition TEXT PRIMARY KEY)")
            with self.assertRaises(CellError):
                PopulationPolicy(
                    database,
                    DerivedPlan(
                        self.plan.principal_id, self.plan.agent_id, self.plan.cells
                    ),
                )


if __name__ == "__main__":
    unittest.main()
