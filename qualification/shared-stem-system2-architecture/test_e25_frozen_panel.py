"""E25 contract tests: REAL historical old ZIP, SYNTHETIC new source fixtures.

These tests DO NOT claim six newly executed pretrained passages or human gains.
The new original pretrained forwards are a separate hosted CI job.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from e25_unseen_material import (old_source_groups,exclude_previous_source_passages,
                                ORIGINAL_SOURCE_HEAD,VAL_SHA,write_once)
from e25_fixed_policy_transfer import (frozen,POLICY_SHA,ARMS,METHODS,
                                 previous_model_from_zip,geometry,propose,source_json,verify_original_two_seals)
from e25_independent_score import (independently_predictions,reference_sigmoid,
                                   sign_flip_paired_passages,truth_from_parquet)

ROOT=Path(__file__).resolve().parent
ORIGINAL=os.environ.get('HEPTA_E25_ORIGINAL','/mnt/data/hepta-artifact-11946621518.zip')
POLICY=str(ROOT/'e25_frozen_policy.json')


def hashjson(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def synthetic_six():
    """Source-relabelled original logits, explicitly NOT fresh pretrained inference."""
    old=previous_model_from_zip(ORIGINAL)
    with ZipFile(ORIGINAL) as z:
        original=json.loads(z.read('multirc-native-candidate-audit/audit.json'))
    slate=[];index=[]
    for i in range(6):
        group=f'{i+99:032x}'
        qq=[]
        for q in (0,1):
            cc=[]
            for v in (0,1):
                task=f'{i+3:04x}{q:04x}{v:04x}'.ljust(32,'f')
                cc.append(dict(task_id=task,candidate_id=v,answer=f'answer_{i}_{q}_{v}'))
                index.append(dict(task_id=task,source_group=group,question_slot=q,
                                  candidate_id=v,original_v1_candidate=v==0))
            qq.append(dict(question_slot=q,question=f'question_{i}_{q}',
                           original_task_id=cc[0]['task_id'],candidates=cc))
        slate.append(dict(source_group=group,evidence=f'Passage_{i}',questions=qq))
    audit=deepcopy(original)
    audit['rows']=index
    audit['actual_candidate_count']=len(index)
    audit['actual_question_encoder_calls']=len(index)
    audit['actual_reader_calls']=len(index)*4
    audit['shared_evidence_encoder_calls']=6
    audit['source_panel_id']='a'*64
    audit['slate_id']='b'*64
    audit['evaluation_labels_loaded']=False
    audit['previous_v1_training_unchanged']=True
    audit['native_candidates_not_cross_question_fabrications']=True
    audit['model_snapshot_sha256']=old['model_snapshot_sha256']
    for name in ARMS:
        reference=original['predictions'][name]
        audit['predictions'][name]=[dict(task_id=row['task_id'],
             source_group=row['source_group'],question_slot=row['question_slot'],
             logits=reference[(i//2)%len(reference)]['logits'],
             weights_sha256=old['training'][name]['weights_sha256'])
             for i,row in enumerate(index)]
    new=dict(schema='hepta.multirc.original-question-complete-candidates.v1',
             source_panel_id='a'*64,slate_id='b'*64,rows=slate)
    group_set_digest=sha256(json.dumps(sorted(p['source_group'] for p in slate),
                                     separators=(',',':')).encode()).hexdigest()
    source=dict(new_candidate_count=len(index),new_question_count=12,
         new_source_groups=[x['source_group'] for x in slate],
         original_archive_sha256=original_sha(),original_source_head=ORIGINAL_SOURCE_HEAD,
         selection_uses_labels_or_predictions=False,future_time_or_independent_family=False,
         eligible_unused_passage_count_verified=6,
         eligible_unused_distinct_text_count_verified=6,
         full_unused_source_census_before_model=True,
         source_issuer_independently_authenticated=False,
         eligible_unused_group_set_sha256=group_set_digest,
         production_accepted=False)
    owner=deepcopy(old);owner['actual_eval_encoder_calls']=6;owner['panel_id']='a'*64
    return audit,source,new,owner


def original_sha():
    return sha256(Path(ORIGINAL).read_bytes()).hexdigest()


class E25FrozenSourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(ORIGINAL).is_file():
            raise RuntimeError('original real pretrained ZIP is REQUIRED; no skip/fixture replacement')
        cls.config=frozen(POLICY)
        cls.audit,cls.source,cls.slate,cls.owner=synthetic_six()

    def test_original_archived_model_sha_is_real(self):
        self.assertEqual(original_sha(),self.config['model_archive_sha256'])

    def test_original_real_historical_archive_has_exactly_ten_eligible_source_passages(self):
        # True original pretrained ZIP bytes, but NO new six-passage logits
        # or human validation labels are accessed in this diagnostic.
        with ZipFile(ORIGINAL) as z:
            archive=json.loads(z.read('multirc-material/MATERIAL.json'))
        validation=archive['material_admission']['validation']
        self.assertEqual((validation['eligible_passages'],
                          validation['eligible_distinct_texts']), (10,10))
        self.assertEqual(archive['total_selected_validation_passages'],4)
        self.assertEqual(validation['raw_passages'],83)
        self.assertEqual(validation['raw_rows'],4848)

    def test_historical_training_source_and_new_group_division(self):
        self.assertEqual(len(old_source_groups(ORIGINAL)),4)
        self.assertEqual(len(set(old_source_groups(ORIGINAL))),4)
        self.assertEqual(previous_model_from_zip(ORIGINAL)['steps'],64)

    def test_original_head_params_fixed_exact_4_by_2_by_5(self):
        self.assertEqual(len(self.config['folds']),4)
        self.assertEqual([f['fold'] for f in self.config['folds']],list(range(4)))
        self.assertEqual({k:len(f['weights'][k]) for f in self.config['folds'] for k in METHODS},
                         {k:5 for k in METHODS})

    def test_frozen_model_file_sha_cannot_rewrite(self):
        self.assertEqual(sha256(Path(POLICY).read_bytes()).hexdigest(),POLICY_SHA)
        with tempfile.TemporaryDirectory() as td:
            altered=Path(td)/'fake.json'
            d=deepcopy(self.config)
            d['folds'][0]['weights'][METHODS[1]][0]+=1e-5
            altered.write_text(json.dumps(d))
            with self.assertRaises(ValueError):frozen(str(altered))

    def test_original_seal_wrong_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake.zip';p.write_bytes(Path(ORIGINAL).read_bytes()+b'f')
            with self.assertRaises(ValueError):old_source_groups(str(p))

    def test_real_pretrained_readers_identical_in_synthetic_provenance_fixture(self):
        x,old=geometry(self.audit,self.source,self.slate,self.owner,ORIGINAL)
        self.assertEqual(len(x),24)
        self.assertEqual(len(old['training']),4)
        self.assertEqual(len({(r['group'],r['question_slot']) if 'group' in r else (r['source_group'],r['question_slot']) for r in x}),12)

    def test_experimental_frozen_students_have_no_new_human_labels(self):
        result=propose(self.audit,self.source,self.slate,self.owner,self.config,ORIGINAL)
        self.assertEqual(result['new_validation_candidates'],24)
        self.assertEqual(result['new_reader_train_anchor_slate_evidence_forwards'],20)
        self.assertFalse(result['human_validation_labels_read_before_seal'])
        self.assertFalse(result['production_accepted'])
        self.assertFalse(result['learning_or_model_selected'])
        self.assertEqual(set(result['rows'][0]['probabilities']),set(ARMS)|set(METHODS))

    def test_independent_old_data_relabelled_logits_reference_parity(self):
        result=propose(self.audit,self.source,self.slate,self.owner,self.config,ORIGINAL)
        independent=independently_predictions(self.audit,self.slate,self.config)
        for r in result['rows']:
            for arm,x in r['probabilities'].items():
                self.assertAlmostEqual(x,independent[r['task_id']][arm],delta=1e-12)

    def test_frozen_fourfold_head_weight_mutation_rejected(self):
        config=deepcopy(self.config);config['folds'][0]['weights'][METHODS[0]][1]=float('nan')
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.json';p.write_text(json.dumps(config))
            with self.assertRaises(ValueError):frozen(str(p))

    def test_source_observation_missing_group_rejected(self):
        src=deepcopy(self.source);src['new_source_groups'].pop()
        with self.assertRaises(ValueError):geometry(self.audit,src,self.slate,self.owner,ORIGINAL)

    def test_forged_six_source_census_is_denied_before_reader_scoring(self):
        for key,value in (
                ('eligible_unused_passage_count_verified',5),
                ('eligible_unused_distinct_text_count_verified',7),
                ('full_unused_source_census_before_model',False),
                ('source_issuer_independently_authenticated',True),
                ('eligible_unused_group_set_sha256','f'*64)):
            source=deepcopy(self.source)
            source[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                geometry(self.audit,source,self.slate,self.owner,ORIGINAL)

    def test_source_new_pretrained_evidence_required(self):
        audit=deepcopy(self.audit);audit['shared_evidence_encoder_calls']=0
        with self.assertRaises(ValueError):geometry(audit,self.source,self.slate,self.owner,ORIGINAL)

    def test_model_head_not_retrained_or_silently_swapped(self):
        owner=deepcopy(self.owner);owner['training']['conditioned']['weights_sha256']='0'*64
        with self.assertRaises(ValueError):geometry(self.audit,self.source,self.slate,owner,ORIGINAL)

    def test_original_answer_slate_missing_candidate_rejected(self):
        bad=deepcopy(self.audit);bad['rows'].pop()
        with self.assertRaises(ValueError):geometry(bad,self.source,self.slate,self.owner,ORIGINAL)

    def test_malformed_model_logit_refused(self):
        bad=deepcopy(self.audit);bad['predictions']['no_evidence'][0]['logits'][1]=float('nan')
        with self.assertRaises(ValueError):geometry(bad,self.source,self.slate,self.owner,ORIGINAL)

    def test_positive_new_source_and_unsupported_time_claim_denied(self):
        source=deepcopy(self.source);source['future_time_or_independent_family']=True
        with self.assertRaises(ValueError):geometry(self.audit,source,self.slate,self.owner,ORIGINAL)

    def test_source_material_selection_uses_no_labels(self):
        # Simulate only the original ID hashing protocol; not public model inference.
        old={f'{i+1:032x}' for i in range(4)}
        rows=[];hashes=set()
        for i in range(10):
            p=f'original passage number {i}'
            doc=hashjson(p)
            group=sha256(f'validation:passage:{i}:{doc}'.encode()).hexdigest()[:32]
            hashes.add(group)
            if i<4:old.add(group)
            for q in (1,2):
                rows.append({'idx':{'paragraph':i,'question':q,'answer':0},
                 'paragraph':p,'question':f'q{q}','answer':'a','label':i%2})
        old=old-set(f'{i+1:032x}' for i in range(4))
        fake=types.SimpleNamespace(_digest=hashjson)
        with patch.dict(sys.modules,{'next_round_matrix':fake}):
            x=exclude_previous_source_passages(rows,old)
            self.assertEqual(len(x),12)
            alternate=deepcopy(rows)
            for row in alternate:row['label']^=1
            self.assertEqual(x[0]['paragraph'],exclude_previous_source_passages(alternate,old)[0]['paragraph'])

    def test_previous_four_missing_after_prelabel_pruning_fails(self):
        group={'a'*32,'b'*32,'c'*32,'d'*32}
        with patch.dict(sys.modules,{'next_round_matrix':types.SimpleNamespace(_digest=hashjson)}):
            with self.assertRaises(ValueError):exclude_previous_source_passages([{'idx':{'paragraph':1,'question':2,'answer':3},'paragraph':'x','question':'y','answer':'z','label':1}],group)

    def test_exact_create_only_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'saved.json';x={'authority':'DENY_ALL'}
            first=write_once(p,x)
            self.assertEqual(first,sha256(p.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):write_once(p,x)

    def test_proposed_readout_not_an_independent_new_family(self):
        record=propose(self.audit,self.source,self.slate,self.owner,self.config,ORIGINAL)
        self.assertFalse(record['new_time_or_data_family'])
        self.assertFalse(record['complete_service_cost_measured'])

    def test_original_owner_and_candidate_seals_reproduce_sha(self):
        with ZipFile(ORIGINAL) as z, tempfile.TemporaryDirectory() as td:
            root=Path(td)
            entries={}
            for key,target in (("multirc-run/predictions.json","owner.json"),
                               ("multirc-run/COMMITTED.json","owner-committed.json"),
                               ("multirc-native-candidate-audit/audit.json","slate.json"),
                               ("multirc-native-candidate-audit/COMMITTED.json","slate-committed.json")):
                p=root/target;p.write_bytes(z.read(key));entries[target]=p
            self.assertTrue(verify_original_two_seals(*(str(entries[x]) for x in (
                "owner.json","owner-committed.json","slate.json","slate-committed.json"))))
            entries['slate.json'].write_bytes(entries['slate.json'].read_bytes()+b'X')
            with self.assertRaises(ValueError):verify_original_two_seals(*(str(entries[x]) for x in (
                "owner.json","owner-committed.json","slate.json","slate-committed.json")))

    def test_frozen_policy_introspects_exact_source_sha(self):
        self.assertTrue(self.config['tau_posthoc_on_original_family'])
        self.assertEqual(self.config['source_commit'],'67e4576111b61720f03ea9a105bad6e7ce2eb28c')
        self.assertFalse(self.config['new_time_or_source_family'])

    def test_exact_pairwise_six_passage_sign_flip_negative(self):
        passes=list(range(6));base={i:2 for i in passes};other={i:3 if i==0 else 2 for i in passes}
        self.assertEqual(sign_flip_paired_passages(base,other,passes),'64/64')
        self.assertAlmostEqual(reference_sigmoid(0.),0.5)
        self.assertAlmostEqual(reference_sigmoid(5.),1/(1+__import__('math').exp(-5)),places=14)

    def test_reviewer_catches_swapped_candidate_probability(self):
        result=propose(self.audit,self.source,self.slate,self.owner,self.config,ORIGINAL)
        ref=independently_predictions(self.audit,self.slate,self.config)
        first=result['rows'][0]
        first['probabilities'][METHODS[0]]+=0.1
        self.assertGreater(abs(first['probabilities'][METHODS[0]]-ref[first['task_id']][METHODS[0]]),0.05)

    def test_new_source_label_fabrication_not_marked_real_test(self):
        self.assertEqual(len(self.source['new_source_groups']),6)
        self.assertFalse(self.source['selection_uses_labels_or_predictions'])
        self.assertFalse(self.source['production_accepted'])

if __name__=='__main__':unittest.main()
