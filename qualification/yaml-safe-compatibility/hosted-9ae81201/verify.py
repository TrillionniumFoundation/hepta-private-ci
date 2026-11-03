#!/usr/bin/env python3
"""Read exact hosted bytes and Git source; never execute archived code."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import zipfile

parser=argparse.ArgumentParser()
parser.add_argument('--artifacts',type=Path,default=Path(__file__).resolve().parent)
parser.add_argument('--repo',type=Path,default=Path('/workspace/scratch/1f1d02319616/private-ci-dependency-union-work-20261103'))
args=parser.parse_args()
BASE=args.artifacts
HEAD='9ae81201f2761e7217f019c40b40de952ca4579d'
ENV={**os.environ,'GIT_OPTIONAL_LOCKS':'0','GIT_NO_LAZY_FETCH':'1'}
def sha(b):return hashlib.sha256(b).hexdigest()
def git(*a):return subprocess.check_output(['git',*a],cwd=args.repo,env=ENV)
entries={}
for row in git('ls-tree','-r','-z',HEAD).split(b'\0'):
    if row:
        spec,path=row.split(b'\t',1);entries[path.decode()]=spec.decode().split()[-1]
cache={}
def blob(path):
    oid=entries[path]
    if oid not in cache:cache[oid]=git('cat-file','blob',oid)
    return cache[oid]
tree=git('rev-parse',HEAD+'^{tree}').decode().strip()
expected_inputs=json.loads(blob('qualification/yaml-safe-compatibility/CANDIDATE_INPUTS.json'))['runtime_and_manifest_sha256']
assert len(expected_inputs)==85
artifacts=json.loads((BASE/'artifact-metadata.json').read_text())
assert len(artifacts)==7
inputs={}; reports=[]; native_counts={}
counts={'codex-utils-yaml':10,'codex-skills':49,'codex-skills-extension':175,'codex-core-plugins':420,'codex-external-agent-migration':166}
ansi=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
for a in artifacts:
    d=BASE/str(a['id']);raw=(d/'artifact.zip').read_bytes()
    assert len(raw)==a['size_in_bytes'] and 'sha256:'+sha(raw)==a['digest']
    z=zipfile.ZipFile(io.BytesIO(raw));assert z.testzip() is None
    assert a['workflow_run']['head_sha']==HEAD and a['workflow_run']['id']==41680954821
    r=json.loads((d/'RECEIPT.json').read_text())
    assert r['source_commit']==HEAD and r['source_tree']==tree
    assert r['accepted'] is True and r['inputs_unchanged'] is True
    assert r['source_sha256_before']==r['source_sha256_after']
    assert len(r['source_sha256_before'])==89
    assert r['original_just_test_stack_bytes']==8388608
    for p,h in r['source_sha256_before'].items():
        assert p not in inputs or inputs[p]==h
        inputs[p]=h
    for p,h in expected_inputs.items():assert r['source_sha256_before'][p]==h
    for c in r['commands']:
        assert c['exit_code']==0
        for suffix in ['stdout','stderr']:
            assert sha((d/(c['name']+'.'+suffix)).read_bytes())==c[suffix+'_sha256']
    row={'artifact_id':a['id'],'mode':r['mode'],'package':r['package'],
         'zip_bytes':len(raw),'zip_sha256':sha(raw),'receipt_sha256':sha((d/'RECEIPT.json').read_bytes()),
         'source_inputs':len(r['source_sha256_before']),'before_after_equal':True,
         'commands':r['commands']}
    if r['mode']=='native':
        assert len(r['commands'])==1 and r['commands'][0]['argv']==['just','test','--locked','-p',r['package']]
        log=ansi.sub('',(d/'original-just-test.stderr').read_text())
        summaries=re.findall(r'^\s*Summary\s+\[[^\]]+\]\s+(\d+) tests run: (\d+) passed, (\d+) skipped\s*$',log,re.M)
        assert len(summaries)==1
        run,passed,skipped=map(int,summaries[0]);assert run==passed==counts[r['package']] and skipped==0
        individual=re.findall(r'^\s*PASS\s+\[[^\]]+\]\s+\(\s*(\d+)/(\d+)\)\s+(.+)$',log,re.M)
        assert len(individual)==run
        assert {int(x[0]) for x in individual}==set(range(1,run+1))
        assert all(int(x[1])==run for x in individual)
        assert not re.search(r'^\s*(FAIL|SKIP|TIMEOUT|ABORT|FLAKY)\s+\[',log,re.M)
        row.update(tests=run,zero_skipped=True,individual_pass_records_verified=run,
                   count_evidence='Original nextest raw per-case records and summary; no JUnit artifact was retained by this workflow.')
        native_counts[r['package']]=run
    elif r['mode']=='bazel':
        assert [c['name'] for c in r['commands']]==['original-bazel-committed-lock-check','original-bazel-lock-update','original-bazel-lock-check','bazel-yaml-utility-tests']
        assert (d/'MODULE.bazel.lock').read_bytes()==blob('MODULE.bazel.lock')
        stdout=(d/'bazel-yaml-utility-tests.stdout').read_text();stderr=(d/'bazel-yaml-utility-tests.stderr').read_text()
        combined=stdout+'\n'+stderr
        assert re.search(r'^//codex-rs/utils/yaml:yaml-unit-tests\s+PASSED in ',combined,re.M)
        assert 'Executed 1 out of 1 test: 1 test passes.' in combined or 'Executed 1 out of 1 test: 1 test pass' in combined
        assert '(cached)' not in next(x for x in combined.splitlines() if x.startswith('//codex-rs/utils/yaml:yaml-unit-tests'))
        row.update(committed_lock_checked_before_generation=True,
                   generated_lock_exact_to_committed=True,lock_sha256=sha(blob('MODULE.bazel.lock')),
                   actual_bazel_test_target_executed=True)
    else:
        assert r['mode']=='graph' and len(r['commands'])==1
        assert r['commands'][0]['argv']==['cargo','metadata','--locked','--all-features','--format-version','1']
        graph=json.loads((d/'cargo-metadata-all-features.stdout').read_text())
        assert len(graph['packages'])==r['graph']['package_count']==1524
        assert not any(p['name'] in {'serde_yaml','unsafe-libyaml'} for p in graph['packages'])
        package=[p for p in graph['packages'] if p['name']=='serde-saphyr'];assert len(package)==1
        assert package[0]['source'] is None and package[0]['version']=='2.1.0'
        assert package[0]['id']==r['graph']['parser_package']
        assert package[0]['manifest_path'].endswith('/codex-rs/third_party/serde-saphyr-2.1.0/Cargo.toml')
        lock=tomllib.loads(blob('codex-rs/Cargo.lock').decode())
        key=lambda p:(p['name'],p['version'],p.get('source'))
        assert {key(p) for p in lock['package']}=={key(p) for p in graph['packages']}
        row.update(metadata_packages=1524,metadata_lock_records_match=True,legacy_parser_absent=True)
    reports.append(row)
for p,h in sorted(inputs.items()):assert sha(blob(p))==h,p
assert native_counts==counts and len(inputs)==89
report={'schema':'yaml-final-head-independent-readback-v1','source_commit':HEAD,'source_tree':tree,
        'workflow_run':41680954821,'all_seven_artifacts_verified':True,'unique_git_source_paths_verified':89,
        'reviewed_source_manifest_paths_verified':85,'source_before_after_unchanged':True,
        'native_test_counts':native_counts,'native_total':sum(native_counts.values()),'native_zero_skipped':True,
        'module_lock_sha256':sha(blob('MODULE.bazel.lock')),'artifacts':reports,
        'qualification_scope':'Original five native package suites, complete all-features graph and committed-lock-first Bazel utility target on exact 9ae source.',
        'boundaries':['No JUnit files were retained by this workflow; case counts were independently read from all original per-case PASS records and the original summary.',
                      'The 89 inputs are the explicitly snapshotted qualification scope, not every repository source file.',
                      'No separate-branch result establishes union-source, full-platform or paired-host acceptance.',
                      'No Cargo/native/Bazel/archived code executed by this verifier.']}
out=BASE/'VERIFIED.json';out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'path':str(out),'sha256':sha(out.read_bytes()),'source_paths':89,'native_counts':native_counts,
                  'native_total':820,'artifacts':7,'all_logs_sources_lock_and_actual_pass_records_match':True}))
