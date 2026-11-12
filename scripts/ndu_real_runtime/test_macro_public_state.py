"""Manufactured public-category regressions, not policy efficacy evidence."""

from copy import deepcopy
import unittest

from .macro_policy import fit, load, source_sha256
from .macro_public_state import project
from .metacontrol_macro_contract import digest
from .test_macro_policy import CONTEXT, pair


def metadata(category):
    return [float(index == category) for index in range(4)] + [0.0] * 12


def categorized_pair(source, decision, feature, category, gain):
    row = pair(source, decision, feature)
    row["state"] = project(
        [feature], metadata(category), 10.0, ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
    )
    for macro, branch in row["branches"].items():
        branch["public_state_sha256"] = digest(row["state"])
        branch["initial_public_state_sha256"] = digest(["fixture", decision])
        branch["quality"] = 0.5 + (gain if macro == "READ" else 0.0)
    return row


class MacroPublicStateTests(unittest.TestCase):
    def test_actor_and_converter_use_the_same_original_public_projection(self):
        from .macro_training_pairs import _project
        from .test_macro_actor import fixture_deployment, load_fixture, state

        adapter = load_fixture(fixture_deployment("STOP"))
        legal = ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
        _, detail = adapter.next([0.5], state(), legal, public_metadata=metadata(1))
        step = {
            "public_features": [0.5],
            "public_metadata": metadata(1),
            "remaining_seconds": 10.0,
            "legal_actions": legal,
            "candidate_features": [[0.5]],
            "candidate_metadata": [],
            "memory_sha256": "a" * 64,
            "weights_sha256": "a" * 64,
            "controller": detail,
        }
        self.assertEqual(_project(step, 10.0)[0], detail["macro_public_state"])
        step["public_metadata"] = metadata(3)
        with self.assertRaisesRegex(ValueError, "public state differs"):
            _project(step, 10.0)
        del step["public_metadata"]
        with self.assertRaises(KeyError):
            _project(step, 10.0)
        with self.assertRaises(TypeError):
            load_fixture(fixture_deployment("STOP")).next([0.5], state(), legal)
        with self.assertRaises(ValueError):
            load_fixture(fixture_deployment("STOP")).next(
                [0.5], state(), legal, public_metadata=None
            )

    def test_public_task_category_changes_cell_without_changing_encoded_content(self):
        features = [0.25, 0.75]
        legal = ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
        original = deepcopy(features)
        date = project(features, metadata(1), 10.0, legal)
        total = project(features, metadata(3), 10.0, legal)
        self.assertEqual(date["features"], total["features"])
        self.assertNotEqual(date["context_belief"], total["context_belief"])
        self.assertEqual(features, original)
        self.assertEqual(
            project(features, metadata(1), 10.0, ["STOP", "WRITE_TEXT"])[
                "legal_macros"
            ],
            ["STOP"],
        )
        with self.assertRaises(ValueError):
            project(features, metadata(1), 10.0, ["STOP", "PREPARE_ROI"])

    def test_missing_ambiguous_or_nonfinite_public_goal_is_refused(self):
        bad = [
            None,
            [],
            [0.0] * 16,
            [1.0, 1.0, 0.0, 0.0] + [0.0] * 12,
            [0.5, 0.5, 0.0, 0.0] + [0.0] * 12,
            [True, 0.0, 0.0, 0.0] + [0.0] * 12,
            metadata(0) + [1.0],
            metadata(0)[:-1] + [float("nan")],
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                project([0.5], value, 10.0, ["STOP", "WRITE_TEXT", "PREPARE_ROI"])

    def test_conditional_cells_can_make_different_actions_after_cold_load(self):
        train = [
            categorized_pair(source, source + str(feature), feature, category, 0.1)
            for source, category in (("a", 1), ("b", 3))
            for feature in (0.0, 1.0)
        ]
        calibration = [
            categorized_pair(
                f"cal{category}-{index}", f"c{category}-{index}", 0.5, category, gain
            )
            for category, gain in ((1, 0.4), (3, -0.4))
            for index in range(9)
        ]
        model = fit(
            train, calibration, context=CONTEXT, expected_source_sha256=source_sha256()
        )
        model = load(model.to_bytes(), model.sha256, context=CONTEXT)
        self.assertTrue(model.data["calibration"]["complete"])
        self.assertEqual(len(model.data["calibration"]["conditional"]), 2)
        outcomes = {}
        for category in (1, 3):
            public = project(
                [0.5], metadata(category), 10.0, ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
            )
            for policy in ("unconditional", "conditional"):
                outcomes[category, policy] = model.choose(
                    public,
                    policy,
                    context=CONTEXT,
                    read_seconds_bound=2.0,
                    finalizer_seconds_reserve=1.0,
                )[0]
        self.assertEqual(
            outcomes,
            {
                (1, "unconditional"): "STOP",
                (3, "unconditional"): "STOP",
                (1, "conditional"): "READ",
                (3, "conditional"): "STOP",
            },
        )


if __name__ == "__main__":
    unittest.main()
