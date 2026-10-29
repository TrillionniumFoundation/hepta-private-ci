"""Synthetic operational ancestry and completion barriers; no Torch or task calls."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import endpoint_v2 as v2


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class EndpointV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def ancestor(self):
        source = self.root / "science.py"
        source.write_text("# synthetic immutable source\n")
        protocol = "1" * 64
        old = {"allowed_phases": ["C"], "registered_commit": "a" * 40, "protocol_sha256": protocol,
               "source_files": {source.name: v2.file_hash(source)}}
        oldpath = self.root / "old-freeze.json"
        write(oldpath, old)
        original = {"path": str(oldpath), "sha256": v2.file_hash(oldpath), "registered_commit": old["registered_commit"],
                    "protocol_sha256": protocol, "source_root": str(self.root)}
        parent = {**old, "registered_commit": "b" * 40, "attempt_id": "attempt02", "execution_kind": "training",
                  "operational_amendment_sha256": "2" * 64, "scientific_parent": original}
        path = self.root / "actual-freeze.json"
        write(path, parent)
        descriptor = {**original, "path": str(path), "sha256": v2.file_hash(path), "registered_commit": parent["registered_commit"]}
        registration = {"attempt_id": "attempt02", "_sha256": "2" * 64, "original_protocol": {"sha256": protocol},
                        "original_source_freezes": {"C": original}}
        return parent, descriptor, registration

    def test_actual_attempt_parent_preserves_exact_scientific_ancestry(self):
        parent, descriptor, registration = self.ancestor()
        old = parent["scientific_parent"]
        with patch.dict(v2.KNOWN_PARENTS, {"C": (old["sha256"], old["registered_commit"])}):
            self.assertEqual(v2.parent_freeze("C", descriptor, registration), parent)
            original = {**old}
            with self.assertRaisesRegex(ValueError, "Actual checkpoint parent"):
                v2.parent_freeze("C", original, registration)
            parent["source_files"] = {"science.py": "9" * 64}
            write(Path(descriptor["path"]), parent)
            descriptor["sha256"] = v2.file_hash(descriptor["path"])
            with self.assertRaisesRegex(ValueError, "changed an originally frozen"):
                v2.parent_freeze("C", descriptor, registration)

    def test_operation_completion_is_required_and_binds_actual_bytes(self):
        descriptor = {"sha256": "3" * 64}
        parent = {"operational_amendment_sha256": "4" * 64, "protocol_sha256": "5" * 64}
        with self.assertRaisesRegex(ValueError, "did not complete"):
            v2.operation_complete(self.root, "C", None, descriptor, parent)
        target = self.root / "stage_C/COMPLETE.json"
        write(target, {"complete": True, "synthetic": True})
        receipt = {"schema": "hepta.fullstudy.training-operation.2", "complete": True, "phase": "C", "seed": None,
                   "attempt_id": "attempt02", "source_freeze_sha256": descriptor["sha256"],
                   "operational_amendment_sha256": parent["operational_amendment_sha256"], "post_execution_storage_check": True,
                   "scientific_complete": {"path": "stage_C/COMPLETE.json", "bytes": target.stat().st_size, "sha256": v2.file_hash(target)}}
        write(self.root / "operations/C-all.COMPLETE.json", receipt)
        self.assertEqual(v2.operation_complete(self.root, "C", None, descriptor, parent), receipt)
        collector = Mock(return_value="synthetic inventory")
        with patch.object(v2, "c", SimpleNamespace(collect_checkpoints=collector)):
            self.assertEqual(v2.collect_c(self.root, "plan", "runtime", descriptor, parent), "synthetic inventory")
        collector.assert_called_once_with(self.root, "plan", parent, descriptor["sha256"], parent["protocol_sha256"], "runtime")
        target.write_text('{"complete":false}')
        with self.assertRaisesRegex(ValueError, "actual scientific completion"):
            v2.operation_complete(self.root, "C", None, descriptor, parent)

    def test_final_access_uses_scorer_identity_and_rejects_subsets(self):
        expected = {f"{a}-{s}-{m}": None for a in ("ordinary", "dual") for s in range(801, 809)
                    for m in ("ordinary", "field12", "frozen")}
        entries = [{"id": key, "path": key + ".bin", "bytes": 1, "sha256": "7" * 64} for key in expected]
        source, freeze = self.root / "allocation.json", self.root / "scorer.json"
        write(source, {"synthetic": True})
        write(freeze, {"registered_commit": "c" * 40})
        args = SimpleNamespace(phase="C", assets="not-opened", source_manifest=str(source), freeze=str(freeze))
        inventory = {"stage": str(self.root), "entries": entries, "complete_sha256": "8" * 64}
        loader = Mock(return_value="synthetic corpus")
        gate = SimpleNamespace(CHECKPOINT_SCHEMA="checkpoints", FREEZE_SCHEMA="access", _barrier=Mock(), load_new_roles=loader)
        sizes = []
        with patch.object(v2, "c", SimpleNamespace(expected_ids=lambda: expected)), patch.object(v2, "sources", gate):
            with self.assertRaisesRegex(ValueError, "subset"):
                v2.endpoint_corpus(args, {**inventory, "entries": entries[:-1]}, {"registered_commit": "c" * 40}, sizes.append)
            loader.assert_not_called()
            corpus, access = v2.endpoint_corpus(args, inventory, {"registered_commit": "c" * 40}, sizes.append)
        self.assertEqual(corpus, "synthetic corpus")
        self.assertEqual(loader.call_args.args[2], ["final_task", "final_clean"])
        stored = json.loads(Path(access["freeze_path"]).read_text())
        self.assertEqual(stored["scorer_freeze_sha256"], v2.file_hash(freeze))
        self.assertEqual(stored["required_checkpoint_ids"], sorted(expected))
        self.assertEqual(len(sizes), 2)
        self.assertTrue(all(size > 0 for size in sizes))


if __name__ == "__main__":
    unittest.main()
