import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


PATH = Path(__file__).with_name("hepta-lane-e-closure.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_e_closure_tested", PATH)
assert SPEC is not None and SPEC.loader is not None
CLOSURE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CLOSURE
SPEC.loader.exec_module(CLOSURE)


class LaneEClosedWorldTests(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(CLOSURE.MATRIX_PATH.read_text())
        self.trace = json.loads(CLOSURE.TRACE_PATH.read_text())

    def matrix_findings(self, matrix):
        findings = CLOSURE.Findings()
        modules = CLOSURE.verify_matrix(matrix, findings)
        return modules, findings

    def test_real_signed_and_dataset_bound_operator_operations_are_required(self):
        _, findings = self.matrix_findings(self.matrix)
        self.assertEqual(findings.items, [])
        changed = copy.deepcopy(self.matrix)
        operator = next(item for item in changed["modules"] if item["module"] == "learning.operator")
        operator["operations"] = [
            item for item in operator["operations"]
            if item["operation"] != "fit_tabular_operator_verified_v2"
        ]
        _, findings = self.matrix_findings(changed)
        self.assertIn("operation_closed_world", [item.code for item in findings.items])

    def test_unknown_operator_operation_does_not_expand_the_closed_world(self):
        changed = copy.deepcopy(self.matrix)
        operator = next(item for item in changed["modules"] if item["module"] == "learning.operator")
        operator["operations"].append({**operator["operations"][0], "operation": "self_authorize"})
        _, findings = self.matrix_findings(changed)
        self.assertIn("operation_closed_world", [item.code for item in findings.items])

    def test_real_fitting_cases_are_required_and_unknown_cases_are_rejected(self):
        modules, findings = self.matrix_findings(self.matrix)
        CLOSURE.verify_traceability(self.trace, modules, findings)
        self.assertEqual(findings.items, [])
        for missing in ("OP-05", "OP-06"):
            changed = copy.deepcopy(self.trace)
            changed["cases"] = [item for item in changed["cases"] if item["id"] != missing]
            findings = CLOSURE.Findings()
            CLOSURE.verify_traceability(changed, modules, findings)
            self.assertIn("case_closed_world", [item.code for item in findings.items])
        changed = copy.deepcopy(self.trace)
        changed["cases"].append({**changed["cases"][0], "id": "OP-99"})
        findings = CLOSURE.Findings()
        CLOSURE.verify_traceability(changed, modules, findings)
        self.assertIn("case_closed_world", [item.code for item in findings.items])

    def test_duplicate_operations_do_not_silently_overwrite_a_record(self):
        for prepend in (True, False):
            changed = copy.deepcopy(self.matrix)
            operations = changed["modules"][0]["operations"]
            duplicate = {**operations[0], "status": "not_implemented"}
            if prepend:
                operations.insert(0, duplicate)
            else:
                operations.append(duplicate)
            _, findings = self.matrix_findings(changed)
            self.assertIn("duplicate_operation", [item.code for item in findings.items])

    def test_duplicate_external_gate_cannot_hide_a_self_certification(self):
        for prepend in (True, False):
            changed = copy.deepcopy(self.matrix)
            gates = changed["externalGates"]
            duplicate = {**gates[0], "repositoryMaySelfCertify": True}
            if prepend:
                gates.insert(0, duplicate)
            else:
                gates.append(duplicate)
            _, findings = self.matrix_findings(changed)
            self.assertIn("duplicate_external_gate", [item.code for item in findings.items])

    def test_malformed_external_gate_record_is_not_discarded(self):
        changed = copy.deepcopy(self.matrix)
        changed["externalGates"].append({"repositoryMaySelfCertify": True})
        _, findings = self.matrix_findings(changed)
        self.assertIn("invalid_external_gate", [item.code for item in findings.items])


if __name__ == "__main__":
    unittest.main()
