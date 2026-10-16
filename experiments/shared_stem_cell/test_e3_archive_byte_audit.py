"""Source-only archive-envelope and original predictor-identity negative controls.

These fixtures are not real model/TEST scoring; the separately executed
historical original ZIP test requires actual downloaded pinned archives.
"""
import copy
import hashlib
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
import zipfile

import e3_archive_byte_audit as a

def fixture():
    rows=[];past=[]
    for i in range(64):
        rid=f'{i+1:064x}';group=f'{i+101:064x}';source=f'{i+201:064x}'
        rows.append({'id':rid,'group':group,'source_input_sha256':source,
                     'probabilities':[0.4,0.3,0.2,0.1]})
        past.append({'id':rid,'group':group,'source_input_sha256':source,
                     'arms':{'text_only':[0.4,0.3,0.2,0.1],
                             'train_gate':[0.4,0.3,0.2,0.1],
                             'image_masked':[0.4,0.3,0.2,0.1]}})
    ocr={'schema':'hepta.e3.ocr-granite-physical.v1',
         'source_sha256':a.SOURCE,'authority':'DENY_ALL',
         'production_accepted':False,'stem_selected':False,
         'signed_model_origin_authenticated':False,
         'model':{'repo':a.GRANITE[0],'revision':a.GRANITE[1],
                  'pipeline_digest':'b'*64},
         'ocr_engine':'tesseract','physical_ocr_calls':192,
         'physical_granite_forward_batches':60,
         'actual_original_pretrained_forward_self_reported':True,
         'ocr_nonempty_cases':110,'rows':rows}
    return ocr,a.preds(past)

class ArchiveContract(unittest.TestCase):
    def test_actual_archives_not_used_as_test_labels(self):
        self.assertFalse(hasattr(a,'HELD_LABELS'))
        self.assertFalse(hasattr(a,'LABEL_SHA'))
        self.assertEqual(a.ORIGINAL_SHA if hasattr(a,'ORIGINAL_SHA') else a.SOURCE,a.SOURCE)

    def test_actual_ocr_contract_synthetic(self):
        ocr,refs=fixture()
        data=json.dumps(ocr).encode()
        parsed,rows=a.check_ocr(data,refs,require_historical_original=True)
        self.assertEqual(parsed['ocr_nonempty_cases'],110)
        self.assertEqual(len(rows),64)

    def test_ocr_wrong_publisher_denied(self):
        ocr,refs=fixture();ocr['model']['repo']='not IBM'
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_wrong_revision_denied(self):
        ocr,refs=fixture();ocr['model']['revision']='f'*40
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_wrong_source_denied(self):
        ocr,refs=fixture();ocr['source_sha256']='f'*64
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_fake_promotion_denied(self):
        ocr,refs=fixture();ocr['production_accepted']=True
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_fake_forward_denied(self):
        ocr,refs=fixture();ocr['physical_granite_forward_batches']=0
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_group_swap_denied(self):
        ocr,refs=fixture();ocr['rows'][0]['group']='e'*64
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_duplicate_row_denied(self):
        ocr,refs=fixture();ocr['rows'][0]['id']=ocr['rows'][1]['id']
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_ocr_target_bearing_value_denied(self):
        ocr,refs=fixture();ocr['rows'][0]['probabilities']=[True,0,0,0]
        with self.assertRaises(a.OriginalZipDenied):a.check_ocr(json.dumps(ocr).encode(),refs)

    def test_nonfinite_and_duplicate_json_denied(self):
        for value in (b'{"a":NaN}',b'{"a":1e999}',b'{"a":1,"a":2}'):
            with self.subTest(value=value),self.assertRaises(a.OriginalZipDenied):a.parse(value)

    def _zip(self,members):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'a.zip'
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as f:
            for k,v in members:
                f.writestr(k,v)
        return path,a.hash_bytes(path.read_bytes())

    def test_bounded_original_numerical_zip_fixture(self):
        path,digest=self._zip([('result.json',b'{"authority":"DENY_ALL"}')])
        self.assertEqual(set(a.original_zip(path,digest)),{'result.json'})

    def test_wrong_zip_sha_denied(self):
        path,_=self._zip([('result.json',b'{}')])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,'a'*64)

    def test_duplicate_zip_member_denied(self):
        path,digest=self._zip([('result.json',b'{}'),('result.json',b'{"x":1}')])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,digest)

    def test_zip_path_traversal_denied(self):
        path,digest=self._zip([('../result.json',b'{}')])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,digest)

    def test_zip_nested_parent_components_denied(self):
        path,digest=self._zip([('sub/../result.json',b'{}')])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,digest)

    def test_zip_symlink_denied(self):
        zi=zipfile.ZipInfo('result.json');zi.create_system=3
        zi.external_attr=(stat.S_IFLNK | 0o777)<<16
        path,digest=self._zip([(zi,b'outside')])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,digest)

    def test_missing_original_numerical_zip_member_denied(self):
        path,digest=self._zip([('result.json',b'{}')])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,digest,expected_members={'other.json'})

    def test_incorrect_zip_member_count_denied(self):
        path,digest=self._zip([])
        with self.assertRaises(a.OriginalZipDenied):a.original_zip(path,digest)

    def test_zip_rejects_non_numeric_media_extensions(self):
        path,digest=self._zip([('image.jpg',b'fake')])
        with self.assertRaises(a.OriginalZipDenied):
            a.original_zip(path,digest,expected_members={'result.json'})

if __name__=='__main__':unittest.main()
