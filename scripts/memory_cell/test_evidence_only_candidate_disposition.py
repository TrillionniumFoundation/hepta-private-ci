"""No gold-value guessing or singleton results misrepresented as reasoning."""
import json
import unittest

from evidence_only_candidate_disposition import restrict_scored


class LocalChoiceTests(unittest.TestCase):
    def setUp(self):
        self.docs = dict(
            terminal=dict(identity="terminal", content=json.dumps(dict(
                id="terminal", schema="hepta.controlled-event.v1",
                value="site_11111111",
            ))),
            distractor=dict(identity="distractor", content=json.dumps(dict(
                id="distractor", schema="hepta.controlled-event.v1",
                value="site_22222222",
            ))),
            bridge=dict(identity="bridge", content=json.dumps(dict(
                id="bridge", schema="hepta.controlled-event.v1",
                value="component_only",
            ))),
        )
        self.row = dict(candidates=[
            dict(value="site_11111111", mean_log_likelihood=-1.0),
            dict(value="site_22222222", mean_log_likelihood=-0.5),
        ])

    def test_empty_source_must_abstain(self):
        got = restrict_scored(self.row, [], self.docs)
        self.assertEqual((got["chosen"], got["abstained"], got["singleton"]),
                         (None, True, False))

    def test_terminal_only_is_trivial_singleton(self):
        got = restrict_scored(self.row, ["terminal"], self.docs)
        self.assertEqual(got["chosen"], "site_11111111")
        self.assertTrue(got["singleton"])

    def test_missing_bridge_does_not_imply_caused_success(self):
        got = restrict_scored(self.row, ["terminal"], self.docs)
        self.assertTrue(got["singleton"])
        self.assertNotIn("bridge", got["evidence_only_candidates"])

    def test_multiple_options_still_require_model_ranking(self):
        got = restrict_scored(self.row, ["terminal", "distractor"], self.docs)
        self.assertEqual(got["chosen"], "site_22222222")
        self.assertEqual(got["candidate_count"], 2)
        self.assertFalse(got["singleton"])


if __name__ == "__main__":
    unittest.main()
