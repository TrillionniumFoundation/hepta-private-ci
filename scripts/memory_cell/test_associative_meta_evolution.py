"""Source-bound, model-free adversarial tests. No production or QA claim."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import associative_graph_causal as g
import associative_meta_evolution as m


def fixture():
    families = []
    for f in range(10):
        docs = []
        for i in range(128):
            docs.append({"id": f"D{f}:{i}",
                         "speaker": "Alice" if i % 2 else "Bob",
                         "text": ("alpha beta graph evidence %d" % (i % 13)) if i % 3
                         else ("temporal plan session memory %d" % (i % 11)),
                         "session": f"session_{1 + i // 32}", "seq": i + 1})
            docs[-1]["text"] += f" cluster{i // 8} topic{i // 8}"
        fam = f"conv-{f}"
        questions = [{"id": f"{fam}/q{i:04d}",
                      "text": "alpha beta graph memory"} for i in range(24)]
        families.append({"family": fam, "sources": docs, "questions": questions})
    return {"schema": g.SCHEMA, "source_sha256": g.DATASET_SHA256,
            "policy": {"source_max": g.MAX_SOURCES,
                       "questions_per_family": g.Q_PER_FAMILY}, "families": families}


def make_dirs(root):
    prepared = root / "prepared"
    prepared.mkdir()
    public = fixture()
    labels = {q["id"]: {"evidence": [f["sources"][0]["id"]],
                         "unresolved_reference": False}
              for f in public["families"] for q in f["questions"]}
    pubsha = g.create_only(prepared / "public.json", public)
    refsha = g.create_only(prepared / "private.json",
                           {"schema": g.SCHEMA, "annotations": labels})
    g.create_only(prepared / "manifest.json", {
        "schema": g.SCHEMA, "public_sha256": pubsha,
        "private_sha256": refsha, "source_sha256": g.DATASET_SHA256,
        "family_count": 10, "question_count": 240,
        "labels_visible_to_worker": False, "production_accepted": False})
    worker = root / "worker"
    worker.mkdir()
    for name in ("public.json", "manifest.json"):
        (worker / name).write_bytes((prepared / name).read_bytes())
    return prepared, worker


class GateMechanics(unittest.TestCase):
    def setUp(self):
        self.section = fixture()["families"][0]
        self.docs = self.section["sources"]
        self.edges = g.graph_edges(self.docs)

    def test_deterministic_nonzero_weights(self):
        a = m._learn(self.docs, self.edges, "conv-0")
        b = m._learn(self.docs, self.edges, "conv-0")
        self.assertEqual(a, b)
        self.assertNotEqual(a["parent"], [0.0] * 4)
        self.assertEqual(a["parent_parameter_touches"], a["split_parameter_touches"])
        self.assertEqual(a["parent_parameters"], a["split_parameters"])

    def test_split_has_same_edges_but_distinct_weights(self):
        artifact = m._learn(self.docs, self.edges, "conv-0")
        a = m._new_edges(self.docs, self.edges, artifact, mode="typed_split")
        b = m._new_edges(self.docs, self.edges, artifact, mode="swapped_type")
        self.assertEqual(tuple(row[:3] for row in a), tuple(row[:3] for row in self.edges))
        self.assertNotEqual(a, b)
        self.assertTrue(all(.1 <= e[3] <= .95 for e in a))

    def test_training_is_question_label_blind(self):
        old = m._learn(self.docs, self.edges, "conv-0")
        section = copy.deepcopy(self.section)
        section["questions"][0]["text"] = "arbitrary gold reference answer"
        self.assertEqual(old, m._learn(section["sources"], self.edges, "conv-0"))

    def test_revoke_any_root_denies_descendants(self):
        artifact = m._learn(self.docs, self.edges, "conv-0")
        with self.assertRaisesRegex(ValueError, "revoked"):
            m.verify_artifact(artifact, self.docs, "conv-0",
                              revoked={self.docs[-1]["id"]})
        with self.assertRaisesRegex(ValueError, "withdrawal"):
            m._learn(self.docs, self.edges, "conv-0", revoked={self.docs[0]["id"]})

    def test_changes_to_source_break_artifact(self):
        artifact = m._learn(self.docs, self.edges, "conv-0")
        docs = copy.deepcopy(self.docs)
        docs[9]["text"] = "drifted source changed after candidate training"
        with self.assertRaisesRegex(ValueError, "mismatched"):
            m.verify_artifact(artifact, docs, "conv-0")
        with self.assertRaisesRegex(ValueError, "mismatched"):
            m.verify_artifact(artifact, self.docs, "conv-1")

    def test_wrong_shape_nonfinite_and_claim_rejected(self):
        artifact = m._learn(self.docs, self.edges, "conv-0")
        for mutation in (
                lambda a: a["parent"].append(0.0),
                lambda a: a["children"]["temporal"].__setitem__(0, float("nan")),
                lambda a: a.__setitem__("production_accepted", True),
                lambda a: a.__setitem__("source_root_count", 1),
                lambda a: a.__setitem__("parent_parameter_touches", 1),
                lambda a: a.__setitem__("extra", "prompt injection")):
            tampered = copy.deepcopy(artifact)
            mutation(tampered)
            with self.assertRaises(ValueError):
                m.verify_artifact(tampered, self.docs, "conv-0")

    def test_unsupported_edge_is_denied(self):
        for bad in (("secret", 0, 1, .5), ("temporal", 0, 200, .5),
                    ("lexical", 1, 1, .5), ("temporal", 0, 1, 2.0)):
            with self.assertRaises(ValueError):
                m._features(self.docs, bad)


class SealedEvolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.prepared, cls.worker = make_dirs(cls.root)
        cls.run_dir = cls.root / "run"
        cls.seal = m.run(cls.worker, cls.run_dir)
        cls.report = m.review(cls.prepared, cls.run_dir, cls.root / "result.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_complete_seven_arm_census_and_adjudication(self):
        report = self.report
        self.assertEqual(self.seal["question_count"], 240)
        self.assertEqual(set(report["by_arm"]), set(m.ARMS))
        self.assertEqual({a: report["by_arm"][a]["reference_questions"] for a in m.ARMS},
                         dict.fromkeys(m.ARMS, 240))
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["trained_memory_content"])
        self.assertFalse(report["learned_graph_topology"])
        self.assertEqual(report["language_answers_generated"], 0)

    def test_artifact_and_predictions_recompute_from_public(self):
        journal = g.strict_load((self.run_dir / "predictions.json").read_bytes())
        self.assertEqual(len(journal["rows"]), 240)
        self.assertEqual(set(journal["artifacts"]),
                         {f"conv-{i}" for i in range(10)})
        self.assertEqual(set(journal["rows"][0]["arms"]), set(m.ARMS))
        self.assertTrue(all(len(ids) == 8 and len(set(ids)) == 8
                            for row in journal["rows"] for ids in row["arms"].values()))

    def test_worker_refuses_hidden_annotations(self):
        with self.assertRaisesRegex(ValueError, "physically absent"):
            m.run(self.prepared, self.root / "must-not-run")

    def test_seal_forgery_and_output_rewrite_fail_closed(self):
        import shutil
        forged = self.root / "forged"
        forged.mkdir()
        for name in ("predictions.json", "seal.json"):
            shutil.copyfile(self.run_dir / name, forged / name)
        original = g.strict_load((forged / "predictions.json").read_bytes())
        original["rows"][0]["arms"]["typed_split"][0] = "D0:99999"
        raw = g.canonical(original)
        (forged / "predictions.json").write_bytes(raw)
        seal = g.strict_load((forged / "seal.json").read_bytes())
        seal["predictions_sha256"] = g.digest(raw)  # attacker can reseal
        (forged / "seal.json").write_bytes(g.canonical(seal))
        with self.assertRaisesRegex(ValueError, "mismatch"):
            m.review(self.prepared, forged, self.root / "forged-report.json")

    def test_private_reference_mutation_is_denied(self):
        prepared = self.root / "tampered-private"
        prepared.mkdir()
        for name in ("public.json", "manifest.json", "private.json"):
            (prepared / name).write_bytes((self.prepared / name).read_bytes())
        p = g.strict_load((prepared / "private.json").read_bytes())
        p["annotations"]["conv-0/q0000"]["evidence"] = ["D0:127"]
        (prepared / "private.json").write_bytes(g.canonical(p))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            m.review(prepared, self.run_dir, self.root / "tampered-report.json")

    def test_no_report_replacement(self):
        with self.assertRaises(FileExistsError):
            m.review(self.prepared, self.run_dir, self.root / "result.json")

    def test_no_public_source_forgery(self):
        altered = self.root / "source-changed"
        altered.mkdir()
        for name in ("public.json", "manifest.json"):
            (altered / name).write_bytes((self.worker / name).read_bytes())
        obj = g.strict_load((altered / "public.json").read_bytes())
        obj["families"][0]["sources"][5]["text"] = "rewritten event"
        (altered / "public.json").write_bytes(g.canonical(obj))
        with self.assertRaises(ValueError):
            m.run(altered, self.root / "altered-run")


if __name__ == "__main__":
    unittest.main()
