"""Stdlib independent operation/slot provenance test for TRAIN-only research."""
import copy
import unittest

from group_attention_slot_review import _public_ops, digest, review_train_slots


class OperationSlotReviewTests(unittest.TestCase):
    def example(self):
        # Intentionally shuffled 4-edge dependency; final answer is in fact
        # index 0, not the fourth row or fourth scheduled operation.
        text = ("Start at n0 and follow every link. What is the endpoint class? Answer one of A B C D E F G H.\n"
                "n4 has class B.\n"
                "n2 links to n3.\n"
                "n0 links to n1.\n"
                "n3 links to n4.\n"
                "n1 links to n2.")
        import hashlib, json
        facts = [("label","n4","B"),("link","n2","n3"),("link","n0","n1"),
                 ("link","n3","n4"),("link","n1","n2")]
        source = hashlib.sha256(json.dumps(["dependency",("follow","n0"),
            sorted(facts)],separators=(",",":")).encode()).hexdigest()
        case = dict(case_id="train/"+source[:20], source_group=source,
                    family="dependency", text=text)
        ops = [("follow_edge",2),("follow_edge",4),("follow_edge",1),
               ("follow_edge",3),("read_terminal_label",0)]
        row = dict(case_id=case["case_id"], source_group=source,
                   family="dependency", operations=[name for name,_ in ops],
                   evidence_indices=[i for _,i in ops], slots=[0,0,1,2,3])
        receipt = dict(schema="hepta.group.train-attention-binding.v2",
                       authority="DENY_ALL",train_only=True,
                       slot_assignments=[row],slot_assignment_sha256=digest([row]),
                       total_teacher_steps=5,supervised_steps=5,truncated_teacher_steps=0,
                       coalesced_teacher_steps=1,supervised_slots=4,
                       terminal_evidence_supervised_cases=1)
        return case, receipt

    def test_shuffled_long_path_terminal_label_recovered(self):
        case, receipt = self.example()
        data = review_train_slots([case],receipt,4)
        self.assertEqual(data["operations"],5)
        self.assertTrue(data["terminal_evidence_preserved"])
        self.assertEqual(_public_ops(case)[-1],("read_terminal_label",0))

    def test_reject_rehashed_truncation_and_terminal_substitution(self):
        case, original = self.example()
        for edit in ("drop_terminal","wrong_fact","wrong_slot","coverage"):
            row = copy.deepcopy(original)
            if edit == "drop_terminal":
                row["slot_assignments"][0]["operations"].pop()
                row["slot_assignments"][0]["evidence_indices"].pop()
                row["slot_assignments"][0]["slots"].pop()
            elif edit == "wrong_fact":
                row["slot_assignments"][0]["evidence_indices"][-1] = 3
            elif edit == "wrong_slot":
                row["slot_assignments"][0]["slots"][-1] = 2
            else:
                row["supervised_steps"] = 4
            row["slot_assignment_sha256"] = digest(row["slot_assignments"])
            with self.subTest(edit=edit),self.assertRaises(ValueError):
                review_train_slots([case],row,4)

    def test_reject_unbound_source_and_nontrain_schema(self):
        case, receipt = self.example()
        modified = copy.deepcopy(case)
        modified["source_group"] = "f"*64
        with self.assertRaises(ValueError):
            review_train_slots([modified],receipt,4)
        untrusted = copy.deepcopy(receipt)
        untrusted["train_only"] = False
        with self.assertRaises(ValueError):
            review_train_slots([case],untrusted,4)


if __name__ == "__main__":
    unittest.main()
