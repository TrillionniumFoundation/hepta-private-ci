"""Offline HCSN six-stage evidence gatebook. Research only; never grants release.

A self-declared receipt is not third-party evidence: SHA syntax and numeric
checks cannot authenticate a GitHub tree, prove semantic math, rerun a GPU
experiment, or establish scientific replication. This module makes missing
and failed gates visible; final production admission is ALWAYS denied here.
"""
from __future__ import annotations

from dataclasses import dataclass,asdict
import math
import re
from typing import Mapping

REQUIRED={
'P0':('hx_coupled_fixed_point','global_obstacle','regenerative_qvi',
      'boundary_gradients','native_fp32_error_enclosures'),
'P1':('fresh_sealed_controlled_tasks','matched_information_and_derivatives',
      'incremental_call_risk_margin_gain','budget_adjusted_net_utility'),
'P2':('selective_copy','mqar_overwrite_recall','irregular_time',
      'multiple_regeneration','cross_process_recovery'),
'P3':('real_four_modal_encoders','cross_modal_retrieval','temporal_grounding',
      'missing_modality','untouched_ood'),
'P4':('rust_native_neuron','gpu_native_kernel','low_precision_golden_vectors',
      'four_scale_measurement','direct_energy_measurement','fault_recovery'),
'P5':('shared_encoder_hcsn_head','tuned_transformer_ssm_baselines',
      'matched_quality_full_cost','negative_transfer','replicated_net_gain'),
}
HEX64=re.compile('[0-9a-f]{64}\\Z')
HEX40=re.compile('[0-9a-f]{40}\\Z')

class EvidenceError(ValueError): pass

@dataclass(frozen=True)
class StageOutcome:
    stage: str
    status: str
    missing: tuple[str,...]
    failed: tuple[str,...]
    declared_pass_only: tuple[str,...]


def _digest(value,what,length=64):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{'+str(length)+r'}',value):
        raise EvidenceError(f'invalid {what} sha')


def _receipt(name, data):
    if type(data) is not dict or set(data)!={'result','real_execution',
                                           'source_sha','result_sha256','run_log_sha256'}:
        raise EvidenceError(f'{name}: wrong evidence-receipt schema')
    if data['result'] not in ('PASS','FAIL','MISSING'):
        raise EvidenceError(f'{name}: unknown result')
    if type(data['real_execution']) is not bool:
        raise EvidenceError(f'{name}: real_execution must be bool')
    if data['result']=='PASS':
        if data['real_execution'] is not True:
            raise EvidenceError(f'{name}: skipped/synthetic cannot pass')
        _digest(data['source_sha'],name+' source',40)
        _digest(data['result_sha256'],name+' result')
        _digest(data['run_log_sha256'],name+' log')
    else:
        # Failed/missing gates may lack running evidence; never invent it.
        for k,v in (('source_sha',data['source_sha']),
                    ('result_sha256',data['result_sha256']),
                    ('run_log_sha256',data['run_log_sha256'])):
            if v is not None:
                _digest(v,name+' '+k,40 if k=='source_sha' else 64)


def evaluate_ledger(ledger: dict) -> dict:
    if type(ledger) is not dict or set(ledger)!={'schema','repository','main_sha',
                                               'source_status','stages','hardware'}:
        raise EvidenceError('wrong top-level gatebook schema')
    if ledger['schema']!='hcsn-sixstage-research-v1':
        raise EvidenceError('unknown research gatebook schema')
    if ledger['repository']!='TrillionniumFoundation/hepta-private-ci':
        raise EvidenceError('wrong or ambiguous repository')
    if ledger['source_status'] not in ('VERIFIED_EXTERNAL','GITHUB_403','UNKNOWN'):
        raise EvidenceError('invalid source verification status')
    if ledger['main_sha'] is not None:
        _digest(ledger['main_sha'],'main',40)
    if type(ledger['stages']) is not dict or set(ledger['stages'])!=set(REQUIRED):
        raise EvidenceError('six stages required, no aliases')
    hardware=ledger['hardware']
    if type(hardware) is not dict or set(hardware)!={'scale_runs','device','meter'}:
        raise EvidenceError('incomplete hardware section')
    scale_runs=hardware['scale_runs']
    if type(scale_runs) is not dict or any(str(x) not in scale_runs for x in (64,256,1024,4096)):
        raise EvidenceError('four scale metadata slots required')
    for n in (64,256,1024,4096):
        row=scale_runs[str(n)]
        if row is None:
            continue
        required=('p95_ms','p99_ms','rss_mib','vram_mib','joules',
                  'throughput_cell_s','recovery_ms','run_log_sha256')
        if type(row) is not dict or set(row)!=set(required):
            raise EvidenceError(f'wrong {n}-Cell hardware receipt schema')
        _digest(row['run_log_sha256'],f'{n} scale log')
        for key in required[:-1]:
            value=row[key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise EvidenceError(f'{n} {key} must be actually measured nonnegative')
        if not (row['p95_ms']<=row['p99_ms'] and row['joules']>0 and
                row['throughput_cell_s']>0):
            raise EvidenceError(f'{n}-Cell impossible timing/energy evidence')

    outcomes=[]
    for stage, gates in REQUIRED.items():
        entries=ledger['stages'][stage]
        if type(entries) is not dict or set(entries)!=set(gates):
            raise EvidenceError(f'{stage} missing or unknown gate names')
        missing=[];failed=[];passed=[]
        for name in gates:
            receipt=entries[name]
            _receipt(f'{stage}.{name}',receipt)
            if receipt['result']=='MISSING':missing.append(name)
            elif receipt['result']=='FAIL':failed.append(name)
            else:passed.append(name)
        status='FAILED' if failed else 'INCOMPLETE' if missing else 'DECLARED_PASS_UNVERIFIED'
        outcomes.append(StageOutcome(stage,status,tuple(missing),tuple(failed),tuple(passed)))

    # These dependencies cannot be replaced by standalone local math tests.
    p4_complete=all(scale_runs[str(s)] is not None for s in (64,256,1024,4096))
    unmet=[x.stage for x in outcomes if x.status!='DECLARED_PASS_UNVERIFIED']
    if not p4_complete and 'P4' not in unmet: unmet.append('P4')
    if ledger['source_status']!='VERIFIED_EXTERNAL' or ledger['main_sha'] is None:
        remote_status='UNVERIFIED_REMOTE_SOURCE'
    else:
        remote_status='SOURCE_SHA_DECLARED_BUT_NOT_INDEPENDENTLY_ATTESTED'
    return {
        'schema':'hcsn-sixstage-report-v1',
        'remote_verification':remote_status,
        'stages':[asdict(x) for x in outcomes],
        'four_hardware_scales_complete':p4_complete,
        'blocking_stages':sorted(unmet),
        'all_blockers_closed':False,  # Offline report cannot authenticate release authority.
        'production_activation_allowed':False,
        'decision':'DENY_ALL_OFFLINE_RESEARCH_ONLY',
    }


def pending_ledger():
    """Grounded startup ledger: no inferred PASS, no fictional hardware."""
    def absent():
        return dict(result='MISSING',real_execution=False,source_sha=None,
                    result_sha256=None,run_log_sha256=None)
    return dict(schema='hcsn-sixstage-research-v1',
                repository='TrillionniumFoundation/hepta-private-ci',
                main_sha=None,source_status='GITHUB_403',
                hardware=dict(scale_runs={str(n):None for n in (64,256,1024,4096)},
                              device=None,meter=None),
                stages={stage:{k:absent() for k in keys} for stage,keys in REQUIRED.items()})
