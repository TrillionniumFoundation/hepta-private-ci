import unittest
from stem_native_nonpromotion import audit_nonpromotion, ARMS, PHASES, STAGES


def record():
    metrics = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                metrics[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8, succeeded=8, failed=0,
                    source_accuracy=.25, diagnostic_f1=.125,
                    emitted_citation_markers=0, delivered_citation_markers=0,
                )
    return dict(metrics=metrics, logical_policy_attempts=576,
                production_accepted=False)


class GateTests(unittest.TestCase):
    def test_complete_success_does_not_qualify(self):
        out = audit_nonpromotion(record())
        self.assertFalse(out["scale_out_permitted"])
        self.assertFalse(out["any_aggregate_source_or_answer_gain"])
        self.assertEqual(out["audited_policy_attempts"], 576)
        self.assertEqual(out["learning_arms"]["gated"]["identical_source_accuracy"], 12)

    def test_positive_aggregate_still_does_not_certify_production(self):
        data = record()
        data["metrics"]["48/test/gated"]["source_accuracy"] = .5
        out = audit_nonpromotion(data)
        self.assertTrue(out["any_aggregate_source_or_answer_gain"])
        self.assertFalse(out["scale_out_permitted"])

    def test_missing_row_and_faked_acceptance_rejected(self):
        for mutation in ("missing", "promoted", "mismatched_count"):
            data = record()
            if mutation == "missing":
                data["metrics"].pop("48/test/gated")
            elif mutation == "promoted":
                data["production_accepted"] = True
            else:
                data["metrics"]["48/test/gated"]["attempted"] = 7
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_nonpromotion(data)

    def test_citation_fabrication_rejected(self):
        data = record()
        data["metrics"]["48/test/gated"]["delivered_citation_markers"] = 1
        with self.assertRaises(ValueError):
            audit_nonpromotion(data)


if __name__ == "__main__":
    unittest.main()
