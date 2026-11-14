import json
import ast
from pathlib import Path
import subprocess
import sys
import unittest

from typed_memory_cell_contract import (
    AUTHORITY,
    CompressedPayload,
    LineageError,
    MODE,
    MemoryCell,
    MemoryContractError,
    MemoryRegistry,
    MemoryTypeError,
    RetrievalDenied,
    TombstonedMemoryError,
    WrongMemoryType,
    digest_payload,
    run,
)


class TypedMemoryTests(unittest.TestCase):
    def test_split_and_seed_reproducible(self):
        self.assertEqual(run(17), run(17))
        self.assertNotEqual(run(17), run(18))
        self.assertTrue(run(17)["non_resurrection"])

    def test_type_and_budget_contract(self):
        with self.assertRaises(MemoryTypeError):
            digest_payload("unknown", "x")
        cell = MemoryCell("m", "episodic", digest_payload("episodic", "x"), 4, "0" * 64, 10, 2)
        cell.validate()
        with self.assertRaises(MemoryContractError):
            MemoryCell("bad", "semantic", "x", 0, "0" * 64, 1, 1).validate()

    def test_tombstone_non_resurrection(self):
        registry = MemoryRegistry()
        parent = MemoryCell("p", "procedural", digest_payload("procedural", "root"), 8, "0" * 64, 100, 10)
        registry.add(parent)
        child = registry.split("p", (("a", "payload"),))[0]
        registry.tombstone(child.cell_id, "delete")
        with self.assertRaises(TombstonedMemoryError):
            registry.get(child.cell_id)
        with self.assertRaises(MemoryContractError):
            registry.add(child)

    def test_compressed_payload_digest_is_immutable_and_verified(self):
        payload = CompressedPayload.from_text("episodic event")
        self.assertEqual(payload.decode(), "episodic event")
        self.assertEqual(len(payload.raw_digest), 64)
        self.assertEqual(len(payload.compressed_digest), 64)
        with self.assertRaises(TypeError):
            payload.compressed[0] = 0
        # A digest-only legacy Cell remains accepted, but a payload-bearing
        # Cell verifies its compressed byte count and digest at registration.
        cell = MemoryCell(
            "immutable",
            "episodic",
            digest_payload("episodic", "episodic event"),
            payload.compressed_size,
            "0" * 64,
            32,
            10,
            compressed_digest=payload.compressed_digest,
            raw_digest=payload.raw_digest,
            payload_text="episodic event",
        )
        cell.validate()

    def test_parent_child_split_budget_and_rollback_lineage(self):
        registry = MemoryRegistry()
        parent = MemoryCell("p2", "procedural", digest_payload("procedural", "root"), 8, "0" * 64, 100, 10)
        registry.add(parent)
        children = registry.split("p2", (("a", "step-a"), ("b", "step-b")), memory_type="semantic")
        self.assertEqual({child.memory_type for child in children}, {"semantic"})
        self.assertEqual(sum(child.budget_flops for child in children), parent.budget_flops)
        self.assertTrue(all(child.parent_digest == parent.digest for child in children))
        initial = registry._lineage[parent.cell_id][0]
        self.assertEqual(registry.rollback(parent.cell_id, initial.artifact_digest), initial)
        with self.assertRaises(LineageError):
            registry.rollback(parent.cell_id, "f" * 64)

    def test_retention_watermark_and_retrieval_authority_fail_closed(self):
        registry = MemoryRegistry()
        payload = CompressedPayload.from_text("temporary working state")
        cell = MemoryCell(
            "expiring",
            "working",
            digest_payload("working", "temporary working state"),
            payload.compressed_size,
            "0" * 64,
            32,
            2,
            compressed_digest=payload.compressed_digest,
            raw_digest=payload.raw_digest,
            payload_text="temporary working state",
        )
        registry.add(cell)
        self.assertEqual(len(registry.retrieve("working", cell.payload_digest)), 1)
        with self.assertRaises(RetrievalDenied):
            registry.retrieve("working", cell.payload_digest, authority="ALLOW")
        with self.assertRaises(RetrievalDenied):
            registry.retrieve("working", cell.payload_digest, capability=("decode",))
        expired = registry.advance(2)
        self.assertEqual(expired[0].cell_id, cell.cell_id)
        self.assertEqual(registry.retrieve("working", cell.payload_digest), [])
        with self.assertRaises(TombstonedMemoryError):
            registry.rollback(cell.cell_id, registry._lineage[cell.cell_id][0].artifact_digest)

    def test_wrong_type_and_standard_library_only(self):
        registry = MemoryRegistry()
        cell = MemoryCell("typed", "episodic", digest_payload("episodic", "x"), 4, "0" * 64, 10, 2)
        registry.add(cell)
        with self.assertRaises(WrongMemoryType):
            cell.decode("semantic")
        source = Path(__file__).with_name("typed_memory_cell_contract.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        self.assertTrue({"torch", "tensorflow", "jax", "numpy", "pandas"}.isdisjoint(roots))

    def test_retrieval_is_type_scoped(self):
        registry = MemoryRegistry()
        parent = MemoryCell("w", "working", digest_payload("working", "x"), 8, "0" * 64, 100, 10)
        registry.add(parent)
        self.assertEqual(len(registry.retrieve("working", parent.payload_digest)), 1)
        self.assertEqual(registry.retrieve("semantic", parent.payload_digest), [])

    def test_protocol_and_cli(self):
        result = run(17)
        self.assertEqual(result["mode"], MODE)
        self.assertEqual(result["authority"], AUTHORITY)
        payload = json.loads(subprocess.run([sys.executable, "typed_memory_cell_contract.py", "--seed", "17"], check=True, capture_output=True, text=True).stdout)
        self.assertTrue(payload["protocol"]["compression_is_digest_only"])


if __name__ == "__main__":
    unittest.main()
