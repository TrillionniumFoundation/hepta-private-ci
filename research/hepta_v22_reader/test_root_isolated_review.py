"""No-network root-disjoint blinded review tests; no actual human rating."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

import source_first as v17
import v19_qwen_reference as qwen
import blinded_sufficiency as v21
import root_isolated_review as v22
from test_blinded_sufficiency import make_fixture


class RootExposureTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir=Path(tmp.name)
        self.src,self.ref,self.plan=make_fixture(self.dir)
        fake=patch.object(qwen,'validate',return_value=self.plan)
        fake.start();self.addCleanup(fake.stop)
        self.intake=self.dir/'private-v21'
        self.review=self.dir/'private-v22'
        v21.prepare(self.src,self.ref,self.intake,blinding_key=bytes(range(32)))

    def make(self):return v22.prepare(self.intake,self.review)
    def files(self):return (self.intake/'blinded-private.json',self.intake/'identity-private.json',self.intake/'observation-sanitized.json')

    def test_every_ticket_twice_each_slot_root_unique(self):
        receipt=self.make()
        self.assertEqual(receipt['distinct_tickets'],96)
        self.assertEqual(receipt['reviewer_exposures'],192)
        self.assertEqual(receipt['max_per_source_root_per_slot'],1)
        self.assertEqual(sum(receipt['reviewer_packet_counts']),192)
        self.assertTrue(v22.verify_private(self.intake,self.review)['root_isolation_verified'])

    def test_reviewer_cannot_see_two_arms_of_same_root(self):
        self.make()
        plan=v17.read(self.review/'owner-assignment-private.json')
        for slot in range(plan['slots']):
            ts=[tid for tid,pair in plan['assignments'].items() if slot in pair]
            roots=[plan['root_by_ticket'][tid] for tid in ts]
            self.assertEqual(len(roots),len(set(roots)))
        for slots in plan['assignments'].values():
            self.assertEqual(len(slots),2)
            self.assertNotEqual(*slots)

    def test_no_original_arm_source_label_or_key_in_review_packet(self):
        self.make()
        private=v17.read(self.intake/'identity-private.json')
        for file in (self.review/'reviewer-slots').iterdir():
            obj=v17.read(file)
            self.assertEqual(set(obj),{'schema','source_owner_sha256','reviewer_slot','tickets',
                                       'gold_answers_or_model_outputs_included',
                                       'other_policy_variants_included',
                                       'human_reviewer_identity_authenticated','authority'})
            for t in obj['tickets']:
                self.assertEqual(set(t),{'ticket_id','ticket_sha256','question','evidence'})
                self.assertNotIn(private['raw_blinding_key_hex'],str(t))

    def test_no_pretend_human_review(self):
        rec=self.make()
        self.assertFalse(rec['actual_human_reviews_received'])
        self.assertFalse(rec['independent_reviewer_identities_verified'])
        self.assertFalse(rec['evidence_sufficiency_certified'])
        self.assertFalse(rec['reader_semantic_accuracy_verified'])
        self.assertEqual(rec['model_pretrained_forwards_this_step'],0)
        self.assertEqual(v22.verify_public(self.review/'observation-sanitized.json')['independent_human_reviews'],0)

    def test_cannot_create_existing_folder(self):
        self.make()
        with self.assertRaisesRegex(ValueError,'create-only'):self.make()

    def test_cannot_accept_public_private_ticket_or_roster(self):
        (self.intake/'blinded-private.json').chmod(0o644)
        with self.assertRaises(ValueError):self.make()

    def test_re_sign_reviewer_packet_still_invalid(self):
        self.make()
        path=self.review/'reviewer-slots'/'slot-00.json'
        packet=v17.read(path)
        packet['tickets'][0]['question']='mutated privately'
        path.write_bytes(v17.canon(packet));path.chmod(0o600)
        digest=v17.digest(packet)
        public=self.review/'observation-sanitized.json'
        row=v17.read(public);row['packet_digests'][0]=digest
        public.write_bytes(v17.canon(row));public.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'changed'):v22.verify_private(self.intake,self.review)

    def test_reject_duplicate_tickets_or_forged_source_claim(self):
        self.make()
        plan_path=self.review/'owner-assignment-private.json'
        plan=v17.read(plan_path)
        one=next(iter(plan['assignments']))
        plan['assignments'][one]=[0,0]
        plan_path.write_bytes(v17.canon(plan));plan_path.chmod(0o600)
        with self.assertRaises(ValueError):v22.verify_private(self.intake,self.review)

    def test_reject_new_review_packet_extra_arm(self):
        self.make()
        packet_path=self.review/'reviewer-slots'/'slot-00.json'
        packet=v17.read(packet_path)
        packet['tickets'].append(packet['tickets'][0])
        packet_path.write_bytes(v17.canon(packet));packet_path.chmod(0o600)
        with self.assertRaises(ValueError):v22.verify_private(self.intake,self.review)

    def test_reject_false_human_review_claim_even_resigned(self):
        self.make()
        p=self.review/'observation-sanitized.json'
        r=v17.read(p);r['actual_human_reviews_received']=True
        p.write_bytes(v17.canon(r));p.chmod(0o600)
        with self.assertRaises(ValueError):v22.verify_public(p)
        with self.assertRaises(ValueError):v22.verify_private(self.intake,self.review)

    def test_cannot_reuse_blinding_key_to_mix_source_roots(self):
        roster, identity, receipt=(v17.read(p) for p in self.files())
        vals=list(identity['logical_to_ticket'])
        a,b=vals[0],next(s for s in vals if s.split('/')[0]!=vals[0].split('/')[0])
        identity['logical_to_ticket'][b]=identity['logical_to_ticket'][a]
        with self.assertRaisesRegex(ValueError,'cross-root alias'):
            v22.derive(roster,identity,receipt)

    def test_source_root_unique_capacity_is_hard_bounded(self):
        roster,ident,receipt=(v17.read(p) for p in self.files())
        # With unchanged real-census geometry, a 12-slot plan cannot isolate
        # two raters for every >=9-ticket root; no relaxation or duplicate slot.
        with patch.object(v22, 'MAX_SLOTS', 12):
            with self.assertRaisesRegex(ValueError,'capacity'):
                v22.derive(roster,ident,receipt)

    def test_empty_or_extra_slot_file_fails(self):
        self.make()
        extra=self.review/'reviewer-slots'/'forged-private.json'
        v17.write_once(extra,{'fake':True})
        with self.assertRaises(ValueError):v22.verify_private(self.intake,self.review)

    def test_source_only_code_no_torch(self):
        import sys
        self.assertNotIn('torch',sys.modules)
        self.make()
        self.assertNotIn('transformers',sys.modules)
        self.assertNotIn('torch',sys.modules)


if __name__=='__main__':unittest.main()
