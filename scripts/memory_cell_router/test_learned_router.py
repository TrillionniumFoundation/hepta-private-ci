"""Behavioral checks for utility-fitted routing and immutable artifact replay."""

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from learned_router import MAGIC, fit_router, load_router
from router_features import verify_question_splits


SOURCE = hashlib.sha256(
    b"independently retained source utility observations"
).hexdigest()
EXPERTS = ["cell-a", "cell-b", "cell-c"]


def source_observations():
    templates = [
        ("Which color is assigned to {name}?", "Recall the color for {name}."),
        ("Where was {name} on day 7?", "Recall {name}'s location at time 7."),
        (
            "What step follows prepare in task {name}?",
            "Return the next action in workflow {name}.",
        ),
    ]
    rows = []
    for name in ("Ada", "Basil", "Cora", "Devon", "Enid", "Faron"):
        for slot, wordings in enumerate(templates):
            for template in wordings:
                rows.append(
                    {
                        "question": template.format(name=name),
                        "utilities": [float(index == slot) for index in range(3)],
                        "reject": False,
                    }
                )
        for template in (
            "Forecast the weather for {name} tomorrow.",
            "What weather is expected in {name}?",
        ):
            rows.append(
                {
                    "question": template.format(name=name),
                    "utilities": [0.0, 0.0, 0.0],
                    "reject": True,
                }
            )
    return rows


class LearnedRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observations = source_observations()
        cls.router = fit_router(
            cls.observations, expert_ids=EXPERTS, source_sha256=SOURCE
        )

    def test_learns_heldout_entities_wordings_and_rejection(self):
        final = []
        expected = []
        for name in ("Zoe", "Yuki", "Oslo"):
            final.extend(
                [
                    f"State the stored color for {name}.",
                    f"Retrieve {name}'s location for day 7.",
                    f"Provide the next step of workflow {name}.",
                    f"Provide the weather forecast for {name}.",
                ]
            )
            expected.extend([0, 1, 2, None])
        self.assertEqual(
            verify_question_splits(
                {
                    "training": [row["question"] for row in self.observations],
                    "final": final,
                }
            ),
            {"training": 48, "final": 12},
        )
        actual = [
            self.router.predict({"question": question})["slot"] for question in final
        ]
        self.assertEqual(actual, expected)
        self.assertLess(self.router.training["last_preupdate_cross_entropy"], 0.1)
        self.assertLess(
            self.router.training["last_preupdate_cross_entropy"],
            self.router.training["first_cross_entropy"],
        )

    def test_utility_permutation_changes_route_without_relation_dispatch(self):
        swapped = [
            dict(
                row,
                utilities=[
                    row["utilities"][1],
                    row["utilities"][2],
                    row["utilities"][0],
                ],
            )
            for row in self.observations
        ]
        router = fit_router(swapped, expert_ids=EXPERTS, source_sha256=SOURCE)
        questions = [
            "State the stored color for Zoe.",
            "Retrieve Zoe's location for day 7.",
            "Provide the next step of workflow Zoe.",
        ]
        self.assertEqual(
            [router.predict({"question": q})["slot"] for q in questions], [2, 0, 1]
        )

    def test_closed_inference_schema_rejects_privileged_input(self):
        for field in (
            "answer",
            "gold",
            "relation",
            "expert_id",
            "source_digest",
            "utilities",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.router.predict({"question": "What color is Zoe?", field: "leak"})
        for request in (
            "What color is Zoe?",
            {"question": ""},
            {"question": 3},
            {"question": "a" * 4097},
        ):
            with self.subTest(request=str(request)[:50]), self.assertRaises(ValueError):
                self.router.predict(request)

    def test_reload_exactly_preserves_predictions_and_measured_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "router.bin"
            receipt = self.router.save(path)
            loaded = load_router(path, expected_sha256=receipt["sha256"])
            for question in (
                "Recall the color for Zoe.",
                "Provide the weather forecast for Yuki.",
            ):
                self.assertEqual(
                    loaded.predict({"question": question}),
                    self.router.predict({"question": question}),
                )
            self.assertEqual(receipt["artifact_bytes"], path.stat().st_size)
            self.assertEqual(
                receipt["private_parameter_bytes"], self.router.weights.nbytes
            )
            self.assertEqual(
                receipt["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
            self.assertEqual(loaded.training, self.router.training)
            self.assertEqual(loaded.source_sha256, SOURCE)
            with self.assertRaises(FileExistsError):
                self.router.save(path)
            payload = bytearray(path.read_bytes())
            payload[-1] ^= 1
            path.write_bytes(payload)
            with self.assertRaises(ValueError):
                load_router(path, expected_sha256=receipt["sha256"])

    def test_invalid_source_utilities_and_nonfinite_state_are_rejected(self):
        invalid = (
            [1, 0],
            [1, float("nan"), 0],
            [1, float("inf"), 0],
            [2, 0, 0],
            [True, 0, 0],
        )
        for utilities in invalid:
            with self.subTest(utilities=utilities), self.assertRaises(ValueError):
                fit_router(
                    [
                        {
                            "question": "Recall color for Zoe.",
                            "utilities": utilities,
                            "reject": False,
                        }
                    ],
                    expert_ids=EXPERTS,
                    source_sha256=SOURCE,
                )
        for config in (
            {"dimension": True},
            {"min_confidence": 0.5},
            {"learning_rate": float("nan")},
            {"gold_answers": []},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                fit_router(
                    self.observations,
                    expert_ids=EXPERTS,
                    source_sha256=SOURCE,
                    config=config,
                )
        bad = dict(self.observations[0], answer="hidden gold")
        with self.assertRaises(ValueError):
            fit_router([bad], expert_ids=EXPERTS, source_sha256=SOURCE)
        with self.assertRaises(ValueError):
            fit_router(
                self.observations,
                expert_ids=["same", "same", "other"],
                source_sha256=SOURCE,
            )
        with self.assertRaises(ValueError):
            fit_router(self.observations, expert_ids=EXPERTS, source_sha256="unbound")
        self.assertFalse(self.router.weights.flags.writeable)
        self.assertTrue(np.isfinite(self.router.weights).all())

    def test_equal_utility_has_no_manufactured_expert_discrimination(self):
        tied = [
            {"question": row["question"], "utilities": [1.0, 1.0, 1.0], "reject": False}
            for row in self.observations
        ]
        router = fit_router(tied, expert_ids=EXPERTS, source_sha256=SOURCE)
        self.assertEqual(router.training["informative_expert_examples"], 0)
        self.assertEqual(router.training["tied_expert_examples"], len(tied))
        decision = router.predict({"question": "State the stored color for Zoe."})
        self.assertEqual(decision["status"], "routed")
        self.assertTrue(decision["ambiguous_experts"])
        self.assertLess(decision["expert_margin"], 0.05)
        self.assertGreater(decision["support_confidence"], 0.9)

    def test_positive_support_tie_routes_without_expertise_claim(self):
        common = [
            {
                "question": f"Recall the color for entity E{index:02d}.",
                "utilities": [1.0, 1.0],
                "reject": False,
            }
            for index in range(16)
        ]
        negatives = [
            {
                "question": f"Forecast the weather for entity E{index:02d}.",
                "utilities": [0.0, 0.0],
                "reject": True,
            }
            for index in range(16)
        ]
        router = fit_router(
            common + negatives, expert_ids=EXPERTS[:2], source_sha256=SOURCE
        )
        decision = router.predict({"question": "Recall the color assigned to Zoe."})
        self.assertEqual(decision["status"], "routed")
        self.assertIn(decision["slot"], (0, 1))
        self.assertGreater(decision["support_confidence"], 0.9)
        self.assertLess(decision["expert_confidence"], 0.55)
        self.assertTrue(decision["ambiguous_experts"])
        self.assertGreaterEqual(decision["margin"], 0.05)
        self.assertEqual(router.training["informative_expert_examples"], 0)
        self.assertEqual(
            decision, router.predict({"question": "Recall the color assigned to Zoe."})
        )
        self.assertIsNone(
            router.predict({"question": "Forecast the weather for Zoe."})["slot"]
        )

    def test_structurally_invalid_pinned_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "router.bin"
            self.router.save(path)
            original = path.read_bytes()
            start = len(MAGIC) + 4
            length = struct.unpack("<I", original[len(MAGIC) : start])[0]
            header = json.loads(original[start : start + length])
            weights = bytearray(original[start + length :])
            weights[:4] = struct.pack("<f", float("inf"))
            header["weight_sha256"] = hashlib.sha256(weights).hexdigest()
            metadata = json.dumps(
                header, sort_keys=True, separators=(",", ":")
            ).encode()
            invalid = MAGIC + struct.pack("<I", len(metadata)) + metadata + weights
            path.write_bytes(invalid)
            with self.assertRaises(ValueError):
                load_router(path, expected_sha256=hashlib.sha256(invalid).hexdigest())
            with self.assertRaises(ValueError):
                load_router(
                    Path(directory),
                    expected_sha256=hashlib.sha256(original).hexdigest(),
                )

    def test_split_overlap_and_duplicate_source_questions_are_rejected(self):
        with self.assertRaises(ValueError):
            verify_question_splits(
                {
                    "training": ["  What COLOR for Zoe? "],
                    "final": ["what color for zoe?"],
                }
            )
        with self.assertRaises(ValueError):
            fit_router(
                self.observations + [self.observations[0]],
                expert_ids=EXPERTS,
                source_sha256=SOURCE,
            )
        again = fit_router(self.observations, expert_ids=EXPERTS, source_sha256=SOURCE)
        self.assertTrue(np.array_equal(again.weights, self.router.weights))
        self.assertEqual(again.training, self.router.training)


if __name__ == "__main__":
    unittest.main()
