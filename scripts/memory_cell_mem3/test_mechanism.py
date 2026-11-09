"""Custom unit fixtures; no registered MEM-3 campaign is executed here."""

from collections import Counter
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from actor import Reader, compose
from evaluate import evaluate
from fixture import expected_answer, gate, metadata


def stage():
    return {
        "generation": 1,
        "phase": "base",
        "tick": 0,
        "facts": [
            {
                "source": f"{r}:{n}",
                "node": n,
                "relation": r,
                "value": (1 - n) if r == "A" else n,
                "version": 1,
                "live": True,
                "expires": 10,
                "dependencies": [],
            }
            for r in "AB"
            for n in range(2)
        ],
    }


def task():
    return {
        "task_id": "unit",
        "family": "unit",
        "start": 0,
        "program": ["A", "B"],
        "budget": 3,
    }


class WrongReader:
    def read(self, source):
        return {"value": 0, "version": 1}


class MechanismTests(unittest.TestCase):
    def test_strong_retrievers_compose_current_evidence(self):
        current = stage()
        with tempfile.TemporaryDirectory() as temporary:
            for arm in ("exact", "bm25"):
                reader = Reader(arm, current, {}, 99, None, Path(temporary))
                actual = compose(reader, metadata(current["facts"]), task(), 0)
                self.assertEqual(
                    actual["value"], expected_answer(current["facts"], task(), 0)
                )
                self.assertEqual([r["source"] for r in actual["steps"]], ["A:0", "B:1"])

    def test_gate_does_not_correct_wrong_prediction_or_replace_its_path(self):
        current = stage()
        actual = compose(WrongReader(), metadata(current["facts"]), task(), 0)
        self.assertEqual([r["source"] for r in actual["steps"]], ["A:0", "B:0"])
        result = evaluate(current, [task()], [actual])["counts"]
        self.assertEqual(
            (
                result["joint_correct"],
                result["raw_errors"],
                result["invalid_used_sources"],
            ),
            (0, 1, 0),
        )

    def test_safe_sources_do_not_hide_invalid_terminal_assertion(self):
        current = stage()
        current["facts"][-1]["live"] = False
        actual = compose(WrongReader(), metadata(current["facts"]), task(), 0)
        score = evaluate(current, [task()], [actual])["counts"]
        self.assertEqual(
            (
                score["invalid_terminal_assertions"],
                score["invalid_used_sources"],
                score["answerable"],
            ),
            (1, 0, 0),
        )

    def test_gate_tracks_versions_dependencies_expiry_and_has_no_values(self):
        current = stage()
        current["facts"][0]["version"] = 2
        current["facts"][2]["dependencies"] = [["A:0", 1]]
        meta = metadata(current["facts"])
        changed = copy.deepcopy(current["facts"])
        changed[0]["value"] = 7
        self.assertEqual(metadata(changed), meta)
        self.assertEqual(
            [
                gate(meta, "A:0", 1, 0),
                gate(meta, "B:0", 1, 0),
                gate(meta, "A:1", 1, 11),
                gate(meta, "C:0", 1, 0),
            ],
            ["version", "dependency", "expired", "unknown"],
        )

    def test_native_read_path_never_uses_retrieved_values(self):
        class ForbiddenFacts:
            def __getitem__(self, key):
                raise AssertionError("native read accessed retrieval answers")

        class NumericDouble:
            def predict(self, key):
                return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        reader = object.__new__(Reader)
        reader.arm, reader.memory, reader.cost = "native", NumericDouble(), Counter()
        reader.features, reader.versions, reader.facts = (
            {"A:0": [1.0]},
            {"A:0": 1},
            ForbiddenFacts(),
        )
        self.assertEqual(reader.read("A:0"), {"value": 1, "version": 1})

    def test_terminal_success_cannot_be_forged_over_wrong_raw_path(self):
        current = stage()
        actual = compose(WrongReader(), metadata(current["facts"]), task(), 0)
        actual["value"] = 1
        with self.assertRaises(ValueError):
            evaluate(current, [task()], [actual])

    def test_failed_training_or_later_task_preserves_cost_and_full_roster(self):
        spec = importlib.util.spec_from_file_location(
            "mem3_cli_test", Path(__file__).with_name("run.py")
        )
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        queries = [{**task(), "task_id": str(i), "program": ["A"]} for i in range(2)]
        data = {
            "tasks": queries,
            "streams": [{"seed": 99, "features": {}, "stages": [stage()]}],
        }
        for fail_constructor in (True, False):

            class FailingReader:
                def __init__(self, *args):
                    self.cost, self.reads = (
                        {"native_updates": 3, "native_request_bytes": 42},
                        0,
                    )
                    if fail_constructor:
                        raise RuntimeError("injected fourth-update failure")

                def read(self, source):
                    self.reads += 1
                    if self.reads == 2:
                        raise RuntimeError("injected second-task failure")
                    return {"value": 1, "version": 1}

                def close(self):
                    pass

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "fixture.json").write_text(json.dumps(data))
                (root / "binary").write_bytes(b"not-executed-unit-double")
                (root / "prior").write_bytes(b"unit-evidence")
                argv = [
                    "mem3",
                    "--fixture",
                    str(root / "fixture.json"),
                    "--native",
                    str(root / "binary"),
                    "--first-experiment-evidence",
                    str(root / "prior"),
                    "--output",
                    str(root / "out"),
                ]
                with (
                    patch("sys.argv", argv),
                    patch.multiple(
                        cli,
                        Reader=FailingReader,
                        SEEDS=(99,),
                        PHASES=("base",),
                        ARMS=("native",),
                        fixture=lambda: data,
                    ),
                ):
                    with self.assertRaises(SystemExit):
                        cli.main()
                folder = root / "out/seed-99-base-native"
                failure = json.loads((folder / "failure.json").read_text())
                self.assertEqual(
                    failure["partial_cost"],
                    {"native_updates": 3, "native_request_bytes": 42},
                )
                self.assertEqual(failure["planned_task_count"], 2)
                self.assertEqual(
                    failure["completed_task_ids"], [] if fail_constructor else ["0"]
                )
                self.assertEqual(
                    failure["missing_task_ids"],
                    ["0", "1"] if fail_constructor else ["1"],
                )
                self.assertEqual(
                    len(json.loads((folder / "task-roster.json").read_text())), 2
                )


if __name__ == "__main__":
    unittest.main()
