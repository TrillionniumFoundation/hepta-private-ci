"""Offline source/identity safety tests only; NOT actual Granite97 inference."""
import copy
import hashlib
import json
import pathlib
import tempfile
import time
import unittest

import granite97_v9_public_physical as v9


class StudyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.model = self.root / 'model'
        self.model.mkdir()
        for f in v9.FILES:
            (self.model / f).write_bytes(('fixed fake, not a real model:'+f).encode())
        self.source = self.root / 'source.txt'
        self.source.write_bytes(bytes.fromhex('') + PUBLIC_SOURCE)
        self.lockfile = self.root / 'lock.json'
        self.lock = v9.prepare(self.source, self.model, self.lockfile,
                               now_ms=time.time_ns()//1_000_000)
        self.v = [0] * 384
        self.exp = {'schema': 'hepta.stem.granite97-token-export.v5',
                    'source_sha256': v9.SOURCE_SHA,
                    'input_digest':'2'*64, 'material_digest':self.lock['material_sha256'],
                    'encoder_digest':'3'*64, 'tokenizer_digest':'4'*64,
                    'normalizer_digest':'5'*64, 'quantization_digest':'6'*64,
                    'preprocessing_digest':'7'*64, 'adapter_digest':'8'*64,
                    'expires_at_ms':self.lock['expires_at_ms'], 'encoder_forwards':1,
                    'input_ids':[101], 'values_q24':self.v}
        self.exportfile = self.root / 'export.json'
        self.write(self.exportfile, self.exp)
        self.review = {'schema':'hepta.stem.granite97-independent-physical-review.v1',
                       'export_sha256':hashlib.sha256(self.exportfile.read_bytes()).hexdigest(),
                       'source_sha256':v9.SOURCE_SHA,
                       'input_digest':self.exp['input_digest'],
                       'material_sha256':self.lock['material_sha256'],
                       'encoder_digest':self.exp['encoder_digest'],
                       'reviewer_encoder_forwards':1,
                       'reviewer_encoder_cpu_ns':100, 'reviewer_encoder_wall_ns':120,
                       'exact_tensors':2,
                       'feature_q24_sha256':hashlib.sha256(b'\0'*3072).hexdigest(),
                       'model_replayed':True, 'selected_model':False,
                       'production_authorized':False,'authority':'DENY_ALL'}
        self.reviewfile = self.root / 'review.json'
        self.write(self.reviewfile, self.review)

    @staticmethod
    def write(path, obj):
        path.write_text(json.dumps(obj,sort_keys=True)+'\n')

    def admit(self):
        return v9.admit(self.lockfile,self.source,self.exportfile,
                        self.reviewfile,self.root/'admission.json')

    def test_pinned_source_exact(self):
        self.assertEqual(v9.sha(PUBLIC_SOURCE),v9.SOURCE_SHA)
        self.assertEqual(v9.source_bytes(self.source),PUBLIC_SOURCE)
        self.source.write_bytes(PUBLIC_SOURCE+b'!')
        with self.assertRaises(ValueError): v9.source_bytes(self.source)

    def test_bounded_material_root_and_hash(self):
        x, digest = v9.calculate_material(self.model)
        self.assertEqual(digest,self.lock['material_sha256'])
        self.assertEqual(x['revision'],v9.REVISION)
        (self.model/'config.json').write_text('mutated')
        self.assertNotEqual(v9.calculate_material(self.model)[1],digest)

    def test_real_file_symlink_reject(self):
        orig=self.model/'config.json'
        orig.unlink()
        orig.symlink_to(self.model/'tokenizer.json')
        with self.assertRaises(ValueError):v9.calculate_material(self.model)

    def test_lock_cannot_claim_authority(self):
        for field,val in [('production_authorized',True),('authority','ALLOW'),
                          ('independent_hardware_attested',True),('independent_model_owner_authenticated',True)]:
            x=dict(self.lock);x[field]=val
            with self.subTest(field=field),self.assertRaises(ValueError):v9.check_lock(x)

    def test_missing_workspace_material_fails(self):
        with self.assertRaises(FileExistsError):
            v9.prepare(self.source,self.model,self.root/'second-lock.json',now_ms=time.time_ns()//1_000_000)

    def test_honest_two_head_admission(self):
        result=self.admit()
        self.assertEqual(result['heads'][0]['cell_id'],'cell:reference')
        self.assertEqual(result['heads'][1]['cell_id'],'cell:local-q24')
        self.assertEqual(len(result['heads'][1]['local_q24']),384)
        self.assertEqual(result['heads'][1]['local_q24'][0],v9.Q24)
        self.assertNotIn('production_authorized',result)

    def test_missing_review_fails(self):
        self.reviewfile.unlink()
        with self.assertRaises(ValueError):self.admit()

    def test_wrong_original_export_sha_denies(self):
        self.review['export_sha256']='0'*64
        self.write(self.reviewfile,self.review)
        with self.assertRaises(ValueError):self.admit()

    def test_wrong_physical_feature_digest_denies(self):
        self.review['feature_q24_sha256']='0'*64
        self.write(self.reviewfile,self.review)
        with self.assertRaises(ValueError):self.admit()

    def test_reviewer_self_grant_denies(self):
        for k,v in [('production_authorized',True),('model_replayed',False),('reviewer_encoder_forwards',0)]:
            fake=copy.deepcopy(self.review);fake[k]=v
            self.write(self.reviewfile,fake)
            with self.subTest(k=k),self.assertRaises(ValueError):self.admit()

    def test_duplicate_json_key_rejected(self):
        self.exportfile.write_bytes(b'{"schema":"old","schema":"new"}')
        with self.assertRaisesRegex(ValueError,'duplicate'):self.admit()

    def test_expired_lock_blocks_native(self):
        lock=dict(self.lock);lock['expires_at_ms']=1
        self.write(self.lockfile,lock)
        with self.assertRaisesRegex(ValueError,'expired'):self.admit()

    def test_source_material_and_epoch_bind_together(self):
        lock=dict(self.lock);lock['generation']=10
        self.write(self.lockfile,lock)
        with self.assertRaises(ValueError):self.admit()
        self.write(self.lockfile,self.lock)
        self.exp['material_digest']='0'*64
        self.write(self.exportfile,self.exp)
        with self.assertRaises(ValueError):self.admit()

    def test_native_result_audit_and_false_promotion(self):
        admitted=self.admit()
        admission=self.root/'admission.json'
        simulated={'schema':'hepta.stem.granite-v3-local-shadow-result.v7',
                   'authority':'DENY_ALL','model_selected':False,'production_authorized':False,
                   'admission_bytes_digest':v9.sha(admission.read_bytes()),
                   'original_source_digest':v9.SOURCE_SHA,
                   'exported_bytes_digest':admitted['export_bytes_digest'],
                   'independently_reviewed_bytes_digest':admitted['independent_review_bytes_digest'],
                   'complete_input_digest':admitted['complete_input_digest'],
                   'claimed_reviewer_encoder_forwards':1,
                   'actual_reader_attention_pairs':2,
                   'cells':[{'cell_id':'cell:reference'},{'cell_id':'cell:local-q24'}]}
        native=self.root/'native.json'
        self.write(native,simulated)
        r=v9.audit_native(self.lockfile,admission,native,self.root/'audit.json')
        self.assertFalse(r['pretrained_task_correctness_established'])
        self.assertFalse(r['independent_source_or_model_signer'])
        native.write_text(json.dumps({**simulated,'production_authorized':True}))
        with self.assertRaises(ValueError):
            v9.audit_native(self.lockfile,admission,native,self.root/'audit2.json')


PUBLIC_SOURCE = (b'Research-only constructed example. In the fictional materials ledger, '
                 b'specimen Q-17 was assigned the tag AMBER in the first signed observation. '
                 b'A later note describes the laboratory room as BLUE, but does not change '
                 b'the specimen tag.\nQuestion: What tag was assigned to specimen Q-17?\n'
                 b'Ordered options: A. BLUE; B. AMBER; C. GREEN; D. not recorded.\n')

if __name__=='__main__':unittest.main()
