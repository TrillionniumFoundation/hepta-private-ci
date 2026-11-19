"""Declared full retry of unchanged V8 research after sandbox-layer ENOSPC.

Only local frozen research inputs are read. No network, deletion, selection,
algorithm/configuration change, or original-output modification is performed.
"""

from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from record_grid_interruption_v8 import record,sha


workspace=Path('/workspace/scratch/60f94d809f44')
root=workspace/'pft-development-v8'
output=root/'grid-r2'
log=root/'grid-r2.log'
declaration=root/'grid-retry-declaration.json'
runtime=root/'grid-r2-runtime-execution.json'
inventory=root/'grid-attempt1-interruption-approved-exec.json'
assert all(not p.exists() for p in (output,log,declaration,runtime,inventory))
pins=json.loads((workspace/'pft-audit-v8-development/pins.json').read_bytes())
assert pins['protocol_sha256']=='d84f8e40551e31ac502b9bd7c8813ea1394fa722440658a7cca13694af8b5786'
assert pins['source_sha256']=='cda4c60b6a3f256f87f1207a2104f62755633a289902c4dae31c15a139a20276'
assert pins['source_commit']=='201d28f2c3e784d02da910fc24156e15e493d288' and pins['source_files']==117
stat=os.statvfs(workspace)
free=stat.f_bfree*stat.f_frsize
assert free>=200_000_000,('Insufficient actual space for registered complete retry',free)
original=record(workspace,inventory)
assert original['recoverable_cpu_lower_bound_ns']==57251806899
protocol=workspace/'hepta-repo-v8/qa/stem-bakeoff/cell_field_development_protocol_v8.json'
source_manifest=root/'grid-executed-source.json'
assert sha(protocol)==pins['protocol_sha256']
sources=json.loads(source_manifest.read_bytes())
canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
assert len(sources)==117 and hashlib.sha256(canonical(sources)).hexdigest()==pins['source_sha256']
for name,expected in sources.items():assert sha(protocol.parent/name)==expected,name
environment={name:'1' for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','PYTHONDONTWRITEBYTECODE')}
runtime_record={'schema':'hepta.local-research-runtime-execution.v8',
    'runtime_execution':'approved_escalated_local_research','at':datetime.now(timezone.utc).isoformat(),
    'reason':'normal sandbox writable layer and synthetic mount setup suffered ENOSPC; approved local retry uses escalated execution view',
    'environment':environment,'free_bytes_before':free,'filesystem_id':getattr(stat,'f_fsid',None),
    'network_accessed':False,'original_evidence_deleted_or_modified':False,'source_protocol_or_algorithm_changed':False,
    'output':str(output),'log':str(log),'launcher_sha256':sha(__file__)}
runtime.write_bytes(canonical(runtime_record)+b'\n')
retry={'schema':'hepta.complete-development-infrastructure-retry.v8',
    'cause':'infrastructure_disk_full','declaration_written_before_execution':True,
    'runtime_execution':'approved_escalated_local_research','runtime_receipt_sha256':sha(runtime),
    'original_partial_directory':str(root/'grid'),'original_inventory_sha256':sha(inventory),
    'original_log_sha256':sha(root/'grid.log'),'original_complete_rows':46,'original_rejected_rows':7,
    'original_recoverable_cpu_lower_bound_ns':57251806899,'original_whole_attempt_cost_exact_known':False,
    'original_unknown_costs':'interrupted47th call, shared preparation, unrecorded I/O; lower bound is not total',
    'retry_output':str(output),'registered_outputs':1152,'all_registered_cases_repeated':True,
    'case_order_unchanged':True,'case_subset_selection':False,'execution_source_commit':pins['source_commit'],
    'protocol_sha256':pins['protocol_sha256'],'executed_source_sha256':pins['source_sha256'],'source_files':117,
    'environment':environment,'primary_complete_attempt':'grid-r2 only after complete seal and independent audit',
    'earlier_partial_outputs_retained':True,'scientific_acceptance':False}
declaration.write_bytes(canonical(retry)+b'\n')
for key,value in environment.items():os.environ[key]=value
print(json.dumps({'retry_declaration_sha256':sha(declaration),'original_inventory_sha256':sha(inventory),
    'free_bytes_before':free,'registered_outputs':1152}),flush=True)
with log.open('xb') as stream:
    os.dup2(stream.fileno(),1)
    os.dup2(stream.fileno(),2)
    os.execv(sys.executable,[sys.executable,'-B',str(protocol.parent/'cell_field_development_run_v8.py'),
        '--workspace',str(workspace),'--protocol',str(protocol),'--source-manifest',str(source_manifest),
        '--source-commit',pins['source_commit'],'--output',str(output)])
