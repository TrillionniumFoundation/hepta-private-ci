"""Original-source two-file evidence integrity and adversarial negative controls.

The local independent-audit substitute is explicitly a public mechanical label
fixture, not a human oracle or original model answer. CI replays the genuine
full original cross-file auditor before opening those labels.
"""
from __future__ import annotations

import copy
from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from real_source_reader_probe import canonical, digest, real_source
from memory_original_nonparam_pair import (
    ARMS, ROOT_COUNTS, bm25_candidates, code_search_candidates,
    source_graph_candidates, read_docs,
)
from memory_original_evidence_completion import (
    SCHEMA, MAX_BYTES_PER_SOURCE, MAX_SPANS, PLAN_SHA256, RANK_SHA256, SLOTS,
    public_plan, rank_without_gold, independent_score, _caller_lines,
    _definition_lines, write_once,
)

# Exposed original static source locations, used ONLY to test independent scorer
# mechanics. These locations are not consulted by the ranker.
ORIGINAL_LINES = {
    "py-http-01": ("Lib/test/test_httplib.py", "Lib/http/client.py", 3, 164, 1397),
    "py-http-02": ("Lib/test/test_httplib.py", "Lib/http/client.py", 3, 237, 1356),
    "py-http-03": ("Lib/test/test_httplib.py", "Lib/http/client.py", 3, 1130, 1091),
    "sk-base-01": ("sklearn/linear_model/tests/test_base.py", "sklearn/linear_model/_base.py", 12, 388, 113),
    "sk-base-02": ("sklearn/linear_model/tests/test_base.py", "sklearn/linear_model/_base.py", 12, 725, 223),
    "sk-log-01": ("sklearn/linear_model/tests/test_logistic.py", "sklearn/linear_model/_logistic.py", 25, 473, 236),
    "sk-log-02": ("sklearn/linear_model/tests/test_logistic.py", "sklearn/linear_model/_logistic.py", 25, 671, 782),
    "sk-api-01": ("sklearn/utils/tests/test_array_api.py", "sklearn/utils/_array_api.py", 19, 231, 966),
    "sk-api-02": ("sklearn/utils/tests/test_array_api.py", "sklearn/utils/_array_api.py", 19, 459, 1010),
    "deno-01": ("libs/cache_dir/global/mod.rs", "libs/cache_dir/cache.rs", 29, 74, 166),
    "deno-02": ("libs/cache_dir/file_fetcher/mod.rs", "libs/cache_dir/cache.rs", 39, 730, 48),
    "deno-03": ("libs/cache_dir/global/mod.rs", "libs/cache_dir/cache.rs", 26, 171, 203),
}


class OriginalTwoSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        reopen = os.environ.get("MEMORY_REOPEN_ZIP")
        if not source or not reopen:
            raise RuntimeError("pinned external originals are mandatory, not optional skips")
        cls.sources = real_source(Path(source), Path(reopen))
        cls.plan = public_plan(cls.sources)
        cls.ranking = rank_without_gold(cls.sources, cls.plan)
        cls.docs = read_docs(cls.sources)
        cls.case_by_id = {x["id"]: x for x in cls.plan["cases"]}

    @classmethod
    def oracle(cls):
        pairs = []
        for case in cls.plan["cases"]:
            caller, target, import_line, call_line, definition = ORIGINAL_LINES[case["id"]]
            call_lines = cls.docs[(case["root"], caller)]["text"].splitlines()
            def_lines = cls.docs[(case["root"], target)]["text"].splitlines()
            pairs.append(dict(
                id=case["id"], repository_proxy=case["root"],
                caller_file=caller, implementation_file=target,
                import_site_sha256=digest(call_lines[import_line - 1].encode()),
                call_site_sha256=digest(call_lines[call_line - 1].encode()),
                definition_site_sha256=digest(def_lines[definition - 1].encode()),
            ))
        return dict(schema="hepta.memory.original-crossfile-dependency.v1", cases=pairs)

    def score_with_local_mechanical_fixture(self, ranking=None, oracle=None, plan=None):
        labels = oracle if oracle is not None else self.oracle()
        with patch.dict(sys.modules, {"memory_original_crossfile_trace":
                                      types.SimpleNamespace(audit=lambda _s: self.oracle())}):
            return independent_score(self.sources, plan or self.plan,
                                     ranking if ranking is not None else self.ranking, labels)

    def test_frozen_source_only_plan_exact_pre_registered(self):
        self.assertEqual(digest(canonical(self.plan) + b"\n"), PLAN_SHA256)
        self.assertEqual(SLOTS, 2)
        self.assertEqual(MAX_SPANS, 3)
        self.assertEqual(MAX_BYTES_PER_SOURCE, 480)
        self.assertEqual(self.plan["arms"], list(ARMS))
        self.assertEqual(len(self.plan["cases"]), 12)
        self.assertEqual(set(ORIGINAL_LINES), set(self.case_by_id))
        self.assertEqual({k: sum(c["root"] == k for c in self.plan["cases"])
                          for k in ROOT_COUNTS}, ROOT_COUNTS)

    def test_query_registration_contains_no_answer_labels(self):
        self.assertFalse(self.plan["gold_before_ranking"])
        self.assertEqual(self.plan["future_source_family_count"], 0)
        for case in self.plan["cases"]:
            self.assertNotIn("implementation_file", case)
            self.assertNotIn("target", case)
            self.assertNotIn("answer", case)

    def test_frozen_complete_original_rank_census(self):
        self.assertEqual(digest(canonical(self.ranking) + b"\n"), RANK_SHA256)
        self.assertEqual(len(self.ranking["rows"]), 36)
        self.assertFalse(self.ranking["labels_opened"])
        self.assertEqual(self.ranking["pretrained_calls"], 0)
        self.assertEqual(self.ranking, rank_without_gold(self.sources, self.plan))

    def test_equal_slots_and_line_byte_budgets(self):
        for row in self.ranking["rows"]:
            self.assertEqual(len(row["source_paths"]), 2)
            self.assertEqual(len(row["evidence"]), 2)
            self.assertEqual(len(set(row["source_paths"])), 2)
            self.assertEqual(row["source_paths"], [x["path"] for x in row["evidence"]])
            self.assertEqual(row["raw_span_bytes"], sum(x["raw_span_bytes"] for x in row["evidence"]))
            for packet in row["evidence"]:
                self.assertLessEqual(packet["raw_span_bytes"], 480)
                self.assertLessEqual(len(packet["spans"]), 3)

    def test_individual_lines_and_blob_sha_are_original(self):
        for row in self.ranking["rows"]:
            for packet in row["evidence"]:
                orig = self.docs[(row["root"], packet["path"])]
                lines = orig["text"].splitlines()
                self.assertEqual(packet["blob_sha"], orig["blob"])
                self.assertEqual(packet["source_sha256"], orig["sha256"])
                for span in packet["spans"]:
                    self.assertEqual(span["text"], lines[span["line"] - 1])
                    self.assertEqual(span["sha256"], digest(span["text"].encode()))

    def test_complete_original_caller_and_definition_lines(self):
        for row in self.ranking["rows"]:
            if row["arm"] != ARMS[1]:
                continue
            evidence = {x["path"]: x for x in row["evidence"]}
            caller, callee, imp, call, definition = ORIGINAL_LINES[row["id"]]
            self.assertEqual({caller, callee}, set(evidence))
            self.assertIn(imp, [x["line"] for x in evidence[caller]["spans"]])
            self.assertIn(call, [x["line"] for x in evidence[caller]["spans"]])
            self.assertIn(definition, [x["line"] for x in evidence[callee]["spans"]])

    def test_lexical_baseline_not_unfairly_removed(self):
        scored = self.score_with_local_mechanical_fixture()
        self.assertEqual(scored["arms"][ARMS[0]]["complete_pairs"], 10)
        self.assertEqual(scored["arms"][ARMS[0]]["import_use_definition_all_present"], 10)
        self.assertEqual(scored["arms"][ARMS[0]]["definition_line"], 11)

    def test_strong_symbol_code_retrieval_matches_graph(self):
        scored = self.score_with_local_mechanical_fixture()
        self.assertEqual(scored["arms"][ARMS[1]]["import_use_definition_all_present"], 12)
        self.assertEqual(scored["arms"][ARMS[2]]["import_use_definition_all_present"], 12)
        self.assertEqual(scored["code_graph_increment_over_symbol"], 0)
        self.assertEqual(scored["arms"][ARMS[1]]["evidence_bytes"], 1654)
        self.assertEqual(scored["arms"][ARMS[2]]["evidence_bytes"], 1654)

    def test_score_remains_mechanical_unknown_real_tasks(self):
        scored = self.score_with_local_mechanical_fixture()
        self.assertEqual(scored["schema"], SCHEMA + ".independent-scored.v1")
        self.assertEqual(scored["new_model_calls"], 0)
        self.assertIsNone(scored["natural_reader_task_success"])
        self.assertIsNone(scored["program_repair_success"])
        self.assertIsNone(scored["total_lifecycle_cost"])
        self.assertFalse(scored["production_qualified"])

    def test_exact_scored_output_can_be_frozen_and_reproduced(self):
        score = self.score_with_local_mechanical_fixture()
        self.assertEqual(digest(canonical(score) + b"\n"),
                         "29a3ab664f7f338589a23e62d33379fdafbb5fbbcf382b8eae917577f1b9d8b8")

    def test_score_denies_forged_source_identity(self):
        forged = copy.deepcopy(self.ranking)
        forged["rows"][0]["evidence"][0]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "evidence tampered"):
            self.score_with_local_mechanical_fixture(ranking=forged)

    def test_score_denies_missing_caller_line(self):
        forged = copy.deepcopy(self.ranking)
        first = next(x for x in forged["rows"] if x["arm"] == ARMS[1])
        first["evidence"][0]["spans"].pop()
        with self.assertRaisesRegex(ValueError, "evidence tampered"):
            self.score_with_local_mechanical_fixture(ranking=forged)

    def test_score_denies_incorrect_gold(self):
        forged = copy.deepcopy(self.oracle())
        forged["cases"][0]["definition_site_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "static oracle"):
            self.score_with_local_mechanical_fixture(oracle=forged)

    def test_rank_denies_forged_query_or_changed_source(self):
        forged = copy.deepcopy(self.plan)
        forged["cases"][0]["caller_file"] = "invented/file.py"
        with self.assertRaisesRegex(ValueError, "plan altered"):
            rank_without_gold(self.sources, forged)
        modified = copy.deepcopy(self.sources)
        item = self.plan["cases"][0]
        k = (item["root"], item["caller_file"])
        modified[1][k] = b"tampered original source"
        with self.assertRaisesRegex(ValueError, "immutable original file"):
            rank_without_gold(modified, self.plan)

    def test_import_lesion_does_not_fake_a_graph_edge(self):
        case = self.case_by_id["sk-base-01"]
        docs = copy.deepcopy(self.docs)
        lexical = bm25_candidates(case, case["root"], docs)
        first = source_graph_candidates(case, case["root"], docs, lexical)[0]
        self.assertEqual(first, ORIGINAL_LINES["sk-base-01"][1])
        caller = docs[(case["root"], case["caller_file"])]
        caller["text"] = caller["text"].replace(
            "from sklearn.linear_model._base import (", "from deliberately.fake import (")
        self.assertNotEqual(source_graph_candidates(case, case["root"], docs, lexical)[0], first)
        self.assertEqual(code_search_candidates(case, case["root"], docs, lexical)[0], first)

    def test_parser_lesion_refuses_false_caller_proof(self):
        item = self.case_by_id["sk-base-01"]
        text = self.docs[(item["root"], item["caller_file"])]["text"]
        baseline = _caller_lines(item, text)
        self.assertIn(12, baseline)
        altered = text.replace("from sklearn.linear_model._base import (", "from deliberately.fake import (")
        self.assertNotIn(12, _caller_lines(item, altered))

    def test_definition_deletion_cannot_be_inferred_from_other_lines(self):
        item = self.case_by_id["py-http-01"]
        text = self.docs[(item["root"], ORIGINAL_LINES["py-http-01"][1])]["text"]
        self.assertEqual(_definition_lines(item["symbol"], text), [1397])
        edited = text.replace("    def request(self, method, url, body=None, headers={}, *", "    def renamed_request(self, method, url, body=None, headers={}, *")
        self.assertEqual(_definition_lines(item["symbol"], edited), [])

    def test_create_only_plan_and_ranking_cli_identical(self):
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.json"
            from memory_original_evidence_completion import main
            args = ["--source-zip", os.environ["MEMORY_REAL_SOURCE_ZIP"],
                    "--reopen-zip", os.environ["MEMORY_REOPEN_ZIP"],
                    "--plan", str(plan)]
            with patch.object(sys, "argv", ["run", "prepare", *args, "--output", str(plan)]):
                main()
            self.assertEqual(digest(plan.read_bytes()), PLAN_SHA256)
            ranking = Path(td) / "ranking.json"
            with patch.object(sys, "argv", ["run", "rank", *args, "--output", str(ranking)]):
                main()
            self.assertEqual(digest(ranking.read_bytes()), RANK_SHA256)
            with patch.object(sys, "argv", ["run", "rank", *args, "--output", str(ranking)]):
                with self.assertRaisesRegex(ValueError, "output must not exist"):
                    main()

    def test_no_production_or_parametric_promotion(self):
        self.assertFalse(self.plan["production_qualified"])
        self.assertFalse(self.ranking["production_qualified"])
        self.assertEqual(len(self.plan["source_inventory"]), len(self.docs))
        self.assertEqual(self.ranking["plan_sha256"], PLAN_SHA256)


if __name__ == "__main__":
    unittest.main()
