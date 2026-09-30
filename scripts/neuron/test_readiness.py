from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("readiness.py")
REPO = SCRIPT.resolve().parents[2]
SPEC = REPO / "docs/modules/neuron.runtime/MODULE_SPEC.json"
MODULE_SPEC = importlib.util.spec_from_file_location("neuron_readiness", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
readiness = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(readiness)


class ReadinessTests(unittest.TestCase):
    """Real temporary Git objects; compiler/host observations are explicit fixtures."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.evidence_dir = Path(self.temp.name) / "evidence"
        self.spec = json.loads(SPEC.read_text())
        self.spec_path = self.root / SPEC.relative_to(REPO)
        self.spec_path.parent.mkdir(parents=True)
        self.spec_path.write_text(json.dumps(self.spec, indent=2) + "\n")
        for item in self.spec["documents"]:
            path = self.root / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.name}\n")
        for name in (
            "scripts/neuron/readiness.py",
            "scripts/neuron/readiness_evidence.py",
            self.spec["qualification"]["workflow"],
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((REPO / name).read_bytes())
        lock = self.root / "codex-rs/Cargo.lock"
        lock.parent.mkdir(exist_ok=True)
        lock.write_text("# fixture lock\n")
        self.patch = mock.patch.object(readiness, "ROOT", self.root)
        self.patch.start()
        readiness.render(self.spec_path, check=False)
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "commit",
            "-qm",
            "base",
        )
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "source-marker").write_text("source\n")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "commit",
            "-qm",
            "source",
        )
        self.source = self.git("rev-parse", "HEAD")
        self.objects = readiness.provenance.candidate(self.root, self.source, self.base)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def git(self, *args):
        return readiness.provenance.git(self.root, *args)

    def capture_args(self, gate_id):
        gate = readiness.gate_by_id(self.spec, gate_id)
        tested, tree = self.objects[gate["lane"]]
        system, arch, target = readiness.provenance.PLATFORMS[gate["platform"]]
        return argparse.Namespace(
            spec=self.spec_path,
            gate=gate_id,
            source_sha=self.source,
            base_sha=self.base,
            tested_sha=tested,
            tree_sha=tree,
            lane=gate["lane"],
            toolchain=gate["toolchain"],
            target_triple=target,
            workflow=self.spec["qualification"]["workflowName"],
            run_id="42",
            run_attempt="1",
            job=gate_id,
            repository=self.spec["qualification"]["repository"],
            runner_name="fixture-runner",
            runner_os=system,
            runner_arch=arch,
            runner_image="fixture-image",
            result="success",
            stage_outcomes=json.dumps(
                {key: "success" for key in readiness.required_stages(gate)}
            ),
            output=self.evidence_dir / f"{gate_id}.provenance.json",
        )

    def capture(self, gate_id):
        args = self.capture_args(gate_id)
        self.git("checkout", "--detach", "-q", args.tested_sha)
        observed = {
            "release": self.spec["toolchains"][args.toolchain],
            "host": args.target_triple,
        }
        with (
            mock.patch.object(
                readiness.provenance, "actual_rust", return_value=observed
            ),
            mock.patch.dict("os.environ", {"RUNNER_ENVIRONMENT": "fixture"}),
        ):
            readiness.capture(args)
        return args.output

    def aggregate(
        self,
        name="READINESS_MANIFEST.json",
        allow_incomplete=False,
        qualification_outcome="success",
        download_outcome="success",
    ):
        self.git("checkout", "--detach", "-q", self.source)
        args = argparse.Namespace(
            spec=self.spec_path,
            evidence_dir=self.evidence_dir,
            source_sha=self.source,
            base_sha=self.base,
            workflow=self.spec["qualification"]["workflowName"],
            run_id="42",
            run_attempt="1",
            repository=self.spec["qualification"]["repository"],
            output=Path(self.temp.name) / name,
            allow_incomplete=allow_incomplete,
            qualification_outcome=qualification_outcome,
            download_outcome=download_outcome,
        )
        readiness.aggregate(args)
        return json.loads(args.output.read_text())

    def complete(self):
        for gate in self.spec["qualification"]["requiredGates"]:
            self.capture(gate["id"])

    def test_rendered_projections_are_current_and_activation_is_false(self):
        readiness.render(self.spec_path, check=True)
        data = readiness.load_json(
            self.root / self.spec["paths"]["productionActivation"]
        )
        self.assertIs(data["productionActivation"], False)

    def test_generated_document_links_resolve_inside_and_outside_docs(self):
        import re

        index = self.root / self.spec["paths"]["docsIndex"]
        targets = re.findall(r"\]\(([^)]+)\)", index.read_text())
        self.assertEqual(len(targets), len(self.spec["documents"]))
        for target, item in zip(targets, self.spec["documents"]):
            self.assertEqual(
                (index.parent / target).resolve(), (self.root / item["path"]).resolve()
            )
            self.assertTrue((index.parent / target).is_file())

    def test_render_rejects_missing_bound_document(self):
        (self.root / self.spec["documents"][0]["path"]).unlink()
        with self.assertRaises(readiness.ReadinessError):
            readiness.render(self.spec_path, check=True)

    def test_capture_contains_required_bindings(self):
        data = readiness.load_json(self.capture("linux-stable-source-head"))
        self.assertEqual(data["testedSha"], self.source)
        self.assertEqual(
            data["observedRust"],
            {"release": "1.95.0", "host": "x86_64-unknown-linux-gnu"},
        )
        self.assertEqual(data["workflow"]["runId"], "42")
        self.assertIn("workflowSha256", data["bindings"])
        self.assertIn("provenanceValidatorSha256", data["bindings"])

    def test_aggregate_accepts_one_complete_same_candidate_set(self):
        self.complete()
        report = self.aggregate()
        self.assertTrue(report["qualificationReady"])
        self.assertFalse(report["productionActivation"])
        self.assertFalse(report["hostedExecutionIndependentlyVerified"])
        self.assertEqual(len(report["inputEvidence"]), 8)

    def test_aggregate_rejects_mixed_source_sha(self):
        path = self.capture("linux-stable-source-head")
        data = readiness.load_json(path)
        data["sourceSha"] = self.base
        path.write_text(json.dumps(data))
        report = self.aggregate(allow_incomplete=True)
        self.assertFalse(report["qualificationReady"])
        self.assertIn(
            "evidence source SHA does not match requested candidate", report["blockers"]
        )

    def test_aggregate_rejects_failed_or_missing_gate(self):
        self.capture("linux-stable-source-head")
        report = self.aggregate(allow_incomplete=True)
        self.assertFalse(report["qualificationReady"])
        self.assertTrue(
            any(item.startswith("missing evidence") for item in report["blockers"])
        )

    def test_rejects_changed_identity_platform_run_step_or_claim(self):
        self.complete()
        path = self.evidence_dir / "linux-stable-source-head.provenance.json"
        original = readiness.load_json(path)
        changes = [
            (("testedSha",), self.base),
            (("testedTree",), self.base),
            (("module",), "other"),
            (("workflow", "runId"), "43"),
            (("workflow", "runAttempt"), "2"),
            (("workflow", "repository"), "other/repo"),
            (("workflow", "job"), "other"),
            (("runner", "targetTriple"), "aarch64-unknown-linux-gnu"),
            (("runner", "fingerprintSha256"), "0" * 64),
            (("observedRust", "release"), "1.88.0"),
            (("stageOutcomes", "frozen"), "skipped"),
            (("claimBoundary", "release"), True),
            (("claimBoundary", "qualificationGatePassed"), 1),
            (("workflow",), None),
            (("runner",), None),
            (("sourceSha",), []),
            (("schema",), "hepta.neuron.runtime.qualification-provenance.v1"),
        ]
        for index, (keys, value) in enumerate(changes):
            with self.subTest(keys=keys):
                current = copy.deepcopy(original)
                target = current
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                path.write_text(json.dumps(current))
                result = self.aggregate(f"changed-{index}.json", allow_incomplete=True)
                self.assertFalse(result["qualificationReady"])
        path.write_text(json.dumps(original))

    def test_capture_rejects_dirty_checkout_before_publication(self):
        args = self.capture_args("linux-stable-source-head")
        (self.root / "untracked").write_text("uncommitted\n")
        with self.assertRaises(ValueError):
            readiness.capture(args)
        self.assertFalse(args.output.exists())

    def test_capture_rejects_another_commit_for_source_lane(self):
        args = self.capture_args("linux-stable-source-head")
        args.tested_sha = self.base
        with self.assertRaises(readiness.ReadinessError):
            readiness.capture(args)
        self.assertFalse(args.output.exists())

    def test_capture_rejects_actual_compiler_or_target_mismatch(self):
        args = self.capture_args("linux-stable-source-head")
        with mock.patch.object(
            readiness.provenance,
            "actual_rust",
            return_value={"release": "1.88.0", "host": args.target_triple},
        ):
            with self.assertRaises(readiness.ReadinessError):
                readiness.capture(args)
        self.assertFalse(args.output.exists())

    def test_evidence_and_manifest_are_never_overwritten(self):
        self.complete()
        path = self.evidence_dir / "linux-stable-source-head.provenance.json"
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.capture("linux-stable-source-head")
        self.assertEqual(path.read_bytes(), original)
        self.aggregate()
        with self.assertRaises(FileExistsError):
            self.aggregate()

    def test_json_rejects_duplicate_nonfinite_and_oversized_evidence(self):
        path = Path(self.temp.name) / "input.json"
        for value in (
            b'{"result":1,"result":2}',
            b'{"result":NaN}',
            b" " * (readiness.provenance.MAX_EVIDENCE_BYTES + 1),
        ):
            path.write_bytes(value)
            with self.assertRaises(readiness.ReadinessError):
                readiness.load_json(path)

    def test_record_with_null_source_is_a_diagnostic_not_an_exception(self):
        path = self.capture("linux-stable-source-head")
        data = readiness.load_json(path)
        data["sourceSha"] = None
        path.write_text(json.dumps(data))
        self.assertFalse(self.aggregate(allow_incomplete=True)["qualificationReady"])

    def test_synthetic_merge_is_recomputed_from_exact_git_objects(self):
        merge, tree = self.objects["synthetic-merge"]
        self.assertEqual(
            self.git("show", "-s", "--format=%P", merge), f"{self.base} {self.source}"
        )
        self.assertEqual(
            self.git("merge-tree", "--write-tree", self.base, self.source), tree
        )
        path = self.capture("linux-stable-synthetic-merge")
        self.assertEqual(readiness.load_json(path)["testedSha"], merge)

    def test_synthetic_lane_accepts_a_genuinely_different_merge_tree(self):
        self.git("checkout", "--detach", "-q", self.base)
        (self.root / "base-marker").write_text("independent base change\n")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "commit",
            "-qm",
            "advanced base",
        )
        self.base = self.git("rev-parse", "HEAD")
        self.objects = readiness.provenance.candidate(self.root, self.source, self.base)
        self.assertNotEqual(
            self.objects["source-head"][1], self.objects["synthetic-merge"][1]
        )
        self.complete()
        self.assertTrue(self.aggregate()["qualificationReady"])

    def test_capture_cannot_upgrade_failed_required_stage(self):
        args = self.capture_args("linux-stable-source-head")
        stages = json.loads(args.stage_outcomes)
        stages["frozen"] = "failure"
        args.stage_outcomes = json.dumps(stages)
        with mock.patch.object(
            readiness.provenance,
            "actual_rust",
            return_value={"release": "1.95.0", "host": args.target_triple},
        ):
            with self.assertRaises(readiness.ReadinessError):
                readiness.capture(args)
        self.assertFalse(args.output.exists())

    def test_workflow_final_result_requires_all_job_outcomes(self):
        import os
        import textwrap

        workflow = (REPO / self.spec["qualification"]["workflow"]).read_text()
        script = textwrap.dedent(
            workflow.split("name: Require every target and candidate gate", 1)[1].split(
                "run: |", 1
            )[1]
        )
        env = os.environ.copy()
        names = ("QUALIFICATION_OUTCOME", "DOWNLOAD_OUTCOME", "AGGREGATE_OUTCOME")
        env.update(dict.fromkeys(names, "success"))
        self.assertEqual(subprocess.run(["bash", "-c", script], env=env).returncode, 0)
        for name in names:
            with self.subTest(outcome=name):
                env[name] = "failure"
                self.assertNotEqual(
                    subprocess.run(["bash", "-c", script], env=env).returncode, 0
                )
                env[name] = "success"

    def test_manifest_rejects_a_post_capture_matrix_failure(self):
        self.complete()
        report = self.aggregate(allow_incomplete=True, qualification_outcome="failure")
        self.assertFalse(report["qualificationReady"])
        self.assertIn("qualification matrix is failure", report["blockers"])

    def test_manifest_rejects_incomplete_artifact_download(self):
        self.complete()
        report = self.aggregate(allow_incomplete=True, download_outcome="failure")
        self.assertFalse(report["qualificationReady"])
        self.assertIn("artifact download is failure", report["blockers"])


if __name__ == "__main__":
    unittest.main()
