"""Recovery fixtures are not pretrained results or evidence of model ability."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import five_causal_experiments as c
import question_relevance_trial as trial
import relevance_recovery as r


def journal(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = '0' * 64
    with path.open('xb') as stream:
        for row in rows: previous = c.journal_append(stream, row, previous)


def optim_rows(units=14, epochs=8, open_tail=False):
    rows=[]
    for epoch in range(epochs):
        for index in range(units):
            rows.append(dict(event='optimizer_started',epoch=epoch,index=index))
            rows.append(dict(event='optimizer_finished',epoch=epoch,index=index,
                             observed_decoder_forwards=4 if index==13 else 8))
    if open_tail: rows.append(dict(event='optimizer_started',epoch=epochs,index=0))
    return rows


def material(study, arm):
    directory=study/arm
    weights=directory/'adapter/adapter_model.safetensors'
    weights.parent.mkdir(parents=True,exist_ok=True);weights.write_bytes(b'FIXTURE-NOT-MODEL')
    objective={'name':'paired-evidence-margin-v1'}
    plan={'actual_epochs':8,'training_units':14,'loss_objective':objective}
    receipt={'base_unchanged':True,'checkpoint_reload_equal':True,'optimizer_steps':112,
             'training_forwards':864,'loss_objective':objective,'initial_adapter_sha256':'a'*64,
             'adapter_tensor_sha256':'b'*64,'files':{'adapter/adapter_model.safetensors':c.file_sha(weights)}}
    c.write_new(directory/'training-plan.json',plan)
    c.write_new(directory/'training-receipt.json',receipt)
    journal(directory/'optimizer-journal.jsonl',optim_rows())
    return receipt


def cases():
    rows=[]
    for split in ('train','select'):
        conditions=('own_sources','empty','donor_sources','matched_donor_question') if split=='train' else ('own_sources','empty','donor_sources')
        for index in range(4):
            for condition in conditions:
                request={'question':'fixture question '+str(index),'options':[], 'evidence':[]}
                if split=='select' and index==3 and condition=='donor_sources':request=None
                rows.append(dict(question_id=split+':'+str(index),family='fixture:'+split,split=split,
                                 condition=condition,request=request))
    return rows


def arm_files(study, arm):
    raw=[];events=[]
    for slot,case in enumerate(cases()):
        row={k:case[k] for k in ('question_id','family','split','condition')}
        row.update(arm=arm,trial_id=c.digest([arm,slot,row]),evidence_ids=[],answer='FIXTURE',status='succeeded')
        if case['request'] is None:row.update(answer=None,status='unavailable_source_or_donor')
        else:row['public_request_sha256']=c.digest(case['request'])
        raw.append(row);events.append(dict(event='generation_recorded',**row))
    train=[dict(question_id=c.digest(['train',i]),status='succeeded',observed_decoder_forwards=8) for i in range(14)]
    audits=[dict(question_id=c.digest(['select',i]),status='succeeded' if i<3 else 'unavailable_recipient_annotation',observed_decoder_forwards=4 if i<3 else 0) for i in range(4)]
    events.append(dict(event='train_diagnostic_started',arm=arm))
    events.extend(dict(event='train_diagnostic_recorded',arm=arm,**x) for x in train)
    events.extend(dict(event='select_audit_recorded',arm=arm,**x) for x in audits)
    for suffix,value in (('-raw.json',raw),('-scores.json',[{} for _ in raw]),('-train-diagnostic.json',train),('-content-audit.json',audits)):
        c.write_new(study/(arm+suffix),value)
    c.write_new(study/(arm+'-raw-seal.json'),dict(sha256=c.file_sha(study/(arm+'-raw.json')),before_target_scoring=True))
    if arm!='frozen_reader':material(study,arm)
    return raw,events


class SubsetTests(unittest.TestCase):
    def test_default_is_original_full_order(self):self.assertIs(trial.execution_arms(),trial.ARMS)
    def test_reverse_only_keeps_original_profile(self):self.assertEqual(trial.execution_arms([r.RESTART]),(trial.ARMS[-1],))
    def test_scientific_plan_not_mutated(self):
        before=c.digest(trial.PLAN);trial.execution_arms([r.RESTART]);self.assertEqual(c.digest(trial.PLAN),before)
    def test_bad_subsets_rejected(self):
        for names in ([],(),['unknown'],['repeat_empty','repeat_empty'],['nonempty_reversed','frozen_reader'],'frozen_reader',[True]):
            with self.assertRaises(c.Invalid):trial.execution_arms(names)
    def test_invalid_subset_fails_before_import_download_output(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out'
            with self.assertRaises(c.Invalid):trial.run(None,None,None,None,out,only_arms=['bad'])
            self.assertFalse(out.exists())


class JournalTests(unittest.TestCase):
    def test_complete_census_measures_all_forwards(self):
        x=r.optimizer_census(optim_rows());self.assertEqual(x['completed_updates'],112);self.assertEqual(x['known_decoder_forward_lower_bound'],864)
    def test_open_update_unknown_not_zero(self):
        x=r.optimizer_census(optim_rows(1,1,True));self.assertEqual(x['completed_updates'],1);self.assertTrue(x['unobserved_tail_cost_unknown']);self.assertFalse(x['optimizer_state_resumable'])
    def test_failed_work_retained(self):
        rows=optim_rows(1,1);rows[-1]['event']='optimizer_failed_or_unknown'
        x=r.optimizer_census(rows);self.assertEqual(x['failed_updates'],1);self.assertEqual(x['known_decoder_forward_lower_bound'],8)
    def test_missing_start_rejected(self):
        with self.assertRaises(c.Invalid):r.optimizer_census(optim_rows(1,1)[1:])
    def test_duplicate_attempt_rejected(self):
        with self.assertRaises(c.Invalid):r.optimizer_census(optim_rows(1,1)*2)
    def test_overlapping_starts_rejected(self):
        with self.assertRaises(c.Invalid):r.optimizer_census([dict(event='optimizer_started',epoch=0,index=i) for i in (0,1)])
    def test_boolean_cost_or_unit_rejected(self):
        for key in ('epoch','observed_decoder_forwards'):
            rows=optim_rows(1,1);rows[-1][key]=True
            with self.assertRaises(c.Invalid):r.optimizer_census(rows)
    def test_chain_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events';rows=optim_rows(1,1);journal(p,rows);self.assertEqual(r.read_chain(p),rows)
            p.write_bytes(p.read_bytes().replace(b'"index":0',b'"index":1',1))
            with self.assertRaises(c.Invalid):r.read_chain(p)
    def test_truncated_json_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events';journal(p,optim_rows(1,1));p.write_bytes(p.read_bytes()+b'{')
            with self.assertRaises(ValueError):r.read_chain(p)
    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events';p.write_text('{"record":{},"record":{},"previous_sha256":"'+'0'*64+'"}\n')
            with self.assertRaises(c.Invalid):r.read_chain(p)


class MaterialTests(unittest.TestCase):
    def test_complete_receipt_checks_actual_files_and_journal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);expected=material(p,'repeat_empty');actual,counts=r.check_receipt(p,'repeat_empty')
            self.assertEqual(expected,actual);self.assertEqual(counts['completed_updates'],112)
    def test_stale_weight_pin_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);material(p,'repeat_empty');(p/'repeat_empty/adapter/adapter_model.safetensors').write_bytes(b'changed')
            with self.assertRaises(c.Invalid):r.check_receipt(p,'repeat_empty')
    def test_receipt_cannot_hide_open_update(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);material(p,'repeat_empty');q=p/'repeat_empty/optimizer-journal.jsonl';q.unlink();journal(q,optim_rows(open_tail=True))
            with self.assertRaises(c.Invalid):r.check_receipt(p,'repeat_empty')
    def test_copy_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').write_bytes(b'exact');r.copy_checked(p/'a',p/'b');self.assertEqual((p/'b').read_bytes(),b'exact')
            with self.assertRaises(c.Invalid):r.copy_checked(p/'a',p/'b')
    def test_copy_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').write_bytes(b'exact');(p/'s').symlink_to(p/'a')
            with self.assertRaises(c.Invalid):r.copy_checked(p/'s',p/'b')
    def test_full_saved_arm_and_unavailable_slot_retained(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);raw,events=arm_files(p,'repeat_empty');x=r.check_arm(p,'repeat_empty',cases(),events)
            self.assertEqual(x['raw'],raw);self.assertEqual(len(x['raw']),28);self.assertEqual(len(x['audits']),4)
    def test_raw_cannot_differ_from_chained_record(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);_,events=arm_files(p,'frozen_reader');events[0]['answer']='altered'
            with self.assertRaises(c.Invalid):r.check_arm(p,'frozen_reader',cases(),events)
    def test_scoring_before_generation_not_reusable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);_,events=arm_files(p,'frozen_reader');events.insert(0,dict(event='train_diagnostic_started',arm='frozen_reader'))
            with self.assertRaises(c.Invalid):r.check_arm(p,'frozen_reader',cases(),events)
    def test_missing_audit_file_is_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);_,events=arm_files(p,'frozen_reader');(p/'frozen_reader-content-audit.json').unlink()
            with self.assertRaises(c.Invalid):r.check_arm(p,'frozen_reader',cases(),events)
    def test_original_success_cannot_be_relabelled_as_cancelled(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'source').mkdir();(p/'source/tested-commit.txt').write_text(r.CANCELLED_SOURCE)
            c.write_new(p/'study/report.json',{'status':'success'})
            with self.assertRaises(c.Invalid):r.inspect_cancelled(p)


if __name__=='__main__':unittest.main()
