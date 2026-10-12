#!/usr/bin/env python3
"""Execute the two exact mechanisms; never selects or promotes a Hepta model."""
import argparse
import hashlib
from pathlib import Path
import time

from four_gate_common import write_once, require
import fbsde_local
import fbsde_tree


def run(output, profile="exact_v1", **options):
    require(profile in ("exact_v1", "coupled_nonlinear_v1", "learned_coupled_v1", "semantic_acquisition_v1", "cpu_tail_replay_v1", "riccati_solver_v1", "continuation_workspace_v1", "verified_tracking_v1", "input_tied_challenge_v1", "novelty_calibration_v1", "verified_feedback_learning_v1", "learned_depth_allocation_v1", "outcome_depth_routing_v1"), "study profile")
    if profile == "outcome_depth_routing_v1":
        from fbsde_outcome_study import run as run_outcome
        return run_outcome(output, **options)
    if profile == "learned_depth_allocation_v1":
        from fbsde_depth_study import run as run_depth
        return run_depth(output, **options)
    if profile == "verified_feedback_learning_v1":
        from fbsde_tracking_feedback_study import run as run_feedback
        return run_feedback(output, **options)
    if profile == "novelty_calibration_v1":
        from fbsde_tracking_novelty_study import run as run_novelty
        return run_novelty(output, **options)
    if profile == "input_tied_challenge_v1":
        from fbsde_tracking_challenge_study import run as run_challenge
        return run_challenge(output)
    if profile == "verified_tracking_v1":
        from fbsde_tracking_study import run as run_tracking
        return run_tracking(output, **options)
    if profile == "continuation_workspace_v1":
        from fbsde_workspace_study import run as run_workspace
        return run_workspace(output)
    if profile == "riccati_solver_v1":
        from fbsde_riccati_study import run as run_riccati
        return run_riccati(output)
    if profile == "cpu_tail_replay_v1":
        from fbsde_cpu_replay import run as replay
        return replay(output, **options)
    if profile == "semantic_acquisition_v1":
        from fbsde_acquisition_study import run as run_acquisition
        return run_acquisition(output, **options)
    if profile == "coupled_nonlinear_v1":
        from fbsde_coupled_study import run as run_coupled
        return run_coupled(output)
    if profile == "learned_coupled_v1":
        from fbsde_coupled_learning import experiment
        return experiment(output)
    output.mkdir(parents=True,exist_ok=False)
    sources={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
             for name in ('fbsde_local.py','fbsde_tree.py','fbsde_study.py','four_gate_common.py')}
    write_once(output/'design.json',{'schema':'hepta.fbsde.exact-study.design.v1','sources':sources,
        'deterministic_mesh':[8,16,32,64,128,256,512],'segments':4,
        'stochastic_paths':128,'stochastic_finest':1024,'scenario_cases':16,
        'scope':'numerical_and_exhaustive_mechanism_checks_not_model_efficacy',
        'production_promotion_permitted':False})
    results={}
    for name,module in (('local',fbsde_local),('tree',fbsde_tree)):
        cpu,wall=time.process_time_ns(),time.perf_counter_ns()
        result=module.experiment()
        result['execution_cost']={'cpu_ns':time.process_time_ns()-cpu,'wall_ns':time.perf_counter_ns()-wall}
        write_once(output/(name+'.json'),result)
        results[name]=result
    rows=results['local']['mesh']
    require(all(r['stitched']['same_discrete_global_problem'] and
                not r['wrong_reset']['same_discrete_global_problem'] for r in rows),'pasting check')
    require(all(abs(r['whole']['initial_y']-r['stitched']['initial_y'])<1e-9 for r in rows),'monolithic check')
    require(rows[-1]['stitched']['max_trajectory_error']<rows[0]['stitched']['max_trajectory_error']/20,
            'analytic convergence check')
    require(all(r['reference']==r['root_value'] for r in results['tree']['rows']),'exhaustive policy check')
    write_once(output/'summary.json',{'exact_mechanism_checks_passed':True,
        'fbsde_global_general_theorem_proved':False,'real_encoder_experiment_executed_here':False,
        'production_promotion_permitted':False,
        'results_sha256':{n:hashlib.sha256((output/(n+'.json')).read_bytes()).hexdigest() for n in results}})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--depth-planning-engine', choices=('fresh_solve_v1','shared_continuation_v2'), default='fresh_solve_v1')
    parser.add_argument('--tracking-control-profile', choices=('all_steps_v1','learned_belief_v1','shared_head_mixture_v2'), default='all_steps_v1')
    parser.add_argument('--tracking-record-profile', choices=('retained_objects_v1','serialized_records_v2'), default='retained_objects_v1')
    parser.add_argument('--tracking-feature-profile', choices=('ordinal_sensitive_v1','local_participant_v2'), default='ordinal_sensitive_v1')
    parser.add_argument('--tracking-source', choices=('generated', 'bbh'), default='generated')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument("--profile", choices=("exact_v1", "coupled_nonlinear_v1", "learned_coupled_v1", "semantic_acquisition_v1", "cpu_tail_replay_v1", "riccati_solver_v1", "continuation_workspace_v1", "verified_tracking_v1", "input_tied_challenge_v1", "novelty_calibration_v1", "verified_feedback_learning_v1", "learned_depth_allocation_v1", "outcome_depth_routing_v1"), default="exact_v1")
    parser.add_argument("--cohort", choices=("banking_v1", "travel_guard_v1"), default="banking_v1")
    parser.add_argument("--backend", choices=("hashing_reference_v1", "mmbert"), default="hashing_reference_v1")
    parser.add_argument("--kernel-profile", choices=("uniform_joint_v1", "joint_backoff_cv_v2"), default="uniform_joint_v1")
    parser.add_argument("--publisher-root", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--replay-count", type=int, default=64)
    parser.add_argument("--clock-diagnostics", action="store_true")
    args = parser.parse_args()
    options = dict(backend=args.backend, publisher_root=args.publisher_root, model_dir=args.model_dir, kernel_profile=args.kernel_profile, cohort=args.cohort, clock_diagnostics=args.clock_diagnostics) if args.profile == "semantic_acquisition_v1" else {}
    if args.profile in ("novelty_calibration_v1", "verified_feedback_learning_v1", "learned_depth_allocation_v1", "outcome_depth_routing_v1"):
        require(args.evidence_dir is not None and args.backend == "hashing_reference_v1", "explicit frozen lexical Head source required")
        options = dict(evidence_dir=args.evidence_dir)
    if args.profile == 'learned_depth_allocation_v1':
        options['planning_engine'] = args.depth_planning_engine
    if args.profile == "cpu_tail_replay_v1":
        require(args.evidence_dir is not None, "replay evidence directory required")
        options = dict(evidence_dir=args.evidence_dir, repeats=args.replay_count, model_dir=args.model_dir)
    if args.profile == "verified_tracking_v1":
        options = dict(backend=args.backend, publisher_root=args.publisher_root,
                       model_dir=args.model_dir, tracking_source=args.tracking_source,
                       feature_profile=args.tracking_feature_profile, record_profile=args.tracking_record_profile, control_profile=args.tracking_control_profile)
    run(args.output, args.profile, **options)
