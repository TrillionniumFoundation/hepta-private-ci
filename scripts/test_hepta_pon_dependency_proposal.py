"""Control tests only: Cargo, Rust and Bazel are never executed by this file."""

from copy import deepcopy
import json
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import textwrap

import hepta_pon_dependency_proposal as proposal


SOURCE = "a" * 40
MANIFEST = b'[workspace.dependencies]\nzstd = "0.13"\nother = { version = "1", features = ["keep"] }\n'


def workflow_bootstrap(environment, event):
    workflow = (
        proposal.ROOT / ".github/workflows/hepta-pon-rustsec-lock-proposal.yml"
    ).read_text()
    script = textwrap.dedent(
        workflow.split("python3 - <<'PY_SOURCE'\n", 1)[1].split(
            "          PY_SOURCE\n", 1
        )[0]
    )
    with TemporaryDirectory() as temporary:
        event_path = Path(temporary) / "event.json"
        output_path = Path(temporary) / "output"
        event_path.write_text(json.dumps(event))
        values = {
            **environment,
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_OUTPUT": str(output_path),
        }
        with patch.dict(os.environ, values, clear=True):
            exec(compile(script, "workflow-precheckout-source-check", "exec"), {})
        return output_path.read_text().strip().removeprefix("source=")


def lock_fixture(
    extra="", source="registry+https://github.com/rust-lang/crates.io-index"
):
    # Synthetic parser input, never written over a project lock or qualified as one.
    entries = [
        f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = "{source}"\nchecksum = "{checksum}"\n'
        for name, (version, checksum) in proposal.TARGETS.items()
    ]
    return ("\n".join(entries) + extra).encode()


class ProposalControls(unittest.TestCase):
    def test_pr_and_dispatch_select_mutually_exclusive_exact_sources(self):
        repository = "TrillionniumFoundation/hepta-private-ci"
        cases = [
            (
                {
                    "GITHUB_REPOSITORY": repository,
                    "GITHUB_EVENT_NAME": "workflow_dispatch",
                    "GITHUB_SHA": SOURCE,
                },
                {"inputs": {"source_sha": SOURCE}},
            ),
            (
                {
                    "GITHUB_REPOSITORY": repository,
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_SHA": "b" * 40,
                    "GITHUB_REF": "refs/pull/4080/merge",
                },
                {
                    "action": "synchronize",
                    "number": 4080,
                    "pull_request": {
                        "head": {
                            "sha": SOURCE,
                            "repo": {"full_name": repository, "fork": False},
                        },
                        "base": {"repo": {"full_name": repository}},
                    },
                },
            ),
        ]
        for environment, event in cases:
            for validator in (proposal.source_from_event, workflow_bootstrap):
                with self.subTest(
                    kind=environment["GITHUB_EVENT_NAME"], validator=validator.__name__
                ):
                    self.assertEqual(validator(environment, event), SOURCE)

    def test_source_checks_reject_forks_missing_shas_and_conflicting_origins(self):
        repository = "TrillionniumFoundation/hepta-private-ci"
        environment = {
            "GITHUB_REPOSITORY": repository,
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_SHA": "b" * 40,
            "GITHUB_REF": "refs/pull/4080/merge",
        }
        original = {
            "action": "synchronize",
            "number": 4080,
            "pull_request": {
                "head": {
                    "sha": SOURCE,
                    "repo": {"full_name": repository, "fork": False},
                },
                "base": {"repo": {"full_name": repository}},
            },
        }
        cases = []
        for key, value in (
            ("fork", True),
            ("fork", None),
            ("full_name", "foreign/repository"),
        ):
            event = deepcopy(original)
            event["pull_request"]["head"]["repo"][key] = value
            cases.append((environment, event))
        for value in (None, "a" * 7, "Z" * 40):
            event = deepcopy(original)
            event["pull_request"]["head"]["sha"] = value
            cases.append((environment, event))
        cases.extend(
            [
                (environment, {**original, "inputs": {"source_sha": SOURCE}}),
                (environment, {**original, "action": "closed"}),
                ({**environment, "GITHUB_REF": "refs/pull/4079/merge"}, original),
            ]
        )
        dispatch = {
            **environment,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": SOURCE,
        }
        cases.extend(
            [
                (dispatch, {}),
                (dispatch, {"inputs": {"source_sha": "b" * 40}}),
                (
                    dispatch,
                    {
                        "inputs": {"source_sha": SOURCE},
                        "pull_request": original["pull_request"],
                    },
                ),
            ]
        )
        for index, (values, event) in enumerate(cases):
            for validator in (proposal.source_from_event, workflow_bootstrap):
                with (
                    self.subTest(case=index, validator=validator.__name__),
                    self.assertRaises(ValueError),
                ):
                    validator(values, event)

    def test_manifest_changes_only_reviewed_bytes(self):
        self.assertEqual(
            proposal.change_manifest(MANIFEST),
            MANIFEST.replace(b'zstd = "0.13"', b'zstd = "0.14.3"'),
        )

    def test_manifest_rejects_unreviewed_source_generations(self):
        for value in (
            MANIFEST.replace(b'"0.13"', b'"0.14"'),
            MANIFEST.replace(
                b'zstd = "0.13"', b'zstd = { version = "0.13", features = ["keep"] }'
            ),
            MANIFEST.replace(b'zstd = "0.13"', b'zstd="0.13"'),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                proposal.change_manifest(value)

    def test_applied_graph_proposal_fails_before_native_execution(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            output = root / "output"
            originals = {
                proposal.INPUTS[0]: proposal.change_manifest(MANIFEST),
                proposal.INPUTS[1]: lock_fixture(),
                proposal.INPUTS[2]: b"{}\n",
            }
            for path, raw in originals.items():
                destination = checkout / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            with (
                patch.object(proposal, "ROOT", checkout),
                patch.object(proposal, "require_hosted"),
                patch.object(proposal, "git", return_value=""),
                patch.object(proposal.subprocess, "run") as native,
            ):
                with self.assertRaisesRegex(ValueError, "original workspace zstd"):
                    proposal.prepare(output, SOURCE)
                native.assert_not_called()
            saved = json.loads((output / "record.json").read_text())
            self.assertEqual(saved["state"], "preparing")
            self.assertFalse(saved["committed_source_qualified"])
            self.assertTrue(
                all(stage["state"] == "not_started" for stage in saved["stages"])
            )
            self.assertEqual(
                {path: (checkout / path).read_bytes() for path in originals},
                originals,
            )

    def test_lock_keeps_bigint_blocker_open(self):
        extra = '\n[[package]]\nname = "crypto-bigint"\nversion = "0.5.5"\n'
        review = proposal.check_lock(lock_fixture(extra))
        self.assertEqual(review["crypto_bigint_versions"], ["0.5.5"])
        self.assertFalse(review["crypto_bigint_blocker_closed"])

    def test_lock_rejects_duplicate_legacy_package_or_tampered_source(self):
        for value in (
            lock_fixture('\n[[package]]\nname = "zstd"\nversion = "0.13.3"\n'),
            lock_fixture().replace(proposal.TARGETS["ctutils"][1].encode(), b"0" * 64),
            lock_fixture(source="git+https://example.invalid/substitute"),
        ):
            with self.subTest(value=value[:80]), self.assertRaises(ValueError):
                proposal.check_lock(value)

    def test_scope_rejects_manifest_feature_removal_elsewhere(self):
        proposal.validate_changed_paths(proposal.INPUTS)
        with self.assertRaises(ValueError):
            proposal.validate_changed_paths(
                [*proposal.INPUTS, "codex-rs/aws-auth/Cargo.toml"]
            )

    def test_interruption_remains_unknown(self):
        stages = [
            {"name": "completed", "state": "succeeded", "exit_code": 0},
            {"name": "interrupted", "state": "running", "exit_code": None},
            {"name": "not-run", "state": "not_started", "exit_code": None},
        ]
        self.assertEqual(proposal.interrupted_stages(stages), ["interrupted"])
        self.assertIsNone(stages[1]["exit_code"])
        self.assertEqual(stages[2]["state"], "not_started")

    def test_local_invocation_rejected_before_git_or_native_commands(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(proposal, "git") as git,
        ):
            with self.assertRaisesRegex(ValueError, "hosted workflow"):
                proposal.require_hosted(SOURCE, Path("/tmp/proposal"))
            git.assert_not_called()

    def test_hosted_identity_and_output_path_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            checkout.mkdir()
            event_path = root / "event.json"
            event_path.write_text(json.dumps({"inputs": {"source_sha": SOURCE}}))
            environment = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "TrillionniumFoundation/hepta-private-ci",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_SHA": SOURCE,
                "GITHUB_EVENT_PATH": str(event_path),
                "RUNNER_TEMP": temporary,
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(proposal, "ROOT", checkout),
                patch.object(proposal, "git", return_value=SOURCE),
            ):
                proposal.require_hosted(SOURCE, root / "output")
                with self.assertRaises(ValueError):
                    proposal.require_hosted(SOURCE, checkout / "output")
                with self.assertRaises(ValueError):
                    proposal.require_hosted(SOURCE, root.parent / "escape")
                with self.assertRaises(ValueError):
                    proposal.require_hosted("a" * 7, root / "output")
                with (
                    patch.dict(os.environ, {"GITHUB_SHA": "b" * 40}),
                    self.assertRaises(ValueError),
                ):
                    proposal.require_hosted(SOURCE, root / "output")
                with (
                    patch.object(proposal, "git", return_value="b" * 40),
                    self.assertRaises(ValueError),
                ):
                    proposal.require_hosted(SOURCE, root / "output")

    def test_command_failure_retains_real_exit_and_stops_later_stages(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            (checkout / "codex-rs").mkdir(parents=True)
            (checkout / proposal.INPUTS[0]).write_bytes(MANIFEST)
            output = root / "output"
            (output / "logs").mkdir(parents=True)
            record = {
                "source": SOURCE,
                "state": "prepared",
                "original": {proposal.INPUTS[0]: {"sha256": proposal.sha256(MANIFEST)}},
                "stages": [
                    {
                        "name": name,
                        "cwd": cwd,
                        "command": command,
                        "state": "not_started",
                        "exit_code": None,
                    }
                    for name, cwd, command in proposal.COMMANDS
                ],
            }
            proposal.save_record(output, record)
            runner = Mock(return_value=Mock(returncode=37))
            with (
                patch.object(proposal, "ROOT", checkout),
                patch.object(proposal, "require_hosted"),
                patch.object(proposal, "git", return_value=""),
                patch.object(proposal.subprocess, "run", runner),
            ):
                self.assertEqual(proposal.run(output, SOURCE), 37)
            saved = json.loads((output / "record.json").read_text())
            self.assertEqual(saved["state"], "failed")
            self.assertEqual(saved["stages"][0]["exit_code"], 37)
            self.assertTrue(
                all(stage["state"] == "not_started" for stage in saved["stages"][1:])
            )
            runner.assert_called_once()
            self.assertEqual(len(list((output / "logs").iterdir())), 2)

    def test_finalizer_rejects_extra_manifest_edits_and_keeps_artifact_hashes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            output = root / "output"
            originals = {
                proposal.INPUTS[0]: MANIFEST,
                proposal.INPUTS[1]: lock_fixture(),
                proposal.INPUTS[2]: b"{}\n",
            }
            for path, raw in originals.items():
                for directory in (checkout, output / "original"):
                    destination = directory / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(raw)
            manifest = checkout / proposal.INPUTS[0]
            manifest.write_bytes(
                proposal.change_manifest(MANIFEST).replace(b'["keep"]', b"[]")
            )
            record = {
                "source": SOURCE,
                "state": "generated",
                "original": {
                    path: {"sha256": proposal.sha256(raw)}
                    for path, raw in originals.items()
                },
                "stages": [],
                "committed_source_qualified": False,
            }
            proposal.save_record(output, record)
            with (
                patch.object(proposal, "ROOT", checkout),
                patch.object(proposal, "require_hosted"),
                patch.object(proposal, "git", return_value=""),
                patch.object(
                    proposal.subprocess, "check_output", return_value=b"mock patch"
                ),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertEqual(proposal.finalize(output, SOURCE), 1)
            saved = json.loads((output / "record.json").read_text())
            self.assertFalse(saved["ready_for_review"])
            self.assertFalse(saved["committed_source_qualified"])
            self.assertIn("declared mutation", saved["review_errors"][0])
            hashes = json.loads((output / "files.json").read_text())["files"]
            for identity in hashes:
                self.assertEqual(
                    proposal.sha256((output / identity["path"]).read_bytes()),
                    identity["sha256"],
                )


if __name__ == "__main__":
    unittest.main()
