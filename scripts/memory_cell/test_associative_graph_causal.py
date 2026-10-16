"""Adversarial, model-free tests: not a real Reader or benchmark result."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import associative_graph_causal as g


def public_fixture():
    families = []
    for f in range(10):
        family = f"conv-{f}"
        docs = []
        for i in range(128):
            docs.append({"id": f"D{f}:{i}", "speaker": "A" if i % 2 else "B",
                         "text": ("alpha beta graph memory evidence %d" % (i % 13))
                             if i % 3 else ("plan step temporal session notes %d" % (i % 11)),
                         "session": "session_%d" % (1 + i // 32), "seq": i + 1})
        questions = [{"id": f"{family}/q{i:04d}", "text": "alpha beta graph memory"}
                     for i in range(24)]
        families.append({"family": family, "sources": docs, "questions": questions})
    return {"schema": g.SCHEMA, "source_sha256": g.DATASET_SHA256,
            "policy": {"source_max": g.MAX_SOURCES, "questions_per_family": 24},
            "families": families}


def write_fixture(tmp):
    prepared = tmp / "prepared"
    prepared.mkdir()
    public = public_fixture()
    hidden = {q["id"]: {"evidence": [s["sources"][0]["id"]],
                        "unresolved_reference": False}
              for s in public["families"] for q in s["questions"]}
    pubsha = g.create_only(prepared / "public.json", public)
    privsha = g.create_only(prepared / "private.json",
                            {"schema": g.SCHEMA, "annotations": hidden})
    manifest = {"schema": g.SCHEMA, "public_sha256": pubsha,
                "private_sha256": privsha, "source_sha256": g.DATASET_SHA256,
                "family_count": 10, "question_count": 240,
                "labels_visible_to_worker": False, "production_accepted": False}
    g.create_only(prepared / "manifest.json", manifest)
    worker = tmp / "worker"
    worker.mkdir()
    for name in ("public.json", "manifest.json"):
        (worker / name).write_bytes((prepared / name).read_bytes())
    return prepared, worker


class GraphMechanicsTest(unittest.TestCase):
    def test_bm25_top_is_source_derived(self):
        a = g.bm25_scores(["cats purr", "bicycle wheels"], "cats purr")
        self.assertGreater(a[0], a[1])

    def test_typed_edges_only(self):
        docs = public_fixture()["families"][0]["sources"]
        edges = g.graph_edges(docs)
        self.assertTrue(any(t == "temporal" for t, *_ in edges))
        self.assertTrue(any(t == "lexical" for t, *_ in edges))
        degree = [0] * len(docs)
        for kind, a, b, weight in edges:
            self.assertIn(kind, ("temporal", "lexical"))
            self.assertLess(a, b)
            self.assertTrue(0 < weight <= 1)
            degree[a] += 1; degree[b] += 1
        self.assertLessEqual(max(degree), g.MAX_DEGREE)

    def test_topology_lesion_preserves_edge_weight_and_degree_distribution(self):
        docs = public_fixture()["families"][0]["sources"]
        edges = g.graph_edges(docs)
        swapped = g.permute_edges(edges, len(docs), "conv-0")
        self.assertEqual(swapped, g.permute_edges(edges, len(docs), "conv-0"))
        self.assertNotEqual(edges, swapped)
        self.assertEqual(sorted((kind, w) for kind, _, _, w in edges),
                         sorted((kind, w) for kind, _, _, w in swapped))
        def degrees(items):
            degree = [0] * len(docs)
            for _, i, j, _ in items:
                degree[i] += 1; degree[j] += 1
            return sorted(degree)
        self.assertEqual(degrees(edges), degrees(swapped))

    def test_unrelated_question_cannot_change_graph(self):
        p = public_fixture()["families"][0]
        edges1 = g.graph_edges(p["sources"])
        p["questions"][0]["text"] = "arbitrary future winner gold reference"
        self.assertEqual(edges1, g.graph_edges(p["sources"]))

    def test_no_seed_no_spontaneous_activation(self):
        docs = public_fixture()["families"][0]["sources"]
        rankings, _ = g.rank_arms(docs, "unmatchedzz", "conv-0")
        self.assertEqual(rankings["bm25"], rankings["fixed_graph"])

    def test_all_five_arms_exact_top8(self):
        docs = public_fixture()["families"][0]["sources"]
        results, _ = g.rank_arms(docs, "alpha beta", "conv-0")
        self.assertEqual(set(results), set(g.ARMS))
        self.assertTrue(all(len(v) == g.TOP_K and len(set(v)) == g.TOP_K for v in results.values()))

    def test_duplicate_json_keys_and_nan_refused(self):
        with self.assertRaises(ValueError):
            g.strict_load(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            g.strict_load(b'{"a":NaN}')

    def test_label_smuggling_and_wrong_generation_refused(self):
        p = public_fixture()
        p["families"][0]["questions"][0]["answer"] = "gold"
        with self.assertRaises(ValueError):
            g.validate_public(p)
        p = public_fixture()
        p["families"][0]["sources"][0]["seq"] = 9
        with self.assertRaises(ValueError):
            g.validate_public(p)

    def test_noncanonical_id_and_malformed_session_refused(self):
        p = public_fixture()
        p["families"][0]["sources"][0]["id"] = "../../secret"
        with self.assertRaises(ValueError):
            g.validate_public(p)
        p = public_fixture()
        p["families"][0]["sources"][0]["session"] = "../tmp"
        with self.assertRaises(ValueError):
            g.validate_public(p)


class SealedStudyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prepared, self.worker = write_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_deny_hidden_labels_at_worker(self):
        with self.assertRaises(ValueError):
            g.run(self.prepared, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_sealed_full_census_and_negative_authority(self):
        output = self.root / "run"
        seal = g.run(self.worker, output)
        self.assertEqual(seal["question_count"], 240)
        self.assertFalse(seal["production_accepted"])
        self.assertEqual(seal["reader_calls"], 0)
        result = g.review(self.prepared, output, self.root / "report.json")
        self.assertEqual(result["effective_source_family_count_at_most"], 10)
        self.assertFalse(result["statistical_superiority"])
        for arm in g.ARMS:
            self.assertEqual(result["by_arm"][arm]["referenced"], 240)

    def test_tampered_prediction_and_resealed_output_refused(self):
        output = self.root / "run"
        g.run(self.worker, output)
        file = output / "predictions.json"
        data = json.loads(file.read_text())
        data["rows"][0]["arms"]["bm25"][0] = "D0:9999"
        raw = g.canonical(data)
        file.write_bytes(raw)
        seal_path = output / "seal.json"
        seal = json.loads(seal_path.read_text())
        seal["predictions_sha256"] = g.digest(raw)
        seal_path.write_bytes(g.canonical(seal))
        with self.assertRaises(ValueError):
            g.review(self.prepared, output, self.root / "report.json")

    def test_source_change_even_with_rehashed_worker_manifest_refused(self):
        p = json.loads((self.worker / "public.json").read_text())
        p["families"][0]["sources"][0]["text"] = "new unrelated content"
        (self.worker / "public.json").write_bytes(g.canonical(p))
        with self.assertRaises(ValueError):
            g.load_public(self.worker)

    def test_revoked_or_changed_public_source_blocks_old_seal(self):
        output = self.root / "run"
        g.run(self.worker, output)
        p = json.loads((self.prepared / "public.json").read_text())
        del p["families"][0]["sources"][0]
        (self.prepared / "public.json").write_bytes(g.canonical(p))
        with self.assertRaises(ValueError):
            g.review(self.prepared, output, self.root / "report.json")

    def test_missing_private_or_citation_labels_refused(self):
        output = self.root / "run"
        g.run(self.worker, output)
        (self.prepared / "private.json").unlink()
        with self.assertRaises(ValueError):
            g.review(self.prepared, output, self.root / "report.json")

    def test_symlink_refused(self):
        link = self.root / "link.json"
        link.symlink_to(self.worker / "public.json")
        with self.assertRaises(ValueError):
            g.regular_bytes(link)

    def test_no_same_report_overwrite(self):
        output = self.root / "run"
        g.run(self.worker, output)
        dest = self.root / "report.json"
        g.review(self.prepared, output, dest)
        with self.assertRaises(FileExistsError):
            g.review(self.prepared, output, dest)

    def test_private_annotation_rewrite_refused(self):
        output = self.root / "run"
        g.run(self.worker, output)
        h = json.loads((self.prepared / "private.json").read_text())
        k = next(iter(h["annotations"]))
        h["annotations"][k]["evidence"] = ["D0:9999"]
        (self.prepared / "private.json").write_bytes(g.canonical(h))
        with self.assertRaises(ValueError):
            g.review(self.prepared, output, self.root / "report.json")


if __name__ == "__main__":
    unittest.main()
