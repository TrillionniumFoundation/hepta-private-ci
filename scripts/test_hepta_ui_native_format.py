"""Keep complete cargo-fmt coverage while bounding Windows process arguments."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_ui_native_format as native_format


class NativeFormatTests(unittest.TestCase):
    def test_follows_local_dependency_workspaces_and_cycles_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()

            def package(name, dependencies=(), edition="2024"):
                return {
                    "manifest_path": str(root / name / "Cargo.toml"),
                    "targets": [
                        {
                            "src_path": str(root / name / "src/lib.rs"),
                            "edition": edition,
                        },
                        {
                            "src_path": str(root / name / "tests/contract.rs"),
                            "edition": edition,
                        },
                    ],
                    "dependencies": [{"path": str(root / dep)} for dep in dependencies]
                    + [{"path": None}],
                }

            app = package("app", ("owner", "adapter"))
            adapter = package("adapter", ("app",))
            owner = package("owner", ("app", "vendor"))
            sibling = package("owner-sibling")
            vendor = package("vendor", edition="2021")
            responses = {
                str(root / "app/Cargo.toml"): [app, adapter],
                str(root / "owner/Cargo.toml"): [owner, sibling],
                str(root / "vendor/Cargo.toml"): [vendor],
            }
            with patch.object(
                subprocess,
                "check_output",
                side_effect=lambda args, **_: json.dumps(
                    {"packages": responses[args[-1]]}
                ),
            ) as metadata:
                targets = native_format.collect_targets(root / "app/Cargo.toml")
            self.assertEqual(metadata.call_count, 3)
            self.assertEqual(
                targets,
                {
                    Path(target["src_path"]): target["edition"]
                    for p in (app, adapter, owner, sibling, vendor)
                    for target in p["targets"]
                },
            )
            self.assertTrue(
                all("--offline" in call.args[0] for call in metadata.call_args_list)
            )

    def test_batches_preserve_every_target_edition_and_check_flag(self):
        # Spaces and non-BMP characters exercise Windows quoting and UTF-16 size.
        targets = {
            Path(
                f"/fixture workspace/目录😀/{'long-name-' * 12}/{index}/lib.rs"
            ): edition
            for index, edition in enumerate(["2024"] * 400 + ["2021"] * 10)
        }
        commands = native_format.format_commands(targets)
        self.assertGreater(len(commands), 2)
        observed = {}
        for command in commands:
            self.assertEqual(
                command[:6],
                ["rustup", "run", "1.95.0", "rustfmt", "--check", "--edition"],
            )
            self.assertLessEqual(
                native_format.command_units(command), native_format.MAX_COMMAND_UNITS
            )
            for argument in command[7:]:
                self.assertNotIn(Path(argument), observed)
                observed[Path(argument)] = command[6]
        self.assertEqual(observed, targets)

    def test_single_overlong_target_fails_instead_of_being_omitted(self):
        with self.assertRaisesRegex(ValueError, "exceeds command limit"):
            native_format.format_commands({Path("x" * 20_000): "2024"})

    def test_empty_target_inventory_fails(self):
        with patch.object(subprocess, "check_output", return_value='{"packages": []}'):
            with self.assertRaisesRegex(ValueError, "no formatting targets"):
                native_format.collect_targets(Path("Cargo.toml"))

    def test_format_failure_is_retained_and_later_batches_still_run(self):
        targets = {Path("one.rs"): "2021", Path("two.rs"): "2024"}
        with (
            patch.object(native_format, "collect_targets", return_value=targets),
            patch.object(
                subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess([], 1),
                    subprocess.CompletedProcess([], 0),
                ],
            ) as run,
        ):
            self.assertEqual(native_format.check_format(Path("Cargo.toml")), 1)
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
