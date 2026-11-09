"""Contract/learning control tests, never independent repository task results."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .contracts import LIMIT, digest, load, read_bound, validate_task, write_new
from .memory import initial_state, retrieve, update, validate_state


def corpus():
    return {
        "schema": "hepta.repo-mdv.corpus.v1",
        "documents": [
            {
                "id": "clippy",
                "text": "compiler immutable borrow clippy repair",
                "exposure": "development",
                "source": {"sha256": "a" * 64, "reference": "unit-control-only"},
            },
            {
                "id": "database",
                "text": "database migration restore sql",
                "exposure": "development",
                "source": {"sha256": "b" * 64, "reference": "unit-control-only"},
            },
        ],
    }


class MemoryControls(unittest.TestCase):
    def test_actual_update_is_consumed_after_serialization(self):
        bank, query = corpus(), "compiler repair"
        before = initial_state(bank)
        feedback = {
            "split": "development",
            "terminal": "proved",
            "selected_document": "clippy",
            "query_sha256": digest(query),
            "mandatory_checks": [
                {"returncode": 0, "cleanup_complete": True, "error": None}
            ],
        }
        after = update(bank, before, query, "clippy", feedback)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "state.json"
            write_new(p, after)
            replay = retrieve(bank, "immutable compiler", load(p))
        self.assertEqual(before, initial_state(bank))
        self.assertEqual(after["parent_sha256"], digest(before))
        self.assertEqual(after["updates"], 1)
        self.assertGreater(
            next(x for x in replay if x["document_id"] == "clippy")[
                "learned_association"
            ],
            0,
        )

    def test_unverified_success_cannot_train(self):
        bank = corpus()
        for terminal, code, complete, error in [
            ("unknown", 0, True, None),
            ("proved", 1, True, None),
            ("proved", 0, False, None),
            ("proved", 0, True, {"type": "Timeout"}),
        ]:
            with self.subTest(
                terminal=terminal, code=code, complete=complete, error=error
            ):
                feedback = {
                    "split": "development",
                    "terminal": terminal,
                    "selected_document": "clippy",
                    "query_sha256": digest("compiler"),
                    "mandatory_checks": [
                        {
                            "returncode": code,
                            "cleanup_complete": complete,
                            "error": error,
                        }
                    ],
                }
                with self.assertRaises(ValueError):
                    update(bank, initial_state(bank), "compiler", "clippy", feedback)

    def test_same_material_available_to_baseline(self):
        bank = corpus()
        self.assertEqual(
            retrieve(bank, "compiler"), retrieve(bank, "compiler", initial_state(bank))
        )

    def test_changed_bank_or_nonfinite_state_rejected(self):
        bank, state = corpus(), initial_state(corpus())
        changed = copy.deepcopy(bank)
        changed["documents"][0]["text"] += " changed"
        with self.assertRaises(ValueError):
            validate_state(state, changed)
        state["weights"][0][0] = float("nan")
        with self.assertRaises(ValueError):
            validate_state(state, bank)

    def test_confirmation_cannot_be_enabled_by_caller_claim(self):
        with self.assertRaisesRegex(ValueError, "HOLD"):
            validate_task(
                {
                    "schema": "hepta.repo-mdv.dev-task.v1",
                    "split": "confirmation",
                    "custody": "approved",
                },
                corpus(),
            )

    def test_oversize_input_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversize.json"
            with path.open("wb") as stream:
                stream.truncate(LIMIT + 1)
            original = __import__("os").fdopen
            opened = []

            class Observe:
                def __init__(self, stream):
                    self.stream = stream
                    self.read_calls = 0

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.stream.close()

                def fileno(self):
                    return self.stream.fileno()

                def read(self, *args):
                    self.read_calls += 1
                    return self.stream.read(*args)

            def observe(*args, **kwargs):
                wrapper = Observe(original(*args, **kwargs))
                opened.append(wrapper)
                return wrapper

            with patch("cell_repo_mdv.contracts.os.fdopen", observe):
                with self.assertRaisesRegex(ValueError, "oversize"):
                    read_bound(path)
            self.assertEqual([x.read_calls for x in opened], [0])

    def test_duplicate_keys_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load(path)
            link = Path(tmp) / "link.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlink"):
                load(link)


if __name__ == "__main__":
    unittest.main()
