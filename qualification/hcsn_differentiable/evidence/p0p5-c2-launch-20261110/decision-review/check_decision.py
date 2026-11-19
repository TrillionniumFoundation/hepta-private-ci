"""Metadata-only review of the already frozen root diagnostic decision."""
import hashlib
import json
from pathlib import Path

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = Path(__file__).resolve().parent


def identity(path):
    data = Path(path).read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


path = BASE / 'c2-execution-decision-v1/DECISION.json'
decision_identity = identity(path)
assert decision_identity['sha256'] == 'bee192193f0f12599f783f348b6dea8c10b2a18df359487c3cc0c0c44d071370'
decision = json.loads(path.read_bytes())
checked = {}
for name, expected in decision['evidence_inputs'].items():
    checked[name] = identity(name)
    assert checked[name] == expected, name
assert len(checked) == 10
candidate = BASE / 'c2-execution-candidate-v4'
contract = json.loads((candidate / 'CONTRACT.json').read_bytes())
assert identity(candidate / 'CONTRACT.json')['sha256'] == decision['contract_sha256']
assert identity(candidate / 'PROGRAM-MANIFEST.json')['sha256'] == decision['program_manifest_sha256']
names = [f'hcsn-s{seed}-lr{lr}' for seed in (101, 211, 307) for lr in ('0.001', '0.003')]
assert decision['fit_names'] == contract['fit_names'] == names
assert decision['workers'] == contract['workers'] == 6
assert decision['threads_per_fit'] == contract['threads'] == 1
assert decision['cumulative_active_wall_seconds_per_fit'] == contract['cumulative_active_wall_seconds'] == 43200
assert decision['finalization_reserve_seconds_inside_cap'] == contract['finalization_reserve_seconds'] == 600
assert decision['maximum_cumulative_epochs'] == contract['maximum_epochs'] == 200
assert decision['confirmation_E_access'] is False
assert decision['scientific_admission'] == decision['whole_training_numerical_admission'] == 'HOLD'
assert all(decision[k] is False for k in ('new_seeds', 'new_learning_rates', 'new_memorization_diagnostic',
    'learnable_physics', 'source_or_architecture_changes', 'automatic_retry', 'main_merge_authorized',
    'release_publication_authorized', 'optimized_GPU_or_energy_claim'))
assert decision['parent_partial_work_refund_seconds'] == 0
terminal_path = next(n for n in checked if n.endswith('HCSN-TERMINAL-SUMMARY.json'))
terminal = json.loads(Path(terminal_path).read_bytes())
remaining = 6 * 43200 - terminal['hcsn_sum_outer_wall_seconds']
assert remaining == decision['maximum_new_summed_fit_active_wall_seconds_before_exit_overhead']
rare_path = next(n for n in checked if n.endswith('hcsn-s101-lr0.003__finite-best-2.json'))
rare = json.loads(Path(rare_path).read_bytes())['result']
index = rare['quantities'].index('event_count')
reference, projected = rare['reference'][index], rare['projected'][index]
relative = abs(projected - reference) / abs(reference)
scaled = abs(projected - reference) / max(1.0, abs(reference))
assert relative == rare['relative_errors'][index] and scaled == rare['scaled_errors'][index]
assert .041 < relative < .042 and scaled < .01 and rare['status'] == 'passed_fixture'
stdout_path = BASE / 'final-numerics-provisional-2056-v1/controller-stdout.txt'
completed_finite_lines = sum("'stage': 'finite-" in line and "'status': 'completed'" in line
                             for line in stdout_path.read_text().splitlines())
assert completed_finite_lines == 14
result = {
    'schema': 'c2-root-decision-independent-JSON-review-v1',
    'scope': 'Frozen decision, contract, existing receipts and scalar arithmetic only; no live C2 files or models read.',
    'decision_identity': decision_identity, 'verified_evidence_inputs': checked,
    'ten_input_identities_match': True, 'six_fixed_candidates_and_resources_match': True,
    'recomputed_remaining_summed_active_allowance_seconds_before_exit_overhead': remaining,
    'rare_count_reference': reference, 'rare_count_projected': projected,
    'rare_count_relative_error': relative, 'rare_count_relative_percent_error': relative * 100,
    'rare_count_scaled_error': scaled,
    'software_scope': 'v3 native 53 synthetic tests plus 6 parent validation-only children; v4 five cloud targeted tests and exact independent delta review, not a second complete native preflight.',
    'completed_finite_stdout_rows': completed_finite_lines,
    'additional_stdout_identity': identity(stdout_path),
    'open_provenance_item': 'The decision binds one finite result and the retained stdout has fourteen completed stages. Completion alone does not establish fourteen numerical passes. A separate read-only count/source appendix is required; preserve this decision and its unique launch identity.',
    'source_execution_blocker_identified': False,
    'new_execution_triggered_by_this_review': False,
    'numerical_admission': 'HOLD', 'scientific_admission': 'HOLD',
}
(OUT / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({k: v for k, v in result.items() if k != 'verified_evidence_inputs'}, indent=2))
