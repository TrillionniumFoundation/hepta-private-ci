import unittest

from hepta_learning_eval_projection import BEGIN, END, canonical, projection, replace_projection


def status():
    return {"module": "learning.eval", "claims": {"productionImplementation": False},
            "sourceFacts": {"recoverySource": {"processKillFixtureCutCount": 7},
                            "outcomeSource": {"maximumChannels": 32, "maximumBatchRows": 100000},
                            "capacitySource": {"configuredAttempts": 4096,
                                               "expectedLifecycleEvents": 24576,
                                               "anchoredRestartInterval": 128}}}


class ProjectionTests(unittest.TestCase):
    def test_canonical_key_order_is_stable(self):
        self.assertEqual(canonical({"b": 2, "a": 1}), canonical({"a": 1, "b": 2}))

    def test_missing_block_preserves_all_design_text(self):
        original = "# Design\n\nDetailed protocol and historical evidence.\n"
        result = replace_projection(original, projection(status()))
        self.assertTrue(result.startswith(original))
        self.assertEqual(result.count(BEGIN), 1)

    def test_replacement_is_idempotent_and_preserves_both_sides(self):
        document = "prefix\n" + BEGIN + "\nold\n" + END + "\nsuffix\n"
        block = projection(status())
        result = replace_projection(document, block)
        self.assertEqual(result, "prefix\n" + block + "suffix\n")
        self.assertEqual(replace_projection(result, block), result)

    def test_malformed_markers_fail_closed(self):
        for document in [BEGIN, END, END + BEGIN, BEGIN + END + BEGIN + END]:
            with self.subTest(document=document), self.assertRaises(ValueError):
                replace_projection(document, projection(status()))

    def test_changed_inventory_changes_projection(self):
        value = status()
        before = projection(value)
        value["sourceFacts"]["recoverySource"]["processKillFixtureCutCount"] = 8
        self.assertNotEqual(before, projection(value))

    def test_capacity_inventory_changes_projection(self):
        value = status()
        before = projection(value)
        value["sourceFacts"]["capacitySource"]["configuredAttempts"] = 8192
        self.assertNotEqual(before, projection(value))

    def test_source_cannot_issue_acceptance(self):
        value = status()
        value["claims"]["productionImplementation"] = True
        with self.assertRaises(ValueError):
            projection(value)


if __name__ == "__main__":
    unittest.main()
