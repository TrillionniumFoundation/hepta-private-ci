"""Canonical stable IDs for the experimental Cell population boundary.

These tests validate exact Python value types, not native owner authentication.
"""

from dataclasses import replace
import unittest

from hepta_cells.component_types import (
    CellError,
    ComponentIdentity,
    Partition,
    Qualification,
    digest,
)
from hepta_cells.population import PopulationPlan
from test_hepta_cells_population_plan import population_cells


class _ImpersonatedString(str):
    """Wire spelling differs from equality/hash comparisons to trusted IDs."""

    def __new__(cls, actual: str, impersonated: str):
        value = str.__new__(cls, actual)
        value.impersonated = impersonated
        return value

    def __reduce_ex__(self, protocol):
        return (type(self), (str(self), self.impersonated))

    def __eq__(self, other):
        return other == self.impersonated

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.impersonated)


class CanonicalStableIdentityTests(unittest.TestCase):
    def test_partition_owner_cell_and_run_ids_reject_subclass_identity(self):
        original = Partition("principal:one", "agent:one", "mem", "run:one")
        plan = PopulationPlan("principal:one", "agent:one", population_cells())
        self.assertEqual(plan.spec(original).cell_id, "mem")
        for field, actual, impersonated in (
            ("principal_id", "principal:other", "principal:one"),
            ("agent_id", "agent:other", "agent:one"),
            ("cell_id", "another-cell", "mem"),
            ("run_id", "run:other", "run:one"),
        ):
            with self.subTest(field=field), self.assertRaises(CellError):
                partition = replace(
                    original,
                    **{field: _ImpersonatedString(actual, impersonated)},
                )
                plan.spec(partition)

    def test_component_identity_rejects_subclass_and_noncanonical_digest(self):
        good = digest(["real-bundle"])
        original = ComponentIdentity("shared_head", good)
        self.assertEqual(len(original.digest), 64)
        for field, value in (
            ("implementation", _ImpersonatedString("wrong", "shared_head")),
            ("bundle_digest", _ImpersonatedString("0" * 64, good)),
            ("configuration_digest", _ImpersonatedString("0" * 64, good)),
        ):
            with self.subTest(field=field), self.assertRaises(CellError):
                replace(original, **{field: value})

    def test_qualification_rejects_subclass_digest(self):
        good = digest(["real-evaluation"])
        original = Qualification(good, good, good)
        for field in ("source_identity", "candidate_identity", "evaluation_digest"):
            with self.subTest(field=field), self.assertRaises(CellError):
                replace(original, **{field: _ImpersonatedString("0" * 64, good)})


if __name__ == "__main__":
    unittest.main()
