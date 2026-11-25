#!/usr/bin/env python3
"""Focused negative checks for resume identity and irreversible candidate freezing."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from sufficient import State, digest, encode, message_id, signed_message, synthetic


class ProtocolStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.args = SimpleNamespace(node="ai395", model=str(Path(__file__).resolve().parents[1] / "multihost.py"),
                                    root=str(self.root), round_id="negative-test", size=8, seed=271822,
                                    resume=False, external=None)
        self.state = State(self.args)

    def tearDown(self):
        self.directory.cleanup()

    def resumed(self, **changes):
        args = copy.copy(self.args)
        args.resume = True
        for key, value in changes.items():
            setattr(args, key, value)
        return State(args)

    def rewrite_ledger(self, mutate):
        value = json.loads(self.state.ledger.read_text())
        mutate(value["body"])
        value["sha256"] = digest(value["body"])
        self.state.ledger.write_bytes(encode(value))

    def test_resume_cli_identity(self):
        for changed in ({"size": 16}, {"seed": self.args.seed + 1}, {"node": "pocket4"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.resumed(**changed)

    def test_resume_recomputes_boundary(self):
        self.rewrite_ledger(lambda body: body["artifact"]["parent"].__setitem__(0, 11.0))
        with self.assertRaisesRegex(ValueError, "boundary"):
            self.resumed()

    def test_parent_and_ridge_types(self):
        for field, value in (("parent", True), ("parent", float("inf")), ("ridge", True), ("ridge", float("nan"))):
            with self.subTest(field=field, value=value):
                artifact = copy.deepcopy(self.state.artifact)
                if field == "parent":
                    artifact["parent"][0] = value
                else:
                    artifact["objective"]["ridge"] = value
                with self.assertRaises(ValueError):
                    self.state.validate_artifact(artifact)

    def test_semantic_deduplication(self):
        original = {k: v for k, v in self.state.own[0].items() if k != "payload_hash"}
        changed = copy.deepcopy(original)
        changed["data_hash"] = digest(["other data"])
        changed["id"] = message_id(changed, self.state.header)
        self.assertEqual(self.state.accept(signed_message(changed)), "rejected_batch_conflict")
        changed = copy.deepcopy(original)
        changed["node"] = "pocket4"
        changed["id"] = message_id(changed, self.state.header)
        self.assertEqual(self.state.accept(signed_message(changed)), "rejected_duplicate_data")
        self.assertEqual(len(self.state.messages), 4)

    def test_negative_gram_rejected(self):
        changed = {k: copy.deepcopy(v) for k, v in self.state.own[0].items() if k != "payload_hash"}
        changed.update(node="pocket4", data_hash=digest(["different data"]))
        changed["id"] = message_id(changed, self.state.header)
        changed["gram"][0][0] = -100000.0
        self.assertEqual(self.state.accept(signed_message(changed)), "rejected_non_psd")

    def test_published_round_is_frozen(self):
        artifact = synthetic(self.state.model, "pocket4", self.args.size, self.args.seed)
        for batch in artifact["batches"]:
            body = {**self.state.header, **batch, "node": "pocket4"}
            body["id"] = message_id(body, self.state.header)
            self.assertEqual(self.state.accept(signed_message(body)), "accepted")
        exported = self.state.solve()
        expected = self.state.solution["candidate_sha256"]
        exported["candidate"][0] += 100.0
        self.assertEqual(self.state.solution["candidate_sha256"], expected)
        self.assertEqual(self.state.accept(self.state.own[0]), "rejected_finalized")
        with self.assertRaises(ValueError):
            self.state.solve()
        self.state.finish({"test": True})
        with self.assertRaisesRegex(ValueError, "cannot resume"):
            self.resumed()


if __name__ == "__main__":
    unittest.main(verbosity=2)
