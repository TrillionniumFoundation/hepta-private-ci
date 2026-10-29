"""Execute real workspace programs and reject replay that hides failed tools."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import representative_compare as runner
from script_gateway import ScriptGateway


class RepresentativeTests(unittest.TestCase):
    def test_actual_workspace_cases_and_immutable_test_boundary(self):
        corpus = json.loads((HERE / "corpus.json").read_text())
        for case in corpus["cases"]:
            if case["id"] not in runner.CASES:
                continue
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                workspace, initial, readonly = runner.prepare(case, root)
                for step in runner.steps_for(case):
                    result = subprocess.run([sys.executable, "-I", "-B", "-S", str(HERE / "workspace_tool.py"),
                        step["tool"], json.dumps(step["arguments"]), str(root / "workspace.json")],
                        cwd=workspace, capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, step.get("exit", 0), result.stderr)
                    if "stdout" in step:
                        self.assertEqual(result.stdout, step["stdout"])
                    if "stderr_contains" in step:
                        self.assertIn(step["stderr_contains"], result.stderr)
                    if case["id"] == "mcp_readonly":
                        content = json.loads(result.stdout)["result"]["content"]
                        self.assertEqual(json.loads(content[0]["text"]), {"version": "1.0.0", "source": "fixture"})
                oracle = runner.independent_oracle(case, workspace, initial, readonly)
                self.assertTrue(oracle["passed"], oracle)
                if "test_calc.py" in readonly:
                    refused = subprocess.run([sys.executable, "-I", "-B", "-S", str(HERE / "workspace_tool.py"),
                        "hepta_write", json.dumps({"path": "test_calc.py", "content": "pass\n"}),
                        str(root / "workspace.json")], cwd=workspace, capture_output=True, check=False)
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertEqual(runner.digest(workspace / "test_calc.py"), readonly["test_calc.py"])

    def test_replay_requires_original_failed_feedback_and_preserves_same_stream(self):
        gateway = object.__new__(ScriptGateway)
        steps = [{"tool": "hepta_tests", "arguments": {}, "exit": 1, "stderr_contains": "AssertionError"}]
        case = {"name": "repair", "calls": 2, "steps": steps}
        output = json.dumps({"exit_code": 1, "stdout": "", "stderr": "AssertionError"})
        native = {"input": [{"type": "function_call_output", "call_id": "call_repair_0", "output": output}]}
        codex = {"input": [{"type": "function_call_output", "call_id": "call_repair_0",
                            "output": [{"type": "input_text", "text": output}]}]}
        self.assertEqual(gateway.replay(case, native), gateway.replay(case, codex))
        with self.assertRaisesRegex(ValueError, "missing or duplicate"):
            gateway.replay(case, {"input": []})
        native["input"][0]["output"] = json.dumps({"exit_code": 0, "stdout": "", "stderr": ""})
        with self.assertRaisesRegex(ValueError, "expected exit"):
            gateway.replay(case, native)


if __name__ == "__main__":
    unittest.main()
