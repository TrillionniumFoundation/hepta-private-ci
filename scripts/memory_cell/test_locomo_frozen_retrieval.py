"""Synthetic source-only LoCoMo tests; fixture results are NOT model evidence."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import locomo_frozen_retrieval as m


@dataclass(frozen=True)
class Document:
    identity: str
    root: str
    scope: str
    session: str
    observed_at: str
    content: str
    assets: tuple = ()


def fixture():
    docs, splits, targets = [], {s: [] for s in m.SPLITS}, {}
    for family_id in range(10):
        scope = f"locomo:family_{family_id:02}"
        split = "train" if family_id < 6 else "selection" if family_id < 8 else "evaluation"
        family_docs = []
        for j in range(9):
            d = Document(f"{scope}/D1:{j}", f"root-{scope}", scope, "session_1",
                         "2026-01-01T00:00:00Z",
                         (f"Person{family_id} favorite park place{family_id} "
                          if j == 0 else f"Person{family_id} other history {j}"))
            docs.append(d)
            family_docs.append(d)
        ids = sorted(d.identity for d in family_docs)
        census = [(d.identity, d.root, d.observed_at,
                   m.sha256(d.content.encode()).hexdigest())
                  for d in sorted(family_docs, key=lambda x: x.identity)]
        for j in range(8):
            qid = f"{scope}/q{j}"
            splits[split].append(dict(
                dataset="locomo", family_proxy_digest=m.digest([scope]),
                native_family=scope, observation_time="2026-01-01T00:00:00Z",
                question=f"Where is Person{family_id} favorite park place{family_id}?",
                question_id=qid, scope=scope,
                source_ids=ids, source_census_sha256=m.digest(census),
                source_roots_digest=m.digest([f"root-{scope}"]),
            ))
            targets[qid] = dict(answer=f"UNPUBLISHED_GOLD_{qid}",
                                support=[family_docs[0].identity], category="1",
                                unanswerable=False, unresolved_support=[])
    public = dict(schema=m.PROFILE, source_sha256={"locomo":m.SOURCE_SHA},
                  generating_source_commit="a"*40,
                  model_input_contains_answers=False,
                  production_accepted=False,
                  census=dict(split_family_proxies=dict(train=6,selection=2,evaluation=2)),
                  splits=splits)
    return public, docs, targets


class FrozenLoCoMoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / "public"
        self.public.mkdir()
        self.population, self.docs, self.targets = fixture()
        original = sys.modules.get("evidence_bundle")
        fake = types.ModuleType("evidence_bundle")
        fake.observed_time = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))
        sys.modules["evidence_bundle"] = fake
        def restore():
            if original is None:
                sys.modules.pop("evidence_bundle", None)
            else:
                sys.modules["evidence_bundle"] = original
        self.addCleanup(restore)
        m.write_once(self.public / "population.json", m.canonical(self.population) + b"\n")

    def stage(self):
        orig = self.root / "fake-source.json"
        orig.write_text("EXACT_PIN_AUTHORIZED_FAKE", encoding="utf-8")
        fake = types.ModuleType("native")
        fake.load = lambda *args, **kwargs: types.SimpleNamespace(documents=self.docs)
        with patch.dict(sys.modules, {"native": fake}):
            return m.stage(self.public, orig)

    def retrieval(self):
        self.stage()
        fake = types.ModuleType("evidence_bundle")
        fake.observed_time = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))
        with patch.dict(sys.modules, {"evidence_bundle": fake}):
            return m.retrieve(self.public, self.root / "retrieved")

    def selection_targets(self):
        chosen = {x["question_id"] for x in self.population["splits"]["selection"]}
        p = self.root / "selection-targets.json"
        m.write_once(p, m.canonical({k:v for k,v in self.targets.items() if k in chosen})+b"\n")
        return p

    def evaluation_targets(self):
        chosen = {x["question_id"] for x in self.population["splits"]["evaluation"]}
        p = self.root / "evaluation-targets.json"
        m.write_once(p, m.canonical({k:v for k,v in self.targets.items() if k in chosen})+b"\n")
        return p

    def test_precommitted_original_census_all_ten_families(self):
        entries = m._documents(self.population, self.docs)
        self.assertEqual(len(entries), 90)
        self.assertEqual(m._population(self.population)[1], set(self.targets))

    def test_public_history_excludes_private_targets(self):
        self.stage()
        blob=(self.public / "histories.jsonl").read_bytes()
        self.assertNotIn(b"UNPUBLISHED_GOLD_", blob)
        self.assertEqual(len(blob.splitlines()), 90)
        self.assertEqual(m.read_public(self.public)[2]["target_file_in_reader_inputs"], False)

    def test_all_eighty_questions_and_six_frozen_conditions(self):
        receipt=self.retrieval()
        self.assertEqual(receipt["planned_questions"], 80)
        self.assertEqual(receipt["planned_arms"], 6)
        self.assertEqual(len((self.root/"retrieved/decisions.jsonl").read_bytes().splitlines()), 480)
        self.assertFalse(receipt["labels_opened"])
        self.assertEqual(receipt["model_generations"], 0)

    def test_selection_then_evaluation_in_separate_scoring_inputs(self):
        self.retrieval()
        selection=m.score_selection(self.public, self.root/"retrieved",
                                    self.selection_targets(), self.root/"chosen.json")
        self.assertIn(selection["selection_arm"], m.ARMS)
        self.assertFalse(selection["heldout_labels_opened"])
        result=m.score_evaluation(self.public, self.root/"retrieved",
                                  self.root/"chosen.json", self.evaluation_targets(),
                                  self.root/"evaluated.json")
        self.assertEqual(result["frozen_choice_on_evaluation"]["planned"], 16)
        self.assertEqual(result["model_answers_generated"], 0)
        self.assertFalse(result["production_accepted"])

    def test_source_content_or_census_tamper_reject(self):
        bad=list(self.docs)
        bad[0]=Document(**(bad[0].__dict__|{"content":"CHANGED"}))
        with self.assertRaises(ValueError):
            m._documents(self.population,bad)
        good=self.stage()
        content=(self.public/"histories.jsonl").read_bytes().replace(b"other history",b"other HISTORY",1)
        (self.public/"histories.jsonl").write_bytes(content)
        with self.assertRaises(ValueError):
            m.read_public(self.public)

    def test_unsafe_root_or_question_leak_fails(self):
        bad=json.loads(json.dumps(self.population))
        bad["splits"]["evaluation"][0]["family_proxy_digest"]=bad["splits"]["train"][0]["family_proxy_digest"]
        with self.assertRaises(ValueError):
            m._population(bad)
        d=self.docs[0]
        bad_doc=dict(d.__dict__, answer="PRIVATE_TARGET_NEVER_PUBLIC")
        with self.assertRaises(ValueError):
            m._documents(self.population, [bad_doc]+self.docs[1:])

    def test_retrieval_journal_forgery_rejected_before_opening_gold(self):
        self.retrieval()
        p=self.root/"retrieved/decisions.jsonl"
        with p.open("ab") as f:
            f.write(b'{"invalid":true}\n')
        with self.assertRaises(ValueError):
            m.score_selection(self.public, self.root/"retrieved",
                              self.root/"not-present-gold.json",self.root/"chosen.json")

    def test_selection_process_rejects_evaluation_gold(self):
        self.retrieval()
        with self.assertRaisesRegex(ValueError, "wrong private target partition"):
            m.score_selection(self.public,self.root/"retrieved",self.evaluation_targets(),
                              self.root/"chosen.json")

    def test_duplicate_json_nonfinite_and_overwrite_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"v":NaN}'):
            with self.assertRaises(ValueError):
                m.strict_json(raw)
        m.write_once(self.root/"once",b"x")
        with self.assertRaises(FileExistsError):
            m.write_once(self.root/"once",b"x")


if __name__ == "__main__":
    unittest.main()
