import tempfile
import unittest
import json
import sys
from pathlib import Path

from operational_cohort_plan import canonical
from prospective_action_inputs import sha_file
from prospective_action_run import run, verify_inventory, verify_pins
from test_prospective_action_execution import fixture


class ProspectiveRunIntegrityTests(unittest.TestCase):
    def test_complete_driver_seals_before_commands_and_accounts_every_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, _ = fixture(root)
            inputs = json.loads((root / "inputs/inputs.json").read_bytes())
            group = next(iter(inputs["case_bindings"]))
            env = root / "env"
            (env / "bin").mkdir(parents=True)
            executable = env / "bin/python"
            executable.symlink_to(sys.executable)
            inventory = root / "inventory.json"
            inventory.write_bytes(canonical([{"path": "bin/python", "bytes": executable.stat().st_size,
                                             "sha256": sha_file(executable)}]))
            config = {"profiles": {"fixture": {"python": str(executable), "python_sha256": sha_file(executable),
                                                "plain_pytest": True}},
                      "group_profiles": {group: "fixture"}, "source_stores": {"scrapy": str(store)},
                      "inventories": {"fixture": {"root": str(env), "manifest": str(inventory), "sha256": sha_file(inventory)}}}
            runtime = root / "runtime.json"
            runtime.write_bytes(canonical(config))
            result = run(root / "inputs/inputs.json", runtime, root / "executions", root / "work", workers=1)
            self.assertEqual(result["physical_command_executions"], 6)
            self.assertEqual(result["completed_groups"], 1)
            self.assertTrue(result["all_runtime_files_unchanged"])
            self.assertGreater(result["all_reaped_children_cpu_ns"], 0)
            self.assertEqual(result["execution_plan_sha256"], sha_file(root / "executions/execution-plan.json"))

    def test_runtime_tampering_and_undeclared_files_block_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / "env"
            environment.mkdir()
            file = environment / "runtime.py"
            file.write_bytes(b"pinned runtime\n")
            record = {"path": "runtime.py", "bytes": file.stat().st_size, "sha256": sha_file(file)}
            manifest = root / "inventory.json"
            manifest.write_bytes(canonical([record]))
            pin = sha_file(manifest)
            self.assertEqual(verify_inventory(environment, manifest, pin)["files"], 1)
            (environment / "__pycache__").mkdir()
            (environment / "__pycache__/runtime.pyc").write_bytes(b"irrelevant bytecode")
            self.assertEqual(verify_inventory(environment, manifest, pin)["files"], 1)
            extra = environment / "unplanned.pyc"
            extra.write_bytes(b"unreviewed package")
            with self.assertRaisesRegex(ValueError, "extra or missing"):
                verify_inventory(environment, manifest, pin)
            extra.unlink()
            file.write_bytes(b"changed runtime\n")
            with self.assertRaisesRegex(ValueError, "runtime file differs"):
                verify_inventory(environment, manifest, pin)
            with self.assertRaisesRegex(ValueError, "frozen execution input"):
                verify_pins({str(file): record["sha256"]})

    def test_manifest_pin_is_checked_before_using_declared_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "inventory.json"
            manifest.write_bytes(canonical([{"path": "../outside", "bytes": 0, "sha256": "a" * 64}]))
            with self.assertRaisesRegex(ValueError, "declared pin"):
                verify_inventory(root, manifest, "b" * 64)
            with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
                verify_inventory(root, manifest, sha_file(manifest))


if __name__ == "__main__":
    unittest.main()
