"""Self-authored synthetic mechanics tests only. Never loads any real corpus/gold."""
import copy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import selectors
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from retrieval import ARMS, BM25Index, Retriever, navigate, pack, serialize_parent, terms
from runner import load_inputs, load_parser, percentile, execute_arm, verify_freeze, suite, sha256
from scoring import score_tasks, screen, verify_gold_task, verify_emitted_pack

# Standalone direct BM25 oracle newly written for this public derivative.
# This replaces an unavailable historical reference-module import.
from collections import Counter
from types import SimpleNamespace
import re

def reference_terms(text):
    return re.findall(r"[a-z0-9]+", text.lower())

def reference_rank(query, documents):
    ids = sorted(documents)
    counts = {i: Counter(reference_terms(documents[i])) for i in ids}
    lengths = {i: sum(counts[i].values()) for i in ids}
    n = len(ids)
    avg = sum(lengths.values()) / n if n else 0
    scores = {}
    for i in ids:
        values = []
        for term in sorted(set(reference_terms(query))):
            tf = counts[i].get(term, 0)
            if tf:
                df = sum(term in counts[j] for j in ids)
                idf = math.log(1 + (n - df + .5) / (df + .5))
                values.append(idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * lengths[i] / (avg or 1))))
        scores[i] = sum(values)
    return sorted(ids, key=lambda i: (-scores[i], i))

reference = SimpleNamespace(terms=reference_terms, rank=reference_rank)


def doc(i, text, title="", links=()):
    return {"source": "toy", "citation": f"https://example.invalid/toy/{i}#L1-L2",
            "title": title, "text": text, "links": list(links)}


def pinned(body, path="src/guide/toy.md"):
    return {"source": "toy", "path": path,
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
            "sha256": hashlib.sha256(body).hexdigest()}


class RetrievalTests(unittest.TestCase):
    def test_exact_bm25_formula_and_zero_ties(self):
        corpus = {"z": "cat cat dog", "a": "cat", "b": "dog fish", "empty": ""}
        index = BM25Index(corpus)
        expected = math.log(1 + (4 - 2 + .5) / (2 + .5)) * 2 * 2.2 / (2 + 1.2 * (.25 + .75 * 3 / 1.5))
        self.assertEqual(index.scores("cat")["z"], expected)
        self.assertEqual(index.rank("unseen"), sorted(corpus))
        self.assertEqual(index.rank("CAT cat CAT"), index.rank("cat"))
        self.assertEqual(index.rank("fish dog cat"), index.rank("cat fish dog"))
        self.assertEqual(BM25Index({}).rank("cat"), [])

    def test_tokenizer_matches_frozen_reference(self):
        for value in ["ABC-def_12", "é中文APPLE", "K KABC İ Ω", "", "x.x() v-model"]:
            self.assertEqual(terms(value), reference.terms(value))

    def test_builtin_sum_near_tie_matches_reference(self):
        docs = {"000": "alpha beta gamma gamma gamma", "001": "alpha beta beta beta gamma",
                "002": "alpha alpha alpha beta gamma"}
        self.assertEqual(BM25Index(docs).rank("alpha beta gamma"), reference.rank("alpha beta gamma", docs))
        self.assertEqual(BM25Index(docs).rank("alpha beta gamma"), ["000", "001", "002"])

    def test_150_random_collections_exact_reference_rank(self):
        rng = random.Random(117)
        words = ["alpha", "beta", "gamma", "delta", "x", "12"]
        for case in range(150):
            corpus = {f"p-{i:03d}": " ".join(rng.choices(words, k=rng.randrange(0, 40)))
                      for i in range(rng.randrange(0, 25))}
            query = " ".join(rng.choices(words + ["unseen"], k=rng.randrange(0, 8)))
            self.assertEqual(BM25Index(corpus).rank(query), reference.rank(query, corpus), case)

    def test_prf_exact_terms_and_reference_order(self):
        docs = {"a": doc("a", "query zebra zebra alpha alpha cat xx"),
                "b": doc("b", "query beta beta gamma gamma"),
                "c": doc("c", "zebra beta spare"), "d": doc("d", "cat cat")}
        index = BM25Index({i: d["title"] + " " + d["text"] for i, d in docs.items()})
        seeds = index.rank("query")[:2]
        from collections import Counter
        c = Counter(t for i in seeds for t in terms(docs[i]["title"] + " " + docs[i]["text"])
                    if len(t) >= 3 and t not in {"query"})
        expected = sorted(c, key=lambda t: (-c[t] * math.log(1 + (len(docs) + .5) /
                            (sum(t in set(terms(d["title"] + " " + d["text"])) for d in docs.values()) + .5)), t))[:4]
        result = navigate("query", docs, "prf")
        self.assertEqual(result["expansions"], expected)
        self.assertEqual(result["ids"], index.rank("query " + " ".join(expected))[:4])

    def test_prf_tie_is_lexical_and_four_only(self):
        index = BM25Index({"a": "query zzz yyy xxx www vvv uuu", "b": "other"})
        self.assertEqual(index.expansions("query", ["a"]), ["uuu", "vvv", "www", "xxx"])

    def test_links_use_local_bm25_and_hash_frozen_order(self):
        docs = {"a": doc("a", "alpha alpha", links=[{"target": i, "anchor": label}
                for i, label in [("x", "alpha"), ("y", "other"), ("z", "alpha alpha")]]),
                "b": doc("b", "alpha"), "c": doc("c", "alpha filler"),
                "x": doc("x", "mandatory evidence", "x"),
                "y": doc("y", "unrelated evidence", "y"),
                "z": doc("z", "second mandatory", "z")}
        target_corpus = {"x": "alpha x", "y": "other y", "z": "alpha alpha z"}
        result = navigate("alpha", docs, "links")
        self.assertEqual(result["seeds"], ["a", "b"])
        self.assertEqual(result["extra_targets"], reference.rank("alpha", target_corpus)[:2])
        self.assertEqual(result["ids"], ["a", "b"] + result["extra_targets"])
        hashed = navigate("alpha", docs, "hash_links")
        self.assertEqual(hashed["extra_targets"], sorted(target_corpus, key=lambda i: (hashlib.sha256(i.encode()).hexdigest(), i))[:2])
        self.assertNotIn("z", navigate("alpha", docs, "bm25")["ids"])
        self.assertIn("z", result["ids"])

    def test_nonlink_arms_never_access_links(self):
        class Poison(dict):
            def __getitem__(self, key):
                if key == "links":
                    raise AssertionError("nonlink field access")
                return super().__getitem__(key)
            def get(self, key, default=None):
                if key == "links":
                    raise AssertionError("nonlink field access")
                return super().get(key, default)
        docs = {str(i): Poison(doc(str(i), "alpha")) for i in range(9)}
        for arm in ("bm25", "prf", "bm25_top8"):
            self.assertEqual(navigate("alpha", docs, arm)["link_field_reads"], 0)

    def test_same_source_and_seed_exclusion(self):
        docs = {"a": doc("a", "query query", links=[{"target": "b", "anchor": "query"},
                {"target": "x", "anchor": "query"}, {"target": "missing", "anchor": "query"}]),
                "b": doc("b", "query"), "x": doc("x", "other")}
        docs["x"]["source"] = "foreign"
        self.assertEqual(navigate("query", docs)["extra_targets"], [])

    def test_full_citation_utf8_and_no_truncation(self):
        small = doc("a", "汉字\r\n", "É")
        payload = serialize_parent(small)
        self.assertEqual(payload, small["citation"] + "\nÉ\n汉字\r\n\n")
        self.assertNotEqual(len(payload), len(payload.encode()))
        big = doc("big", "x" * 8192)
        docs = {"big": big, "a": small, "b": doc("b", "literal")}
        result = pack(["big", "a", "a", "b"], docs)
        self.assertEqual(result["ids"], ["a", "b"])
        self.assertEqual(result["payloads"][0], payload)
        self.assertEqual(result["bytes"], sum(len(p.encode()) for p in result["payloads"]))
        self.assertEqual(result["skipped_over_budget"], ["big"])
        self.assertNotIn("#a", payload)

    def test_exact_byte_boundary_and_budget_locked(self):
        d = doc("a", "")
        d["text"] = "x" * (8192 - len(serialize_parent(d).encode()))
        self.assertEqual(pack(["a"], {"a": d})["bytes"], 8192)
        d["text"] += "x"
        self.assertEqual(pack(["a"], {"a": d})["ids"], [])
        with self.assertRaises(ValueError):
            pack([], {}, byte_cap=8193)
        with self.assertRaises(ValueError):
            pack([], {}, max_parents=5)

    def test_equal_main_budget_and_separate_top8(self):
        docs = {f"p{i}": doc(f"p{i}", "identical query") for i in range(10)}
        for arm in ARMS:
            result = navigate("query", docs, arm)
            self.assertEqual(len(result["ids"]), 8 if arm == "bm25_top8" else 4)
            self.assertEqual(result["byte_cap"], 8192)
        self.assertEqual(navigate("query", docs, "bm25")["ids"], ["p0", "p1", "p2", "p3"])


class ParserIntegrationTests(unittest.TestCase):
    def test_true_false_identical_and_nonlink_scanner_zero(self):
        module = load_parser()
        bodies = {"src/guide/toy.md": b"# Start {#start}\nalpha [required](./target.md#target)\n",
                  "src/guide/target.md": b"# Target {#target}\nToy prerequisite.\n"}
        entries = [module.Entry(**pinned(body, path)) for path, body in bodies.items()]
        outputs = []
        for links in (False, True):
            with patch.object(module, "extract_line_candidates", wraps=module.extract_line_candidates) as scanner:
                parser = module.Parser(entries, lambda source, path: bodies[path], commit=("0" * 40), extract_links=links)
                parents = [p for entry in entries for p in parser.parse(entry.source, entry.path).parents]
                docs, audit = parser.to_mechanics(parents)
                if not links:
                    self.assertEqual(scanner.call_count, 0)
                    self.assertTrue(all(not a["links_extracted"] for a in audit.values()))
                else:
                    self.assertGreater(scanner.call_count, 0)
                outputs.append({i: {k: d[k] for k in ("citation", "title", "text")} for i, d in docs.items()})
        self.assertEqual(outputs[0], outputs[1])

    def test_raw_loader_pins_cost_and_failure_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = b"# Toy {#toy}\nalpha prerequisite\n"
            (root / "toy.md").write_bytes(body)
            row = dict(pinned(body), local_path="toy.md")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"commit": "0" * 40, "files": [row]}))
            queries = root / "queries.json"
            queries.write_text(json.dumps([{"id": "q", "question": "alpha"}]))
            docs, task_queries, audit = load_inputs(manifest, queries, "bm25")
            self.assertEqual(audit["raw_load_count"], 1)
            self.assertEqual(audit["raw_bytes"], len(body))
            self.assertFalse(audit["extract_links"])
            self.assertEqual(len(docs), 1)
            result = execute_arm("bm25", manifest, queries, root / "successful")
            self.assertEqual(result["status"], "SUCCESS")
            self.assertGreater(result["cold_end_to_end_seconds"], 0)
            self.assertGreaterEqual(result["startup_seconds"], 0)
            cold_event = next(e for e in result["events"] if e["event"] == "cold_complete")
            warm_event = next(e for e in result["events"] if e["event"] == "warm_started")
            self.assertGreaterEqual(warm_event["warm_started_monotonic"], cold_event["cold_finished_monotonic"])
            self.assertGreaterEqual(cold_event["warm_ack_sent_since_spawn_seconds"], result["cold_end_to_end_seconds"])
            costs = json.loads((root / "successful" / "costs.json").read_text())
            self.assertEqual(costs["warm_repeats"], 3)
            self.assertEqual(costs["warm_queries"], 3)
            self.assertGreater(costs["peak_rss_bytes"], 0)
            (root / "toy.md").write_bytes(body + b"tamper")
            failed = execute_arm("bm25", manifest, queries, root / "failed")
            self.assertNotEqual(failed["status"], "SUCCESS")
            self.assertIsNone(failed["cold_end_to_end_seconds"])
            self.assertGreater(failed["failed_work_charged_seconds"], 0)
            self.assertTrue((root / "failed" / "stderr.log").read_text())

    def test_percentiles_fixed_nearest_rank(self):
        self.assertEqual(percentile([9, 1, 3, 7], .5), 3)
        self.assertEqual(percentile([9, 1, 3, 7], .95), 9)
        self.assertIsNone(percentile([], .5))

    def test_delayed_parent_read_does_not_deadlock_cold_ack(self):
        original = selectors.DefaultSelector
        class DelayedSelector:
            def __init__(self):
                self.delegate = original()
                self.first = True
            def register(self, *args, **kwargs):
                return self.delegate.register(*args, **kwargs)
            def select(self, *args, **kwargs):
                if self.first:
                    self.first = False
                    time.sleep(.15)
                return self.delegate.select(*args, **kwargs)
            def close(self):
                self.delegate.close()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = b"# Toy\nalpha prerequisite\n"
            (root / "toy.md").write_bytes(body)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"commit": "0" * 40, "files": [dict(pinned(body), local_path="toy.md")]}))
            queries = root / "queries.json"
            queries.write_text(json.dumps([{"id": "q", "question": "alpha"}]))
            with patch("runner.selectors.DefaultSelector", DelayedSelector):
                result = execute_arm("bm25", manifest, queries, root / "delayed", timeout=2)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertGreaterEqual(result["cold_end_to_end_seconds"], .15)

    def test_incomplete_or_invented_freeze_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freeze.json"
            for value in [{"files": {}}, {"schema": "sanitized-pilot-code-freeze-v1", "files": {}},
                          {"schema": "sanitized-pilot-code-freeze-v1", "files": {"other": "0" * 64}}]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    verify_freeze(path)

    def test_top8_failure_not_a_primary_execution_veto(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, queries, freeze, auth = [root / name for name in ("manifest", "queries", "freeze", "auth")]
            manifest.write_text(json.dumps({"fixture_kind": "self_authored_synthetic"}))
            queries.write_text("[]")
            freeze.write_text("{}")
            auth.write_text(json.dumps({"kind": "synthetic_engineering_only", "manifest_sha256": sha256(manifest),
                                       "queries_sha256": sha256(queries), "freeze_sha256": sha256(freeze)}))
            def mocked_arm(arm, *args, **kwargs):
                success = arm != "bm25_top8"
                return {"arm": arm, "status": "SUCCESS" if success else "TIMEOUT", "process_total_seconds": 1,
                        "events": [{"event": "cold_complete", "canonical_representation_sha256": "same"}] if success else []}
            with patch("runner.verify_freeze", return_value=sha256(freeze)), patch("runner.execute_arm", side_effect=mocked_arm):
                result = suite(manifest, queries, root / "output", auth, freeze)
            self.assertEqual(result["execution_gate"], "AWAIT_INDEPENDENT_SCORING")
            self.assertTrue(result["primary_canonical_representations_equal"])
            self.assertFalse(result["primary_execution_failure"])
            self.assertNotEqual(result["diagnostic_status"]["bm25_top8"], "SUCCESS")


class ScoringTests(unittest.TestCase):
    def fixture(self):
        parser_module = load_parser()
        raw = b"# Toy {#toy}\nAlpha requires a prerequisite.\n"
        row = pinned(raw)
        parser = parser_module.Parser([parser_module.Entry(**row)], lambda *args: raw,
                                      commit=("0" * 40), extract_links=False)
        parent = parser.parse("toy", row["path"]).parents[0]
        docs, _ = parser.to_mechanics([parent])
        task = {"id": "t", "eligible": True, "question": "alpha", "intended_action": "Use alpha correctly",
                "source_anchor_file": row["path"], "stratum": "direct", "review_decision": "approved",
                "semantic_review_complete": True, "representation_review_complete": True,
                "semantic_obligations": [{"id": "o", "statement": "Alpha requires a prerequisite."}],
                "sufficient_support_alternatives": [{"parent_ids": [parent.id], "coverage": [
                    {"obligation_id": "o", "parent_id": parent.id, "source": "toy", "path": row["path"],
                     "file_sha256": row["sha256"], "start_line": 2, "end_line": 2,
                     "exact_text": "Alpha requires a prerequisite.\n"}]}]}
        return task, docs, {parent.id: parent}, {("toy", row["path"]): raw}

    def test_reviewed_span_then_pack_required_not_id_only(self):
        task, docs, parents, raw = self.fixture()
        self.assertTrue(verify_gold_task(task, parents, raw)["eligible"])
        output = navigate("alpha", docs, "bm25")
        result = score_tasks([task], {"bm25": {"t": output}}, docs, parents, raw)
        self.assertTrue(result["task_results"][0]["success"]["bm25"])
        bad = copy.deepcopy(output)
        bad["payloads"] = ["fake"]
        with self.assertRaisesRegex(ValueError, "altered"):
            verify_emitted_pack(bad, docs, "bm25")

    def test_review_missing_bad_hash_bad_span_rejected(self):
        for change, value in [("semantic_review_complete", False), ("representation_review_complete", False),
                              ("review_decision", "pending")]:
            task, docs, parents, raw = self.fixture()
            task[change] = value
            with self.assertRaises(ValueError):
                verify_gold_task(task, parents, raw)

    def test_same_id_forged_adapter_does_not_bridge_gold(self):
        task, docs, parents, raw = self.fixture()
        ident = next(iter(docs))
        docs[ident]["text"] = "No support here.\n"
        output = navigate("alpha", docs, "bm25")
        with self.assertRaisesRegex(ValueError, "canonical"):
            score_tasks([task], {"bm25": {"t": output}}, docs, parents, raw)
        for key, value in [("exact_text", "invention"), ("file_sha256", "0" * 64), ("end_line", 20)]:
            task, docs, parents, raw = self.fixture()
            task["sufficient_support_alternatives"][0]["coverage"][0][key] = value
            with self.assertRaises(ValueError):
                verify_gold_task(task, parents, raw)

    def synthetic_screen(self):
        protocol = json.loads((HERE / "PROTOCOL.template.json").read_text())
        scored = {"task_results": [{"id": str(i), "stratum": "direct" if i == 0 else "reference",
                   "success": {"links": True, "bm25": i < 6, "prf": i < 6, "hash_links": i < 6}}
                  for i in range(8)], "excluded": [{"id": str(i), "reason": "toy excluded"} for i in range(8, 16)],
                  "budget_infeasible": []}
        runtime = {arm: {"status": "SUCCESS", "cold_end_to_end_seconds": 1.0} for arm in ARMS}
        return scored, runtime, protocol

    def test_three_controls_gain_and_exact_tie(self):
        scored, runtime, protocol = self.synthetic_screen()
        result = screen(scored, runtime, protocol)
        self.assertEqual(result["screen"], "PASS_SCREEN")
        self.assertEqual(result["strongest_cheap_control"], "bm25")
        self.assertEqual(result["planned_denominator_rates"]["links"], .5)
        runtime["prf"]["cold_end_to_end_seconds"] = .9
        self.assertEqual(screen(scored, runtime, protocol)["strongest_cheap_control"], "prf")
        scored["task_results"][6]["success"]["hash_links"] = True
        self.assertEqual(screen(scored, runtime, protocol)["screen"], "REJECT")

    def test_direct_loss_any_control_and_zero_direct(self):
        scored, runtime, protocol = self.synthetic_screen()
        scored["task_results"][0]["success"] = {"links": False, "hash_links": True}
        self.assertIn("direct_task_loss", screen(scored, runtime, protocol)["rejection_reasons"])
        scored["task_results"][0]["stratum"] = "reference"
        self.assertEqual(screen(scored, runtime, protocol)["screen"], "INCONCLUSIVE")

    def test_timeout_never_success_or_fake_runtime(self):
        scored, runtime, protocol = self.synthetic_screen()
        runtime["hash_links"] = {"status": "TIMEOUT", "cold_end_to_end_seconds": None}
        result = screen(scored, runtime, protocol)
        self.assertEqual(result["screen"], "INCONCLUSIVE")
        self.assertIsNone(result["candidate_cold_time_ratio"])
        runtime["hash_links"] = {"status": "SUCCESS", "cold_end_to_end_seconds": 1}
        runtime["links"]["cold_end_to_end_seconds"] = 2.000001
        self.assertEqual(screen(scored, runtime, protocol)["screen"], "REJECT")
        runtime["links"]["cold_end_to_end_seconds"] = True
        self.assertEqual(screen(scored, runtime, protocol)["screen"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
