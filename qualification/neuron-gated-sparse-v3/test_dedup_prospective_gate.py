#!/usr/bin/env python3
"""Real serialized model bytes and bounded signed-future duplicate-rejection tests.

All data, signers and labels are synthetic and are never A0/NDU credentials.
"""
import argparse
import base64
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from precommit_future import binary_metrics, score
from dedup_prospective_gate import canonical_tensor_sha, review, main
from test_realized_budget_audit import fixture, sha


def signed(root: Path, prefix: str, payload: dict) -> tuple[Path,Path]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    secret = Ed25519PrivateKey.generate()
    public = secret.public_key()
    raw = public.public_bytes(Encoding.Raw,PublicFormat.Raw)
    pem = root/(prefix+'.pem')
    pem.write_bytes(public.public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo))
    sig = root/('signed-'+prefix+'.json')
    canonical = json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    sig.write_text(json.dumps({
        'payload':payload,'signer_key_id':hashlib.sha256(raw).hexdigest(),
        'signature_b64':base64.b64encode(secret.sign(canonical)).decode()
    }))
    return sig,pem


class PhysicalDedupFutureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        original, self.training=fixture(self.root,width=16)
        self.training.update(cell_id='not-real-owner',
            encoder_digest_claimed='a'*64,
            no_change_v1_selected_sha256='b'*64,
            training_cutoff_utc='2026-10-01T00:00:00Z')
        self.train_sha=self.save_receipt()
        mapping={f"{r['cap']}:{r['arm']}":r['weight_sha256'] for r in self.training['models']}
        self.labels={}
        probabilities={'v2':580000,'v3':730000,'ssm':340000,'min_gru':520000}
        events=[]
        for i in range(6):
            case=f'future-case-{i}'
            part='future' if i<3 else 'ood'
            label=i%2
            self.labels[case]=label
            events.append({
                'case_id':case, 'partition':part,
                'source_group_sha256':hashlib.sha256(f'grp{i}'.encode()).hexdigest(),
                'event_time_utc':'2026-10-14T09:20:00Z',
                'owner_v1_probability_ppm':500000,
                'candidates':{k:probabilities[k.split(':')[1]] for k in mapping}
            })
        self.seal={
            'schema':'hepta.neuron.five-arm-research-forecast-seal.v2',
            'cell_id':'not-real-owner','encoder_digest_claimed':'a'*64,
            'training_cutoff_utc':'2026-10-01T00:00:00Z',
            'frozen_v1_artifact_sha256':'b'*64,
            'a0_evidence_class':'SYNTHETIC_FIXTURE_ONLY',
            'train_receipt_sha256':self.train_sha,'model_sha256':mapping,
            'sealed_at_utc_untrusted_local_clock':'2026-10-14T09:30:00Z',
            'ndu_eligible':False,'production_qualification':False,
            'rows':events
        }
        self.seal_path=self.root/'seal.json'
        self.seal_sha=self.save_seal()
        self.scored=self.make_score()

    def save_receipt(self):
        p=self.root/'training-receipt.json'
        p.write_text(json.dumps(self.training,sort_keys=True)+'\n')
        return sha(p)

    def save_seal(self):
        self.seal_path.write_text(json.dumps(self.seal,sort_keys=True)+'\n')
        value=sha(self.seal_path)
        if hasattr(self,'scored'):
            self.scored['seal_sha256']=value
        return value

    def make_score(self):
        output={}
        for part in ('future','ood'):
            values=[(row,self.labels[row['case_id']]) for row in self.seal['rows']
                    if row['partition']==part]
            base=binary_metrics([(row['owner_v1_probability_ppm'],label)
                                 for row,label in values])
            metrics={}
            for key in self.seal['model_sha256']:
                cohort=[(row['candidates'][key],label) for row,label in values]
                stat=binary_metrics(cohort)
                stat['brier_improvement_ppm']=base['brier_ppm']-stat['brier_ppm']
                stat['false_acceptance_at_confidence_85pct']=sum(
                    (p>=850000 and not y) or (p<=150000 and bool(y)) for p,y in cohort)/len(cohort)
                metrics[key]=stat
            output[part]={'owner_v1':base,'candidates':metrics}
        return {'a0_evidence_class':'SYNTHETIC_FIXTURE_ONLY',
                'seal_sha256':self.seal_sha, 'decision':'NO_PRODUCTION_PROMOTION',
                'ndu_eligible':False, 'production_qualification':False,
                'native_q24_parity_verified':False,
                'trusted_host_time_independently_proven':False,
                'partitions':output}

    def check(self):
        return review(self.root,self.train_sha,self.seal_path,self.seal_sha,
                      self.scored,synthetic_canary=True)

    def test_twenty_physical_slots_collapse_to_four_model_hypotheses(self):
        out=self.check()
        self.assertEqual((out['nominal_candidate_slots'],
                          out['unique_physical_tensor_models_per_arm'],
                          out['redundant_ceiling_alias_count']),(20,4,16))
        self.assertFalse(out['equal_realized_parameter_design_valid'])
        self.assertEqual(len(out['unique_model_groups']),4)
        self.assertEqual({r['arm'] for r in out['unique_model_groups']},
                         {'v2','v3','ssm','min_gru'})
        self.assertTrue(all(len(r['nominal_budget_aliases'])==5
                            for r in out['unique_model_groups']))
        self.assertFalse(out['ndu_eligible'])
        self.assertFalse(out['production_qualification'])
        self.assertEqual(out['decision'],'NO_MODEL_PROMOTION')
        self.assertTrue(1<=len(out['descriptive_pareto_candidate_ids_only'])<=4)

    def test_differently_serialized_same_tensors_deduplicate(self):
        model=next(r for r in self.training['models'] if r['cap']==8192 and r['arm']=='v2')
        path=self.root/model['weight_file']
        before=canonical_tensor_sha(path)
        data=path.read_bytes()
        header_len=int.from_bytes(data[:8],'little')
        header=json.loads(data[8:8+header_len])
        header['__metadata__']={'descriptive-run-name':'second-nominal-ceiling'}
        rewrite=json.dumps(header,separators=(',',':')).encode()
        path.write_bytes(len(rewrite).to_bytes(8,'little')+rewrite+data[8+header_len:])
        self.assertEqual(canonical_tensor_sha(path),before)
        model['weight_sha256']=sha(path)
        self.train_sha=self.save_receipt()
        self.seal['train_receipt_sha256']=self.train_sha
        self.seal['model_sha256']['8192:v2']=sha(path)
        self.seal_sha=self.save_seal()
        self.scored['seal_sha256']=self.seal_sha
        result=self.check()
        self.assertEqual(result['unique_physical_tensor_models_per_arm'],4)
        self.assertEqual(result['redundant_ceiling_alias_count'],16)

    def test_physical_same_model_cannot_predict_differently(self):
        self.seal['rows'][0]['candidates']['8192:v3']+=1
        self.seal_sha=self.save_seal()
        with self.assertRaisesRegex(ValueError,'divergent future prediction'):
            self.check()

    def test_different_signed_metrics_for_same_model_rejected(self):
        self.scored['partitions']['ood']['candidates']['8192:v3']['brier_ppm']+=0.001
        with self.assertRaisesRegex(ValueError,'inconsistent signed metrics'):
            self.check()

    def test_changed_model_sha_in_seal_rejected(self):
        self.seal['model_sha256']['2048:ssm']='f'*64
        self.seal_sha=self.save_seal()
        with self.assertRaisesRegex(ValueError,'not bound to sealed prediction'):
            self.check()

    def test_train_receipt_sha_or_frozen_v1_drift_rejected(self):
        with self.assertRaisesRegex(ValueError,'training receipt SHA mismatch'):
            review(self.root,'c'*64,self.seal_path,self.seal_sha,self.scored,synthetic_canary=True)
        self.seal['frozen_v1_artifact_sha256']='c'*64
        self.seal_sha=self.save_seal()
        with self.assertRaisesRegex(ValueError,'not joined'):
            self.check()

    def test_tensor_fingerprint_requires_current_pinned_physical_hash(self):
        from dedup_prospective_gate import canonical_tensor_sha
        model=next(x for x in self.training['models'] if x['arm']=='v3')
        p=self.root/model['weight_file']
        self.assertEqual(len(canonical_tensor_sha(p,model['weight_sha256'])),64)
        with self.assertRaisesRegex(ValueError,'changed after pinned receipt audit'):
            canonical_tensor_sha(p,'f'*64)

    def test_candidate_tensor_sha_changed_after_seal(self):
        with (self.root/'2048'/'v2.safetensors').open('ab') as fp: fp.write(b'evil')
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
            self.check()

    def test_refuses_unsigned_or_wrong_scored_result(self):
        self.scored['ndu_eligible']=True
        with self.assertRaisesRegex(ValueError,'fabricated model authority'):
            self.check()

    def test_missing_future_ood_and_wrong_paired_case(self):
        self.scored['partitions'].pop('ood')
        with self.assertRaisesRegex(ValueError,'missing signed future or OOD'):
            self.check()
        self.scored=self.make_score()
        self.seal['rows'].append(copy.deepcopy(self.seal['rows'][0]))
        self.seal_sha=self.save_seal()
        with self.assertRaisesRegex(ValueError,'duplicate, or unpaired'):
            self.check()

    def test_cross_arm_different_execution_is_not_collapsed_by_parameters(self):
        out=self.check()
        self.assertEqual(len({v['arm'] for v in out['unique_model_groups']}),4)
        self.assertEqual(out['unique_physical_tensor_models_per_arm'],4)

    def test_real_signed_witness_outcomes_through_score_and_review(self):
        from precommit_future import score
        wit={'schema':'hepta.neuron.five-arm-precommit-witness.v1',
             'seal_sha256':self.seal_sha,'committed_at_utc':'2026-10-14T09:31:00Z',
             'host_id':'synthetic-host-not-authenticated','operation_id':'synthetic-op'}
        outcome={'schema':'hepta.neuron.five-arm-independent-outcomes.v1',
                 'cell_id':self.seal['cell_id'],'input_seal_sha256':self.seal_sha,
                 'rows':[{'case_id':row['case_id'],'partition':row['partition'],
                          'source_group_sha256':row['source_group_sha256'],
                          'label':self.labels[row['case_id']],
                          'label_available_at_utc':'2026-10-14T09:32:00Z'}
                         for row in self.seal['rows']]}
        witness,pub=signed(self.root,'witness',wit)
        outcomes,outpub=signed(self.root,'outcomes',outcome)
        args=argparse.Namespace(
            seal_file=str(self.seal_path),seal_sha256=self.seal_sha,
            signed_witness=str(witness),witness_pubkey=str(pub),
            signed_outcomes=str(outcomes),outcome_pubkey=str(outpub),
            synthetic_canary=True)
        independently_verified=score(args)
        result=review(self.root,self.train_sha,self.seal_path,self.seal_sha,
                      independently_verified,synthetic_canary=True)
        self.assertEqual(result['unique_physical_tensor_models_per_arm'],4)
        # Exercise the unmocked CLI: both signer public keys and the sealed
        # physical model bytes are rechecked before create-only JSON output.
        from unittest.mock import patch
        import contextlib
        import io
        import sys
        report=self.root/'actual-signed-cli-dedup.json'
        argv=['dedup_prospective_gate.py','--trained-root',str(self.root),
              '--training-receipt-sha256',self.train_sha,
              '--seal-file',str(self.seal_path),'--seal-sha256',self.seal_sha,
              '--signed-witness',str(witness),'--witness-pubkey',str(pub),
              '--signed-outcomes',str(outcomes),'--outcome-pubkey',str(outpub),
              '--synthetic-canary','--report',str(report)]
        with patch.object(sys,'argv',argv),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(),0)
        emitted=json.loads(report.read_text())
        self.assertEqual(emitted['unique_physical_tensor_models_per_arm'],4)
        self.assertEqual(emitted['redundant_ceiling_alias_count'],16)
        self.assertEqual(emitted['decision'],'NO_MODEL_PROMOTION')
        with patch.object(sys,'argv',argv),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(),2)  # create-only output rejects overwrite
        outcome['rows'][0]['label_available_at_utc']='2026-10-14T09:29:59Z'
        signed(self.root,'outcomes',outcome)
        with self.assertRaisesRegex(ValueError,'leakage'):
            score(args)

    def test_cli_produces_new_signed_format_review_not_production(self):
        from unittest.mock import patch
        import contextlib
        import io
        import sys
        r=self.root/'independent-dedup.json'
        argv=['dedup_prospective_gate.py','--trained-root',str(self.root),
              '--training-receipt-sha256',self.train_sha,
              '--seal-file',str(self.seal_path),'--seal-sha256',self.seal_sha,
              '--signed-witness',str(self.root/'not-used-witness.json'),
              '--witness-pubkey',str(self.root/'not-used.pem'),
              '--signed-outcomes',str(self.root/'not-used-outcome.json'),
              '--outcome-pubkey',str(self.root/'not-used-key.pem'),
              '--synthetic-canary','--report',str(r)]
        with patch('dedup_prospective_gate.signed_future_score',return_value=self.scored),\
             patch.object(sys,'argv',argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(),0)
        file=json.loads(r.read_text())
        self.assertFalse(file['ndu_eligible'])
        self.assertFalse(file['production_qualification'])
        self.assertEqual(file['redundant_ceiling_alias_count'],16)


if __name__=='__main__':
    unittest.main()
