"""Synthetic audit corruption checks; the independently authored fixture is never opened."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve()
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parents[2] / "memory-cell-v7"))
sys.path.insert(0, str(ROOT.parents[1]))

from evidence import canonical, digest, transitions
from learning.paired import paired_catalog
from learning.byte_model import paired_bytes
from model_evidence import audit_pairs


def development_export(count):
    records = []
    for index in range(count):
        for kind, value in (("event", index + 4), ("semantic", {"factor": index - 3, "label": f"开发{index}"}),
                            ("procedure", {"opcode": "affine", "bias": 2 - index, "limit": 50})):
            record = {"schema": "hepta.memory.cell-record.v1", "entity": f"entity:scorer-dev-{index}",
                      "kind": kind, "effective_at": 20, "value": value}
            records.append({"source_id": digest(canonical(record)), "revision": 1,
                            "owner_memory_id": f"memory:{index}:{kind}", "record": record})
    return {"schema": "hepta.memory.owner-snapshot.v1", "owner_agent_id": "agent:dev", "scope": "scope:dev",
            "owner_cut_digest": digest(canonical(records)), "observed_at_unix_seconds": 100,
            "records": records, "withdrawn_addresses": [], "current_source_ids": [row["source_id"] for row in records]}


class EvidenceTests(unittest.TestCase):
    def test_raw_models_verify_and_corruption_or_value_sidecar_fails(self):
        for representation, train in (("catalog", paired_catalog), ("byte", paired_bytes)):
            with self.subTest(representation=representation):
                old_export = development_export(2)
                old = train(old_export, {})
                _, old_models = audit_pairs(old, old_export, representation, None)
                export = development_export(3)
                fit = train(export, old["artifacts"]["trained"])
                audit, _ = audit_pairs(fit, export, representation, old_models)
                self.assertTrue(audit["semantic"]["clean_rebuild_exact_f32_equal"])
                corrupted = deepcopy(fit)
                corrupted["rebuilds"]["semantic"] = deepcopy(fit["artifacts"]["zero"]["semantic"])
                with self.assertRaisesRegex(ValueError, "second clean"):
                    audit_pairs(corrupted, export, representation, old_models)
                if representation == "byte":
                    from evidence import decode
                    corrupted = deepcopy(fit)
                    native = decode(corrupted["artifacts"]["trained"]["semantic"]["native"])
                    native["target_values"] = [1, 2, 3]
                    corrupted["artifacts"]["trained"]["semantic"]["native"] = canonical(native).decode()
                    with self.assertRaisesRegex(ValueError, "external value table"):
                        audit_pairs(corrupted, export, representation, old_models)

    def test_itemwise_retention_detects_losses_hidden_by_unchanged_accuracy(self):
        self.assertEqual(transitions({"a": True, "b": False}, {"a": False, "b": True}),
                         {"retained": 0, "lost": 1, "gained": 1, "still_wrong": 0})
        with self.assertRaisesRegex(ValueError, "inventory"):
            transitions({"a": True}, {"b": True})


if __name__ == "__main__":
    unittest.main()
