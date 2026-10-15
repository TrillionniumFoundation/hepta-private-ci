import copy
import json
import unittest
from pathlib import Path
from amcn_reader_capacity_denial import check

DATA = json.loads(Path(__file__).with_name("ORIGINAL_READER_CAPACITY_24_64_NEGATIVE.json").read_text())

class NegativeControls(unittest.TestCase):
    def test_original_denied(self):
        self.assertFalse(check(DATA)["production_accepted"])
    def test_reader_swap(self):
        x=copy.deepcopy(DATA);x["real_original_reader_model_sha256"]="0"*64
        with self.assertRaises(ValueError):check(x)
    def test_omitted_call(self):
        x=copy.deepcopy(DATA);x["actual_original_64_reader_calls"]=15
        with self.assertRaises(ValueError):check(x)
    def test_missing_prefix(self):
        x=copy.deepcopy(DATA);x["paired_original_24_64_greedy_prefix_equal_calls"]=15
        with self.assertRaises(ValueError):check(x)
    def test_fabricated_success(self):
        x=copy.deepcopy(DATA);x["independent_semantic_task_success"]=1
        with self.assertRaises(ValueError):check(x)
    def test_gold_selection_hidden(self):
        x=copy.deepcopy(DATA);x["original_publisher_answer_selection_uses_gold"]=False
        with self.assertRaises(ValueError):check(x)
    def test_cost_tamper(self):
        x=copy.deepcopy(DATA);x["publisher_annotated_witness"]["generated_64"]=100
        with self.assertRaises(ValueError):check(x)
    def test_fake_hf_verification(self):
        x=copy.deepcopy(DATA);x["official_HF_operator_parity_verified"]=True
        with self.assertRaises(ValueError):check(x)
    def test_fake_future(self):
        x=copy.deepcopy(DATA);x["true_future_calendar_windows"]=2
        with self.assertRaises(ValueError):check(x)

if __name__=="__main__":unittest.main()
