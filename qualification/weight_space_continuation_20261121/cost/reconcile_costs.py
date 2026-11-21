#!/usr/bin/env python3
"""Post-hoc arithmetic only: distinguish allocated reserve from measured spend.

This does not change the frozen study, prediction envelope or preconfirmation
choice. It performs no model import and no scientific rerun.
"""
import hashlib
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'attempt001'


def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    final=read(ROOT/'FINAL_COST_ACCOUNTING.json')
    audit=read(OUT/'INDEPENDENT_REVIEW.json')
    choice=read(OUT/'RESEARCH_CHOICE_SEALED.json')
    rows=[json.loads(x) for x in (OUT/'TIMINGS.jsonl').read_text().splitlines()]
    ref=audit['reference_confirmation_cpu_seconds']; opt=audit['specialized_confirmation_cpu_seconds']
    total=final['all_science_probe_reader_and_supervisor_cpu_seconds']
    investment=total-ref-opt
    candidate_with_qualification=investment+opt
    per_call=(ref-opt)/288
    stages={}
    for r in rows:
        if r['phase']!='confirmation': continue
        d=stages.setdefault(r['implementation'],{})
        for c in r['call_records']:
            for k,v in c['stages'].items(): d[k]=d.get(k,0.)+v['cpu_ns']/1e9
    note=dict(schema='hepta.finite-cost-posthoc-reconciliation.v1',
        scope='arithmetic decomposition of completed supervised qualification only; no changed selection or prediction',
        preconfirmation_choice=choice['decision'],general_ndu_decision='KEEP_ORIGINAL_AND_STOP',
        bound_kind='observed_finite_worklist',future_bound_claimed=False,
        confirmation_calls_per_implementation=288,reference_confirmation_cpu_seconds=ref,
        specialized_confirmation_cpu_seconds=opt,observed_execution_cpu_ratio=ref/opt,
        measured_supervised_qualification_cpu_seconds=total,
        measured_nonconfirmation_qualification_cpu_seconds=investment,
        candidate_plus_measured_qualification_cpu_seconds=candidate_with_qualification,
        measured_qualification_recovery_saved_cpu_seconds=ref-candidate_with_qualification,
        reserved_budget_qualification_cpu_seconds=choice['complete_qualification_investment_cpu_seconds'],
        reserved_budget_recovery_saved_cpu_seconds=audit['full_qualification_recovery_observed_saved_cpu_seconds'],
        label_clarification='The frozen reader field full_qualification_recovery_observed_saved_cpu_seconds includes the predeclared 3-second reserve, so it is reserved-budget accounting; the measured accounting is separately provided here.',
        observed_fixed_mixture_per_call_cpu_saving_seconds=per_call,
        observed_arithmetic_break_even_calls=investment/per_call if per_call>0 else None,
        observed_arithmetic_break_even_full_18cell_rounds=(investment/(per_call*18) if per_call>0 else None),
        break_even_limitation='Post-hoc arithmetic interpolation with already observed costs; no future guarantee, production horizon or resource-utility conversion. Frozen conservative envelope has nonpositive saving lower prediction, so its break-even remains null.',
        stage_attribution_cpu_seconds=stages,
        stage_timer_limitation='Short-stage zeros retained; grouped totals are the measured unit. Stage sums need not equal whole blocks because intervening bookkeeping is included only in block totals.',
        unmeasured_outside_supervised_scope=['protocol authoring and metadata-only preflight CPU',
            'external tool service execution cost','final receipt emission tail'],
        unknown_components_effect='These cannot turn a KEEP decision into a proven positive net value; they are not silently set to zero.',
        model_imports=0,model_calls=0,optimizer_calls=0,production_eligible=False,
        source_sha256=sha(Path(__file__)),input_sha256={name:sha(p) for name,p in {
            'final_accounting':ROOT/'FINAL_COST_ACCOUNTING.json',
            'independent_review':OUT/'INDEPENDENT_REVIEW.json',
            'choice':OUT/'RESEARCH_CHOICE_SEALED.json','timings':OUT/'TIMINGS.jsonl'}.items()},
        posthoc_arithmetic_process_cpu_seconds_at_report=time.process_time())
    with (OUT/'POSTHOC_COST_RECONCILIATION.json').open('x') as f:
        json.dump(note,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({k:note[k] for k in ('measured_nonconfirmation_qualification_cpu_seconds',
        'candidate_plus_measured_qualification_cpu_seconds','measured_qualification_recovery_saved_cpu_seconds',
        'observed_arithmetic_break_even_calls','observed_execution_cpu_ratio')},allow_nan=False))


if __name__=='__main__': main()
