"""Offline V9 source, provenance and failure-closed science-admission tests.

No fake pretrained execution. When ORIGINAL_BEANS_V9_* paths are present,
additional tests open the authentic immutable GitHub Actions source/model ZIPs.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import original_beans_v9 as v
from multimodal_token_bridge_v8 import to_physical_bank, Denied


def parquet_rows():
    rows = []
    for index in range(120):
        label = index % 3
        image = b'\xff\xd8' + b'beans' + index.to_bytes(4, 'little') + bytes([index]) * 75
        rows.append({'image_file_path': None, 'image': {'bytes': image, 'path': None}, 'labels':label})
    return rows


class V9ContractTests(unittest.TestCase):
    def test_predeclared_original_pins(self):
        self.assertEqual(v.ORIGINAL_RUN_ID, 38680856403)
        self.assertEqual(v.FEATURE_ARTIFACT_ID, 11949168280)
        self.assertEqual(v.DATA_REV, '27aa014ce09b193e1a6f58112d4a66e0eddb69c5')
        self.assertEqual(len(v.MODEL_REV), 40)
        self.assertEqual(len(v.SOURCE_ZIP_SHA), 64)
        self.assertEqual(v.WIDTH, 384)

    def test_source_token_bounded_shape(self):
        self.assertEqual(v._cell_type('beans-one'), v._cell_type('beans-one'))
        self.assertIn(v._cell_type('beans-other'), {'type0', 'type1'})
        self.assertEqual(len({v._cell_type('beans-'+str(x)) for x in range(50)}), 2)
        self.assertNotEqual(v._inactive_digest('text','encoder'),v.WEIGHTS_SHA)

    def test_noncanonical_json_rejected(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'\xff'):
            with self.subTest(raw=raw),self.assertRaises(v.Reject):
                v.json_strict(raw)

    def test_reject_noncanonical_jsonl(self):
        for raw in (b'{"z":1,"a":2}\n', b'{"x":1}\n\n', b'{"x":1}', b'\n'):
            with self.subTest(raw=raw),self.assertRaises(v.Reject):
                v.lines_strict(raw)

    def test_canonical_lines(self):
        obj = {'b':2,'a':1}
        self.assertEqual(v.lines_strict(v.canonical(obj)),[obj])

    def test_publisher_selection_has_expected_class_counts(self):
        rows = v.select_parquet(parquet_rows(),'test')
        self.assertEqual(len(rows),24)
        self.assertEqual([r[0] for r in rows],[0]*8+[1]*8+[2]*8)
        self.assertEqual(len({r[2] for r in rows}),24)
        self.assertEqual(len(v.select_parquet(parquet_rows(),'train')),36)

    def test_publisher_selection_label_mutation_detectable(self):
        rows = parquet_rows()
        selected = v.select_parquet(rows,'test')
        index=selected[0][1]
        rows[index]['labels'] = (rows[index]['labels']+1)%3
        self.assertNotEqual(selected,v.select_parquet(rows,'test'))

    def test_publisher_selection_rejects_label_or_path_forgery(self):
        for field in ('labels','image'):
            rows = parquet_rows()
            rows[0][field] = 'evil'
            with self.subTest(field=field),self.assertRaises(v.Reject):
                v.select_parquet(rows,'test')

    def test_not_a_date_based_future(self):
        self.assertEqual(v.TASK,'healthy_vs_diseased_binary_reanalysis')
        self.assertEqual(v.SCOPE,'hepta-e2-natural-beans-retrospective-research')

    def test_zip_parent_traversal_rejected_after_real_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'archive.zip'
            with ZipFile(path,'w') as z:
                z.writestr('../oops', b'wrong')
            with self.assertRaises(v.Reject):
                v.PinnedZip(path,v.sha(path.read_bytes()))

    def test_zip_duplicate_entry_rejected(self):
        import warnings
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'archive.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with ZipFile(path,'w') as z:
                    z.writestr('x',b'hello')
                    z.writestr('x',b'world')
            with self.assertRaises(v.Reject):
                v.PinnedZip(path,v.sha(path.read_bytes()))

    def test_zip_checksum_rejected_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'z.zip'
            with ZipFile(path,'w') as z:z.writestr('allowed',b'ok')
            with self.assertRaises(v.Reject):
                v.PinnedZip(path,'0'*64)

    def test_zip_symlink_rejected(self):
        from zipfile import ZipInfo
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'z.zip'
            entry=ZipInfo('linked')
            entry.create_system=3
            entry.external_attr=(0o120777)<<16
            with ZipFile(path,'w') as z:z.writestr(entry,b'target')
            with self.assertRaises(v.Reject):
                v.PinnedZip(path,v.sha(path.read_bytes()))

    def test_exact_known_sha_lengths(self):
        for field in ('SOURCE_ZIP_SHA','FEATURE_ZIP_SHA','TARGET_ZIP_SHA',
                      'WEIGHTS_SHA','PREPROCESS_SHA','TRAIN_SHA','TEST_SHA'):
            token=getattr(v,field)
            self.assertEqual(len(token),64)
            self.assertTrue(all(c in '0123456789abcdef' for c in token))

    def test_fail_on_missing_archive(self):
        with self.assertRaises(v.Reject):
            v.stage('/nonexistent/isolated-source.zip','/nonexistent/features.zip')

    def test_publisher_parquet_reselect_identity(self):
        rows=parquet_rows()
        select=v.select_parquet(rows,'test')
        label,index,imgsha=select[0]
        ident='beans-'+v.sha(v.canonical(['hepta.beans.real-image.v1','future',index,imgsha]))[:24]
        self.assertTrue(ident.startswith('beans-'))
        self.assertEqual(len(ident),30)
        self.assertEqual(label,0)

    def test_download_must_refuse_empty_authorization(self):
        with self.assertRaises(v.Reject):
            v.download_original('source','/no/file','')

    def test_download_must_refuse_unknown_kind(self):
        with self.assertRaises(v.Reject):
            v.download_original('models-elsewhere','/no/file','x'*40)


class OriginalArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=os.environ.get('HDCF_BEANS_ORIGINAL_SOURCE_ZIP')
        cls.features=os.environ.get('HDCF_BEANS_ORIGINAL_FEATURE_ZIP')
        cls.targets=os.environ.get('HDCF_BEANS_ORIGINAL_TARGET_ZIP')

    def _original(self):
        if not self.source or not self.features or not self.targets:
            self.skipTest('original immutable artifacts are not present; source-only tests above apply')

    def test_actual_60_real_image_feature_contract(self):
        self._original()
        bank=v.stage(self.source,self.features)
        self.assertEqual(len(bank['fit']),36)
        self.assertEqual(len(bank['held']),24)
        self.assertEqual(bank['dimension'],384)
        self.assertTrue(all('target' not in row for row in bank['held']))
        self.assertEqual({row['target'] for row in bank['fit']},{0,1})

    def test_original_source_and_withheld_admitted_only_in_reviewer(self):
        self._original()
        _,fit,held,lab=v._source_targets(self.source,self.targets)
        self.assertEqual(len(fit),36)
        self.assertEqual(len(held),24)
        self.assertEqual(len(lab['held']),24)
        self.assertEqual(sum(x['class_label']=='healthy' for x in lab['held'].values()),8)

    def test_original_derived_bank_rejects_label_visibility(self):
        self._original()
        bank=v.stage(self.source,self.features)
        bank['held'][0]['target']=1
        try:
            from physical_bank import Denied as OldDenied, validate_bundle
        except ModuleNotFoundError:
            self.skipTest('existing HDCF physical_bank is only available in stacked GitHub checkout')
        with self.assertRaises(OldDenied):validate_bundle(bank)

    def test_original_held_source_disjoint(self):
        self._original()
        bank=v.stage(self.source,self.features)
        self.assertFalse({r['family'] for r in bank['fit']}&{r['family'] for r in bank['held']})
        self.assertFalse({r['id'] for r in bank['fit']}&{r['id'] for r in bank['held']})

    def test_original_zip_mutation_fails_before_pretrained_features(self):
        self._original()
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'mutated.zip'
            raw=Path(self.features).read_bytes()
            dest.write_bytes(raw[:-8]+bytes([raw[-8]^1])+raw[-7:])
            with self.assertRaises(v.Reject):v.stage(self.source,dest)


if __name__=='__main__':
    unittest.main()
