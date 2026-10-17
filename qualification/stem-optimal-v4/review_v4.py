"""Independent original-publisher postseal scorer; no model loading or training.

The v3 three-arm original scorer remains authoritative for its own inputs.
This extension checks a fourth, distinct model receipt. Always HOLD_NO_GO.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import stem_v4 as core

sys.path.insert(0,str(core.ROOT / 'stem-optimal-v3'))
sys.path.insert(0,str(core.ROOT / 'stem-optimal-v1'))

ARMS = ('centroid','frozen_init','learned')
FIELDS = {
    'schema','cohort','candidate','source_plan_sha256','model_repo','model_revision',
    'actual_weight_sha256','model_precision','actual_loaded_parameters','original_parameter_audit',
    'native_width','projected_width',
    'projection','prompt_name','initial_head_sha256','trained_head_sha256',
    'head_parameters','optimizer_steps','rows','cost','fleet','train_only_centroid',
    'future_windows',
    'human_verified_new_sources','ndu_task_utility_qualified',
    'cell_split_authorized','production_authorized','authority','disposition'
}
COST = {'physical_encoder_sequences','physical_encoder_forward_batches',
        'model_load_seconds','embedding_seconds','head_train_seconds',
        'complete_wall_seconds','complete_cpu_seconds','maxrss_bytes_linux_unattested',
        'energy_joules','complete_request_p99_ms'}
FLEET = {'fleet_cell_count','active_heads_per_call','head_parameter_count',
         'head_weight_bytes_fp32','timed_batched_calls','head_batch_p95_ms',
         'head_batch_p99_ms','last_logit_sha256','real_pretrained_input_feature',
         'complete_request_p99','energy_joules','target_host_attested'}


def safe_float(x, lo=0.0, hi=1e12):
    return type(x) in (float,int) and math.isfinite(x) and lo <= x <= hi


def check_fourth(source, receipt, gold):
    """Presealed receipt + independent heldout label mapping; no raw targets in run."""
    core.require(type(source) is dict and type(receipt) is dict and set(receipt) == FIELDS,
                 'unknown or label-bearing receipt keys')
    core.require(receipt['schema'] == core.SCHEMA and receipt['cohort'] == core.COHORT
                 and receipt['candidate'] == core.ARM
                 and receipt['source_plan_sha256'] == source['source_plan_sha256'],
                 'wrong cohort or source digest')
    core.require((receipt['model_repo'],receipt['model_revision'],receipt['actual_weight_sha256'])
                 == (core.REPO, core.REVISION, core.WEIGHT_SHA), 'unpinned fourth model')
    core.require(type(receipt['actual_loaded_parameters']) is int and
                 200_000_000 <= receipt['actual_loaded_parameters'] <= 350_000_000,
                 'unqualified text-only loaded parameter census')
    material = receipt['original_parameter_audit']
    import material_census_v5 as source_census
    core.require(type(material) is dict and set(material) == {
        'profile','original_weight_sha256','runtime_parameter_elements',
        'runtime_unique_parameter_tensors','original_archive_tensor_count',
        'source_tensor_elements_including_unused_modalities',
        'source_value_coverage_verified','strict_logical_name_mapping_verified',
        'model_issuer_signature_verified','proof_digest',
        'audit_wall_seconds_unattested'},
        'missing required original parameter source census')
    core.require(material['profile'] == source_census.PROFILE and
                 material['original_weight_sha256'] == core.WEIGHT_SHA and
                 material['runtime_parameter_elements'] == receipt['actual_loaded_parameters'] and
                 type(material['runtime_unique_parameter_tensors']) is int and
                 100 <= material['runtime_unique_parameter_tensors'] <= 2500 and
                 type(material['original_archive_tensor_count']) is int and
                 300 <= material['original_archive_tensor_count'] <= 5000 and
                 type(material['source_tensor_elements_including_unused_modalities']) is int and
                 600_000_000 <= material['source_tensor_elements_including_unused_modalities'] <= 1_000_000_000 and
                 material['source_value_coverage_verified'] is True and
                 material['strict_logical_name_mapping_verified'] is False and
                 material['model_issuer_signature_verified'] is False and
                 type(material['proof_digest']) is str and
                 len(material['proof_digest']) == 64 and
                 all(c in '0123456789abcdef' for c in material['proof_digest']) and
                 safe_float(material['audit_wall_seconds_unattested'], 0, 10000),
                 'original pretrained text parameters are unverified')
    core.require(receipt['model_precision'] == 'fp32_cpu' and
                 receipt['native_width'] == 768 and receipt['projected_width'] == 384 and
                 receipt['projection'] == core.PROJECTION and
                 receipt['prompt_name'] == 'Classification', 'unmatched projection/input profile')
    core.require(receipt['head_parameters'] == 27656 and
                 receipt['optimizer_steps'] == 100, 'head parameter/update count')
    for fld in ('initial_head_sha256','trained_head_sha256'):
        value=receipt[fld]
        core.require(type(value) is str and len(value)==64 and
                     all(c in '0123456789abcdef' for c in value), 'head digest invalid')
    core.require(receipt['initial_head_sha256'] != receipt['trained_head_sha256'],
                 'no trained head state')
    core.require(receipt['authority'] == 'DENY_ALL' and
                 receipt['disposition'] == 'HOLD_NO_GO' and
                 receipt['future_windows'] == 0 and receipt['human_verified_new_sources'] == 0 and
                 receipt['ndu_task_utility_qualified'] is False and
                 receipt['cell_split_authorized'] is False and
                 receipt['production_authorized'] is False, 'unauthorized scientific promotion')
    cost=receipt['cost']
    core.require(type(cost) is dict and set(cost)==COST, 'incomplete real cost receipt')
    core.require(type(cost['physical_encoder_sequences']) is int and
                 cost['physical_encoder_sequences']==96 and
                 type(cost['physical_encoder_forward_batches']) is int and
                 cost['physical_encoder_forward_batches']==6, 'no complete real forwards')
    for field in COST - {'physical_encoder_sequences','physical_encoder_forward_batches',
                         'energy_joules','complete_request_p99_ms'}:
        core.require(safe_float(cost[field]), 'invalid meter')
    core.require(cost['energy_joules'] is None and
                 cost['complete_request_p99_ms'] is None, 'unattested energy or p99')
    fleet=receipt['fleet']
    core.require(type(fleet) is dict and set(fleet)==FLEET,'malformed fleet')
    core.require(fleet['fleet_cell_count']==4096 and fleet['active_heads_per_call']==32
                 and fleet['head_parameter_count']==4096*6914 and
                 fleet['head_weight_bytes_fp32']==4096*6914*4 and
                 fleet['timed_batched_calls']==64, 'invented fleet inventory')
    core.require(fleet['real_pretrained_input_feature'] is True and
                 fleet['target_host_attested'] is False and
                 fleet['complete_request_p99'] is None and fleet['energy_joules'] is None,
                 'false target host or lifecycle receipt')
    core.require(safe_float(fleet['head_batch_p95_ms']) and
                 safe_float(fleet['head_batch_p99_ms']) and
                 fleet['head_batch_p95_ms'] <= fleet['head_batch_p99_ms'],
                 'invalid head timings')
    core.require(type(fleet['last_logit_sha256']) is str and
                 len(fleet['last_logit_sha256'])==64 and
                 all(ch in '0123456789abcdef' for ch in fleet['last_logit_sha256']),
                 'unbound real head output')
    expected = source['heldout']
    rows = receipt['rows']
    core.require(type(rows) is list and len(rows)==len(expected)==32
                 and type(gold) is dict and set(gold)=={r['case_id'] for r in expected},
                 'missing independent original case/gold')
    result={}
    for arm in ARMS:
        result[arm]={'correct':0,'brier_sum':0.0}
    for row, registered in zip(rows,expected):
        core.require(type(row) is dict and set(row)=={'case_id','source_sha256','scores'}
                     and row['case_id']==registered['case_id'] and
                     row['source_sha256']==registered['source_sha256'],
                     'case source/order substitution')
        core.require(type(row['scores']) is dict and set(row['scores'])==set(ARMS),
                     'missing score arm')
        y=gold[row['case_id']]
        core.require(type(y) is int and 0 <= y < 4, 'original human label invalid')
        for arm in ARMS:
            prob=row['scores'][arm]
            core.require(type(prob) is list and len(prob)==4 and
                         all(safe_float(p,0,1) for p in prob) and
                         abs(sum(prob)-1)<1e-5, 'invalid probability distribution')
            result[arm]['correct'] += int(max(range(4),key=lambda i: prob[i])==y)
            result[arm]['brier_sum'] += sum((p-int(i==y))**2 for i,p in enumerate(prob))
    import train_only_centroid_v5 as centroid
    control = receipt['train_only_centroid']
    core.require(type(control) is dict and set(control) == {
        'schema','selected_temperature','registered_temperatures',
        'fit_only_loocv_multiclass_brier','fit_examples','fit_per_class_counts',
        'heldout_labels_used_for_calibration','heldout_calibration_metric_selected',
        'new_head_sgd_steps','train_feature_digest','output_rows',
        'fit_and_output_wall_seconds_unattested','new_model_forward_calls',
        'production_authorized'}, 'missing train-only centroid control')
    losses=control['fit_only_loocv_multiclass_brier']
    core.require(control['schema'] == centroid.PROFILE and
                 control['registered_temperatures'] == list(centroid.TEMPERATURES) and
                 type(losses) is list and len(losses) == len(centroid.TEMPERATURES) and
                 all(safe_float(v,0,2) for v in losses) and
                 control['selected_temperature'] == centroid.TEMPERATURES[
                    min(range(len(losses)),key=lambda i:(losses[i],i))] and
                 control['fit_examples'] == 64 and
                 control['fit_per_class_counts'] == [16]*4 and
                 control['heldout_labels_used_for_calibration'] is False and
                 control['heldout_calibration_metric_selected'] is False and
                 control['new_head_sgd_steps'] == 0 and
                 control['new_model_forward_calls'] == 0 and
                 control['production_authorized'] is False and
                 safe_float(control['fit_and_output_wall_seconds_unattested']) and
                 type(control['train_feature_digest']) is str and
                 len(control['train_feature_digest']) == 64 and
                 all(ch in '0123456789abcdef' for ch in control['train_feature_digest']),
                 'non-FIT-only or unbounded cheap baseline calibration')
    cal_rows=control['output_rows']
    core.require(type(cal_rows) is list and len(cal_rows) == 32,
                 'missing calibrated centroid outputs')
    scored={'correct':0,'brier_sum':0.0}
    for row, registered in zip(cal_rows,expected):
        core.require(type(row) is dict and set(row) == {
            'case_id','source_sha256','probabilities'} and
            row['case_id']==registered['case_id'] and
            row['source_sha256']==registered['source_sha256'],
            'calibrated source ID drift')
        q = row['probabilities']
        core.require(type(q) is list and len(q)==4 and
                     all(safe_float(v,0,1) for v in q) and
                     abs(sum(q)-1)<1e-5, 'invalid train-only centroid scores')
        y=gold[row['case_id']]
        scored['correct']+=int(max(range(4),key=q.__getitem__)==y)
        scored['brier_sum']+=sum((v-int(i==y))**2 for i,v in enumerate(q))
    result['train_only_loocv_centroid']={
        'correct':scored['correct'],'n':32,'brier':scored['brier_sum']/32,
        'temperature_selected_on_training_only':control['selected_temperature'],
        'calibration_requires_additional_head_sgd':False,
        'independent_source_future_qualified':False}
    return {
        arm:(values if arm=='train_only_loocv_centroid' else
             {'correct':values['correct'],'n':32,'brier':values['brier_sum']/32})
        for arm,values in result.items()}


def ensure_matched_initial_heads(old_runs, fourth):
    core.require(type(old_runs) is list and len(old_runs) == 3 and
                 all(type(r) is dict and 'initial_head_sha256' in r for r in old_runs),
                 'missing incumbent initializer receipts')
    digests={r['initial_head_sha256'] for r in old_runs}
    core.require(len(digests) == 1 and fourth['initial_head_sha256'] in digests,
                 'cross-version initial Head tensor mismatch; not equal Head baseline')


def quarantine_unqualified_mmbert(incumbent):
    """Keep the original score audit but never rank a randomly initialized stem.

    V3 run 39002204047, original mmBERT job 117331622649 warns that
    embeddings.tok_embeddings.weight is newly initialized.  This static
    negative observation is NOT a new model loader certificate.  All original
    V3 artifacts remain immutable and can be reopened separately.
    """
    import copy
    core.require(type(incumbent) is dict and type(incumbent.get('models')) is dict
                 and set(incumbent['models']) == {'granite47', 'granite97', 'mmbert140'},
                 'three original source-bound model records required before exclusion')
    out = copy.deepcopy(incumbent)
    out['models'].pop('mmbert140')
    out['disqualified_comparator'] = {
        'candidate': 'mmbert140',
        'reason_code': 'ORIGINAL_PRETRAINED_TOKEN_EMBEDDING_NOT_LOADED',
        'original_run_id': 39002204047,
        'original_job_id': 117331622649,
        'job_warning_independently_fetched_in_this_workflow': False,
        'original_prediction_bytes_preserved_in_v3_artifact': True,
        'descriptive_score_eligible': False,
        'pretrained_model_qualified': False,
    }
    out['eligible_descriptive_baselines'] = ['granite47', 'granite97']
    out['all_checkpoint_parameters_independently_qualified'] = False
    return out


# Precommitted finite sensitivity *reporting* grid, never fitted on heldout gold.
# A heldout-optimal temperature is NOT selected or used by a producer.
TEMPERATURES = (1.0, 0.25, 0.0625, 0.015625)


def postseal_centroid_temperature_sensitivity(old_runs, gold):
    """Test a cheap zero-Head-SGD alternative after all model predictions seal.

    Temperature cannot be selected from these same heldout labels and then
    reported as externally calibrated efficacy. Return the entire fixed grid.
    The original V3 score vectors/provenance are separately checked by the V3
    independent reviewer before this diagnostic is called.
    """
    core.require(type(old_runs) is list and len(old_runs) == 3 and
                 type(gold) is dict and len(gold) == 32, 'original panel incomplete')
    result = {}
    for run in old_runs:
        name = run.get('candidate')
        if name == 'mmbert140':
            continue  # known original randomly initialized checkpoint
        core.require(name in ('granite47', 'granite97') and name not in result,
                     'unregistered cheap-control candidate')
        rows = run['rows']
        core.require(type(rows) is list and len(rows) == 32 and
                     {r['case_id'] for r in rows} == set(gold), 'cheap-control case identity')
        measures = {}
        for temperature in TEMPERATURES:
            total, correct = 0.0, 0
            for row in rows:
                y = gold[row['case_id']]
                p = row['scores']['centroid']
                core.require(type(y) is int and 0 <= y < 4 and
                             type(p) is list and len(p) == 4 and
                             all(type(v) in (float, int) and math.isfinite(v)
                                 and 0 <= v <= 1 for v in p) and
                             abs(sum(p) - 1) < 1e-5,
                             'unbound or invalid original centroid probabilities')
                # Stable softmax(log(p) / T), preserves argmax for every T>0.
                logits = [math.log(max(float(v), 1e-300))/temperature for v in p]
                pivot = max(logits)
                w = [math.exp(v-pivot) for v in logits]
                z = sum(w)
                q = [v/z for v in w]
                correct += int(max(range(4), key=q.__getitem__) == y)
                total += sum((q[i]-float(i == y))**2 for i in range(4))
            measures[str(temperature)] = {'correct':correct,'n':32,
                                          'mean_multiclass_brier':total/32}
        result[name] = measures
    core.require(set(result) == {'granite47','granite97'}, 'both valid cheap controls missing')
    return {'temperatures_fixed_in_advance':list(TEMPERATURES),
            'heldout_temperature_selected':False,
            'train_only_calibrated':False,
            'additional_head_sgd_steps':0,
            'postseal_diagnostic_not_model_qualification':True,
            'models':result}


def review_original(train_raw, test_raw, source, old_runs, fourth, materials):
    import stem_hard_charge_review_v3 as v3_review
    import stem_candidate_v1 as v1
    # Independently reconstruct the complete roster, both truth files and v3 controls.
    incumbent = v3_review._review(train_raw,test_raw,source,old_runs,materials)
    incumbent = quarantine_unqualified_mmbert(incumbent)
    _,gold=v3_review.reconstruct(train_raw,test_raw,v1.ORIGINAL_SHA)
    sensitivity = postseal_centroid_temperature_sensitivity(old_runs, gold)
    core.check_source(source)
    fourth_result=check_fourth(source,fourth,gold)
    ensure_matched_initial_heads(old_runs, fourth)
    return {'schema':'hepta.stem.original-four-model-postseal.v4',
            'cohort':core.COHORT,'source_sha256':source['source_plan_sha256'],
            'existing_original_three_model_scoring':incumbent,
            'postseal_zero_sgd_centroid_temperature_sensitivity':sensitivity,
            'fourth_model':{'id':core.ARM,'source':'original_pretrained_embeddinggemma2',
                            'descriptive_scores':fourth_result,
                            'matched_training_budget_only':True,
                            'matched_end_to_end_compute':False},
            'future_windows':0,'new_source_families':0,'stem_winner_verified':False,
            'system2_net_utility_verified':False,'production_authorized':False,
            'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}


def main():
    p=argparse.ArgumentParser()
    for key in ('train','test','source','old_granite47','old_granite97',
                'old_mmbert140','fourth','materials','output'):
        p.add_argument('--'+key.replace('_','-'),type=Path,required=True)
    args=p.parse_args()
    def file_bytes(path):
        core.require(path.is_file() and not path.is_symlink() and
                     path.stat().st_size<=2_000_000,'publisher material size')
        return path.read_bytes()
    result=review_original(file_bytes(args.train),file_bytes(args.test),
                           core.read_json(args.source),
                           [core.read_json(getattr(args,'old_'+name))
                            for name in ('granite47','granite97','mmbert140')],
                           core.read_json(args.fourth),core.read_json(args.materials))
    core.write_private(args.output,result)

if __name__=='__main__':
    main()
