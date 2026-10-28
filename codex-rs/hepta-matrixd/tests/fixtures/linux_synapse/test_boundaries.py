"""Real small-file/process failures, never a fake Synapse qualification."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from . import prep_inside
from .commands import Commands
from .contract import SCHEMA, TARGET, TOOLS, SYNAPSE_REF, SYNAPSE_ID, SYNAPSE_VERSION
from .contract import (
    SYNAPSE_REVISION,
    PLATFORM,
    load_contract,
    reject_compiler_overrides,
    validate_synapse_labels,
)
from .files import atomic_publish, checksum, copy_file, describe, inventory, relative
from .files import stage_directory, verify, write_bytes, write_json


def example_contract():
    identity = {"bytes": 1, "sha256": "a" * 64}
    return {
        "schema": SCHEMA,
        "target": TARGET,
        "rust_release": "1.96.0",
        "nextest_version": "0.9.103",
        "image": {
            "reference": "example.invalid/builder@sha256:" + "b" * 64,
            "config_id": "sha256:" + "c" * 64,
            "os": "linux",
            "architecture": "arm64",
        },
        "tools": {name: {"path": "/usr/bin/" + name, **identity} for name in TOOLS},
        "tool_bundle": {"mount_path": "/hepta-tools", "files": {}},
        "control_docker": {"path": "/hepta-control/docker", **identity},
        "synapse": {
            "reference": SYNAPSE_REF,
            "config_id": SYNAPSE_ID,
            "version": SYNAPSE_VERSION,
            "revision": SYNAPSE_REVISION,
            "platform": PLATFORM,
        },
    }


class FileBoundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-linux-boundary-")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_copy_readback_and_changed_input_rejected(self):
        source, destination = self.root / "input", self.root / "output"
        write_bytes(source, b"actual preserved bytes\n")
        identity = copy_file(source, destination)
        self.assertEqual(describe(destination), identity)
        source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            verify(source, identity)
        self.assertEqual(destination.read_bytes(), b"actual preserved bytes\n")

    def test_symlink_and_special_file_rejected(self):
        write_bytes(self.root / "regular", b"x")
        (self.root / "link").symlink_to(self.root / "regular")
        with self.assertRaises(ValueError):
            describe(self.root / "link")
        with self.assertRaises(ValueError):
            inventory(self.root)
        (self.root / "link").unlink()
        os.mkfifo(self.root / "fifo")
        with self.assertRaises(ValueError):
            inventory(self.root)

    def test_nonoverwriting_atomic_publication(self):
        stage = stage_directory(self.root, "result")
        write_bytes(stage / "raw", b"first")
        destination = self.root / "result"
        atomic_publish(stage, destination)
        second = stage_directory(self.root, "result")
        write_bytes(second / "raw", b"second failed attempt remains")
        with self.assertRaises(ValueError):
            atomic_publish(second, destination)
        self.assertEqual((destination / "raw").read_bytes(), b"first")
        self.assertEqual(
            (second / "raw").read_bytes(), b"second failed attempt remains"
        )

    def test_invalid_paths_do_not_create_output(self):
        for name in (".", "../escape", "/absolute", "x//y", "x\\y", "x/../y", "x\ny"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative(name)
        with self.assertRaises(ValueError):
            stage_directory(self.root, "x/y")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_ancestor_symlink_rejected_before_any_external_write(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        source = self.root / "source"
        write_bytes(source, b"preserve")
        attacks = (
            lambda: write_bytes(self.root / "link/new/file", b"bad"),
            lambda: copy_file(source, self.root / "link/new/file"),
            lambda: inventory(self.root / "link/empty"),
            lambda: stage_directory(self.root / "link", "candidate"),
        )
        for attack in attacks:
            with self.assertRaises(ValueError):
                attack()
            self.assertEqual(list(outside.iterdir()), [])
        stage = stage_directory(self.root, "publish")
        with self.assertRaises(ValueError):
            atomic_publish(stage, self.root / "link/result")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertTrue(stage.is_dir())

    def test_nonzero_child_keeps_exact_stdout_stderr(self):
        python = Path(sys.executable).resolve()
        tool = {"path": str(python), **describe(python)}
        commands = Commands(self.root / "logs", {"python": tool}, {}, self.root)
        with self.assertRaises(RuntimeError):
            commands.run(
                "python",
                [
                    "-I",
                    "-c",
                    "import sys; print('before failure'); sys.stderr.write('reason\\n'); sys.exit(9)",
                ],
                label="failure",
            )
        record = json.loads((self.root / "logs/000-END.json").read_text())
        self.assertEqual(record["exit_code"], 9)
        self.assertTrue(record["executable_unchanged"])
        self.assertEqual(
            (self.root / "logs/000-failure.stdout").read_bytes(), b"before failure\n"
        )
        self.assertEqual(
            (self.root / "logs/000-failure.stderr").read_bytes(), b"reason\n"
        )
        self.assertGreaterEqual(record["child_cpu_seconds"], 0)

    def tool_probe_environment_child(self):
        # A real controlled child checks the subprocess environment boundary.
        # This is not Rustup and never produces a native tool qualification.
        child = self.root / "environment-child"
        script = """import json
import os
import sys
if os.environ.get("CARGO_HOME") != "/usr/local/cargo":
    sys.stderr.write("error: failed to determine cargo home: could not find cargo home dir\\n")
    sys.exit(1)
print(json.dumps({"arguments": sys.argv[1:], "cwd": os.getcwd(), "environment": dict(os.environ)}))
"""
        write_bytes(
            child, ("#!" + str(Path(sys.executable).resolve()) + "\n" + script).encode()
        )
        child.chmod(0o700)
        return child

    def test_tool_probe_passes_image_cargo_home_without_host_environment(self):
        child = self.tool_probe_environment_child()
        output = self.root / "probe"

        class LookupCompleted(Exception):
            pass

        class StopAfterLookup(Commands):
            def text(self, tool, args, *, label):
                super().text(tool, args, label=label)
                raise LookupCompleted

        with (
            mock.patch.object(prep_inside.platform, "system", return_value="Linux"),
            mock.patch.object(prep_inside.platform, "machine", return_value="aarch64"),
            mock.patch.object(prep_inside, "TOOLS", {"cargo"}),
            mock.patch.object(prep_inside.shutil, "which", return_value=str(child)),
            mock.patch.object(prep_inside, "Commands", StopAfterLookup),
            mock.patch.dict(
                os.environ,
                {
                    "CARGO_HOME": "/host/unmounted-cargo",
                    "HOME": "/host/unmounted-home",
                    "HEPTA_CI_HOST_MARKER": "must-not-be-inherited",
                },
            ),
            self.assertRaises(LookupCompleted),
        ):
            prep_inside.probe_tools(output)
        directory = output / "bootstrap-tool-commands"
        record = json.loads((directory / "000-END.json").read_text())
        actual = json.loads((directory / "000-actual-cargo.stdout").read_text())
        self.assertEqual(actual["arguments"], ["which", "cargo"])
        self.assertEqual(actual["cwd"], "/")
        self.assertEqual(actual["environment"], record["environment"])
        self.assertEqual(actual["environment"]["CARGO_HOME"], "/usr/local/cargo")
        self.assertEqual(actual["environment"]["RUSTUP_HOME"], "/usr/local/rustup")
        self.assertFalse(
            {"HOME", "HEPTA_CI_HOST_MARKER"} & actual["environment"].keys()
        )
        self.assertEqual(record["exit_code"], 0)
        self.assertTrue(record["executable_unchanged"])
        self.assertEqual((directory / "000-actual-cargo.stderr").read_bytes(), b"")
        self.assertFalse((output / "TOOL_PROBE.json").exists())

    def test_missing_cargo_home_retains_observed_failure_bytes(self):
        child = self.tool_probe_environment_child()
        directory = self.root / "failed-probe"
        commands = Commands(
            directory,
            {"rustup": {"path": str(child), **describe(child)}},
            {"RUSTUP_HOME": "/usr/local/rustup"},
            Path("/"),
        )
        with self.assertRaisesRegex(RuntimeError, "actual-cargo failed with exit 1"):
            commands.text("rustup", ["which", "cargo"], label="actual-cargo")
        record = json.loads((directory / "000-END.json").read_text())
        stderr = directory / "000-actual-cargo.stderr"
        self.assertEqual(
            stderr.read_bytes(),
            b"error: failed to determine cargo home: could not find cargo home dir\n",
        )
        self.assertEqual(record["stderr"], {"path": stderr.name, **describe(stderr)})
        self.assertEqual(record["exit_code"], 1)
        self.assertTrue(record["executable_unchanged"])
        self.assertEqual((directory / "000-actual-cargo.stdout").read_bytes(), b"")

    def test_pinned_synapse_publisher_labels_and_mutations(self):
        # Exact labels observed in the failed native-arm64 preflight artifact.
        labels = {
            "org.opencontainers.image.version": "1.159.0",
            "gitsha1": "7b10e6b9bc2dacc33f0974c999f640b55ef831bc",
        }
        expected = example_contract()["synapse"]
        validate_synapse_labels(labels, expected)
        for changed in (
            {**labels, "gitsha1": "0" * 40},
            {**labels, "org.opencontainers.image.version": "1.158.0"},
            {"org.opencontainers.image.version": "1.159.0"},
            {**labels, "org.opencontainers.image.revision": "0" * 40},
            None,
        ):
            with self.subTest(labels=changed), self.assertRaises(ValueError):
                validate_synapse_labels(changed, expected)

    def test_contract_digest_and_platform_rejected_before_execution(self):
        contract = example_contract()
        path = self.root / "seal.json"
        write_json(path, contract)
        self.assertEqual(load_contract(path, checksum(path)), contract)
        for digest in (None, "", 123, "d" * 64):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                load_contract(path, digest)
        for index, mutation in enumerate(
            ("architecture", "image_tag", "extra_tool", "external_unsealed")
        ):
            value = copy.deepcopy(contract)
            if mutation == "architecture":
                value["image"]["architecture"] = "amd64"
            elif mutation == "image_tag":
                value["image"]["reference"] = "example.invalid/builder:latest"
            elif mutation == "extra_tool":
                value["tools"]["unreviewed"] = value["tools"]["sh"]
            else:
                value["tools"]["just"]["path"] = "/hepta-tools/just"
            candidate = self.root / f"bad-{index}.json"
            write_json(candidate, value)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                load_contract(candidate, checksum(candidate))

    def test_compiler_overrides_even_empty_fail_closed(self):
        for name in (
            "RUSTC",
            "RUSTC_WRAPPER",
            "LD_PRELOAD",
            "CARGO_PROFILE_DEV_OPT_LEVEL",
            "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                reject_compiler_overrides({name: ""})
        reject_compiler_overrides(
            {"LANG": "C", "PATH": "/untrusted-but-never-inherited"}
        )


if __name__ == "__main__":
    unittest.main()
