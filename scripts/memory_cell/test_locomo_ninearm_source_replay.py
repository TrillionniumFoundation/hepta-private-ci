"""Provenance and process-isolation tests; no model accuracy claims."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

import locomo_ninearm_source_replay as study

ROOT = Path(os.getenv("HEPTA_LOCOMO_NINEARM_ROOT", "/mnt/data"))
PUBLIC = ROOT / "public"
SELECTION = ROOT / "selection"
EVALUATION = ROOT / "evaluation"
EXISTING = ROOT / "result"


class FrozenSourceOnlyReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PUBLIC.is_dir() and SELECTION.is_dir() and EVALUATION.is_dir() and EXISTING.is_dir()):
            if os.getenv("HEPTA_LOCOMO_NINEARM_ROOT"):
                raise ValueError("CI must provide full exact pinned archive cohort")
            raise unittest.SkipTest("full pinned archive cohort required")
        cls.public, cls.docs = study.load_public(PUBLIC)
        cls.rows = study.compute(cls.public, cls.docs)

    def test_all_720_decisions_recover_original_480_exactly(self):
        self.assertEqual(len(self.rows), 720)
        self.assertEqual(study.verify_original_six(PUBLIC, self.rows), 480)
        self.assertEqual(study.sha(b''.join(study.canonical(x)+b'\n' for x in self.rows)),
                         'd3c09d944f5bfc855056d109fa0cc379a9a2dc11a3e628556af0448f8be82197')

    def test_selection_only_frozen_arm_and_honest_heldout(self):
        policy = study.strict_json((EXISTING / 'policy.json').read_bytes())
        report = study.strict_json((EXISTING / 'report.json').read_bytes())
        self.assertEqual(policy['selected_arm'], 'lexical_k8')
        self.assertEqual(report['selected_arm'], 'lexical_k8')
        self.assertEqual(report['evaluation']['lexical_k8']['full_annotated_support_covered'], 9)
        self.assertEqual(report['evaluation']['lexical_k4']['full_annotated_support_covered'], 8)
        self.assertEqual(report['evaluation']['fusion_k8']['full_annotated_support_covered'], 3)
        self.assertEqual(report['models_generated'], 0)
        self.assertFalse(report['production_accepted'])
        self.assertFalse(report['independent_source_family_authentication'])

    def test_all_six_source_archive_outer_sha_pins(self):
        for name in study.ZIPS:
            root = PUBLIC if name in ('public','decisions') else SELECTION if name == 'selection' else EVALUATION
            self.assertTrue(study.read_zip(root, name))

    def test_public_and_selection_are_physically_gold_free(self):
        study.check_roles(PUBLIC, SELECTION, EVALUATION)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for p in PUBLIC.iterdir():
                shutil.copyfile(p, root / p.name)
            shutil.copyfile(SELECTION / study.ZIPS['selection'][0], root / study.ZIPS['selection'][0])
            with self.assertRaisesRegex(ValueError, 'premature private'):
                study.check_roles(root)

    def test_alias_or_wrong_target_role_rejected(self):
        with self.assertRaises(ValueError):
            study.check_roles(PUBLIC, PUBLIC)
        with self.assertRaises(ValueError):
            study.check_roles(PUBLIC, EVALUATION)

    def test_checksum_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p in PUBLIC.iterdir():
                shutil.copyfile(p, root/p.name)
            altered=root/study.ZIPS['public'][0]
            altered.write_bytes(altered.read_bytes()+b'x')
            with self.assertRaisesRegex(ValueError, 'external ZIP pin'):
                study.read_zip(root, 'public')

    def test_forged_journal_rejected_even_when_receipt_digest_rehashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            for name in ('decisions.jsonl','receipt.json'):
                shutil.copyfile(EXISTING/name, output/name)
            rows=[study.strict_json(x) for x in (output/'decisions.jsonl').read_bytes().splitlines()]
            rows[0]['selected'].reverse()
            raw=b''.join(study.canonical(x)+b'\n' for x in rows)
            (output/'decisions.jsonl').write_bytes(raw)
            receipt=study.strict_json((output/'receipt.json').read_bytes())
            receipt['raw_journal_sha256']=study.sha(raw)
            (output/'receipt.json').write_bytes(study.canonical(receipt)+b'\n')
            with self.assertRaisesRegex(ValueError, 'posthoc retrieval'):
                study.checked_decisions(PUBLIC, output)

    def test_forged_policy_rejected_before_heldout_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            for name in ('decisions.jsonl','receipt.json','policy.json'):
                shutil.copyfile(EXISTING/name, output/name)
            p=study.strict_json((output/'policy.json').read_bytes())
            p['selected_arm']='fusion_k8'
            (output/'policy.json').write_bytes(study.canonical(p)+b'\n')
            with self.assertRaisesRegex(ValueError, 'policy selection'):
                study.evaluate(PUBLIC, SELECTION, EVALUATION, output)

    def test_eligibility_missing_support_counts_unknown(self):
        public={'splits':{'evaluation':[{'question_id':'q','source_ids':['a'], 'family_proxy_digest':'F'}]}}
        decisions=[{'question_id':'q','arm':arm,'selected':['a'], 'selected_source_bytes':20} for arm in study.ARMS]
        cases={'q':dict(support=['b'],unanswerable=False,unresolved_support=[],answer='x')}
        result=study.scores(public,decisions,'evaluation',cases)
        self.assertTrue(all(v['eligible']==0 and v['unknown_or_unanswerable']==1 and v['annotated_support_outside_original_pool']==1 for v in result.values()))

    def test_no_immutable_output_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sealed.json';study.write_new(p,b'{}\n')
            with self.assertRaises(ValueError):study.write_new(p,b'changed')


if __name__ == '__main__':
    unittest.main()
