"""Adversarial native-wire type checks; no owner or adoption authority."""

import hashlib
from dataclasses import replace
import unittest

from hepta_cells.bundle import Bundle, reset_cutover_digest, stable_id_bytes


class ForgedEncoding(str):
    """Equals the approved StableId but encodes different bytes on demand."""

    def encode(self, encoding="ascii", errors="strict"):
        return b"unrelated-encoded-id"


def digest(label):
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def fixture():
    names = (
        "base",
        "heads",
        "composition",
        "encoder",
        "tokenizer",
        "normalizer",
        "calibration",
        "numeric_profile",
        "output_schema",
        "state_schema",
        "state_semantics",
    )
    source = Bundle(
        "artifact:source",
        2,
        {
            **{name: digest(name) for name in names},
            "organ_adapter": None,
            "cell_adapter": None,
        },
    )
    candidate = source.successor(
        "artifact:candidate",
        dict(source.components, heads=digest("new-head")),
        digest("dataset"),
        digest("rule"),
        digest("evaluation"),
    )
    return source, candidate


class NativeStableIdWireTests(unittest.TestCase):
    def test_plain_native_stable_id_wire_is_unchanged(self):
        label = "principal:one"
        wire = len(label).to_bytes(4, "big") + label.encode("ascii")
        self.assertEqual(stable_id_bytes(label), wire)
        source, candidate = fixture()
        self.assertNotEqual(source.digest(), candidate.digest())

    def test_lookalike_python_str_cannot_override_bundle_wire(self):
        source, _ = fixture()
        disguised = ForgedEncoding(source.artifact_id)
        self.assertEqual(disguised, source.artifact_id)
        self.assertNotEqual(disguised.encode(), source.artifact_id.encode())
        with self.assertRaisesRegex(ValueError, "invalid native StableId"):
            stable_id_bytes(disguised)
        with self.assertRaisesRegex(ValueError, "invalid native StableId"):
            replace(source, artifact_id=disguised).digest()

    def test_lookalike_partition_and_owner_cannot_change_reset_wire(self):
        source, candidate = fixture()
        partition = dict(
            principal_id="principal:one",
            agent_id="agent:one",
            cell_id="cell:one",
            run_id="run:one",
        )
        args = (
            "operation:one",
            "state:owner",
            partition,
            source,
            candidate,
            digest("initializer"),
            digest("checkpoint"),
        )
        self.assertEqual(len(reset_cutover_digest(*args)), 64)
        for key in partition:
            with self.subTest(field=key):
                altered = dict(partition, **{key: ForgedEncoding(partition[key])})
                with self.assertRaisesRegex(ValueError, "invalid native StableId"):
                    reset_cutover_digest(args[0], args[1], altered, *args[3:])
        for index in (0, 1):
            with self.subTest(role=index):
                altered = list(args)
                altered[index] = ForgedEncoding(altered[index])
                with self.assertRaisesRegex(ValueError, "invalid native StableId"):
                    reset_cutover_digest(*altered)


if __name__ == "__main__":
    unittest.main()
