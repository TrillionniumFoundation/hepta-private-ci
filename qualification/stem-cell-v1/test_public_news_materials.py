import csv
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from public_news_materials import (acquire_news, select_split, verify_file,
                                   validate_disjoint, prepare_news)


def make_csv(path, count=8):
    with Path(path).open('w', newline='') as stream:
        writer=csv.writer(stream)
        for i in range(count):
            for label in range(1,5):
                writer.writerow([label,f'Title {label} {i}',f'Description, "quoted" {label} {i}'])


class PublicNewsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'train.csv'; make_csv(self.path)

    def test_selection_is_deterministic_balanced_and_label_free(self):
        a,y=select_split(self.path,'train',3,expected_rows=32)
        b,z=select_split(self.path,'train',3,expected_rows=32)
        self.assertEqual((a,y),(b,z))
        self.assertEqual([y.count(i) for i in range(4)],[3]*4)
        self.assertTrue(all('label' not in r and 'quoted' in r['state'] for r in a))
        self.assertEqual(len({r['sample_id'] for r in a}),12)

    def test_smaller_sample_is_subset_not_model_adaptive(self):
        a,_=select_split(self.path,'train',2)
        b,_=select_split(self.path,'train',4)
        self.assertTrue({r['sample_id'] for r in a}<={r['sample_id'] for r in b})

    def test_invalid_csv_missing_class_count_and_bool_quota_reject(self):
        with self.assertRaises(ValueError): select_split(self.path,'train',True)
        with self.assertRaises(ValueError): select_split(self.path,'test',1,expected_rows=3)
        for text in ('1,title,desc\n','5,title,desc\n','1,title\n','1,,description\n'):
            self.path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                select_split(self.path,'train',2)

    def test_overlong_text_fails_instead_of_dropping_the_record(self):
        self.path.write_text('1,title,'+'x'*65537+'\n')
        with self.assertRaises(ValueError): select_split(self.path,'train',1)

    def test_duplicates_normalized_content_and_eval_labels_reject(self):
        train,_=select_split(self.path,'train',1)
        for change in ('duplicate','normalized','label'):
            other=dict(train[0]);other['sample_id']='other'
            if change=='normalized': other['state']=' '.join(other['state'].upper().split())
            if change=='label': other['label']=1;other['state']='different'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_disjoint(train,[other])

    def test_git_blob_verification_detects_same_length_mutation_and_symlink(self):
        raw=self.path.read_bytes();size=len(raw)
        blob=hashlib.sha1(f'blob {size}\0'.encode()+raw).hexdigest()
        verify_file(self.path,size,blob)
        self.path.write_bytes(b'x'+raw[1:])
        with self.assertRaises(ValueError): verify_file(self.path,size,blob)
        self.path.write_bytes(raw)
        link=self.root/'linked';link.symlink_to(self.path)
        with self.assertRaises(ValueError): verify_file(link,size,blob)

    def test_acquisition_is_bounded_exclusive_and_failed_material_is_not_consumed(self):
        raw=b'abc';url='https://raw.githubusercontent.com/example'
        class Response(io.BytesIO):
            def geturl(self): return 'not-the-requested-url'
        output=self.root/'download'
        with patch('public_news_materials.urlopen',return_value=Response(raw)):
            with self.assertRaises(ValueError): acquire_news(output)
        self.assertTrue((output/'FAILED.json').exists())
        with self.assertRaises(FileExistsError): acquire_news(output)
        with self.assertRaises(ValueError): prepare_news(output)

    def test_acquisition_verifies_the_transferred_bytes(self):
        raw=b'abc';blob=hashlib.sha1(b'blob 3\0'+raw).hexdigest()
        class Response(io.BytesIO):
            def geturl(self): return self.url
        def open_url(url,timeout):
            response=Response(raw);response.url=url;return response
        with patch('public_news_materials.FILES',{'test.csv':(3,blob)}), patch('public_news_materials.urlopen',side_effect=open_url):
            result=acquire_news(self.root/'download')
        self.assertEqual((result/'test.csv').read_bytes(),raw)
        self.assertTrue((result/'material.json').is_file())


if __name__=='__main__':
    unittest.main()
