import hashlib
import unittest
from dataclasses import replace

from hepta_cells.bundle import Bundle, reset_cutover_digest, validate_local_update


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    components = {
        key: digest(value)
        for key, value in (
            ("base", "base"),
            ("heads", "heads"),
            ("composition", "composition"),
            ("encoder", "encoder"),
            ("tokenizer", "tokenizer"),
            ("normalizer", "normalizer"),
            ("calibration", "calibration"),
            ("numeric_profile", "numeric"),
            ("output_schema", "output"),
            ("state_schema", "schema"),
            ("state_semantics", "semantics"),
        )
    }
    components.update(organ_adapter=None, cell_adapter=None)
    base = Bundle("artifact:base", 1, components)
    candidate = base.successor(
        "artifact:next",
        dict(components, heads=digest("trained-heads")),
        digest("dataset"),
        digest("rule"),
        digest("evaluation"),
    )
    return base, candidate


class BundleTests(unittest.TestCase):
    def test_native_compatibility_bundle_and_reset_conformance(self):
        base, candidate = fixture()
        partition = dict(
            principal_id="principal:one",
            agent_id="agent:one",
            cell_id="cell:one",
            run_id="run:next",
        )
        plan = reset_cutover_digest(
            "cutover:one",
            "owner:state",
            partition,
            base,
            candidate,
            digest("initializer"),
            digest("reset"),
        )
        self.assertEqual(
            (base.digest(), candidate.digest(), plan),
            (
                "50c9be0c39fe042b5f88525823511181448080cdac871815201735cb0986dda1",
                "6cd309665ea081b3dfa00433df7d8643860e4be00a285fb48e0fd87ea3983d6d",
                "900f2fd17f892c382d69ab31ced5db8fdac81dd293297263f103d785013e5db8",
            ),
        )

    def test_frozen_base_domain_and_state_cannot_change_in_local_training(self):
        base, candidate = fixture()
        self.assertEqual(
            validate_local_update("shared_semantic", base, candidate),
            candidate.digest(),
        )
        for key in (
            "base",
            "organ_adapter",
            "encoder",
            "state_semantics",
            "composition",
            "cell_adapter",
        ):
            wrong = replace(
                candidate,
                components=dict(candidate.components, **{key: digest("wrong")}),
            )
            with self.subTest(component=key), self.assertRaises(ValueError):
                validate_local_update("shared_semantic", base, wrong)

    def test_explicit_adapter_and_temporal_scopes(self):
        base, candidate = fixture()
        adapter = replace(
            candidate,
            components=dict(candidate.components, cell_adapter=digest("adapter")),
        )
        self.assertEqual(
            validate_local_update(
                "shared_semantic", base, adapter, "cell_adapter_and_heads"
            ),
            adapter.digest(),
        )
        temporal = replace(
            candidate, components=dict(candidate.components, base=digest("new-kernel"))
        )
        self.assertEqual(
            validate_local_update(
                "stateful_temporal", base, temporal, "kernel_and_heads"
            ),
            temporal.digest(),
        )
        with self.assertRaises(ValueError):
            validate_local_update("deterministic", base, candidate)

    def test_invalid_or_noop_successor_rejected(self):
        base, candidate = fixture()
        invalid = [
            replace(candidate, generation=3),
            replace(candidate, components=base.components),
            replace(candidate, training_lineage=None),
            replace(candidate, generation=True),
            replace(candidate, rollback_predecessor=digest("wrong")),
            replace(candidate, components=dict(candidate.components, heads="0" * 64)),
        ]
        for item in invalid:
            with self.assertRaises(ValueError):
                validate_local_update("shared_semantic", base, item)

    def test_rollback_is_new_successor_and_partition_affects_plan(self):
        base, candidate = fixture()
        rollback = candidate.successor(
            "artifact:rollback",
            base.components,
            digest("dataset"),
            digest("rollback"),
            digest("evaluation"),
        )
        self.assertEqual(
            validate_local_update("shared_semantic", candidate, rollback),
            rollback.digest(),
        )
        p = dict(principal_id="p", agent_id="a", cell_id="c", run_id="r")
        first = reset_cutover_digest(
            "op", "owner", p, candidate, rollback, digest("i"), digest("t")
        )
        second = reset_cutover_digest(
            "op",
            "owner",
            dict(p, cell_id="other"),
            candidate,
            rollback,
            digest("i"),
            digest("t"),
        )
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
