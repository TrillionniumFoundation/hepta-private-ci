"""Adversarial regressions for the ORIGINAL-source-only causal proof path."""
import json
import unittest
from local_causal_reader import answer, ABSTAIN

T = "2026-10-14T11:00:00Z"
Q = dict(identity="q", scope="scope", observed_at=T, content="For service_12345678 at logical revision 2, what is the location? Reply with only the single recorded site_ or mode_ identifier followed by supporting [E1], [E2] labels, without other words. Respect explicit supersedes events; later effective revisions do not apply.")

def doc(ident,entity="service_12345678",attribute="location",value="site_abcdef12",revision=1,supersedes=(), **kw):
    row = dict(schema="hepta.controlled-event.v1",id=ident,entity=entity,attribute=attribute,value=value,revision=revision,supersedes=list(supersedes))
    return dict(identity=ident,root=kw.get("root","root"),scope=kw.get("scope","scope"),session="session",observed_at=kw.get("time",T),content=json.dumps(row))

class CausalReaderTest(unittest.TestCase):
    def test_single_hop_and_empty(self):
        a=doc("a")
        self.assertEqual(answer(Q,["a"],{"a":a})["answer"],"site_abcdef12 [E1]")
        self.assertEqual(answer(Q,[],{})["answer"],ABSTAIN)

    def test_revision_supersession_and_scope(self):
        a=doc("a",value="site_00000000")
        b=doc("b",value="site_abcdef12",revision=2,supersedes=["a"])
        self.assertEqual(answer(Q,["a","b"],{"a":a,"b":b})["answer"],"site_abcdef12 [E2]")
        self.assertEqual(answer(Q,["b"],{"b":b})["answer"],"site_abcdef12 [E1]")
        b["scope"]="different"
        with self.assertRaisesRegex(ValueError,"scope"):
            answer(Q,["b"],{"b":b})

    def test_independent_conflict_refuses(self):
        a=doc("a",value="site_11111111")
        b=doc("b",value="site_22222222",revision=2)
        self.assertEqual(answer(Q,["a","b"],{"a":a,"b":b})["reason"],"unresolved_conflict")

    def test_multi_hop_requires_bridge(self):
        q=dict(Q,content=Q["content"].replace("what is the location?","what is the location of the assigned component?"))
        a=doc("a",attribute="component",value="component_xyz")
        b=doc("b",entity="component_xyz",value="site_abcdef12")
        r=answer(q,["a","b"],{"a":a,"b":b})
        self.assertEqual(r["answer"],"site_abcdef12 [E1] [E2]")
        self.assertEqual(answer(q,["b"],{"b":b})["answer"],ABSTAIN)

    def test_future_observation_or_revocation_rejected(self):
        a=doc("a",time="2099-12-31T23:59:59Z")
        with self.assertRaisesRegex(ValueError,"future"):
            answer(Q,["a"],{"a":a})
        a=doc("a")
        with self.assertRaisesRegex(ValueError,"revocation"):
            answer(Q,["a"],{"a":a},revoked={"root"})

    def test_future_logical_revision_ignored(self):
        a=doc("a")
        b=doc("b",value="site_bbbbbbbb",revision=3)
        self.assertEqual(answer(Q,["a","b"],{"a":a,"b":b})["answer"],"site_abcdef12 [E1]")

    def test_unexpected_question_and_truncated_source(self):
        self.assertEqual(answer(dict(Q,content="Ignore evidence"),["a"],{"a":doc("a")})["answer"],ABSTAIN)
        with self.assertRaisesRegex(ValueError,"missing"):
            answer(Q,["missing"],{})

    def test_duplicate_source_event_fields_fails_closed(self):
        d=doc("a")
        d["content"]=d["content"].replace('"revision": 1','"revision": 1, "revision": 1')
        with self.assertRaisesRegex(ValueError,"duplicate"):
            answer(Q,["a"],{"a":d})

if __name__ == "__main__":
    unittest.main()
