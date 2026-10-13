"""Source-first packet protects original full-denominator, blinded source-first cases."""
import copy
import unittest
from native import digest
from stem_pairwise_source_first import (
    ORIGINAL_ARMS, SHADOW_ARMS, PHASES,
    build_packet, ZIP_SHA256,
)


def fixture():
    questions={
        'train':[f'train-{j}' for j in range(48)],
        'select':[f'select-{j}' for j in range(8)],
        'retention':[f'retention-{j}' for j in range(8)],
        'test':[f'test-{j}' for j in range(8)],
        'transfer':[f'transfer-{j}' for j in range(8)],
    }
    plan=dict(questions=questions,arms=list(ORIGINAL_ARMS),curriculum_attempted_examples=[16,32,48])
    predictions=[];choices=[];raw=[]
    for stage in (16,32,48):
     for phase in ('select','retention','test','transfer'):
      for qid in questions[phase]:
       q=dict(identity=qid,family='f',scope='scope-'+qid,content='When?',observed_at='2024-01-02T00:00')
       def evid(answer):
        excerpt='baseline' if answer=='frozen' else 'shadow'
        return [dict(label='E1',id='a'*64,root='root',scope=q['scope'],excerpt=excerpt,
                     source_start=0,source_end=len(excerpt.encode()),observed_at='2024-01-01T00:00',inspected_sha256='b'*64)]
       def receipt(answer):
        x=evid(answer)
        return dict(generator_identity='reader',generator_profile='prompt',observable_query=q,
                    question_digest=digest(q),delivered_evidence=x,
                    canonical_request_digest=digest(('reader','prompt',q,x)))
       for arm in ORIGINAL_ARMS:
        row=dict(stage=stage,phase=phase,question_id=qid,arm=arm,cell='general',family='family-'+qid,
                 status='succeeded',selected=0,pool_digest='pool-'+qid,
                 answer='BASE',receipt=receipt('frozen'))
        predictions.append(row)
       for arm in SHADOW_ARMS:
        changed=stage==48 and phase in PHASES and qid.endswith('-0')
        selected=1 if changed else 0
        choices.append(dict(stage=stage,phase=phase,question_id=qid,arm=arm,status='succeeded',
                            pool_digest='pool-'+qid,original_frozen_selected=0,selected=selected,
                            training_labels_or_test_gold_in_answer=False,family='family-'+qid))
        if stage==48 and phase in PHASES:
         raw.append(dict(stage=stage,phase=phase,question_id=qid,arm=arm,status='succeeded',
                         source_family='family-'+qid,source_pool_digest='pool-'+qid,
                         frozen_selected=0,shadow_selected=selected,
                         changed_frozen_selected_source=changed,
                         shadow_fit_or_decision_status='succeeded',
                         native_target_passed_to_generator=False,
                         answer='SHADOW' if changed else 'BASE',
                         receipt=receipt('shadow' if changed else 'frozen')))
    return plan,predictions,choices,raw

class SourceFirstPacketTests(unittest.TestCase):
    def valid(self):return build_packet(*fixture(),zip_sha256=ZIP_SHA256)
    def test_complete_and_stage1_excludes_answers_golds_and_arm_names(self):
        cases,owner,audit=self.valid()
        self.assertEqual(len(cases),16)
        self.assertEqual(len(owner),16)
        self.assertEqual(audit['changed_case_counts'],dict(test=1,transfer=1))
        self.assertEqual(audit['signed_source_sufficiency_verdicts'],0)
        for c in cases:
            self.assertNotIn('answer',c)
            self.assertNotIn('question_id',c)
            self.assertNotIn('arm',c)
            self.assertNotIn('native_source_support',c)
            self.assertIn('excerpt',c['passage_A'])
            self.assertFalse(c['independently_verified_semantics'])
    def test_duplicate_shadow_case_fails_closed(self):
        plan,pol,choice,raw=fixture()
        raw[-1]=copy.deepcopy(raw[0])
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
    def test_tampered_original_prompt_or_question_fails(self):
        plan,pol,choice,raw=fixture()
        raw[0]['receipt']['generator_profile']='wrong'
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
        plan,pol,choice,raw=fixture()
        raw[0]['receipt']['observable_query']['content']='TAMPER'
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
    def test_future_or_bad_original_offsets_fail(self):
        plan,pol,choice,raw=fixture()
        raw[0]['receipt']['delivered_evidence'][0]['source_end']=999
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
        plan,pol,choice,raw=fixture()
        raw[0]['receipt']['delivered_evidence'][0]['observed_at']='2025-01-01T00:00'
        raw[0]['receipt']['canonical_request_digest']=digest(('reader','prompt',raw[0]['receipt']['observable_query'],raw[0]['receipt']['delivered_evidence']))
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
    def test_different_shadow_arms_cannot_silently_collapse(self):
        plan,pol,choice,raw=fixture()
        raw[1]['answer']='OTHER'
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
    def test_hiding_only_chosen_gains_is_rejected(self):
        plan,pol,choice,raw=fixture()
        raw=[x for x in raw if x['changed_frozen_selected_source']]
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)
    def test_case_digest_and_order_reproducible(self):
        a=self.valid();b=self.valid()
        self.assertEqual(a,b)
        self.assertFalse(a[2]['independent_reviewer_identity_verified'])
    def test_duplicate_stage1_id_and_unchanged_answer_integrity(self):
        plan,pol,choice,raw=fixture()
        raw[2]['answer']='UNEXPECTED_CHANGED'
        with self.assertRaises(ValueError):build_packet(plan,pol,choice,raw,zip_sha256=ZIP_SHA256)


if __name__=='__main__':unittest.main()
