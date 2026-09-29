"""Real owner workflows accept editorial rewrites, not missing execution wiring."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock

from hepta_workflow_commands import load_workflow, verify_document_workflow

ROOT = Path(__file__).resolve().parents[1]


class DocumentWorkflowSemanticsTests(unittest.TestCase):
    cases = (
        ("hepta-development-docs.yml", "scripts/hepta-docs.py", True),
        ("hepta-algorithm-docs.yml", "scripts/hepta-algorithm-docs.py", False),
        ("hepta-implementation-readiness.yml", "scripts/hepta-readiness.py", False),
    )

    def workflow(self, filename):
        return load_workflow((ROOT / ".github/workflows" / filename).read_text())

    def test_quoted_reordered_yaml_and_labels_keep_real_owner_commands(self):
        for filename, validator, recorded in self.cases:
            document = self.workflow(filename)
            for job in document["jobs"].values():
                job["name"] = "Clearer human-readable description"
                for step in job["steps"]:
                    step["name"] = "Unrelated step title"
            document.setdefault("env", {})["RUNBOOK_NOTE"] = (
                "Never git push; persist-credentials: true is forbidden"
            )
            with self.subTest(workflow=filename):
                verify_document_workflow(
                    json.dumps(document, sort_keys=True),
                    ROOT,
                    validator,
                    recorded=recorded,
                )

    def test_job_permission_and_checkout_escalation_is_rejected(self):
        for filename, validator, recorded in self.cases:
            for change in ("job-write", "no-permissions", "credentials", "wrong-head"):
                document = self.workflow(filename)
                job = document["jobs"]["source-head"]
                checkout = next(
                    s
                    for s in job["steps"]
                    if str(s.get("uses", "")).startswith("actions/checkout@")
                )
                if change == "job-write":
                    job["permissions"] = {"contents": "write"}
                elif change == "no-permissions":
                    document.pop("permissions")
                elif change == "credentials":
                    checkout["with"]["persist-credentials"] = "true"
                else:
                    checkout["with"]["ref"] = "main"
                with (
                    self.subTest(workflow=filename, change=change),
                    self.assertRaises(ValueError),
                ):
                    verify_document_workflow(
                        json.dumps(document), ROOT, validator, recorded=recorded
                    )

    def test_comment_and_env_data_do_not_replace_source_verification(self):
        for filename, validator, recorded in self.cases:
            document = self.workflow(filename)
            job = document["jobs"]["source-head"]
            invocation = "python3 " + validator + " verify"
            for step in job["steps"]:
                if "run" in step:
                    step["run"] = "\n".join(
                        "# " + line if invocation in line else line
                        for line in step["run"].splitlines()
                    )
            job["env"] = {"DOCUMENTATION_EXAMPLE": invocation}
            with (
                self.subTest(workflow=filename),
                self.assertRaisesRegex(ValueError, "execute verifier"),
            ):
                verify_document_workflow(
                    json.dumps(document), ROOT, validator, recorded=recorded
                )

    def test_merge_input_and_output_identity_cannot_be_replaced(self):
        filename, validator, recorded = self.cases[0]
        for change in ("base", "source", "output"):
            document = self.workflow(filename)
            job = document["jobs"]["merge-candidate"]
            merge = next(s for s in job["steps"] if s.get("id") == "synthetic")
            if change in ("base", "source"):
                merge["with"][change + "-sha"] = "${{ github.sha }}"
            else:
                job = json.loads(
                    json.dumps(job).replace("steps.synthetic.outputs.sha", "github.sha")
                )
                document["jobs"]["merge-candidate"] = job
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_document_workflow(
                    json.dumps(document), ROOT, validator, recorded=recorded
                )

    def test_recorded_workflow_cannot_drop_retained_artifacts(self):
        filename, validator, recorded = self.cases[0]
        document = self.workflow(filename)
        job = document["jobs"]["source-head"]
        job["steps"] = [
            s
            for s in job["steps"]
            if not str(s.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        with self.assertRaisesRegex(ValueError, "artifacts"):
            verify_document_workflow(
                json.dumps(document), ROOT, validator, recorded=recorded
            )


class AlgorithmCatalogEvolutionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "algorithm_evolution_test", ROOT / "scripts/hepta-algorithm-docs.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def verify_changed(self, change):
        module = self.module
        load = module.load

        def changed(path):
            value = load(path)
            if path == module.REGISTRY_PATH:
                change(value)
            return value

        output = io.StringIO()
        status = (ROOT / module.STATUS_PATH).read_text()
        with mock.patch.object(module, "load", side_effect=changed):
            with mock.patch.object(module, "status_text", return_value=status):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(module.verify(), 0)
        return json.loads(output.getvalue().strip().splitlines()[-1])

    def test_new_registered_module_gate_and_specification_use_the_same_validator(self):
        def grow(value):
            value["criticalModules"].append("memory.retrieval")
            value["closureGates"].append(
                {
                    "id": "ACG-EXTRA",
                    "name": "New owner-specific check",
                    "required": True,
                }
            )
            value["documents"].append(
                {
                    "id": "ALG-EXTENSION",
                    "path": "docs/learning/README.md",
                    "documentationState": "closed",
                    "implementationState": "not_implied",
                    "modules": ["memory.retrieval"],
                    "paperIds": [],
                }
            )

        result = self.verify_changed(grow)
        self.assertEqual(
            (
                result["criticalModules"],
                result["closureGates"],
                result["specifications"],
            ),
            (15, 14, 7),
        )
        self.assertFalse(result["capabilityClaimsAdvanced"])
        self.assertFalse(result["authorityGranted"])

    def test_reordered_and_consolidated_specifications_preserve_module_coverage(self):
        def consolidate(value):
            value["documents"] = list(reversed(value["documents"][:-1]))
            value["criticalModules"].reverse()
            value["closureGates"].reverse()

        self.assertEqual(self.verify_changed(consolidate)["specifications"], 5)

    def test_duplicate_unknown_and_uncovered_inputs_remain_rejected(self):
        def mutate(value, case):
            if case == "critical":
                value["criticalModules"].append(value["criticalModules"][0])
            elif case == "uncovered":
                value["criticalModules"].append("memory.retrieval")
            elif case == "gate":
                value["closureGates"].append(value["closureGates"][0])
            elif case == "document":
                value["documents"].append(value["documents"][0])
            elif case == "path":
                value["documents"][1]["path"] = value["documents"][0]["path"]
            elif case == "protocol":
                value["requiredProtocols"].append("UnregisteredProtocolV1")
            elif case == "domain":
                value["requiredDataDomains"].append(None)

        for case in (
            "critical",
            "uncovered",
            "gate",
            "document",
            "path",
            "protocol",
            "domain",
        ):
            with self.subTest(case=case), self.assertRaises(SystemExit):
                self.verify_changed(lambda value: mutate(value, case))


if __name__ == "__main__":
    unittest.main()
