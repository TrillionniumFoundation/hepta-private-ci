"""Source-extracted terminal admission tests. No model is loaded or experiment started.

The function is compiled from the actual c2_controller.py AST, with deterministic
stdio-only dependencies so this bounded regression also runs without Torch.
"""
import ast
import hashlib
import json
import math
from pathlib import Path
import tempfile
import traceback
import unittest


class Ineligible(ValueError):
    pass


def require(ok, why):
    if not ok:
        raise Ineligible(why)


def identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def sha(path):
    return identity(path)["sha256"]


def terminal_gate():
    source = Path(__file__).with_name("c2_controller.py")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    # Extract both real source functions: the terminal gate now requires the
    # stricter parent/contract JSON decoder after policy-lineage convergence.
    nodes = [item for item in tree.body if isinstance(item, ast.FunctionDef)
             and item.name in ("strict_c2_json_object", "terminal_result_gate")]
    assert any(item.name == "terminal_result_gate" for item in nodes)
    module = ast.Module(body=nodes, type_ignores=[])
    ns = dict(Path=Path, json=json, math=math, traceback=traceback,
              identity=identity, sha=sha, require=require, hashlib=hashlib)
    exec(compile(module, str(source), "exec"), ns)
    return ns["terminal_result_gate"]


class TerminalJSONAdmissionTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.parent_dir = self.root / "parents" / "hcsn-s101-lr0.001"
        self.parent_dir.mkdir(parents=True)
        self.parent_result = self.parent_dir / "result.json"
        self.parent_result.write_text(json.dumps({
            "model_configuration": {"width":16},
            "source_before": {"status":"fixed"}
        }), encoding="utf-8")
        self.parent = {
            "name":"hcsn-s101-lr0.001", "seed":101,"learning_rate":0.001,
            "result_sha256":sha(self.parent_result)
        }
        self.contract = {"parent_campaign":str(self.parent_dir.parent)}
        self.result_path = self.root / "result.json"
        self.row = {"returncode":2, "hard_timeout_sent":False, "process_started":True,
                    "whole_process_wall_seconds":1.0,"child_cpu_seconds":0.5}
        self.valid = {
            "schema":"hcsn-c2-soft-wall-continuation-v1",
            "production_execution":True,"confirmation_access":False,
            "arm":"hcsn","seed":101,"learning_rate":0.001,
            "parent":str(self.parent_dir),"parent_outer":self.parent,
            "parent_report":identity(self.parent_result),
            "model_configuration":{"width":16},
            "status":"failed","training_adequacy_established":False,
            "new_main_updates":0
        }
        self.gate = terminal_gate()

    def run_raw(self, raw):
        self.result_path.write_bytes(raw)
        return self.gate(self.row,self.result_path,self.parent,self.contract)

    def test_valid_nonzero_terminal_evidence_stays_structurally_complete(self):
        row = self.run_raw(json.dumps(self.valid).encode())
        self.assertTrue(row["terminal_evidence_complete"])
        self.assertEqual(row["status"],"failed")
        self.assertFalse(row["adequate"])

    def test_matching_hash_duplicate_status_is_rejected(self):
        data = json.dumps(self.valid).replace('"status": "failed"',
            '"status": "completed_development", "status": "failed"')
        row = self.run_raw(data.encode())
        self.assertFalse(row["terminal_evidence_complete"])

    def test_matching_hash_nan_field_is_rejected(self):
        row = self.run_raw((json.dumps(self.valid)[:-1] + ',"probe":NaN}').encode())
        self.assertFalse(row["terminal_evidence_complete"])

    def test_matching_hash_overflowed_float_is_rejected(self):
        row = self.run_raw((json.dumps(self.valid)[:-1] + ',"probe":1e99999}').encode())
        self.assertFalse(row["terminal_evidence_complete"])

    def test_matching_hash_oversized_result_is_rejected(self):
        data = json.dumps({**self.valid,"padding":"z"*(17*1024*1024)}).encode()
        row = self.run_raw(data)
        self.assertFalse(row["terminal_evidence_complete"])

    def test_invalid_utf8_is_rejected(self):
        row = self.run_raw(b'\xff')
        self.assertFalse(row["terminal_evidence_complete"])


if __name__ == "__main__":
    unittest.main()
