"""Read-only decisions and whole-arm timeout; no model is imported or executed."""

import signal
import time
import unittest

from run_budget_models import freeze_routes, hard_deadline, score_known


class ModelRouteTests(unittest.TestCase):
    def test_route_is_source_only_and_score_requires_provenance(self):
        records = [
            dict(
                record_id="a",
                entity="alpha source",
                relation="command",
                value="x",
                source_digest="a",
            ),
            dict(
                record_id="b",
                entity="beta source",
                relation="command",
                value="y",
                source_digest="b",
            ),
        ]
        versions = [dict(roots=[]), dict(roots=["b"])]
        routes = freeze_routes(
            "data_split",
            records,
            versions,
            {"slots": [0, 1]},
            [dict(id="q", question="alpha source command")],
        )
        self.assertEqual(routes[0]["slot"], 0)
        rows = [
            dict(
                query_id="a",
                kind="known_source_heldout_wording",
                control="adapter",
                slot=0,
                raw={"text": "x"},
            )
        ]
        score = score_known(records, versions, rows)["adapter"]
        self.assertEqual(
            (score["correct"], score["supported_correct"], score["denominator"]),
            (1, 0, 1),
        )

    @unittest.skipUnless(
        hasattr(signal, "SIGALRM"), "Linux main-thread wall timer required"
    )
    def test_host_work_is_covered_by_end_to_end_deadline(self):
        with self.assertRaises(TimeoutError):
            with hard_deadline(0.02):
                time.sleep(0.2)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
