"""Create a final research evidence ledger without converting missing gates to passes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def read(name): return json.loads((ROOT/name).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def evidence(names):
    return [{'path':name,'sha256':sha(ROOT/name),'bytes':(ROOT/name).stat().st_size} for name in names]

def main():
    main_results=read('results/aggregate.json')
    coupled=read('coupled/results/aggregate.json')
    strict=read('audit/strict_initial_counterfactual/aggregate.json')
    main_cost=read('benchmark_results/scaling_results.json')
    coupled_cost=read('coupled/benchmark_results/scaling_results.json')
    numeric=read('full_numeric_control_results/summary.json')
    hepta=read('hepta/closure_ledger.json')
    if not read('audit/coupled_checkpoint/summary.json')['all_passed']:
        raise ValueError('Coupled recovery audit failed')
    if main_results['completed_training_runs']!=70 or len(main_results['rows'])!=14:
        raise ValueError('Incomplete main experiment')
    if not all(r['all_gradients_finite'] for r in main_results['rows']):
        raise ValueError('Nonfinite gradient receipt')
    if set(coupled['milestones'])!={'fixed_updates','equal_cpu'}:
        raise ValueError('Incomplete supplementary experiment')
    if not all(r['all_gradients_finite'] for r in coupled['milestones'].values()):
        raise ValueError('Supplementary gradient gate failed')
    if not strict['all_completed'] or not strict['same_actual_preobservation_initial_state']:
        raise ValueError('Strict counterfactual missing')
    if len(main_cost['results'])!=20 or len(coupled_cost['results'])!=4:
        raise ValueError('Incomplete resource matrix')
    if not numeric['complete'] or not numeric['all_model_checks_passed']:
        raise ValueError('Numeric implementation control incomplete')
    if main_results['anticipation_probe']['status']!='complete':
        raise ValueError('Anticipation probe incomplete')
    if any(r['status']!='complete' for r in main_results['transfer_diagnostics']):
        raise ValueError('Incomplete transfer diagnostics')
    v0=ROOT.parent/'rrsnn_experiments'
    frozen_v0=json.loads((v0/'results/source_freeze.json').read_text())
    if any(sha(v0/name)!=digest for name,digest in frozen_v0.items()):
        raise ValueError('Original v0 frozen source changed')
    for filename,field in [('experiment_plan.json','frozen_sources'),
                           ('analysis_protocol.json','scripts'),
                           ('coupled/experiment_plan.json','source_and_data_sha256'),
                           ('coupled/analysis_protocol.json','source_sha256'),
                           ('audit/strict_initial_counterfactual/protocol.json','source_sha256')]:
        for name,digest in read(filename)[field].items():
            if sha(ROOT/name)!=digest: raise ValueError('Frozen source drift: '+name)
    entries=[]
    def add(identifier,status,claim,limits,files):
        entries.append({'id':identifier,'status':status,'finding':claim,'scope_and_limits':limits,
                        'evidence':evidence(files)})
    add('R0-SCALAR','verified_in_stated_scope',
        'First-passage, killed-kernel mass, discounted hit, renewal and scalar threshold checks are retained.',
        'Constant coefficients, fixed boundary and a specified stationary scalar reset-control problem; no general multivariate analytic solution.',
        ['../rollover_snn_research/analytic_neuron.py','../rollover_snn_research/results/validation_results.json',
         'audit/full_control_qvi.txt'])
    add('R1-FINITE-OPERATOR','verified_in_stated_scope',
        'Finite-state propagation, semigroup, repeated events, reset, refractory phases, causal parameter switches and no-op timing are audited.',
        'The finite generator is a model approximation; spatial/floor/phase/remap errors against a continuous process remain measured and explicit.',
        ['density_validation_results.json','audit/results/density_operator_validation.json',
         'audit/results/sampled_policy_validation.json','audit/results/exact_adapter_validation.json'])
    add('R2-LEDGER','verified_in_stated_scope',
        'The causal memory task has consistent renewal/release/output actions and conserved budgets; independent reachable-state oracle checks pass.',
        'Shared legal-action masks enforce feasibility. Task-action budget is distinct from hidden-neuron spikes and measured hardware energy.',
        ['audit/results/evaluator_streaming_audit.json','audit/results/full_control_bellman.json'])
    add('R3-GRADIENTS','verified_in_stated_scope',
        'Both endpoint path objectives and genuine spike-feedback full-path objectives have independent gradient checks and completed finite-gradient training.',
        'Oracle-imitation expected NLL, not a proven terminal-utility policy gradient. Continuous-time event feedback occurs at observation boundaries.',
        ['audit/results/sampled_state_objective_audit.json','audit/results/path_score_gradient.json',
         'coupled/results/validation.json','coupled/results/evaluator_validation.json','coupled/results/training_summary.json'])
    primary=main_results['comparisons']['primary']['datasets']['shift']['contrasts_candidate_minus_reference']['normalized_utility']
    lo,hi=primary['paired_bootstrap_95_percentile_interval']
    status=('evaluated_candidate_inferior' if hi<0 else 'evaluated_positive_synthetic_contrast' if lo>0
            else 'evaluated_advantage_not_established')
    add('R4-PRIMARY-COMPARISON',status,
        'All70 main training runs, frozen validation selection, closed-loop test/shift/paired evaluations and paired statistics are complete.',
        'Five seeds, synthetic tasks and fixed finite replay draws. A positive result would still not establish real future or production utility.',
        ['experiment_plan.json','analysis_protocol.json','results/selection.json','results/aggregate.json'])
    add('R4-SPIKE-FEEDBACK','evaluated_supplementary',
        'Five real-spike-feedback training trajectories have both fixed-update and CPU-target checkpoints, compared to their predeclared RNN references.',
        'Ten milestones are not ten independent seeds; primary conclusions remain those of the frozen70-run matrix.',
        ['coupled/experiment_plan.json','coupled/analysis_protocol.json','coupled/results/aggregate.json'])
    add('R4-STRICT-INITIAL','verified_and_evaluated',
        'Four conditions share the exact actual preobservation neural state; marginal initialization is preserved and the separate full diagnostic is complete.',
        'Subsequent path noise is not coupled identically; condition changes can legitimately alter postobservation state.',
        ['audit/strict_initial_counterfactual/protocol.json',
         'audit/strict_initial_counterfactual/initialization_audit.json',
         'audit/strict_initial_counterfactual/aggregate.json'])
    add('R4-NUMERICAL-CONTROL','verified_in_stated_scope',
        'Numerical-root boundary plus uniformization matches analytic-root plus matrix-exponential state, decisions and expected-distribution gradients on5 checkpoints.',
        'No alternative-implementation retraining, full-path gradient replacement or general continuous-PDE equivalence claim.',
        ['full_numeric_control_results/summary.json','spiking_baselines_validation.json'])
    pressure=main_cost['pressure_or_unknown_rows']+coupled_cost['pressure_or_unknown_rows']
    add('R4-LOCAL-COST','measured_with_resource_qualifications' if pressure else 'measured_no_limit_events_in_observed_windows',
        'All20 main plus4 spike-feedback local cost rows are measured with raw timings and per-process resource sidecars.',
        f'{pressure} rows have pressure/unknown qualifiers. Policy-instance rows are not real Hepta Cells; process RSS differs from numeric state bytes.',
        ['benchmark_protocol.json','benchmark_results/scaling_results.json',
         'coupled/benchmark_protocol.json','coupled/benchmark_results/scaling_results.json'])
    add('R5-OFFLINE','verified_in_stated_scope',
        'Official type compilation, bounded Rust transport and trained-weight joint recovery are recorded in the separate Hepta ledger.',
        'Offline research evidence does not establish actual owner execution, production registration or a real target workload.',
        ['hepta/closure_ledger.json','hepta/provenance.json','hepta/complete_offline_replay.json'])
    add('R5-COUPLED-RESTORE','verified_in_stated_scope',
        'Both fixed-update and equal-CPU seed101 spike-feedback artifacts pass8 complete-state continuation recoveries and18 rejection cases.',
        'A separate Python single-owner committed-event inference adapter stores actual spike traces, context, pending score and RNG; no crash-distributed journal or official owner claim.',
        ['audit/coupled_checkpoint/summary.json','audit/coupled_checkpoint/closure_addendum.json',
         'audit/coupled_checkpoint/checkpoint.py','audit/coupled_checkpoint/independent_review.json'])
    open_hepta=[entry for entry in hepta['entries'] if entry['status'].startswith('open_')]
    result={'schema':'rrsnn.v2.final-evidence-ledger.v1','local_declared_experiments_complete':True,
            'all_blockers_closed':False,'production_activation_performed':False,
            'main_training_runs':70,'supplementary_training_trajectories':5,
            'supplementary_checkpoint_milestones':10,'formal_local_cost_rows':24,
            'main_primary_effect':primary,'main_primary_interpretation':status,
            'v0_frozen_source_unchanged':True,'all_checked_protocol_hashes_match':True,
            'entries':entries,'open_external_or_upstream_gates':open_hepta,
            'unestablished_claims':[
                'A general globally optimal closed-form neuron for arbitrary coupled resource and maturity states.',
                'A biological mechanism fit or exhaustive proof of literature novelty.',
                'Generalization to actual future Hepta outcomes, actual production Cell workloads or hardware energy.',
                'A complete CfC or LSNN reproduction; implemented comparators are explicitly specified event-held ALIF and time-basis RNN variants.'
            ],
            'decision_rule':'Report observed performance, including negative results. Missing actual runtime/data/receipts remain open; a correctly executed experiment does not turn an unsuccessful hypothesis into a passed performance gate.'}
    (ROOT/'closure_ledger.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    complete={'schema':'rrsnn.v2.complete-results.v1','evidence_ledger':result,
              'main':main_results,'spike_feedback_supplement':coupled,'strict_initial_counterfactual':strict,
              'main_resource_measurements':main_cost,'spike_feedback_resource_measurements':coupled_cost,
              'numerical_implementation_control':numeric,'hepta':hepta,
              'coupled_restore_addendum':read('audit/coupled_checkpoint/closure_addendum.json')}
    destination=ROOT.parent/'RR_SNN_V2_Complete_Results.json'
    destination.write_text(json.dumps(complete,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'ledger':str(ROOT/'closure_ledger.json'),'complete_results':str(destination),
                      'main_status':status,'open_external_or_upstream_gates':len(open_hepta),
                      'pressure_or_unknown_cost_rows':pressure},ensure_ascii=False))

if __name__=='__main__': main()
