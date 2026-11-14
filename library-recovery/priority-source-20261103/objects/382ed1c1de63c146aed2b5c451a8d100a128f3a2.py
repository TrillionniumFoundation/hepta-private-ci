"""Fail-closed P0–P5 evidence inventory. This DOES NOT authenticate evidence.

No automated production promotion: manual independent evidence inspection,
source/CI provenance, hardware logs and scientific replication remain required.
"""
import json
from pathlib import Path

REQUIREMENTS={
    'P0':['full_hx_equity_obstacle','full_parameter_domain','independent_numerical_solver',
          'boundary_gradients','fp32_bf16','degenerate_limits','regenerative_qvi'],
    'P1':['call_only','risk_only','margin_only','call_risk','call_margin',
          'risk_margin','call_risk_margin','slope_and_parameter_match',
          'same_training_budget','unseen_mechanism_attribution'],
    'P2':['selective_copy','mqar','overwrite','long_range','irregular_time',
          'multiple_regenerations','checkpoint_causality'],
    'P3':['paired_text_image','paired_text_audio','paired_audio_video',
          'paired_four_modality','ood_noise_robustness','entity_time_holdout'],
    'P4':['rust_native_kernel','gpu_native_kernel','cells_64','cells_256',
          'cells_1024','cells_4096','real_energy_joules','crash_recovery'],
    'P5':['matched_train_tokens','matched_train_flops','matched_total_cost',
          'tuned_transformer_baseline','tuned_ssm_baseline',
          'unseen_holdout_advantage','negative_transfer_guard']
}


def empty_ledger():
    return {'schema':'hcsn-p0-p5-evidence-inventory-v1',
            'production_activation_allowed':False,
            'all_blockers_closed':False,
            'stage_evidence':{k:{name:{'status':'OPEN','artifact':None}
                                  for name in names}
                              for k,names in REQUIREMENTS.items()}}


def assess(ledger):
    if ledger.get('schema')!='hcsn-p0-p5-evidence-inventory-v1':
        raise ValueError('unsupported evidence schema')
    results={}
    for stage,names in REQUIREMENTS.items():
        items=ledger.get('stage_evidence',{}).get(stage,{})
        unclosed=[]
        for name in names:
            datum=items.get(name,{})
            # Status claims alone never close a gate; supporting artifact must
            # be present, with independent verification still manual.
            if datum.get('status')!='PASS' or not datum.get('artifact'):
                unclosed.append(name)
        results[stage]={'evidence_items_required':len(names),
                        'evidence_items_missing_or_unverified':len(unclosed),
                        'missing':unclosed,
                        'status':'OPEN' if unclosed else 'REQUIRES_INDEPENDENT_REVIEW'}
    return {'results':results,'all_blockers_closed':False,
            'production_activation_allowed':False,'policy':'DENY_ALL',
            'note':'Presence of an artifact is not independent certification.'}


def write_template(path):
    Path(path).write_text(json.dumps(empty_ledger(),ensure_ascii=False,indent=2)+'\n')
