"""Immutable registered preparation bundle; receipts stay outside the run."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

BASE=Path('/dev/shm/hepta-round6-d831a963ef2f')
REPO=BASE/'hepta-analytic'
RUN=REPO/'experiments/analytic_event_neuron/round6/evidence/registered_001'
OUTPUT=BASE/'registered_preparation_packaging_001'
BUNDLE=BASE/'registered_preparation_bundle_001'
FREEZE='1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1'
PREPARED='01cd90245b3d024d5be8676a684266c44a2e8e608fd9d175625db979d48d688a'
UTILITY='3c98bfe234c1bfba14b72e114f771cd18c06fc900d754be3c59d3145a12cbb66'
LEDGER='c105641eda645aa8516fc98037be53ed0fecdb69e8e0cc81affe76f8a14ab1b6'
sys.path.insert(0,str(REPO))
from experiments.analytic_event_neuron.round6 import artifact_bundle as bundle
from experiments.analytic_event_neuron.round6.lifecycle import verify

def write(name,item):
    with (OUTPUT/name).open('x') as stream:
        json.dump(item,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def identities():
    values={'freeze_sha256':bundle.sha(RUN/'FREEZE.json'),
            'prepared_sha256':bundle.sha(RUN/'PREPARED.json'),
            'ledger_sha256':bundle.sha(RUN/'execution/PREPARATION_BATCH_COMPLETED.json'),
            'utility_sha256':bundle.sha(Path(bundle.__file__))}
    assert values=={'freeze_sha256':FREEZE,'prepared_sha256':PREPARED,'ledger_sha256':LEDGER,'utility_sha256':UTILITY},values
    assert not (RUN/'confirmation').exists(),'Confirmation must not be constructed for the preparation bundle'
    verify(RUN,FREEZE)
    return values

started=time.perf_counter_ns()
try:
    before=identities()
    members=bundle.snapshot(RUN)
    write('SOURCE_BEFORE.json',{'schema':'hepta.preparation-bundle.before.v1',
        'created_utc':datetime.now(timezone.utc).isoformat(),'run':str(RUN),
        'identities':before,'source_members':members,'aggregate_ledger_stability_confirmed_by':'/root/r6_source_restore',
        'source_writes_stopped_before_pack':True,'confirmation_constructed':False})
    manifest=bundle.pack(RUN,BUNDLE)
    after=identities()
    assert bundle.snapshot(RUN)==members==manifest['members'],'Registered evidence changed during packaging'
    status=os.statvfs(BASE)
    result={'schema':'hepta.registered-preparation-bundle.v1','passed':True,
        'completed_utc':datetime.now(timezone.utc).isoformat(),'identities_before':before,'identities_after':after,
        'source_before_sha256':bundle.sha(OUTPUT/'SOURCE_BEFORE.json'),'wrapper_source_sha256':bundle.sha(__file__),
        'bundle_directory':str(BUNDLE),'manifest_sha256':bundle.sha(BUNDLE/'BUNDLE.json'),
        'archive':manifest['archive'],'part_count':len(manifest['parts']),'maximum_part_bytes':max(p['bytes'] for p in manifest['parts']),
        'member_count':len(manifest['members']),'file_count':sum(p['kind']=='file' for p in manifest['members']),
        'directory_count':sum(p['kind']=='dir' for p in manifest['members']),
        'uncompressed_file_bytes':sum(p['bytes'] for p in manifest['members']),
        'member_modes_preserved':True,'all_run_members_except_explicit_cache_exclusion_included':True,
        'all_chunk_and_archive_member_hashes_reopened_verified':True,'registered_source_snapshot_stable':True,
        'packaging_receipts_outside_registered_run':True,'publication_performed':False,'confirmation_constructed':False,
        'body_wall_ns':time.perf_counter_ns()-started,'available_bytes_after':status.f_bavail*status.f_frsize}
    write('RESULT.json',result)
    print(json.dumps(result,sort_keys=True))
except Exception as error:
    write('FAILURE.json',{'passed':False,'error':type(error).__name__+': '+str(error),
        'created_utc':datetime.now(timezone.utc).isoformat(),'wrapper_source_sha256':bundle.sha(__file__)})
    raise
