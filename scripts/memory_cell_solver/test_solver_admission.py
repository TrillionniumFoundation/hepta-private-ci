"""Pure metadata/feedback regressions; no model, gate subprocess or real task run."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import solver_admission as admission
from edit_protocol import sha
from solver_common import file_identity
from solver_tasks import feedback


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fixture = self.root / "fixture"
        fixture.mkdir()
        (fixture / "workflow.yml").write_text("original source\n")
        tools = {}
        for name in ("python", "ffmpeg", "ffprobe", "openssl"):
            path = self.root / ("tool-" + name)
            path.write_text("unit identity only: " + name)
            tools[name] = str(path)
        self.spec = {
            "files": {"workflow.yml": file_identity(fixture / "workflow.yml")},
            "tools": {name: file_identity(path) for name, path in tools.items()},
        }
        self.contract_sha = "a" * 64
        profile_identity = self.write(
            "profile.json",
            {
                "schema": "hepta.memory-cell.runtime-profile.v1",
                "task_contract_sha256": self.contract_sha,
                "tools": self.spec["tools"],
            },
        )
        profile = {key: profile_identity[key] for key in ("path", "sha256")}
        profile["tools"] = tools
        runtime = {
            "sha256": profile["sha256"],
            "tools": self.spec["tools"],
            "mode": "controller_supplied",
            "qualification_proven_by_profile_alone": False,
        }
        qualified = self.write(
            "qualification/qualification.json",
            {
                "accepted": True,
                "tests_run": 6,
                "failures": 0,
                "errors": 0,
                "skips": 0,
                "contract_sha256": self.contract_sha,
                "runtime": runtime,
            },
        )
        argv = [
            tools["python"],
            "-B",
            str(admission.EVALUATION / "test_codec_executor_v2.py"),
            "--fixture",
            str(fixture),
            "--known-fix",
            str(self.root / "not-read-gold.py"),
            "--output",
            str(self.root / "qualification"),
            "--runtime-profile",
            profile["path"],
            "--runtime-profile-sha256",
            profile["sha256"],
        ]
        for name, path in tools.items():
            argv.extend(["--" + name, path])
        command = self.write(
            "qualification-command.json",
            {
                "argv": argv,
                "returncode": 0,
                "runtime_profile_sha256": profile["sha256"],
            },
        )
        self.input = {
            "task": {"id": "codec", "unit_metadata": True},
            "files": {"workflow.yml": "original source\n", "runner.py": None},
        }
        task_input = self.write("task-input.json", self.input)
        retrieved = self.write(
            "retrieval.json", {"documents": [], "retrieval_receipt": None}
        )
        manifest = self.write("model.json", {"file": {"bytes": 1, "sha256": "0" * 64}})
        self.protocol = {
            "task_order": ["codec"],
            "arms": ["no_history", "retrieval"],
            "source_files": {},
            "tasks": {
                "codec": {
                    "fixture": str(fixture),
                    "runtime_profile": profile,
                    "input": task_input,
                    "qualification": qualified,
                    "qualification_command": command,
                }
            },
            "retrieval_files": {
                "codec:no_history": retrieved,
                "codec:retrieval": retrieved,
            },
            "retrieval": {"maximum_documents": 5, "maximum_utf8_bytes": 12000},
            "staged_model_manifest": {
                key: manifest[key] for key in ("bytes", "sha256")
            },
        }
        self.request = {
            "output": str(self.root / "not-created"),
            "protocol": "not-opened-here",
            "protocol_sha256": "b" * 64,
            "model_manifest": manifest["path"],
            "model_manifest_sha256": manifest["sha256"],
            "model": "not-loaded",
            "arm": "no_history",
            "task": "codec",
            "fixture": str(fixture),
            "runtime_profile": profile,
            "retrieval": retrieved["path"],
            "retrieval_sha256": retrieved["sha256"],
        }
        for name, replacement in (
            ("source_inventory", lambda _: {}),
            ("task_contract", lambda _: (self.spec, self.contract_sha)),
            (
                "describe",
                lambda *_: (
                    self.input["task"],
                    {"workflow.yml": "original source\n", "runner.py": None},
                ),
            ),
        ):
            patcher = patch.object(admission, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(value, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}

    def test_valid_frozen_input_is_consumed_without_model(self):
        self.assertEqual(
            admission.verify_request(self.request, self.protocol),
            (self.input["task"], self.input["files"]),
        )
        self.assertFalse(Path(self.request["output"]).exists())

    def test_added_runner_or_symlink_refused_before_prompt(self):
        fixture = Path(self.request["fixture"])
        extra = fixture / "runner.py"
        extra.write_text("unadmitted resolution-like bytes")
        with self.assertRaisesRegex(ValueError, "fixture file set"):
            admission.verify_request(self.request, self.protocol)
        extra.unlink()
        extra.symlink_to(fixture / "workflow.yml")
        with self.assertRaisesRegex(ValueError, "symlink"):
            admission.verify_request(self.request, self.protocol)

    def test_profile_and_executable_drift_refused(self):
        profile = self.request["runtime_profile"]
        path = Path(profile["path"])
        raw = path.read_bytes()
        path.write_bytes(raw + b" ")
        with self.assertRaisesRegex(ValueError, "profile hash"):
            admission.verify_request(self.request, self.protocol)
        path.write_bytes(raw)
        Path(profile["tools"]["ffmpeg"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "executable changed"):
            admission.verify_request(self.request, self.protocol)

    def test_wrong_qualification_command_binding_refused(self):
        task = self.protocol["tasks"]["codec"]
        command = json.loads(Path(task["qualification_command"]["path"]).read_text())
        command["argv"][command["argv"].index("--runtime-profile-sha256") + 1] = (
            "c" * 64
        )
        task["qualification_command"] = self.write(
            "qualification-command.json", command
        )
        with self.assertRaisesRegex(ValueError, "qualification argv"):
            admission.verify_request(self.request, self.protocol)

    def test_failed_qualification_or_new_source_in_frozen_input_refused(self):
        task = self.protocol["tasks"]["codec"]
        qualified = json.loads(Path(task["qualification"]["path"]).read_text())
        qualified["accepted"] = False
        task["qualification"] = self.write(
            "qualification/qualification.json", qualified
        )
        with self.assertRaisesRegex(ValueError, "qualification did not succeed"):
            admission.verify_request(self.request, self.protocol)
        qualified["accepted"] = True
        task["qualification"] = self.write(
            "qualification/qualification.json", qualified
        )
        proposed = {
            "task": self.input["task"],
            "files": self.input["files"] | {"runner.py": "unadmitted code"},
        }
        task["input"] = self.write("task-input.json", proposed)
        with self.assertRaisesRegex(ValueError, "original allowed source"):
            admission.verify_request(self.request, self.protocol)

    def test_real_candidate_lint_feedback_not_baseline_codes(self):
        directory = self.root / "feedback/candidate-lint"
        directory.mkdir(parents=True)
        (directory / "stdout").write_text(
            json.dumps(
                [
                    {
                        "code": "F821",
                        "message": "undefined name repaired_name",
                        "location": {"row": 3, "column": 2},
                    }
                ]
            )
        )
        value = json.loads(
            feedback(
                {
                    "accepted": False,
                    "status": "lint_failed",
                    "baseline_codes": ["F401", "E731"],
                },
                directory.parent,
            )
        )
        self.assertEqual([row["code"] for row in value["candidate_lint"]], ["F821"])
        self.assertNotIn("baseline_codes", value)

    def test_codec_feedback_reports_missing_ids_and_valid_bounded_json(self):
        report = {"tests_run": 0, "completed": [], "outcomes": []}
        value = feedback(
            {
                "accepted": False,
                "status": "task_failed",
                "profiles": {"provisioned": {"passed": False, "semantic": report}},
            },
            self.root,
        )
        parsed = json.loads(value)
        self.assertEqual(parsed["profiles"]["provisioned"]["missing_count"], 21)
        self.assertEqual(parsed["profiles"]["provisioned"]["tests_run"], 0)
        self.assertLessEqual(len(value.encode()), 6000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
