"""Separately sealed source-first original LoCoMo diagnostic negative contracts."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from hashlib import sha256

import amcn_original_locomo_trial as mod


class OriginalLoCoMoSourceSealing(unittest.TestCase):
    def test_canonical_serialization_and_create_only(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'sealed.json'
            mod.sealed_write(path,{'a':1,'z':False})
            raw=path.read_bytes()
            self.assertEqual(raw,mod.canonical({'z':False,'a':1})+b'\n')
            with self.assertRaisesRegex(ValueError,'create-only'):
                mod.sealed_write(path,{'z':True})

    def test_exact_external_sha_and_duplicate_json_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.json'
            path.write_text('{"a":1,"a":2}')
            pin=sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'duplicate JSON'):
                mod.open_pinned(path,pin)
            with self.assertRaisesRegex(ValueError,'external exact source SHA'):
                mod.open_pinned(path,'0'*64)

    def test_independent_gold_plan_binding_refuses_swapped_trials(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            answer={"schema":mod.PROFILE+'.raw-model-answers.v1',
               "public_file_sha256":"a"*64,"public_payload_sha256":"b"*64,
               "model_answers_generated":1,"production_accepted":False,
               "gold_opened_during_model_execution":False,
               "cases":[{"case_id":"q1","family":"f1","source_ids":["x"],
                         "raw_answer":"wrong answer", "raw_answer_sha256":sha256(b'wrong answer').hexdigest(),
                         "reached_output_ceiling":True}]}
            golden={"schema":mod.PROFILE+'.withheld-publisher-gold.v1',
               "public_payload_sha256":"c"*64,
               "gold_cases":[{"case_id":"q1","family":"f1","publisher_answer":"right answer",
                             "publisher_evidence":["x"]}]}
            a,g=d/'answer.json',d/'gold.json'
            mod.sealed_write(a,answer);mod.sealed_write(g,golden)
            with self.assertRaisesRegex(ValueError,'publisher answer/public plan drift'):
                mod.descriptive_score(a,mod.file_sha(a),g,mod.file_sha(g),d/'score.json')
            self.assertFalse((d/'score.json').exists())

    def test_score_preserves_failed_literal_answer_and_weak_support_only(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            gold={"schema":mod.PROFILE+'.withheld-publisher-gold.v1',
                  "public_payload_sha256":"b"*64,
                  "gold_cases":[{"case_id":"q1","family":"f1","publisher_answer":"May 2023",
                                 "publisher_evidence":["D1:3"]}]}
            answer={"schema":mod.PROFILE+'.raw-model-answers.v1',
                "public_payload_sha256":"b"*64,"model_answers_generated":1,
                "production_accepted":False,"gold_opened_during_model_execution":False,
                "cases":[{"case_id":"q1","family":"f1","source_ids":["D1:3"],
                          "raw_answer":"Evidence date May 2023 [E1]",
                          "raw_answer_sha256":sha256(b'Evidence date May 2023 [E1]').hexdigest(),
                          "reached_output_ceiling":False}]}
            a,g=d/'answers.json',d/'publisher.json'
            mod.sealed_write(a,answer);mod.sealed_write(g,gold)
            summary=mod.descriptive_score(a,mod.file_sha(a),g,mod.file_sha(g),d/'scored.json')
            self.assertEqual(summary['literal_exact_matches'],0)
            self.assertEqual(summary['weak_evidence_recovered_questions'],1)
            self.assertIsNone(summary['independent_semantic_success_metric'])
            self.assertFalse(summary['production_accepted'])

    def test_bm25_cannot_consume_gold_labels(self):
        rows=[{'id':'a','text':'Alice discussed adoption agencies.'},
              {'id':'b','text':'The weather is sunny.'}]
        out=mod.bm25('What did Alice research about adoption agencies?',rows)
        self.assertEqual([x['id'] for x in out],['a','b'])

    def test_unknown_gold_fields_rejected_before_any_reader_call(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'public.json'
            mod.sealed_write(path,{'schema':mod.PROFILE+'.public.v1',
                 'original_dataset_sha256':mod.CORPUS_SHA256,
                 'training_labels_or_publisher_gold_present':False,
                 'original_calendar_future_windows':0,'cases':[],
                 'top_k':3,'publisher_gold_ans':'leak'})
            with patch.object(mod,'ArchivedLlama') as physical:
                with self.assertRaisesRegex(ValueError,'unexpected gold/source fields'):
                    mod.generate(path,mod.file_sha(path),Path(d),'output.json')
                physical.assert_not_called()


if __name__=='__main__':unittest.main()
