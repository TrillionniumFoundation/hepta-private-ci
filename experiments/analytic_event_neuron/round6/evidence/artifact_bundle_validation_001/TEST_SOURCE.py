"""Small concrete conformance fixture for the standalone bundle utility."""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import shutil
import stat
import subprocess
import sys
import tarfile
import time

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent/'hepta-analytic'
UTILITY=REPO/'experiments/analytic_event_neuron/round6/artifact_bundle.py'
spec=importlib.util.spec_from_file_location('bundle_utility',UTILITY)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
review=REPO/'experiments/analytic_event_neuron/round6/evidence/recovery/SOURCE_REVIEW_002.json'
primary=json.loads(review.read_text())['sources_sha256']
before={name:m.sha(REPO/name) for name in primary}
started=time.perf_counter_ns(); checks=[]

def check(name,condition):
    if not condition: raise AssertionError(name)
    checks.append(name)

def rejected(label,call,destination):
    try: call()
    except (ValueError,FileExistsError) as error:
        check(label + ': no destination created', not destination.exists())
        checks.append(label + ': ' + str(error))
    else: raise AssertionError('Expected refusal: '+label)

source=ROOT/'fixture';source.mkdir()
(source/'empty').mkdir();(source/'nested').mkdir();(source/'__pycache__').mkdir()
(source/'run.sh').write_bytes(b'#!/bin/sh\nexit 0\n');(source/'run.sh').chmod(0o755)
(source/'nested/data.bin').write_bytes(random.Random(7301).randbytes(4096))
(source/'__pycache__/excluded.pyc').write_bytes(b'not artifact evidence')
first,second=ROOT/'bundle_a',ROOT/'bundle_b'
a=m.pack(source,first,512);b=m.pack(source,second,512)
check('deterministic complete archive and manifest',a==b and m.sha(first/'BUNDLE.json')==m.sha(second/'BUNDLE.json'))
check('raw chunks within connector bound',len(a['parts'])>1 and all(p['bytes']<=m.MAX_CHUNK for p in a['parts']))
check('cache excluded explicitly',all('__pycache__' not in p['name'] for p in a['members']))
restored=ROOT/'restored'
m.restore(first,restored,m.sha(first/'BUNDLE.json'))
check('restored file bytes and modes',m.snapshot(restored)==m.snapshot(source) and stat.S_IMODE((restored/'run.sh').stat().st_mode)==0o755)
cli=subprocess.run([sys.executable,'-B',str(UTILITY),'verify',str(first),'--expected-manifest-sha256',m.sha(first/'BUNDLE.json')],capture_output=True,text=True)
check('CLI verification',cli.returncode==0 and json.loads(cli.stdout)['passed'])
corrupt=ROOT/'corrupt_chunk';shutil.copytree(first,corrupt)
p=corrupt/a['parts'][0]['name'];data=p.read_bytes();p.write_bytes(bytes([data[0]^1])+data[1:])
rejected('corrupt raw chunk',lambda:m.restore(corrupt,ROOT/'bad_chunk_restore'),ROOT/'bad_chunk_restore')

# Both malicious archives have valid chunk/archive hashes; rejection must reach member checks.
for label,names in [('unsafe_path',['../escape']),('duplicate_member',['safe.txt','safe.txt'])]:
    bad=ROOT/label;bad.mkdir(); payload=b'forbidden'
    with (bad/'archive.tar.gz').open('xb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:
            with tarfile.open(fileobj=compressed,mode='w') as archive:
                for name in names:
                    item=tarfile.TarInfo(name);item.mode=0o644;item.size=len(payload)
                    archive.addfile(item,io.BytesIO(payload))
    archive=(bad/'archive.tar.gz').read_bytes();parts=[]
    for offset in range(0,len(archive),512):
        block=archive[offset:offset+512];name=f'part-{len(parts):05d}.bin'
        (bad/name).write_bytes(block);parts.append(m.part_identity(name,block))
    doc={'schema':m.SCHEMA,'excluded_components':['__pycache__'],'root_mode':0o755,'chunk_bytes':512,
         'archive':{'name':'archive.tar.gz','bytes':len(archive),'sha256':hashlib.sha256(archive).hexdigest()},'parts':parts,
         'members':[{'name':'safe.txt','kind':'file','mode':0o644,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}
    (bad/'BUNDLE.json').write_text(json.dumps(doc))
    rejected(label,lambda:m.restore(bad,ROOT/(label+'_restore')),ROOT/(label+'_restore'))
check('unsafe extraction wrote nothing outside destination',not (ROOT/'escape').exists())
(source/'link').symlink_to(source/'run.sh')
rejected('source symlink',lambda:m.pack(source,ROOT/'symlink_bundle'),ROOT/'symlink_bundle')
(source/'link').unlink()
identity=m.sha(first/'BUNDLE.json')
try:m.pack(source,first)
except FileExistsError:check('existing bundle not overwritten',m.sha(first/'BUNDLE.json')==identity)
else:raise AssertionError('Overwrote existing bundle')
try:m.restore(first,restored)
except ValueError:check('existing restore not overwritten',m.snapshot(restored)==m.snapshot(source))
else:raise AssertionError('Overwrote existing restored directory')
check('frozen scientific sources unchanged',before=={name:m.sha(REPO/name) for name in primary})
result={'schema':'hepta.artifact-bundle.conformance.v1','passed':True,'completed_utc':datetime.now(timezone.utc).isoformat(),
        'utility_sha256':m.sha(UTILITY),'utility_lines':len(UTILITY.read_text().splitlines()),'test_source_sha256':m.sha(__file__),
        'checks':checks,'wall_ns':time.perf_counter_ns()-started,'source_primary_count':len(primary),
        'primary_matches_review_002':before==primary,'default_and_maximum_chunk_bytes':m.MAX_CHUNK,
        'fixture_chunk_bytes':512,'fixture_archive_bytes':a['archive']['bytes'],'fixture_chunks':len(a['parts']),
        'fixture_archive_sha256':a['archive']['sha256'],'fixture_manifest_sha256':identity,
        'complete_archive_kept_locally':True,'network_or_publication_performed':False,'cli_stdout':cli.stdout}
with (ROOT/'RESULT.json').open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
