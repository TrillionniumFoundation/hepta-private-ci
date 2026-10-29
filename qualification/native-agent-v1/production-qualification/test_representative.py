"""Execute real workspace programs and reject replay that hides failed tools."""

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import representative_compare as runner
from representative_audit import audit_actual
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
                    if "presentation" in step:
                        self.assertEqual(len(result.stdout.encode()), step["presentation"]["stdout"]["bytes"])
                        self.assertEqual(hashlib.sha256(result.stdout.encode()).hexdigest(), step["presentation"]["stdout"]["sha256"])
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

    def test_audit_binds_real_repair_feedback_to_original_proposals_and_admissions(self):
        case = next(case for case in json.loads((HERE / "corpus.json").read_text())["cases"]
                    if case["id"] == "repair")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace, _, _ = runner.prepare(case, root)
            evidence, sessions = root / "model", root / "sessions" / "fixture"
            evidence.mkdir()
            sessions.mkdir(parents=True)
            steps, history = runner.steps_for(case), []
            gateway = object.__new__(ScriptGateway)
            for number in range(len(steps) + 1):
                request = {"input": list(history)}
                data, response = gateway.replay({"name": "repair", "calls": number + 1,
                    "steps": steps}, request)
                runner.save(evidence / f"model-{number:02}.request.json", request)
                (evidence / f"model-{number:02}.response.sse").write_bytes(data)
                if number == len(steps):
                    break
                item = response["output"][0]
                runner.save(sessions / f"tool-{number:02}.json", {"call": {
                    key: item[key] for key in ("call_id", "name", "arguments")}})
                run = subprocess.run([sys.executable, "-I", "-B", "-S", str(HERE / "workspace_tool.py"),
                    item["name"], item["arguments"], str(root / "workspace.json")],
                    cwd=workspace, capture_output=True, text=True, check=False)
                history += [item, {"type": "function_call_output", "call_id": item["call_id"],
                    "output": json.dumps({"exit_code": run.returncode, "stdout": run.stdout, "stderr": run.stderr})}]
            audited = audit_actual(root, "repair", "replay")
            self.assertEqual([call["exit_code"] for call in audited["calls"]], [1, 0, 0, 0])
            self.assertTrue(audited["usage_is_synthetic"])
            with self.assertRaisesRegex(ValueError, "provider identity"):
                audit_actual(root, "repair", "live", "different-provider-model")
            admission = sessions / "tool-02.json"
            original = admission.read_bytes()
            value = json.loads(original)
            value["call"]["arguments"] = json.dumps({"path": "src/calc.py", "old": "sum(values) + 1", "new": "0"})
            admission.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "admitted payload"):
                audit_actual(root, "repair", "replay")
            admission.write_bytes(original)
            request_path = evidence / "model-04.request.json"
            request = json.loads(request_path.read_text())
            request["input"][1]["output"] = json.dumps({"exit_code": 0, "stdout": "", "stderr": ""})
            request_path.write_text(json.dumps(request))
            with self.assertRaisesRegex(ValueError, "rewritten"):
                audit_actual(root, "repair", "replay")


if __name__ == "__main__":
    unittest.main()
