"""Pure original-source cue and early-failure admission tests (no fake HF)."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from amcn_real_hf_smoke import freeze_cues, run_original_hf


def sample(i):
    return {'sample_id': f'conversation-{i}',
            'qa': [{'question': f'When was event {i}?', 'answer':'hidden', 'evidence':['D1:2']}],
            'conversation': {'session_1': [{'speaker':'A', 'text':f'Source {i}',
                                           'dia_id':'D1:1'}]}}


class OriginalHfAdmission(unittest.TestCase):
    def test_ten_immutable_source_families_are_label_blind(self):
        data=[sample(i) for i in range(10)]
        first=freeze_cues(data)
        self.assertEqual(len(first),10)
        self.assertEqual(len({r['source_family_sha256'] for r in first}),10)
        mutated=deepcopy(data)
        mutated[0]['qa'][0]['answer']='changed'
        mutated[0]['qa'][0]['evidence']=['new evidence']
        self.assertEqual(first,freeze_cues(mutated))

    def test_duplicate_family_fails_before_model(self):
        data=[sample(i) for i in range(10)];data[9]['sample_id']=data[0]['sample_id']
        with self.assertRaises(ValueError): freeze_cues(data)

    def test_absent_source_fails_before_model(self):
        data=[sample(i) for i in range(10)];data[1]['conversation']['session_1']=[]
        with self.assertRaises(ValueError): freeze_cues(data)

    def test_unstaged_encoder_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                run_original_hf(Path(root)/'not-a-model',Path(root)/'missing',Path(root)/'out')
            self.assertFalse((Path(root)/'out').exists())


if __name__ == '__main__': unittest.main()
