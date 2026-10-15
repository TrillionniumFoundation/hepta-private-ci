"""Source-bound stdlib replay of counters and exact frozen sampling identities."""
import copy
import hashlib
import random
import unittest
from group_terminal_receipt_review import replay_terminal_guard


class TerminalGuardReviewTests(unittest.TestCase):
    def fixture(self):
        cases=[dict(case_id=f"train/{i}",source_group=f"group/{i}") for i in range(4)]
        records=[dict(case_id=c["case_id"],source_group=c["source_group"],
                      slots=slots) for c, slots in zip(cases,([0, 2],[0],[1,2,3],[0,1]))]
        p=dict(terminal_guard=True,public_cases={"train":cases},max_depth=4,steps=10,seed=41)
        raw=bytes(int(d>=max(r["slots"])) for r in records for d in range(4))
        g=random.Random(41)
        sample=hashlib.sha256()
        eligible=suppressed=0
        for _ in range(10):
            ids=g.sample(range(4),4)
            dep=g.randint(1,4)
            sample.update(repr((ids,dep)).encode())
            for i in ids:
                for d in range(dep):
                    if d >= max(records[i]["slots"]): eligible+=1
                    else: suppressed+=1
        r=dict(batch_size=4,completed_steps=10,
               terminal_eligibility_sha256=hashlib.sha256(raw).hexdigest(),
               terminal_eligibility_bytes=len(raw),
               sample_and_depth_sha256=sample.hexdigest(),
               terminal_eligible_step_examples=eligible,
               terminal_suppressed_step_examples=suppressed)
        return p, dict(slot_assignments=records),r

    def test_complete_source_and_sampler_replay(self):
        p,t,r=self.fixture()
        out=replay_terminal_guard(p,t,r)
        self.assertEqual(out["eligible"],r["terminal_eligible_step_examples"])
        self.assertEqual(out["suppressed"],r["terminal_suppressed_step_examples"])

    def test_reject_count_hash_and_source_forgery(self):
        p,t,r=self.fixture()
        mutations=(
            lambda p,t,r: r.update(terminal_eligible_step_examples=r["terminal_eligible_step_examples"]+1),
            lambda p,t,r: r.update(terminal_eligibility_sha256="0"*64),
            lambda p,t,r: r.update(sample_and_depth_sha256="f"*64),
            lambda p,t,r: r.update(terminal_eligibility_bytes=1),
            lambda p,t,r: t["slot_assignments"][0].update(slots=[0]),
            lambda p,t,r: t["slot_assignments"][0].update(source_group="forged"),
            lambda p,t,r: p.update(seed=42),
            lambda p,t,r: p.update(terminal_guard=False),
        )
        for mutation in mutations:
            pp,tt,rr=copy.deepcopy((p,t,r))
            mutation(pp,tt,rr)
            with self.subTest(mutation=str(mutation)),self.assertRaises(ValueError):
                replay_terminal_guard(pp,tt,rr)

    def test_reject_missing_slots_and_unordered_evidence(self):
        p,t,r=self.fixture()
        for slots in ([],[-1],[3,1],[4],[True]):
            pp,tt,rr=copy.deepcopy((p,t,r))
            tt["slot_assignments"][0]["slots"]=slots
            with self.subTest(slots=slots),self.assertRaises(ValueError):
                replay_terminal_guard(pp,tt,rr)


if __name__=="__main__":
    unittest.main()
