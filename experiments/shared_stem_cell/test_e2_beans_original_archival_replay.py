"""Hermetic negative and roundtrip tests. Images/models are synthetic fixtures."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from e2_beans_original_zip_review import Reject,canon,digest
from test_e2_beans_original_zip_review import fake_archives,zipup
from e2_beans_original_replay import prepare,finish
from e2_beans_independent_svd_oracle import independently_fit, independent_svd_parity
from e2_beans_original_artifact_fetch import (FetchError,ORIGINAL,SOURCE_HEAD,
                                               validate_run_and_inventory,download_verified)

class OriginalReplayTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.members=fake_archives()
        self.rebuild()

    def rebuild(self):
        self.paths={}
        self.pins={}
        for k,data in self.members.items():
            path=self.root/(k+'.zip')
            self.pins[k]=zipup(data,path)
            self.paths[k]=path

    def seal(self):
        out=self.root/'new-seal'
        status=prepare(self.paths['source'],self.pins['source'],
                       self.paths['producer'],self.pins['producer'],out)
        self.assertFalse(status['withheld_labels_opened'])
        return out,status

    def finish(self,out):
        return finish(self.paths,self.pins,out/'probe_model.json',
                      digest((out/'probe_model.json').read_bytes()),
                      out/'probe_predictions.json',
                      digest((out/'probe_predictions.json').read_bytes()),
                      self.root/'score.json')

    def test_complete_two_process_fixture_replay(self):
        out,receipt=self.seal()
        self.assertEqual(receipt['authority'],'DENY_ALL')
        result=self.finish(out)
        self.assertEqual(result['original_cases'],24)
        self.assertEqual(result['vision_ridge_correct'],8)
        self.assertEqual(result['fitted_bridge_correct'],24)
        report=json.loads((self.root/'score.json').read_bytes())
        self.assertFalse(report['natural_task_accepted'])
        self.assertEqual(report['svd_oracle']['train_cases'],36)
        self.assertEqual(report['svd_oracle']['future_cases'],24)
        self.assertTrue(report['svd_oracle']['independently_replayed_all_predictions'])
        self.assertFalse(report['production_accepted'])

    def test_same_source_seal_is_create_only(self):
        self.seal()
        with self.assertRaises(Reject):self.seal()

    def test_repeat_scoring_is_create_only(self):
        out,_=self.seal()
        self.finish(out)
        with self.assertRaises(Reject):self.finish(out)

    def test_wrong_source_pin_fails_before_training(self):
        with self.assertRaises(Reject):prepare(self.paths['source'],'0'*64,
                       self.paths['producer'],self.pins['producer'],self.root/'bad-seal')

    def test_future_labels_in_producer_fail_before_fitting(self):
        self.members['producer']['future_class_targets.jsonl']=b'private test\n'
        self.rebuild()
        with self.assertRaises(Reject):self.seal()

    def test_future_labels_in_source_fail_before_fitting(self):
        self.members['source']['future_caption_targets.jsonl']=b'private test\n'
        self.rebuild()
        with self.assertRaises(Reject):self.seal()

    def test_mutated_seal_rejected_even_with_matching_new_file_hash(self):
        out,_=self.seal()
        m=json.loads((out/'probe_model.json').read_bytes())
        m['weights'][0][0] += 0.2
        (out/'probe_model.json').write_bytes(canon(m))
        with self.assertRaises(Reject):self.finish(out)

    def test_prediction_tamper_rejected_even_when_hash_updated(self):
        out,_=self.seal()
        p=json.loads((out/'probe_predictions.json').read_bytes())
        p['rows'][0]['predicted_label']='healthy' if p['rows'][0]['predicted_label']!='healthy' else 'bean_rust'
        (out/'probe_predictions.json').write_bytes(canon(p))
        with self.assertRaises(Reject):self.finish(out)

    def test_label_tamper_in_withheld_rejected(self):
        out,_=self.seal()
        labels=[json.loads(line) for line in self.members['withheld']['future_class_targets.jsonl'].splitlines()]
        labels[0]['class_label']='healthy' if labels[0]['class_label']!='healthy' else 'bean_rust'
        self.members['withheld']['future_class_targets.jsonl']=b''.join(canon(x) for x in labels)
        self.rebuild()
        with self.assertRaises(Reject):self.finish(out)

    def test_duplicate_original_role_zip_path_rejected(self):
        out,_=self.seal()
        paths=self.paths.copy();paths['withheld']=paths['source']
        with self.assertRaises(Reject):finish(paths,self.pins,out/'probe_model.json',
                      digest((out/'probe_model.json').read_bytes()),
                      out/'probe_predictions.json',
                      digest((out/'probe_predictions.json').read_bytes()),self.root/'score.json')

    def test_original_fitting_does_not_depend_on_future_zip(self):
        original=__import__('e2_beans_original_zip_review')
        src=original.original_zip(self.paths['source'],self.pins['source'])
        prod=original.original_zip(self.paths['producer'],self.pins['producer'])
        a,b=independently_fit(src,prod)
        self.assertEqual(a.shape,(384,3))
        self.assertEqual(b.shape,(3,))

    def test_falsified_production_authority_rejected(self):
        out,_=self.seal()
        data=json.loads((out/'probe_model.json').read_bytes())
        data['production_accepted']=True
        (out/'probe_model.json').write_bytes(canon(data))
        with self.assertRaises(Reject):self.finish(out)

class FetcherTests(unittest.TestCase):
    def test_completed_success_exact_head_and_roles(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        run={'id':42,'status':'completed','conclusion':'success','head_sha':SOURCE_HEAD}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':False,
                             'workflow_run':{'id':42}} for role,n in ids.items()]}
        self.assertTrue(validate_run_and_inventory(run,items,42,ids))

    def test_queue_never_admitted(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        run={'id':42,'status':'queued','conclusion':None,'head_sha':SOURCE_HEAD}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':False,
                             'workflow_run':{'id':42}} for role,n in ids.items()]}
        with self.assertRaises(FetchError):validate_run_and_inventory(run,items,42,ids)

    def test_wrong_exact_source_ref_fail_closed(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        run={'id':42,'status':'completed','conclusion':'success','head_sha':'f'*40}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':False,
                             'workflow_run':{'id':42}} for role,n in ids.items()]}
        with self.assertRaises(FetchError):validate_run_and_inventory(run,items,42,ids)

    def test_mixed_original_action_runs_rejected(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        run={'id':42,'status':'completed','conclusion':'success','head_sha':SOURCE_HEAD}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':False,
                             'workflow_run':{'id':43 if role=='withheld' else 42}} for role,n in ids.items()]}
        with self.assertRaises(FetchError):validate_run_and_inventory(run,items,42,ids)

    def test_expired_archive_rejected(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        run={'id':42,'status':'completed','conclusion':'success','head_sha':SOURCE_HEAD}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':role=='producer',
                             'workflow_run':{'id':42}} for role,n in ids.items()]}
        with self.assertRaises(FetchError):validate_run_and_inventory(run,items,42,ids)

    def test_download_exact_byte_hash_and_safe_no_url_token_leak(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        blobs={r:(r+' original bytes').encode() for r in ORIGINAL}
        pins={r:digest(b) for r,b in blobs.items()}
        run={'id':42,'status':'completed','conclusion':'success','head_sha':SOURCE_HEAD}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':False,
                             'workflow_run':{'id':42}} for role,n in ids.items()]}
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            with patch('e2_beans_original_artifact_fetch._api_get_json',side_effect=[run,items]), \
                 patch('e2_beans_original_artifact_fetch._download_exact_artifact',
                       side_effect=lambda n,token,expected:blobs[next(k for k in ids if ids[k]==n)]):
                status=download_verified(42,ids,pins,root/'out','not-a-real-token')
            self.assertFalse(status['production_accepted'])
            self.assertEqual({p.name for p in (root/'out').iterdir()},
                             {k+'.zip' for k in ORIGINAL})
            self.assertEqual((root/'out'/'producer.zip').read_bytes(),blobs['producer'])


    def test_fit_only_artifact_fetch_never_downloads_withheld_zip(self):
        ids={r:i+100 for i,r in enumerate(ORIGINAL)}
        blobs={r:(r+' archive bytes').encode() for r in ORIGINAL}
        pins={r:digest(b) for r,b in blobs.items()}
        run={'id':42,'status':'completed','conclusion':'success','head_sha':SOURCE_HEAD}
        items={'artifacts':[{'id':n,'name':ORIGINAL[role],'expired':False,
                             'workflow_run':{'id':42}} for role,n in ids.items()]}
        calls=[]
        def fake_download(n, token, sha):
            calls.append(n)
            return blobs[next(k for k in ids if ids[k]==n)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch('e2_beans_original_artifact_fetch._api_get_json',side_effect=[run,items]), \
                 patch('e2_beans_original_artifact_fetch._download_exact_artifact',side_effect=fake_download):
                status=download_verified(42,ids,pins,Path(tmp)/'fit-only','mock-token',roles={'source','producer'})
            self.assertEqual(set(status['archives']),{'source','producer'})
            self.assertEqual(set(calls),{ids['source'],ids['producer']})
            self.assertFalse((Path(tmp)/'fit-only'/'withheld.zip').exists())
            self.assertFalse((Path(tmp)/'fit-only'/'independent.zip').exists())

    def test_fetch_disallows_unknown_requested_roles(self):
        with self.assertRaises(FetchError):
            download_verified(42,{},{},Path('/tmp/x'),'token',roles={'arbitrary'})

    def test_archive_redirect_never_forwards_token_to_storage(self):
        from e2_beans_original_artifact_fetch import _download_exact_artifact
        from urllib import error as urllib_error
        from email.message import Message
        archive=b'original archive zip placeholder'
        header=Message()
        header['Location']='https://myaccount.blob.core.windows.net/archived/abc?temp=token'
        class FakeOpen:
            def open(self, req, timeout):
                self_req=req
                self.auth_present=bool(req.get_header('Authorization'))
                raise urllib_error.HTTPError(req.full_url,302,'Found',header,None)
        api=FakeOpen()
        seen=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return None
            def read(self,n):return archive
        def fake_storage(req,timeout):
            seen.append(req)
            return Response()
        with patch('e2_beans_original_artifact_fetch.request.build_opener',return_value=api), \
             patch('e2_beans_original_artifact_fetch.request.urlopen',side_effect=fake_storage):
            value=_download_exact_artifact(42,'secret-do-not-forward',digest(archive))
        self.assertEqual(value,archive)
        self.assertTrue(api.auth_present)
        self.assertEqual(len(seen),1)
        self.assertIsNone(seen[0].get_header('Authorization'))

    def test_archive_redirect_to_random_host_rejected(self):
        from e2_beans_original_artifact_fetch import _download_exact_artifact
        from urllib import error as urllib_error
        from email.message import Message
        hdr=Message();hdr['Location']='https://exfil.example.com/archive.zip'
        class RejectOpen:
            def open(self,req,timeout):
                raise urllib_error.HTTPError(req.full_url,302,'Found',hdr,None)
        with patch('e2_beans_original_artifact_fetch.request.build_opener',return_value=RejectOpen()):
            with self.assertRaises(FetchError):
                _download_exact_artifact(17,'secret',digest(b'real-data'))

if __name__=='__main__':unittest.main()
