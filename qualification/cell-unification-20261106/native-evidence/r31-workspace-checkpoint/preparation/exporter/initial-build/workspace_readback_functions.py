"""Source text for the inert exporter builder; not an executable runner."""


def verify_prior_terminal(value, job_id, expected_exit):
    require(value['job_id'] == job_id and value['exit_code'] == expected_exit
            and value['state'] == ('succeeded' if expected_exit == 0 else 'failed'),
            'historical outer identity/result differs')
    for key in ('output_complete', 'output_durable', 'terminal_publication_confirmed'):
        require(value[key] is True, 'historical outer publication incomplete')
    for key in ('timed_out', 'cancelled', 'automatic_retry'):
        require(value[key] is False, 'historical outer was not natural')
    require(not any(value['log_truncated'].values()) and all(v is None for v in value['log_errors'].values()),
            'historical output was truncated or unavailable')


def preserve_r29_baseline(pre, pinned_input):
    proof = pre['original_r29_workspace_baseline']
    require(proof['schema'] == 'hepta.r31-original-r29-workspace-baseline.v1'
            and proof['source_commit'] == SOURCE52_COMMIT and proof['source_tree'] == SOURCE52_TREE,
            'R29 baseline source identity differs')
    require(proof['identity_key'] == ['binary', 'name'] and proof['count'] == 20228
            and proof['original_failed_100_preserved'] is True and proof['test_ids_used_as_filter'] is False
            and proof['old_metadata_reused_as_current'] is False, 'R29 baseline boundary differs')
    require(len(proof['originals']) == 4 and {p['path'] for p in proof['originals']} == set(R29_WORKSPACE_BASELINE_INPUT_PINS),
            'R29 original baseline files differ')
    originals = {}
    for pointer in proof['originals']:
        raw = pinned_input(pointer, 'input/r29-original-workspace-baseline')
        check_pin(raw, R29_WORKSPACE_BASELINE_INPUT_PINS[pointer['path']], pointer['path'])
        originals[pointer['path']] = raw
    old = 'native-workspace-r29'
    metadata = json.loads(originals[old + '-metadata.json'])
    members, defaults = metadata['workspace_members'], metadata['workspace_default_members']
    packages = {p['id']: p for p in metadata['packages']}
    require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
            and set(members) == set(defaults) and len(packages) == len(metadata['packages'])
            and set(members) <= set(packages), 'R29 original workspace member identities differ')
    rows, review = review_original_workspace(originals[old + '-tests.log'], {packages[p]['name'] for p in members})
    require(rows == json.loads(originals[old + '-test-results.json'])
            and review == json.loads(originals[old + '-result-review.json']), 'R29 original full-log rows/review differ')
    require(review['complete_execution_accounting'] is True and review['pass'] is False
            and review['terminal_unique_test_count'] == 20228
            and review['terminal_counts'] == {'PASS': 20227, 'FAIL': 1, 'TIMEOUT': 0}
            and review['reported_skipped'] == 130, 'R29 failure population was relabelled')
    require(proof['observed_original_counts'] == review['terminal_counts']
            and proof['original_reported_skipped'] == review['reported_skipped'], 'R29 proof results differ')
    failed = {p['path']: pinned_input(p, 'input/r29-failed-provenance') for p in pre['original_r29_failed_100_provenance']}
    receipt = json.loads(failed[old + '-tests-receipt.json'])
    raw_result = json.loads(failed[old + '-tests-raw-process-result.json'])
    terminal = json.loads(failed[old + '-terminal-process-status.json'])
    require(receipt['source_commit'] == raw_result['source_commit'] == SOURCE52_COMMIT
            and receipt['source_tree'] == raw_result['source_tree'] == SOURCE52_TREE
            and receipt['exit_code'] == raw_result['exit_code'] == receipt['effective_exit_code'] == 100,
            'R29 original raw/receipt failure differs')
    require(terminal['state'] == 'failed' and terminal['exit_code'] == 100, 'R29 outer failure differs')
    require(receipt['log_sha256'] == sha(originals[old + '-tests.log'])
            and receipt['acceptance_readback'] == {'path': old + '-result-review.json', **data_pin(originals[old + '-result-review.json'])},
            'R29 original failed receipt does not bind the full baseline log')
    ids = {(r['binary'], r['name']) for r in rows}
    require(len(ids) == len(rows) == 20228, 'R29 baseline has duplicate identities')
    return ids, {'source_commit': SOURCE52_COMMIT, 'source_tree': SOURCE52_TREE,
                 'count': len(ids), 'counts': review['terminal_counts'], 'reported_skipped': review['reported_skipped'],
                 'failed_100_preserved': True, 'used_as_filter': False}


def preserve_prior_project(pre, env, pinned_input, kind):
    historical = kind == 'r28'
    name = 'source52_r28_historical_project_gate' if historical else 'r30_closed_gate_readback'
    proof = pre[name]
    prefix = R28_PREFIX if historical else R30_PREFIX
    commit, tree, count = (SOURCE52_COMMIT, SOURCE52_TREE, 195) if historical else (COMMIT, TREE, 197)
    phases = ('python-runner', 'strict', 'tests') if historical else ('strict', 'tests')
    expected_count = 26 if historical else 19
    require(proof['source_commit'] == commit and proof['source_tree'] == tree, 'prior project source identity differs')
    expected_names = {prefix + suffix for suffix in ('-environment.json', '-preconditions.json',
        '-source-pre-verification.json', '-source-final-verification.json', '-complete.json',
        '-tests-test-results.json', '-tests-result-review.json')}
    for phase in phases:
        expected_names |= {prefix + '-' + phase + suffix for suffix in (
            '.log', '-resources.txt', '-raw-process-result.json', '-receipt.json',
            '-source-pre-verification.json', '-source-post-verification.json')}
    if historical:
        expected_names.add(prefix + '-python-runner-result-review.json')
    require(len(proof['originals']) == expected_count and {p['path'] for p in proof['originals']} == expected_names,
            'prior project original set differs')
    originals = {p['path']: pinned_input(p, 'input/' + kind + '-prerequisites') for p in proof['originals']}
    outer = json.loads(pinned_input(proof['outer_terminal'], 'input/' + kind + '-prerequisites'))
    verify_prior_terminal(outer, R28_JOB_ID if historical else R30_JOB_ID, 0)
    prior_env = json.loads(originals[prefix + '-environment.json'])
    require(prior_env['selection'] == env['selection']
            and prior_env['approved_prerequisite_env_pin'] == env['approved_prerequisite_env_pin'],
            'current and prior environment/prerequisite selection differs')
    previous_pre = json.loads(originals[prefix + '-preconditions.json'])
    baseline_raw = pinned_input(previous_pre['baseline'], 'input/' + kind + '-baseline')
    baseline_object = json.loads(baseline_raw)
    ids = {(row['binary'], row['name']) for row in baseline_object['test_ids']}
    expected_ids = 1564 if historical else 1345
    require(len(ids) == len(baseline_object['test_ids']) == expected_ids, 'prior project baseline identity count differs')
    if not historical:
        require(previous_pre['baseline']['path'] == BASELINE_NAME and sha(baseline_raw) == BASELINE_SHA,
                'R30 exact app-server baseline differs')
    else:
        require(proof['historical_source52_all_three_phases_and_outer_pass'] is True
                and proof['source53_execution_claimed'] is False and proof['substitutes_for_r30'] is False,
                'historical source52 project was relabelled as source53 qualification')
    def prior_guard(value):
        if historical:
            verify_inherited_guard(value, 'r28 prerequisite')
        else:
            recorded_guard(value)
    prior_guard(json.loads(originals[prefix + '-source-pre-verification.json']))
    prior_guard(json.loads(originals[prefix + '-source-final-verification.json']))
    package_names = HISTORICAL_FOUR_PACKAGES if historical else PACKAGES
    args = [value for package in package_names for value in ('-p', package)]
    commands = {
        'strict': ['just', 'clippy', '--locked', *args, '--', '-D', 'warnings'],
        'tests': ['just', 'test', '--locked', '--retries', '0', *args],
        'python-runner': ['python3', '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_run_nextest*.py', '-v'],
    }
    receipt_pins = []
    end = None
    for phase in phases:
        stem = prefix + '-' + phase
        raw_bytes, rec_bytes = originals[stem + '-raw-process-result.json'], originals[stem + '-receipt.json']
        raw, rec = json.loads(raw_bytes), json.loads(rec_bytes)
        require(raw['source_commit'] == rec['source_commit'] == commit and raw['source_tree'] == rec['source_tree'] == tree,
                'prior phase source identity differs')
        require(raw['phase'] == phase and raw['command'] == commands[phase]
                and raw['cwd'] == str(S if phase == 'python-runner' else S / 'codex-rs'), 'prior phase command differs')
        require(raw['exit_code'] == rec['exit_code'] == rec['effective_exit_code'] == 0
                and rec['phase_pass'] is True and rec['issues'] == [], 'prior project phase is not actual PASS')
        for key in ('phase', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
            require(raw[key] == rec[key], 'prior raw/receipt differs: ' + key)
        require(raw['end_unix'] >= raw['start_unix'] and (end is None or raw['start_unix'] >= end)
                and outer['at_unix_ms'] / 1000 >= raw['end_unix'], 'prior phase time order differs')
        end = raw['end_unix']
        require(rec['raw_process_result'] == {'path': stem + '-raw-process-result.json', **data_pin(raw_bytes)},
                'prior raw pointer differs')
        require(rec['log_sha256'] == sha(originals[stem + '.log'])
                and rec['resources_sha256'] == sha(originals[stem + '-resources.txt'])
                and re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', originals[stem + '-resources.txt'], re.M) == [b'0'],
                'prior log/resources/result differ')
        prior_guard(json.loads(originals[stem + '-source-pre-verification.json']))
        post = json.loads(originals[stem + '-source-post-verification.json'])
        prior_guard(post)
        require(post['gate_exit_code'] == 0 and rec['source_guards_pass'] is True
                and rec['source_postguard'] == {'path': stem + '-source-post-verification.json', **data_pin(originals[stem + '-source-post-verification.json'])},
                'prior postguard pointer differs')
        if phase == 'python-runner':
            computed = review_python(originals[stem + '.log'])
            require(computed['pass'] is True and computed == json.loads(originals[stem + '-result-review.json']),
                    'historical Python32 complete log differs')
        if phase == 'tests':
            rows, computed = (review_inherited_tests if historical else review_tests)(originals[stem + '.log'], ids)
            require(computed['pass'] is True and len(rows) == expected_ids
                    and {(row['binary'], row['name']) for row in rows} == ids,
                    'prior full project exact identity population did not pass')
            require(rows == json.loads(originals[stem + '-test-results.json'])
                    and computed == json.loads(originals[stem + '-result-review.json']), 'prior complete rows/review differ')
        if rec['acceptance_readback'] is not None:
            acceptance = stem + '-result-review.json'
            require(rec['acceptance_readback'] == {'path': acceptance, **data_pin(originals[acceptance])},
                    'prior acceptance pointer differs')
        receipt_pins.append({'path': stem + '-receipt.json', **data_pin(rec_bytes)})
    complete = json.loads(originals[prefix + '-complete.json'])
    require(complete['source_commit'] == commit and complete['source_tree'] == tree
            and complete['source_guards_pass'] is True and complete['phase_receipts'] == receipt_pins
            and proof['phase_receipts'] == receipt_pins, 'prior complete identity/receipt binding differs')
    require(complete['strict_exit'] == complete['tests_exit'] == 0
            and complete['all_old_ids_observed_pass'] is True and complete['fix_fmt_executed'] is False,
            'prior complete result differs')
    if historical:
        require(complete['python_exit'] == 0 and proof['python_tests'] == 32 and proof['python_skipped'] == 0,
                'historical Python phase differs')
    else:
        require(proof['same_source_strict_full_tests_and_outer_pass'] is True and proof['exact_old_test_id_set'] is True
                and complete['diagnostic_only'] is True and complete['behavior_repair_claimed'] is False,
                'R30 source53 project classification differs')
        require(proof['source53_apply'] == pre['source53_apply'], 'R30 and R31 apply provenance differs')
    require(complete['cargo_lock_sha256'] == LOCKS['codex-rs/Cargo.lock']
            and complete['bazel_lock_sha256'] == LOCKS['MODULE.bazel.lock'], 'prior dual lock identity differs')
    return {'source_commit': commit, 'source_tree': tree, 'source_count': count,
            'original_count': expected_count, 'outer_exit': 0, 'baseline_count': expected_ids,
            'full_logs_reparsed': True, 'historical_only': historical,
            'qualifies_current_workspace': False, 'terminal_at_unix_ms': outer['at_unix_ms']}


def review_closed_workspace(closed, terminal, baseline, baseline_proof, prerequisites):
    """Preserve nonzero raw returns and absent originals; never fabricate success."""
    errors = []
    def attempt(label, operation, default=None):
        try:
            return operation()
        except Exception as error:
            errors.append({'stage': label, 'error': repr(error)})
            return default
    def get(suffix):
        return json.loads(closed[PREFIX + suffix])
    def identity(value):
        require(value['source_commit'] == COMMIT and value['source_tree'] == TREE, 'current original source differs')
    def classification(value):
        require(value['diagnostic_only'] is True and value['behavior_repair_claimed'] is False,
                'current diagnostic classification differs')
    def pointer(value, name):
        require(value == {'path': name, **data_pin(closed[name])}, 'original pointer differs: ' + name)
    for suffix in ('-environment.json', '-preconditions.json'):
        attempt(suffix + ':identity', lambda suffix=suffix: identity(get(suffix)))
        attempt(suffix + ':classification', lambda suffix=suffix: classification(get(suffix)))
    attempt('initial_guard', lambda: recorded_guard(get('-source-pre-verification.json')))
    metadata = scope = metadata_rec = None
    metadata_rc = attempt('metadata:raw', lambda: get('-metadata-raw-process-result.json'))
    metadata_receipt = attempt('metadata:receipt', lambda: get('-metadata-receipt.json'))
    def verify_metadata():
        raw_bytes = closed[PREFIX + '-metadata.json']
        value = json.loads(raw_bytes)
        raw, receipt = metadata_rc, metadata_receipt
        require(raw is not None and receipt is not None, 'metadata raw or receipt absent')
        for item in (raw, receipt):
            identity(item)
            require(item['command'] == METADATA_COMMAND and item['cwd'] == str(S / 'codex-rs')
                    and item['exit_code'] == 0, 'metadata invocation differs or failed')
        require(raw['schema'] == 'hepta.native-raw-process-result.v1' and raw['phase'] == 'workspace-metadata'
                and receipt['schema'] == 'hepta.native-metadata-receipt.v1', 'metadata schema/phase differs')
        for key in ('command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
            require(raw[key] == receipt[key], 'metadata raw/receipt differs: ' + key)
        require(raw['resources_not_collected_for_read_only_metadata'] is True
                and raw['end_unix'] >= raw['start_unix']
                and raw['start_unix'] * 1000 >= prerequisites['r30']['terminal_at_unix_ms'],
                'metadata prerequisite/time boundary differs')
        require(abs(receipt['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6,
                'metadata elapsed differs')
        pointer(receipt['raw_process_result'], PREFIX + '-metadata-raw-process-result.json')
        pointer(receipt['source_postguard'], PREFIX + '-metadata-source-post-verification.json')
        require(receipt['stdout'] == data_pin(raw_bytes)
                and receipt['stderr'] == data_pin(closed[PREFIX + '-metadata-stderr.log'])
                and receipt['source_guards_pass'] is True, 'metadata output/guard binding differs')
        recorded_guard(get('-metadata-source-post-verification.json'))
        require(value['workspace_root'] == str(S / 'codex-rs') and value['target_directory'] == str(T / 'target'),
                'metadata root/target differs')
        members, defaults = value['workspace_members'], value['workspace_default_members']
        packages = {p['id']: p for p in value['packages']}
        require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
                and set(members) == set(defaults) and len(packages) == len(value['packages'])
                and set(members) <= set(packages), 'actual fresh 193/default identities differ')
        expected_scope = {
            'schema': 'hepta.source53-current-default-workspace-scope.v1', 'source_tree': TREE, 'source_commit': COMMIT,
            'metadata_command': METADATA_COMMAND, 'metadata': {'path': PREFIX + '-metadata.json', **data_pin(raw_bytes)},
            'metadata_generated_on_current_source': True, 'old_metadata_reused_as_current': False,
            'workspace_root': value['workspace_root'], 'target_directory': value['target_directory'],
            'workspace_member_count': len(members), 'workspace_default_member_count': len(defaults),
            'workspace_members': [{'id': pid, 'name': packages[pid]['name'], 'manifest_path': packages[pid]['manifest_path']} for pid in members],
            'workspace_default_members': [{'id': pid, 'name': packages[pid]['name']} for pid in defaults],
            'command': COMMAND, 'features': 'unchanged_defaults', 'filters': 'no_additions',
            'all_platforms_features_external_services_qualified': False, 'diagnostic_only': True, 'behavior_repair_claimed': False,
        }
        actual_scope = get('-scope.json')
        require(actual_scope == expected_scope, 'scope does not reproduce current fresh metadata/original ordering')
        return value, actual_scope, receipt
    verified_metadata = attempt('metadata:full_readback', verify_metadata)
    if verified_metadata is not None:
        metadata, scope, metadata_rec = verified_metadata
    raw = attempt('workspace:raw_json', lambda: get('-tests-raw-process-result.json'))
    receipt = attempt('workspace:receipt_json', lambda: get('-tests-receipt.json'))
    rows, review, parse_error = [], None, None
    raw_exit = raw.get('exit_code') if isinstance(raw, dict) else None
    effective_exit = receipt.get('effective_exit_code') if isinstance(receipt, dict) else None
    def verify_raw():
        require(raw is not None, 'workspace raw return absent')
        identity(raw)
        require(raw['schema'] == 'hepta.native-raw-process-result.v1' and raw['phase'] == 'workspace-tests'
                and raw['command'] == COMMAND and raw['cwd'] == str(S / 'codex-rs'), 'workspace raw command/phase differs')
        require(isinstance(raw['exit_code'], int) and raw['end_unix'] >= raw['start_unix']
                and terminal['at_unix_ms'] / 1000 >= raw['end_unix'], 'workspace raw time/exit differs')
        require(metadata_rec is not None and raw['start_unix'] >= metadata_rec['end_unix'],
                'workspace began without verified current metadata')
    attempt('workspace:raw_identity', verify_raw)
    for suffix in ('-tests-source-pre-verification.json', '-source-post-test-verification.json'):
        attempt(suffix, lambda suffix=suffix: recorded_guard(get(suffix)))
    if PREFIX + '-tests.log' in closed and scope is not None:
        try:
            rows, review = review_workspace(closed[PREFIX + '-tests.log'], {p['name'] for p in scope['workspace_members']}, baseline)
        except Exception as error:
            parse_error = repr(error)
            errors.append({'stage': 'workspace:parser', 'error': parse_error})
    def verify_receipt():
        require(receipt is not None and raw is not None, 'workspace receipt/raw absent')
        identity(receipt); classification(receipt)
        require(receipt['schema'] == 'hepta.native-workspace-gate-receipt.v2', 'workspace receipt schema differs')
        for key in ('source_commit', 'source_tree', 'phase', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
            require(raw[key] == receipt[key], 'workspace raw/receipt differs: ' + key)
        require(receipt['source_manifest'] == SOURCE_NAME and receipt['source_manifest_sha256'] == SOURCE_PIN['sha256']
                and receipt['environment_manifest'] == PREFIX + '-environment.json', 'workspace receipt source/environment differs')
        pointer(receipt['raw_process_result'], PREFIX + '-tests-raw-process-result.json')
        pointer(receipt['source_preguard'], PREFIX + '-tests-source-pre-verification.json')
        pointer(receipt['source_postguard'], PREFIX + '-source-post-test-verification.json')
        pointer(receipt['scope'], PREFIX + '-scope.json')
        require(receipt['log_sha256'] == sha(closed[PREFIX + '-tests.log'])
                and receipt['resources_sha256'] == sha(closed[PREFIX + '-tests-resources.txt']), 'workspace output hashes differ')
        require(re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', closed[PREFIX + '-tests-resources.txt'], re.M) == [str(raw_exit).encode()],
                'workspace resource exit differs')
        post = get('-source-post-test-verification.json')
        require(post['phase'] == 'workspace-tests' and post['gate_exit_code'] == raw_exit
                and receipt['source_guards_pass'] is True, 'workspace postguard result differs')
        require(receipt['phase_pass'] is (effective_exit == 0) and terminal['exit_code'] == effective_exit
                and (raw_exit == 0 or effective_exit == raw_exit), 'workspace outer/effective/raw result differs')
        require(abs(receipt['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6,
                'workspace elapsed differs')
        require(receipt['test_scope'] == 'original_default_workspace' and receipt['packages_argument'] is None
                and receipt['workspace_member_count'] == receipt['workspace_default_member_count'] == 193
                and receipt['retries'] == 0 and receipt['filters'] == 'no_additions'
                and receipt['features'] == 'unchanged_defaults' and receipt['fix_fmt_executed'] is False
                and receipt['outer_timeout_seconds_contract'] == 9600,
                'workspace original no-p/default selection differs')
        require(receipt['original_r29_workspace_baseline'] == baseline_proof
                and receipt['test_ids_used_as_filter'] is False and receipt['exact_old_test_id_set_required'] is True,
                'workspace baseline proof/usage differs')
        if receipt['acceptance_readback'] is not None:
            pointer(receipt['acceptance_readback'], PREFIX + '-result-review.json')
        if effective_exit == 0:
            require(raw_exit == 0 and receipt['issues'] == [] and review is not None and review['pass'] is True,
                    'successful receipt lacks exact full PASS accounting')
    attempt('workspace:receipt_readback', verify_receipt)
    if review is not None:
        def verify_results():
            for name, value in ((PREFIX + '-test-results.json', rows), (PREFIX + '-result-review.json', review)):
                require(name in closed and json.loads(closed[name]) == value, 'original rows/review differs or absent: ' + name)
            if effective_exit == 0:
                require(review['complete_execution_accounting'] is True and review['pass'] is True
                        and review['terminal_unique_test_count'] == 20228, 'successful gate does not have exact20228 PASS')
        attempt('workspace:original_result_readback', verify_results)

    complete = attempt('complete:json', lambda: get('-complete.json')) if PREFIX + '-complete.json' in closed else None
    incomplete = attempt('incomplete:json', lambda: get('-incomplete.json')) if PREFIX + '-incomplete.json' in closed else None
    orchestration = attempt('orchestration:json', lambda: get('-orchestration-error.json')) if PREFIX + '-orchestration-error.json' in closed else None
    if complete is not None:
        def verify_complete():
            identity(complete); classification(complete)
            require(complete['schema'] == 'hepta.source53-default-workspace-complete.v1', 'complete schema differs')
            require(set(closed) == {PREFIX + suffix for suffix in SUCCESS_SUFFIXES}, 'successful closure is not exactly18 original files')
            require(terminal['exit_code'] == raw_exit == effective_exit == 0 and review is not None and review['pass'] is True,
                    'complete record without natural full PASS')
            require(complete['source_manifest'] == SOURCE_NAME and complete['source_manifest_sha256'] == SOURCE_PIN['sha256']
                    and complete['cargo_lock_sha256'] == LOCKS['codex-rs/Cargo.lock']
                    and complete['bazel_lock_sha256'] == LOCKS['MODULE.bazel.lock'], 'complete source/locks differ')
            require(complete['workspace_exit'] == complete['effective_exit_code'] == 0
                    and complete['command'] == COMMAND and complete['source_guards_pass'] is True
                    and complete['workspace_member_count'] == complete['workspace_default_member_count'] == 193,
                    'complete command/scope/exit differs')
            require(complete['unique_test_count'] == review['terminal_unique_test_count']
                    and complete['counts'] == review['terminal_counts'] and complete['reported_skipped'] == review['reported_skipped'],
                    'complete counts differ')
            pointer(complete['receipt'], PREFIX + '-tests-receipt.json')
            pointer(complete['readback'], PREFIX + '-result-review.json')
            pointer(complete['scope'], PREFIX + '-scope.json')
            require(complete['original_r29_workspace_baseline'] == baseline_proof
                    and complete['exact_old_test_id_set_observed_pass'] is True
                    and complete['test_ids_used_as_filter'] is False
                    and complete['original_r29_failure_relabelled_as_pass'] is False
                    and complete['fix_fmt_executed'] is False
                    and complete['all_platforms_features_external_services_qualified'] is False,
                    'complete historical/qualification boundary differs')
        attempt('complete:readback', verify_complete)
    if incomplete is not None:
        def verify_incomplete():
            identity(incomplete); classification(incomplete)
            require(complete is None and terminal['exit_code'] != 0
                    and incomplete['original_exit_code'] == raw_exit
                    and incomplete['effective_exit_code'] == effective_exit == terminal['exit_code'], 'incomplete result differs')
            pointer(incomplete['receipt'], PREFIX + '-tests-receipt.json')
            require(incomplete['terminal_counts'] == (review['terminal_counts'] if review is not None else None)
                    and incomplete['nextest_started'] == (review['nextest_started'] if review is not None else None),
                    'incomplete counts/started differs')
            require(incomplete['fix_fmt_executed'] is False and incomplete['no_automatic_retry'] is True
                    and incomplete['source_retained'] is True, 'incomplete retry/scope differs')
        attempt('incomplete:readback', verify_incomplete)
    if orchestration is not None:
        def verify_orchestration():
            identity(orchestration); classification(orchestration)
            require(orchestration['schema'] == 'hepta.source53-workspace-orchestration-error.v1'
                    and orchestration['no_automatic_retry'] is True and orchestration['source_retained'] is True
                    and orchestration['fix_fmt_executed'] is False and terminal['exit_code'] != 0,
                    'orchestration error identity/boundary differs')
        attempt('orchestration:readback', verify_orchestration)
    if terminal['exit_code'] == 0 and complete is None:
        errors.append({'stage': 'outer_success', 'error': 'original complete absent; no success inferred'})
    if terminal['exit_code'] != 0 and incomplete is None and orchestration is None:
        errors.append({'stage': 'outer_failure', 'error': 'no original incomplete/error; existing originals preserved'})
    passed = terminal['exit_code'] == 0 and complete is not None and review is not None and review['pass'] and not errors
    return {'rows': rows, 'review': review, 'parse_error': parse_error, 'readback_errors': errors,
            'metadata': None if metadata is None else data_pin(closed[PREFIX + '-metadata.json']),
            'metadata_raw_exit': None if metadata_rc is None else metadata_rc.get('exit_code'),
            'metadata_receipt_exit': None if metadata_receipt is None else metadata_receipt.get('exit_code'),
            'original_workspace_exit': raw_exit, 'effective_workspace_exit': effective_exit,
            'original_complete_present': complete is not None, 'original_incomplete_present': incomplete is not None,
            'original_orchestration_error_present': orchestration is not None,
            'engineering_gate': 'PASS' if passed else ('FAIL' if terminal['exit_code'] != 0 else 'READBACK_INCOMPLETE')}
