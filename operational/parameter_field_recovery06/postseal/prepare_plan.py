"""Prospective execution06 postseal declaration; metadata only, no RAW writes."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[3]
BASE = SOURCE.parent
OWN = Path(__file__).resolve().parent
OPS = BASE / 'fullstudy_execution06_ops'
RAW = BASE / 'fullstudy_execution06_durable_raw'
WORK = BASE / 'fullstudy_execution06_postseal_20261030'
PYTHON = str(BASE / 'runtime_recovery_20261030/venv/bin/python')
EPISODE = 'execution06_detached_20261030'
OLD_PLAN = SOURCE / 'supplements/parameter_field_fullstudy_20261030/PRE_ENDPOINT_PLAN.json'
OLD_PLAN_SHA = 'cfd35051e481c5c1d070fec88f933e191b6368655325857079e3505fd195f8b1'
SUPPLEMENT_SHA = '1b705285b99fc7185c20155fa85f3a5d370b473196eaf59c8ae1d6bb2941a633'
PROTOCOL_SHA = '2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55'
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery06 import historical_costs as metadata

need, descriptor, read = metadata.require, metadata.descriptor, metadata.read

def verify(item):
    metadata.checked(item)
    return item


def bound(item):
    return read(metadata.checked(item))


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')
        stream.flush()
        __import__('os').fsync(stream.fileno())
    return descriptor(Path(path).absolute())


def committed(item, commit):
    verify(item)
    relative = Path(item['path']).relative_to(SOURCE).as_posix()
    result = subprocess.run(['git', '-C', str(SOURCE), 'show', commit + ':' + relative],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    need(hashlib.sha256(result.stdout).hexdigest() == item['sha256'], 'Postseal source is not byte-exact in the registered commit: ' + relative)


def original_plan():
    item = descriptor(OLD_PLAN)
    need(item['sha256'] == OLD_PLAN_SHA, 'Original pre-endpoint supplement plan changed')
    return item, bound(item)


def validate_plan(plan, producer_config_descriptor, source_commit):
    """Validate preserved science and source binding, also after endpoints exist."""
    parent_item, parent = original_plan()
    producer = bound(producer_config_descriptor)
    need(set(producer) == metadata.PRODUCER_CONFIG_KEYS
         and producer['schema'] == metadata.PRODUCER_CONFIG_SCHEMA and producer['execution_episode'] == EPISODE,
         'Postseal producer configuration differs')
    fresh = producer['fresh_registration']
    need(re.fullmatch(r'[0-9a-f]{40}', source_commit)
         and fresh['registered_commit'] == source_commit and fresh['execution_episode'] == EPISODE
         and fresh['raw_root'] == str(RAW) and fresh['source_root'] == str(SOURCE), 'Postseal producer/root/commit differs')
    need(plan.get('schema') == parent['schema'] == 'hepta.fullstudy.postseal-plan.2'
         and plan.get('status') == 'PRE_ENDPOINT' and plan.get('execution_episode') == EPISODE
         and plan.get('registered_source_commit') == source_commit and plan.get('original_plan') == parent_item
         and plan.get('producer_config') == producer_config_descriptor
         and plan.get('producer_map') == producer['producer_map'] and plan.get('import_receipt') == producer['import_receipt']
         and plan.get('execution_context') == {'operations_root':str(OPS),'raw_root':str(RAW),'source_root':str(SOURCE)},
         'Wrong execution06 prospective postseal declaration')
    unchanged = ('analyses','attempt_id','documentation','forbidden','frozen_sources','implementation','input_gate',
                 'new_implementation_not_recovered_old_bytes','original_phase_freezes','output_policy','protocol_sha256',
                 'scientific_payloads_opened_during_preparation','semantic_tests','unchanged')
    need(all(plan.get(key) == parent[key] for key in unchanged), 'Postseal scientific analyses, constraints or original sources changed')
    need(plan['pipeline_interface'] == {**parent['pipeline_interface'], 'execution_episode': EPISODE}, 'Pipeline interface changed beyond episode')
    need(plan.get('producer_adapter') == descriptor(SOURCE/'operational/parameter_field_recovery06/producer_adapter.py'),
         'Producer adapter descriptor differs')
    names = {'prepare_plan.py','prepare_pins.py','run_supplement.py','review.py','test_review.py'}
    need(set(plan.get('postseal_sources',{})) == names, 'Postseal source population differs')
    for name,item in plan['postseal_sources'].items():
        need(item['path'] == str(OWN/name), 'Postseal entrypoint path differs')
        committed(item,source_commit)
    need(set(plan.get('review_contracts',{})) == {'FIELD_MAP.json','C_SCOPE.json','FINAL_CONCLUSION_TEMPLATE.zh-CN.md'}, 'Review contract population differs')
    for name,item in plan['review_contracts'].items():
        need(item['path'] == str(OWN/name), 'Review contract path differs')
        committed(item,source_commit)
    for item in (producer['producer_map'],producer['import_receipt'],plan['producer_adapter']):
        verify(item)
    return producer


def build_plan(producer_config_descriptor, source_commit):
    """Return a reviewable plan dict; the root initializer alone seals it."""
    parent_item,parent = original_plan()
    producer = bound(producer_config_descriptor)
    for relative in ('stage_A/endpoints','stage_B/endpoints','stage_C/endpoint_evaluation','aggregate_results','analysis_operations'):
        need(not (RAW/relative).exists(), 'Execution06 endpoint/aggregate barrier already exists; no late preregistration')
    plan=deepcopy(parent)
    plan.update({'execution_episode':EPISODE,'declared_at':datetime.now(timezone.utc).isoformat(),
        'registered_source_commit':source_commit,'original_plan':parent_item,'producer_config':producer_config_descriptor,
        'producer_map':producer['producer_map'],'import_receipt':producer['import_receipt'],
        'producer_adapter':descriptor(SOURCE/'operational/parameter_field_recovery06/producer_adapter.py'),
        'execution_context':{'operations_root':str(OPS),'raw_root':str(RAW),'source_root':str(SOURCE)},
        'pipeline_interface':{**parent['pipeline_interface'],'execution_episode':EPISODE},
        'declaration_scope':'Execution06 producer/provenance adapter for the unchanged execution04 preregistered finite diagnostics; no scientific values read or scientific analyses changed.',
        'preparation_state':'METADATA_ONLY_NO_REAL_ANALYSIS',
        'postseal_sources':{name:descriptor(OWN/name) for name in ('prepare_plan.py','prepare_pins.py','run_supplement.py','review.py','test_review.py')},
        'review_contracts':{name:descriptor(OWN/name) for name in ('FIELD_MAP.json','C_SCOPE.json','FINAL_CONCLUSION_TEMPLATE.zh-CN.md')}})
    validate_plan(plan,producer_config_descriptor,source_commit)
    return plan
