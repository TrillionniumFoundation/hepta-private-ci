"""Bounded, no-partial-write official Memory adapter security regressions."""
import unittest

from test_amcn import LongMemEvalBridgeTests


class ShadowBridgeSecurityTests(unittest.TestCase):
    def setUp(self):
        self.Backend = LongMemEvalBridgeTests()._load_bridge()

    @staticmethod
    def record(identity, text, goal="safe goal"):
        return {"id": identity, "goal": goal,
                "states": [{"url": "https://example.invalid/page",
                            "text": text, "action": "read"}]}

    def test_empty_query_never_loses_negative_capabilities(self):
        memory=self.Backend({})
        self.assertEqual(memory.query("unknown evidence", query_image="ignored.png"), [])
        receipt=memory.post_query_hook(query="unknown evidence", query_image="ignored.png",
                                      memory_context=[])
        self.assertEqual(receipt["count"], 0)
        self.assertEqual(receipt["source_ids"], [])
        self.assertTrue(receipt["image_unsupported"])
        self.assertIs(receipt["trained_neural_cell"], False)
        self.assertIs(receipt["production_qualified"], False)

    def test_control_character_source_id_refused(self):
        memory=self.Backend({})
        with self.assertRaises(RuntimeError):
            memory.insert(self.record("forged\nsource-id", "text"))
        self.assertEqual(memory.query("text"), [])

    def test_oversize_source_and_goal_fail_before_partial_insert(self):
        memory=self.Backend({})
        for payload in (
            self.record("long-goal", "normal", goal="G" * 32769),
            self.record("long-observation", "x" * (1024 * 1024 + 1)),
            {"id":"long-url", "goal":"safe", "states":[{
                "url":"x" * 8193, "text":"safe", "action":"open"}]},
            {"id":"long-action", "goal":"safe", "states":[{
                "url":"https://example.invalid", "text":"safe",
                "action":"a" * 8193}]},
        ):
            with self.assertRaises(RuntimeError):
                memory.insert(payload)
        self.assertEqual(memory.query("safe"), [])

    def test_atomic_rejection_does_not_poison_following_valid_trajectory(self):
        memory=self.Backend({"top_k":2, "max_records":2})
        bad={"id":"bad", "goal":"test", "states":[{
            "url":"url", "text":"one", "action":None},
            {"url":"url", "text":"two", "action":None},
            {"url":"url", "text":"three", "action":None}]}
        with self.assertRaises(RuntimeError):
            memory.insert(bad)
        memory.insert(self.record("good", "database deadlock"))
        self.assertEqual(len(memory.query("database deadlock")),1)


if __name__=="__main__":
    unittest.main()
