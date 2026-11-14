"""Fail-closed canonical identity tests for the experimental native-compatible Bundle.

These tests do not confer native owner authorization or model efficacy.
"""

from dataclasses import replace
import hashlib
import unittest

from hepta_cells.bundle import (
    Bundle,
    OPTIONAL,
    REQUIRED,
    digest_bytes,
    stable_id_bytes,
    validate_local_update,
)


class _SpoofedString(str):
    """Wire bytes differ from the identity that Python equality impersonates."""

    def __new__(cls, wire_value, impersonated):
        result = str.__new__(cls, wire_value)
        result.impersonated = impersonated
        return result

    def __eq__(self, other):
        return other == self.impersonated

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.impersonated)

    def __reduce_ex__(self, protocol):
        return (type(self), (str(self), self.impersonated))


def _sha(label):
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _source():
    components = {key: _sha(key) for key in REQUIRED}
    components.update({key: None for key in OPTIONAL})
    return Bundle("fixture:parent", 1, components)


def _successor(source):
    components = dict(source.components, heads=_sha("new-head"))
    return source.successor(
        "fixture:child", components, _sha("dataset"),
        _sha("rule"), _sha("frozen-eval"),
    )


class BundleCanonicalIdentityTests(unittest.TestCase):
    def test_native_stable_id_and_digest_reject_subclass(self):
        for callback, value in (
            (stable_id_bytes, _SpoofedString("fake-id", "genuine-id")),
            (digest_bytes, _SpoofedString(_sha("fake"), _sha("real"))),
        ):
            with self.subTest(callback=callback.__name__):
                with self.assertRaises(ValueError):
                    callback(value)

    def test_bundle_rejects_noncanonical_outer_and_component_fields(self):
        source = _source()
        self.assertEqual(source.record()["artifact_id"], "fixture:parent")
        changed_head = dict(source.components)
        changed_head["heads"] = _SpoofedString(_sha("wire"), _sha("heads"))
        for forged in (
            replace(
                source,
                artifact_id=_SpoofedString("wire-artifact", "fixture:parent"),
            ),
            replace(source, components=changed_head),
        ):
            with self.subTest(field=type(forged.artifact_id).__name__):
                with self.assertRaises(ValueError):
                    forged.record()

    def test_component_and_lineage_keys_reject_subclass_equalities(self):
        source = _source()
        component_keys = dict(source.components)
        component_keys[_SpoofedString("hidden-head-key", "heads")] = (
            component_keys.pop("heads")
        )
        with self.assertRaises(ValueError):
            replace(source, components=component_keys).record()
        successor = _successor(source)
        lineage_keys = dict(successor.training_lineage)
        lineage_keys[_SpoofedString("hidden-parent-key", "source_bundle")] = (
            lineage_keys.pop("source_bundle")
        )
        with self.assertRaises(ValueError):
            replace(successor, training_lineage=lineage_keys).record()

    def test_immediate_successor_cannot_spoof_parent_digest(self):
        source = _source()
        candidate = _successor(source)
        self.assertEqual(
            validate_local_update("shared_semantic", source, candidate, "heads"),
            candidate.digest(),
        )
        forged = replace(
            candidate,
            rollback_predecessor=_SpoofedString(
                _sha("unrelated-parent"), source.digest()
            ),
        )
        with self.assertRaises(ValueError):
            validate_local_update("shared_semantic", source, forged, "heads")


    def test_rejects_derived_bundle_containers_and_policy_strings(self):
        source = _source()
        candidate = _successor(source)

        class _DerivedBundle(Bundle):
            pass

        for corrupted in (
            replace(source, components=type("HiddenDict", (dict,), {})(
                source.components
            )),
            replace(candidate, training_lineage=type("HiddenDict", (dict,), {})(
                candidate.training_lineage
            )),
        ):
            with self.subTest(container=type(corrupted.components).__name__):
                with self.assertRaises(ValueError):
                    corrupted.digest()
        for args in (
            (_DerivedBundle(**source.record()), candidate, "shared_semantic", "heads"),
            (source, candidate, _SpoofedString("invalid", "shared_semantic"), "heads"),
            (source, candidate, "shared_semantic", _SpoofedString("invalid", "heads")),
        ):
            with self.subTest(scope=args[2:]), self.assertRaises(ValueError):
                validate_local_update(args[2], args[0], args[1], args[3])


if __name__ == "__main__":
    unittest.main()
