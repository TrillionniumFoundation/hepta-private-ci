"""Publication/identity/phase rejection tests in a disposable Git fixture.

The fixture remote ref is synthetic and is never presented as publication of a
real study. Real rebuilt executables are mandatory inputs to this test module.
"""

import argparse
import ast
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from experiments.continuous_boundary_policy.common import (
    ARMS,
    CONTROLS,
    SEEDS,
    save_json,
    sha,
)
from . import identity, sources
from .sources import BINARY_SHA, PACKAGE, REPOSITORY

BINARIES = {}


def git(root, *args):
    return (
        subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        identity.verify_binaries(BINARIES)
        cls.temporary = tempfile.TemporaryDirectory(prefix="hepta-reproduction-tests-")
        cls.root = Path(cls.temporary.name)
        cls.repo = cls.root / "repository"
        cls.package = cls.repo / PACKAGE.relative_to(REPOSITORY)
        old = json.loads(
            (
                REPOSITORY / "experiments/continuous_boundary_policy/SOURCE_SEAL.json"
            ).read_bytes()
        )
        paths = set(old["source_files"]) | {
            "experiments/continuous_boundary_policy/SOURCE_SEAL.json",
            "experiments/continuous_boundary_flow/SOURCE_SEAL.json",
        }
        for relative in paths:
            target = cls.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / relative, target)
        shutil.copytree(
            PACKAGE,
            cls.package,
            ignore=shutil.ignore_patterns(
                "__pycache__", "SOURCE_SEAL.json", "evidence", "results"
            ),
        )
        shutil.copyfile(
            cls.package / "preflight/SCORE_BUILD.preformat.json",
            cls.package / "preflight/SCORE_BUILD.json",
        )
        sources.freeze_source(cls.repo)
        git(cls.repo, "init", "--quiet")
        git(cls.repo, "config", "user.name", "Reproduction test fixture")
        git(cls.repo, "config", "user.email", "fixture@example.invalid")
        git(cls.repo, "add", ".")
        git(cls.repo, "commit", "--quiet", "-m", "synthetic publication fixture")
        cls.commit = git(cls.repo, "rev-parse", "HEAD")
        git(cls.repo, "update-ref", identity.REMOTE, cls.commit)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.output = self.root / self._testMethodName

    def initialize(self):
        return identity.initialize(self.output, BINARIES, self.commit, self.repo)

    def sealed_phase_fixture(self):
        self.initialize()
        identity.begin_training(self.output)
        identity.mark_phase(self.output, "TRAINING_COMPLETE")
        env = json.loads((self.output / "ENVIRONMENT.json").read_bytes())
        selection = {
            "schema": "hepta.continuous-boundary-policy.selection.v1",
            "protocol_sha256": env["protocol_sha256"],
            "source_seal_sha256": env["source_seal_sha256"],
            "native_binary_sha256": BINARY_SHA["native"],
            "score_binary_sha256": BINARY_SHA["score"],
            "checkpoints": [
                {"seed": seed, "arm": arm} for seed in SEEDS for arm in ARMS + CONTROLS
            ],
            "training_files": {
                str(p.relative_to(self.output)): sha(p.read_bytes())
                for p in self.output.rglob("*")
                if p.is_file() and p.name != "costs.jsonl"
            },
            "training_costs_prefix_sha256": sha(b""),
            "training_costs_prefix_bytes": 0,
        }
        save_json(self.output / "SELECTION_SEAL.json", selection)
        return selection

    def test_valid_published_identity_and_initialization(self):
        env = self.initialize()
        self.assertEqual(env, identity.verify_frozen(self.output, BINARIES, self.repo))
        self.assertEqual(env["binary_sha256"], BINARY_SHA)
        with self.assertRaises(ValueError):
            self.initialize()

    def test_local_unpublished_commit_rejected_before_output(self):
        git(
            self.repo,
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "unpublished local fixture",
        )
        unpublished = git(self.repo, "rev-parse", "HEAD")
        with self.assertRaises(subprocess.CalledProcessError):
            identity.initialize(self.output, BINARIES, unpublished, self.repo)
        self.assertFalse(self.output.exists())

    def test_wrong_or_abbreviated_publication_rejected(self):
        relative = str((self.package / "PROTOCOL.json").relative_to(self.repo))
        with self.assertRaises(ValueError):
            identity.verify_publication(
                self.commit, relative, b"wrong bytes", self.repo
            )
        with self.assertRaises(ValueError):
            identity.verify_publication(self.commit[:12], relative, b"", self.repo)

    def test_binary_missing_swapped_and_mutated_rejected(self):
        fake = self.root / "not-a-native-binary"
        fake.write_bytes(b"diagnostic tamper fixture")
        for binaries in (
            {"native": BINARIES["native"]},
            {**BINARIES, "score": fake},
            {"native": BINARIES["score"], "score": BINARIES["native"]},
        ):
            with self.subTest(keys=list(binaries)):
                with self.assertRaises(ValueError):
                    identity.initialize(self.output, binaries, self.commit, self.repo)
                self.assertFalse(self.output.exists())

    def test_run_plan_and_environment_binding_mutations_rejected(self):
        self.initialize()
        path = self.output / "REPRODUCTION_PLAN.json"
        raw = path.read_bytes()
        path.write_bytes(raw + b" ")
        with self.assertRaises(ValueError):
            identity.verify_frozen(self.output, BINARIES, self.repo)
        path.write_bytes(raw)
        path = self.output / "ENVIRONMENT.json"
        env = json.loads(path.read_bytes())
        env["binary_sha256"]["native"] = "0" * 64
        path.write_text(json.dumps(env))
        with self.assertRaises(ValueError):
            identity.verify_frozen(self.output, BINARIES, self.repo)

    def test_source_missing_original_or_new_implementation_rejected(self):
        source = json.loads((self.package / "SOURCE_SEAL.json").read_bytes())
        for relative in (
            "experiments/continuous_boundary_policy/training.py",
            "experiments/continuous_boundary_policy_reproduction/identity.py",
        ):
            changed = copy.deepcopy(source)
            changed["source_files"].pop(relative)
            with self.assertRaises(ValueError):
                sources.verify_source(changed, self.repo)

    def test_source_original_bytes_drift_rejected(self):
        path = self.repo / "experiments/continuous_boundary_policy/training.py"
        raw = path.read_bytes()
        try:
            path.write_bytes(raw + b"\n")
            with self.assertRaises(ValueError):
                identity.initialize(self.output, BINARIES, self.commit, self.repo)
            self.assertFalse(self.output.exists())
        finally:
            path.write_bytes(raw)

    def test_training_restart_and_early_confirmation_rejected(self):
        self.initialize()
        with self.assertRaises(ValueError):
            identity.verify_preconfirmation(self.output)
        identity.begin_training(self.output)
        with self.assertRaises(ValueError):
            identity.begin_training(self.output)
        with self.assertRaises(ValueError):
            identity.verify_preconfirmation(self.output)

    def test_confirmation_artifacts_partial_hosts_and_retry_rejected(self):
        self.sealed_phase_fixture()
        identity.verify_preconfirmation(self.output)
        for name in (
            "EXTERNAL_SELECTION.json",
            "MANIFEST.json",
            "contexts/2203/test_id.json",
            "phases/CONFIRMATION_COMPLETE.json",
        ):
            path = self.output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
            with self.assertRaises(ValueError):
                identity.verify_preconfirmation(self.output)
            path.unlink()
        (self.output / "confirmation_hosts").mkdir()
        with self.assertRaises(ValueError):
            identity.verify_preconfirmation(self.output)

    def test_selected_training_cost_mutation_rejected(self):
        self.sealed_phase_fixture()
        (self.output / "costs.jsonl").write_bytes(b"{}\n")
        with self.assertRaises(ValueError):
            identity.verify_preconfirmation(self.output)

    def test_train_confirm_algorithm_ast_parity(self):
        old = ast.parse(
            (REPOSITORY / "experiments/continuous_boundary_policy/study.py").read_text()
        )
        new = ast.parse((PACKAGE / "phases.py").read_text())
        for name in ("train", "confirm"):
            functions = []
            for tree in (old, new):
                node = copy.deepcopy(
                    next(
                        n
                        for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == name
                    )
                )
                body = []
                for item in node.body:
                    if (
                        isinstance(item, ast.If)
                        and isinstance(item.test, ast.Call)
                        and isinstance(item.test.func, ast.Attribute)
                        and item.test.func.attr == "exists"
                    ):
                        continue
                    if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call):
                        call = item.value
                        called = getattr(call.func, "id", None)
                        if called in {
                            "verify_frozen",
                            "begin_training",
                            "verify_preconfirmation",
                            "mark_phase",
                        }:
                            continue
                        if called == "verify_publication":
                            call.args[1] = ast.Constant(
                                value="namespace-only-path-change"
                            )
                    body.append(item)
                node.body = body
                functions.append(ast.dump(node, include_attributes=False))
            self.assertEqual(*functions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--score-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    global BINARIES
    BINARIES = {"native": args.native_binary, "score": args.score_binary}
    if args.output.exists():
        raise ValueError("Test receipt already exists")
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(IdentityTests)
    )
    receipt = {
        "schema": "hepta.boundary-policy-reproduction.identity-tests.v1",
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "passed": result.wasSuccessful(),
        "wall_seconds": time.perf_counter() - started,
        "binary_sha256": BINARY_SHA,
        "synthetic_git_fixture": True,
        "formal_study_initialized": False,
        "source_sha256": {p.name: sha(p.read_bytes()) for p in PACKAGE.glob("*.py")},
    }
    save_json(args.output, receipt)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
