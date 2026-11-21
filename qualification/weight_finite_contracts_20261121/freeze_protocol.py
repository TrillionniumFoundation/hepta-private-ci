"""Freeze one receipt-only audit; never reads upstream result/cost files."""
from pathlib import Path
import ast
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from offline_controls import CONTROL_NAMES

ROOT=Path(__file__).resolve().parent


def digest(raw):return hashlib.sha256(raw).hexdigest()


def main():
    if (ROOT/'PROTOCOL_FROZEN.json').exists() or (ROOT/'attempt001').exists():
        raise ValueError('single freeze required')
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-queue-sha256',required=True)
    expected=parser.parse_args().expected_queue_sha256
    if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('external expected queue SHA256 must be 64 lowercase hex characters')
    queue=json.loads((ROOT/'QUEUE_FROZEN.json').read_bytes())
    if digest((ROOT/'QUEUE_FROZEN.json').read_bytes())!=expected:
        raise ValueError('prospective queue changed')
    upath=Path(queue['upstream_protocol']['path']);upraw=upath.read_bytes()
    if digest(upraw)!=queue['upstream_protocol']['sha256']:
        raise ValueError('upstream protocol drift')
    upstream=json.loads(upraw)
    producer=upath.parent/'scripts/build_oracle.py';producer_pin=dict(path=str(producer),sha256=digest(producer.read_bytes()))
    files={}
    def add(path,expected=None):
        path=Path(path);raw=path.read_bytes();d=digest(raw)
        if expected is not None and d!=expected:raise ValueError('upstream pinned input changed: '+str(path))
        files[str(path)]=dict(bytes=len(raw),sha256=d)
    for p in sorted(ROOT.glob('*.py')):
        ast.parse(p.read_text(),filename=str(p));add(p)
    add(ROOT/'README.md');add(ROOT/'QUEUE_FROZEN.json');add(upath);add(producer)
    for row in upstream['sources']:add(row['path'],row['sha256'])
    for row in upstream['inputs']:
        add(row['checkpoint_path'],row['checkpoint_gzip_sha256']);add(row['schedules_path'],row['schedules_sha256'])
    cpu_model=None
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        if line.startswith('model name'):
            cpu_model=line.split(':',1)[1].strip();break
    env=dict(python=sys.version,python_executable_sha256=digest(Path(sys.executable).read_bytes()),
        numpy=importlib.metadata.version('numpy'),scipy=importlib.metadata.version('scipy'),
        machine=platform.machine(),kernel=platform.release(),CPU_model=cpu_model,
        CPU_affinity_for_this_audit=[8],all_numeric_threads=1,shared_host=True,
        native_operator_algorithm_is_not_interchangeable_with_SciPy_expm=True,
        transitive_BLAS_and_OS_binary_closure_pinned=False)
    records=upath.parent/'evidence'
    protocol=dict(schema='hepta.finite-reuse-audit.v1',frozen_before_first_audit=True,
        queue_frozen_before_cost_read=True,created_at_UTC=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        chronology=dict(queue_and_KEEP_choice_frozen_before_upstream_costs=True,
            upstream_cost_summary_received_in_agent_message_before_source_freeze=True,
            entire_source_freeze_before_any_cost_knowledge_claimed=False,
            upstream_raw_results_opened_before_freeze=False,
            reason='The producer summary preceded the private audit source freeze; no frozen queue, choice or threshold changed.'),
        queue_sha256=digest((ROOT/'QUEUE_FROZEN.json').read_bytes()),
        source_contract=dict(upstream_protocol_sha256=digest(upraw),upstream_sources=upstream['sources'],
            producer_sha256=producer_pin['sha256'],scope='event-history-163-state operator and complete history only'),
        producer=producer_pin,files=files,environment=env,
        receipts=dict(oracle=str(records/'ORACLE_INPUT.json'),arrays=str(records/'ORACLE_ARRAYS.npz'),
            trace=str(records/'OPERATOR_TRACE.json'),resource=str(records/'ORACLE_RECEIPT.json')),
        safety_controls=CONTROL_NAMES,
        resources=dict(total_CPU_seconds=60,total_wall_seconds=120,address_space_bytes=536870912,
            audit_CPU_hard=40,reader_CPU_hard=15,supervisor_CPU_reserve=5,
            supervisor_CPU_abort_check=4,supervisor_initial_kernel_limits=[4,60],
            supervisor_final_kernel_limits=[4,5],affinity_CPU=8,numeric_threads=1),
        new_scientific_calls=0,expm_calls=0,neural_forward_calls=0,synthetic_performance_calls=0,
        independent_reader='no cache producer import; reconstruct exact keys from original receipts and full array bytes',
        prospective_CPU_resource_choice='KEEP_EXISTING_PATHS_AND_STOP_NEW_FULL_HISTORY_CACHE',
        incremental_avoided_model_computations_in_committed_queue=0,
        baseline_operator_reuse_already_enabled=True,general_NDU='KEEP_ORIGINAL_AND_STOP',
        missing_future_contract=['production request queue/horizon','independent financial benefit','owner utility per resource','future enforceable execution-cost bound'],
        performance_speedup_claim=False,numerical_quality_claim=False,automatic_retry=False,
        scope='single finite receipt audit and separately counted byte-cache qualification; not production cache adoption')
    with (ROOT/'PROTOCOL_FROZEN.json').open('x') as f:
        json.dump(protocol,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps(dict(status='FROZEN_NO_RESULT_READ',sha256=digest((ROOT/'PROTOCOL_FROZEN.json').read_bytes()),
        source_files=len(files),upstream_scientific_results_read=0)))


if __name__=='__main__':main()
