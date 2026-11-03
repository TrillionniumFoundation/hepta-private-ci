"""Tamper and exact pinned-archive tests for the model-free MemoryCell verifier."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import memorycell_strong_rag_exact_replay as audit

MODEL = Path('/mnt/data/hepta-strong-rag-11743043427.zip')
SOURCE = Path('/mnt/data/event-inputs-20261010.zip')


class StrongRagExactReplayTests(unittest.TestCase):
    def test_full_real_readonly_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'evidence.json'
            audit.main(MODEL,SOURCE,dest)
            receipt=json.loads(dest.read_text())
            self.assertEqual((receipt['calibration_rows_verified'],receipt['evaluation_rows_verified']), (40,72))
            self.assertEqual(receipt['manifest_members_checked'],78)
            self.assertEqual(receipt['replayed_program_probes'],28)
            self.assertEqual(receipt['matched_prompt_pairs'],39)
            self.assertEqual(receipt['calibration_top_k'],1)
            self.assertEqual(receipt['evaluation']['organized']['strict_correct'],8)
            self.assertEqual(receipt['evaluation']['organized']['correct_with_full_program_declared_citations'],4)
            self.assertFalse(receipt['production_accepted'])

    def test_bad_generated_outer_zip_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tampered.zip'
            buf=MODEL.read_bytes()
            path.write_bytes(buf[:-1]+bytes([buf[-1]^1]))
            with self.assertRaises(AssertionError):
                audit.verify_zip(path,audit.MODEL_ZIP,43)

    def test_wrong_original_zip_pin_fails_closed(self):
        with self.assertRaises(AssertionError):
            audit.verify_zip(SOURCE,'0'*64,35)

    def test_duplicate_json_or_nan_fails_closed(self):
        for raw in (b'{"q":1,"q":2}',b'{"q":NaN}',b'{"q":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                audit.strict_json(raw)

    def test_only_registered_strict_grammar_can_score(self):
        self.assertIsNotNone(audit.RESPONSE.fullmatch('site_abcdef12 [E1]'))
        for answer in ('site_abcdef12 and site_12345678','site_abcdef12 [E0]','result: site_abcdef12','mode_abcdef1','site_abcdef12 [E1] arbitrary'):
            with self.subTest(answer=answer):
                self.assertIsNone(audit.RESPONSE.fullmatch(answer))

    def test_forged_scored_outcome_is_rejected(self):
        with zipfile.ZipFile(MODEL) as z:
            prep=audit.strict_json(z.read('prep/calibration-plan.json'))
            raw=[audit.strict_json(line) for line in z.read('calibration/raw-answers.jsonl').splitlines()]
            scored=audit.strict_json(z.read('calibration/scored-answers.json'))
            labels=audit.strict_json(z.read('prep/calibration-labels.json'))
        with zipfile.ZipFile(SOURCE) as z:
            src=audit.strict_json(z.read('plan/source-view.json'))
        by_id={d['identity']:d for d in src}
        scored[0]['strict_task_success']=not scored[0]['strict_task_success']
        with self.assertRaises(AssertionError):
            audit.compare_rows(raw,scored,prep['cases'],labels,by_id,'calibration',None,None)


if __name__=='__main__':
    unittest.main()
