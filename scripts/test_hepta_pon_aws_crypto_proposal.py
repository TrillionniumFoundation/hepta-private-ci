"""Static and failure controls only; no Cargo, Rust, Bazel or crypto is executed."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import hepta_pon_aws_crypto_proposal as hosted
import hepta_pon_aws_crypto_source as source
from hepta_pon_dependency_proposal import source_from_event


SHA = "a" * 40
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
WORKFLOW = hosted.ROOT / ".github/workflows/hepta-pon-aws-crypto-proposal.yml"


def bootstrap(environment, event):
    script = textwrap.dedent(
        WORKFLOW.read_text()
        .split("python3 - <<'PY_SOURCE'\n", 1)[1]
        .split("          PY_SOURCE\n", 1)[0]
    )
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        event_file = directory / "event.json"
        output = directory / "output"
        event_file.write_text(json.dumps(event))
        with patch.dict(
            os.environ,
            {
                **environment,
                "GITHUB_EVENT_PATH": str(event_file),
                "GITHUB_OUTPUT": str(output),
            },
            clear=True,
        ):
            exec(compile(script, "aws-proposal-precheckout", "exec"), {})
        return output.read_text().strip().removeprefix("source=")


def synthetic_lock():
    # Parser-only fixture. Never written over a real project dependency lock.
    sections = [
        f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = "{hosted.REGISTRY}"\nchecksum = "{checksum}"\n'
        for name, (version, checksum) in hosted.TARGETS.items()
    ]
    sections.append('[[package]]\nname = "aws-config"\nversion = "1.8.12"\n')
    return "\n".join(sections).encode()


def synthetic_metadata():
    packages = [
        {"id": name, "name": name, "version": version, "source": hosted.REGISTRY}
        for name, (version, _) in hosted.TARGETS.items()
    ]
    packages.append(
        {
            "id": "provider",
            "name": "aws-config",
            "version": "1.8.12",
            "source": None,
            "manifest_path": str(hosted.ROOT / hosted.VENDOR / "Cargo.toml"),
        }
    )
    nodes = [{"id": package["id"], "features": []} for package in packages]
    nodes[-1]["features"] = [
        "credentials-login",
        "credentials-process",
        "default",
        "default-https-client",
        "rt-tokio",
        "sso",
    ]
    next(node for node in nodes if node["id"] == "aws-sigv4")["features"] = [
        "sigv4a",
        "default",
        "sign-http",
        "http1",
    ]
    return {
        "packages": packages,
        "workspace_members": ["provider"],
        "resolve": {"nodes": nodes},
    }


class HostedControls(unittest.TestCase):
    def test_failed_command_keeps_raw_failure_and_remaining_stage_denominator(self):
        with TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            output = Path(temporary) / "output"
            for name in hosted.INPUTS:
                destination = checkout / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.frozen_inputs()[name])

            def failed_command(_args, **kwargs):
                kwargs["stderr"].write(b"synthetic command failure control\n")
                return SimpleNamespace(returncode=23)

            with (
                patch.object(hosted, "ROOT", checkout),
                patch.object(
                    hosted,
                    "static_review",
                    side_effect=lambda: source.static_review(source.frozen_inputs()),
                ),
                patch.object(hosted, "require_hosted"),
                patch.object(hosted, "git", return_value=""),
                patch.object(
                    hosted.subprocess, "run", side_effect=failed_command
                ) as native,
            ):
                hosted.prepare(output, SHA)
                self.assertEqual(hosted.run(output, SHA), 23)
                native.assert_called_once()
            record = json.loads((output / "record.json").read_text())
            self.assertEqual(
                (
                    record["state"],
                    record["stages"][0]["state"],
                    record["stages"][0]["exit_code"],
                ),
                ("failed", "failed", 23),
            )
            self.assertTrue(
                all(stage["state"] == "not_started" for stage in record["stages"][1:])
            )
            self.assertEqual(
                (output / "logs/cargo-version.stderr.txt").read_bytes(),
                b"synthetic command failure control\n",
            )
            self.assertFalse(record["committed_source_qualified"])

    def test_interruption_preserves_unknown_outcome_and_never_qualifies(self):
        with TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            output = Path(temporary) / "output"
            for name in hosted.INPUTS:
                destination = checkout / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.frozen_inputs()[name])

            def interrupted_command(_args, **kwargs):
                kwargs["stderr"].write(b"synthetic interruption control\n")
                raise KeyboardInterrupt

            with (
                patch.object(hosted, "ROOT", checkout),
                patch.object(
                    hosted,
                    "static_review",
                    side_effect=lambda: source.static_review(source.frozen_inputs()),
                ),
                patch.object(hosted, "require_hosted"),
                patch.object(hosted, "git", return_value=""),
                patch.object(hosted.subprocess, "run", side_effect=interrupted_command),
                patch.object(hosted.subprocess, "check_output", return_value=b""),
                patch.dict(os.environ, {"PROPOSAL_STEP_OUTCOME": "cancelled"}),
            ):
                hosted.prepare(output, SHA)
                with self.assertRaises(KeyboardInterrupt):
                    hosted.run(output, SHA)
                self.assertEqual(hosted.finalize(output, SHA), 1)
            record = json.loads((output / "record.json").read_text())
            self.assertEqual(record["interrupted_or_unknown_stages"], ["cargo-version"])
            self.assertIsNone(record["stages"][0]["exit_code"])
            self.assertEqual(record["workflow_proposal_step_outcome"], "cancelled")
            self.assertFalse(record["ready_for_review"])
            self.assertFalse(record["committed_source_qualified"])
            files = json.loads((output / "files.json").read_text())["files"]
            diagnostic = next(
                entry
                for entry in files
                if entry["path"] == "logs/cargo-version.stderr.txt"
            )
            self.assertEqual(
                diagnostic["sha256"],
                hashlib.sha256(b"synthetic interruption control\n").hexdigest(),
            )

    def test_exact_pr_and_dispatch_sources_use_the_same_fail_closed_contract(self):
        pr_environment = {
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/4080/merge",
            "GITHUB_SHA": "b" * 40,
        }
        pr_event = {
            "number": 4080,
            "action": "synchronize",
            "pull_request": {
                "head": {"sha": SHA, "repo": {"full_name": REPOSITORY, "fork": False}},
                "base": {"repo": {"full_name": REPOSITORY}},
            },
        }
        dispatch_environment = {
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": SHA,
        }
        dispatch_event = {"inputs": {"source_sha": SHA}}
        for environment, event in [
            (pr_environment, pr_event),
            (dispatch_environment, dispatch_event),
        ]:
            for validator in [source_from_event, bootstrap]:
                self.assertEqual(validator(environment, event), SHA)
        negatives = []
        for field, value in [
            ("fork", True),
            ("fork", None),
            ("full_name", "foreign/repo"),
        ]:
            event = deepcopy(pr_event)
            event["pull_request"]["head"]["repo"][field] = value
            negatives.append((pr_environment, event))
        for value in [None, "A" * 40, "a" * 7]:
            event = deepcopy(pr_event)
            event["pull_request"]["head"]["sha"] = value
            negatives.append((pr_environment, event))
        negatives.extend(
            [
                (pr_environment, {**pr_event, "inputs": {"source_sha": SHA}}),
                (
                    {**pr_environment, "GITHUB_EVENT_NAME": "pull_request_target"},
                    pr_event,
                ),
                ({**pr_environment, "GITHUB_REF": "refs/pull/4079/merge"}, pr_event),
                (dispatch_environment, {}),
                (dispatch_environment, {"inputs": {"source_sha": "b" * 40}}),
                (
                    dispatch_environment,
                    {**dispatch_event, "pull_request": pr_event["pull_request"]},
                ),
            ]
        )
        for index, (environment, event) in enumerate(negatives):
            for validator in [source_from_event, bootstrap]:
                with (
                    self.subTest(case=index, validator=validator.__name__),
                    self.assertRaises(ValueError),
                ):
                    validator(environment, event)

    def test_local_run_is_rejected_before_any_native_process(self):
        with (
            TemporaryDirectory() as temporary,
            patch.dict(os.environ, {}, clear=True),
            patch.object(hosted.subprocess, "run") as native,
        ):
            with self.assertRaisesRegex(
                ValueError, "restricted to the declared hosted workflow"
            ):
                hosted.run(Path(temporary), SHA)
            native.assert_not_called()

    def test_lock_parser_rejects_legacy_duplicate_and_forged_packages(self):
        valid = synthetic_lock()
        hosted.check_lock(valid)
        negatives = [
            valid + b'\n[[package]]\nname = "crypto-bigint"\nversion = "0.5.5"\n',
            valid.replace(hosted.TARGETS["p256"][1].encode(), b"0" * 64),
            valid.replace(
                b'name = "aws-config"\nversion = "1.8.12"',
                b'name = "aws-config"\nversion = "1.8.12"\nsource = "registry+https://github.com/rust-lang/crates.io-index"',
            ),
        ]
        for raw in negatives:
            with self.assertRaises(ValueError):
                hosted.check_lock(raw)

    def test_metadata_cannot_claim_sigv4a_or_credentials_that_were_not_enabled(self):
        metadata = synthetic_metadata()
        hosted.check_metadata(json.dumps(metadata), True)
        for identifier, feature in [
            ("provider", "credentials-login"),
            ("provider", "sso"),
            ("provider", "default"),
            ("aws-sigv4", "sigv4a"),
        ]:
            altered = deepcopy(metadata)
            node = next(
                node for node in altered["resolve"]["nodes"] if node["id"] == identifier
            )
            node["features"].remove(feature)
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                hosted.check_metadata(json.dumps(altered), True)
        altered = deepcopy(metadata)
        altered["packages"][-1]["manifest_path"] = "/substitute/Cargo.toml"
        with self.assertRaises(ValueError):
            hosted.check_metadata(json.dumps(altered), True)


if __name__ == "__main__":
    unittest.main()
