"""Stream/queue/scoring integration without any model training or generation."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory_cell_service"))
from source_store import SourceStore
from training_queue import TrainingQueue

from evolution_common import digest, read_json
from longitudinal_campaign import campaign, load_stream
from longitudinal_protocol import protocol
from longitudinal_runtime import apply_events, background_job
from longitudinal_scoring import quality_gates, questions, score_round


class LongitudinalTests(unittest.TestCase):
    def test_all_registered_streams_have_real_queued_background_jobs(self):
        for seed, plan in campaign()["streams"].items():
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as root:
                store = SourceStore(
                    Path(root) / "sources.sqlite", plan["scope"], plan["cell_id"]
                )
                queue = TrainingQueue(store)
                actual, bg = [], 0
                for index, item in enumerate(plan["rounds"]):
                    before = apply_events(store, item["before_background"])
                    claimed = (
                        queue.claim("background", lease_seconds=100, now=1000)
                        if item["background_steps"]
                        else None
                    )
                    if item["background_steps"]:
                        self.assertIsNotNone(claimed)
                        self.assertEqual(background_job(before), claimed.job_id)
                        before_epoch = store.snapshot()["epoch"]
                        bg += 1
                    actual_events = apply_events(store, item["events"])
                    if item["label"] == "conflict":
                        self.assertEqual(
                            actual_events[0]["immediate_overlay"]["status"], "conflict"
                        )
                    if item["label"] == "resolve":
                        self.assertEqual(actual_events[0]["event"]["entity"], "long_04")
                        self.assertEqual(
                            actual_events[0]["immediate_overlay"]["status"], "answered"
                        )
                    current = store.snapshot()
                    actual.append(len(current["facts"]))
                    if claimed:
                        self.assertGreater(current["epoch"], before_epoch)
                        queue.fail(
                            claimed,
                            "simulated superseded completion, no model",
                            now=1001,
                        )
                        self.assertEqual(
                            queue.status(claimed.job_id)["state"], "superseded"
                        )
                    publication = queue.claim("clean", lease_seconds=100, now=1001)
                    self.assertIsNotNone(publication)
                    self.assertEqual(publication.snapshot, current)
                    with store.transaction() as db:
                        db.execute(
                            "UPDATE jobs SET state='completed' WHERE id=?",
                            (publication.job_id,),
                        )
                    self.assertIsNone(
                        queue.claim("no-work", lease_seconds=100, now=1002)
                    )
                self.assertEqual((actual, bg), (plan["expected_live_fact_counts"], 3))
                self.assertEqual(
                    sum(actual) * 2
                    + sum(actual[i] * 4 for i in plan["control_rounds"]),
                    186,
                )

    def test_one_wrong_wording_fails_source_unit_not_half_a_source(self):
        facts = [
            dict(entity="a", relation="color", value="blue", source_digest="a" * 64),
            dict(entity="b", relation="color", value="red", source_digest="b" * 64),
        ]
        snapshot = dict(facts=facts)
        plan = protocol()
        query = questions(snapshot, plan["read_templates"])
        journal = dict(
            rows=[
                dict(question=q, text=v, answer_postprocessed=False)
                for q, v in zip(query, ["blue", "wrong", "red", "red"])
            ],
            fact_input=False,
            retrieval_input=False,
            answer_lexicon_input=False,
        )
        score = score_round(
            snapshot,
            snapshot,
            [dict(kind="correct", entity="a", relation="color")],
            journal,
            plan["read_templates"],
        )
        self.assertEqual(score["raw_queries"], dict(correct=3, total=4))
        self.assertEqual(
            score["source_both_wordings"], dict(correct=1, total=2, accuracy=0.5)
        )
        self.assertEqual(
            quality_gates([score], plan),
            dict(
                every_round_parameter_accuracy=False,
                every_measured_retention_panel=False,
                every_corrected_source_exact=False,
            ),
        )
        journal["fact_input"] = True
        with self.assertRaisesRegex(ValueError, "source/retrieval"):
            score_round(snapshot, snapshot, [], journal, plan["read_templates"])

    def test_registered_campaign_rejects_unregistered_seed_or_modification(self):
        file = Path(__file__).with_name("longitudinal-campaign-002.json")
        frozen = read_json(file)
        self.assertEqual(
            load_stream(file, digest(frozen), 24023), frozen["streams"]["24023"]
        )
        with self.assertRaisesRegex(ValueError, "seed"):
            load_stream(file, digest(frozen), 7)
        with self.assertRaisesRegex(ValueError, "digest"):
            load_stream(file, "0" * 64, 24019)


if __name__ == "__main__":
    unittest.main()
