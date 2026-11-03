#!/usr/bin/env python3
"""Verify downloaded 9cf hosted outputs against exact Git source, without running archived code."""
import argparse
if not __debug__:
    raise RuntimeError("Verification must not run with assertions disabled")
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

parser=argparse.ArgumentParser()
parser.add_argument('--artifacts',type=Path,default=Path(__file__).resolve().parent)
parser.add_argument('--repo',type=Path,default=Path('/workspace/scratch/1f1d02319616/private-ci-matrix-work-20261103'))
args=parser.parse_args()
BASE=args.artifacts
REPO=args.repo
HEAD='0b9da54535a7795b2433947a479e6d9e71525e0a'
ENV={**os.environ,'GIT_OPTIONAL_LOCKS':'0','GIT_NO_LAZY_FETCH':'1'}
def sha(b): return hashlib.sha256(b).hexdigest()
def git(*args): return subprocess.check_output(['git',*args],cwd=REPO,env=ENV)
entries={}
for row in git('ls-tree','-r','-z',HEAD).split(b'\0'):
    if row:
        spec,path=row.split(b'\t',1)
        entries[path.decode()]=spec.decode().split()[-1]
inputs={}; reports=[]
artifacts=json.loads((BASE/'9cf-artifacts.json').read_text())
for a in artifacts:
    d=BASE/str(a['id']);raw=(d/'artifact.zip').read_bytes()
    assert len(raw)==a['size_in_bytes'] and 'sha256:'+sha(raw)==a['digest']
    archive=zipfile.ZipFile(io.BytesIO(raw));assert archive.testzip() is None
    assert a['workflow_run']['head_sha']==HEAD and a['workflow_run']['id']==41701057635
    r=json.loads((d/'receipt.json').read_text())
    assert r['source_commit']==HEAD and (d/'source-commit.txt').read_text().strip()==HEAD
    assert r['status']=='passed' and r['source_inputs_unchanged'] is True
    assert r['source_before']==r['source_after']
    for p,h in r['source_before'].items():
        assert p not in inputs or inputs[p]==h
        inputs[p]=h
    for c in r['commands']:
        assert c['exit_code']==0
        assert sha((d/(c['name']+'.log')).read_bytes())==c['log_sha256']
    summary={'artifact_id':a['id'],'mode':r['mode'],'artifact_sha256':sha(raw),
             'artifact_bytes':len(raw),'receipt_sha256':sha((d/'receipt.json').read_bytes()),
             'source_inputs':len(r['source_before']),'source_before_after_equal':True,
             'commands':[{'name':x['name'],'exit_code':x['exit_code'],'log_sha256':x['log_sha256']} for x in r['commands']]}
    if r['mode']=='bazel':
        expected=git('cat-file','blob',entries['MODULE.bazel.lock'])
        assert (d/'MODULE.bazel.lock').read_bytes()==expected
        assert [c['name'] for c in r['commands']][:3]==['committed-lock-check','original-lock-update','original-lock-check']
        log=(d/'matrix-regressions.log').read_text()
        targets=re.findall(r'^//codex-rs/hepta-matrix-sdk:(\S+)\s+PASSED in ',log,re.M)
        assert len(targets)==3 and 'Executed 3 out of 3 tests: 3 tests pass.' in log
        assert sorted(targets)==['hepta-matrix-sdk-crypto_advisory-test','hepta-matrix-sdk-event_handler_context-test','hepta-matrix-sdk-sdk_store_upgrade-test']
        summary.update(committed_lock_equal_generated=True,lock_sha256=sha(expected),executed_bazel_test_targets=targets)
    else:
        assert (d/'rustc-version.txt').read_text().startswith('rustc 1.96.0 ')
        xml=(d/(r['mode']+'.junit.xml')).read_bytes()
        assert sha(xml)==r['tests']['sha256']
        root=ET.fromstring(xml); cases=root.findall('.//testcase')
        assert len(cases)==r['tests']['count'] and len(cases)>0
        assert int(root.attrib['tests'])==len(cases)
        for attr in ['failures','errors','disabled']:
            assert int(root.get(attr,'0'))==0
        assert not any(x.tag in ['failure','error','skipped'] for c in cases for x in c)
        assert r['tests']['zero_skipped'] is True
        assert [c.get('name') for c in cases]==r['tests']['names']
        expected_counts={'owners':113,'sqlite-starlark':221,'crypto-migration':1,'synapse-protocol':1}
        assert len(cases)==expected_counts[r['mode']]
        summary.update(tests=len(cases),zero_skipped=True,junit_sha256=sha(xml))
        if r['mode']=='owners':
            for name in ['gap_fill::tests::sdk_auxiliary_metadata_is_dropped_instead_of_retained_outside_raw_bounds','gap_fill::tests::sdk_bundled_thread_payload_is_included_in_raw_bounds']:
                assert name in r['tests']['names']
            summary['both_repaired_gap_fill_cases_executed']=True
            dbus=json.loads((d/'pinned-dbus-receipt.json').read_text())
            assert dbus['status']=='PASS' and len(dbus['commands'])==52
            assert all(c['exit']==0 for c in dbus['commands'])
            assert dbus['archive']['sha256']=='0ba2a1a4b16afe7bceb2c07e9ce99a8c2c3508e5dec290dbb643384bd6beb7e2'
            for name,h in dbus['inputs'].items():
                candidates=[p for p in inputs if p.startswith('third_party/dbus/') and Path(p).name==name and inputs[p]==h]
                assert len(candidates)==1, name
            summary['pinned_dbus_actual_build_and_identity_commands']=52
    reports.append(summary)

# Read every distinct referenced Git blob, including the full legacy producer.
process=subprocess.Popen(['git','cat-file','--batch'],cwd=REPO,env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
checked={}
for path,h in sorted(inputs.items()):
    oid=entries[path]
    if oid not in checked:
        process.stdin.write((oid+'\n').encode());process.stdin.flush()
        header=process.stdout.readline().decode().split()
        assert header[0]==oid and header[1]=='blob'
        raw=process.stdout.read(int(header[2]));assert process.stdout.read(1)==b'\n'
        checked[oid]=sha(raw)
    assert checked[oid]==h, path
process.stdin.close(); assert process.wait()==0
report={'schema':'matrix-hosted-0b9-independent-readback-v1','source_commit':HEAD,
        'source_tree':git('rev-parse',HEAD+'^{tree}').decode().strip(),'workflow_run':41701057635,
        'unique_git_source_paths_verified':len(inputs),'all_source_before_after_equal':True,
        'artifacts':reports,'native_cases_verified':sum(x.get('tests',0) for x in reports),
        'scope':'Exact joint-source Matrix qualification only; no complete original blocking CI, full-platform or paired-host acceptance implied.',
        'independent_execution':'No Cargo, native binaries, Bazel or archived code was executed by this verifier.'}
path=BASE/'VERIFIED.json'
path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'path':str(path),'sha256':sha(path.read_bytes()),'source_paths':len(inputs),'native_cases':report['native_cases_verified'],
                  'modes':[r['mode'] for r in reports],'all_logs_junit_lock_source_hashes_match':True}))
