"""Fresh execution guards share the original consumer's serialization lock."""

from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import paired_consumer as owner


class FreshConsumerTests(unittest.TestCase):
    def test_existing_and_racing_owner_results_are_not_new_executions(self):
        release = {"request_sha256": "c" * 64, "candidate_sha256": "d" * 64}
        original_lock = owner.locked
        with tempfile.TemporaryDirectory() as temp:
            for command, marker in (
                ("select", "selection"),
                ("run", "STARTED.json"),
                ("report", "OUTCOME.json"),
            ):
                with self.subTest(command=command):
                    home = Path(temp) / command
                    admission, task, selection = "e" * 64, "a" * 64, "b" * 64
                    (home / admission).mkdir(parents=True)
                    args = SimpleNamespace(
                        home=home,
                        admission=admission,
                        materials=Path(temp),
                        cmd=command,
                        task=task,
                    )

                    @contextmanager
                    def original_writer_won(folder):
                        with original_lock(folder):
                            if command == "select":
                                (folder / marker).mkdir()
                            else:
                                scope = owner.request_scope(
                                    admission, release, task, selection
                                )
                                target = folder / scope["operation"]
                                target.mkdir()
                                (target / marker).write_text("{}")
                            yield

                    with (
                        patch.object(
                            owner,
                            "context",
                            return_value=({}, {"release": release}, {}),
                        ),
                        patch.object(owner, "locked", original_writer_won),
                        patch.object(
                            owner.cold, "selection", return_value=selection
                        ) as cold,
                        patch.object(owner, "native") as authorize,
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "historical cold|original run|original outcome"
                        ):
                            owner.operate(args, require_new=True)
                    authorize.assert_not_called()
                    if command == "select":
                        cold.assert_not_called()


if __name__ == "__main__":
    unittest.main()
