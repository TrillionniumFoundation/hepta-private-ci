"""Original engineering archive identities, real stage failures and substitution controls."""

import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from . import data, paired_loop as loop, runtime_artifacts

ARCHIVE = (
    Path(__file__).resolve().parents[2]
    / "qualification/paired-consumer-use-20261123/CONSUMER_ENGINEERING_ORIGINALS.zip"
)


class PairedLoopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        with zipfile.ZipFile(ARCHIVE) as archive:
            path = self.root / "original.sqlite"
            path.write_bytes(archive.read("original/intake/intake.sqlite"))
            with sqlite3.connect(path) as database:
                self.binding = json.loads(
                    database.execute("SELECT binding FROM admissions").fetchone()[0]
                )
                self.config = json.loads(
                    database.execute("SELECT value FROM settings").fetchone()[0]
                )
            prefix = "original/intake/" + data.digest(self.binding) + "/"
            self.request = json.loads(archive.read(prefix + "paired.json"))
            self.release = json.loads(archive.read(prefix + "release.json"))
            self.outcomes = [
                json.loads(archive.read(n))
                for n in archive.namelist()
                if n.startswith(prefix) and n.endswith("/OUTCOME.json")
            ]
        self.runtime = {
            "test_fixture_only": True,
            "source": "original engineering fixture",
        }
        self.manifest = loop.identity(
            self.config, self.binding, self.request, self.runtime
        )
        self.pin = data.digest(self.manifest)

    def test_original_model_and_release_bind_to_one_identity(self):
        self.assertEqual(self.manifest["release"], self.release)
        self.assertEqual(
            self.manifest["candidate_sha256"], self.release["candidate_sha256"]
        )
        self.assertEqual(
            self.manifest["parent_sha256"], data.digest(self.request["parent"])
        )
        self.assertEqual(self.manifest["release"]["scope"], "engineering_fixture")
        for field in (
            "router_sha256",
            "source_exposure_sha256",
            "evaluation_sha256",
            "model_runtime_sha256",
        ):
            self.assertEqual(len(self.manifest[field]), 64)

    def test_cross_study_request_model_and_freeze_substitutions_are_rejected(self):
        for field in (
            "study_sha256",
            "freeze_sha256",
            "candidate_sha256",
            "request_sha256",
        ):
            with self.subTest(field=field):
                substituted = copy.deepcopy(self.binding)
                substituted["release"][field] = "f" * 64
                with self.assertRaises(ValueError):
                    loop.identity(self.config, substituted, self.request, self.runtime)
        for component in (
            "parent",
            "candidate",
            "retention",
            "future",
            "timeout_seconds",
        ):
            with self.subTest(component=component):
                modified = copy.deepcopy(self.request)
                if component in ("parent", "candidate"):
                    modified[component]["runtime"]["threads"] += 1
                elif component == "timeout_seconds":
                    modified[component] += 1
                else:
                    modified[component] = modified[component] + modified[component]
                with self.assertRaises(ValueError):
                    loop.identity(self.config, self.binding, modified, self.runtime)

    def test_implementation_change_changes_the_identity(self):
        altered = loop.identity(
            self.config, self.binding, self.request, {"source": "another evaluator"}
        )
        self.assertNotEqual(data.digest(altered), self.pin)

    def artifact_runtime(self):
        directory = self.root / "runtime"
        directory.mkdir()
        (directory / "fixture.py").write_bytes(b"value = 1\n")
        return dict(
            package_sha256="1" * 64,
            python=sys.version,
            executable_sha256="2" * 64,
            packages={name: "engineering-fixture" for name in loop.PACKAGES},
            dependency_identity_kind="verified_runtime_artifacts_v1",
            runtime_closure_complete=False,
            runtime_artifacts=runtime_artifacts.snapshot(self.root, ["runtime"]),
        )

    def test_artifact_identity_and_readback_use_v2_without_granting_authority(self):
        self.runtime = self.artifact_runtime()
        self.manifest = loop.identity(
            self.config, self.binding, self.request, self.runtime
        )
        self.pin = data.digest(self.manifest)
        self.assertEqual(
            self.manifest["schema"], "hepta.paired-learning.loop-identity.v2"
        )
        folder, outcome = self.make_stages()
        result = loop.readback(
            folder, self.pin, outcome["scope"]["task"], self.binding, outcome
        )
        self.assertEqual(result["schema"], "hepta.paired-learning.loop-readback.v2")
        self.assertFalse(result["production_authorization_available"])
        self.assertFalse(result["settlement_authorized"])
        self.assertEqual(result["site_attested_independent_adopted_improvements"], 0)

    def test_artifact_inventory_change_changes_loop_and_complete_claim_is_refused(self):
        runtime = self.artifact_runtime()
        original = loop.identity(self.config, self.binding, self.request, runtime)
        original_pin = data.digest(original)
        (self.root / "runtime/fixture.py").write_bytes(b"value = 2\n")
        runtime["runtime_artifacts"] = runtime_artifacts.snapshot(
            self.root, ["runtime"]
        )
        changed = loop.identity(self.config, self.binding, self.request, runtime)
        self.assertNotEqual(original_pin, data.digest(changed))
        runtime["runtime_closure_complete"] = True
        with self.assertRaisesRegex(ValueError, "closure is not established"):
            loop.identity(self.config, self.binding, self.request, runtime)

    def test_dependency_change_during_action_is_retained_as_failed_stage(self):
        runtime = self.artifact_runtime()
        manifest = loop.identity(self.config, self.binding, self.request, runtime)
        args = SimpleNamespace(
            home=self.root / "home",
            admission=data.digest(self.binding),
            materials=self.root,
            cmd="select",
            expected_loop=data.digest(manifest),
        )
        (args.home / args.admission).mkdir(parents=True)
        changed = copy.deepcopy(runtime)
        changed["executable_sha256"] = "3" * 64
        with (
            patch.object(
                loop.consumer,
                "context",
                return_value=(self.config, self.binding, self.request),
            ),
            patch.object(loop, "implementation_for", side_effect=[runtime, changed]),
            patch.object(
                loop.consumer, "operate", return_value={"fixture": True}
            ) as dispatch,
        ):
            with self.assertRaisesRegex(ValueError, "implementation changed during"):
                loop.operate(args)
        dispatch.assert_called_once()
        path = args.home / args.admission / "bound-loop" / args.expected_loop / "select"
        self.assertEqual(
            json.loads((path / "END.json").read_bytes())["status"], "FAILED"
        )
        self.assertFalse((path / "RESULT.json").exists())

    def test_failed_real_child_is_charged_and_not_redispatched(self):
        path = self.root / "failed"
        subject = {"loop_sha256": self.pin, "command": "run", "task_sha256": "a" * 64}

        def action():
            subprocess.run(
                [sys.executable, "-c", "raise SystemExit(7)"],
                check=True,
                capture_output=True,
            )

        with self.assertRaises(subprocess.CalledProcessError):
            loop.measured_action(path, subject, action)
        result = json.loads((path / "END.json").read_bytes())
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_type"], "CalledProcessError")
        self.assertGreater(result["wall_ns"], 0)
        self.assertGreater(result["cpu_ns"], 0)
        with self.assertRaises(FileExistsError):
            loop.measured_action(path, subject, lambda: self.fail("redispatched"))

    def test_interruption_is_not_a_completed_stage(self):
        def interrupt():
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            loop.measured_action(self.root / "interrupted", {}, interrupt)
        result = json.loads((self.root / "interrupted/END.json").read_bytes())
        self.assertEqual(
            (result["status"], result["error_type"]), ("FAILED", "KeyboardInterrupt")
        )

    def make_stages(self):
        outcome = self.outcomes[0]
        scope = outcome["scope"]
        selected = dict(
            pair=scope["pair"], candidate=scope["candidate"], selection_sha256="b" * 64
        )
        outputs = dict(
            select=selected,
            run=dict(run_receipt=scope["run_receipt"]),
            report=outcome,
            verify=outcome,
            **{"verify-request": dict(run_receipt=scope["run_receipt"])},
        )
        folder = (
            self.root / "home" / data.digest(self.binding) / "bound-loop" / self.pin
        )
        folder.mkdir(parents=True)
        loop.consumer.put(folder / "IDENTITY.json", self.manifest)
        for command, result in outputs.items():
            subject = dict(
                loop_sha256=self.pin,
                command=command,
                task_sha256=None if command == "select" else scope["task"],
            )
            loop.measured_action(
                folder / loop.stage_key(command, scope["task"]),
                subject,
                lambda r=result: r,
            )
        return folder, outcome

    def test_engineering_use_never_becomes_real_adoption_or_free_total_cost(self):
        folder, outcome = self.make_stages()
        report = loop.readback(
            folder, self.pin, outcome["scope"]["task"], self.binding, outcome
        )
        self.assertEqual(report["site_attested_independent_adopted_improvements"], 0)
        self.assertIsNone(report["improvement_id"])
        self.assertIsNone(report["end_to_end_wall_ns"])
        self.assertIsNone(report["adopted_improvements_per_total_cost"])
        self.assertFalse(report["complete_total_cost"])
        self.assertFalse(report["settlement_authorized"])
        self.assertFalse(report["consensus_credit_authorized"])

    def test_altered_retained_stage_cannot_be_read_as_the_original(self):
        folder, outcome = self.make_stages()
        task = outcome["scope"]["task"]
        path = folder / loop.stage_key("run", task) / "RESULT.json"
        path.write_text(json.dumps({"run_receipt": "e" * 64}))
        with self.assertRaisesRegex(ValueError, "stage or result differs"):
            loop.readback(folder, self.pin, task, self.binding, outcome)

    def test_completed_but_unpublished_readback_recovers_without_dispatch(self):
        folder, outcome = self.make_stages()
        before = {
            p.relative_to(folder): p.read_bytes()
            for p in folder.rglob("*")
            if p.is_file()
        }
        args = SimpleNamespace(
            home=self.root / "home",
            admission=data.digest(self.binding),
            materials=self.root,
            cmd="readback",
            expected_loop=self.pin,
            task=outcome["scope"]["task"],
        )
        with (
            patch.object(
                loop.consumer,
                "context",
                return_value=(self.config, self.binding, self.request),
            ),
            patch.object(loop, "implementation", return_value=self.runtime),
            patch.object(loop.consumer, "operate") as dispatch,
        ):
            result = loop.operate(args)["result"]
        dispatch.assert_not_called()
        self.assertEqual(
            result["authority_observation"], "retained_engineering_fixture_verification"
        )
        self.assertEqual(
            before,
            {
                p.relative_to(folder): p.read_bytes()
                for p in folder.rglob("*")
                if p.is_file()
            },
        )

    def test_other_principal_cannot_be_joined_to_an_original_loop(self):
        folder, outcome = self.make_stages()
        binding = copy.deepcopy(self.binding)
        binding["native"]["study_principal_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "admission binding"):
            loop.readback(folder, self.pin, outcome["scope"]["task"], binding, outcome)


if __name__ == "__main__":
    unittest.main()
