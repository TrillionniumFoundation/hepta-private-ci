"""Standalone stdlib review of physical shared-Stem / Head cohort counters.

Reports are self-described source observations, NOT independent device/model
attestation or model-capability validation. Never authorizes deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat

SCHEMA = 'hepta.reader.physical-stem-packed-cell-cohort.v1'
REVIEW_SCHEMA = 'hepta.reader.physical-stem-packed-cell-review.v1'
MODES = ('repeated', 'distinct', 'two_scopes')
SIZES = (64,256,1024,4096)
NO_GO = ('is_cpu_synthetic','real_421m_model_loaded','model_quality_gain_established',
         'independent_future_task_utility','actual_4096_real_worker_executed',
         'signed_final_use_verified','full_lifecycle_cost_qualified',
         'production_authorized')


def deny_unless(ok,msg):
    if not ok:raise ValueError(msg)


def stable_digest(doc):
    return hashlib.sha256(json.dumps(doc,allow_nan=False,sort_keys=True,
          separators=(',', ':')).encode()).hexdigest()


def read_strict(path):
    p=Path(path)
    fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        before=os.fstat(fd)
        deny_unless(stat.S_ISREG(before.st_mode) and 10<=before.st_size<=100000,
                    'bounded regular report required')
        with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(100001)
        after=os.fstat(fd)
        deny_unless((before.st_ino,before.st_dev,before.st_mtime_ns,before.st_size)==
                    (after.st_ino,after.st_dev,after.st_mtime_ns,after.st_size) and
                    len(raw)==before.st_size,'report changed during read')
    finally:os.close(fd)
    def hook(pairs):
        out={}
        for key,val in pairs:
            deny_unless(key not in out,'duplicate report key')
            out[key]=val
        return out
    try:return json.loads(raw,object_pairs_hook=hook,
        parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite number')))
    except (ValueError, UnicodeError, RecursionError) as exc:raise ValueError('invalid report JSON') from exc


def review_reports(reports):
    deny_unless(isinstance(reports,dict) and set(reports)==set(MODES),
                'exact three-arm source-distribution census required')
    ref=reports['repeated']
    for mode in MODES:
        r=reports[mode]
        deny_unless(isinstance(r,dict) and r.get('schema')==SCHEMA
            and r.get('distribution')==mode
            and r.get('report_sha256')==stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
            and r.get('authority')=='DENY_ALL', 'immutable source-only report and deny authority required')
        for name in NO_GO:
            deny_unless(r.get(name) is (name=='is_cpu_synthetic'), 'false production or pretrained claim')
        n=r.get('cohort_logical_cells');k=r.get('active_cells')
        deny_unless(type(n) is int and n in SIZES and type(k) is int and k==max(8,n//10)
                    and r.get('head_per_cell_parameters')==9744
                    and r.get('head_parameters_total')==n*9744
                    and r.get('head_resident_fp32_tensor_bytes')==n*9744*4
                    and r.get('stem_frozen_parameters')==384*384+384,
                    'physical Head or Stem geometry drift')
        deny_unless(type(r.get('seed')) is int and type(r.get('training_steps')) is int
                    and 2<=r['training_steps']<=8
                    and r.get('training_examples')==k*r['training_steps']
                    and r.get('trainable_active_parameters')==k*9744
                    and type(r.get('physically_changed_active_scalars')) is int
                    and 0<r['physically_changed_active_scalars']<=k*9744
                    and r.get('dormant_weights_byte_identical') is True,
                    'fake sparse training or inactive weight preservation')
        deny_unless(r.get('physical_head_forward_rows')==(r['training_steps']+5)*k+3
                    and r.get('head_frozen_paired_forward_rows')==2*k
                    and r.get('head_sparse_training_forward_rows')==(r['training_steps']+2)*k
                    and r.get('head_trained_validation_forward_rows')==k
                    and r.get('head_unpacked_spot_rows')==3,
                    'Head work census incomplete or fabricated')
        for number in ('train_loss_initial','train_loss_final',
                       'unpacked_vs_packed_logits_max_abs',
                       'trained_unpacked_vs_packed_logits_max_abs',
                       'shared_vs_uncached_logits_max_abs'):
            deny_unless(type(r.get(number)) is float and math.isfinite(r[number]),
                         'finite physical Head evidence required')
        deny_unless(0<=r['unpacked_vs_packed_logits_max_abs']<=1e-5
                    and 0<=r['trained_unpacked_vs_packed_logits_max_abs']<=1e-5
                    and r['shared_vs_uncached_logits_max_abs']==0.,
                    'frozen Cell outputs differ from direct or cached reference')
        for label in ('baseline','shared'):
            x=r.get(label)
            deny_unless(isinstance(x,dict) and x.get('logical_borrows')==k
                       and x.get('access_hook_calls')==k
                       and type(x.get('cache_hits')) is int and x['cache_hits']>=0
                       and type(x.get('encoder_calls')) is int and x['encoder_calls']>=0
                       and x['cache_hits']+x['encoder_calls']==k
                       and type(x.get('peak_cache_tensor_bytes')) is int
                       and 0<=x['peak_cache_tensor_bytes']<=x.get('cache_budget_bytes',-1)
                       and type(x.get('encoder_and_lookup_wall_ns')) is int
                       and x['encoder_and_lookup_wall_ns']>0,
                       'unmatched physical Stem forwards, borrow checks or cache bound')
        deny_unless(r['baseline']['encoder_calls']==k
                    and r['baseline']['cache_hits']==0
                    and r['baseline']['cache_budget_bytes']==0
                    and r.get('stem_actual_physical_calls')==r['baseline']['encoder_calls']+r['shared']['encoder_calls']
                    and type(r['stem_actual_physical_calls']) is int,
                    'uncached baseline did not actually forward all active Cells')
        deny_unless(r.get('head_local_training_wall_ns',0)>0
                    and r.get('head_frozen_paired_forward_wall_ns',0)>0
                    and r.get('complete_study_wall_ns',0)>0,
                    'missing positive physical work accounting')
        deny_unless(r.get('stem_unchanged_after_learning') is True,
                    'frozen Stem must not mutate during Head SGD')
        for field in ('frozen_logits_sha256','learned_logits_sha256',
                      'stem_original_weight_sha256','active_indices_sha256',
                      'original_source_input_sha256'):
            h=r.get(field)
            deny_unless(isinstance(h,str) and len(h)==64 and all(z in '0123456789abcdef' for z in h),
                        'full logits weight lineage required')
        deny_unless(r['frozen_logits_sha256']!=r['learned_logits_sha256'],
                    'learned Head did not change physical predictions')
        for name in ('seed','cohort_logical_cells','active_cells','training_steps',
                     'head_parameters_total','head_resident_fp32_tensor_bytes',
                     'stem_original_weight_sha256','active_indices_sha256'):
            deny_unless(r[name]==ref[name], 'unequal research cohort and learning budget')
    repeated=reports['repeated']; unique=reports['distinct'];scoped=reports['two_scopes']
    budgets={r['shared']['cache_budget_bytes'] for r in reports.values()}
    deny_unless(len(budgets)==1,'unmatched cache resource ceiling across arms')
    budget=budgets.pop()
    # Every physical frozen Stem output has precisely 384 FP32 scalars.
    # Repeated sources cycle through four keys; two-scope inputs through eight.
    # A short LRU cannot retain the full cycle and genuinely offers NO saving.
    slots=budget//(384*4)
    k=repeated['active_cells']
    expected={'repeated':4 if slots>=4 else k,
              'distinct':k,
              'two_scopes':8 if slots>=8 else k}
    for mode in MODES:
        message={'repeated':'repeated evidence cache claims unphysical savings',
                 'distinct':'distinct inputs cannot achieve cached source reuse',
                 'two_scopes':'cross-principal scope isolation cannot claim reuse'}[mode]
        deny_unless(reports[mode]['shared']['encoder_calls']==expected[mode],message)
    deny_unless(repeated['original_source_input_sha256']==scoped['original_source_input_sha256']
                and repeated['original_source_input_sha256']!=unique['original_source_input_sha256']
                and repeated['frozen_logits_sha256']==scoped['frozen_logits_sha256']
                and repeated['learned_logits_sha256']==scoped['learned_logits_sha256'],
                'scope isolation changed actual numerical Cell outputs')
    return dict(schema=REVIEW_SCHEMA,cohort_logical_cells=ref['cohort_logical_cells'],
       active_cells=ref['active_cells'],source_distribution_arms=list(MODES),
       matched_cache_budget_bytes=budget,
       measured_call_counts=dict((m,reports[m]['shared']['encoder_calls']) for m in MODES),
       matched_output_scope_split=True,
       independent_hardware_attestation=False,actual_pretrained_encoder_verified=False,
       independent_future_task_quality_established=False,production_authorized=False,
       authority='DENY_ALL')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for mode in MODES:p.add_argument('--'+mode.replace('_','-'),dest=mode,required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    r=review_reports({mode:read_strict(getattr(args,mode)) for mode in MODES})
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(r,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps(r,sort_keys=True))


if __name__=='__main__':main()
