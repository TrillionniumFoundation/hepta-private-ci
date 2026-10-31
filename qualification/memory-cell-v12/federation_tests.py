"""Local protocol tests. Numeric fixtures do not constitute cross-VM evidence."""

import copy
import hashlib
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import unittest

from federation import Authority, Denied, canonical, file_digest, infer, seal_bundle, verify_bundle, write_json
from federation_experiment import candidate, kill_at_boundary


class FederationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binding = dict(run="unit-test-only", source="local-fixture", nonce="unique-test")
        raw = {"head.bias": ([1], [0]), "head.weight": ([1, 2], [1, -1]),
               "hidden.bias": ([2], [0, 0]), "hidden.weight": ([2, 2], [1, 0, 0, 1])}
        arrays, checksum = {}, hashlib.sha256()
        for name, (shape, values) in raw.items():
            data = struct.pack("<" + "f" * len(values), *values)
            arrays[name] = dict(shape=shape, f32le_hex=data.hex())
            checksum.update(canonical([name, shape, "float32"]))
            checksum.update(data)
        self.model = dict(schema="hepta.memory.numpy-mlp.v12", activation="relu", dimension=2,
                          hidden=2, output=1, arrays=arrays, parameter_sha256=checksum.hexdigest())
        self.probes = dict(schema="hepta.memory.v12.probes.v1", inputs=[[1, 0], [0, 1], [-1, 2]],
                           expected_logits=[[1], [-1], [-2]], tolerance=dict(atol=1e-5, rtol=1e-5),
                           model_parameter_sha256=checksum.hexdigest())
        source = self.root / "source"
        source.mkdir()
        write_json(source / "model.json", self.model)
        write_json(source / "probes.json", self.probes)
        self.checkpoint = seal_bundle(source, self.root / "bundle", self.binding)
        self.output = infer(self.root / "bundle", self.binding, self.checkpoint)
        self.control = Authority(self.root / "authority.sqlite", self.binding,
                                 initial=dict(checkpoint=self.checkpoint, probes=self.probes))

    def tearDown(self):
        self.control.close()
        self.temporary.cleanup()

    def read(self, node):
        return candidate(node, self.control.issue(node), copy.deepcopy(self.output))

    def prepared(self):
        result = self.read("replica-a")
        self.control.release(result)
        return dict(binding=self.binding, node="replica-a", epoch=1, checkpoint=self.checkpoint,
                    read_grant=result["ticket"]["grant"], verified_checkpoint=True)

    def test_real_tensor_decode_and_bundle_binding(self):
        self.assertEqual(self.output["logits"], self.probes["expected_logits"])
        with self.assertRaises(Denied):
            verify_bundle(self.root / "bundle", dict(self.binding, nonce="other-run"), self.checkpoint)
        with (self.root / "bundle/model.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaises(Denied):
            infer(self.root / "bundle", self.binding, self.checkpoint)

    def test_tensor_identity_cannot_be_replaced_by_a_manifest_claim(self):
        self.model["parameter_sha256"] = "0" * 64
        write_json(self.root / "source/model.json", self.model)
        bad_checkpoint = seal_bundle(self.root / "source", self.root / "bad", self.binding)
        with self.assertRaises(Denied):
            infer(self.root / "bad", self.binding, bad_checkpoint)

    def test_migration_fences_old_owner_and_inflight_result(self):
        pending, prepared = self.read("source"), self.prepared()
        self.control.migrate("replica-a", expected_epoch=1, expected_owner="source", prepared=prepared)
        self.assertEqual(self.control.state(), dict(epoch=2, owner="replica-a", checkpoint=self.checkpoint, valid=1))
        for epoch in (1, 2):
            with self.assertRaises(Denied):
                self.control.authorize_write("source", epoch, self.checkpoint)
        with self.assertRaises(Denied):
            self.control.release(pending)
        self.assertTrue(self.control.release(self.read("replica-a"))["released"])
        with self.assertRaises(Denied):
            self.control.migrate("replica-a", expected_epoch=1, expected_owner="source", prepared=prepared)

    def test_unacknowledged_preparation_has_no_migration_authority(self):
        result = self.read("replica-a")
        prepared = dict(binding=self.binding, node="replica-a", epoch=1, checkpoint=self.checkpoint,
                        read_grant=result["ticket"]["grant"], verified_checkpoint=True)
        with self.assertRaises(Denied):
            self.control.migrate("replica-a", expected_epoch=1, expected_owner="source", prepared=prepared)
        with self.assertRaises(Denied):
            self.control.authorize_write("replica-a", 1, self.checkpoint)

    def test_output_tampering_grant_mutation_and_replay(self):
        result = self.read("replica-a")
        altered = copy.deepcopy(result)
        altered["output"]["logits"][0][0] += 1
        with self.assertRaises(Denied):
            self.control.release(altered)
        altered = copy.deepcopy(result)
        altered["output"]["query_sha256"] = "0" * 64
        with self.assertRaises(Denied):
            self.control.release(altered)
        altered = copy.deepcopy(result)
        altered["ticket"]["permission"] = "write"
        with self.assertRaises(Denied):
            self.control.release(altered)
        self.control.release(result)
        with self.assertRaises(Denied):
            self.control.release(result)

    def test_revocation_fences_computed_outputs_and_future_grants(self):
        pending, prepared = self.read("source"), self.prepared()
        self.control.revoke(self.checkpoint)
        for operation in (lambda: self.control.release(pending), lambda: self.control.issue("source"),
                          lambda: self.control.authorize_write("source", 2, self.checkpoint),
                          lambda: self.control.migrate("replica-a", expected_epoch=2,
                                  expected_owner="source", prepared=prepared)):
            with self.assertRaises(Denied):
                operation()

    def test_snapshot_rollback_and_event_corruption(self):
        self.control.close()
        shutil.copyfile(self.root / "authority.sqlite", self.root / "old.sqlite")
        self.control = Authority(self.root / "authority.sqlite", self.binding)
        self.control.revoke(self.checkpoint)
        self.control.close()
        anchor = file_digest(self.root / "authority.sqlite")
        with self.assertRaises(Denied):
            Authority(self.root / "old.sqlite", self.binding, expected_anchor=anchor)
        with sqlite3.connect(self.root / "authority.sqlite") as db:
            db.execute("UPDATE events SET body='{}' WHERE seq=1")
        with self.assertRaises(Denied):
            Authority(self.root / "authority.sqlite", self.binding)

    def test_reopen_rejects_revocation_projection_resurrection_without_external_anchor(self):
        self.read("source")
        self.control.revoke(self.checkpoint)
        self.control.close()
        # Preserve the valid revoke event and its hash chain. Only corrupt the
        # materialized table that was previously trusted by release().
        with sqlite3.connect(self.root / "authority.sqlite") as db:
            db.execute("UPDATE state SET epoch=1,valid=1 WHERE id=1")
        with self.assertRaisesRegex(Denied, "disagree with committed history"):
            Authority(self.root / "authority.sqlite", self.binding)

    def test_reopen_rejects_consumed_grant_reset_without_external_anchor(self):
        result = self.read("replica-a")
        self.control.release(result)
        self.control.close()
        # Retain the release event, but roll back only the deduplication bit.
        with sqlite3.connect(self.root / "authority.sqlite") as db:
            db.execute("UPDATE grants SET consumed=0 WHERE id=?", (result["ticket"]["grant"],))
        with self.assertRaisesRegex(Denied, "disagree with committed history"):
            Authority(self.root / "authority.sqlite", self.binding)

    def test_actual_sigkill_before_and_after_commit(self):
        prepared = self.prepared()
        self.control.close()
        write_json(self.root / "crash-request.json", dict(binding=self.binding, prepared=prepared))
        first = kill_at_boundary(self.root, "before_commit")
        self.control = Authority(self.root / "authority.sqlite", self.binding)
        self.assertEqual(self.control.state()["epoch"], 1)
        self.control.close()
        second = kill_at_boundary(self.root, "after_commit")
        self.control = Authority(self.root / "authority.sqlite", self.binding)
        self.assertEqual(self.control.state(), dict(epoch=2, owner="replica-a", checkpoint=self.checkpoint, valid=1))
        self.assertEqual([first["exit_code"], second["exit_code"]], [-9, -9])
        self.assertNotEqual(first["child_pid"], second["child_pid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
