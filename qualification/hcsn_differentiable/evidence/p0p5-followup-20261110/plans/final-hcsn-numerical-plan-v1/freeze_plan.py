"""Freeze a terminal-checkpoint numerical plan without reading any live fit."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
from zipfile import ZipFile, ZIP_DEFLATED

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = BASE / 'final-hcsn-numerical-plan-v1'
SOURCE = BASE / 'v8-local-validation/source'
DATA = BASE / 'uci-cloud-prepared-v1'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
OUT.mkdir(exist_ok=False)
manifest = json.loads((DATA / 'data-manifest.json').read_bytes())
assert sha(DATA / 'data-manifest.json') == '0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb'
assert manifest['mode'] == 'all-development' and not manifest['confirmation_access']
ids = ['A01-0', 'A01-256', 'A04-3072', 'B01-0', 'C01-0', 'D01-0']
episodes, data_rows = {}, []
for eid in ids:
    entry = next(v for v in manifest['episodes'] if v['id'] == eid)
    path = DATA / entry['path']
    assert sha(path) == entry['sha256']
    row = json.loads(path.read_bytes())
    assert len(row['y']) == 256 and row['sequence'][0] in 'ABCD'
    assert row['dt'] == [v / 10000000 for v in row['delta_ticks']]
    episodes[eid] = row
    positive = [v for v in row['dt'] if v > 0]
    data_rows.append({'id': eid, 'partition': row['partition'], 'sequence': row['sequence'],
                      'events': 256, 'path_in_prepared_data': entry['path'], 'sha256': entry['sha256'],
                      'dt_minimum': min(row['dt']), 'dt_minimum_positive': min(positive),
                      'dt_maximum': max(row['dt']), 'dt_positive_median': statistics.median(positive),
                      'zero_gaps': row['dt'].count(0)})
fixed = [('A01-0', 31, 32), ('A01-0', 31, 128), ('A01-256', 127, 32),
         ('A04-3072', 47, 8), ('A04-3072', 47, 32), ('B01-0', 31, 32),
         ('C01-0', 31, 32), ('D01-0', 31, 32), ('A01-0', 0, 255)]
fixtures = []
for eid, position, count in fixed:
    gaps = episodes[eid]['dt'][position + 1:position + 1 + count]
    assert len(gaps) == count and all(0 <= v <= .2 for v in gaps)
    fixtures.append({'episode_id': eid, 'posterior_after_position': position,
                     'intervals': count, 'durations': gaps,
                     'durations_sha256': hashlib.sha256(json.dumps(gaps, separators=(',', ':')).encode()).hexdigest(),
                     'future_observations': False})
capsule = BASE / 'training-source-v8.zip'
assert sha(capsule) == '288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102'
source_names = ['qualification/hcsn_differentiable/' + name for name in
                ['operator.py', 'contract.py', 'network.py', 'encoder.py', 'value.py',
                 'regenerative.py', 'training_domain.py', 'training_domain_audit.py',
                 'training_domain_finite.py']]
source_names += ['proposals/localization-v3/' + name for name in
                 ['cores.py', 'frozen_tables.py', 'train.py', 'hcsn_study_support.py']]
plan = {
    'schema': 'terminal-trained-HCSN-bounded-numerical-plan-v1',
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'execution_status': 'planned_no_final_checkpoint_read',
    'final_model_read_during_plan_creation': False,
    'training_performed': False, 'confirmation_E_access': False,
    'scientific_admission': 'HOLD', 'whole_training_domain_admission': 'HOLD',
    'native_base': '/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training',
    'original_campaign': 'campaign-v2',
    'fit_roster': [f'hcsn-s{seed}-lr{lr:g}' for seed in [101, 211, 307] for lr in [.001, .003]],
    'source_capsule_sha256': sha(capsule), 'source_files': {n: sha(SOURCE/n) for n in source_names},
    'data_manifest_sha256': sha(DATA/'data-manifest.json'), 'fixed_episodes': data_rows,
    'eligibility': {
        'before_opening_fit_directory': 'Read terminal outer process evidence first. Do not inspect a running HCSN checkpoint or live trace.',
        'completed': 'Require terminal process, stable source/data/configuration and exact report/checkpoint hashes, complete-epoch counters and optimizer/RNG identities.',
        'softwall_or_censored': 'A genuinely terminal attempt with an intact report and stable source-bound complete-epoch checkpoint may receive a bounded trained-checkpoint numerical audit. Retain failure/censor reason, actual epoch/update count and adequacy=false unless independently established. It is not a completed/adequately trained parent.',
        'hardkill_or_missing_final_report': 'HOLD. Preserve exact exit and missing artifacts. Do not fabricate a completed parent, silently resume, or label a partial checkpoint final.',
        'stable_inputs': 'Collect two matching complete artifact inventories after terminal acknowledgement; bind original bytes, source capsule, loaded module paths, runtime versions, full wrapper model configuration and checkpoint hashes before export.'},
    'model_selection': {
        'primary': 'For every eligible one of the six declared candidates, use its first strict maximum D macro-F1 checkpoint over recorded complete epochs (best.pt), independently verify selection. No candidate is omitted because its numerical audit or memorization failed.',
        'last_checkpoint': 'Independently bind last.pt and its completed epoch/update count for every eligible candidate; export A04-3072 and audit the fixed burst8 fixture as a separately labelled final-update diagnostic.',
        'common_LR': 'Choose one LR only by mean independently recomputed D macro-F1 over all three declared seeds and both original LR rosters. If any metric/chain is unavailable, retain an incomplete selection. Numerical pass/failure never selects the LR.',
        'adequacy': 'Keep numerical fixture status, attempt completion/censoring, heuristic training adequacy, and scientific benefit as separate fields.'},
    'expected_construction': {
        'arm': 'hcsn', 'width': 16, 'learn_core_adapter': True,
        'freeze_shared': True, 'cache_frozen_tables': True,
        'grid': {'active_cells': 256, 'endpoint': 4.8, 'initial_log_std': .08,
                 'phase_cells': 16, 'quadrature_order': 32, 'refractory': .2, 'tail_rate': 1.0},
        'physics': 'Verify exact checkpoint bits and constructor-fixed/frozen requires_grad state; do not substitute the nominal values or infer qualification from constructor bounds.',
        'operator': 'Bind exact reward, reset, age and grid configuration; the independent finite oracle must receive the matching regenerative operator.'},
    'original_training_trace': {
        'read_after_terminal_only': True, 'record_budget': 4096, 'byte_budget': 33554432,
        'record_unit': '(time position, layer, microbatch) vector row with up to8 valid samples',
        'maximum_sample_position_layer_states': 32768,
        'training_events_per_epoch': 89216, 'minimum_epochs_for_bound': 30,
        'maximum_30_epoch_sample_state_coverage_fraction': 32768 / (89216 * 30),
        'selection': 'Chronological prefix, not random sampling. The byte cap may bind earlier. Actual retained/seen/dropped counts remain unknown until the true terminal footer is read.',
        'call_scope': 'Main microbatch forward before the corresponding optimizer step, update_index is completed main updates. Diagnostics and D evaluations are not captured; successful capture does not prove subsequent backward/step succeeded.',
        'limitations': ['Content state is absent.', 'model_sha256 covers only inner network tensors, not the full wrapper.', 'Interrupted partial forward is not captured.'],
        'checks': 'Verify header/footer/hash, exact plan/data/source, padding indices, all captured grid/physics ranges, counters and main update ledger. Reuse audit_trace(max_records=16) on the original retained prefix; report every evaluated batch sample and explicit missing coverage. Its incomplete/truncated status remains HOLD.'},
    'supplemental_export': {
        'primary_episodes_per_checkpoint': ids, 'primary_expected_valid_states_if_all6_eligible': 9216,
        'last_episode_per_checkpoint': 'A04-3072', 'last_expected_valid_states_if_all6_eligible': 1536,
        'batch_size': 1, 'evaluation_mode': True, 'gradients': False,
        'trace_limit_per_file_records': 512, 'trace_limit_per_file_bytes': 33554432,
        'binding': 'Use exact v8 full-wrapper forward and valid mask. A network forward hook and recorder must observe the same returned trace. Bind full wrapper/inner-network digests before and after, checkpoint, episode hash, every probability vector and full future gap list. Cache cold-start/time/bytes are recorded.',
        'scope': 'New fixed-checkpoint evaluations only. They do not reconstruct or complete original training visitation.'},
    'state_and_gradient_checks': {
        'all_exported_states': 'Check finite/nonnegative normalized probability, event/count conservation, padding exclusion, actual one-step reward agreement, phase/tail/first-cell masses and finite content/output. Save extrema with exact episode/position/checkpoint identities.',
        'reference': 'Reuse frozen training_domain_audit._reference and _basis_gradients once per exact grid/physics/reward key. Compare every basis coefficient and each exported posterior-weighted first-order physical derivative with80-digit central differences (relative parameter step1e-25). Posterior weights are held fixed; this is not an end-to-end content/likelihood gradient proof.',
        'basis_and_weighted_scaled_gradient_limit': 2e-9,
        'perpetual_pressure_sentinels': [{'episode_id': 'A01-0', 'position': 31}, {'episode_id': 'A04-3072', 'position': 48}, {'episode_id': 'A04-3072', 'position': 49}],
        'pressure_scope': 'Apply the existing constant-gap perpetual comparison only to these predeclared sampled laws. Preserve every failure separately; this artificial infinite repetition is not the real finite observation schedule.'},
    'tail_and_logrisk': {
        'inputs': 'At each distinct actual physical key use the fixed selected episodes\' minimum positive, median positive and maximum gaps. Distances are first active-cell center, exact reset distance, active endpoint and posterior-selected nonzero support cell with largest distance; retain precise query bits.',
        'reference': 'Independent80-digit reflection formula for scalar log F and log G, with mp.diff and ordinary central finite differences at representable steps. Reuse original test_logrisk formula; bind its exact source. Zero deadlines get their explicit probability0/log-risk-minus-infinity branch.',
        'log_absolute_error_limit': '3e-10 + 5e-13 * abs(reference_log_probability)',
        'scaled_first_derivative_error_limit': 3e-10,
        'report': 'Record finite log values even if probability underflows, log absolute error and probability absolute/relative errors separately. Tail-cell mass is descriptive; no blanket relative-tail-accuracy claim follows from the finite scaled gate.'},
    'finite_schedule_fixtures_per_primary_checkpoint': fixtures,
    'finite_schedule_count_if_all6_primary_eligible': 54,
    'last_checkpoint_fixture': fixtures[3],
    'finite_reference': {
        'implementation': 'Exact frozen training_domain_finite.audit_finite_schedule; no future observation updates.',
        'digits': 80, 'quadrature_orders': [8, 16],
        'quantities': ['value', 'event_count', 'discounted_event_count', 'active_probability'],
        'scaled_error': 'abs(candidate-reference)/max(1,abs(reference))',
        'scaled_error_limit': .01, 'reference_order_doubling_sensitivity_limit': 2e-8,
        'mass_residual_limit': 5e-11,
        'sensitivity_scope': 'Order doubling is measured sensitivity, not a certified reference error bound.',
        'relative_error_reporting': 'Always additionally show absolute error and relative error where reference is nonzero. Subunit reference quantities pass an absolute-error gate, not necessarily1% relative error.',
        'age_reset_multifire': 'Retain initial remaining-refractory mass, exact reset law and all actual gaps.128/255-gap cases test repeated regeneration; report actual reference count and do not call a fixture multifire unless its reference supports that claim.'},
    'resource_caps': {
        'workers': 1, 'torch_threads': 1, 'dtype': 'float64', 'device': 'CPU',
        'whole_attempt_wall_seconds': 10800, 'per_stage_wall_seconds': 900,
        'peak_RSS_limit_bytes': 2147483648, 'address_space_limit_bytes': 8589934592,
        'source_or_checkpoint_mutation': False, 'optimizer_steps': 0,
        'stop_rule': 'At a cap, preserve partial logs/checkpoints/input identities and report remaining fixtures as untested/HOLD. Do not widen tolerances, reduce the declared roster after seeing outcomes, or silently restart.',
        'cost_scope': 'Audit overhead separate from all original training/retries; record complete outer wall, waited CPU, RSS, cache construction, UTC overlap and exact dependency versions. Do not add nested timers or infer energy.'},
    'known_failures_preserved': [
        '135 prior all-basis/infinite-repeat grid pressure cases did not admit the domain.',
        'N128 finite schedule maximum count scaled error1.6404% remains failed.',
        'Earlier N256 exit137 remains incomplete with stopcause unknown; its later separate receipt is not a rewrite.',
        'Width16 two-step probe A04 positions48/49 at8e-7/1e-7 had infinite-repeat scaled errors1.4724548718/2.6152741830. Its five finite fixtures passing does not erase these failures.'
    ],
    'not_covered': ['Entire historical training domain or all ABC/D windows.',
                    'Learnable physical parameters across their constructor range or drift crossing zero.',
                    'End-to-end reference gradients through the learned observation/content update.',
                    'Unbounded schedules, all tail-relative errors, FP32/mixed precision, learned/QVI boundaries.',
                    'Scientific superiority or held-out E confirmation.'],
    'release_gate': 'Only individually complete source/model/data/configuration/log chains may receive passed_named_finite_fixtures at the declared scope. Global/whole-training/scientific statuses remain HOLD. Source-frozen execution wrapper and its meaningful binding tests are required before execution; plan creation performs no numerical audit.'
}
(OUT/'PLAN.json').write_text(json.dumps(plan, indent=2, allow_nan=False)+'\n')
(OUT/'freeze_plan.py').write_bytes(Path(__file__).read_bytes())
(OUT/'training-source-v8.zip').write_bytes(capsule.read_bytes())
for name in ['RESULT.json', 'REVIEW.md', 'MANIFEST.json', 'fact_check.py']:
    p = BASE/'v8-recorder-scope-review-v1'/name
    (OUT/('recorder-scope-'+name)).write_bytes(p.read_bytes())
print(json.dumps({'directory':str(OUT),'plan_bytes':(OUT/'PLAN.json').stat().st_size,'plan_sha256':sha(OUT/'PLAN.json'),'final_models_read':False,'finite_fixtures_per_best':len(fixtures)}))
