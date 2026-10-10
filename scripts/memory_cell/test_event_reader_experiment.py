"""Execution-order and census tests with an explicit non-pretrained reader."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import event_reader_experiment as experiment
from event_memory_trial import ARMS
from event_projection import EventProjection
from native import Question, digest
from test_event_projection import doc


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class ReaderExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        self.plan_dir = self.root / "plan"
        self.model = self.root / "model"
        for path in (self.inputs, self.plan_dir, self.model):
            path.mkdir()
        docs, cases, labels = [], [], []
        for index in range(8):
            name = f"q{index}"
            source = replace(doc(f"event{index}", value=f"site_{index:08x}"), scope=name)
            query = Question(name, name, name, "Where?", "2026-01-02T00:00:00Z")
            projection = EventProjection((source,))
            docs.append(asdict(source))
            cases.append(
                dict(
                    query=asdict(query), kind="new_fact",
                    candidate_ids=[source.identity],
                    candidate_digest=digest((source.identity,)),
                    frontier=projection.frontier,
                    controls={
                        arm: dict(selected=[] if arm == "empty" else [source.identity])
                        for arm in ARMS
                    },
                )
            )
            labels.append(
                dict(
                    id=name, expected=f"site_{index:08x}",
                    support=[source.identity], kind="new_fact",
                )
            )
        write(self.inputs / "labels.json", labels)
        write(self.plan_dir / "source-view.json", docs)
        self.plan = dict(
            schema="hepta.event-organization.plan.v1", arms=ARMS, token_limit=2048,
            cases=cases, labels_sha=pin(self.inputs / "labels.json"),
            source_view_sha=pin(self.plan_dir / "source-view.json"),
            extraction={}, frozen=dict(costs={}),
        )
        write(self.plan_dir / "plan.json", self.plan)
        write(self.model / "inventory.json", dict(inventory_digest="fixture-reader"))
        write(
            self.model / "stage.json",
            dict(inventory_sha256=pin(self.model / "inventory.json")),
        )

    def execute(self, fail_at=None):
        calls = []
        raw_read = experiment.read
        root = self.root

        class FixtureReader:
            def __init__(self, *args, **kwargs):
                pass

            def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
                bundle.validate(query, originals, frontier=frontier, revoked=revoked)
                calls.append((query.identity, bundle.mode, bundle.delivered()))
                if len(calls) == fail_at:
                    raise ValueError("explicit injected test failure")
                answer = "site_ffffffff [E1]" if bundle.selected else "I do not know."
                return answer, dict(
                    reader_identity="fixture-reader", reader_profile="fixture-view",
                    token_limit=token_limit, input_ids_digest=digest(asdict(query)),
                    input_tokens=80, generated_tokens=8, seconds=0.01,
                    delivered_evidence=bundle.delivered(),
                )

            def verify_frozen(self):
                if len(calls) != 48:
                    raise ValueError("lost actual attempt")

        def checked_read(path, expected):
            if path.name == "labels.json":
                raw = (root / "out/raw-answers.jsonl").read_text().splitlines()
                self.assertEqual(len(raw), 48)
                self.assertTrue(all("strict_task_success" not in line for line in raw))
            return raw_read(path, expected)

        with (
            patch.object(experiment, "EventPresentationReader", FixtureReader),
            patch.object(experiment, "read", side_effect=checked_read),
            patch.dict("os.environ", {"HEPTA_MEMORY_TESTED_COMMIT": "a" * 40}),
        ):
            result = experiment.run(
                self.plan_dir, self.inputs, self.model, self.root / "out",
                plan_sha=pin(self.plan_dir / "plan.json"),
                stage_sha=pin(self.model / "stage.json"),
            )
        return result, calls

    def test_all_raw_answers_precede_labels_and_empty_still_calls_reader(self):
        result, calls = self.execute()
        self.assertEqual(len(calls), 48)
        self.assertEqual(sum(not evidence for _, _, evidence in calls), 8)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["parametric_optimizer_executed"])
        self.assertIsNone(result["total_lifecycle_cost"])

    def test_failed_call_is_retained_and_cannot_make_a_smaller_success_census(self):
        with self.assertRaises(ValueError):
            self.execute(fail_at=2)
        raw = [
            json.loads(line)
            for line in (self.root / "out/raw-answers.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(raw), 48)
        self.assertEqual(sum(row["status"] == "failed" for row in raw), 1)
        self.assertTrue((self.root / "out/report.json").exists())

    def test_missing_duplicate_and_drifted_plan_reject_before_model_loading(self):
        for mutate in (
            lambda p: p["cases"].pop(),
            lambda p: p["cases"].__setitem__(0, p["cases"][1]),
            lambda p: p["cases"][0].update(candidate_digest="changed"),
        ):
            plan = deepcopy(self.plan)
            mutate(plan)
            write(self.plan_dir / "plan.json", plan)
            with self.assertRaises(ValueError):
                experiment.preflight(
                    self.plan_dir, self.inputs, pin(self.plan_dir / "plan.json")
                )
        self.assertFalse((self.root / "out").exists())

    def test_label_byte_change_is_not_allowed_before_generation(self):
        (self.inputs / "labels.json").write_text("[]")
        with self.assertRaises(ValueError):
            experiment.preflight(self.plan_dir, self.inputs, pin(self.plan_dir / "plan.json"))


if __name__ == "__main__":
    unittest.main()
