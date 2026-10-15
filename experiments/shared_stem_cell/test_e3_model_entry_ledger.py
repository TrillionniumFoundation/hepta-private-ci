"""Physical 192-source synthetic UTF8/PNG model input admission regressions.

Tests are *not* pretrained E3 model inference, nor source-owner/label claims.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

import e3_model_entry_ledger as handoff


def png(x: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    rgb=bytes((x%256,(x//256)%256,0))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+rgb))+chunk(b'IEND',b'')


def fixture(root: Path):
    (root/'images').mkdir(parents=True)
    (root/'inputs').mkdir()
    rows=[]; labels=[]
    offset=0
    for split,count in handoff.SIZES.items():
        for j in range(count):
            pic=png(offset)
            imgsha=handoff.digest(pic)
            (root/'images'/imgsha).write_bytes(pic)
            row={'id':handoff.digest(f'id/{split}/{j}'.encode()),
                 'group':handoff.digest(f'group/{split}/{j}'.encode()),
                 'split':split,'image':imgsha,'scope':'public-scienceqa-e3-research',
                 'question':f'Synthetic independent question {split} {j}?',
                 'hint':'', 'choices':['A','B','C','D']}
            rows.append(row)
            if split!='test':
                labels.append({'id':row['id'],'group':row['group'],
                               'split':split,'label':j%4})
            offset+=1
    source=b''.join(handoff.canonical(r) for r in rows)
    fit=b''.join(handoff.canonical(r) for r in labels)
    sourcehash=handoff.digest(source);fithash=handoff.digest(fit)
    (root/'inputs/sources.jsonl').write_bytes(source)
    (root/'inputs/fit_labels.jsonl').write_bytes(fit)
    cohort={'schema':'hepta.e3-source-membership.v1',
            'dataset':handoff.SOURCE_DATASET,'revision':handoff.REVISION,
            'source_sha256':sourcehash,'counts':handoff.SIZES,
            'source_only':True,'chronological_future':False,
            'production_accepted':False}
    raw=handoff.canonical(cohort)
    (root/'inputs/cohort-before-labels.json').write_bytes(raw)
    seal={'dataset':handoff.SOURCE_DATASET,'dataset_revision':handoff.REVISION,
          'source_sha256':sourcehash,'fit_labels_sha256':fithash,
          'cohort_sha256':handoff.digest(raw),
          'private_test_labels_sha256':None,'raw_image_count':192,
          'model_inference_completed':False,
          'externally_independent_labels':False,'production_accepted':False}
    (root/'source-seals.json').write_bytes(handoff.canonical(seal))
    return sourcehash,fithash


class RealFileTreeContract(unittest.TestCase):
    def setUp(self):
        self._tmp=tempfile.TemporaryDirectory()
        self.root=Path(self._tmp.name)/'predictor'
        self.source,self.fit=fixture(self.root)
    def tearDown(self):
        self._tmp.cleanup()
    def check(self):
        return handoff.audit(self.root,self.source,self.fit)

    def test_full_192_source_128_fit_and_zero_held_admitted(self):
        x=self.check()
        self.assertEqual((x['source_count'],x['train_cal_count'],x['image_count'],x['test_label_count']),
                         (192,128,192,0))
        self.assertFalse(x['test_target_bytes_or_digest_admitted'])
        self.assertEqual(x['authority'],'DENY_ALL')
    def test_repeated_prepost_audits_identical_without_media_export(self):
        self.assertEqual(self.check(),self.check())
        self.assertFalse(self.check()['raw_model_media_uploaded'])
    def test_cosmetic_source_seal_rewrite_changes_byte_fingerprint(self):
        before=self.check()
        self.assertEqual(before['tree_fingerprint_profile'],handoff.FINGERPRINT_PROFILE)
        self.assertEqual(before['tree_fingerprint_file_count'],196)
        path=self.root/'source-seals.json'
        original=json.loads(path.read_bytes())
        pretty=(json.dumps(original,indent=2,sort_keys=True)+'\n').encode()
        self.assertNotEqual(pretty,path.read_bytes())
        path.write_bytes(pretty)
        after=self.check()
        self.assertNotEqual(before['tree_fingerprint'],after['tree_fingerprint'])
        self.assertNotEqual(before['original_source_receipt_sha256'],
                            after['original_source_receipt_sha256'])
        self.assertEqual(before['source_sha256'],after['source_sha256'])
        self.assertEqual(before['fit_sha256'],after['fit_sha256'])

    def test_cosmetic_cohort_rewrite_changes_byte_fingerprint(self):
        before=self.check()
        cohort=self.root/'inputs/cohort-before-labels.json'
        original=json.loads(cohort.read_bytes())
        pretty=(json.dumps(original,indent=2,sort_keys=True)+'\n').encode()
        self.assertNotEqual(pretty,cohort.read_bytes())
        cohort.write_bytes(pretty)
        seal=self.root/'source-seals.json'
        receipt=json.loads(seal.read_bytes())
        receipt['cohort_sha256']=handoff.digest(pretty)
        seal.write_bytes(handoff.canonical(receipt))
        after=self.check()
        self.assertNotEqual(before['tree_fingerprint'],after['tree_fingerprint'])
        self.assertNotEqual(before['original_source_receipt_sha256'],
                            after['original_source_receipt_sha256'])
        self.assertEqual(before['source_sha256'],after['source_sha256'])
        self.assertEqual(before['fit_sha256'],after['fit_sha256'])

    def test_mutation_between_inventory_and_receipt_parse_denied(self):
        # First input walk observes original receipt. The patched document
        # reader changes only JSON whitespace before the semantic read.
        # Without a second byte scan, the original audit accepted it.
        original_document = handoff.document
        seen = []
        def rewrite_after_scan(root, relative, size=32*1024*1024):
            if relative == 'source-seals.json':
                seal=self.root/'source-seals.json'
                contents=json.loads(seal.read_bytes())
                seal.write_text(json.dumps(contents,sort_keys=True,indent=2)+'\\n')
                seen.append(relative)
            return original_document(root, relative, size)
        with mock.patch.object(handoff,'document',side_effect=rewrite_after_scan):
            with self.assertRaises(handoff.ModelEntryDenied):
                self.check()
        self.assertEqual(seen,['source-seals.json'])

    def test_late_test_label_after_first_inventory_denied(self):
        # The original path-only/byte-bound first pass has already finished.
        # Add an unregistered target file as source metadata is parsed.
        original_document=handoff.document
        seen=[]
        def add_late_target(root, relative, size=32*1024*1024):
            if relative=='source-seals.json':
                (self.root/'inputs/test_labels.jsonl').write_bytes(b'secret\\n')
                seen.append(relative)
            return original_document(root,relative,size)
        with mock.patch.object(handoff,'document',side_effect=add_late_target):
            with self.assertRaises(handoff.ModelEntryDenied):
                self.check()
        self.assertEqual(seen,['source-seals.json'])

    def test_test_label_file_or_original_parquet_rejected(self):
        for relative in ('private_labels/test_labels.jsonl','inputs/test_labels.jsonl',
                         'inputs/validation-0000.parquet', 'images/debug.arrow'):
            path=self.root/relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'danger')
            try:
                with self.subTest(relative=relative),self.assertRaises(handoff.ModelEntryDenied):self.check()
            finally:path.unlink()
    def test_label_sha_visibility_and_false_model_authority_rejected(self):
        seal=self.root/'source-seals.json'
        original=seal.read_bytes()
        for key,value in [('private_test_labels_sha256','a'*64),
                          ('production_accepted',True),
                          ('model_inference_completed',True),
                          ('externally_independent_labels',True)]:
            doc=json.loads(original);doc[key]=value
            seal.write_bytes(handoff.canonical(doc))
            with self.subTest(key=key),self.assertRaises(handoff.ModelEntryDenied):self.check()
        seal.write_bytes(original)
        self.check()
    def test_training_label_changed_even_when_self_resigned_denied(self):
        p=self.root/'inputs/fit_labels.jsonl'
        data=p.read_bytes();records=[json.loads(x) for x in data.splitlines()]
        records[0]['label']=(records[0]['label']+1)%4
        new=b''.join(handoff.canonical(r) for r in records)
        p.write_bytes(new)
        seal=self.root/'source-seals.json';doc=json.loads(seal.read_bytes())
        doc['fit_labels_sha256']=handoff.digest(new)
        seal.write_bytes(handoff.canonical(doc))
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
    def test_source_record_extra_target_field_denied_even_if_full_hash_rewritten(self):
        p=self.root/'inputs/sources.jsonl';records=[json.loads(x) for x in p.read_bytes().splitlines()]
        records[128]['answer']=1
        rewritten=b''.join(handoff.canonical(x) for x in records)
        p.write_bytes(rewritten)
        self.source=handoff.digest(rewritten)
        cohort=self.root/'inputs/cohort-before-labels.json';co=json.loads(cohort.read_bytes())
        co['source_sha256']=self.source;cohort.write_bytes(handoff.canonical(co))
        seal=self.root/'source-seals.json';d=json.loads(seal.read_bytes())
        d['source_sha256']=self.source;d['cohort_sha256']=handoff.digest(cohort.read_bytes())
        seal.write_bytes(handoff.canonical(d))
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
    def test_image_tamper_even_if_root_seal_unchanged(self):
        name=next((self.root/'images').iterdir());name.write_bytes(name.read_bytes()+b'altered')
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
    def test_missing_image_rejected(self):
        next((self.root/'images').iterdir()).unlink()
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
    def test_symlink_and_hardlink_source_rejected(self):
        src=self.root/'inputs/sources.jsonl'
        src.rename(self.root/'inputs/sources.old')
        src.symlink_to(self.root/'inputs/sources.old')
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
        src.unlink();(self.root/'inputs/sources.old').rename(src)
        os.link(src,self.root/'inputs/foreign')
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
    def test_duplicate_json_fields_and_nonfinite_denied(self):
        for data in (b'{"a":1,"a":2}',b'{"x":NaN}',b'{"a":Infinity}'):
            with self.assertRaises(handoff.ModelEntryDenied):handoff.strict(data)
    def test_missing_or_duplicate_original_source_rows_denied(self):
        src=self.root/'inputs/sources.jsonl'
        lines=src.read_bytes().splitlines(keepends=True)
        src.write_bytes(b''.join(lines[:-1]))
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
        src.write_bytes(b''.join(lines[:-1]+[lines[0]]))
        with self.assertRaises(handoff.ModelEntryDenied):self.check()
    def test_prelabel_cohort_really_source_only(self):
        cohort=self.root/'inputs/cohort-before-labels.json';val=json.loads(cohort.read_bytes())
        val['source_only']=False;cohort.write_bytes(handoff.canonical(val))
        with self.assertRaises(handoff.ModelEntryDenied):self.check()


if __name__=='__main__':unittest.main()
