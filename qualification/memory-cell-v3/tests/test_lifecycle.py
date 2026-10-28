"""Durable owner integration: updates, stale restoration, and graph admission."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from v3.lifecycle import (
    FactorOwner,
    atomic_write,
    canonical,
    prepare_version,
    read_regular,
    sha,
)
from v3.numeric_graph import numeric_executor
from v3.learned_graph import GraphQuery, TypedValue


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.root = self.path / "owner"
        self.witness = self.path / "external" / "witness.json"
        self.values = np.arange(48, dtype=np.int32).reshape(4, 12)
        self.years = [2000, 2001, 2002, 2003]
        self.owner = FactorOwner(self.root, self.witness, scope="co2")

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, generation, values, mask=None):
        manifest, _ = prepare_version(
            self.root,
            scope="co2",
            generation=generation,
            years=self.years,
            matrix=values,
            mask=mask,
            rank=2,
        )
        self.owner.publish(generation, expected_generation=generation - 1)
        return manifest

    def test_clean_correction_revoke_reload_and_explicit_residual(self):
        self.publish(1, self.values)
        corrected = self.values.copy()
        corrected[1, 3] = 999
        corrected[2, 4] = 0
        mask = np.ones_like(corrected, dtype=bool)
        mask[2, 4] = False
        self.publish(2, corrected, mask)
        reloaded = FactorOwner(self.root, self.witness, scope="co2")
        self.assertEqual(
            reloaded.read(
                [(2001, 4), (2002, 5), (2005, 2)], generation=2, mode="lossless_codec"
            ),
            [999, None, None],
        )
        with self.assertRaises(ValueError):
            reloaded.read([(2001, 4)], generation=1)
        self.assertEqual(reloaded.parameter_read_calls, 0)

    def test_old_pointer_restore_and_tampered_artifact_fail_before_read(self):
        self.publish(1, self.values)
        old = (self.root / "active.json").read_bytes()
        self.publish(2, self.values + 1)
        latest = (self.root / "active.json").read_bytes()
        (self.root / "active.json").write_bytes(old)
        with self.assertRaises(ValueError):
            self.owner.read([(2000, 1)], generation=1)
        (self.root / "active.json").write_bytes(latest)
        artifact = self.root / "versions" / "2" / "memory.factor"
        raw = artifact.read_bytes()
        artifact.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(ValueError):
            self.owner.read([(2000, 1)], generation=2)
        self.assertEqual(self.owner.parameter_read_calls, 0)

    def test_wrong_bindings_and_midpath_publication_block_stale_graph(self):
        first = self.publish(1, self.values)
        with self.assertRaises(ValueError):
            self.owner.admission_check(1, "c01", "0" * 64, first["frontier_sha256"])
        with self.assertRaises(ValueError):
            self.owner.admission_check(1, "c01", first["model_sha256"], "0" * 64)
        calls = []

        def admission(generation, operation, artifact, frontier):
            self.owner.admission_check(generation, operation, artifact, frontier)
            calls.append(operation)
            if len(calls) == 1:
                self.publish(2, self.values + 10)

        executor = numeric_executor(
            "co2",
            lambda coordinates: self.owner.read(coordinates, generation=1),
            generation=1,
            admission_check=admission,
            artifact_bindings={name: first["model_sha256"] for name in ("c02", "c01")},
            source_frontier_digest=first["frontier_sha256"],
        )
        with self.assertRaises(ValueError):
            executor.run(
                ("c02", "c01"),
                TypedValue("address", (2001, 2)),
                GraphQuery("numeric-study", "previous", "co2"),
                expected_generation=1,
            )
        self.assertEqual((calls, self.owner.parameter_read_calls), (["c02"], 0))

    def test_interrupted_witness_commit_rolls_forward_only_with_durable_intent(self):
        self.publish(1, self.values)
        prepare_version(
            self.root,
            scope="co2",
            generation=2,
            years=self.years,
            matrix=self.values + 1,
            rank=2,
        )

        def fail_active(path, payload):
            if Path(path).name == "active.json":
                raise OSError("simulated process loss after witness commitment")
            atomic_write(path, payload)

        with patch("v3.lifecycle.atomic_write", side_effect=fail_active):
            with self.assertRaises(OSError):
                self.owner.publish(2, expected_generation=1)
        recovered = FactorOwner(self.root, self.witness, scope="co2")
        self.assertEqual(recovered.recover()["generation"], 2)
        self.assertEqual(
            recovered.read([(2000, 1)], generation=2, mode="lossless_codec"), [1]
        )
        self.assertFalse((self.root / "publication-intent.json").exists())

    def test_parameter_reader_needs_no_residual_and_uses_verified_address_bytes(self):
        self.publish(1, self.values)
        (self.root / "versions/1/residual.codec").unlink()
        reader = FactorOwner(self.root, self.witness, scope="co2")
        address_reads = []

        def observed_read(path, limit=128_000_000):
            raw = read_regular(path, limit)
            if Path(path).name == "addresses.json":
                address_reads.append(raw)
            return raw

        with patch("v3.lifecycle.read_regular", side_effect=observed_read):
            reader.recover()
        self.assertEqual(len(address_reads), 1)
        self.assertEqual(reader.read([(2001, 1)], generation=1), [12])
        with self.assertRaises(ValueError):
            reader.read([(2001, 1)], generation=1, mode="lossless_codec")

    def test_invalid_prepared_model_cannot_advance_the_published_witness(self):
        self.publish(1, self.values)
        prepare_version(
            self.root,
            scope="co2",
            generation=2,
            years=self.years,
            matrix=self.values + 1,
            rank=2,
        )
        directory = self.root / "versions" / "2"
        model = directory / "memory.factor"
        raw = b"INVALID!" + model.read_bytes()[8:]
        model.write_bytes(raw)
        manifest_file = directory / "manifest.json"
        manifest = json.loads(manifest_file.read_bytes())
        manifest["model_sha256"] = sha(raw)
        manifest_file.write_bytes(canonical(manifest))
        before = (self.witness.read_bytes(), (self.root / "active.json").read_bytes())
        with self.assertRaises(ValueError):
            self.owner.publish(2, expected_generation=1)
        self.assertEqual(
            (self.witness.read_bytes(), (self.root / "active.json").read_bytes()),
            before,
        )
        self.assertEqual(self.owner.read([(2001, 1)], generation=1), [12])


if __name__ == "__main__":
    unittest.main()
