"""Composition crosses real SQLite journals and a real local filesystem effect."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from hepta_cells.deterministic import ExactRetriever, NumericAlgorithm, RuleVerifier, ToolCell, ToolReply
from hepta_cells.lifecycle import Budget, CellOwner, Partition, PendingExecution


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class FileEffectPort:
    """One test-owned file capability with durable original-result readback."""

    def __init__(self, root, lose_ack=True):
        self.root, self.lose_ack, self.calls = Path(root), lose_ack, 0

    def invoke(self, invocation):
        self.calls += 1
        start = time.perf_counter_ns()
        content = json.dumps(invocation.arguments, sort_keys=True).encode()
        with (self.root / "effect.json").open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        output = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        receipt = {"operation_id": invocation.operation_id, "output": output,
                   "work_units": 1, "original_elapsed_ns": time.perf_counter_ns() - start}
        with (self.root / "original-result.json").open("x") as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        if self.lose_ack:
            raise ConnectionError("test loses acknowledgement after the effect and receipt are durable")
        return ToolReply(output, 1, receipt["original_elapsed_ns"])

    def readback(self, invocation):
        receipt = json.loads((self.root / "original-result.json").read_text())
        if receipt["operation_id"] != invocation.operation_id:
            raise ValueError("different original tool operation")
        raw = (self.root / "effect.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["output"]["sha256"]:
            raise ValueError("effect differs from original receipt")
        return ToolReply(receipt["output"], receipt["work_units"], receipt["original_elapsed_ns"])


class ComponentCompositionTests(unittest.TestCase):
    def test_retrieval_verification_numeric_and_effect_share_one_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "owner.sqlite"
            owner = CellOwner(database)
            budget = Budget(max_work_units=128)
            def partition(name):
                return Partition("engineering", "agent", name, "run")
            retriever = ExactRetriever({"accepted": {"permission": "fixture-write", "scale": 2},
                                        "hidden": "must-not-leak"}, digest("corpus"))
            verifier = RuleVerifier([{"field": "permission", "op": "equal", "value": "fixture-write"},
                                     {"field": "scale", "op": "range", "min": 1, "max": 3}], digest("rules"))
            numeric = NumericAlgorithm("dot", digest("numeric"))
            port = FileEffectPort(root)
            tool = ToolCell("fixture-file-write", digest("only-this-test-directory"), port, digest("tool-bundle"))
            try:
                owner.create(partition("retrieve"), retriever, {"keys": ["accepted"]}, budget)
                owner.create(partition("verify"), verifier, budget=budget)
                owner.create(partition("numeric"), numeric, budget=budget)
                owner.create(partition("effect"), tool, budget=budget)
                retrieved = owner.step(partition("retrieve"), retriever, "lookup", {"key": "accepted"})
                hidden = owner.step(partition("retrieve"), retriever, "hidden-lookup", {"key": "hidden"})
                self.assertEqual(hidden["output"], {"found": False, "value": None})
                checked = owner.step(partition("verify"), verifier, "check", retrieved["output"]["value"])
                self.assertTrue(checked["output"]["passed"])
                computed = owner.step(partition("numeric"), numeric, "calculate", {"left": [2, 3], "right": [1, 2]})
                payload = {"verified": checked["output"]["passed"], "value": computed["output"]["value"]}
                with self.assertRaises(PendingExecution):
                    owner.step(partition("effect"), tool, "durable-write", payload)
                original_bytes = (root / "effect.json").read_bytes()
            finally:
                owner.close()

            reopened = CellOwner(database)
            try:
                with self.assertRaises(PendingExecution):
                    reopened.step(partition("effect"), tool, "durable-write", payload)
                recovered = reopened.reconcile(partition("effect"), tool, "durable-write", tool.readback)
                replayed = reopened.step(partition("effect"), tool, "durable-write", payload)
                self.assertEqual(recovered, replayed)
                self.assertEqual(port.calls, 1)
                self.assertEqual((root / "effect.json").read_bytes(), original_bytes)
                self.assertEqual(json.loads(original_bytes), {"value": 8.0, "verified": True})
                self.assertGreater(recovered["elapsed_ns"], 0)
                self.assertEqual(reopened.checkpoint(partition("effect"))["state"], {"completed": 1})
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
