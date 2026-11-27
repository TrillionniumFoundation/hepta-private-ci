"""New release checks, using only invented documents and public aggregates."""
from pathlib import Path
import hashlib
import json
import math
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import raw_markdown as rm
from retrieval import ARMS
HERE = Path(__file__).resolve().parents[1]


def parser_for(texts, links=True, repository="example/synthetic-docs"):
    bodies = {path: text.encode() for path, text in texts.items()}
    entries = [rm.Entry("synthetic", p, rm.git_blob_sha1(b), hashlib.sha256(b).hexdigest())
               for p, b in bodies.items()]
    calls = []
    def loader(source, path):
        calls.append(path)
        return bodies[path]
    return rm.Parser(entries, loader, commit="0" * 40, extract_links=links,
                     repository=repository), calls


class PublicParserTests(unittest.TestCase):
    def test_source_locator_positive_rules_and_lazy_adapter(self):
        texts = {"src/guide/entry.md": "# Entry {#entry}\n[a](../api/rules.html#need) [b](/api/rules#need) [c](../api/rules.md)\n",
                 "src/api/rules.md": "# Root {#root}\nInvented root.\n## Need {#need}\nInvented condition.\n"}
        parser, calls = parser_for(texts)
        start = parser.parse("synthetic", "src/guide/entry.md")
        parser.to_mechanics(start.parents)
        self.assertEqual(calls, ["src/guide/entry.md"])
        outcomes = [parser.resolve(start.parents[0], x) for x in start.parents[0].links]
        self.assertTrue(all(x.status == "resolved" for x in outcomes))
        self.assertEqual(outcomes[0].target, outcomes[1].target)
        self.assertNotEqual(outcomes[0].target, outcomes[2].target)
        self.assertEqual(outcomes[2].mode, "document-root-first-parent")
        self.assertEqual(calls, ["src/guide/entry.md", "src/api/rules.md"])

    def test_contiguous_crlf_dynamic_unicode_and_citation(self):
        text = "# Toy {#toy}\r\nA naïve café.\r\n- A **bold** condition.\r\n{{ inert }}\r\n## More {#more}\r\nSecond line without final newline"
        parser, _ = parser_for({"src/toy.md": text})
        doc = parser.parse("synthetic", "src/toy.md")
        self.assertEqual("".join(x.text for x in doc.parents), text)
        self.assertEqual(doc.parents[0].citation, "https://github.com/example/synthetic-docs/blob/" + "0" * 40 + "/src/toy.md#L1-L4")
        self.assertNotIn(doc.parents[0].id, doc.parents[0].citation)
        self.assertEqual(doc.parents[1].breadcrumb, ("Toy", "More"))
        self.assertTrue(doc.warnings)

    def test_fences_and_inline_code_are_inert(self):
        text = "# Toy {#toy}\n````text\n# Not heading\n[a](#toy)\n```\n`````\n## More {#more}\n`[hidden](#toy)` [shown](#more)\n"
        parser, _ = parser_for({"src/toy.md": text})
        doc = parser.parse("synthetic", "src/toy.md")
        self.assertEqual([p.title for p in doc.parents], ["Toy", "More"])
        self.assertEqual(sum(len(p.candidates) for p in doc.parents), 1)
        self.assertEqual(parser.resolve(doc.parents[1], doc.parents[1].links[0]).status, "resolved")

    def test_common_rejections_and_no_scanner_for_nonlinks(self):
        for text, reason in [("# A {#a}\n# B {#a}\n", "duplicate_explicit_anchor"),
                             ("# A\n```\nunclosed", "unclosed_fence")]:
            for mode in (False, True):
                parser, _ = parser_for({"src/toy.md": text}, mode)
                doc = parser.parse("synthetic", "src/toy.md")
                self.assertEqual((doc.reason, doc.parents), (reason, ()))
        parser, calls = parser_for({"src/toy.md": "# A {#a}\n[x](#a)\n"}, False)
        with patch.object(rm, "extract_line_candidates", side_effect=AssertionError):
            doc = parser.parse("synthetic", "src/toy.md")
        with patch.object(parser, "_resolve", side_effect=AssertionError):
            _, audit = parser.to_mechanics(doc.parents)
        self.assertEqual(parser.lexical_scan_calls, 0)
        self.assertEqual(parser.graph_resolutions, 0)
        self.assertTrue(all(x["link_counts"] is None for x in audit.values()))
        with self.assertRaises(RuntimeError):
            parser.resolve(doc.parents[0], None)
        self.assertEqual(len(calls), 1)

    def test_repository_only_changes_citation_not_locator_or_identity(self):
        texts = {"src/toy.md": "# A {#a}\n[x](#a)\n"}
        first, _ = parser_for(texts, repository="example/one")
        second, _ = parser_for(texts, repository="example/two")
        a = first.parse("synthetic", "src/toy.md").parents[0]
        b = second.parse("synthetic", "src/toy.md").parents[0]
        self.assertEqual(a.id, b.id)
        self.assertNotEqual(a.citation, b.citation)
        self.assertEqual(first.resolve(a, a.links[0]).target, second.resolve(b, b.links[0]).target)
        for repo in ["bad", "../bad/repo", "https://example.invalid/repo", "a/b#fragment", "a/b?query"]:
            with self.assertRaises(ValueError):
                parser_for(texts, repository=repo)


class AggregateArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.results = json.loads((HERE / "RESULTS.json").read_text())
        self.a = self.results["aggregate"]
        self.rules = json.loads((HERE / "PROTOCOL.template.json").read_text())["scoring"]["machine"]

    def test_denominators_rates_strata_and_paired_counts(self):
        a = self.a
        self.assertEqual(a["eligible"] + a["excluded_count"], a["planned"])
        self.assertEqual(sum(s["eligible"] for s in a["strata"].values()), a["eligible"])
        for arm in ARMS:
            count = a["complete_counts"][arm]
            self.assertEqual(sum(s["complete_counts"][arm] for s in a["strata"].values()), count)
            self.assertEqual(a["eligible_rates"][arm], count / a["eligible"])
            self.assertEqual(a["planned_denominator_rates"][arm], count / a["planned"])
        for arm, row in self.results["paired_candidate_vs_control"].items():
            self.assertEqual(sum(row.values()), a["eligible"])
            self.assertEqual(row["both_complete"] + row["candidate_only_complete"], a["complete_counts"]["links"])
            self.assertEqual(row["both_complete"] + row["control_only_complete"], a["complete_counts"][arm])
            self.assertEqual(row["candidate_only_complete"] - row["control_only_complete"], a["gains_over_each_control"][arm])

    def test_rejection_and_original_cost_ratio(self):
        a = self.a
        costs = self.results["costs_from_original_frozen_run"]
        ratio = costs["arms"]["links"]["cold_end_to_end_seconds"] / costs["arms"]["bm25"]["cold_end_to_end_seconds"]
        self.assertEqual(ratio, a["candidate_cold_time_ratio"])
        self.assertLessEqual(ratio, self.rules["maximum_cold_time_ratio"])
        self.assertTrue(all(g < self.rules["minimum_gain_each"] for g in a["gains_over_each_control"].values()))
        self.assertEqual(a["direct_loss_count"], 0)
        self.assertEqual(a["screen"], "REJECT")
        self.assertFalse(a["diagnostic_enters_primary_screen"])
        self.assertTrue(math.isclose(sum(c["process_total_seconds"] for c in costs["arms"].values()), costs["all_process_seconds_including_failed_work"], abs_tol=1e-12))


if __name__ == "__main__":
    unittest.main()
