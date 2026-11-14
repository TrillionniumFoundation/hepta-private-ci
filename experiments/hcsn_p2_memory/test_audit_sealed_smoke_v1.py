"""Original-byte receipt validation tests; live CPU runs are not repeated."""
import copy
from pathlib import Path
import unittest
from .audit_sealed_smoke_v1 import audit_bundle,verify_raw_files,UnresolvedSealedSmoke,ARMS,ARCHIVE_FILE

P=Path(__file__).with_name(ARCHIVE_FILE)

class SealedSmokeAuditTests(unittest.TestCase):
    def test_exact_original_archive_and_negative_ood(self):
        result=audit_bundle(P)
        self.assertTrue(result['archive_original_bytes_verified'])
        self.assertEqual(result['records'],2)
        self.assertLess(result['timed_minus_aggregate_ood_pp'],-40)
        self.assertFalse(result['all_scientific_blockers_closed'])
        self.assertFalse(result['provenance_authenticated'])

    def test_archive_tamper_fail_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.gz.b64';b=P.read_bytes();p.write_bytes(b[:15]+(b'X' if b[15:16]!=b'X' else b'Y')+b[16:])
            with self.assertRaises(UnresolvedSealedSmoke):audit_bundle(p)

    def test_unsealed_forged_source_or_output_refused(self):
        import tarfile,io,gzip,base64,json
        raw=gzip.decompress(base64.b64decode(P.read_text()))
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            files={x.name:t.extractfile(x).read() for x in t.getmembers()}
        for tamper in ('missing','raw','receipt'):
            d=copy.deepcopy(files)
            if tamper=='missing':d.pop('aggregate.stdout.json')
            if tamper=='raw':
                key=ARMS['aggregate_count']+'.json';d[key]=d[key].replace(b'4132',b'4133')
            if tamper=='receipt':
                key='timed.stdout.json';j=json.loads(d[key]);j['all_scientific_blockers_closed']=True;d[key]=json.dumps(j).encode()
            with self.subTest(tamper=tamper),self.assertRaises(UnresolvedSealedSmoke):verify_raw_files(d)

if __name__=='__main__':unittest.main()
