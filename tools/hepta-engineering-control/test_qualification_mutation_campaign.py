import unittest

from control_engineering_v2.qualification_mutation_campaign import mutation_definitions


class MutationCampaignDefinitionTests(unittest.TestCase):
    def test_expected_clock_mutations_are_bounded_and_source_exact(self):
        source = """
if future_skew > policy.maximum_future_skew_ns:
    pass
if now_ns >= expires_unix_ns:
    pass
if age > policy.maximum_observation_age_ns:
    pass
"""
        mutations = mutation_definitions(source)
        self.assertEqual(len(mutations), 3)
        self.assertEqual({item.operation for item in mutations}, {"replace_text"})

    def test_source_drift_rejects_campaign(self):
        with self.assertRaisesRegex(ValueError, "mutation_campaign_source_drift"):
            mutation_definitions("if now_ns >= expires_unix_ns:\n    pass\n")


if __name__ == "__main__":
    unittest.main()
