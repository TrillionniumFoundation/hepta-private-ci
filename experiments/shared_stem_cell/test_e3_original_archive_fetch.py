import unittest
from e3_original_archive_fetch import validate, storage_host, FetchReject, RUN_ID, SOURCE_HEAD, ARTIFACT_ID, ARTIFACT_NAME, ARCHIVE_SHA

def good():
    return {'id':RUN_ID,'head_sha':SOURCE_HEAD,'status':'completed','conclusion':'success'}, {
        'id':ARTIFACT_ID,'name':ARTIFACT_NAME,'expired':False,
        'workflow_run':{'id':RUN_ID},'size_in_bytes':29629,'digest':'sha256:'+ARCHIVE_SHA}

class FetchValidationTests(unittest.TestCase):
    def test_valid_original_metadata(self):
        self.assertIsNone(validate(*good()))
    def test_wrong_head_deny(self):
        r,a=good();r['head_sha']='f'*40
        with self.assertRaises(FetchReject):validate(r,a)
    def test_wrong_artifact_id_deny(self):
        r,a=good();a['id']=1
        with self.assertRaises(FetchReject):validate(r,a)
    def test_wrong_run_association_deny(self):
        r,a=good();a['workflow_run']['id']=1
        with self.assertRaises(FetchReject):validate(r,a)
    def test_expired_deny(self):
        r,a=good();a['expired']=True
        with self.assertRaises(FetchReject):validate(r,a)
    def test_digest_drift_deny(self):
        r,a=good();a['digest']='sha256:'+'0'*64
        with self.assertRaises(FetchReject):validate(r,a)
    def test_private_host_and_username_deny(self):
        for url in ('https://evil.example/evil.zip','http://blob.core.windows.net/f',
                    'https://x.blob.core.windows.net.evil.net/x','https://evil:pass@x.blob.core.windows.net/z'):
            with self.subTest(url=url),self.assertRaises(FetchReject):storage_host(url)
    def test_accepted_github_storage_subdomain(self):
        self.assertEqual(storage_host('https://a.blob.core.windows.net/file?sig=a'),'a.blob.core.windows.net')
        self.assertEqual(storage_host('https://b.githubusercontent.com/zip'),'b.githubusercontent.com')

if __name__=='__main__':unittest.main()
