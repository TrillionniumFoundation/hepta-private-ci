"""Exact-branch AuthBus refresh diagnostic. No source edits or security setup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

BASE = 'e5b2002db99d231e696df1a7647889d4be656f0f'
PARENT = 'c4ded18427cd9b7854d56a80730fe6bd37d8ae70'
BRANCH = 'refs/heads/dot/authbus-lint-qualification-20261006'
PRODUCTS = {'codex-rs/hepta-agentd/src/automation_effect_host.rs': {'base': '7484825cdf90224bcd771695b9d9e692cdb26be7', 'candidate': '7ea843322b6c3fab3db815f36dd7df7b2162fa29'}, 'codex-rs/hepta-agentd/src/browser_servo.rs': {'base': '89bf62c8da8808a59047718313b43ed74bcf5ac5', 'candidate': 'd6232415313fa47c332a309c9c377aad8d6e6278'}, 'codex-rs/hepta-agentd/src/cognitive_context.rs': {'base': '494043d2e03a7f738ad1de3a065766a4423cef0b', 'candidate': '4979cc767f6fcd0fff189e8417b22b97cb3b06c0'}, 'codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs': {'base': '5ab696a64859955a49ac07aa0634094b5144d97b', 'candidate': 'ec7cc681bc1b6f473b135cdc10d32124327be376'}, 'codex-rs/hepta-agentd/src/cognitive_context_request.rs': {'base': None, 'candidate': '088fa1ca016d0f92163fd34beeefe7d9b975f3bc'}, 'codex-rs/hepta-agentd/src/cognitive_context_tests.rs': {'base': '21b5cb0e03f66fc86645a73fd978626ce1e9638a', 'candidate': 'ba4d809c1f23163e9fcd0709097adde608342a88'}, 'codex-rs/hepta-agentd/src/cognitive_retrieval_learning.rs': {'base': '7dde8b3954eeca66ecee1f91d6a388d2871a5540', 'candidate': 'd226ca43fe446cb4c10a737d38497b2f31acb094'}, 'codex-rs/hepta-agentd/src/cognitive_retrieval_learning_tests.rs': {'base': 'f282b1ff8c959e1451cb45eae76c769d41f2c997', 'candidate': 'e78695d66a7830f9493df3c5562df974b8248434'}, 'codex-rs/hepta-agentd/src/intelligence_product.rs': {'base': '1781996175ec7f16f44b9f58ac3e2c2bd41358af', 'candidate': 'd2ed9bc10b0b0c217c91aac3f59d9eb9715941fc'}, 'codex-rs/hepta-agentd/src/intelligence_product_runner.rs': {'base': '1e83821238aef2b5f478a958e32151c2091acdc8', 'candidate': '7dd337420e799b01eda1e748f49a958d9ab24a78'}, 'codex-rs/hepta-agentd/src/lib.rs': {'base': 'c075e561eaa96820706ad98d20972eb5fd924b06', 'candidate': 'b47c8a54359f8150f39e41bb0a400b4cb410aa0b'}, 'codex-rs/hepta-agentd/src/plasticity_host.rs': {'base': '085d85fde32b89d59eb3169d8d8f6e7f005c2ac5', 'candidate': 'c5e390e0b09f776fc4e493eeca40bc66eab20788'}, 'codex-rs/hepta-agentd/src/plasticity_learning_producer.rs': {'base': '507dc9a4e89399a3a67dc48c8f8b12f2a1a46a67', 'candidate': 'c5142ccd95e2b837ac6ddb5e6efece3aa23b25bc'}, 'codex-rs/hepta-agentd/src/plasticity_runtime.rs': {'base': 'd1c57448d9c344171ae85d0abe888fe990e7a021', 'candidate': '7d76801786837e835791dc07df3d1de83df9a3f0'}, 'codex-rs/hepta-agentd/src/plasticity_runtime_lifetime_tests.rs': {'base': '6fb6e22b86638b60871696a691db12baf16a1347', 'candidate': '2ae36f567e955c4f998da3e2e78769d1bf26294d'}, 'codex-rs/hepta-agentd/src/state.rs': {'base': '2260831880c27f3ea062114e51bba58dc7b50a0e', 'candidate': '5b30c2801e621c7baa8d16d9b8761f592df34ed4'}, 'codex-rs/hepta-agentd/src/state_control.rs': {'base': 'e7c2f88a5dd4c4414ce13a3060b7b8ccea934e28', 'candidate': 'c9eed3a2f2aca5019b1ec466c9d4aa21743b047a'}, 'codex-rs/hepta-agentd/src/test_support.rs': {'base': '5b7db40482c96bae227dbe4f59770e5595461c4d', 'candidate': 'f9dced94135a53a29fd266db683d013833250727'}, 'codex-rs/hepta-agentd/src/state_isolation_tests.rs': {'base': 'a3b52a0f4e635571a2a70e9b2d93001d0be44ca8', 'candidate': '080339497d286dbb81addc31c2312ad7bc9d22e5'}, 'codex-rs/hepta-infer-worker-host/src/native_app_server.rs': {'base': '11f2db281a3bb2c1f80f5b3ceebb2cb5fedd09d1', 'candidate': 'b62c3d55a078562778e8c8c8e8d9069b95f51f24'}, 'codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs': {'base': '9cd9c6564d47ce37d26ac9f0694c5743d73273c3', 'candidate': '78add4668d2bf3985b62f400cc2f3e1ee1586080'}, 'codex-rs/hepta-infer-worker-host/src/native_output_text.rs': {'base': None, 'candidate': '6440a07e06a4edea31f3500cfa2fcdce48cff2b6'}, 'codex-rs/hepta-infer-worker-host/src/native_output_text_tests.rs': {'base': None, 'candidate': '942e868fd8b332dea4941a8d60dfb71656f63962'}, 'codex-rs/hepta-agentd/tests/terminal_cell_owner.rs': {'base': 'dc06eca8abfc6c85e1f32ea0846c75dd9883d80e', 'candidate': '324377a0be0d49c09aed30dcc5418139c7076376'}}
DIAGNOSTICS = ('.github/workflows/authbus-lint-qualification.yml', 'scripts/hepta_authbus_lint_qualification.py')
REQUIRED = 'automation_effect_host::tests::host_dispatches_exact_wire_payload_once'
REQUIRED_AGENTD = ('automation_effect_host::tests::host_dispatches_exact_wire_payload_once', 'plasticity_runtime::lifetime_tests::agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently', 'plasticity_runtime::tests::runtime_queue_capacity_is_bounded', 'cognitive_context::tests::hnmf::final_use_revalidation_rejects_changed_hnmf_context', 'intelligence_product::tests::signed::signed_evaluation_completes_existing_owner_preparation_and_run_admission', 'state::isolation_tests::zero_effect_readiness_rejects_missing_cognitive_owner', 'state::isolation_tests::zero_effect_readiness_requires_real_store_then_app_server')
INFER_REQUIRED = ('native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone', 'native_app_server::tests::completed_only_text_does_not_require_or_fabricate_a_delta', 'native_app_server::tests::seeded_start_deltas_and_repeated_final_produce_one_message', 'native_app_server::tests::item_order_and_wrong_binding_are_preserved_for_final_only_messages', 'native_app_server::tests::rejected_text_stays_quarantined_while_grace_records_terminal_truth', 'native_app_server::tests::cancellation_grace_uses_same_text_without_trusting_terminal_summary', 'native_app_server::output_text::tests::completed_only_returns_text_exactly_once', 'native_app_server::output_text::tests::completed_without_start_is_supported', 'native_app_server::output_text::tests::seeded_start_plus_suffix_delta_and_final_preserves_all_text_once', 'native_app_server::output_text::tests::repeated_full_start_is_idempotent_without_completing_item', 'native_app_server::output_text::tests::older_late_start_snapshot_is_noop_and_newer_snapshot_appends_only_suffix', 'native_app_server::output_text::tests::conflicting_late_start_rejects_without_altering_accepted_output', 'native_app_server::output_text::tests::completed_item_allows_only_prefix_consistent_start_snapshots', 'native_app_server::output_text::tests::seeded_start_enforces_text_bound_atomically_on_new_and_existing_items', 'native_app_server::output_text::tests::seeded_start_budget_counts_only_new_suffix_and_all_items', 'native_app_server::output_text::tests::streamed_prefix_plus_completion_adds_only_missing_suffix', 'native_app_server::output_text::tests::identical_duplicate_completion_is_idempotent', 'native_app_server::output_text::tests::repeated_equal_text_with_distinct_ids_is_not_deduplicated', 'native_app_server::output_text::tests::started_order_wins_over_interleaved_text_arrival', 'native_app_server::output_text::tests::missing_and_late_starts_keep_first_observation_order', 'native_app_server::output_text::tests::started_after_completion_does_not_reopen_item', 'native_app_server::output_text::tests::duplicate_deltas_append_because_no_sequence_identity_exists', 'native_app_server::output_text::tests::duplicated_or_out_of_order_deltas_can_conflict_with_final_text', 'native_app_server::output_text::tests::final_must_match_the_whole_streamed_prefix', 'native_app_server::output_text::tests::conflicting_repeated_final_cannot_extend_or_replace_text', 'native_app_server::output_text::tests::empty_delta_after_final_is_harmless_but_nonempty_delta_is_rejected', 'native_app_server::output_text::tests::empty_delta_for_unknown_item_reserves_a_bounded_order_slot', 'native_app_server::output_text::tests::first_error_is_sticky_and_preserves_partial_output', 'native_app_server::output_text::tests::named_completion_preserves_earlier_items', 'native_app_server::output_text::tests::named_completion_can_add_an_item_and_repeat_an_existing_final', 'native_app_server::output_text::tests::all_text_event_kinds_are_rejected_after_terminal_sealing', 'native_app_server::output_text::tests::abort_returns_partial_items_in_reserved_order_without_requiring_finals', 'native_app_server::output_text::tests::empty_turn_and_empty_final_are_valid', 'native_app_server::output_text::tests::opaque_unicode_ids_and_text_use_byte_budgets', 'native_app_server::output_text::tests::each_event_kind_rejects_empty_and_oversized_ids', 'native_app_server::output_text::tests::empty_messages_cannot_bypass_item_count_bound', 'native_app_server::output_text::tests::aggregate_id_bytes_are_bounded_independently_of_item_count', 'native_app_server::output_text::tests::delta_cannot_exceed_aggregate_text_bound_across_items', 'native_app_server::output_text::tests::completed_suffix_budget_charges_only_additional_bytes', 'native_app_server::output_text::tests::oversized_completion_is_atomic_for_existing_and_new_items', 'native_app_server::output_text::tests::unicode_text_limit_is_bytes_not_character_count', 'native_app_server::output_text::tests::abort_snapshot_does_not_reset_state_before_interrupt_grace', 'native_app_server::output_text::tests::rejected_accumulator_remains_rejected_for_interrupt_grace')
PACKAGE = 'codex-hepta-agentd'
PACKAGES = (PACKAGE, 'codex-hepta-infer-worker-host', 'codex-hepta-matrixd')
LIMIT = 16 * 1024**2


def git(*args, env=None):
    return subprocess.check_output(['git', '--no-replace-objects', *args], env=env, text=True).strip()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def remaining():
    seconds = int(float(os.environ['AUTHBUS_DEADLINE']) - time.time())
    if seconds < 30:
        raise ValueError('80-minute anchored diagnostic budget exhausted; remaining stages NOT RUN')
    return seconds


def identity():
    import hepta_ci_exec
    if os.environ.get('GITHUB_EVENT_NAME') != 'push' or os.environ.get('GITHUB_REF') != BRANCH:
        raise ValueError('Only the exact reviewed branch push is allowed')
    record = hepta_ci_exec.identity()
    head = record['commit']
    if record['dirty'] or head != os.environ['SOURCE_SHA'] or head != os.environ['TESTED_SHA']:
        raise ValueError('Source identity or clean-worktree check failed')
    if os.environ.get('HEPTA_CI_LANE') != 'source-head':
        raise ValueError('Source-head lane required')
    if record.get('parents') != [PARENT]:
        raise ValueError('Exact reviewed predecessor required for this diagnostic correction')
    git('merge-base', '--is-ancestor', BASE, head)
    for path, blobs in PRODUCTS.items():
        if blobs['base'] is not None and git('rev-parse', f'{BASE}:{path}') != blobs['base']:
            raise ValueError('Base source blob mismatch: ' + path)
        if git('rev-parse', f'{head}:{path}') != blobs['candidate']:
            raise ValueError('Candidate source blob mismatch: ' + path)
    if set(git('diff', '--name-only', BASE, head).splitlines()) != {*PRODUCTS, *DIAGNOSTICS}:
        raise ValueError('Unexpected source or diagnostic change')
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
        git('read-tree', head, env=env)
        git('update-index', '--force-remove', '--', *DIAGNOSTICS, env=env)
        for path, blobs in PRODUCTS.items():
            if blobs['base'] is None:
                git('update-index', '--force-remove', '--', path, env=env)
            else:
                git('update-index', '--add', '--cacheinfo', f"100644,{blobs['base']},{path}", env=env)
        restored = git('write-tree', env=env)
    if restored != git('rev-parse', f'{BASE}^{{tree}}'):
        raise ValueError('Restored source projection does not equal exact reviewed base')
    return {'head': head, 'tree': record['tree'], 'base': BASE, 'product_blobs': {path: blobs['candidate'] for path, blobs in PRODUCTS.items()},
            'diagnostic_blobs': {p: git('rev-parse', f'{head}:{p}') for p in DIAGNOSTICS}}


def read_json(path):
    if path.stat().st_size > LIMIT:
        raise ValueError('JSON evidence bound exceeded')
    return json.loads(path.read_text())


def discovery_names(data, package=PACKAGE):
    suites = data.get('rust-suites', {})
    if len(suites) != 1:
        raise ValueError('Exactly the Agentd library suite must be discovered')
    suite = next(iter(suites.values()))
    if suite.get('package-name') != package or suite.get('kind') != 'lib' or suite.get('status') != 'listed':
        raise ValueError('Unexpected discovery target or status')
    cases = suite['testcases']
    if data.get('test-count') != len(cases) or not cases:
        raise ValueError('Discovery count mismatch or empty suite')
    for case in cases.values():
        expected_match = {'status': 'mismatch', 'reason': 'ignored'} if case.get('ignored') else {'status': 'matches'}
        if case.get('filter-match') != expected_match:
            raise ValueError('Full library discovery unexpectedly filtered tests')
    runnable = sorted(name for name, case in cases.items() if not case['ignored'])
    ignored = sorted(name for name, case in cases.items() if case['ignored'])
    if package == PACKAGE and not set(REQUIRED_AGENTD).issubset(runnable):
        raise ValueError('Required real product regressions absent or ignored')
    if package == PACKAGES[1] and not set(INFER_REQUIRED).issubset(runnable):
        raise ValueError('Failing consumer regression absent or ignored')
    if not runnable:
        raise ValueError('No executable library tests discovered')
    return {'runnable': runnable, 'ignored': ignored, 'discovered': len(cases)}


def verify_junit(path, expected, required=()):
    raw = path.read_bytes()
    if len(raw) > LIMIT:
        raise ValueError('JUnit evidence bound exceeded')
    root = ET.fromstring(raw)
    cases = list(root.iter('testcase'))
    executed = [c for c in cases if not any(child.tag == 'skipped' for child in c)]
    names = [c.get('name') for c in executed]
    failures = [c.get('name') for c in executed if any(child.tag in ('failure', 'error', 'rerunFailure', 'rerunError') for child in c)]
    if len(names) != len(set(names)) or sorted(names) != sorted(expected):
        raise ValueError('Executed JUnit names/count differ from exact selected discovery')
    if failures:
        raise ValueError(f'Native failures: {failures}')
    if not names or not set(required).issubset(names):
        raise ValueError('Required product regressions did not execute')
    return {'executed': len(names), 'passed': len(names), 'names': sorted(names),
            'reported_skipped': [c.get('name') for c in cases if c not in executed], 'sha256': hashlib.sha256(raw).hexdigest()}


def metadata(directory):
    policy = runpy.run_path('scripts/run-nextest.py', run_name='authbus_nextest_policy')
    workspace = Path.cwd() / 'codex-rs'
    if not all(policy['use_scoped_metadata'](['--locked', '--lib', '-p', package], workspace) for package in PACKAGES):
        raise ValueError('Repository metadata policy requires broader resolution; do not bypass it')
    with (directory / 'cargo-metadata.json').open('x') as output:
        subprocess.run(['cargo', 'metadata', '--no-deps', '--format-version=1', '--locked', '--manifest-path', str(workspace / 'Cargo.toml')], stdout=output, check=True, timeout=remaining())
    data = read_json(directory / 'cargo-metadata.json')
    if data['resolve'] is not None or Path(data['workspace_root']).resolve() != workspace.resolve():
        raise ValueError('Metadata is not the fresh exact no-deps workspace')
    if not set(PACKAGES).issubset({p['name'] for p in data['packages'] if p['id'] in data['workspace_members']}):
        raise ValueError('Selected package missing')


def discovery(directory, package):
    with (directory / (package + '-nextest-list.json')).open('x') as output:
        subprocess.run(['cargo', 'nextest', 'list', '--locked', '--lib', '-p', package,
                        '--cargo-metadata', str(directory / 'cargo-metadata.json'), '--message-format', 'json'],
                       cwd='codex-rs', stdout=output, check=True, timeout=remaining())
    save(directory / (package + '-discovered-names.json'), discovery_names(read_json(directory / (package + '-nextest-list.json')), package))


def recorded_run(path, command):
    import hepta_ci_exec
    cancellation = hepta_ci_exec.CommandCancellation()
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, cancellation.request)
        return hepta_ci_exec.run(path, command, minimum_tests=0, timeout_seconds=remaining(), cancellation=cancellation)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def commands(directory):
    shared = ['just', 'test', '--tool-config-file', f"authbus-lint:{directory / 'junit-overlay.toml'}", '--cargo-metadata', str(directory / 'cargo-metadata.json'), '--locked', '--retries', '0', '--lib']
    stages = [{'name': 'format', 'command': ['rustfmt', '--edition', '2024', '--check', *PRODUCTS]},
              {'name': 'metadata', 'command': [sys.executable, DIAGNOSTICS[1], 'metadata']}]
    for package in (PACKAGE, PACKAGES[1]):
        stages.append({'name': package + '-discovery', 'command': [sys.executable, DIAGNOSTICS[1], 'discovery', '--package', package], 'discovery': package})
        stages.append({'name': package + '-library', 'command': shared + ['-p', package], 'tests': package})
    stages += [
        {'name': 'strict-lint', 'command': ['just', 'clippy', '--locked', '--all-targets', '-p', PACKAGE, '--no-deps', '--', '-D', 'warnings']},
        {'name': 'infer-strict-lint', 'command': ['just', 'clippy', '--locked', '--all-targets', '-p', PACKAGES[1], '--no-deps', '--', '-D', 'warnings']},
        {'name': 'consumer-check', 'command': ['cargo', 'check', '--manifest-path', 'codex-rs/Cargo.toml', '--locked', '--all-targets', '-p', PACKAGES[1], '-p', PACKAGES[2]]},
        {'name': 'legacy-constructor-check', 'command': ['cargo', 'check', '--manifest-path', 'codex-rs/Cargo.toml', '--locked', '--lib', '-p', PACKAGE, '--features', 'qualification-legacy-learning-write']},
    ]
    return stages


def run(directory):
    if shutil.disk_usage(directory).free < 8 * 1024**3:
        raise ValueError('Less than 8 GiB free before build; native qualification incomplete')
    # The lower-priority overlay adds reporting only; repository deadlines stay unchanged.
    (directory / 'junit-overlay.toml').write_text('[profile.local.junit]\npath = ' + json.dumps(str(directory / 'nextest-junit.xml')) + '\n')
    records = [dict(item, status='not-run') for item in commands(directory)]
    save(directory / 'stages.json', records)
    failed = False
    ready = set()
    for rec in records:
        name = rec['name']
        package = rec.get('tests') or rec.get('discovery')
        prerequisite = 'metadata' if rec.get('discovery') else package + '-discovery' if rec.get('tests') else None
        if prerequisite is not None and prerequisite not in ready:
            rec['error'] = 'Required preparation did not pass; stage NOT RUN'
            failed = True
            save(directory / 'stages.json', records)
            continue
        try:
            if rec.get('tests'):
                (directory / 'nextest-junit.xml').unlink(missing_ok=True)
            code = recorded_run(directory / f'{name}.json', rec['command'])
            rec['exit_code'] = code
            native = read_json(directory / f'{name}.json')
            if native.get('interrupted_signal') is not None:
                rec['status'] = 'interrupted'
                save(directory / 'stages.json', records)
                return code or 2
            rec['status'] = 'passed' if code == 0 else 'failed'
            if native.get('output_limit_exceeded'):
                raise ValueError('Native output exceeded bound; evidence incomplete')
            if rec.get('tests'):
                expected = [rec['focused']] if rec.get('focused') else read_json(directory / (package + '-discovered-names.json'))['runnable']
                required = REQUIRED_AGENTD if package == PACKAGE else INFER_REQUIRED
                report = directory / 'nextest-junit.xml'
                shutil.copyfile(report, directory / f'{name}.junit.xml')
                rec['junit'] = verify_junit(report, expected, required)
            if code == 0:
                ready.add(name)
            failed |= code != 0
        except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
            rec.update(status='incomplete', error=str(error))
            failed = True
        save(directory / 'stages.json', records)
    return int(failed)


def stage(directory):
    destination = directory / 'upload'
    if destination.is_symlink():
        raise ValueError('Artifact destination must not be a symlink')
    destination.mkdir(exist_ok=True)
    if any(child.is_symlink() for child in destination.iterdir()):
        raise ValueError('Artifact destination contains a symlink')
    total = 0
    inventory = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise ValueError(f'Symlink evidence rejected: {path.name}')
        if not path.is_file() or path.suffix not in ('.json', '.xml', '.log', '.txt'):
            continue
        size = path.stat().st_size
        if size > LIMIT or total + size > 64 * 1024**2:
            raise ValueError(f'Artifact bound exceeded: {path.name}; no silent truncation')
        shutil.copyfile(path, destination / path.name)
        total += size
        inventory.append({'name': path.name, 'bytes': size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    save(destination / 'inventory.json', inventory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('before', 'after', 'metadata', 'discovery', 'run', 'stage', 'budget'))
    parser.add_argument('--package', choices=PACKAGES)
    args = parser.parse_args()
    if args.phase == 'discovery' and args.package is None:
        parser.error('discovery requires a fixed package')
    directory = Path(os.environ['AUTHBUS_EVIDENCE']).resolve()
    root = Path(git('rev-parse', '--show-toplevel')).resolve()
    if directory.is_relative_to(root):
        raise ValueError('Evidence must be outside source')
    directory.mkdir(parents=True, exist_ok=True)
    if args.phase == 'stage':
        stage(directory)
    elif args.phase == 'budget':
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'minutes={max(1, remaining() // 60)}\n')
    elif args.phase in ('before', 'after'):
        observed = identity()
        save(directory / f'source-{args.phase}.json', observed)
        if args.phase == 'after' and observed != read_json(directory / 'source-before.json'):
            raise ValueError('Source changed during execution')
    else:
        identity()
        if args.phase == 'metadata':
            metadata(directory)
        elif args.phase == 'discovery':
            discovery(directory, args.package)
        else:
            return run(directory)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
