"""Execute the exact documented development restore and relocated qualifier tests."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent/'hepta-analytic'
DOC=REPO/'experiments/analytic_event_neuron/round6/REPRODUCE.md'
ARCHIVE=Path('/workspace/scratch/d831a963ef2f/runtime-audit-r6/export_001/ROUND6_DEVELOPMENT_EVIDENCE_001.tar.gz')
MANIFEST=REPO/'experiments/analytic_event_neuron/round6/evidence/DEVELOPMENT_EVIDENCE_001_MANIFEST.json'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def write(name,item):
    with (ROOT/name).open('x') as stream:
        json.dump(item,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def invoke(label,command,stdin=None,override=None):
    environment=os.environ.copy();environment.update(override or {})
    start={'command':command,'cwd':str(REPO),'environment_overrides':override or {},
           'stdin_sha256':None if stdin is None else hashlib.sha256(stdin.encode()).hexdigest(),
           'started_utc':datetime.now(timezone.utc).isoformat()}
    write(label+'_STARTED.json',start)
    cpu=resource.getrusage(resource.RUSAGE_CHILDREN);clock=time.perf_counter_ns()
    result=subprocess.run(command,input=stdin,capture_output=True,text=True,cwd=REPO,env=environment)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    with (ROOT/(label+'.stdout.log')).open('x') as stream:stream.write(result.stdout)
    with (ROOT/(label+'.stderr.log')).open('x') as stream:stream.write(result.stderr)
    receipt={**start,'completed_utc':datetime.now(timezone.utc).isoformat(),'returncode':result.returncode,
             'wall_ns':time.perf_counter_ns()-clock,
             'child_user_seconds':after.ru_utime-cpu.ru_utime,'child_system_seconds':after.ru_stime-cpu.ru_stime,
             'stdout_sha256':sha(ROOT/(label+'.stdout.log')),'stderr_sha256':sha(ROOT/(label+'.stderr.log'))}
    write(label+'_COMPLETED.json',receipt)
    if result.returncode:raise RuntimeError(label+' failed: '+result.stderr)
    return receipt

before_doc=sha(DOC)
primary=json.loads((REPO/'experiments/analytic_event_neuron/round6/evidence/recovery/SOURCE_REVIEW_002.json').read_text())['sources_sha256']
before_primary={name:sha(REPO/name) for name in primary}
try:
    blocks=re.findall(r"<<'PYDEV'\n(.*?)\nPYDEV\n",DOC.read_text(),re.S)
    assert len(blocks)==1,'Exactly one documented Python restore block required'
    snippet=blocks[0]+'\n'
    with (ROOT/'EXACT_DOCUMENTED_RESTORE.py').open('x') as stream:stream.write(snippet)
    assert sha(ARCHIVE)=='6be4c5bfc0d2ae329ca735f04d909f78459e43cdd627ba1c8235e1a719b1ea47'
    assert sha(MANIFEST)=='31f50587439ffbb75385297860824d1f9e8fafb5cdd232c48e662caada61bbab'
    inputs=ROOT/'inputs';inputs.mkdir()
    for source,name in [(ARCHIVE,'ROUND6_DEVELOPMENT_EVIDENCE_001.tar.gz'),(MANIFEST,'DEVELOPMENT_EVIDENCE_001_MANIFEST.json')]:
        shutil.copy2(source,inputs/name)
        assert sha(source)==sha(inputs/name)
    restored=ROOT/'restored_development'
    restore=invoke('DOCUMENTED_RESTORE',[sys.executable,'-B','-',str(inputs),str(restored)],stdin=snippet)
    fixture=restored/'experiments/analytic_event_neuron/round6/evidence/native_qualification_001/results'
    tests=invoke('RELOCATED_QUALIFIER',[sys.executable,'-B','-m','unittest',
        'experiments.analytic_event_neuron.round6.test_qualifier','-v'],override={'HEPTA_QUALIFICATION_RESULT':str(fixture)})
    assert sha(DOC)==before_doc,'Guide changed during validation'
    assert before_primary=={name:sha(REPO/name) for name in primary},'Scientific sources changed'
    manifest=json.loads(MANIFEST.read_text())
    record={'schema':'hepta.documented-reproduction.conformance.v1','passed':True,
        'completed_utc':datetime.now(timezone.utc).isoformat(),'documentation_sha256':before_doc,
        'runner_sha256':sha(__file__),'exact_documented_snippet_sha256':sha(ROOT/'EXACT_DOCUMENTED_RESTORE.py'),
        'development_archive_sha256':sha(ARCHIVE),'development_manifest_sha256':sha(MANIFEST),
        'restored_file_count':len(manifest['files']),'restored_directory_count':len(manifest['directories']),
        'restored_fixture':str(fixture),'retained_qualifier_tests':4,
        'commands':[restore,tests],'full_child_cpu_seconds':sum(r['child_user_seconds']+r['child_system_seconds'] for r in (restore,tests)),
        'full_command_wall_ns':sum(r['wall_ns'] for r in (restore,tests)),
        'primary_source_count':len(primary),'primary_sources_unchanged':True,
        'primary_matches_review_002':before_primary==primary,'documentation_correction_required':False,
        'registered_or_confirmation_paths_written':False,'scientific_experiment_repeated':False,
        'scope':'Actual complete-development-tar branch of the exact documented adapter, followed by four retained-evidence tests at the relocated fixture path.'}
    write('RESULT.json',record)
    print(json.dumps({key:value for key,value in record.items() if key!='commands'},sort_keys=True))
except Exception as error:
    write('FAILURE.json',{'passed':False,'error':type(error).__name__+': '+str(error),'documentation_sha256':before_doc,
        'created_utc':datetime.now(timezone.utc).isoformat()})
    raise
