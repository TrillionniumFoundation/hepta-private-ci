"""Model imports must use the separately pinned inventory, with no model runs."""

import builtins
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from historical_inventory import bind_model_sources
from storage_ledger import file_record
import warm_trial
import warm_worker


def pin(path):
    row, _ = file_record(path)
    return {key: row[key] for key in ("path", "bytes", "sha256")}


class ModelSourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.code = self.repo / "scripts/memory_cell"
        self.code.mkdir(parents=True)
        (self.code / "parametric_model.py").write_text("import bound_helper\n")
        (self.code / "bound_helper.py").write_text(
            'raise RuntimeError("fixture source must not execute")\n'
        )
        self.inputs = [pin(p) for p in sorted(self.code.glob("*.py"))]
        self.inventory = self.root / "inventory.json"
        self.inventory.write_text(json.dumps({"files": self.inputs}))

    def test_correct_source_closure_is_admitted_without_importing_it(self):
        result = bind_model_sources(self.code, self.inputs)
        self.assertEqual(result, self.inputs)

    def test_other_repo_is_rejected_before_any_worker_execution(self):
        other = self.root / "other"
        shutil.copytree(self.repo, other)
        p = {
            "schema": "hepta.memory.warm-cost-proposal.v2",
            "jobs": [{"phase": "warmup", "index": i} for i in range(2)]
            + [{"phase": "measured", "index": i} for i in range(18)],
            "order": ["retrieval", "memory"],
            "budget": {
                "decoder_calls_including_warmup_max": 20,
                "training_updates": 0,
                "max_new_tokens_per_decoder": 16,
                "max_complete_prompt_tokens": 192,
            },
            "generation_limits": dict(warm_worker.GENERATION_LIMITS),
            "implementation": [warm_trial.pin(p) for p in warm_trial.HERE.glob("*.py")],
            "python": str(Path(sys.executable).resolve()),
            "inventory": warm_trial.pin(self.inventory),
            "inputs": self.inputs,
            "model_code": str(other / "scripts/memory_cell"),
            "supervisor": str(self.root),
            "sources": [],
            "operations": [],
            "model_request": {},
            "limits": {},
        }
        protocol = self.root / "protocol.json"
        raw = json.dumps(p).encode()
        protocol.write_bytes(raw)
        output = self.root / "output"
        output.mkdir()
        called = []

        def worker(*args, **kwargs):
            called.append(True)
            raise RuntimeError("unbound worker started")

        with patch.dict(sys.modules, {"process_meter_v2": SimpleNamespace(run=worker)}):
            result = warm_trial.execute_body(
                SimpleNamespace(
                    protocol=protocol,
                    protocol_sha256=hashlib.sha256(raw).hexdigest(),
                    output=output,
                )
            )
        self.assertEqual(called, [])
        self.assertIn("independently pinned", result["error"])
        self.assertEqual(protocol.read_bytes(), raw)

    def test_changed_or_unpinned_dependency_is_rejected(self):
        helper = self.code / "bound_helper.py"
        with self.assertRaisesRegex(ValueError, "independently pinned"):
            bind_model_sources(
                self.code, [row for row in self.inputs if row["path"] != str(helper)]
            )
        helper.write_text("changed = True\n")
        with self.assertRaises(ValueError):
            bind_model_sources(self.code, self.inputs)

    def test_foreign_cached_module_is_rejected(self):
        foreign = self.root / "foreign.py"
        foreign.write_text("pass\n")
        with patch.dict(
            sys.modules, {"parametric_model": SimpleNamespace(__file__=str(foreign))}
        ):
            with self.assertRaisesRegex(ValueError, "loaded model module"):
                bind_model_sources(self.code, self.inputs)

    def test_package_shadowing_pinned_source_is_rejected(self):
        package = self.code / "parametric_model"
        package.mkdir()
        (package / "__init__.py").write_text("pass\n")
        with self.assertRaisesRegex(ValueError, "import resolution"):
            bind_model_sources(self.code, self.inputs)

    def test_freeze_rejects_wrong_repo_without_rewriting_independent_inventory(self):
        other = self.root / "other"
        shutil.copytree(self.repo, other)
        dev = self.root / "development"
        (dev / "runs/24041").mkdir(parents=True)
        (dev / "protocol.json").write_text(json.dumps({"questions": ["a", "b", "c"]}))
        (dev / "runs/24041/adapter-request.json").write_text(
            json.dumps({"payload": {}})
        )
        before = self.inventory.read_bytes()
        with self.assertRaisesRegex(ValueError, "independently pinned"):
            warm_trial.freeze(
                SimpleNamespace(
                    development=dev,
                    repo=other,
                    inventory=self.inventory,
                    output=self.root / "freeze",
                )
            )
        self.assertEqual(self.inventory.read_bytes(), before)
        self.assertFalse((self.root / "freeze/protocol.json").exists())

    def test_worker_refuses_wrong_root_before_importing_torch(self):
        other = self.root / "other"
        shutil.copytree(self.repo, other)
        imports = []
        original = builtins.__import__

        def observe(name, *args, **kwargs):
            if name == "torch":
                imports.append(name)
                raise AssertionError("model runtime must not be imported")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=observe):
            with self.assertRaisesRegex(ValueError, "independently pinned"):
                warm_worker.run(
                    {
                        "mode": "memory",
                        "generation_limits": dict(warm_worker.GENERATION_LIMITS),
                        "model_code": str(other / "scripts/memory_cell"),
                        "model_source_pins": self.inputs,
                    }
                )
        self.assertEqual(imports, [])


if __name__ == "__main__":
    unittest.main()
