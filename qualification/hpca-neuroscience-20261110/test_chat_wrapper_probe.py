import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parent))
import chat_wrapper_probe as p

class Stub:
    chat_template = "on"
    eos_token_id = 2
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        assert tokenize and add_generation_prompt
        assert len(messages)==1 and messages[0]["role"]=="user"
        return [1,101,102]
    def __call__(self, text, add_special_tokens):
        return {"input_ids":[1,99]}

class TestWrapper(unittest.TestCase):
    def test_frozen_roster(self):
        q=json.loads((p.ROOT/"CHAT_WRAPPER_PLAN.json").read_text())
        b=json.loads((p.ROOT/"BASE_OUTPUT_PLAN.json").read_text())
        d=json.loads((p.ROOT/"HPCA_V2_OOD_PLAN.json").read_text())
        self.assertEqual(len(p.validate_roster(q,b,d)),24)
    def test_reject_changed_plan(self):
        q=json.loads((p.ROOT/"CHAT_WRAPPER_PLAN.json").read_text())
        b=json.loads((p.ROOT/"BASE_OUTPUT_PLAN.json").read_text())
        d=json.loads((p.ROOT/"HPCA_V2_OOD_PLAN.json").read_text())
        q["task_plan_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"task plan changed"):
            p.validate_roster(q,b,d)
    def test_reject_added_system_arm(self):
        q=json.loads((p.ROOT/"CHAT_WRAPPER_PLAN.json").read_text())
        b=json.loads((p.ROOT/"BASE_OUTPUT_PLAN.json").read_text())
        d=json.loads((p.ROOT/"HPCA_V2_OOD_PLAN.json").read_text())
        q["arm"]="system_few_shot_prompt"
        with self.assertRaisesRegex(ValueError,"unregistered prompt"):
            p.validate_roster(q,b,d)
    def test_question_content_unchanged(self):
        self.assertEqual(p.messages({"question":" Is 2+2=4?  "}),
                         [{"role":"user","content":"Is 2+2=4?\nAnswer:"}])
    def test_has_real_chat_wrapper(self):
        self.assertEqual(p.encode(Stub(),{"question":"Q?"}),[1,101,102])
    def test_missing_chat_template_rejected(self):
        t=Stub()
        t.chat_template=None
        with self.assertRaisesRegex(ValueError,"missing"):
            p.encode(t,{"question":"Q?"})
    def test_ended_chat_header_rejected(self):
        class Bad(Stub):
            def apply_chat_template(self,*a,**k):return [1,2]
        with self.assertRaisesRegex(ValueError,"assistant prefix"):
            p.encode(Bad(),{"question":"Q?"})
    def test_missing_wrapper_rejected(self):
        class Bad(Stub):
            def apply_chat_template(self,*a,**k):return [1,99]
        with self.assertRaisesRegex(ValueError,"not applied"):
            p.encode(Bad(),{"question":"Q?"})
    def test_parser_is_leading_and_standalone(self):
        for v in (" yes ","NO.","No:","YES\n"):
            self.assertIsNotNone(p.parse_answer(v))
        for v in ("","yesterday","yes12","maybe yes","no_more","<|im_end|>"):
            self.assertIsNone(p.parse_answer(v))
if __name__=="__main__":
    unittest.main()
