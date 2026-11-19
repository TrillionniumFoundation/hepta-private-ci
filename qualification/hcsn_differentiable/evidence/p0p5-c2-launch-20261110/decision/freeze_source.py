"""Freeze a bounded diagnostic continuation decision against completed evidence."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path('/workspace/scratch/c385a7439f8e')
OUT = ROOT / 'c2-execution-decision-v1'


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    OUT.mkdir(exist_ok=False)
    candidate = ROOT / 'c2-execution-candidate-v4'
    contract_path = candidate / 'CONTRACT.json'
    manifest_path = candidate / 'PROGRAM-MANIFEST.json'
    contract = json.loads(contract_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    assert identity(manifest_path)['sha256'] == '322eb8f76cce589ba44ed66eff822f7b497e6507106a1ad56a65bdc8c83f7f57'
    assert identity(contract_path)['sha256'] == 'bc814b8913f5d5777f771030623bcd1f862a526f35144a8da0164e1da60f8e51'
    for name, value in manifest['files'].items():
        assert identity(candidate / name) == value
    native = ROOT / 'c2-native-preflight-recovered-v1/RESULT.json'
    preflight = json.loads(native.read_text())
    assert identity(native)['sha256'] == '61552a97bfffb9e35ac7c7068c411231089cb175b3f36d303f09fca0a51548d7'
    assert preflight['status'] == 'passed_native_preflight_only' and preflight['source_unchanged'] is True
    assert preflight['real_training_optimizer_steps'] == 0
    review_path = ROOT / 'c2-v4-budget-reporting-independent-review-v1/RESULT.json'
    review = json.loads(review_path.read_text())
    assert identity(review_path)['sha256'] == '39e52f422138b2012d4a670f0fcb193819073db0caaf3c1a117b6896dc570028'
    assert review['source_blocker_identified_in_reporting_delta'] is False
    assert review['runner_AST_equal_after_stripping_only_reporting_fields'] is True
    paths = [native, review_path,
        ROOT / 'c2-execution-validation-attempt-05/RESULT.json',
        ROOT / 'c2-execution-validation-attempt-05/TESTED-SOURCE.zip',
        ROOT / 'c2-execution-independent-review-v1/RESULT.json',
        ROOT / 'six-logrisk-query-confirmation-v1/RESULT.json',
        ROOT / 'logrisk-json-independent-review-v1/RESULT.json',
        ROOT / 'final-numerics-provisional-2056-v1/hcsn-s101-lr0.003__finite-best-2.json',
        ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/STATUS.json',
        ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-followup-20261110/original42/receipts-v1/HCSN-TERMINAL-SUMMARY.json']
    evidence = {str(path): identity(path) for path in paths}
    decision = {'schema': 'hcsn-c2-root-diagnostic-execution-decision-v1',
        'decided_utc': datetime.now(timezone.utc).isoformat(),
        'execution_authorized': True, 'scope': 'six-original-hcsn-c2-only',
        'authority': 'User authorized full P0-P5 work and the existing bounded native-host research workflow; this is a concrete execution decision within that request.',
        'contract_sha256': identity(contract_path)['sha256'],
        'program_manifest_sha256': identity(manifest_path)['sha256'],
        'program_capsule_sha256': identity(ROOT / 'c2-execution-validation-attempt-05/TESTED-SOURCE.zip')['sha256'],
        'candidate': 'reporting-only-v4', 'source_model_and_data': 'Unchanged original v8 source, six original HCSN parents and manifest bound in CONTRACT.json.',
        'fit_names': contract['fit_names'], 'confirmation_E_access': False,
        'new_seeds': False, 'new_learning_rates': False, 'new_memorization_diagnostic': False,
        'learnable_physics': False, 'source_or_architecture_changes': False,
        'workers': 6, 'threads_per_fit': 1, 'maximum_cumulative_epochs': 200,
        'cumulative_active_wall_seconds_per_fit': 43200,
        'maximum_new_summed_fit_active_wall_seconds_before_exit_overhead': 172938.8845898183,
        'budget_scope': 'Original complete outer wall is charged before new work. Prelaunch, imports, discarded-partial replay, all recording, evaluation and finalization consume the same remaining fit allowance. Actual polling/exit overhead is measured and not hidden.',
        'finalization_reserve_seconds_inside_cap': 600,
        'finalization_reserve_scope': 'Training stops early at the reserve; this is not a guarantee that two terminal capture slots, full-D evaluation and I/O finish. Each capture slot shares one 120-second soft timer across three episodes. Finalization failure, recording_hold or timeout cannot grant adequacy.',
        'address_space_bytes_per_fit': 8589934592, 'RSS_stop_bytes_per_fit': 6442450944,
        'parent_partial_work_refund_seconds': 0, 'resume_only_last_complete_epoch': True,
        'before_first_step_full_state_witness_required': True,
        'supplemental_checkpoint_policy_sha256': contract['supplement_policy_sha256'],
        'actual_optimization_visit_policy_sha256': contract['optimization_policy_sha256'],
        'actual_optimization_trace_scope': 'Prospectively selected first actual microbatches after resume and declared epoch milestones; sparse empirical visits, not whole-trajectory coverage.',
        'same_budget_comparison': 'Original 300/900/1800-second results are unchanged. C2 is a separately labeled longer-resource/calendar phase, not retroactive original-protocol completion.',
        'stopping': 'Inherited min30/patience10/delta.002, maximum200 complete epochs and cumulative wall cap. Strict-best selection remains separate from plateau adequacy.',
        'reason_to_continue': 'All six original diagnostics passed and all six fits stopped on resource limits before declared adequacy. All six strict-best full-D predictions reproduced independently. A bounded all-candidate extension is needed to assess whether inadequate optimization explains the remaining development-quality gap.',
        'software_evidence_scope': 'v3: 53 native synthetic tests and six actual parent bind-only checks. v4: five cloud targeted tests including a tiny complete-state resume, plus independent exact AST/source-delta review. v4 is not claimed to have a second full native preflight.',
        'numerical_evidence_scope': 'The separate frozen terminal audit is still running. Its observed first14 finite fixtures passed the original scaled-error criterion; this is not completion or domain qualification. The bound rare-count example has about4.14 percent relative count error despite passing the scaled gate.',
        'gradient_evidence_scope': 'The retained log-risk ordinary-FP64-FD confirmation gate remains failed/inconclusive. At the one above-resolution disagreement, AD, 80-digit derivative and high-precision FD agree; discount is fixed in this experiment. This does not grant a full training-gradient qualification.',
        'known_numeric_limits': ['Original traces retain only update0, no post-update states.',
            'Repeated-tiny-gap perpetual-pressure cases fail and remain failures.',
            'Scaled finite errors do not certify relative rare-event/count precision.',
            'Learnable drift/noise/boundary/reset domains and entire training trajectory remain unqualified.'],
        'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD',
        'optimized_GPU_or_energy_claim': False, 'P5_benefit_gate': 'unchanged',
        'automatic_retry': False, 'unique_launch_key': 'hcsn-c2-native-execution-c385-v1',
        'unknown_launch_rule': 'Reconcile the same launch identity; never create a second independent execution after an unknown acknowledgement.',
        'terminal_acceptance': 'Collect every attempted fit, including failed, truncated, missing and hard-timeout outcomes; verify immutable source/parent chains, full-state witness, complete-epoch commits, costs and fresh logits independently before any further claim.',
        'release_publication_authorized': False, 'main_merge_authorized': False,
        'evidence_inputs': evidence}
    with (OUT / 'DECISION.json').open('x') as stream:
        json.dump(decision, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    (OUT / 'freeze_source.py').write_bytes(Path(__file__).read_bytes())
    files = {p.name: identity(p) for p in sorted(OUT.iterdir())}
    with (OUT / 'MANIFEST.json').open('x') as stream:
        json.dump({'files': files, 'scope': 'Frozen decision before any real C2 execution; not a successful execution receipt.'}, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'decision': identity(OUT / 'DECISION.json'), 'manifest': identity(OUT / 'MANIFEST.json')}))


if __name__ == '__main__':
    main()
