"""Independent V14 original prompt replay negative and source-only fixtures."""
import copy
from hashlib import sha256
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import v14_reader_original_request_review as r
import v14_reader_original_request_builder as b
from test_v14_reader_original_request_builder import original_source_fixture


def h(value):
    return sha256(value.encode()).hexdigest()


class IndependentOriginalRequestReview(unittest.TestCase):
    def setUp(self):
        self.src = original_source_fixture()
        self.plan, self.private = b.prepare(self.src)

    def check(self):
        return r.review(self.src, self.plan, self.private)

    def reject(self, mutation):
        mutation()
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.check()

    def test_all_original_prompt_bytes_independently_reproduced(self):
        actual = self.check()
        self.assertEqual(actual['case_count'], 2)
        self.assertEqual(actual['recomputed_actual_four_arm_prompts'], 8)
        self.assertTrue(actual['source_replay_equal'])
        self.assertFalse(actual['original_source_owner_authenticated'])
        self.assertFalse(actual['original_pretrained_reader_executed'])
        self.assertFalse(actual['model_selection_authorized'])
        self.assertEqual(actual['decision'], 'HOLD_NO_GO')

    def test_independent_implementation_never_imports_producer(self):
        source = inspect.getsource(r)
        self.assertNotIn('import v14_reader_original_request_builder', source)
        with subprocess.Popen(
            [sys.executable, '-c',
             "import sys; import v14_reader_original_request_review; "
             "assert 'v14_reader_original_request_builder' not in sys.modules"],
            cwd=str(Path(r.__file__).resolve().parent)
        ) as child:
            self.assertEqual(child.wait(), 0)

    def test_changed_original_evidence_bytes(self):
        self.reject(lambda: self.src['cases'][0]['sources'][0].update(text='forged'))

    def test_changed_original_question(self):
        self.reject(lambda: self.src['cases'][0].update(question='different'))

    def test_changed_source_membership(self):
        self.reject(lambda: self.src['cases'][0]['arms']['sufficient'].reverse())

    def test_changed_source_family(self):
        self.reject(lambda: self.src['cases'][0].update(family='foreign-family'))

    def test_wrong_model_runtime(self):
        self.reject(lambda: self.src['models']['candidate'].update(runtime_sha256=h('foreign')))

    def test_wrong_objective_or_token_budget(self):
        self.reject(lambda: self.src.update(max_output_tokens=12))

    def test_changed_plan_question_digest(self):
        self.reject(lambda: self.plan['cases'][0].update(question_sha256=h('wrong')))

    def test_changed_plan_request_digest(self):
        self.reject(lambda: self.plan['cases'][0]['arms']['none'].update(
            request_sha256=h('different')))

    def test_changed_private_prompt(self):
        self.reject(lambda: self.private['requests']['question-0']['none'].update(
            raw_original_model_input='fabrication'))

    def test_changed_private_source_text(self):
        self.reject(lambda: self.private['requests']['question-0']['sufficient']
                    ['delivered_evidence'][0].update(text='other'))

    def test_private_claimed_model_execution_is_forbidden(self):
        self.reject(lambda: self.private.update(model_executed=True))

    def test_private_gold_exposure_is_forbidden(self):
        self.reject(lambda: self.private.update(publisher_gold_available=True))

    def test_unregistered_original_answer_is_forbidden(self):
        self.reject(lambda: self.src['cases'][0].update(gold_answer='known'))

    def test_missing_private_arm_is_rejected(self):
        self.reject(lambda: self.private['requests']['question-0'].pop('lesion'))

    def test_duplicate_private_original_case_is_rejected(self):
        self.reject(lambda: self.private['requests'].update(fake=self.private['requests']['question-0']))

    def test_no_original_peer_or_eval_auth_is_claimed(self):
        outcome = self.check()
        self.assertFalse(outcome['evidence_sufficiency_independently_verified'])
        self.assertFalse(outcome['production_authorized'])

    def test_independent_cli_preserves_source_free_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            files = []
            for obj, name in [(self.src, 'src.json'), (self.plan, 'plan.json'),
                              (self.private, 'prompts.json')]:
                file = folder / name
                file.write_text(json.dumps(obj, ensure_ascii=False))
                files.append(str(file))
            proc = subprocess.run([
                sys.executable, str(Path(r.__file__)),
                '--source', files[0], '--plan', files[1],
                '--private-requests', files[2]],
                capture_output=True, text=True, check=True)
            out = json.loads(proc.stdout)
            self.assertEqual(out['recomputed_actual_four_arm_prompts'], 8)
            self.assertNotIn('raw_original_model_input', proc.stdout)
            self.assertFalse(out['production_authorized'])


if __name__ == '__main__':
    unittest.main()
