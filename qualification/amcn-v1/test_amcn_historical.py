"""Three-stage original-model input/score contracts (fixtures, not model wins)."""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from amcn_core import Evidence, Refused, digest
from amcn_native import build_inputs
from amcn_source_first import lexical_shortlist
from amcn_historical_trial import (
    CORPUS, GENERATION, PROFILE, SCOPE, read_bounded,
    score_only_after_seal, write_once,
)


def evidence(label, text):
    return Evidence(label, "locomo:fixture", SCOPE, 1, text,
                    sha256(text.encode()).hexdigest(), GENERATION)


def fixture(root):
    question = "Which database deadlock caused the rollback?"
    a = evidence("ev-a", "Database transaction deadlock rollback.")
    b = evidence("ev-b", "Weather sunshine lake.")
    c = evidence("ev-c", "Database connection pooling.")
    d = evidence("ev-d", "Private unrelated household note.")
    evidences = (a, b, c, d)
    candidates = lexical_shortlist(question, list(evidences),
                                   scope=SCOPE, generation=GENERATION, top_k=4)
    srcmap = {x.evidence_id: x for x in evidences}
    rows = [{
        "row_id": digest(["fixture-q", sid, "future_a"]),
        "question_id": "fixture-q",
        "question": question, "family": "test-family",
        "split": "future_a", "evidence": asdict(srcmap[sid])
    } for sid in candidates["ranked_source_ids"]]
    public = {
        "schema": PROFILE + ".public.v2", "dataset_sha256": CORPUS,
        "source_first_shortlists": {"fixture-q": candidates},
        "rows": rows,
    }
    support = ["ev-a"]
    labels = {
        "schema": PROFILE + ".withheld.v2",
        "source_first_plan_sha256": digest(public["source_first_shortlists"]),
        "publisher_support": {"fixture-q": support},
        "row_labels": {r["row_id"]: int(r["evidence"]["evidence_id"] in support)
                       for r in rows},
    }
    records = [{
        "row_id": r["row_id"], "question": r["question"],
        "family": r["family"], "split": r["split"],
        "evidence": srcmap[r["evidence"]["evidence_id"]],
    } for r in rows]
    _, cases = build_inputs(records, scope=SCOPE, generation=GENERATION)
    answers = [{
        "row_id": r["row_id"], "split": r["split"],
        "family": r["family"], "input_sha256": cases[i].input_digest,
        "frozen_relevance": float(r["evidence"]["evidence_id"] == "ev-b") * .8 + .1,
        "trained_relevance": float(r["evidence"]["evidence_id"] == "ev-a") * .8 + .1,
    } for i, r in enumerate(rows)]
    seal = root / "sealed"
    seal.mkdir()
    model = b"fixture-safetensor-header-not-a-pretrained-model"
    (seal / "semantic-head.safetensors").write_bytes(model)
    receipt = {
        "schema": "hepta.amcn.real-head-candidate.v1",
        "prediction_digest": digest(answers),
        "head_tensor_sha256": sha256(model).hexdigest(),
        "source_manifest_sha256": digest([
            (r["row_id"], r["evidence"]["content_sha256"],
             r["evidence"]["source_root"]) for r in rows]),
        "production_accepted": False,
    }
    write_once(root / "public.json", public)
    write_once(root / "gold.json", labels)
    write_once(seal / "sealed-predictions.json", answers)
    write_once(seal / "candidate-receipt.json", receipt)
    return root / "public.json", root / "gold.json", seal, candidates


class HistoricalScoreTests(unittest.TestCase):
    def test_source_first_labels_open_after_prediction_seal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public, withheld, sealed, plan = fixture(root)
            result = score_only_after_seal(public, withheld, sealed,
                                           root / "score.json")
            self.assertFalse(result["production_accepted"])
            m = result["metrics"]
            self.assertTrue(m["supports_selected_without_labels"])
            self.assertEqual(m["full_Reader_responses"], 0)
            self.assertEqual(m["true_future_calendar_windows"], 0)
            self.assertEqual(m["publisher_weak_support_source_first"]
                             ["source_first_lexical_top1_weak_support"]["questions"], 1)
            self.assertEqual(m["publisher_weak_support_source_first"]
                             ["trained_top1_weak_support"]["hits"], 1)
            self.assertEqual(m["publisher_weak_support_source_first"]
                             ["frozen_top1_weak_support"]["hits"], 0)
            self.assertEqual(m["publisher_weak_support_source_first"]
                             ["trained_top1_weak_support"]["questions"], 1)
            self.assertEqual(read_bounded(root / "score.json"), result)
            with self.assertRaises(FileExistsError):
                score_only_after_seal(public, withheld, sealed, root / "score.json")

    def test_zero_label_support_not_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            public, withheld, sealed, _=fixture(root)
            gold=read_bounded(withheld)
            gold["publisher_support"]["fixture-q"]=[]
            gold["row_labels"]={rid:0 for rid in gold["row_labels"]}
            withheld.unlink()
            write_once(withheld,gold)
            result=score_only_after_seal(public,withheld,sealed,root/"score.json")
            self.assertEqual(result["metrics"]["zero_support_cases"],1)
            self.assertEqual(result["metrics"]["publisher_weak_support_source_first"]
                             ["trained_top1_weak_support"]["hits"],0)
            self.assertFalse(result["production_accepted"])

    def test_changed_sources_seals_labels_and_new_score_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            fixture(root)
            cases=("modified_labels", "changed_plan",
                   "changed_original_prediction", "changed_model_file")
            for name in cases:
                with self.subTest(name=name):
                    with tempfile.TemporaryDirectory() as subdir:
                        r=Path(subdir)
                        p,g,s,_=fixture(r)
                        files={"modified_labels":g,"changed_plan":p,
                               "changed_original_prediction":s/"sealed-predictions.json",
                               "changed_model_file":s/"semantic-head.safetensors"}
                        target=files[name]
                        if name=="modified_labels":
                            self.change_json(target,lambda x:
                                x["row_labels"].__setitem__(
                                    next(iter(x["row_labels"])),9))
                        elif name=="changed_plan":
                            self.change_json(target,lambda x:
                                x["source_first_shortlists"]["fixture-q"].__setitem__(
                                    "labels_accessed",True))
                        elif name=="changed_original_prediction":
                            self.change_json(target,lambda x:
                                x[0].__setitem__("trained_relevance",.75))
                        else: target.write_bytes(b"tampered")
                        with self.assertRaises(Refused):
                            score_only_after_seal(p,g,s,r/"score.json")
                        self.assertFalse((r/"score.json").exists())

    @staticmethod
    def change_json(path, mutate):
        value=read_bounded(path)
        mutate(value)
        path.unlink()
        write_once(path,value)


if __name__ == "__main__":
    unittest.main()
