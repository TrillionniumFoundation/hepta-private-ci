"""Tests for an explicit archived reference, not natural-task efficacy.

Only the real-asset class is conditional in source-only CI. Hosted artifact CI
sets HEPTA_ARCHIVED_REFERENCE_ROOT and must execute those actual tensor tests.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
import five_archived_torch_reference as r
from five_archived_reference_trial import archive_rows


class SourceTests(unittest.TestCase):
    def test_unknown_kind_denied(self):
        with self.assertRaises(ValueError):r.verify('/absent','other')

    def test_missing_model_never_falls_back(self):
        with self.assertRaises(ValueError):r.ArchivedModel('/absent','reader')

    def test_empty_snapshot_denied(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):r.verify(d,'reader')

    def test_symlink_in_metadata_not_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'.cache').mkdir();(p/'a').write_bytes(b'not-model');(p/'.cache/link').symlink_to(p/'a')
            with self.assertRaises(ValueError):r.inventory(p)

    def test_metadata_excluded_but_kept_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'config.json').write_bytes(b'{}');(p/'.cache').mkdir();(p/'.cache/metadata').write_bytes(b'meta')
            observed=r.inventory(p)
            self.assertEqual(set(observed),{'config.json'});self.assertEqual((p/'.cache/metadata').read_bytes(),b'meta')

    def test_changed_byte_changes_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').write_bytes(b'a');first=r.inventory(p);(p/'a').write_bytes(b'b')
            self.assertNotEqual(first,r.inventory(p))

    def test_clean_copy_retains_full_inventory_and_records_exclusion(self):
        # Temporary test-only pin; no fixture is admitted as real model evidence.
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/'original';src.mkdir();(src/'model.safetensors').write_bytes(b'fixture')
            (src/'.cache').mkdir();(src/'.cache/meta').write_bytes(b'meta')
            pinned=hashlib.sha256(r.canonical(r.inventory(src))).hexdigest()
            with patch.dict(r.INVENTORIES,reader=pinned):
                result=r.stage_clean(src,p/'clean','reader')
                self.assertEqual(r.inventory(src),r.inventory(p/'clean'))
                self.assertEqual(len(result['excluded_metadata']),1)
                self.assertTrue((src/'.cache/meta').is_file());self.assertFalse((p/'clean/.cache').exists())
                with self.assertRaises(FileExistsError):r.stage_clean(src,p/'clean','reader')

    def test_wrong_archive_hash_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.zip';p.write_bytes(b'bad')
            with self.assertRaises(ValueError):archive_rows(p)

    def test_boolean_and_negative_token_ids_denied(self):
        model=object.__new__(r.ArchivedModel);model.config={'vocab_size':16}
        for ids in ([],[True],[-1],[16],['1']):
            with self.assertRaises(ValueError):model.valid_ids(ids)

    def test_allowed_token_ids(self):
        model=object.__new__(r.ArchivedModel);model.config={'vocab_size':16};model.valid_ids([0,15])

    def test_fixed_profile_does_not_claim_production(self):
        self.assertEqual(r.PROFILE,'hepta.archived-torch-reference.v1')


class ResidentDriverTests(unittest.TestCase):
    def prepare(self, root):
        rows=[{'id':str(i),'system':'s','user':'u','input_ids':[1], 'maximum_new_tokens':1} for i in range(5)]
        (root/'public-requests.json').write_bytes(r.canonical(rows))
        (root/'public-seal.json').write_text(json.dumps({'public_sha256':r.sha_file(root/'public-requests.json')}))

    def backend(self, fail=False):
        from types import SimpleNamespace
        class Fixture:
            loads=0
            def __init__(self,*args):
                Fixture.loads+=1; self.forward_calls=0
                self.tokenizer=SimpleNamespace(chat=lambda *args:[1])
            def generate(self,*args):
                self.forward_calls+=1
                if fail:raise ValueError('fixture failure')
                return {'answer':'FIXTURE', 'input_ids':[1], 'output_ids':[2]}
            def close(self):pass
        return Fixture

    def test_one_owner_for_all_requests(self):
        import five_archived_reference_trial as trial
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.prepare(root);fixture=self.backend()
            with patch.object(trial,'ArchivedModel',fixture):trial.generate_resident(root,root)
            self.assertEqual(fixture.loads,1)
            self.assertEqual(json.loads((root/'raw-seal-0.json').read_bytes())['cold_model_loads'],1)
            self.assertEqual(json.loads((root/'raw-seal-1.json').read_bytes())['cold_model_loads'],0)

    def test_existing_attempt_never_silently_retried(self):
        import five_archived_reference_trial as trial
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.prepare(root);(root/'raw-batch-0.jsonl').write_bytes(b'partial')
            fixture=self.backend()
            with patch.object(trial,'ArchivedModel',fixture):
                with self.assertRaises(ValueError):trial.generate_resident(root,root)
            self.assertEqual(fixture.loads,0)

    def test_failed_calls_stay_in_raw_census(self):
        import five_archived_reference_trial as trial
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.prepare(root)
            with patch.object(trial,'ArchivedModel',self.backend(True)):trial.generate_resident(root,root)
            events=[json.loads(line) for p in root.glob('raw-batch-*.jsonl') for line in p.read_bytes().splitlines()]
            finished=[row for row in events if row['event']=='finished']
            self.assertEqual(len(finished),5);self.assertTrue(all(row['status']=='failed' for row in finished))


class RealAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=os.environ.get('HEPTA_ARCHIVED_REFERENCE_ROOT')
        if root is None:raise unittest.SkipTest('source-only: real artifacts not supplied')
        # An explicit invalid supplied path is a failure, never a skip.
        cls.root=Path(root);torch.set_num_threads(1)
        cls.reader=r.ArchivedModel(cls.root/'reader','reader')
        cls.encoder=r.ArchivedModel(cls.root/'encoder','encoder')

    def test_source_inventories(self):
        self.assertEqual(len(r.verify(self.root/'reader','reader')),8)
        self.assertEqual(len(r.verify(self.root/'encoder','encoder')),6)

    def test_tokenizer_byte_roundtrip(self):
        for text in ('hello 1234 world','a\n\n café  中文 🙂',' 42.8e-3\tX','𠀀 ١٢٣'):
            self.assertEqual(self.reader.tokenizer.decode(self.reader.tokenizer.encode(text)),text)

    def test_digit_split_is_preserved(self):
        tok=self.reader.tokenizer
        self.assertEqual(tok.encode('1234'),sum((tok.encode(c) for c in '1234'),[]))

    def test_exact_chat_template_known_vector(self):
        ids=self.reader.tokenizer.chat('You are a helpful assistant.','What is 2 + 3? Answer with the number only.')
        self.assertEqual(ids,[1,9690,198,2683,359,253,5356,11173,30,2,198,1,4093,198,1780,314,216,34,1232,216,35,47,19842,351,260,1230,805,30,2,198,1,520,9531,198])

    def test_kv_cache_matches_full_prefix(self):
        ids=self.reader.tokenizer.encode('Hello world 123')
        a,_=self.reader.llama(ids);_,cache=self.reader.llama(ids[:-1]);b,_=self.reader.llama(ids[-1:],cache)
        self.assertTrue(torch.allclose(a,b,atol=1e-4,rtol=1e-5));self.assertEqual(int(a.argmax()),int(b.argmax()))

    def test_sdpa_and_eager_match(self):
        ids=self.reader.tokenizer.encode('Hello world')
        a,_=self.reader.llama(ids);b,_=self.reader.llama(ids,attention='sdpa')
        self.assertTrue(torch.allclose(a,b,atol=1e-4,rtol=1e-5))

    def test_bert_finite_and_repeatable(self):
        a=self.encoder.encode(['A short test.']);b=self.encoder.encode(['A short test.'])
        self.assertEqual(a.shape,(1,384));self.assertTrue(torch.isfinite(a).all());self.assertTrue(torch.equal(a,b))

    def test_bert_special_tokens_and_no_truncation(self):
        ids=self.encoder.tokenizer.encode('A short test.')
        self.assertEqual(ids,[101,1037,2460,3231,1012,102])
        with self.assertRaises(ValueError):self.encoder.bert([101]*513)

    def test_unknown_attention_denied(self):
        with self.assertRaises(ValueError):self.reader.llama([1],attention='unknown')

    @classmethod
    def tearDownClass(cls):
        cls.reader.close();cls.encoder.close()


if __name__=='__main__':unittest.main()
