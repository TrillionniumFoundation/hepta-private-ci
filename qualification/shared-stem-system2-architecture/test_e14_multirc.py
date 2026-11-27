"""E14 real-model pre-score and independently owned-label forensic regressions.

The optional ORIGINAL archive is required by the hosted workflow and is
provided via HEPTA_E14_ARCHIVE. Without it source-only tests still run.
"""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction as F
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from e14_multirc_route import (ARCHIVE_SHA, ARMS, POLICIES, CUT, read_prelabel,
                               positive, law_from_prob, strict_json, write_once,
                               build_rows, produce)
from e14_multirc_score import (original_labels, decode_cert, historical_owner_score,
                               source_verified_score, score, VAL_SHA)
from e12_independent_audit import audit
from e12_nonlinear_cert import Law

ARCHIVE = os.environ.get('HEPTA_E14_ARCHIVE')


class E14Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = ARCHIVE if ARCHIVE and Path(ARCHIVE).exists() else None

    def require_original(self):
        if not self.archive:
            self.skipTest('original real-model artifact not supplied locally')
        return self.archive

    def test_01_exact_source_historical(self):
        a = self.require_original()
        self.assertEqual(sha256(Path(a).read_bytes()).hexdigest(), ARCHIVE_SHA)
        o = read_prelabel(a)
        self.assertEqual((o['passage_count'],o['question_count'],o['actual_candidate_count']), (4, 8, 33))

    def test_02_original_prelabel_member_allowlist(self):
        a = self.require_original()
        original = ZipFile.read
        seen = []
        def recording(inst,name,*args,**kwargs):
            seen.append(name)
            return original(inst,name,*args,**kwargs)
        from unittest.mock import patch
        with patch.object(ZipFile,'read',recording):
            read_prelabel(a)
        self.assertEqual(set(seen), {'multirc-native-candidate-audit/audit.json',
                                     'multirc-native-candidate-audit/COMMITTED.json'})
        self.assertFalse(any('score' in name.lower() or 'label' in name.lower() for name in seen))

    def test_03_noncanonical_and_nonfinite_json(self):
        for b in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'', b'{}'*(1100000)):
            with self.subTest(b=b[:20]), self.assertRaises(ValueError):
                strict_json(b)

    def test_04_cross_source_model_mutation_reject(self):
        a=self.require_original()
        with tempfile.TemporaryDirectory() as td:
            with ZipFile(a) as inp, ZipFile(Path(td)/'mutated.zip','w',ZIP_DEFLATED) as out:
                for info in inp.infolist():
                    data=inp.read(info.filename)
                    if info.filename=='multirc-native-candidate-audit/audit.json':
                        original=json.loads(data)
                        original['predictions']['conditioned'][0]['logits'][0]+=1
                        data=json.dumps(original).encode()
                    out.writestr(info.filename,data)
            altered=str(Path(td)/'mutated.zip')
            with self.assertRaises(ValueError):
                read_prelabel(altered)
            # Even a test-specific alternate outer digest cannot override
            # pre-score source owner seal or semantic original case IDs.
            with self.assertRaises(ValueError):
                read_prelabel(altered,required_sha=sha256(Path(altered).read_bytes()).hexdigest())

    def test_05_score_only_bytes_not_read_by_prelabel(self):
        a=self.require_original()
        with tempfile.TemporaryDirectory() as td:
            altered=Path(td)/'owner-score-altered.zip'
            with ZipFile(a) as inp,ZipFile(altered,'w',ZIP_DEFLATED) as out:
                for info in inp.infolist():
                    raw=inp.read(info.filename)
                    if info.filename=='multirc-native-candidate-scores/scores.json':
                        raw=b'{"malicious_label":1}'
                    out.writestr(info.filename,raw)
            self.assertRaises(ValueError, read_prelabel, str(altered))  # original outer checksum
            # Test-injected alternate outer hash leaves the BLIND source
            # identity unchanged despite altered post-label score bytes.
            obs=read_prelabel(str(altered),required_sha=sha256(altered.read_bytes()).hexdigest())
            self.assertEqual(len(obs['rows']),33)

    def test_06_real_model_input_geometry(self):
        o=read_prelabel(self.require_original())
        self.assertEqual(set(o['predictions']),set(ARMS))
        self.assertEqual(len({(r['source_group'],r['question_slot']) for r in o['rows']}),8)
        self.assertFalse(o['evaluation_labels_loaded'])

    def test_07_bounded_pretrained_probabilities(self):
        self.assertGreater(positive([-2.0,2.0]),.98)
        self.assertLess(positive([2.0,-2.0]),.02)
        for p in (0.0,.001,.5,.999,1.0):
            self.assertTrue(-2 <= F(law_from_prob(p).x0) <= 2)
        for p in (float('nan'),float('inf'),-1.,2.,True):
            with self.assertRaises(ValueError):
                law_from_prob(p)

    def test_08_real_e12_complete_original_prefixes(self):
        o=read_prelabel(self.require_original())
        row=build_rows(o)[0]
        from e12_nonlinear_cert import Solve,Trace,State
        t=row['cert']['trace']
        cert=Solve(**{**row['cert'],'trace':Trace(tuple(State(**s) for s in t['states']),tuple(t['z']))})
        report=audit(Law(**row['law']),cert)
        self.assertTrue(report.certified)
        self.assertFalse(report.natural_task_improvement_proven)

    def test_09_complete_pre_score_research(self):
        a=self.require_original()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'prediction.json'
            digest=produce(a,str(out))
            self.assertEqual(sha256(out.read_bytes()).hexdigest(),digest)
            rows=json.loads(out.read_bytes())['rows']
            self.assertEqual(len(rows),33)
            self.assertEqual(sum(r['policy_arms']['cheap_one_map']=='mean_pool_query_fused' for r in rows),15)
            self.assertEqual(sum(r['policy_arms']['e12_full_tree']=='mean_pool_query_fused' for r in rows),9)
            self.assertEqual(sum(r['policy_arms']['cheap_one_map']!=r['policy_arms']['e12_full_tree'] for r in rows),6)
            self.assertRaises(FileExistsError,produce,a,str(out))

    def test_10_fixed_action_profile(self):
        self.assertEqual(CUT,F(9,100))
        self.assertEqual(POLICIES,ARMS+('fixed_confidence','cheap_one_map','e12_full_tree'))

    def test_11_owner_original_summary_not_authorizer(self):
        a=self.require_original()
        owner=historical_owner_score(a)
        self.assertEqual(owner['results']['conditioned']['correct'],16)
        self.assertEqual(owner['results']['mean_pool_query_fused']['correct'],17)
        self.assertEqual(owner['results']['no_evidence']['correct'],16)
        self.assertEqual(owner['results']['no_query']['correct'],19)
        self.assertFalse(owner['production_authorized'])

    def test_12_missing_human_truth_fails_closed(self):
        a=self.require_original()
        o=read_prelabel(a)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'proposals.json';produce(a,str(out))
            proposal=strict_json(out.read_bytes())
            with self.assertRaises(ValueError):
                source_verified_score(proposal,o,{},historical_owner_score(a))
            proposal['original_labels_accessed']=True
            with self.assertRaises(ValueError):
                source_verified_score(proposal,o,{},historical_owner_score(a))

    def test_13_original_task_id_reconstruction_rejects_synthetic_relabel(self):
        # 4 groups x 2 questions; original arbitrary human labels. No real
        # score is asserted in this separately invented synthetic fixture.
        raw=[];candidates=[]
        for g in range(4):
            paragraph=f'held evidence for synthetic passage {g}'
            psha=sha256(json.dumps(paragraph,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            source=sha256(f'validation:passage:{g}:{psha}'.encode()).hexdigest()[:32]
            for question in range(2):
                for ans in range(4 if (g,question)!=(0,0) else 5):
                    cid=ans+1000*g+100*question
                    task=sha256(f'{source}:q{question}:a{cid}'.encode()).hexdigest()[:32]
                    candidates.append(dict(task_id=task,source_group=source,question_slot=question,
                                           candidate_id=cid,original_v1_candidate=ans==0))
                    raw.append(dict(paragraph=paragraph,question=f'question {question}',answer=f'answer {ans}',
                                    label=ans%2,idx=dict(paragraph=g,question=question,answer=cid)))
        self.assertEqual(len(raw),33)
        got=original_labels(raw,candidates)
        self.assertEqual(len(got),33)
        raw[0]['label']=2
        with self.assertRaises(ValueError):original_labels(raw,candidates)

    def test_14_missing_group_or_duplicate_source_reject(self):
        with self.assertRaises(ValueError):original_labels([],[])
        with self.assertRaises(ValueError):original_labels([{}],[{}]*33)

    def test_15_result_promotion_never_from_archive(self):
        owner=historical_owner_score(self.require_original())
        self.assertFalse(owner['independent_test_quality_established'])
        self.assertFalse(owner['official_multirc_score_established'])
        self.assertFalse(owner['production_authorized'])


if __name__=='__main__':unittest.main()
