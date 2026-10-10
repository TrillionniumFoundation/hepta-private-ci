"""Protocol integration tests without claiming pretrained model performance."""

import copy
import tempfile
import unittest
from pathlib import Path

from composition_evidence import make_case
from composition_trial import capability_plan, transfer
from composition_policy import PROFILE, INITIAL
from native import digest
from test_composition_evidence import row


class Reader:
    identity = "a" * 64

    def verify_frozen(self):
        pass

    def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
        bundle.validate(query, originals, frontier=frontier, revoked=revoked)
        return "fixture answer [E1]", dict(reader_identity=self.identity,
            bundle_digest=bundle.seal(), delivered_evidence=bundle.delivered(),
            input_ids_digest=digest((query.content, bundle.delivered())), generated_tokens=4)


class CompositionTrialTests(unittest.TestCase):
    def test_ordinary_conditions_do_not_mutate_or_read_publisher_answers(self):
        case, _ = make_case(row(), ["Unrelated fact."], "2026-01-01T00:00:00Z", "capability")
        plan = dict(cases=[case])
        before = copy.deepcopy(plan)
        result = capability_plan(plan)
        self.assertEqual(plan, before)
        self.assertEqual(set(result["cases"][0]["conditions"]) - set(case["conditions"]),
                         {"retrieved1", "retrieved2"})
        self.assertEqual(result["cases"][0]["conditions"]["publisher_pair"],
                         case["conditions"]["publisher_pair"])

    def test_real_frozen_session_consumes_policy_bytes_and_replays_without_generation(self):
        case, label = make_case(row(), ["Unrelated fact."], "2026-01-01T00:00:00Z", "transfer")
        other = copy.deepcopy(case)
        other["phase"] = "retention"
        other["question"]["identity"] += "-old"
        plan = dict(cases=[case, other])
        artifact = dict(schema=PROFILE, weights=list(INITIAL), roots=[], updates=0,
                        plan_digest=digest(plan), reader_identity=Reader.identity,
                        production_accepted=False)
        labels = {c["question"]["identity"]: label for c in plan["cases"]}
        with tempfile.TemporaryDirectory() as directory:
            result = transfer(plan, labels, artifact, Reader(), Path(directory),
                              source_commit="b" * 40)
            self.assertEqual(result["completed"], 4)
            self.assertEqual(result["failed"], 0)
            self.assertTrue((Path(directory) / "learned-session/READY.json").exists())
            self.assertFalse(result["optimizer_at_read_time"])
            self.assertFalse(result["production_accepted"])


if __name__ == "__main__":
    unittest.main()
