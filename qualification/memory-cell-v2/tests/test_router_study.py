from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from v2.router_study import (
    DEFAULT_PROFILE,
    DESIGN,
    SPECS,
    build_routing_data,
    decision_metrics,
    requests_for,
    run_routing,
)


class RouterStudyTests(unittest.TestCase):
    def test_family_coverage_and_effective_holdout(self):
        training, held = build_routing_data(8001)
        classes = {s.route_id for s in SPECS} | {None}
        for family in set(training["families"]):
            self.assertEqual(
                {
                    label
                    for label, f in zip(training["labels"], training["families"])
                    if f == family
                },
                classes,
            )
        for declared in DESIGN["training_cues"]:
            for cue in declared["cues"]:
                present = {
                    family
                    for text, label, family in zip(
                        training["texts"], training["labels"], training["families"]
                    )
                    if label == declared["route"] and cue in text.casefold().split()
                }
                self.assertEqual(present, set(training["families"]))
        self.assertEqual(
            (len(training["texts"]), len(held)),
            (DESIGN["training_examples"], DESIGN["held_queries"]),
        )
        self.assertFalse(set(training["keys"]) & {e.key for e in held})
        self.assertTrue(
            all(request.cell_type is None for request in requests_for(held, "learned"))
        )
        changed = [replace(e, target="poison", declared_type="poison") for e in held]
        self.assertEqual(
            requests_for(held, "learned"), requests_for(changed, "learned")
        )
        self.assertEqual(
            requests_for(held, "literal"), requests_for(changed, "literal")
        )

    def test_oracle_gap_includes_missed_known_and_wrong_rejections(self):
        score = decision_metrics(
            ["semantic-cell", "episodic-cell", None, None],
            ["semantic-cell", None, "procedural-cell", None],
        )
        self.assertEqual(
            {
                name: score[name]
                for name in (
                    "decision_accuracy",
                    "coverage",
                    "conditional_accuracy",
                    "reject_recall",
                    "wrong_accepted",
                    "missed_known",
                    "oracle_gap",
                )
            },
            {
                "decision_accuracy": 0.5,
                "coverage": 0.5,
                "conditional_accuracy": 0.5,
                "reject_recall": 0.5,
                "wrong_accepted": 1,
                "missed_known": 1,
                "oracle_gap": 0.5,
            },
        )

    def test_formal_seed_mismatch_fails_before_creating_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol = {
                "routing_v2_profile": DEFAULT_PROFILE,
                "seeds": [211, 223, 227, 229, 233],
            }
            with self.assertRaises(ValueError):
                run_routing(protocol, root, "0" * 40, [8001])
            self.assertFalse((root / "routing").exists())

    def test_real_training_reload_and_raw_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_routing(
                {"routing_v2_profile": DEFAULT_PROFILE},
                root,
                "0" * 40,
                [8001],
                development=True,
            )
            run = result["runs"][0]
            seed_dir = root / "routing" / "seed-8001"
            self.assertEqual(
                (seed_dir / "predictions.jsonl").read_bytes(),
                (seed_dir / "predictions-before-reload.jsonl").read_bytes(),
            )
            self.assertTrue(run["reload_same_predictions"])
            self.assertGreater(run["storage"]["learned"]["parameter_bytes"], 0)
            self.assertEqual(
                (
                    run["storage"]["typed"]["parameter_bytes"],
                    run["storage"]["literal"]["parameter_bytes"],
                ),
                (0, 0),
            )
            self.assertEqual(run["training_receipt"]["optimizer_steps"], 600)
            rows = [
                json.loads(line)
                for line in (seed_dir / "predictions.jsonl").read_text().splitlines()
            ]
            self.assertTrue(
                all(row["requests"]["learned"]["cell_type"] is None for row in rows)
            )
            self.assertTrue(
                all(
                    set(row["requests"]["learned"]) == {"text", "scope", "cell_type"}
                    for row in rows
                )
            )
            for mode in ("typed", "literal", "learned"):
                expected = decision_metrics(
                    [row["target"] for row in rows],
                    [row["decisions"][mode]["route_id"] for row in rows],
                )
                self.assertEqual(run["metrics"][mode]["all"], expected)
            with self.assertRaises(FileExistsError):
                run_routing(
                    {"routing_v2_profile": DEFAULT_PROFILE},
                    root,
                    "0" * 40,
                    [8001],
                    development=True,
                )


if __name__ == "__main__":
    unittest.main()
