"""Pure fixture rejection controls; no native Windows acceptance is claimed."""

from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import windows_environment_probe as environment


class EnvironmentControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "source"
        self.root.mkdir()
        self.head = "a" * 40
        self.source = {
            "head": self.head,
            "tree": "b" * 40,
            "trackedChanges": "",
            "allChanges": "",
            "cargoLockSha256": "c" * 64,
        }

    def execute(self, *, complete=True, after=None):
        output = self.directory / "records"
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    environment.probe,
                    "source",
                    side_effect=[self.source, after or self.source],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    environment.probe, "host_facts", return_value=({}, self.directory)
                )
            )
            stack.enter_context(
                mock.patch.object(
                    environment, "observe", return_value={"complete": complete}
                )
            )
            # Any compiler, runner, or original-scope invocation is forbidden in
            # this mode even when all diagnostic observations completed.
            original = stack.enter_context(
                mock.patch.object(
                    environment.probe.original,
                    "execute_groups",
                    side_effect=AssertionError("native invocation"),
                )
            )
            process = stack.enter_context(
                mock.patch.object(
                    environment.probe.subprocess,
                    "run",
                    side_effect=AssertionError("subprocess outside fixture"),
                )
            )
            compiler = stack.enter_context(
                mock.patch.object(
                    environment.probe.subprocess,
                    "check_output",
                    side_effect=AssertionError("compiler invocation"),
                )
            )
            stack.enter_context(mock.patch("sys.stdout", new_callable=io.StringIO))
            code = environment.run(self.root, output, self.head)
            original.assert_not_called()
            process.assert_not_called()
            compiler.assert_not_called()
        return code, json.loads((output / "receipt.json").read_text())

    def test_completed_observations_do_not_claim_or_execute_native_acceptance(self):
        code, receipt = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(
            {
                key: receipt[key]
                for key in (
                    "status",
                    "original_scope",
                    "nativeTestsRun",
                    "observation_only",
                    "science",
                    "priorNativeFailureSuperseded",
                    "fullCost",
                )
            },
            {
                "status": "observation_complete_not_native_pass",
                "original_scope": "not_run",
                "nativeTestsRun": False,
                "observation_only": True,
                "science": False,
                "priorNativeFailureSuperseded": False,
                "fullCost": None,
            },
        )

    def test_incomplete_observation_remains_failed(self):
        code, receipt = self.execute(complete=False)
        self.assertEqual(
            (code, receipt["status"], receipt["original_scope"]),
            (1, "failed_or_incomplete", "not_run"),
        )

    def test_changed_source_cannot_bind_complete_observations(self):
        code, receipt = self.execute(after={**self.source, "allChanges": " M file"})
        self.assertEqual(
            (code, receipt["sourceUnchanged"], receipt["original_scope"]),
            (1, False, "not_run"),
        )

    def test_nonallowlisted_environment_is_rejected_and_missing_values_are_explicit(
        self,
    ):
        values = {key: None for key in environment.ENVIRONMENT_KEYS}
        with self.assertRaises(ValueError):
            environment.environment_cases(
                self.directory, {**values, "SECRET": "never-export"}, "C:\\ProgramData"
            )
        cases = environment.environment_cases(self.directory, values, "C:\\ProgramData")
        inherited = next(case for case in cases if case["name"] == "one-programdata")
        os_derived = next(
            case for case in cases if case["name"] == "programdata-known-folder"
        )
        self.assertEqual(
            (inherited["missingKeys"], "PROGRAMDATA" in inherited["environment"]),
            (["PROGRAMDATA"], False),
        )
        self.assertEqual(
            (os_derived["missingKeys"], os_derived["environment"]["PROGRAMDATA"]),
            ([], "C:\\ProgramData"),
        )


if __name__ == "__main__":
    unittest.main()
