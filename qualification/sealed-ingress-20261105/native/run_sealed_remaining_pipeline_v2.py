#!/usr/bin/env python3
"""Sequence unchanged, pinned second-wave runner; stop at a nonmatching witness."""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time

TASK = pathlib.Path('/home/qq/work/hepta-convergence-20261105-0c901b')
BUNDLE = TASK / 'native-sealed-gate-v2'
SOURCE = TASK / 'source-next'
HEAD = 'eed6541df0add428add8e2d9ab2cbd54a961abeb'
TREE = 'b8ce8b96a759f522cb7db60027d4844f1b3ad974'
RUNNER_SHA = '46552f047784d07b825cec59e0358cfbb02a010f448b7538bb0fadc15ea2f7df'
PLAN_SHA = '00b4d289a635ae36865dc70732a1a10a03a8fb81575be5b5eba0b21fce7027fe'
MANIFEST_SHA = 'e652b430cf2af22ce8f421288bad0687cb6ba332fa31da696034f1ed9bf7c7da'
Q2_RECEIPT_SHA = '6b3d09bac8a4e5cac69fd423a14fc2a19b7e0ba65139acd82c09c2ddf496c5e4'
EMPTY_SHA = hashlib.sha256(b'').hexdigest()
PHASES = ['red-q-plasticity', 'red-q-selector', 'green', 'fix']
ATTEMPTS = {'red-q-plasticity': 2}
REPAIR_SCRIPT_SHA = '6aac58b0ea2ccbd0f9b9fffc9100aedb19283dc67e420b682680cd41ef24f3ec'
WITNESSES = {
    'red-q-agentd': {
        'name': 'current_use_attestation_binds_the_exact_sealed_publication',
        'file': 'hepta-agentd/src/intelligence_evaluation_tests.rs', 'line': 460,
        'raw_fragments': ['assertion failed: matches!', 'original.evaluate',
                          'Err(AgentdIntelligenceEvaluationError::Evidence(_))'],
        'source_line': 'assert!(matches!(',
    },
    'red-q-plasticity': {
        'name': 'durable_proposal_identity_commits_the_exact_qualification_publication',
        'file': 'hepta-intelligence/src/plasticity_product_tests.rs', 'line': 713,
        'raw_fragments': ['assertion `left != right` failed'],
        'source_line': 'assert_ne!(original.evaluation_digest, other.evaluation_digest);',
    },
    'red-q-selector': {
        'name': 'selector_signature_commits_the_exact_qualification_publication',
        'file': 'hepta-intelligence-eval/src/self_evolution_ingress_tests.rs', 'line': 474,
        'raw_fragments': ['assertion failed: matches!', 'admit_self_evolution_selection_v1',
                          'Err(SelfEvolutionSelectionError::Evidence(_))'],
        'source_line': 'assert!(matches!(',
    },
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path, expected=None):
    data = path.read_bytes()
    if expected:
        need(sha(data) == expected, 'Pinned JSON hash differs: ' + str(path))
    return json.loads(data)


def step(receipt, name, folder):
    found = [s for s in receipt['steps'] if s['name'] == name]
    need(len(found) == 1, 'Missing or duplicate native step ' + name)
    item = found[0]
    streams = {}
    for stream in ['stdout', 'stderr']:
        data = (folder / (name + '.' + stream)).read_bytes()
        need(sha(data) == item[stream + '_sha256'], 'Native stream hash differs: ' + name)
        streams[stream] = data
    return item, streams


def read_phase(phase, positive, expected_sha=None):
    folder = TASK / 'evidence' / ('native-sealed-' + phase + '-v' + str(ATTEMPTS.get(phase, 1)))
    receipt = read_json(folder / 'receipt.json', expected_sha)
    need(receipt['schema'] == 'hepta.sealed-ingress-native-phase.v2', 'Wrong phase schema')
    need(receipt['phase'] == phase and receipt['attempt'] == ATTEMPTS.get(phase, 1), 'Wrong phase/attempt')
    need(receipt['execution_head'] == HEAD and receipt['execution_tree'] == TREE, 'Wrong source identity')
    need(receipt['plan_sha256'] == PLAN_SHA and receipt['positive_manifest_sha256'] == MANIFEST_SHA,
         'Wrong plan/manifest identity')
    need(receipt['native_runner_sha256'] == RUNNER_SHA, 'Runner changed')
    need(receipt['exit_code'] == 0, 'Native wrapper did not accept its phase')
    for name, value in [('head-after', HEAD), ('tree-after', TREE)]:
        item, streams = step(receipt, name, folder)
        need(item['exit_code'] == 0 and streams['stdout'].decode().strip() == value,
             'Source identity changed after ' + phase)
    need(sha((SOURCE / 'codex-rs/Cargo.lock').read_bytes()) == receipt['cargo_lock_sha256'],
         'Cargo.lock differs after phase')
    if phase != 'fix':
        item, streams = step(receipt, 'clean-after', folder)
        need(item['exit_code'] == 0 and streams['stdout'] == b'', 'Source not restored clean')
        for f in positive:
            need(sha((SOURCE / f['path']).read_bytes()) == f['sha256'], 'Live positive source differs')
    return receipt, folder


def verify_red(phase, receipt, folder, positive, controls):
    case = controls[phase]
    witness = WITNESSES[phase]
    need(receipt['state'] == 'named-test-failures-observed-review-required'
         and receipt['test_exit_code'] == 100 and receipt['restored_candidate'] is True,
         'Negative control did not complete and restore')
    need(receipt['restored_positive'] == positive, 'Restored positive manifest differs')
    observation = receipt['failure_observation']
    need(observation['run_count'] == 1 and observation['failed_count'] == 1
         and observation['passed_count'] == 0 and observation['complete_named_red'] is True
         and observation['observed_named_failures'] == [witness['name']], 'Wrong named failure set')
    item, streams = step(receipt, 'just-test', folder)
    need(item['exit_code'] == 100 and item['argv'] == case['command'], 'Wrong original test command')
    raw = re.sub(r'\x1b\[[0-9;]*m', '', (streams['stdout'] + b'\n' + streams['stderr']).decode())
    panics = re.findall(r"thread '([^']+)'[^\n]*panicked at ([^\n]+):", raw)
    location = witness['file'] + ':' + str(witness['line']) + ':5'
    need(len(panics) == 2 and all(name.split('::')[-1] == witness['name'] and loc == location
                                 for name, loc in panics), 'Unexpected first panic location/attempt count')
    for fragment in witness['raw_fragments']:
        need(fragment in raw, 'Required original panic fragment absent: ' + fragment)
    source = SOURCE / 'codex-rs' / witness['file']
    need(source.read_text().splitlines()[witness['line'] - 1].strip() == witness['source_line'],
         'Original assertion source line differs')
    need(sha((folder / 'negative.patch').read_bytes()) == receipt['negative_patch_sha256'],
         'Negative patch differs from native receipt')
    return {'required_name': witness['name'], 'panic_location': location, 'attempts': len(panics),
            'witness_scope': 'first assertion only; later assertions are not observed',
            'stderr_sha256': item['stderr_sha256'], 'restored_positive_count': len(positive)}


def verify_cache_repair():
    folder = TASK / 'evidence/native-eval-cache-repair-v1'
    path = folder / 'receipt.json'
    r = read_json(path)
    need(r['schema'] == 'hepta.task-eval-cache-repair.v1' and r['state'] == 'cache-repair-complete'
         and r['exit_code'] == 0 and r['script_sha256'] == REPAIR_SCRIPT_SHA, 'Cache repair is not complete')
    need(r['head'] == HEAD and r['tree'] == TREE and r['source_clean'] is True
         and r['target'] == str(TASK / 'target') and r['exact_task_target'] is True,
         'Cache repair source/target identity differs')
    need(r['old_unit_paths_absent'] is True and r['original_evidence_preserved'] is True
         and r['active_cargo_or_compiler_processes'] == [], 'Cache repair did not safely invalidate old unit')
    clean, _ = step(r, 'clean-eval-package', folder)
    need(clean['exit_code'] == 0 and clean['argv'] == ['cargo', 'clean', '-p', 'codex-hepta-intelligence-eval'],
         'Cache repair scope changed')
    need(r['backup'] and any(x['original'].endswith('.rmeta') for x in r['backup'])
         and any(x['original'].endswith('.rlib') for x in r['backup']), 'Old unit archive missing')
    for item in r['backup']:
        need(sha(pathlib.Path(item['backup']).read_bytes()) == item['sha256'], 'Old unit archive hash differs')
    for rel, expected in r['original_evidence'].items():
        need(sha((TASK / 'evidence' / rel).read_bytes()) == expected, 'Historical failure evidence differs')
    return {'path': str(path), 'sha256': sha(path.read_bytes()),
            'clean_finished_unix_ns': r['clean_finished_unix_ns'], 'old_unit_backup_count': len(r['backup'])}


def verify_fresh_eval(receipt, folder, repair):
    _, streams = step(receipt, 'just-test', folder)
    raw = (streams['stdout'] + b'\n' + streams['stderr']).decode()
    marker = 'Compiling codex-hepta-intelligence-eval v0.0.0 (' + str(SOURCE / 'codex-rs/hepta-intelligence-eval') + ')'
    need(marker in raw, 'Q3 retry did not freshly compile eval from source-next')
    need('unused import: `crate::IndependentEvaluationDispositionV1`' not in raw,
         'Obsolete eval warning was replayed after cache repair')
    items = []
    for path in sorted((TASK / 'target/debug/deps').glob('codex_hepta_intelligence_eval-*.d')):
        data = path.read_bytes()
        stat = path.stat()
        need(stat.st_mtime_ns >= repair['clean_finished_unix_ns'], 'Old eval dep-info survived package clean')
        need(b'hepta-intelligence-eval/src/product_qualification_use.rs' in data,
             'Fresh eval dependency information lacks the helper module')
        items.append({'path': str(path), 'size': len(data), 'sha256': sha(data), 'mtime_ns': stat.st_mtime_ns,
                      'contains_qualification_use': True})
    need(items, 'Fresh eval dep-info is absent')
    return {'compile_marker': marker, 'obsolete_warning_absent': True, 'fresh_depinfo': items,
            'cache_repair_receipt_sha256': repair['sha256']}


def main():
    evidence = TASK / 'evidence/native-sealed-remaining-pipeline-v2'
    evidence.mkdir(exist_ok=False)
    receipt = {'schema': 'hepta.sealed-ingress-native-sequence.v1', 'head': HEAD, 'tree': TREE,
               'state': 'preflight', 'phases': [], 'runner_sha256': RUNNER_SHA,
               'orchestrator_sha256': sha(pathlib.Path(__file__).read_bytes()),
               'test_profile_features_timeouts_unchanged': True, 'automatic_retry': False}

    def save():
        temp = evidence / 'receipt.json.tmp'
        temp.write_text(json.dumps(receipt, indent=2) + '\n')
        temp.replace(evidence / 'receipt.json')

    try:
        save()
        need(sha((BUNDLE / 'run_native_round2.py').read_bytes()) == RUNNER_SHA, 'Frozen runner hash differs')
        plan = read_json(BUNDLE / 'plan.json', PLAN_SHA)
        positive = read_json(BUNDLE / 'final-positive-manifest.json', MANIFEST_SHA)['files']
        controls = {x['phase']: x for x in plan['controls']}
        q2, q2folder = read_phase('red-q-agentd', positive, Q2_RECEIPT_SHA)
        receipt['q2_predecessor_review'] = verify_red('red-q-agentd', q2, q2folder, positive, controls)
        repair = verify_cache_repair()
        receipt['cache_repair_prerequisite'] = repair
        save()
        common = ['--head', HEAD, '--tree', TREE, '--bundle', str(BUNDLE), '--plan-sha256', PLAN_SHA,
                  '--positive-manifest-sha256', MANIFEST_SHA,
                  '--first-wave-head', 'facba0d32c1cd0e8163a6186d7ba91fa311f2e2e',
                  '--first-wave-desktop-receipt', str(TASK / 'evidence/native-desktop-regression-v1/receipt.json'),
                  '--first-wave-green-receipt', str(TASK / 'evidence/native-green-v2/receipt.json'),
                  '--first-wave-fix-receipt', str(TASK / 'evidence/native-fix-v1/receipt.json')]
        for phase in PHASES:
            need(sha((BUNDLE / 'run_native_round2.py').read_bytes()) == RUNNER_SHA, 'Frozen runner drift')
            argv = [sys.executable, str(BUNDLE / 'run_native_round2.py'), phase] + common + ['--attempt', str(ATTEMPTS.get(phase, 1))]
            receipt['state'] = 'running-' + phase
            save()
            print(json.dumps({'pipeline_stage': 'start', 'phase': phase, 'argv': argv}), flush=True)
            started = time.time()
            completed = subprocess.run(argv)
            row = {'phase': phase, 'returncode': completed.returncode, 'elapsed_seconds': time.time() - started}
            receipt['phases'].append(row)
            save()
            need(completed.returncode == 0, 'Native phase returned nonzero: ' + phase)
            actual, folder = read_phase(phase, positive)
            row['receipt'] = str(folder / 'receipt.json')
            row['receipt_sha256'] = sha((folder / 'receipt.json').read_bytes())
            if phase in WITNESSES:
                row['first_assertion_review'] = verify_red(phase, actual, folder, positive, controls)
                if phase == 'red-q-plasticity':
                    row['fresh_eval_compilation'] = verify_fresh_eval(actual, folder, repair)
            elif phase == 'green':
                item, _ = step(actual, 'just-green', folder)
                need(actual['state'] == 'green-complete' and actual['command_exit_code'] == 0
                     and item['exit_code'] == 0 and item['argv'] == plan['commands']['positive_full'],
                     'Full original positive command did not pass')
                summary = actual['test_summary']
                critical = {n for c in controls.values() for n in c['required_named_failures']}
                need(summary['run_count'] > 0 and summary['passed_count'] == summary['run_count']
                     and summary['failed_count'] == 0 and set(summary['critical_passes']) == critical,
                     'Incomplete positive suite')
                row['test_summary'] = summary
            else:
                item, _ = step(actual, 'just-fix', folder)
                need(actual['state'] == 'fix-complete' and actual['command_exit_code'] == 0
                     and item['exit_code'] == 0 and item['argv'] == plan['commands']['scoped_fix'],
                     'Original scoped fix did not complete')
                need(actual['tests_rerun_after_fix'] is False and actual['unexpected_changed_paths'] == [],
                     'Unexpected fix scope or post-fix tests')
                row['post_fix_source_changed'] = actual['post_fix_source_changed']
                row['changed_paths'] = actual['changed_paths']
                row['post_fix_diff_sha256'] = actual['post_fix_diff_sha256']
            row['accepted_for_next_stage'] = True
            save()
            print(json.dumps({'pipeline_stage': 'complete', **row}), flush=True)
        receipt.update(state='sequence-complete', exit_code=0, tests_rerun_after_fix=False)
    except Exception as error:
        receipt.update(state='sequence-blocked', exit_code=1, error=str(error))
    save()
    print(json.dumps({'pipeline_state': receipt['state'], 'exit_code': receipt['exit_code'],
                      'receipt': str(evidence / 'receipt.json')}), flush=True)
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
