"""Create a review draft or the single create-only local protocol freeze."""
import argparse
import datetime
from pathlib import Path
import sys

import numpy as np
import scipy

from artifact_io import identity, read, save, verify_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if list(root.glob("execution_*")):
        raise ValueError("protocol cannot be frozen after any scientific execution directory exists")
    inputs = read(root / "INPUT_MANIFEST.json")
    verify_manifest(root, inputs["files"])
    for phase in ("preparation", "semantic_checks"):
        if read(root / phase / "PROCESS_RECEIPT.json")["exit_code"] != 0:
            raise ValueError("preparation/semantic qualification must pass before freezing")
    files = {str(path.relative_to(root)): identity(path) for path in sorted(root.glob("*.py"))}
    files["INPUT_MANIFEST.json"] = identity(root / "INPUT_MANIFEST.json")
    files["PROTOCOL_PROPOSAL.json"] = identity(root / "PROTOCOL_PROPOSAL.json")
    protocol = dict(
        schema="hepta-terminal-anchored-incumbent-value-edit-v1",
        status="DRAFT_FOR_REVIEW" if args.draft else "FROZEN_BEFORE_ANY_CANDIDATE_FIT_OR_NEW_HOLDOUT",
        frozen_utc=None if args.draft else datetime.datetime.now(datetime.timezone.utc).isoformat(),
        local_freeze_is_not_external_preregistration=True,
        fits=[11, 23, 37, 53, 71],
        source_files=files,
        source_environment=dict(python=sys.version, numpy=np.__version__, scipy=scipy.__version__),
        purpose="Test whether terminal-anchored one-step incumbent advantages and own occupancy weighting produce a useful pure continuation-head direction, selected only by complete own-law TRAIN utility.",
        prior_work_not_repeated="The old 125-point three-bias grid and old full-optimal-Q uniform MSE compilation are known failures; this is one fixed new hypothesis, not a search over more post-holdout hypotheses.",
        information_boundary=dict(
            inputs="All original 64 TRAIN public schedules per fit and exact stored checkpoint transition/emission tables; input package excludes original Q/posterior/label/VAL rows.",
            teacher="Q_C(s,a): immediate task reward/fee followed by fixed C under checkpoint own law, with all finite transitions integrated.",
            terminal_anchor="a_T is first argmax of unchanged C STOP/SUBMIT scores. Y_a=T_pred(a_T)+Q_C(s,a)-T_own(a_T). All three terminal actions are always legal in the pinned task.",
            candidate_interface_has_no_truth_law_member=True,
            truth_asset_loaded_by_pinned_definition_loader_before_fit=True,
            truth_scores_used_for_candidate_targets_or_selection=False,
            interface_isolation_is_not_a_security_sandbox_claim=True,
            evaluator="Independent pinned environment transition tables and original fitted confusion; truth used only after all candidates freeze.",
            law_authority="Exact supplied model tables; no idealized regeneration from nominal physics."),
        training=dict(worlds_per_fit=64, all_original_worlds_required=True,
            state_identity="Canonical full original state including sunk charges, observation history, pending I/O, elapsed time and budgets.",
            state_order="Pinned deterministic DFS insertion order; topology is stable tick sort; every continuation advances exactly one tick.",
            reference="Each TRAIN C value must match the old recursive checked-head executor exactly; candidate score traversal uses actual stored F64 head argmax decisions.",
            endpoint_representation="Frozen 85 input to tanh48 hidden features plus bias; only first three rows of the 4x49 augmented head can change.",
            policy_execution="Pinned checked-head replay: original explicit F64 reduction of augmented [hidden,1] features; this is not an F32/native production qualification.",
            mixed_weight="Per world, 0.9 incumbent-own-law occupancy normalized over continuation-eligible states plus 0.1 uniform over all eligible full states; divide equally over legal continuation actions and over 64 worlds.",
            uniform_control="Same eligible-state/legal-continuation normalization with occupancy mixture zero.",
            teacher_opportunity_diagnostic="TRAIN-only exact anchored-policy rollout recorded as a diagnostic; it is not a new held-out arm or a weight edit."),
        optimization=dict(editable_parameters=147, protected_belief_parameters=49,
            occupancy_mixture=.9, lambda_value=1e-4,
            declared_radius="L2 change <=0.5||C_Q||; solver radius uses inward factor (1-1e-8); exact rational checks on actually stored IEEE F64 differences.",
            direct="Existing spectral secular trust-region solver with independent Cholesky/KKT diagnostics; no gradient steps.",
            gradient="Same quadratic as E, same data/start/radius; projected gradient at 1/L, own Frank-Wolfe gap <=1e-8, maximum100000 steps; no access to direct optimum for stopping.",
            numerical_diagnostics_are_not_outward_error_optimality_proofs=True,
            alphas=[0., .25, .5, .75, 1.],
            path_arms=["E", "G", "EU", "EA"],
            selection="Every path arm separately picks the first exact maximum of mean complete own-law TRAIN utility among its five stored-F64 heads; ascending alpha means ties pick smallest alpha. No tolerance-based tie adaptation.",
            zero_edit_in_every_fitted_path=True,
            stored_path_definition="stored_point(C_Q,alpha*(endpoint_Q-C_Q),same safe radius); actual serialized head, norm and reconstructed full-model identity retained before scoring.",
            random="One PCG64 seed from [protocol_sha,fit,'single-final-E-norm-matched-random']; random delta norm matches final selected and serialized E. If E is zero, R is C. No random search or alpha selection.",
            random_norm_relative_tolerance=1e-10,
            fresh_base_training=False, gradient_baseline_optimization=True,
            full_traditional_retraining_comparison=False),
        arms=dict(C="Exact previous continuation incumbent; strong no-edit model baseline",
            E="Anchored one-step targets, occupancy mixture, direct solve, five-alpha own-value selection; primary weight arm",
            G="Same as E with matched quadratic PGD and identical five-alpha selection",
            EU="Anchored one-step targets, uniform full support, direct solve and identical five-alpha selection",
            EA="Unanchored raw one-step Q_C targets, occupancy mixture, direct solve and identical five-alpha selection",
            M="Exact previously frozen DQ old full-optimal-Q MSE model; no new fitting/selection",
            R="Single random edit norm-matched to final E",
            P="No weight edit: C continuation plus own analytic terminal posterior; program control",
            J="No weight edit: full checkpoint-own-law Bellman program; planning control",
            E_gated="E if the fixed new validation gate accepts, else exact complete C",
            G_gated="G if the same fixed gate accepts, else exact complete C"),
        holdout=dict(validation_per_fit_domain=16, test_per_fit_domain=32, domains=["iid", "ood"],
            minimum_validation_mean_gain=.005,
            gate="Per fit E/G endpoint solver must converge, neither domain may lose versus C, equal-domain mean gain >=.005. EU/EA/M/R/P/J remain secondary frozen controls without validation tuning.",
            failed_gate="Reject and serialize full C; require canonical model SHA and complete deterministic gzip file bytes to match C. Accepted candidates have restoration=null/not applicable.",
            ordering=["source/protocol freeze", "all 5 fits, all 100 path heads, all TRAIN selection and raw models frozen", "generate/score complete new validation", "freeze every gate/model", "generate/score complete new TEST"],
            generator="PCG64 full SHA256 integer from canonical [protocol_sha,fit,split,domain,'public-schedule']; original public domains and six-tick schedule sampling order.",
            exclusion="Exact schedule-content comparison against all2416 available same-task historical unique schedules and all new schedules; collision stops entire run, no replacement.",
            unknown_history="Unseen external trials and unavailable original formal-confirmation content are not excluded by a known-content hash registry.",
            OOD_scope="OOD is relative to original TRAIN; new validation exposes that distribution, TEST is new instances of that exposed domain.",
            repeated_holdout_adaptation_allowed=False),
        inference=dict(primary_contrasts=["E_gated-C IID", "E_gated-C OOD"],
            primary_family_size=2, reused_training_fit_count=5, new_training_fit_count=0,
            interval="Paired Student-t df4 across five old fit means, two-sided Bonferroni-two familywise alpha.05; conditional model-assumption interval for this fixed training family, not distribution-free or new-fit replication.",
            minimum_lower_bound_gain=.005,
            qualification="All E source/norm/numerical gates and both primary lower bounds strictly >.005. Record G/EU/EA numerical failures separately; they do not become qualified candidates.",
            no_world_pseudoreplication=True,
            controls_and_ablations="All raw/gated arms and behavior/error metrics retained; other95% intervals descriptive only, no additional confirmatory claim.",
            not_a_new_Hepta_two_by_two_D_minus_B_factorial=True),
        state_caps=dict(full_per_world=20000, markov_per_world=20000, training_rows_per_fit=200000),
        resource_caps=dict(worker_cpu_seconds=1200, worker_wall_seconds=1800,
            controller_wall_seconds=1830, numeric_threads=1, peak_rss_target_bytes=1073741824,
            RSS_scope="Measured peak RSS checked at budget points, not a hard virtual address limit.",
            verification_cpu_seconds=900, verification_wall_seconds=1200,
            failure="Stop and preserve all partial files/costs; do not reduce fits/worlds, tune another candidate or rerun changed scientific source under this protocol."),
        reporting=dict(full_worker_process_receipts=True,
            costs="Input preparation, semantic checks, all shared graph/feature/own-target work, all solver and finite path candidates, serialization, controls, validation, TEST and independent verification measured separately. J includes own planning/verification/serialization/load; feature caches are cold separately for each held-out arm.",
            controller_cost_limit="Receipt controller CPU covers main body only, after imports and before final receipt write. That missing overhead, agent/editor cost, unknown earlier trials and base-model training are not recoverable full costs.",
            no_energy_or_dollar_inference=True,
            no_free_oracle_or_free_program_baseline_claim=True,
            utility="Original finite task includes requested-read, repair and simulated elapsed fees. Actual CPU has no measured economic conversion; full NDU economic net gain is not qualified.",
            compute_comparison="Direct versus PGD is only the matched147-parameter fixed-feature quadratic and finite path; report shared preprocessing and whole experiment separately, no complete-training speedup claim.",
            failures_retained=True),
        independent_verification=dict(source="verify_records.py; it does not import task_graph.py or run_experiment.py",
            stored_records="Model preservation, rational norm membership, finite path identity, selection, seeds/content exclusion, local event order, exact failed-gate rollback and closed-form-df4 interval recomputation.",
            train_replay="Every6400 TRAIN world/path pair through the old pinned recursive executor; require exact float utility equality, not the new DAG code.",
            holdout_replay="All4960 held-out world/arm pairs through a separate literal-head, recursive eight-behavior evaluator; require node count equality and absolute metric difference <=2e-13; shared original core/law source explicitly retained.",
            local_event_chain_not_external_timestamp_proof=True),
        scope_limits=["Finite fixed-deadline sign task only; not first-passage or financial Call/Put repair",
            "No live Trader or private market data and no remote training",
            "No full-network continuous global-optimality claim; only selection from fixed finite directions",
            "No weight gain attribution to P/J program changes",
            "No result-driven extra candidate round; defects/results remain visible",
            "PGD is gradient optimization, but this is not comparison with complete base retraining"])
    digest = save(args.output, protocol)
    print(__import__("json").dumps(dict(path=str(args.output), status=protocol["status"], sha256=digest), sort_keys=True))


if __name__ == "__main__":
    main()
