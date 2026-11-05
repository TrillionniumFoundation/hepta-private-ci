"""Read-only source/result attribution checks for the exact frozen package."""
from pathlib import Path
import datetime
import hashlib
import json
import re

ROOT = Path('/workspace/scratch/0c901b844a27')
OUT = Path(__file__).resolve().parent
A = ROOT / 'integration/sealed-qualification'
E = 'eed6541df0add428add8e2d9ab2cbd54a961abeb'
ET = 'b8ce8b96a759f522cb7db60027d4844f1b3ad974'
S = '0766fc4d5feabea9569d48e7eca4e0a3431bd0f5'
ST = '1cfb78c47f636a60dcfa9968ffd7e44a054d58cc'
F = '432421d0d9ca9d82c5e3401fe3425af29131505a'
FT = 'd93136bb5e318ea4131bfb5cb0b9ac9310f27d1d'
RUNNER = '46552f047784d07b825cec59e0358cfbb02a010f448b7538bb0fadc15ea2f7df'
PLAN = '00b4d289a635ae36865dc70732a1a10a03a8fb81575be5b5eba0b21fce7027fe'
LOCK = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
PATH = 'codex-rs/hepta-intelligence/src/plasticity_product_tests.rs'
PIN = 'a9efffacf0409231767b81ee7a86633e9a0037d508d4db9ed7720ab2c71e11e8'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def read(rel):
    return (A / rel).read_bytes()


def js(rel):
    return json.loads(read(rel))


def keyed(rows):
    result = {row['path']: row for row in rows}
    assert len(result) == len(rows)
    return result


def equal_rows(rows, expected):
    actual = keyed(rows)
    assert set(actual) == set(expected)
    for path in expected:
        assert actual[path]['sha256'] == expected[path]['sha256']
        assert actual[path]['git_blob'] == expected[path]['git_blob']


def step(receipt, name):
    values = [entry for entry in receipt['steps'] if entry['name'] == name]
    assert len(values) == 1, name
    return values[0]


def verify_log(receipt, step_name, stderr_path, stdout_path):
    entry = step(receipt, step_name)
    stderr = read(stderr_path)
    stdout = read(stdout_path)
    assert sha(stderr) == entry['stderr_sha256']
    assert sha(stdout) == entry['stdout_sha256']
    return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', stderr.decode()), entry


def verify_native_identity(receipt, expected):
    assert receipt['execution_head'] == E and receipt['execution_tree'] == ET
    assert receipt['plan_execution_head'] == E
    assert receipt['native_runner_sha256'] == RUNNER and receipt['plan_sha256'] == PLAN
    assert receipt['cargo_lock_sha256'] == LOCK
    assert receipt['historical_813_passes_apply_only_to_tested_facba'] is True
    assert receipt['first_wave_current_head'] == F
    assert receipt['first_wave_tested_head'] == 'facba0d32c1cd0e8163a6186d7ba91fa311f2e2e'
    equal_rows(receipt['source_expected'], expected)
    equal_rows(receipt['source_before'], expected)


assert sha((ROOT / 'integration/final-second-evidence-payload.json').read_bytes()) == PIN
validation = js('validation.json')
current = js('native-source-manifest.json')
before = js('native/source-manifest-before-scoped-fix.json')
before_bytes = (ROOT / 'adaptive/evidence-audit/second-preflight/snapshot/native-source-manifest.json').read_bytes()
assert read('native/source-manifest-before-scoped-fix.json') == before_bytes
assert validation['source_head'] == current['implementation_commit'] == S
assert validation['source_tree'] == current['implementation_tree'] == ST
assert validation['tested_source_head'] == current['tested_implementation_commit'] == E
assert validation['tested_source_tree'] == current['tested_implementation_tree'] == ET
assert current['merge_parents'] == validation['current_merge_parents'] == [E]
assert current['tested_source_merge_parents'] == [
    'e0b522cd437af1362f8be23f601886b46ec1b063', F]
expected_e = keyed(before['verified_ingress_source_files'])
expected_s = keyed(current['verified_ingress_source_files'])
assert len(expected_e) == len(expected_s) == 14
assert sorted(path for path in expected_e if expected_e[path] != expected_s[path]) == [PATH]
equal_rows(js('native-round2-gate-v2/final-positive-manifest.json')['files'], expected_e)

old_test = (ROOT / 'lifecycle/native-next-trust-formatted' / PATH).read_bytes()
new_test = read('native/scoped-fix/plasticity_product_tests.after.rs')
assert sha(old_test) == expected_e[PATH]['sha256'] and blob(old_test) == expected_e[PATH]['git_blob']
assert sha(new_test) == expected_s[PATH]['sha256'] and blob(new_test) == expected_s[PATH]['git_blob']
assert len(new_test) == expected_s[PATH]['bytes'] == len(old_test) - 8
assert old_test.count(b'candidate_id: update_id.clone(),') == 1
assert old_test.replace(b'candidate_id: update_id.clone(),', b'candidate_id: update_id,', 1) == new_test

alignment = js('native/ai395-second-postfix-alignment-receipt.json')
assert sha(read('native/ai395-second-postfix-alignment-receipt.json')) == '72f596be257474eba63334968754a602d814ad0d18664941e003979f576812f5'
assert alignment['state'] == 'reviewed-postfix-exact-source-aligned' and alignment['exit_code'] == 0
assert alignment['tested_head'] == E and alignment['tested_tree'] == ET
assert alignment['reviewed_postfix_head'] == S and alignment['reviewed_postfix_tree'] == ST
assert alignment['ordered_parents'] == [E]
assert alignment['only_committed_delta'] == [PATH]
for key in ['clean', 'working_bytes_unchanged_by_alignment', 'original_receipts_preserved',
            'first_source_unchanged_clean', 'historical_805_passes_apply_only_to_tested_E']:
    assert alignment[key] is True
assert alignment['tests_rerun_after_fix'] is False and alignment['fix_rerun'] is False
assert alignment['cargo_lock_sha256'] == LOCK
assert alignment['script_sha256'] == sha(read('native/align_second_reviewed_fix.py'))
assert all(entry['exit_code'] == 0 for entry in alignment['steps'])
equal_rows(alignment['reviewed_bytes_before_alignment'], expected_s)
equal_rows(alignment['reviewed_bytes_after_alignment'], expected_s)
assert step(alignment, 'new-identity')['stdout_sha256'] == sha((S + '\n' + ST + '\n').encode())
assert step(alignment, 'old-identity')['stdout_sha256'] == sha((E + '\n' + ET + '\n').encode())
assert step(alignment, 'first-identity-after')['stdout_sha256'] == sha((F + '\n' + FT + '\n').encode())
assert step(alignment, 'full-stack-format-check-only')['argv'] == [
    'just', 'fmt', '--base', '4e31abc907f09740d402d1ddef7a1d2fe0a366a6', '--check']
for name in ['clean-after-alignment', 'final-clean', 'first-clean-after']:
    assert step(alignment, name)['stdout_sha256'] == sha(b'')

inventory_raw = read('native/ai395-second-postfix-verified-rust-blobs.json')
assert sha(inventory_raw) == '71b5fd4cf0616d79a10503798ef86ce5391c6c7aa8d3dfff76f1b522af4460b2'
assert len(inventory_raw) == alignment['rust_inventory']['size'] == 1255601
inventory = keyed(json.loads(inventory_raw))
assert len(inventory) == alignment['rust_inventory']['count'] == 5314
for path, entry in inventory.items():
    assert path.endswith('.rs') and not path.startswith('/') and '..' not in Path(path).parts
    assert re.fullmatch('[0-9a-f]{40}', entry['git_blob'])
    assert re.fullmatch('[0-9a-f]{64}', entry['sha256'])
for path, entry in expected_s.items():
    assert inventory[path]['git_blob'] == entry['git_blob']
    assert inventory[path]['sha256'] == entry['sha256']
assert current['current_all_tracked_rust_bytes_derived_from_verified_one_file_delta'] == 80662751 - 8

all_artifacts = {}
for folder, prefix in [(A, 'qualification/sealed-ingress-20261105/'),
                       (ROOT / 'integration/qualification', 'qualification/runtime-convergence-20261105/')]:
    for file in folder.rglob('*'):
        if file.is_file():
            all_artifacts.setdefault(sha(file.read_bytes()), []).append(prefix + str(file.relative_to(folder)))
originals = []
assert len(alignment['original_receipts']) == 11
for remote_path, digest in alignment['original_receipts'].items():
    assert digest in all_artifacts
    originals.append({'original_path': remote_path, 'sha256': digest,
                      'exact_archived_originals': all_artifacts[digest]})

plan = js('native-round2-gate-v2/plan.json')
assert sha(read('native-round2-gate-v2/plan.json')) == PLAN
assert sha(read('native-round2-gate-v2/run_native_round2.py')) == RUNNER
controls = {entry['phase']: entry for entry in plan['controls']}
expected_counts = {'Q1': (4, 867), 'Q2': (1, 663), 'Q3': (1, 84), 'Q4': (1, 121)}
panics = {
    'Q1': ['product_runner_tests.rs:581:5', 'intelligence_evaluation_tests.rs:428:5',
           'plasticity_product_tests.rs:668:5', 'self_evolution_ingress_tests.rs:405:5'],
    'Q2': ['intelligence_evaluation_tests.rs:460:5'],
    'Q3': ['plasticity_product_tests.rs:713:5'],
    'Q4': ['self_evolution_ingress_tests.rs:474:5']}
negative_results = []
negative_digests = []
for label in ['Q1', 'Q2', 'Q3', 'Q4']:
    item = validation['native_results'][label]
    assert sha(read(item['receipt'])) == item['sha256']
    receipt = js(item['receipt'])
    verify_native_identity(receipt, expected_e)
    control = controls[receipt['phase']]
    assert receipt['test_exit_code'] == 100 and receipt['exit_code'] == 0
    assert receipt['state'] == 'named-test-failures-observed-review-required'
    assert receipt['negative_patch_sha256'] == control['patch_sha256']
    assert receipt['expected_mutated_blob'] == control['mutated_production_git_blob']
    for folder in ['negative-controls/', 'native-round2/negative-controls/',
                   'native-round2-gate-v2/negative-controls/']:
        assert sha(read(folder + control['patch_name'])) == control['patch_sha256']
    stem = item['receipt'].removesuffix('-receipt.json')
    assert sha(read(stem + '-negative.patch')) == control['patch_sha256']
    text, command = verify_log(receipt, 'just-test', stem + '-just-test.stderr', stem + '-just-test.stdout')
    assert command['argv'] == control['command'] and command['exit_code'] == 100
    assert 'Finished `test` profile' in text and 'nextest profile: local' in text
    run_count, skipped = expected_counts[label]
    assert re.search(rf'{run_count} tests? run: 0 passed, {run_count} failed, {skipped} skipped', text)
    observed = receipt['failure_observation']
    assert observed == item['observed']
    assert set(observed['observed_named_failures']) == set(control['required_named_failures'])
    assert len(observed['final_failure_lines']) == run_count
    assert all(line in text for line in observed['final_failure_lines'])
    for panic in panics[label]:
        assert text.count('panicked at ') >= 2
        assert text.count('panicked at ' + 'hepta') >= 2
        assert text.count(panic + ':') == 2
    if label == 'Q1':
        assert text.count('reissued current trust must not rebind a published qualification') == 2
    assert receipt['restored_candidate'] is True
    equal_rows(receipt['restored_positive'], expected_e)
    assert step(receipt, 'clean-after')['stdout_sha256'] == sha(b'')
    assert step(receipt, 'head-after')['stdout_sha256'] == sha((E + '\n').encode())
    assert step(receipt, 'tree-after')['stdout_sha256'] == sha((ET + '\n').encode())
    assert sha(read(item['independent_behavior_review'])) == item['independent_behavior_review_sha256']
    negative_digests.append(item['sha256'])
    negative_results.append({'control': label, 'attempt': receipt['attempt'], 'receipt_sha256': item['sha256'],
                             'patch_sha256': control['patch_sha256'], 'source_head': E,
                             'test_exit': 100, 'wrapper_exit': 0, 'run_count': run_count,
                             'failed': run_count, 'skipped': skipped, 'first_panic_locations': panics[label],
                             'attempts_per_case_inherited_retry': 2, 'all_fourteen_restored': True,
                             'original_command_exactly_matches_frozen_plan': True})

failed = js('native/ai395-sealed-q3-attempt1-receipt.json')
verify_native_identity(failed, expected_e)
assert failed['test_exit_code'] == 101 and failed['exit_code'] == 1
assert failed['state'] == 'negative-control-did-not-prove-required-test-failures'
equal_rows(failed['restored_positive'], expected_e)
failed_text, _ = verify_log(failed, 'just-test', 'native/ai395-sealed-q3-attempt1-just-test.stderr',
                            'native/ai395-sealed-q3-attempt1-just-test.stdout')
assert 'error[E0432]' in failed_text and 'Summary [' not in failed_text
assert failed['restored_candidate'] is True

repair = js('native/ai395-eval-cache-repair-attempt2-receipt.json')
assert repair['head'] == E and repair['tree'] == ET
assert repair['state'] == 'cache-repair-complete' and repair['exit_code'] == 0
assert repair['source_features_profiles_budgets_changed'] is False
assert repair['tests_executed_by_repair'] is False and repair['original_evidence_preserved'] is True
clean_text, clean_command = verify_log(repair, 'clean-eval-package',
    'native/ai395-eval-cache-repair-attempt2-clean-eval-package.stderr',
    'native/ai395-eval-cache-repair-attempt2-clean-eval-package.stdout')
assert clean_command['argv'] == ['cargo', 'clean', '-p', 'codex-hepta-intelligence-eval']
assert clean_command['exit_code'] == 0
guard_stop = js('native/ai395-eval-cache-repair-attempt1-receipt.json')
assert guard_stop['state'] == 'cache-repair-blocked' and guard_stop['exit_code'] == 1
assert not any(entry['name'] == 'clean-eval-package' for entry in guard_stop['steps'])

green = js('native/ai395-sealed-green-receipt.json')
verify_native_identity(green, expected_e)
green_text, green_command = verify_log(green, 'just-green',
    'native/ai395-sealed-green-just-green.stderr', 'native/ai395-sealed-green-just-green.stdout')
assert green_command['argv'] == plan['commands']['positive_full']
assert green['state'] == 'green-complete' and green['exit_code'] == green_command['exit_code'] == 0
passes = re.findall(r'^\s*PASS\s+\[[^\]]+\].*$', green_text, flags=re.M)
assert len(passes) == 805
assert not re.search(r'^\s*(?:TRY\s+\d+\s+)?(?:FAIL|RETRY)\b', green_text, flags=re.M)
assert '805 tests run: 805 passed (1 slow), 66 skipped' in green_text
assert 'nextest profile: local' in green_text
critical = sorted({name for entry in plan['controls'] for name in entry['required_named_failures']})
assert len(critical) == 7
critical_passes = {}
for name in critical:
    matches = [line for line in passes if line.rstrip().endswith('::' + name)]
    assert len(matches) == 1
    critical_passes[name] = matches[0].strip()
assert set(entry['sha256'] for entry in green['prior_phases']) == set(negative_digests)
assert step(green, 'clean-after')['stdout_sha256'] == sha(b'')

fix = js('native/ai395-sealed-fix-receipt.json')
verify_native_identity(fix, expected_e)
_, fix_command = verify_log(fix, 'just-fix', 'native/ai395-sealed-fix-just-fix.stderr',
                            'native/ai395-sealed-fix-just-fix.stdout')
assert fix_command['argv'] == plan['commands']['scoped_fix']
assert fix_command['exit_code'] == fix['command_exit_code'] == fix['exit_code'] == 0
assert fix['state'] == 'fix-complete' and fix['post_fix_source_changed'] is True
assert fix['tests_rerun_after_fix'] is False and fix['changed_paths'] == [PATH]
assert fix['unexpected_changed_paths'] == []
equal_rows(fix['after'], expected_s)
assert fix['post_fix_diff_sha256'] == sha(read('native/ai395-sealed-native-fix.patch'))
assert read('native/ai395-sealed-fix-changed-after-fix.stdout') == PATH.encode() + b'\0'
assert sha(read('native/ai395-sealed-fix-changed-after-fix.stdout')) == step(fix, 'changed-after-fix')['stdout_sha256']
assert set(entry['sha256'] for entry in fix['prior_phases']) == set(negative_digests + [sha(read('native/ai395-sealed-green-receipt.json'))])

outer = js('native/ai395-sealed-remaining-pipeline-v2-receipt.json')
assert outer['head'] == E and outer['tree'] == ET
assert outer['state'] == 'sequence-complete' and outer['exit_code'] == 0
assert outer['tests_rerun_after_fix'] is False
assert [entry['phase'] for entry in outer['phases']] == ['red-q-plasticity', 'red-q-selector', 'green', 'fix']
for entry in outer['phases']:
    assert entry['returncode'] == 0 and entry['accepted_for_next_stage'] is True
    assert entry['receipt_sha256'] in all_artifacts
assert outer['runner_sha256'] == RUNNER and outer['orchestrator_sha256'] in all_artifacts
fresh = outer['phases'][0]['fresh_eval_compilation']
assert fresh['obsolete_warning_absent'] is True
assert 'source-next/codex-rs/hepta-intelligence-eval' in fresh['compile_marker']
assert fresh['compile_marker'] in read('native/ai395-sealed-q3-attempt2-just-test.stderr').decode()
assert sha(read('native/ai395-q3-fresh-eval-fcbed-depinfo.d')) == fresh['fresh_depinfo'][0]['sha256']
assert b'product_qualification_use.rs' in read('native/ai395-q3-fresh-eval-fcbed-depinfo.d')

review_refs = []
for review_file in sorted(A.glob('*.json')):
    rel = review_file.name
    review = js(rel)
    if not isinstance(review, dict):
        continue
    for entry in review.get('artifacts', []):
        if not isinstance(entry, dict) or not {'path', 'sha256'} <= set(entry):
            continue
        data = read(entry['path'])
        assert sha(data) == entry['sha256'] and len(data) == entry['bytes']
        review_refs.append({'review': rel, **entry})
assert sha(read('second-native-positive-and-fix-review.json')) == '68152c6ee834fddbb0be89e0c83865c6341f4733dbee361df769b601d8d46d3a'
assert sha(read('q3-native-independent-review.json')) == '23a56d7a6bd14e7dad2e2c0cb1d23ba7f56749405289b64d8e59b16addd015c5'
assert validation['native_results']['green']['observed'] == green['test_summary']
product_index = js('product-independent-evidence-index.json')
assert product_index['tested_second_head'] == E and product_index['post_fix_source_head'] == S
assert len(product_index['files']) == len({row['path'] for row in product_index['files']}) == 48
for row in product_index['files']:
    prefix = 'qualification/sealed-ingress-20261105/'
    assert row['path'].startswith(prefix)
    data = read(row['path'][len(prefix):])
    assert sha(data) == row['sha256'] and len(data) == row['bytes']
for row in js('negative-controls/manifest.json'):
    receipt = js(row['native_receipt'])
    assert row['positive_source_head'] == receipt['execution_head'] == E
    assert row['native_receipt_sha256'] == sha(read(row['native_receipt']))
    assert row['patch_sha256'] == receipt['negative_patch_sha256']
    assert row['attempt'] == receipt['attempt'] and row['actual_test_exit'] == receipt['test_exit_code']
transfer = js('native/ai395-final-S-inventory-transfer-proof.json')
assert transfer['execution_head'] == S and transfer['tree'] == ST
assert transfer['json_sha256'] == sha(inventory_raw) and transfer['json_size'] == len(inventory_raw)
assert transfer['tracked_rust_count'] == 5314
assert transfer['alignment_receipt_sha256'] == sha(read('native/ai395-second-postfix-alignment-receipt.json'))

result = {
    'schema': 'hepta.sealed-ingress-final-source-result-check.v1',
    'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'tested': {'head': E, 'tree': ET}, 'current': {'head': S, 'tree': ST, 'sole_parent': E},
    'source_delta': {'path': PATH, 'before_blob': expected_e[PATH]['git_blob'],
                     'after_blob': expected_s[PATH]['git_blob'], 'exact_change': 'One final-use update_id.clone() -> update_id',
                     'other_thirteen_ingress_files_unchanged': True, 'source_bytes_delta': -8,
                     'after_bytes_equal_exact_single_replacement': True},
    'full_current_rust_inventory': {'count': len(inventory), 'sha256': sha(inventory_raw),
                                    'bytes': len(inventory_raw), 'all_fourteen_current_entries_match': True,
                                    'scope': 'Archived native full-tree blob verification; reviewer checks inventory integrity and all 14 controlled source entries, not a second remote rehash.'},
    'current_alignment': {'sha256': sha(read('native/ai395-second-postfix-alignment-receipt.json')),
                          'all_steps_exit_zero': True, 'clean': True, 'full_r3_fmt_check': True,
                          'no_working_byte_change_by_alignment': True, 'tests_rerun': False, 'fix_rerun': False,
                          'original_receipts': originals},
    'negative_observations': negative_results,
    'preserved_failed_q3': {'attempt': 1, 'command_exit': 101, 'wrapper_exit': 1,
                            'error': 'E0432 before test execution', 'behavioral_red': False,
                            'fourteen_positive_files_restored': True},
    'cache_repair': {'first_guard_refusal_preserved': True, 'source_configuration_unchanged': True,
                     'sole_recorded_cache_mutation': clean_command['argv'], 'command_exit': 0,
                     'same_frozen_Q3_plan_command_and_patch_reused': True,
                     'fresh_eval_source_next_marker_and_depinfo_verified': True},
    'positive': {'source_head': E, 'command': green_command['argv'], 'command_exit': 0,
                 'actual_PASS_lines': len(passes), 'failed': 0, 'skipped': 66, 'slow': 1,
                 'critical_actual_PASS_lines': critical_passes, 'all_four_required_control_receipts_precede_green': True,
                 'command_elapsed_seconds': green_command['elapsed_seconds'],
                 'stderr_sha256': green_command['stderr_sha256']},
    'fix': {'source_head_at_execution': E, 'command': fix_command['argv'], 'command_exit': 0,
             'state': fix['state'], 'changed_paths': [PATH], 'unexpected_changed_paths': [],
             'tests_rerun_after_fix': False, 'resulting_source': S,
             'native_patch_sha256': fix['post_fix_diff_sha256'], 'E_green_not_reassigned_to_S': True},
    'sequence': {'actual_tail_order': [entry['phase'] for entry in outer['phases']],
                  'state': outer['state'], 'raw_receipt_sha256': sha(read('native/ai395-sealed-remaining-pipeline-v2-receipt.json'))},
    'independent_review_artifact_references': {'checked': len(review_refs), 'all_match': True, 'references': review_refs},
    'product_independent_subindex': {'entries': 48, 'all_hashes_sizes_match': True,
                                    'tested_E_and_current_S_identity_correct': True},
    'current_negative_manifest_receipts_attempts_patch_hashes_match': True,
    'full_inventory_transfer_proof_matches_archived_json_and_alignment': True,
    'observation_limits': [
        'Four controls have 7 named failing cases and one inherited retry each; retries are not independent experimental samples.',
        'Q1 first metrics/current-trust panics do not observe later time-policy, append or counter assertions.',
        'Q3 unequal-digest panic does not observe later replay assertions; Q2/Q4 default panics do not print returned Result values.',
        'The unmodified positive E run separately passes all seven complete named regression tests.',
        'S is a reviewed mechanical test-source adoption, with formatter/source alignment only and no test rerun.',
        'No remote source verification, native test, fix, model/tool action or product release was performed by this archive review.'
    ],
    'issues': []
}
assert sha((ROOT / 'integration/final-second-evidence-payload.json').read_bytes()) == PIN
(OUT / 'source-results-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'inventory': len(inventory), 'current_ingress': 14, 'original_receipts': len(originals),
                  'accepted_controls': len(negative_results), 'positive_PASS': len(passes),
                  'review_artifact_references': len(review_refs), 'issues': []}))
