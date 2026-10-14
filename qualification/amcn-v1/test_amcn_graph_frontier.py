"""Real evidence byte and fixed-window graph mechanics (hermetic tests)."""
import unittest
from hashlib import sha256
from amcn_core import Evidence, Refused
from amcn_graph_frontier import freeze_graph_frontier, score_publisher_weak_only


def evidence(sid, content=None, *, generation="g1", scope="lab", root="fam", revoked=False):
    text = content or ("record-" + sid)
    return Evidence(sid, root, scope, 1, text, sha256(text.encode()).hexdigest(), generation, revoked)


def graph():
    docs = [evidence("a", "deadlock lock chain source"),
            evidence("b", "retry lock transaction"),
            evidence("c", "weather unrelated"),
            evidence("d", "inherited source version"),
            evidence("e", "database accounting service"),
            evidence("f", "connection pool quota")]
    adjacent = {"a": ["d"], "d": ["a", "f"], "f": ["d"]}
    return docs, adjacent


class HardFinalEvidenceFrontier(unittest.TestCase):
    def test_concurrent_source_permutation_has_same_plan(self):
        docs, edges = graph()
        a = freeze_graph_frontier("deadlock lock", docs, edges, scope="lab", generation="g1")
        b = freeze_graph_frontier("deadlock lock", list(reversed(docs)),
                                  {k: list(reversed(v)) for k, v in edges.items()},
                                  scope="lab", generation="g1")
        self.assertEqual(a, b)
        metrics = a["metrics"]
        self.assertLessEqual(metrics["final_evidence_count"], 16)
        self.assertEqual(metrics["expanded_node_count"], 6)
        self.assertEqual(metrics["actual_reader_calls"], 0)
        self.assertFalse(metrics["labels_accessed"])

    def test_labels_only_open_in_score_and_no_claim_of_all_for_no_support(self):
        docs, edges = graph()
        plan = freeze_graph_frontier("deadlock lock", docs, edges, scope="lab", generation="g1")
        score = score_publisher_weak_only(plan, ["a", "absent-uid"])
        weak = score["metrics"]
        self.assertTrue(weak["lexical_top16"]["any_support"])
        self.assertFalse(weak["lexical_top16"]["all_support"])
        self.assertEqual(weak["lexical_top16"]["publisher_recall"], .5)
        self.assertFalse(score["production_accepted"])
        missing = score_publisher_weak_only(plan, [])
        self.assertIsNone(missing["metrics"]["lexical_top16"]["all_support"])
        self.assertIsNone(missing["metrics"]["lexical_top16"]["publisher_recall"])

    def test_stale_revoked_or_foreign_bytes_refused(self):
        docs, edges = graph()
        for modified in (
            [*docs[:-1], evidence("f", revoked=True)],
            [*docs[:-1], evidence("f", generation="g2")],
            [*docs[:-1], evidence("f", root="other")],
            docs + [docs[0]],
        ):
            with self.assertRaises(Refused):
                freeze_graph_frontier("deadlock lock", modified, edges, scope="lab", generation="g1")
        with self.assertRaises(Refused):
            freeze_graph_frontier("deadlock lock", docs, {"a":["z"]},scope="lab",generation="g1")
        with self.assertRaises(Refused):
            freeze_graph_frontier("deadlock lock", docs, {"a":["d"]},scope="lab",generation="g1")

    def test_no_partial_graph_on_resource_exhaustion(self):
        # Sixteen identical seed sources + 50 novel temporal neighbors.
        docs=[evidence(f"k{i:02d}", "deadlock lock") for i in range(16)]
        docs.extend(evidence(f"x{i:02d}", "far unrelated") for i in range(50))
        edges={}
        for i in range(16):
            sid=f"k{i:02d}"; neighbor=f"x{i:02d}"
            edges[sid]=[neighbor]; edges[neighbor]=[sid]
        with self.assertRaisesRegex(Refused, "expansion cap"):
            freeze_graph_frontier("deadlock lock", docs, edges, scope="lab",
                                  generation="g1", max_expansion=16)
        supported=freeze_graph_frontier("deadlock lock", docs, edges, scope="lab",
                                        generation="g1", max_expansion=64)
        self.assertEqual(len(supported["metrics"]["seeds"]),16)
        self.assertEqual(len(supported["metrics"]["final_source_ids"]),16)
        self.assertEqual(supported["metrics"]["expanded_node_count"],32)

    def test_publisher_drift_rejects_duplicate_and_illegal_packet(self):
        docs, edges = graph()
        p=freeze_graph_frontier("deadlock lock", docs, edges, scope="lab", generation="g1")
        with self.assertRaises(Refused):
            score_publisher_weak_only(p, ["a","a"])
        with self.assertRaises(Refused):
            score_publisher_weak_only({"schema":"unknown"}, ["a"])

if __name__=="__main__":
    unittest.main()
