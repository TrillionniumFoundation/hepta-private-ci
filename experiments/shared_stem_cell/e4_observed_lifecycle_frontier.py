#!/usr/bin/env python3
"""Read-only observed-cost frontier for ORIGINAL P0 → E1 → E3 studies.

Accounts real recorded stages without promoting any model, inventing missing
FLOPs/energy/p99 or treating self-timed experiments as production telemetry.
No Torch, foundation loader, model training, source writes, or human labels.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

MODELS=('granite_97m_r2','mmbert_small','embeddinggemma_2_text')
BUDGETS=(4,8,12)
SEEDS=(41,47,53)
KINDS=('additive','gated')
ARMS=('frozen_additive','trained_additive','frozen_gated','trained_gated')
POPULATION=(64,256,1024,4096)
HEAD_PARAMETERS=4145
SCHEMA='hepta.e4.partial-observed-training-cost-frontier.v1'


def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def sha(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def finite_nonnegative(x,label):
    if type(x) not in (int,float) or not math.isfinite(x) or x<0:
        raise ValueError('nonfinite/missing measured '+label)
    return float(x)


def known_positive(x,label):
    v=finite_nonnegative(x,label)
    if v<=0:
        raise ValueError('zero measured '+label)
    return v


def exact_bool(record,key,value):
    if record.get(key) is not value:
        raise ValueError('unsupported claim or missing '+key)


def observed_frontier(fit,blind,p0_reports,e1_reports,e2_seals,e3_reports,e3_reviews,e3_human,*,candidate_sha,run_id):
    if (type(fit) is not dict or type(blind) is not dict or
        type(fit.get('cases')) is not list or type(blind.get('cases')) is not list or
        not fit['cases'] or not blind['cases'] or
        fit.get('metadata')!=blind.get('metadata') or
        type(e3_human) is not dict or
        e3_human.get('schema')!='hepta.e3.original-human-source-budget-descriptive-score.v1' or
        e3_human.get('authority')!='DENY_ALL' or
        type(e3_human.get('models')) is not dict or
        set(e3_human['models'])!=set(MODELS) or
        not all(type(z) is dict and set(z)==set(MODELS)
                for z in (p0_reports,e1_reports,e2_seals,e3_reports,e3_reviews)) or
        type(candidate_sha) is not str or len(candidate_sha)!=40 or
        any(c not in '0123456789abcdef' for c in candidate_sha) or
        type(run_id) is not int or run_id<=0):
        raise ValueError('incomplete source-bound original model cost frontier')
    for k in ('descriptive_only','old_task_retention_verified','stem_or_head_winner_selected',
              'production_promotion_permitted','full_training_plus_serving_cost_matched'):
        exact_bool(e3_human,k,k=='descriptive_only')
    if (e3_human.get('train_source_group_budgets')!=list(BUDGETS) or
        e3_human.get('independent_original_source_groups')!=8):
        raise ValueError('not original eight-source human efficacy study')
    fit_sha,blind_sha=sha(fit),sha(blind)
    n_inputs=len(fit['cases'])+len(blind['cases'])
    out={}
    for model in MODELS:
        p0,e1,e2,e3,ind=(dataset[model] for dataset in
                         (p0_reports,e1_reports,e2_seals,e3_reports,e3_reviews))
        quality=e3_human['models'][model]
        if any(type(x) is not dict for x in (p0,e1,e2,e3,ind,quality)):
            raise ValueError('missing original model receipt')
        if (p0.get('model')!=model or e1.get('model')!=model or
            p0.get('fit_material_sha256')!=fit_sha or
            p0.get('blind_material_sha256')!=blind_sha or
            e1.get('original_fit_sha256')!=fit_sha or
            e1.get('original_blind_sha256')!=blind_sha or
            e2.get('model')!=model or e3.get('model')!=model or
            e3.get('candidate_head_sha')!=candidate_sha or
            e3.get('candidate_run_id')!=run_id or
            e2.get('candidate_head_sha')!=candidate_sha or
            e2.get('candidate_run_id')!=run_id or
            e1.get('original_report_sha256')!=sha(p0) or
            e2.get('original_report_sha256')!=sha(p0) or
            e2.get('probe_report_sha256')!=sha(e1) or
            e2.get('blind_material_sha256')!=blind_sha or
            e3.get('original_e1_probe_sha256')!=sha(e1) or
            e3.get('original_e1_numeric_sha256')!=e2.get('numeric_review_sha256') or
            e3.get('original_fit_sha256')!=fit_sha or
            e3.get('original_blind_sha256')!=blind_sha or
            e3.get('p0_original_report_sha256')!=sha(p0) or
            ind.get('reviewed_e3_report_sha256')!=sha(e3) or
            ind.get('reviewed_e3_weights_sha256')!=e3.get('e3_trained_weights_sha256') or
            ind.get('reviewed_original_fit_sha256')!=fit_sha or
            ind.get('reviewed_original_blind_sha256')!=blind_sha or
            ind.get('reviewed_e1_report_sha256')!=sha(e1) or
            ind.get('reviewed_model')!=model):
            raise ValueError('P0/E1/E2/E3 physical original/source/gradient lineage mismatch')
        for rec in (p0,e1,e2,e3,ind):
            if rec.get('authority')!='DENY_ALL':
                raise ValueError('cannot treat research cost as execution authority')
            exact_bool(rec,'production_promotion_permitted',False)
        for rec,key in ((e1,'quality_scored'),(e1,'model_selection_permitted'),
                        (e1,'end_to_end_cost_equal'),(e1,'native_representation_preserved'),
                        (e1,'physical_model_origin_independently_authenticated'),
                        (e3,'statistical_winner_selected')):
            exact_bool(rec,key,False)
        exact_bool(p0,'physical_model_origin_independently_signed',False)
        exact_bool(e3,'equal_full_lifecycle_cost_certified',False)
        exact_bool(ind,'independent_cpu_performance_attested',False)
        if e1.get('additional_pretrained_loads')!=0 or e1.get('additional_encoder_forwards')!=0:
            raise ValueError('unregistered E1 pretrained load/forward')
        if (e3.get('additional_encoder_loads')!=0 or e3.get('additional_encoder_forwards')!=0 or
            e3.get('projection_extra_physical_forwards')!=1):
            raise ValueError('missing or hidden E3 projection/model work')
        width=e1.get('source_width')
        if type(width) is not int or width not in (256,384):
            raise ValueError('unexpected original compact model width')
        proj=e1.get('shared_projection')
        if (type(proj) is not dict or proj.get('coefficient_count')!=width*128 or
            proj.get('fp32_bytes')!=width*128*4 or
            proj.get('linear_forward_macs')!=n_inputs*width*128 or
            proj.get('projected_bank_bytes')!=n_inputs*128*4 or
            e3.get('projection_extra_mac')!=n_inputs*width*128 or
            e3.get('projection_extra_fp32_bytes')!=n_inputs*128*4):
            raise ValueError('unpaid/incorrect shared projection/cache cost')
        p0_wall=known_positive(p0.get('local_process_wall_ms'),'P0 whole-process wall')
        p0_cpu=known_positive(p0.get('local_process_cpu_ms'),'P0 whole-process CPU')
        original_rss=known_positive(p0.get('local_peak_rss_bytes'),'P0 original process peak RSS')
        profiles=p0.get('complete_source_profiles')
        if (type(profiles) is not dict or
            profiles.get('physical_encoder_api_requests')!=n_inputs or
            not isinstance(profiles.get('physical_encoder_ms_by_case'),dict) or
            len(profiles['physical_encoder_ms_by_case'])!=n_inputs):
            raise ValueError('missing physical original pretrained Encoder request inventory')
        p0_load=known_positive(profiles.get('model_load_ms'),'P0 model load')
        if p0_load>p0_wall+5:
            raise ValueError('claimed P0 model load exceeds whole-process wall')
        e1_arms=e1.get('arms')
        if (type(e1_arms) is not list or
            [(r.get('seed'),r.get('arm')) for r in e1_arms] !=
             [(seed,arm) for seed in SEEDS for arm in ARMS]):
            raise ValueError('not full matched E1 per-head training and frozen controls')
        if any(r.get('parameter_count')!=HEAD_PARAMETERS for r in e1_arms):
            raise ValueError('nonmatched E1 parameter count')
        e1_train_wall=e1_train_cpu=e1_eval_wall=e1_eval_cpu=0.0
        for arm in e1_arms:
            trained=arm['arm'].startswith('trained_')
            if (arm.get('optimizer_steps')!=(40 if trained else 0) or
                arm.get('training_row_exposures')!=(40*len([
                    r for r in fit['cases'] if r.get('split')=='train' and r.get('condition')=='original']) if trained else 0)):
                raise ValueError('incorrect actual E1 training exposures')
            e1_train_wall+=finite_nonnegative(arm.get('fit_wall_ms'),'E1 Head training wall')
            e1_train_cpu+=finite_nonnegative(arm.get('fit_cpu_ms'),'E1 Head training CPU')
            e1_eval_wall+=finite_nonnegative(arm.get('calibration_and_blind_wall_ms'),'E1 CAL/held wall')
            e1_eval_cpu+=finite_nonnegative(arm.get('calibration_and_blind_cpu_ms'),'E1 CAL/held CPU')
        e1_proj_wall=finite_nonnegative(proj.get('one_time_bank_wall_ms'),'E1 shared bank wall')
        e1_proj_cpu=finite_nonnegative(proj.get('one_time_bank_cpu_ms'),'E1 shared bank CPU')
        e3_proj_wall=finite_nonnegative(e3.get('projection_wall_ms'),'E3 duplicated bank wall')
        e3_proj_cpu=finite_nonnegative(e3.get('projection_cpu_ms'),'E3 duplicated bank CPU')
        r3=e3.get('records')
        if (type(r3) is not list or
            [(r.get('budget_source_groups'),r.get('seed'),r.get('architecture')) for r in r3]!=
             [(n,s,k) for n in BUDGETS for s in SEEDS for k in KINDS]):
            raise ValueError('incomplete E3 physical sampled budget records')
        budget_status=ind.get('budget_status')
        if type(budget_status) is not dict or set(budget_status)!=set(map(str,BUDGETS)):
            raise ValueError('missing original infeasible-vs-trained budget audit')
        budget_summary={}
        e3_train_wall=e3_train_cpu=0.0
        for budget in BUDGETS:
            records=[r for r in r3 if r['budget_source_groups']==budget]
            trained=[r for r in records if r.get('status')=='trained']
            infeasible=[r for r in records if r.get('status')=='missing_both_labels']
            if len(trained)+len(infeasible)!=6 or (trained and infeasible):
                raise ValueError('partially missing or fabricated E3 budget')
            flag='qualifiable' if trained else 'infeasible_missing_both_labels'
            if budget_status.get(str(budget))!=flag:
                raise ValueError('independent E3 budget status not matched')
            bw=bc=0.0
            for arm in trained:
                if (arm.get('optimizer_updates')!=40 or
                    arm.get('head_parameter_count')!=HEAD_PARAMETERS or
                    arm.get('train_row_exposures')!=40*arm.get('training_rows',-1)):
                    raise ValueError('missing E3 physical SGD/head exposure')
                bw+=finite_nonnegative(arm.get('train_wall_ms'),'E3 Head fit wall')
                bc+=finite_nonnegative(arm.get('train_cpu_ms'),'E3 Head fit CPU')
            e3_train_wall+=bw;e3_train_cpu+=bc
            budget_summary[str(budget)]={'trained_head_runs':len(trained),
                'infeasible_head_runs':len(infeasible),'measured_train_wall_ms':bw,
                'measured_train_cpu_ms':bc,
                'end_to_end_inference_cost_ms':None}
        if (quality.get('head_parameter_count_each')!=HEAD_PARAMETERS or
            type(quality.get('budgets')) is not dict or
            set(quality['budgets'])!=set(map(str,BUDGETS))):
            raise ValueError('human quality/budget census differs from E3 cost')
        for budget in BUDGETS:
            human=quality['budgets'][str(budget)]
            if type(human) is not dict or set(human.get('seeds',{}))!=set(str(s) for s in SEEDS):
                raise ValueError('missing exact human source-seed budget grid')
            expected_status='descriptive_source_scored' if budget_summary[str(budget)]['trained_head_runs'] else 'infeasible_missing_two_train_labels'
            if human.get('status')!=expected_status:
                raise ValueError('human efficacy reported on physically unavailable Head budget')
            for seed in SEEDS:
                row=human['seeds'][str(seed)]
                if row.get('status') != ('scored_original_human_only' if expected_status=='descriptive_source_scored' else 'infeasible_missing_two_train_labels'):
                    raise ValueError('missing or falsely scored original-human budget')
                if expected_status=='descriptive_source_scored':
                    for name in KINDS:
                        q=row.get(name)
                        if type(q) is not dict or q.get('original_rows')!=e3_human.get('original_human_label_rows'):
                            raise ValueError('wrong original labelled case denominator')
                        for field in ('accuracy','brier'):
                            v=finite_nonnegative(q.get(field),'human task efficacy')
                            if v>1:
                                raise ValueError('invalid human task metric')
        summary_wall=p0_wall+e1_proj_wall+e1_train_wall+e1_eval_wall+e3_proj_wall+e3_train_wall
        summary_cpu=p0_cpu+e1_proj_cpu+e1_train_cpu+e1_eval_cpu+e3_proj_cpu+e3_train_cpu
        out[model]={'cost_scope':'sum_of_self_timed_observed_research_stages_not_full_lifecycle',
          'p0_whole_process_wall_ms':p0_wall,'p0_whole_process_cpu_ms':p0_cpu,
          'p0_original_process_peak_rss_bytes':int(original_rss),
          'p0_pretrained_load_wall_ms_inside_p0_not_added_twice':p0_load,
          'e1_additional_shared_projection_wall_ms':e1_proj_wall,
          'e1_fit_wall_ms':e1_train_wall,'e1_CAL_and_blind_wall_ms':e1_eval_wall,
          'e3_additional_shared_projection_wall_ms':e3_proj_wall,
          'e3_budget_head_training_wall_ms':e3_train_wall,
          'all_recorded_stages_wall_ms_sum_not_end_to_end':summary_wall,
          'all_recorded_stages_cpu_ms_sum_not_end_to_end':summary_cpu,
          'head_trainable_fp32_parameters_each':HEAD_PARAMETERS,
          'theoretical_head_weight_bytes_by_population':{str(n):int(n*HEAD_PARAMETERS*4) for n in POPULATION},
          'inference_work_to_evaluate_all_active_cells':None,
          'current_encoder_parameter_resident_bytes_verified':None,
          'actual_4096_cell_peak_rss_bytes':None,
          'calibration_and_held_e3_inference_wall_ms':None,
          'trained_4_8_12_source_budgets':budget_summary,
          'head_resource_or_model_winner_certified':False}
    return {'schema':SCHEMA,'model_costs':out,
            'source':'exact-original-P0-E1-E2-E3-recorded-stage-chain',
            'source_case_count':n_inputs,'original_human_source_groups':8,
            'selected_model':None,'complete_lifecycle_cost_matched':False,
            'actual_cell_population_host_benchmarks':False,
            'energy_or_gpu_profile_verified':False,
            'backward_and_optimizer_complete_flops_verified':False,
            'source_externally_signed':False,'final_use_authorized':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('fit','blind','e3-scored','output'):
        p.add_argument('--'+n,type=Path,required=True)
    for m in MODELS:
        for name in ('p0','e1','e2-seal','e3','e3-review'):
            p.add_argument('--'+name+'-'+m.replace('_','-'),type=Path,required=True)
    p.add_argument('--candidate-head-sha',required=True)
    p.add_argument('--candidate-run-id',type=int,required=True)
    a=p.parse_args()
    from p0_multirc_semantic_material import read,validate
    fit=read(a.fit); blind=read(a.blind)
    validate(fit,blind)
    result=observed_frontier(fit,blind,
         {m:read(getattr(a,'p0_'+m)) for m in MODELS},
         {m:read(getattr(a,'e1_'+m)) for m in MODELS},
         {m:read(getattr(a,'e2_seal_'+m)) for m in MODELS},
         {m:read(getattr(a,'e3_'+m)) for m in MODELS},
         {m:read(getattr(a,'e3_review_'+m)) for m in MODELS},
         read(a.e3_scored),candidate_sha=a.candidate_head_sha,run_id=a.candidate_run_id)
    with a.output.open('xb') as f:
        f.write(canonical(result)+b'\n')


if __name__=='__main__': main()
