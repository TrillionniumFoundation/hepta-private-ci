"""Sealed execution, independent audit and tamper contract."""
import json
import tempfile
import unittest
from pathlib import Path
from e12_study import execute, review, read_strict

class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root=Path(self.dir.name)

    def original(self):
        path=self.root/'execution.json'
        digest=execute(str(path))
        return path,digest

    def test_full_six_case_execute_independent_review(self):
        src,checksum=self.original()
        result=self.root/'review.json'
        digest=review(str(src),checksum,str(result))
        receipt,_=read_strict(str(result))
        self.assertEqual(len(digest),64)
        self.assertEqual(receipt['registered_cases'],6)
        self.assertTrue(receipt['all_discrete_certificates_and_complete_trees_verified'])
        self.assertFalse(receipt['natural_language_reasoning_gain'])
        self.assertFalse(receipt['production_accepted'])
        self.assertTrue(all(x['certificate_verified_on_entire_public_tree'] for x in receipt['decisions']))
        self.assertTrue(all(x['single_map_certified'] for x in receipt['decisions'] if x['coupling']=='0'))
        self.assertFalse(any(x['single_map_certified'] for x in receipt['decisions'] if x['coupling']=='1/3'))

    def test_create_only_rejects_overwrite(self):
        source,_=self.original()
        with self.assertRaises(FileExistsError):
            execute(str(source))

    def test_source_hash_change_fails(self):
        source,digest=self.original()
        with self.assertRaises(ValueError):
            review(str(source),'0'*64,str(self.root/'review.json'))
        text=source.read_text()
        source.write_text(text+' ')
        with self.assertRaises(ValueError):
            review(str(source),digest,str(self.root/'review.json'))

    def test_wrong_cost_or_overstated_single_map_is_rejected(self):
        source,_=self.original()
        data,_=read_strict(str(source))
        data['rows'][1]['cheap_single_map']['certified_at_same_tolerance']=True
        bad=self.root/'forged.json'
        bad.write_text(json.dumps(data))
        _,sha=read_strict(str(bad))
        with self.assertRaises(ValueError):
            review(str(bad),sha,str(self.root/'review.json'))

    def test_tampered_y_but_new_checksum_still_rejected(self):
        source,_=self.original()
        data,_=read_strict(str(source))
        data['rows'][5]['certificate']['trace']['states'][0]['y']='0'
        bad=self.root/'forged.json'
        bad.write_text(json.dumps(data))
        _,sha=read_strict(str(bad))
        with self.assertRaises(ValueError):
            review(str(bad),sha,str(self.root/'review.json'))

    def test_faked_cpu_and_extra_case_rejected(self):
        source,_=self.original()
        data,_=read_strict(str(source))
        data['rows'][0]['cpu_certified_ns'][0]=0
        bad=self.root/'forged.json'
        bad.write_text(json.dumps(data))
        _,sha=read_strict(str(bad))
        with self.assertRaises(ValueError):
            review(str(bad),sha,str(self.root/'review.json'))
        data['rows'][0]['cpu_certified_ns'][0]=1
        data['rows'].append(data['rows'][-1])
        bad.write_text(json.dumps(data))
        _,sha=read_strict(str(bad))
        with self.assertRaises(ValueError):
            review(str(bad),sha,str(self.root/'review.json'))

    def test_duplicate_key_and_nonfinite_json_rejected(self):
        src=self.root/'malformed.json'
        for text in ('{"x":1,"x":2}','{"x":NaN}','{}'):
            src.write_text(text)
            with self.subTest(text=text):
                if text=='{}':
                    with self.assertRaises(ValueError):
                        review(str(src),read_strict(str(src))[1],str(self.root/'review.json'))
                else:
                    with self.assertRaises(ValueError):
                        read_strict(str(src))

if __name__=='__main__':
    unittest.main()
