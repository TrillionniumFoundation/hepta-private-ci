"""Small data controls for the reviewed fixture receipt and exact test evidence."""

import copy
import json
import os
from http.client import IncompleteRead
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import conformance_fixture as fixture


def _controls(source: Path) -> tuple[dict, list[str]]:
    names = [f"source-control-{index}" for index in range(8)]
    return {
        "success": True,
        "numFailedTests": 0,
        "numPendingTests": 0,
        "numTodoTests": 0,
        "numFailedTestSuites": 0,
        "numPendingTestSuites": 0,
        "numTotalTests": 8,
        "numPassedTests": 8,
        "numTotalTestSuites": 2,
        "numPassedTestSuites": 2,
        "testResults": [
            {
                "name": str(source.resolve()),
                "status": "passed",
                "message": "",
                "assertionResults": [
                    {
                        "title": name,
                        "fullName": f"Source fixture {name}",
                        "status": "passed",
                        "failureMessages": [],
                    }
                    for name in names
                ],
            }
        ],
    }, names


class FixtureReceiptTests(unittest.TestCase):
    def test_exact_executed_file_and_eight_names_are_required(self):
        source = Path("/fixture/controls.test.ts")
        report, names = _controls(source)
        self.assertEqual(len(fixture.validate_controls(report, source, names)), 8)
        for change in (
            "zero",
            "duplicate",
            "extra",
            "skipped",
            "wrong-file",
            "suite-error",
        ):
            with self.subTest(change=change):
                invalid = copy.deepcopy(report)
                result = invalid["testResults"][0]
                if change == "zero":
                    invalid["numTotalTests"] = invalid["numPassedTests"] = 0
                    result["assertionResults"] = []
                elif change == "duplicate":
                    result["assertionResults"][-1]["title"] = names[0]
                elif change == "extra":
                    result["assertionResults"].append(
                        copy.deepcopy(result["assertionResults"][0])
                    )
                elif change == "skipped":
                    result["assertionResults"][0]["status"] = "skipped"
                elif change == "wrong-file":
                    result["name"] = "/fixture/different.test.ts"
                else:
                    result["message"] = "setup failed"
                with self.assertRaises(ValueError):
                    fixture.validate_controls(invalid, source, names)

    def test_duplicate_json_and_symlink_dist_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "duplicated.json"
            malformed.write_text(
                '{"status":"failed","status":"passed"}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                fixture.read_json(malformed)
            dist = root / "dist"
            dist.mkdir()
            cli = dist / "index.js"
            cli.write_text("process.exit(0);\n", encoding="utf-8")
            first = fixture.snapshot_dist(dist)
            cli.write_text("process.exit(1);\n", encoding="utf-8")
            self.assertNotEqual(fixture.snapshot_dist(dist), first)
            target = root / "outside.js"
            target.write_text("process.exit(0);\n", encoding="utf-8")
            cli.unlink()
            cli.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "regular file"):
                fixture.snapshot_dist(dist)

    def test_manifest_stays_closed_without_explicit_root_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            for value in (
                {"schema": "hepta-oauth-origin-fixture-v2", "activated": False},
                {
                    "schema": "hepta-oauth-origin-fixture-v2",
                    "activated": True,
                    "root_admission": None,
                },
                {
                    "schema": "hepta-oauth-origin-fixture-v2",
                    "activated": True,
                    "root_admission": {
                        "reviewer": "agent",
                        "accepted": True,
                        "sha256": "a" * 64,
                    },
                },
            ):
                with self.subTest(value=value):
                    manifest.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        fixture.load_manifest(manifest)

    def test_raw_commit_preserves_parents_tree_and_message_bytes(self):
        tree = "1" * 40
        parents = ["2" * 40, "3" * 40]
        raw = (
            f"tree {tree}\nparent {parents[0]}\nparent {parents[1]}\n"
            "author Source <source@example.invalid> 1 +0000\n"
            "committer Source <source@example.invalid> 1 +0000\n\nfixture\n"
        ).encode()
        identity = fixture.commit_identity(raw)
        self.assertEqual(identity["tree"], tree)
        self.assertEqual(identity["parents"], parents)
        self.assertIs(identity["dirty"], False)
        self.assertNotEqual(
            fixture.commit_identity(raw + b"\n")["commit"], identity["commit"]
        )
        with self.assertRaisesRegex(ValueError, "tree header"):
            fixture.commit_identity(raw.replace(b"tree ", b"missing "))


class OriginalCandidateIdentityTests(unittest.TestCase):
    def identity(self):
        return {
            "repository": fixture.HEPTA_REPOSITORY,
            "run_id": 101,
            "run_attempt": 1,
            "job_id": 202,
            "job_name": "sdk / sdks",
            "runner_id": 303,
            "runner_name": "current-runner",
            "event_name": "pull_request",
            "event_sha": "e" * 40,
            "source_head": "c" * 40,
            "source_tree": "b4ad17bcbfedbde12183ccac5036d8b57f80bb01",
            "source_parents": [fixture.HEPTA_PARENT["head"]],
            "parent": dict(fixture.HEPTA_PARENT),
            "pr_number": 404,
            "workflow_id": 505,
            "workflow_definition_sha": "e" * 40,
        }

    def job(self):
        return {
            "id": 202,
            "name": "sdk / sdks",
            "runner_id": 303,
            "runner_name": "current-runner",
            "run_id": 101,
            "run_attempt": 1,
            "head_sha": "c" * 40,
            "status": "in_progress",
            "conclusion": None,
            "steps": [
                {
                    "name": fixture.BUILD_STEP,
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": fixture.FIXTURE_STEP,
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": fixture.TEST_STEP,
                    "status": "in_progress",
                    "conclusion": None,
                },
            ],
        }

    def provider_run(self, status="queued"):
        identity = self.identity()
        return {
            "id": identity["run_id"],
            "run_attempt": identity["run_attempt"],
            "head_sha": identity["source_head"],
            "head_branch": "current-candidate",
            "event": identity["event_name"],
            "status": status,
            "conclusion": None,
            "repository": {"full_name": fixture.HEPTA_REPOSITORY},
            "path": ".github/workflows/blocking-ci.yml",
            "workflow_id": identity["workflow_id"],
            "pull_requests": [
                {
                    "number": identity["pr_number"],
                    "head": {"sha": identity["source_head"]},
                    "base": {"sha": fixture.HEPTA_PARENT["head"]},
                }
            ],
            "referenced_workflows": [
                {
                    "path": fixture.HEPTA_REPOSITORY
                    + "/.github/workflows/sdk.yml@"
                    + identity["event_sha"],
                    "sha": identity["event_sha"],
                }
            ],
        }

    def observe_current_execution(self, run, jobs, stage=fixture.TEST_STEP):
        identity = self.identity()
        repository = {"full_name": fixture.HEPTA_REPOSITORY}
        event = {
            "repository": repository,
            "number": identity["pr_number"],
            "pull_request": {
                "head": {
                    "sha": identity["source_head"],
                    "ref": "current-candidate",
                    "repo": repository,
                },
                "base": {"sha": fixture.HEPTA_PARENT["head"], "repo": repository},
            },
        }
        responses = {
            "run": run,
            "jobs-1": {"total_count": len(jobs), "jobs": jobs},
            "source-commit": {
                "sha": identity["source_head"],
                "parents": [{"sha": fixture.HEPTA_PARENT["head"]}],
                "tree": {"sha": identity["source_tree"]},
            },
            "actual-event-merge": {
                "sha": identity["event_sha"],
                "parents": [
                    {"sha": fixture.HEPTA_PARENT["head"]},
                    {"sha": identity["source_head"]},
                ],
                "tree": {"sha": identity["source_tree"]},
            },
        }
        publication = {
            "parent": dict(fixture.HEPTA_PARENT),
            "source_paths": list(fixture.HEPTA_CHANGED_PATHS),
            "requires_actual_parent": True,
            "root_must_bind_final_candidate": True,
        }
        api = mock.Mock()
        api.rows = []
        api.get.side_effect = lambda suffix, label: copy.deepcopy(responses[label])
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory).resolve()
            root = temporary / "source"
            (root / ".git").mkdir(parents=True)
            (root / ".git" / "HEAD").write_text(
                identity["source_head"] + "\n", encoding="utf-8"
            )
            event_path = temporary / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            output = temporary / "identity"
            output.mkdir()
            environment = {
                "GITHUB_WORKSPACE": str(root),
                "GITHUB_EVENT_PATH": str(event_path),
                "GITHUB_REPOSITORY": fixture.HEPTA_REPOSITORY,
                "GITHUB_RUN_ID": str(identity["run_id"]),
                "GITHUB_RUN_ATTEMPT": str(identity["run_attempt"]),
                "GITHUB_EVENT_NAME": identity["event_name"],
                "GITHUB_SHA": identity["event_sha"],
                "HEPTA_C2_SOURCE_HEAD": identity["source_head"],
                "GITHUB_JOB": "sdks",
                "RUNNER_NAME": identity["runner_name"],
                "GITHUB_WORKFLOW_SHA": identity["workflow_definition_sha"],
            }
            with mock.patch.dict(os.environ, environment):
                with mock.patch.object(fixture, "IdentityAPI", return_value=api):
                    observed, observed_api = fixture.current_execution(
                        {"publication": publication},
                        root,
                        output,
                        time.monotonic() + 2,
                        stage,
                    )
            self.assertIs(observed_api, api)
            self.assertEqual(
                [call.args[1] for call in api.get.call_args_list],
                ["run", "jobs-1", "source-commit", "actual-event-merge"],
            )
            context = json.loads((output / "context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["identity"], observed)
            self.assertEqual(context["actual_step"], stage)
            return observed

    def test_current_execution_queued_run_requires_active_original_job_and_step(self):
        stages = (fixture.BUILD_STEP, fixture.FIXTURE_STEP, fixture.TEST_STEP)
        for state in ("queued", "in_progress"):
            for current, stage in enumerate(stages):
                with self.subTest(state=state, stage=stage):
                    job = self.job()
                    for index, step in enumerate(job["steps"]):
                        step["status"] = (
                            "completed"
                            if index < current
                            else "in_progress"
                            if index == current
                            else "queued"
                        )
                        step["conclusion"] = "success" if index < current else None
                    queued_sibling = {
                        "id": 203,
                        "name": "other queued job",
                        "status": "queued",
                        "conclusion": None,
                        "runner_name": None,
                    }
                    self.assertEqual(
                        self.observe_current_execution(
                            self.provider_run(state), [job, queued_sibling], stage
                        ),
                        self.identity(),
                    )
        cases = {}
        cases["missing-job"] = []
        cases["ambiguous-job"] = [self.job(), dict(self.job(), id=203)]
        for field, value in (
            ("run_id", 102),
            ("run_attempt", 2),
            ("head_sha", "d" * 40),
            ("runner_name", "other-runner"),
            ("status", "queued"),
            ("conclusion", "failure"),
        ):
            cases["wrong-job-" + field] = [dict(self.job(), **{field: value})]
        for name in (
            "nonactive-step",
            "duplicate-step",
            "failed-build",
            "pending-fixture",
        ):
            job = self.job()
            if name == "nonactive-step":
                job["steps"][2]["status"] = "queued"
            elif name == "duplicate-step":
                job["steps"].append(copy.deepcopy(job["steps"][2]))
            elif name == "failed-build":
                job["steps"][0]["conclusion"] = "failure"
            else:
                job["steps"][1].update(status="in_progress", conclusion=None)
            cases[name] = [job]
        for name, jobs in cases.items():
            with self.subTest(rejection=name):
                with self.assertRaises(ValueError):
                    self.observe_current_execution(self.provider_run(), jobs)

    def test_current_execution_rejects_run_identity_and_terminal_states(self):
        for field, value in (
            ("id", 102),
            ("run_attempt", 2),
            ("head_sha", "d" * 40),
            ("head_branch", "other-candidate"),
            ("event", "push"),
        ):
            with self.subTest(field=field):
                run = self.provider_run()
                run[field] = value
                with self.assertRaisesRegex(ValueError, "original run identity"):
                    self.observe_current_execution(run, [self.job()])
        for status in (
            "completed",
            "waiting",
            "requested",
            "pending",
            "cancelled",
            "unknown",
            None,
        ):
            with self.subTest(status=status):
                with self.assertRaisesRegex(
                    ValueError, "terminal or has an unsupported state"
                ):
                    self.observe_current_execution(
                        self.provider_run(status), [self.job()]
                    )
        for status in ("queued", "in_progress"):
            for conclusion in ("success", "failure", "cancelled", "skipped"):
                with self.subTest(status=status, conclusion=conclusion):
                    run = self.provider_run(status)
                    run["conclusion"] = conclusion
                    with self.assertRaisesRegex(
                        ValueError, "terminal or has an unsupported state"
                    ):
                        self.observe_current_execution(run, [self.job()])

    def test_same_head_old_run_attempt_and_job_are_rejected(self):
        identity = self.identity()
        source = {
            "complete": True,
            "tree": identity["source_tree"],
            "files": {},
            "errors": [],
        }
        binaries = {
            name: {"bytes": 7, "sha256": "d" * 64}
            for name in ("codex", "code_mode_host")
        }
        receipt = {
            "schema": "hepta-sdk-original-build-v1",
            "status": "pending-original-step-terminal",
            "build_step": fixture.BUILD_STEP,
            "original_build_exit_code": 0,
            "source_before": source,
            "source_after": copy.deepcopy(source),
            "identity_before": identity,
            "identity_after": copy.deepcopy(identity),
            "original_binaries": binaries,
            "staged_binaries": copy.deepcopy(binaries),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "build.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with mock.patch.object(
                fixture, "verified_source", return_value=(identity, source)
            ) as observation:
                with mock.patch.object(
                    fixture, "current_staged_binaries", return_value=binaries
                ):
                    self.assertEqual(
                        fixture.inspect_original_build(
                            path,
                            {},
                            root,
                            root,
                            time.monotonic() + 2,
                            fixture.TEST_STEP,
                        )["identity"],
                        identity,
                    )
                    for field in ("run_id", "run_attempt", "job_id", "runner_id"):
                        with self.subTest(field=field):
                            current = copy.deepcopy(identity)
                            current[field] += 1
                            observation.return_value = (current, source)
                            with self.assertRaisesRegex(
                                ValueError, "old run/attempt/job"
                            ):
                                fixture.inspect_original_build(
                                    path,
                                    {},
                                    root,
                                    root,
                                    time.monotonic() + 2,
                                    fixture.TEST_STEP,
                                )

    def test_publication_requires_actual_parent_and_exact_roster(self):
        publication = {
            "parent": dict(fixture.HEPTA_PARENT),
            "source_paths": list(fixture.HEPTA_CHANGED_PATHS),
            "requires_actual_parent": True,
            "root_must_bind_final_candidate": True,
        }
        self.assertEqual(
            fixture.publication_binding({"publication": publication}), publication
        )
        for change in (
            "old-parent",
            "wrong-tree",
            "missing-path",
            "extra-path",
            "reordered",
            "authority",
        ):
            with self.subTest(change=change):
                invalid = copy.deepcopy(publication)
                if change == "old-parent":
                    invalid["parent"]["head"] = "0" * 40
                elif change == "wrong-tree":
                    invalid["parent"]["tree"] = "0" * 40
                elif change == "missing-path":
                    invalid["source_paths"].pop()
                elif change == "extra-path":
                    invalid["source_paths"].append("unreviewed.py")
                elif change == "reordered":
                    invalid["source_paths"].reverse()
                else:
                    invalid["root_must_bind_final_candidate"] = False
                with self.assertRaises(ValueError):
                    fixture.publication_binding({"publication": invalid})

    def test_binary_receipt_rejects_wrong_bytes_or_missing_sibling(self):
        original = {
            name: {"bytes": 7, "sha256": "a" * 64}
            for name in ("codex", "code_mode_host")
        }
        fixture.compare_build_binaries(original, copy.deepcopy(original))
        for change in ("bytes", "sha256", "missing", "extra"):
            with self.subTest(change=change):
                staged = copy.deepcopy(original)
                if change == "bytes":
                    staged["codex"]["bytes"] += 1
                elif change == "sha256":
                    staged["codex"]["sha256"] = "b" * 64
                elif change == "missing":
                    del staged["code_mode_host"]
                else:
                    staged["unreviewed"] = staged["codex"]
                with self.assertRaises(ValueError):
                    fixture.compare_build_binaries(original, staged)

    def test_binary_mutation_changes_actual_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("codex", "code_mode_host"):
                (root / name).write_bytes(b"original binary\n")
                (root / name).chmod(0o755)
            first = {
                name: fixture.binary_identity(root / name, time.monotonic() + 2)
                for name in ("codex", "code_mode_host")
            }
            (root / "codex").write_bytes(b"replaced binary\n")
            after = {
                name: fixture.binary_identity(root / name, time.monotonic() + 2)
                for name in first
            }
            self.assertNotEqual(first["codex"]["sha256"], after["codex"]["sha256"])
            with self.assertRaisesRegex(ValueError, "differs from original build"):
                fixture.compare_build_binaries(first, after)

            bounded = root / "bounded"
            bounded.write_bytes(b"0123456789abcdef")
            bounded.chmod(0o755)
            with mock.patch.object(fixture, "BINARY_BYTES_LIMIT", 16):
                accepted = fixture.binary_identity(bounded, time.monotonic() + 2)
                self.assertEqual(accepted["bytes"], 16)
                with self.assertRaisesRegex(ValueError, "exceeds byte bound"):
                    fixture.file_observation(bounded, time.monotonic() + 2, maximum=8)
                bounded.write_bytes(b"0123456789abcdefg")
                with self.assertRaisesRegex(ValueError, "exceeds byte bound"):
                    fixture.binary_identity(bounded, time.monotonic() + 2)
                bounded.write_bytes(b"0123456789abcdef")
                bounded.chmod(0o644)
                with self.assertRaisesRegex(ValueError, "not executable"):
                    fixture.binary_identity(bounded, time.monotonic() + 2)
                bounded.chmod(0o755)
                with self.assertRaisesRegex(ValueError, "nonregular identity file"):
                    fixture.binary_identity(root, time.monotonic() + 2)
                with self.assertRaisesRegex(ValueError, "existing deadline"):
                    fixture.binary_identity(bounded, time.monotonic() - 1)

            oversized_source = {
                "sha": "1" * 40,
                "truncated": False,
                "tree": [
                    {
                        "path": "source",
                        "type": "blob",
                        "mode": "100644",
                        "size": fixture.SOURCE_BYTES_LIMIT + 1,
                        "sha": "2" * 40,
                    }
                ],
            }
            self.assertGreater(fixture.BINARY_BYTES_LIMIT, fixture.SOURCE_BYTES_LIMIT)
            with self.assertRaisesRegex(ValueError, "source size"):
                fixture.source_map(oversized_source, "1" * 40)

    def test_full_physical_tree_rejects_changed_file_and_symlink(self):
        files = {
            "item": {
                "bytes": 7,
                "git_blob": "5a18cd2fbf65e961b0fd3f6cd6b0b6160f2c808e",
                "mode": "100644",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "item"
            path.write_bytes(b"source\n")
            first = fixture.physical_source(root, files, time.monotonic() + 2)
            self.assertTrue(first["complete"])
            self.assertEqual(first["tree"], "b4ad17bcbfedbde12183ccac5036d8b57f80bb01")
            path.write_bytes(b"changed")
            self.assertFalse(
                fixture.physical_source(root, files, time.monotonic() + 2)["complete"]
            )
            path.unlink()
            outside = root / "outside"
            outside.write_bytes(b"source\n")
            path.symlink_to(outside)
            failure = fixture.physical_source(root, files, time.monotonic() + 2)
            self.assertFalse(failure["complete"])
            self.assertIsNone(failure["tree"])
            self.assertEqual([row["path"] for row in failure["errors"]], ["item"])

    def test_full_tree_digest_rejects_claimed_wrong_blob(self):
        tree = "b4ad17bcbfedbde12183ccac5036d8b57f80bb01"
        document = {
            "sha": tree,
            "truncated": False,
            "tree": [
                {
                    "path": "item",
                    "type": "blob",
                    "mode": "100644",
                    "size": 7,
                    "sha": "5a18cd2fbf65e961b0fd3f6cd6b0b6160f2c808e",
                },
            ],
        }
        self.assertEqual(fixture.source_map(document, tree)["item"]["bytes"], 7)
        for change in ("wrong-blob", "truncated", "duplicate", "wrong-mode"):
            with self.subTest(change=change):
                invalid = copy.deepcopy(document)
                if change == "wrong-blob":
                    invalid["tree"][0]["sha"] = "0" * 40
                elif change == "truncated":
                    invalid["truncated"] = True
                elif change == "duplicate":
                    invalid["tree"].append(copy.deepcopy(invalid["tree"][0]))
                else:
                    invalid["tree"][0]["mode"] = "100755"
                with self.assertRaises(ValueError):
                    fixture.source_map(invalid, tree)

    def test_current_job_rejects_ambiguity_and_wrong_attempt(self):
        job = self.job()
        self.assertEqual(
            fixture.select_original_job(
                [job], 101, 1, "c" * 40, "current-runner", fixture.TEST_STEP
            ),
            job,
        )
        for rows in (
            [],
            [job, copy.deepcopy(job)],
            [dict(job, run_attempt=2)],
            [dict(job, head_sha="d" * 40)],
            [dict(job, runner_name="other-runner")],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    fixture.select_original_job(
                        rows, 101, 1, "c" * 40, "current-runner", fixture.TEST_STEP
                    )

    def test_original_build_prerequisite_cannot_be_pending_or_failed(self):
        for prior in (fixture.BUILD_STEP, fixture.FIXTURE_STEP):
            for state, result in (
                ("in_progress", None),
                ("completed", "failure"),
                ("completed", "cancelled"),
                ("completed", "skipped"),
            ):
                with self.subTest(prior=prior, state=state, result=result):
                    job = self.job()
                    step = next(row for row in job["steps"] if row["name"] == prior)
                    step.update(status=state, conclusion=result)
                    with self.assertRaisesRegex(ValueError, "prerequisite step"):
                        fixture.select_original_job(
                            [job], 101, 1, "c" * 40, "current-runner", fixture.TEST_STEP
                        )

    def test_identity_api_retains_partial_failure_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            response.headers = {"x-request-id": "local-negative-control"}
            response.geturl.return_value = (
                "https://api.github.com/repos/" + fixture.HEPTA_REPOSITORY + "/local"
            )
            failure = IncompleteRead(b"received-prefix", 3)
            response.read.side_effect = failure
            opener = mock.Mock()
            opener.open.return_value = response
            with mock.patch.dict(os.environ, {"GH_TOKEN": "local-control-only"}):
                with mock.patch.object(
                    fixture.urllib.request, "build_opener", return_value=opener
                ):
                    api = fixture.IdentityAPI(output, time.monotonic() + 2)
                    with self.assertRaises(IncompleteRead):
                        api.get("/local", "partial")
            self.assertEqual((output / "partial.body").read_bytes(), b"received-prefix")
            row = json.loads((output / "partial.json").read_text(encoding="utf-8"))
            self.assertEqual(row["received_bytes"], len(b"received-prefix"))
            self.assertEqual(row["retained_bytes"], len(b"received-prefix"))
            self.assertEqual(row["headers"], {"x-request-id": "local-negative-control"})
            self.assertNotIn("body_eof", row)
            self.assertIn("body_read_error", row)


if __name__ == "__main__":
    unittest.main()
