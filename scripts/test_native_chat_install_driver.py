"""Actual ordinary process boundaries plus isolated service fault injection."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import native_chat_install_io as io
import native_chat_install_plan as plan
from native_chat_install_test_support import fixture

SCRIPT = Path(__file__).with_name("hepta-install-native-chat")
loader = importlib.machinery.SourceFileLoader("native_chat_installer", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
loader.exec_module(installer)


@unittest.skipUnless(sys.platform == "linux", "closed Linux installer process boundary")
class PhysicalCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".hepta-install-test-", dir=Path.home()
        )
        self.root = Path(self.temporary.name)
        self.uid = os.getuid()

    def tearDown(self):
        self.temporary.cleanup()

    def test_helper_unknown_retains_physical_child_and_never_replays(self):
        marker = self.root / "executions"
        program = "import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); p.write_text('one'); time.sleep(.15)"
        children = []
        popen = subprocess.Popen

        def record(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        with patch.object(installer.subprocess, "Popen", side_effect=record):
            with self.assertRaisesRegex(
                installer.UnknownCommand, "outcome unknown; inspect original child PID"
            ):
                installer.command(
                    [sys.executable, "-c", program, str(marker)],
                    time.monotonic() + 0.05,
                )
        self.assertEqual(len(children), 1)
        children[0].communicate(timeout=2)
        self.assertEqual(children[0].returncode, 0)
        self.assertEqual(marker.read_text(), "one")

    def test_non_root_entry_refuses_before_any_request_read(self):
        if self.uid == 0:
            self.skipTest("the normal-caller denial requires a non-Root process")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(SCRIPT),
                "prepare",
                "--request",
                str(self.root / "missing"),
                "--sha256",
                "0" * 64,
            ],
            capture_output=True,
            timeout=2,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"Root alone", result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])


@unittest.skipUnless(sys.platform == "linux", "closed Linux systemd installer")
class InterruptedActivationTests(unittest.TestCase):
    def test_partial_stop_unknown_is_retained_and_explicit_restore_does_not_replay(
        self,
    ):
        with tempfile.TemporaryDirectory(
            prefix=".hepta-install-fault-", dir=Path.home()
        ) as directory:
            root = Path(directory)
            request, policy, unit, desktop = fixture()
            desktop_path = root / "hepta-native/config.json"
            desktop_path.parent.mkdir(mode=0o700)
            desktop_path.write_bytes(desktop)
            desktop_path.chmod(0o600)
            request["desktop_config"]["path"] = str(desktop_path)
            checked = plan.checked(request, policy, unit, desktop)
            checked.update(
                namespace=root,
                desktop_bytes=desktop,
                template=b"Group=@ENROLLED_GATEWAY_GROUP@\nExecStart=@IMMUTABLE_PROGRAM@\n",
            )
            replacements = {
                name: root / name.lower()
                for name in (
                    "POLICY",
                    "GATEWAY_DROPIN",
                    "BRIDGE_UNIT",
                    "BRIDGE_CONFIG",
                    "CAPABILITY",
                )
            }
            replacements["POLICY"].write_bytes(checked["target_policy"])
            replacements["POLICY"].chmod(0o600)
            (root / "account.json").write_bytes(io.encode({"account": "fresh-chat"}))
            (root / "account.json").chmod(0o600)
            (root / "chat.capability").write_bytes(b"test-new-key-never-logged")
            (root / "chat.capability").chmod(0o600)
            original = {"pid": 123, "start_ticks": 456, "dropins": ""}
            read = io.read_public
            create = io.durable_create
            parents = io.protected_parents
            commands = []

            def test_create(path, data, mode=0o600, uid=0, gid=0):
                create(path, data, mode, os.getuid(), os.getgid())

            def stopped(*args, deadline):
                commands.append(args)
                raise installer.UnknownCommand(789)

            with (
                patch.object(
                    io,
                    "protected_parents",
                    side_effect=lambda path, owner=0: parents(path, os.getuid()),
                ),
                patch.multiple(plan, **replacements),
                patch.object(
                    io,
                    "read_public",
                    side_effect=lambda path, owner=0: read(path, os.getuid()),
                ),
                patch.object(io, "durable_create", side_effect=test_create),
                patch.object(installer, "owner_epoch"),
                patch.object(installer, "gateway", return_value=original),
            ):
                io.log(root, "prepared", original_gateway=original)
                io.log(root, "keyring-paired", account="fresh-chat")
                with patch.object(installer, "systemctl", side_effect=stopped):
                    with self.assertRaises(installer.UnknownCommand):
                        installer.activate(checked, "original-epoch")
                    with self.assertRaises(ValueError):
                        installer.activate(checked, "original-epoch")
                self.assertEqual(commands, [("stop", plan.GATEWAY_SERVICE)])
                last = json.loads(read(root / "phase-03.json", os.getuid()))
                self.assertEqual(
                    last,
                    {
                        "phase": "activation-outcome-unresolved",
                        "epoch": "original-epoch",
                        "child_pid": 789,
                    },
                )
                self.assertEqual(desktop_path.read_bytes(), desktop)

                def restoring(*args, deadline):
                    commands.append(args)
                    if args[0] == "show":
                        return b"inactive\n" if args[-1] == "ActiveState" else b"\n"
                    return b""

                with patch.object(installer, "systemctl", side_effect=restoring):
                    result = installer.restore(checked, "original-epoch")
                    with self.assertRaises(ValueError):
                        installer.restore(checked, "original-epoch")
                self.assertEqual(
                    result["status"], "original-read-lifecycle-behavior-restored"
                )
                self.assertEqual(
                    replacements["GATEWAY_DROPIN"].read_bytes(), plan.dropin(checked)
                )
                self.assertEqual(desktop_path.read_bytes(), desktop)
                self.assertEqual(
                    (root / "chat.capability").read_bytes(),
                    b"test-new-key-never-logged",
                )
                self.assertNotIn(("start", plan.BRIDGE_SERVICE), commands)
                for phase in root.glob("phase-*.json"):
                    self.assertNotIn(b"test-new-key-never-logged", phase.read_bytes())


if __name__ == "__main__":
    unittest.main()
