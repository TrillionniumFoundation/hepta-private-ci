import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from verify_and_run import (FROZEN_MANIFEST_GIT_BLOB, IMPLEMENTATION_SHA,
                            RESEARCH_SOURCE_SHA, ROOT, SourceRejected, git_blob_sha,
                            sha256, unpack_verified, run)

FILES = ('analysis.py','codec.py','control.py','data.py','evaluate.py',
         'oracle/analysis_audit.py','oracle/benchmark.py','oracle/local_control_audit.py',
         'oracle/solver.py','protocol.json','review/codec_audit.py',
         'review/codec_development.py','review/execution_audit.py',
         'run_experiment.py','train.py')


def make_artifact(base, *, tamper=None, extra=None, make_symlink=False):
    contents = {f: (b'{}\n' if f == 'protocol.json' else
                    b'print("RESEARCH_ONLY")\n') for f in FILES}
    contents['README.md'] = b'manifested but not executable\n'
    if extra:
        contents.update(extra)
    freeze = {'implementation_commit': IMPLEMENTATION_SHA,
              'formal_heldout_accessed':False,
              'files':{f:sha256(contents[f]) for f in FILES}}
    contents['SOURCE_FREEZE.json']=json.dumps(freeze,sort_keys=True).encode()
    contents['CLOUD_RUN_REQUEST.json']=json.dumps({
        'implementation_commit':IMPLEMENTATION_SHA,
        'protocol_sha256': freeze['files']['protocol.json'],
        'expected_repository':'TrillionniumFoundation/hepta-private-ci',
    }).encode()
    trusted_freeze = git_blob_sha(contents['SOURCE_FREEZE.json'])
    receipt={'source_sha': RESEARCH_SOURCE_SHA,'scientific_success':False,
             'production_authorized':False,'dedicated_runner_verified':False,
             'file_sha256':{f:sha256(contents[f]) for f in contents}}
    if tamper=='changed_code': contents['train.py'] = b'malicious alteration\n'
    if tamper=='false_success':receipt['scientific_success']=True
    if tamper=='wrong_branch':receipt['source_sha']='a'*40
    if tamper=='tamper_freeze':
        freeze['formal_heldout_accessed']=True
        contents['SOURCE_FREEZE.json']=json.dumps(freeze).encode()
        receipt['file_sha256']['SOURCE_FREEZE.json']=sha256(contents['SOURCE_FREEZE.json'])
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as tf:
        for f,b in contents.items():
            t=tarfile.TarInfo(f'{ROOT}/{f}')
            t.size=len(b)
            if make_symlink and f=='README.md':
                t.type=tarfile.SYMTYPE;t.linkname='/etc/passwd'
            tf.addfile(t,io.BytesIO(b))
    artifact=base/'test.zip'
    with zipfile.ZipFile(artifact,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('ndu-p0-frozen-source.tar.gz',buf.getvalue())
        z.writestr('source-receipt.json',json.dumps(receipt))
    return artifact,trusted_freeze

class OfflineImporterTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.path=Path(self.t.name)
    def _load(self, **opts):
        artifact,blob=make_artifact(self.path,**opts)
        return unpack_verified(artifact,self.path/'dest',trusted_freeze_blob=blob)
    def test_real_fixture_verified_without_claiming_science(self):
        r=self._load()
        self.assertTrue(r['source_verified'])
        self.assertFalse(r['scientific_qualified'])
        self.assertFalse(r['production_authorized'])
        self.assertEqual(r['pinned_module_count'],15)
        self.assertTrue((self.path/'dest'/ROOT/'run_experiment.py').exists())
        self.assertFalse((self.path/'dest'/ROOT/'README.md').exists())
    def test_corrupted_source_denied(self):
        with self.assertRaisesRegex(SourceRejected,'SHA-256 mismatch'):
            self._load(tamper='changed_code')
        self.assertFalse((self.path/'dest').exists())
    def test_signed_freeze_anchor_rejects_changed_registration(self):
        a,blob=make_artifact(self.path,tamper='tamper_freeze')
        with self.assertRaisesRegex(SourceRejected,'trusted Git blob'):
            unpack_verified(a,self.path/'dest',trusted_freeze_blob=FROZEN_MANIFEST_GIT_BLOB)
    def test_receipt_not_allowed_to_self_certify_science(self):
        with self.assertRaisesRegex(SourceRejected,'permission flags'):
            self._load(tamper='false_success')
    def test_wrong_repository_sha_denied(self):
        with self.assertRaisesRegex(SourceRejected,'original checkout SHA'):
            self._load(tamper='wrong_branch')
    def test_malicious_python_not_installed(self):
        self._load(extra={'sitecustomize.py':b'raise SystemExit("BAD")\n'})
        self.assertFalse((self.path/'dest'/ROOT/'sitecustomize.py').exists())
    def test_absolute_escapes_denied(self):
        a,blob=make_artifact(self.path,extra={'../../escape.txt':b'X'})
        with self.assertRaisesRegex(SourceRejected,'archive member|subtree'):
            unpack_verified(a,self.path/'dest',trusted_freeze_blob=blob)
    def test_symlink_denied(self):
        with self.assertRaisesRegex(SourceRejected,'non-regular'):
            self._load(make_symlink=True)
    def test_no_overwrite_previous_evidence(self):
        self._load()
        a,blob=make_artifact(self.path)
        with self.assertRaisesRegex(SourceRejected,'destination already exists'):
            unpack_verified(a,self.path/'dest',trusted_freeze_blob=blob)
    def test_default_public_pins_reject_synthetic_fixture(self):
        a,blob=make_artifact(self.path)
        with self.assertRaisesRegex(SourceRejected,'trusted Git blob'):
            unpack_verified(a,self.path/'dest')
    def test_unknown_zip_member_denied(self):
        a,blob=make_artifact(self.path)
        with zipfile.ZipFile(a,'a') as z:
            z.writestr('surprise.txt',b'X')
        with self.assertRaisesRegex(SourceRejected,'artifact members'):
            unpack_verified(a,self.path/'dest',trusted_freeze_blob=blob)

if __name__=='__main__':unittest.main()
