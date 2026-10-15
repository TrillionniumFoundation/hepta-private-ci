"""Offline Beans natural-source ingestion fixtures (drawn images, NOT real Beans evidence)."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from e2_beans_source import (
    TRAIN_SHA, TEST_SHA, DATA_REV, CLASSES, SourceError,
    canon, sha, select, prepare_rows, checked_parquet,
)


def fake_dataset(phase):
    results=[]
    for label in range(3):
        for i in range(16):
            img=Image.new('RGB',(64,64),((i*13+label*47+ (1 if phase=='test' else 0))%255,
                                          (i*17+label*53)%255,(i*31+label*29)%255))
            buff=io.BytesIO();img.save(buff,format='PNG')
            results.append({'image_file_path':f'/external/{phase}/{CLASSES[label]}/private-path-{i}.png',
                            'image':{'bytes':buff.getvalue(),'path':None},'labels':label})
    return results

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=fake_dataset('train')
        cls.test=fake_dataset('test')

    def panel(self,train=None,test=None):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)/'panel'
        manifest=prepare_rows(train if train is not None else self.train,
                              test if test is not None else self.test,root)
        return root,manifest

    def test_exact_dataset_revision_identity(self):
        self.assertEqual(len(DATA_REV),40)
        self.assertEqual(len(TRAIN_SHA),64)
        self.assertEqual(len(TEST_SHA),64)

    def test_real_split_case_counts_and_scope(self):
        root,manifest=self.panel()
        self.assertEqual(manifest['train_cases'],36)
        self.assertEqual(manifest['test_cases'],24)
        self.assertTrue(manifest['phase_time_is_not_original_timestamp'])
        self.assertEqual(manifest['authority'],'DENY_ALL')
        self.assertFalse(manifest['production_accepted'])

    def test_all_future_labels_and_test_parquet_sha_withheld(self):
        root,m=self.panel()
        src=(root/'source-manifest.json').read_bytes()
        target=json.loads((root/'withheld'/'target-manifest.json').read_bytes())
        self.assertEqual(set(m['file_sha256s']),{
            'train_images.jsonl','future_images.jsonl','train_anchors.jsonl','train_class.jsonl'})
        self.assertEqual(set(target['file_sha256s']),{
            'future_caption_targets.jsonl','future_class_targets.jsonl'})
        self.assertEqual(target['source_manifest_sha256'],sha(src))
        self.assertEqual(target['original_test_parquet_sha256'],TEST_SHA)
        self.assertNotIn(TEST_SHA.encode(),src)
        for digest in target['file_sha256s'].values():
            self.assertNotIn(digest.encode(),src)

    def test_train_text_only_and_future_source_only(self):
        root,_=self.panel()
        train=[json.loads(line) for line in (root/'source'/'train_anchors.jsonl').read_bytes().splitlines()]
        future=[json.loads(line) for line in (root/'source'/'future_images.jsonl').read_bytes().splitlines()]
        self.assertTrue(all('target_text' in r for r in train))
        self.assertTrue(all('class_label' not in r and 'target_text' not in r for r in future))
        self.assertTrue(all('condition' in r and r['condition']=='vision_required' for r in future))
        self.assertFalse(any('/external/' in json.dumps(r) for r in future))
        self.assertTrue(all('private-path' not in json.dumps(r) for r in future))

    def test_source_ids_unique_without_class_labels(self):
        root,_=self.panel()
        records=[]
        for name in ('train_images.jsonl','future_images.jsonl'):
            records += [json.loads(line) for line in (root/'source'/name).read_bytes().splitlines()]
        self.assertEqual(len({r['case_id'] for r in records}),60)
        self.assertEqual(len({r['image_sha256'] for r in records}),60)
        self.assertEqual(len({r['group_id'] for r in records}),60)
        self.assertTrue(all(not any(label in r['case_id'] for label in CLASSES) for r in records))

    def test_malformed_label_rejected(self):
        bad=copy.deepcopy(self.train)
        bad[0]['labels']=True
        with self.assertRaises(SourceError):select(bad,'train')

    def test_external_path_only_rejected(self):
        bad=copy.deepcopy(self.train)
        bad[0]['image']={'bytes':None,'path':'https://example.com/secret'}
        with self.assertRaises(SourceError):select(bad,'train')

    def test_extra_columns_rejected(self):
        bad=copy.deepcopy(self.train)
        bad[0]['answer']='leaked'
        with self.assertRaises(SourceError):select(bad,'train')

    def test_duplicate_selected_image_rejected(self):
        bad=copy.deepcopy(self.train)
        for row in bad:
            if row['labels']==0:
                row['image']['bytes']=bad[0]['image']['bytes']
        with self.assertRaises(SourceError):select(bad,'train')

    def test_original_byte_digest_required(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'data.parquet';path.write_bytes(b'fake parquet file')
            with self.assertRaises(SourceError):checked_parquet(path,TRAIN_SHA,150_000_000)

    def test_no_mutation_of_source_input(self):
        original=copy.deepcopy(self.test)
        self.panel()
        self.assertEqual(self.test,original)

    def test_write_once_dataset_dir(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'out'
            prepare_rows(self.train,self.test,root)
            with self.assertRaises(SourceError):prepare_rows(self.train,self.test,root)

if __name__=='__main__':unittest.main()
