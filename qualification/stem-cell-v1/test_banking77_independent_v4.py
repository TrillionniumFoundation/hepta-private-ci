"""Source-only and intentionally adversarial independent learning-audit tests."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import banking77_independent_v4 as v4


def source_csv(rows):
    stream=io.StringIO(newline='')
    wr=csv.writer(stream);wr.writerow(['text','category']);wr.writerows(rows)
    return stream.getvalue().encode()


class V4AuditTests(unittest.TestCase):
    def test_hashes_and_gold_from_real_source_are_not_self_authenticating(self):
        train=[];test=[]
        for label in v4.INTENTS:
            for i in range(18):train.append((f'{label} example fit {i}',label))
            for i in range(10):test.append((f'{label} example heldout {i}',label))
        train=source_csv(train);test=source_csv(test)
        fake_sha={'train':v4.digest(train),'test':v4.digest(test)}
        fake_blob={k:hashlib.sha1(b'blob '+str(len(d)).encode()+b'\0'+d).hexdigest()
                   for k,d in [('train',train),('test',test)]}
        with patch.dict(v4.DATA_SHA,fake_sha),patch.dict(v4.DATA_BLOB,fake_blob):
            proof=v4.original_source_selection(train,test)
            self.assertEqual(len(proof['selected']['fit']),64)
            self.assertEqual(len(proof['selected']['heldout']),32)
            self.assertEqual([len([x for x in proof['gold'].values() if x==i]) for i in range(4)],[8]*4)
            with self.assertRaises(v4.EvidenceError):
                v4.original_source_selection(train+b'alter',test)

    def test_closed_zip_outer_digest_and_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'canary.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('a','content')
            with self.assertRaises(v4.EvidenceError):v4.open_pinned_archive(path)
            with self.assertRaises(v4.EvidenceError):
                v4.open_pinned_archive(path, expected_digest=v4.digest(path.read_bytes()))
            path.unlink()
            with zipfile.ZipFile(path,'w') as z:z.writestr('a','1');z.writestr('a','2')
            with self.assertRaises(v4.EvidenceError):
                v4.open_pinned_archive(path, expected_digest=v4.digest(path.read_bytes()))

    def test_logits_and_duplicate_rows(self):
        p=[{'id':f'heldout:{i}','before_logits':[0.,0.,0.,0.],
            'after_logits':[2.,0.,0.,0.]} for i in range(32)]
        gold={f'heldout:{i}':i//8 for i in range(32)}
        result,raw=v4.evaluate(p,gold,'after')
        self.assertEqual(result['correct'],8)
        self.assertEqual(len(raw),32)
        p[0]['id']=p[1]['id']
        with self.assertRaises(v4.EvidenceError):v4.evaluate(p,gold,'after')
        p[0]['id']='heldout:0';p[1]['after_logits'][0]=float('nan')
        with self.assertRaises(v4.EvidenceError):v4.evaluate(p,gold,'after')

    def test_exact_mcnemar_requires_pairing(self):
        a={'a':1,'b':0,'c':1,'d':0};b={'a':0,'b':1,'c':1,'d':0}
        r=v4.mcnemar(a,b)
        self.assertEqual((r['first_only'],r['second_only']), (1,1))
        self.assertEqual(r['exact_two_sided_p'],1)
        with self.assertRaises(v4.EvidenceError):v4.mcnemar(a,{'a':1})

    def test_no_source_claim_from_historical_selected_metadata(self):
        z=Path('/mnt/data/banking77-real-cell-learning.zip')
        if not z.exists():self.skipTest('Original GitHub artifact not mounted on this host')
        files=v4.open_pinned_archive(z)
        r=v4.recount(files, None)
        self.assertEqual(r['arms']['dense16']['scores']['after']['correct'],23)
        self.assertEqual(r['arms']['sparse16_top2']['scores']['after']['correct'],17)
        self.assertFalse(r['source_bytes_independently_verified'])
        self.assertFalse(r['production_authorized'])
        self.assertEqual(r['dense_vs_sparse_after']['discordant'],14)
        corrupted=copy.deepcopy(files)
        name=v4.BASE+'trial/dense16/predictions.json'
        mutated=json.loads(files[name]);mutated[0]['after_logits'][0] += 1
        corrupted[name]=v4.canonical(mutated)
        with self.assertRaises(v4.EvidenceError):v4.recount(corrupted,None)


if __name__=='__main__':unittest.main()
