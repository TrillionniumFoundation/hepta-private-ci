"""Synthetic frozen-input rejection controls; no Ruff, model, or training runs."""

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = load("procedural_support", HERE / "procedural_support.py")
TRIAL = load("_procedural_trial_explicit_checks", HERE / "procedural_trial.py")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class ExplicitProceduralChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.counter = 0

    def fixture(self, corruption=None):
        self.counter += 1
        root = self.root / str(self.counter)
        archive_root = root / "repo" / "qa" / "memory-budget-20261024"
        archive_root.mkdir(parents=True)
        ruff = root / "ruff-original"
        ruff.write_bytes(b"synthetic executable identity only; never executed\n")
        count = 16 if corruption == "member_count" else 17
        files = {
            f"source_{index:02d}.txt": b"synthetic fixture\n" for index in range(count)
        }
        if corruption == "member_path":
            files["../outside.txt"] = files.pop("source_00.txt")
        pins = {
            "ruff-runtime/bin/ruff": digest(ruff.read_bytes()),
            **{
                "task-fixtures/lint-original/" + name: digest(raw)
                for name, raw in files.items()
            },
        }
        if corruption == "ruff_pin":
            pins["ruff-runtime/bin/ruff"] = "0" * 64
        if corruption == "member_pin":
            pins["task-fixtures/lint-original/source_00.txt"] = "0" * 64
        buffer = io.BytesIO()
        prefix = "memory-budget-evidence-20261024/"
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            members = {
                prefix + "prepared-001/protocol.json": json.dumps(
                    {"task_fixture_files": pins}
                ).encode(),
                **{
                    prefix + "task-fixtures/lint-original/" + name: raw
                    for name, raw in files.items()
                },
            }
            for name, raw in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
        raw = buffer.getvalue()
        (archive_root / "part-000").write_bytes(raw)
        part = {"path": "part-000", "bytes": len(raw), "sha256": digest(raw)}
        manifest = {"archive": {"parts": [part], "sha256": digest(raw)}}
        if corruption == "part_size":
            part["bytes"] += 1
        if corruption == "part_pin":
            part["sha256"] = "0" * 64
        if corruption == "archive_pin":
            manifest["archive"]["sha256"] = "0" * 64
        (archive_root / "evidence-manifest.json").write_text(json.dumps(manifest))
        return root, root / "repo", ruff

    def test_exact_synthetic_archive_keeps_original_seventeen_member_contract(self):
        root, repo, ruff = self.fixture()
        receipt = SUPPORT.extract_fixture(repo, root / "output", ruff)
        self.assertEqual(len(receipt["original_fixture_files"]), 17)
        self.assertEqual(receipt["original_semantic_tests"], 76)
        self.assertEqual(receipt["ruff_sha256"], digest(ruff.read_bytes()))

    def test_archive_identity_and_member_rejections_survive_optimization(self):
        for corruption in (
            "part_size",
            "part_pin",
            "archive_pin",
            "ruff_pin",
            "member_path",
            "member_pin",
            "member_count",
        ):
            with self.subTest(corruption=corruption):
                root, repo, ruff = self.fixture(corruption)
                with self.assertRaises(AssertionError):
                    SUPPORT.extract_fixture(repo, root / "output", ruff)

    def test_prepare_rejects_unexpected_teaching_diagnostic_before_commands(self):
        root, repo, ruff = self.fixture()
        args = argparse.Namespace(
            output=root / "prepared",
            repo=repo,
            ruff=ruff,
            python=Path(sys.executable),
            model=root / "model",
        )
        with (
            patch.object(TRIAL, "diagnostic", return_value=({}, ["UNREGISTERED"])),
            patch.object(
                TRIAL, "command", side_effect=RuntimeError("FORBIDDEN_COMMAND")
            ) as command,
            self.assertRaises(AssertionError),
        ):
            TRIAL.prepare(args)
        command.assert_not_called()

    def test_trial_rejects_retained_protocol_source_and_base_before_commands(self):
        for boundary in ("protocol", "implementation", "base"):
            with self.subTest(boundary=boundary):
                self.counter += 1
                root = self.root / str(self.counter)
                output, repo, model = root / "output", root / "repo", root / "model"
                for path in (output, repo, model):
                    path.mkdir(parents=True)
                (repo / "source.py").write_bytes(b"# synthetic source\n")
                (model / "config.json").write_bytes(b"{}")
                protocol = {
                    "implementation": {
                        "source.py": digest((repo / "source.py").read_bytes())
                    },
                    "base_inventory": {
                        "config.json": {"bytes": 2, "sha256": digest(b"{}")}
                    },
                    "seeds": [],
                    "retrieval_operation": "ruff check --fix",
                }
                if boundary == "implementation":
                    protocol["implementation"]["source.py"] = "0" * 64
                if boundary == "base":
                    protocol["base_inventory"]["config.json"]["bytes"] += 1
                raw = json.dumps(protocol).encode()
                (output / "protocol.json").write_bytes(raw)
                args = argparse.Namespace(
                    output=output,
                    repo=repo,
                    model=model,
                    ruff=root / "unused-ruff",
                    python=Path(sys.executable),
                    protocol_sha256="0" * 64 if boundary == "protocol" else digest(raw),
                )
                with (
                    patch.object(
                        TRIAL, "command", side_effect=RuntimeError("FORBIDDEN_COMMAND")
                    ) as command,
                    patch.object(
                        TRIAL, "execute", side_effect=RuntimeError("FORBIDDEN_EXECUTE")
                    ) as execute,
                    self.assertRaises(AssertionError),
                ):
                    TRIAL.trial(args)
                command.assert_not_called()
                execute.assert_not_called()

    def test_worker_rejects_bad_spec_pin_and_mode_before_model_or_reader(self):
        spec = self.root / "training.json"
        spec.write_text(
            json.dumps(
                {
                    "rank": 8,
                    "scope": "synthetic",
                    "facts": [],
                    "steps": 1,
                    "learning_rate": 0.001,
                    "templates": [],
                }
            )
        )
        requests = [
            {
                "mode": "train",
                "training_spec": str(spec),
                "training_spec_sha256": "0" * 64,
                "model": "not-a-model",
                "seed": 1,
            },
            {"mode": "unregistered", "payload": {}},
        ]
        harness = """
import pathlib, runpy, sys, types
def forbidden(*args, **kwargs):
    raise RuntimeError("FORBIDDEN_MODEL_OR_READER")
sys.modules["torch"] = types.SimpleNamespace(set_num_threads=lambda _: None)
sys.modules["parametric_model"] = types.SimpleNamespace(SourceMemoryCell=forbidden)
sys.modules["parametric_worker"] = types.SimpleNamespace(run=forbidden)
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
runpy.run_path(sys.argv[1], run_name="__main__")
"""
        for request in requests:
            with self.subTest(mode=request["mode"]):
                argv = [sys.executable, "-I", "-S", "-B"]
                if sys.flags.optimize:
                    argv.append("-O")
                argv.extend(["-c", harness, str(HERE / "procedural_worker.py")])
                result = subprocess.run(
                    argv,
                    input=json.dumps(request),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("AssertionError", result.stderr)
                self.assertNotIn("FORBIDDEN_MODEL_OR_READER", result.stderr)

    def test_executor_retains_before_state_and_exact_changed_path_guards(self):
        for boundary in ("before", "changed_path"):
            with self.subTest(boundary=boundary):
                self.counter += 1
                root = self.root / str(self.counter)
                original = root / "original"
                target = original / SUPPORT.TARGET
                target.parent.mkdir(parents=True)
                target.write_text("# original target\n")
                (original / "unrelated.py").write_text("# unchanged\n")

                def command(argv, cwd, output, **kwargs):
                    output.mkdir(parents=True)
                    (output / "stdout.log").write_text("F401 E731\n")
                    (output / "stderr.log").write_text("Ran 76 tests\n")
                    if output.name == "action" and boundary == "changed_path":
                        (Path(cwd) / "unrelated.py").write_text("# changed\n")
                    return {
                        "returncode": 0
                        if boundary == "before" or output.name != "before"
                        else 1
                    }

                with patch.object(SUPPORT, "command", side_effect=command):
                    with self.assertRaises(AssertionError):
                        SUPPORT.execute(
                            root / "unused-ruff",
                            Path(sys.executable),
                            original,
                            root / "execution",
                            "ruff check --fix",
                        )


if __name__ == "__main__":
    unittest.main()
