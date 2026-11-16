#!/usr/bin/env python3
"""Verify complete immutable f1fd and redacted-provider downloads; no native execution."""
import base64
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
WORK = BASE.parent
COMMIT = 'afbc9571c7a7941fc791d6c6af05daa3e747ecd2'
ARTIFACTS = [
    {'label':'f1fd', 'bytes':59956, 'sha256':'03393baed2329c3a9eb50337678c67a0856bc568f753f2527272903492f25a8a', 'blob':'b22984b6650ec4b523760f9ef09ac94196f831d3', 'members':43, 'original':'mem8-dependency-closure/mem8-f1fd-full-rmcp-native-v1.tar.xz', 'verifier':'verify_evidence.py'},
    {'label':'provider', 'bytes':56432, 'sha256':'5cbc5b4d293b57980d9efe02bea0c0ec0bfe0ae165e1c9881801c7bc9cd1ae3c', 'blob':'92cde56a3c1aea8fc0d7353621ebeb2ede3257e5', 'members':64, 'original':'mem8-provider-smoke-observation/mem8-provider-55951-original-failure-redacted-v3.tar.xz', 'verifier':'redaction/verify_provider_redacted_v3.py'},
]

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def checked_download(index, pin):
    response = json.loads((BASE / f'READBACK_{index}.json').read_text())
    assert response['encoding'] == 'base64' and COMMIT in response['display_url']
    encoded = response['content']
    assert set(encoded) <= set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r\t ')
    raw = base64.b64decode(''.join(encoded.split()), validate=True)
    assert len(raw) == pin['bytes'] and sha(raw) == pin['sha256']
    assert git_blob(raw) == response['sha'] == pin['blob']
    assert raw == (WORK / pin['original']).read_bytes()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:xz') as bundle:
        for member in bundle:
            p = PurePosixPath(member.name)
            assert member.isfile() and not p.is_absolute() and '..' not in p.parts
            assert member.name not in files
            files[member.name] = bundle.extractfile(member).read()
    assert len(files) == pin['members']
    manifest = json.loads(files['FILE_MANIFEST.json'])
    assert set(files) == {r['path'] for r in manifest['files']} | {'FILE_MANIFEST.json'}
    for row in manifest['files']:
        assert len(files[row['path']]) == row['bytes'] and sha(files[row['path']]) == row['sha256']
    directory = BASE / 'readback' / pin['label']
    for name, content in files.items():
        destination = directory / name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(content)
    (BASE / f"{pin['label']}.tar.xz").write_bytes(raw)
    command = [sys.executable, str(directory / pin['verifier']), str(directory)]
    executed = subprocess.run(command,capture_output=True,text=True,timeout=30,check=False)
    assert executed.returncode == 0 and not executed.stderr, executed.stderr
    verification = json.loads(executed.stdout)
    return directory, {'label':pin['label'], 'bytes':len(raw), 'sha256':sha(raw), 'git_blob':git_blob(raw), 'safe_regular_members':len(files), 'full_member_hashes_verified':True, 'offline_verifier_exit_code':0, 'offline_verification':verification}

def main():
    results = [checked_download(i, pin) for i,pin in enumerate(ARTIFACTS)]
    f1fd, provider = [x[0] for x in results]
    old_junit = WORK / 'mem8-ci-followup-v8/readback/original/rmcp-consumers.junit.xml'
    original = ET.fromstring(old_junit.read_bytes())
    current = ET.fromstring((f1fd / 'records/full-rmcp-268.junit.xml').read_bytes())
    def ids(document):
        return {(x.get('classname'), x.get('name')) for x in document.iter('testcase')}
    assert len(ids(original)) == 268 and ids(original) == ids(current)
    assert original.get('uuid') == 'c6520272-0490-4d9f-bee4-5d08be7198bd'
    assert current.get('uuid') == 'b86c9959-e257-4ce0-91e0-f2eb7120d2cc'
    assert original.get('uuid') != current.get('uuid')
    phase = json.loads((f1fd / 'records/full-rmcp-268.json').read_text())
    start = datetime.fromisoformat(phase['started_at'])
    end = datetime.fromisoformat(phase['finished_at'])
    timestamps = []
    for case in current.iter('testcase'):
        value = case.get('timestamp')
        if value is not None:
            timestamp = datetime.fromisoformat(value.replace('Z','+00:00'))
            assert start <= timestamp <= end
            timestamps.append(value)
    previous = WORK / 'mem8-provider-smoke-observation/provider-original-failure'
    originals = [('original/real-provider-smoke.json.157a88383ba54af497ce5735935e0085.log','real-provider-smoke.raw.log'), ('original/real-provider-smoke.junit.xml','real-provider-smoke.junit.xml'), ('original/PROVIDER_OBSERVATIONS.json','PROVIDER_OBSERVATIONS.json'), ('original/PROVIDER_BINARY.json','PROVIDER_BINARY.json')]
    for actual, prior in originals:
        assert (provider / actual).read_bytes() == (previous / prior).read_bytes()
    privacy = json.loads((provider / 'PROJECTION_PRIVACY_ERRATUM.json').read_text())
    assert privacy['unsafe_objects_not_added_to_tree_commit_or_ref_by_this_task']
    result = {'schema':'hepta.mem8.ci-v9.root-complete-readback.v1', 'immutable_commit':COMMIT, 'archives':[x[1] for x in results], 'original_and_current_268_case_identity_sets_match':True, 'original_junit_uuid':original.get('uuid'), 'f1fd_junit_uuid':current.get('uuid'), 'f1fd_case_timestamps_checked':len(timestamps), 'provider_original_raw_junit_observations_binary_preserved':True, 'provider_original_outcome':'UNKNOWN', 'provider_physical_request_count':None, 'unsafe_prior_objects_not_referenced_in_this_commit':True, 'new_native_executions':0, 'new_model_calls':0, 'qualification_transferred_to_integrated_2ae':False, 'passed':True}
    (BASE / 'ROOT_READBACK_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
