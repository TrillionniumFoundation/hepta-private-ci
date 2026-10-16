"""No-network V21 evidence custody/adjudication tests. All model values fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import source_first as v17
import v19_qwen_reference as qwen
import blinded_sufficiency as v21


def make_fixture(root):
    public=[];entries={};cases=[]
    for fid in v17.ROOTS:
        docs=[dict(id=f'{fid}-e{j}',speaker='Person',text=f'Verified note {j} in {fid}.')
              for j in range(5)]
        qs=[]
        for q in range(3):
            cid=f'{fid}/q{q}';cases.append(cid)
            question=f'What happened in {fid} event {q}?'
            qs.append(dict(id=cid,question=question))
            refs_by_arm=dict(none=[],retrieved=[docs[0]['id'],docs[1]['id']],
                             annotated=[docs[2]['id']],
                             lesion=[] if len(cases)<=24 else [docs[3]['id']])
            for arm,ids in refs_by_arm.items():
                # Only 24 aliases across the complete original panel.
                messages=qwen.message(question,ids,{x['id']:x for x in docs})
                rid=f'{cid}|{arm}'
                entries[rid]=dict(case_id=cid,arm=arm,source_ids=ids,
                                  messages=messages,message_sha256=v17.digest(messages),
                                  question_sha256=v17.sha_text(question))
        public.append(dict(id=fid,questions=qs,utterances=docs))
    owner=dict(schema=v17.SCHEMA+'.owner',public_sha256=v17.digest(public),
               hidden_sha256='h'*64,authority='DENY_ALL',production_accepted=False)
    plan=dict(cases=cases,entries=entries,plan_sha256=v17.digest('plan-source-fixture'),
              publisher_answer_labels_not_exposed=True,production_authorized=False,
              decision='HOLD_NO_GO')
    files=(root/'public.json',root/'owner.json',root/'plan.json',root/'annotation.json',root/'requests.json')
    for p,data in zip(files,(public,owner,{}, {}, {})):
        v17.write_once(p,data)
    qref=root/'qwen-plan.json';v17.write_once(qref,plan)
    return files,qref,plan


class V21Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.inputs,self.reference,self.plan=make_fixture(self.root)
        self.patcher=patch.object(qwen,'validate',return_value=self.plan)
        self.fake_validate=self.patcher.start();self.addCleanup(self.patcher.stop)
        self.target=self.root/'private-review'

    def make(self,**kwargs):
        return v21.prepare(self.inputs,self.reference,self.target,
                           blinding_key=kwargs.get('key',b'\x07'*32))

    def private(self):
        return [self.target/x for x in ('blinded-private.json','identity-private.json',
                                         'observation-sanitized.json')]

    def test_full_source_first_blinded_contract(self):
        result=self.make()
        self.assertEqual((result['original_source_roots'],result['original_questions']), (10,30))
        self.assertEqual((result['logical_evidence_requests'],result['distinct_evidence_tickets']), (120,96))
        self.assertEqual(result['aliases_reused'],24)
        self.assertFalse(result['gold_or_reader_answers_in_packet'])
        self.assertEqual(result['original_pretrained_model_calls'],0)
        self.assertEqual(result['decision'],'HOLD_NO_GO')
        self.assertEqual(v21.validate_private(*self.private())['tickets'],96)
        self.assertEqual(self.target.stat().st_mode & 0o777,0o700)
        for p in self.private():self.assertEqual(p.stat().st_mode & 0o777,0o600)

    def test_private_packet_has_no_gold_or_model_or_arm_label(self):
        self.make();r=v17.read(self.private()[0]);i=v17.read(self.private()[1])
        self.assertEqual(len(r['tickets']),96)
        for t in r['tickets'].values():
            self.assertEqual(set(t),{'ticket_id','ticket_sha256','question','evidence'})
            self.assertNotIn('answer',t)
            self.assertNotIn('model',t)
            self.assertNotIn('arm',t)
        self.assertEqual(set(i['logical_to_ticket']),set(self.plan['entries']))

    def test_public_gitsafe_receipt_verified_without_private_tickets(self):
        self.make()
        r=v21.verify_public_receipt(self.private()[2])
        self.assertEqual(r['distinct_tickets'],96)
        self.assertFalse(r['external_review_complete'])

    def test_public_receipt_cannot_claim_model_or_human_success(self):
        self.make();src=self.private()[2]
        for key,value in [('human_reviewer_results_received',True),
                          ('gold_or_reader_answers_in_packet',True),
                          ('original_pretrained_model_calls',1),
                          ('production_authorized',True),
                          ('decision','GO')]:
            data=v17.read(src);data[key]=value
            forged=self.root/('bad-'+key+'.json');v17.write_once(forged,data)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'nonpublic'):
                v21.verify_public_receipt(forged)

    def test_order_independent_ticket_byte_seal(self):
        original=self.make();r=v17.read(self.private()[0])
        self.assertEqual(original['sealed_private_roster_sha256'],v17.digest(r))
        self.assertEqual(len({v['ticket_sha256'] for v in r['tickets'].values()}),96)

    def test_cannot_overwrite_durable_custody(self):
        self.make()
        with self.assertRaisesRegex(ValueError,'must not exist'):self.make()

    def test_missing_owner_file_denied(self):
        self.inputs[1].unlink()
        with self.assertRaisesRegex(ValueError,'missing'):self.make()

    def test_unlabelled_model_entry_rejects_hidden_file(self):
        v17.write_once(self.root/'hidden.json',{'gold':'secret'})
        with self.assertRaisesRegex(ValueError,'publisher gold'):self.make()
        self.assertFalse(self.target.exists())

    def test_unlabelled_model_entry_rejects_symlink_gold(self):
        (self.root/'hidden.json').symlink_to('missing.json')
        with self.assertRaisesRegex(ValueError,'publisher gold'):self.make()

    def test_unlabelled_model_entry_rejects_model_output(self):
        v17.write_once(self.root/'qwen-physical-private.json',{'output':'secret'})
        with self.assertRaisesRegex(ValueError,'model outputs'):self.make()

    def test_reject_unauthorized_reference_plan(self):
        self.plan=copy.deepcopy(self.plan);self.plan['production_authorized']=True
        self.fake_validate.return_value=self.plan
        with self.assertRaisesRegex(ValueError,'owner/plan'):self.make()

    def test_reject_changed_original_question_bytes(self):
        public=v17.read(self.inputs[0]);public[0]['questions'][0]['question']='Injected replacement'
        self.inputs[0].write_bytes(v17.canon(public))
        owner=v17.read(self.inputs[1]);owner['public_sha256']=v17.digest(public)
        self.inputs[1].write_bytes(v17.canon(owner))
        with self.assertRaisesRegex(ValueError,'citation content changed'):self.make()

    def test_source_messages_with_rehashed_fake_source_ids_denied(self):
        self.plan=copy.deepcopy(self.plan)
        bad=self.plan['entries'][next(iter(self.plan['entries']))]
        bad['source_ids']=['unrecognized-source']
        self.fake_validate.return_value=self.plan
        with self.assertRaisesRegex(ValueError,'citation address absent'):self.make()

    def test_foreign_messages_with_resigned_hash_denied(self):
        self.plan=copy.deepcopy(self.plan)
        row=self.plan['entries'][next(iter(self.plan['entries']))]
        row['messages'][0]['content']='Rewritten instruction'
        row['message_sha256']=v17.digest(row['messages'])
        self.fake_validate.return_value=self.plan
        with self.assertRaisesRegex(ValueError,'citation content changed'):self.make()

    def test_missing_or_duplicate_alias_denied(self):
        self.plan=copy.deepcopy(self.plan)
        self.plan['entries'].pop(next(iter(self.plan['entries'])))
        self.fake_validate.return_value=self.plan
        with self.assertRaisesRegex(ValueError,'incomplete'):self.make()

    def test_cross_workspace_source_substitution_denied(self):
        other=self.root/'other';other.mkdir()
        wrong=other/'owner.json';wrong.write_bytes(self.inputs[1].read_bytes())
        self.inputs=(self.inputs[0],wrong,*self.inputs[2:])
        with self.assertRaisesRegex(ValueError,'one immutable directory'):self.make()

    def test_blinding_key_must_not_be_low_entropy(self):
        with self.assertRaisesRegex(ValueError,'256 bits'):self.make(key=b'tiny')

    def test_mutated_private_ticket_with_regenerated_digest_still_denied(self):
        self.make()
        tpath,_,opath=self.private()
        r=v17.read(tpath)
        tid=next(iter(r['tickets']))
        r['tickets'][tid]['evidence'].append(dict(source_id='forged',speaker='forged',excerpt='forged'))
        r['tickets'][tid]['ticket_sha256']=v17.digest({'question':r['tickets'][tid]['question'],
                                                         'evidence':r['tickets'][tid]['evidence']})
        tpath.write_bytes(v17.canon(r));tpath.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'forged review material'):v21.validate_private(*self.private())

    def test_fake_model_gain_in_sanitized_receipt_denied(self):
        self.make();p=self.private()[2];d=v17.read(p)
        d['model_improvement_verified']=True
        p.write_bytes(v17.canon(d));p.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'forged review'):v21.validate_private(*self.private())

    def test_reviewer_shadow_agreement_never_certifies_human(self):
        self.make();roster=v17.read(self.private()[0]);hash_=v17.digest(roster)
        reviews=[]
        for who in ('reviewer-A','reviewer-B'):
            row=dict(schema=v21.SCHEMA+'.unsigned-review-input',roster_sha256=hash_,
                     reviewer_id=who,authority='DENY_ALL',verdicts={
                      tid:dict(ticket_sha256=t['ticket_sha256'],sufficiency='sufficient')
                      for tid,t in roster['tickets'].items()})
            target=self.root/(who+'.json');v17.write_once(target,row);reviews.append(target)
        report=v21.reconcile_shadow_reviews(self.private()[0],reviews[0],reviews[1],self.root/'report.json')
        self.assertEqual(report['source_blind_agreed_sufficient'],96)
        self.assertIs(report['evidence_sufficiency_certified'],False)
        self.assertIs(report['independent_reviewer_identity_cryptographically_verified'],False)
        self.assertFalse(report['production_authorized'])

    def test_undocumented_review_fields_rejected(self):
        self.make();r=v17.read(self.private()[0]);hash_=v17.digest(r)
        files=[]
        for reviewer_id in ('A','B'):
            row=dict(schema=v21.SCHEMA+'.unsigned-review-input',roster_sha256=hash_,
                     reviewer_id=reviewer_id,authority='DENY_ALL',verdicts={
                        k:dict(ticket_sha256=v['ticket_sha256'],sufficiency='indeterminate')
                        for k,v in r['tickets'].items()})
            row['independently_certified_by_me']=True
            p=self.root/(reviewer_id+'.json');v17.write_once(p,row);files.append(p)
        with self.assertRaisesRegex(ValueError,'unregistered reviewer'):
            v21.reconcile_shadow_reviews(self.private()[0],*files,self.root/'out.json')

    def test_duplicate_reviewer_claim_denied(self):
        self.make();r=v17.read(self.private()[0]);hash_=v17.digest(r)
        files=[]
        for _ in (1,2):
            row=dict(schema=v21.SCHEMA+'.unsigned-review-input',roster_sha256=hash_,
                     reviewer_id='same',authority='DENY_ALL',verdicts={
                        k:dict(ticket_sha256=v['ticket_sha256'],sufficiency='indeterminate')
                        for k,v in r['tickets'].items()})
            p=self.root/('reviewer'+str(len(files))+'.json');v17.write_once(p,row);files.append(p)
        with self.assertRaisesRegex(ValueError,'same reviewer'):
            v21.reconcile_shadow_reviews(self.private()[0],*files,self.root/'out.json')

    def test_no_torch_or_transformers_imported_by_prelabel(self):
        import sys
        self.assertNotIn('torch',sys.modules)
        self.assertNotIn('transformers',sys.modules)
        self.make()
        self.assertNotIn('torch',sys.modules)
        self.assertNotIn('transformers',sys.modules)


if __name__=='__main__':unittest.main()
