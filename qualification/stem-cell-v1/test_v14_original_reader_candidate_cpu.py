"""Original Reader candidate physical path denial tests: never download weights."""
import copy
from hashlib import sha256
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import v14_original_reader_candidate_cpu as candidate
import v14_reader_original_request_builder as source_builder
from test_v14_reader_original_request_builder import original_source_fixture


def material_fixture():
    src = original_source_fixture()
    src['models']['candidate']['weights_sha256'] = candidate.MODEL_SHA
    src['models']['candidate']['tokenizer_sha256'] = candidate.TOKEN_SHA
    src['models']['candidate']['runtime_sha256'] = candidate.file_sha(candidate.runtime_file())
    plan, prompts = source_builder.prepare(src)
    return src, plan, prompts


class RealCandidatePreflight(unittest.TestCase):
    def setUp(self):
        self.src, self.plan, self.private = material_fixture()

    def preflight(self):
        return candidate.check_manifest(self.src, self.plan, self.private)

    def test_original_material_identity_and_request_count(self):
        report, jobs = self.preflight()
        self.assertEqual(len(jobs), 8)
        self.assertEqual(report['case_count'], 2)
        self.assertFalse(report['original_pretrained_reader_executed'])
        self.assertTrue(all(len(x) == 5 for x in jobs))
        self.assertEqual([x[1] for x in jobs[:4]], list(candidate.ARMS))

    def test_missing_original_material_does_not_create_fake_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = []
            for name, value in [('source',self.src),('plan',self.plan),
                                ('private',self.private)]:
                p = root / (name + '.json')
                p.write_text(json.dumps(value, ensure_ascii=False))
                inputs.append(str(p))
            output = root / 'original-answers.json'
            with self.assertRaises(ValueError):
                candidate.run(*inputs, str(root/'missing-real-checkpoint'), output)
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + '.starts.jsonl').exists())

    def test_default_import_never_loads_original_tensors_or_torch(self):
        with subprocess.Popen([
            sys.executable, '-c',
            "import sys, v14_original_reader_candidate_cpu; "
            "assert 'torch' not in sys.modules; "
            "assert 'safetensors' not in sys.modules"
        ], cwd=str(Path(candidate.__file__).resolve().parent)) as process:
            self.assertEqual(process.wait(), 0)

    def test_unpinned_model_identity_denied(self):
        self.plan['models']['candidate']['weights_sha256'] = sha256(b'fake').hexdigest()
        with self.assertRaises(ValueError):
            self.preflight()

    def test_unpinned_original_tokenizer_denied(self):
        self.plan['models']['candidate']['tokenizer_sha256'] = sha256(b'wrong').hexdigest()
        with self.assertRaises(ValueError):
            self.preflight()

    def test_wrong_original_runtime_denied(self):
        self.plan['models']['candidate']['runtime_sha256'] = sha256(b'replaced').hexdigest()
        with self.assertRaises(ValueError):
            self.preflight()

    def test_input_prompt_rewrite_is_detected(self):
        self.private['requests']['question-0']['sufficient']['raw_original_model_input'] = 'fake'
        with self.assertRaises(ValueError):
            self.preflight()

    def test_different_question_text_rejected(self):
        self.src['cases'][0]['question'] += ' malicious appendix'
        with self.assertRaises(ValueError):
            self.preflight()

    def test_more_than_24_output_tokens_rejected(self):
        self.src['max_output_tokens'] = 25
        self.plan, self.private = source_builder.prepare(self.src)
        with self.assertRaises(ValueError):
            self.preflight()

    def test_65_source_cases_do_not_fall_through_into_unsupported_batch(self):
        seed = copy.deepcopy(self.src['cases'][0])
        self.src['cases'] = []
        for k in range(65):
            item = copy.deepcopy(seed)
            item['id'] = 'question-large-' + str(k)
            self.src['cases'].append(item)
        self.plan, self.private = source_builder.prepare(self.src)
        with self.assertRaises(ValueError):
            self.preflight()

    def test_model_root_requires_pinned_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                candidate.pin_original_material(directory)

    def test_existing_or_symlink_private_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'immutable'
            target.write_text('registered original')
            with self.assertRaises(FileExistsError):
                candidate.open_private_once(target)
            self.assertEqual(target.read_text(), 'registered original')
            alias = Path(tmp)/'alias'
            alias.symlink_to(target)
            with self.assertRaises(FileExistsError):
                candidate.open_private_once(alias)

    def test_private_original_file_creation_is_exclusive_mode_0600(self):
        import stat
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'trace.json'
            with candidate.open_private_once(path) as file:
                file.write('{}')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                candidate.open_private_once(path)

    def test_private_scope_never_becomes_full_two_reader_evaluation(self):
        s = inspect.getsource(candidate)
        self.assertNotIn('model_selected = True', s)
        self.assertNotIn('production_authorized": True', s)
        self.assertTrue(candidate.OUTPUT_SCHEMA.endswith('.original-candidate-physical-partial.v1'))


if __name__ == '__main__':
    unittest.main()
