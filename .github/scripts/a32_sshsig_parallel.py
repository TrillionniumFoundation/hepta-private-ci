"""Query-only prerequisites and settled same-attempt resolver/native evidence gates."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

from a32_sshsig_bazel import receipt as bazel_receipt
from a32_sshsig_collection import nested_child_uncertainty
from a32_sshsig_controls_nokill import SPECS, command_for
from a32_sshsig_evidence import (census, reconcile_nextest, bep_events, parse_libtest_list,
                                 parse_libtest_batches, check_xml, proto_int)
from a32_sshsig_guard import (LOCKS, MANIFEST, MEMORY_CASES, PACKAGES, digest, inventory,
                              require, save, verify_bundle, verify_input, verify_pass_cases, check_clean, git)

LANES = ('resolver-linux', 'linux', 'windows', 'windows-owner')
PREREQUISITES = ('cc', 'c++', 'ar', 'make', 'pkg-config', 'bwrap')


def prerequisites(qualification):
    require(sys.platform == 'linux' and qualification.state.get('lane') == 'linux', 'native Linux prerequisite query only')
    found = {name: shutil.which(name) for name in PREREQUISITES}
    save(qualification.evidence / 'prerequisites.json', {'executables': found,
         'query_only': True, 'installation_attempted': False, 'namespace_probe_run': False})
    require(all(found.values()), 'HOLD: missing existing Linux prerequisite; no install/repair: ' +
            ', '.join(name for name, path in found.items() if not path))
    for name, path in found.items():
        qualification.run('prerequisite-' + name, [path, '--version'])
    qualification.run('prerequisite-libcap', [found['pkg-config'], '--modversion', 'libcap'])
    qualification.state['linux_prerequisites_queried'] = True
    qualification.flush()


def read_json(folder, name):
    return json.loads((folder / name).read_bytes())


def expected_identity(state):
    return {'source_sha': os.environ['SOURCE_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
            'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'branch': os.environ['GITHUB_REF_NAME'],
            'repository': os.environ['GITHUB_REPOSITORY'], 'input_tree': state['input_tree']}


def settled(folder, lane):
    require(folder.is_dir() and not folder.is_symlink(), 'missing/non-directory lane evidence')
    require(not any(path.is_symlink() for path in folder.rglob('*')), 'evidence symlink forbidden')
    require(not (folder / 'PARTIAL-NOT-SETTLED.json').exists(), 'partial evidence is not readiness or qualification')
    require(read_json(folder, 'sealed-inventory.json') == inventory(folder, ('sealed-inventory.json',)),
            'sealed evidence inventory changed')
    snapshot = read_json(folder, 'snapshot-receipt.json')
    require(snapshot.get('incomplete_commands') == [], 'unfinished command in snapshot')
    rows = snapshot['immutable_prefix_snapshots']; index = read_json(folder, 'sealed-inventory.json')
    expected = set(index) - {'snapshot-receipt.json'}
    require(len(rows) == len(expected) and {row['path'] for row in rows} == expected, 'incomplete/duplicate snapshot coverage')
    for row in rows:
        require(row['prefix_bytes'] == row['source_bytes_after']
                and index[row['path']] == {'bytes': row['prefix_bytes'], 'sha256': row['sha256']},
                'writer grew or sealed snapshot bytes differ')
    state, commands = read_json(folder, 'source.json'), read_json(folder, 'commands.json')
    require(state.get('lane') == lane and state.get('identity') == expected_identity(state),
            'wrong lane/source/run/attempt identity')
    require(state.get('runner_os') == ('Linux' if lane in ('resolver-linux', 'linux') else 'Windows')
            and state.get('runner_arch') == 'X64', 'wrong recorded native runner platform')
    require(state.get('input_verified') is True and state.get('final_source_clean') is True
            and not state.get('active_child_latch') and not state.get('format_writer_may_be_active')
            and not nested_child_uncertainty(folder), 'source or writer outcome not settled')
    require(state.get('published') is False and state.get('full_project_qualified') is False,
            'unexpected broader authority claim')
    require(commands and len({row['name'] for row in commands}) == len(commands), 'missing/duplicate command ledger')
    require(all(row.get('status') == 'passed' and row.get('exit_code') == 0 for row in commands),
            'failed/interrupted/unrecorded controller command')
    require(state.get('final_head') == state.get('candidate', {}).get('commit'), 'final candidate head differs')
    require('install-bazel-version' in {row['name'] for row in commands}, 'missing pinned Bazel version command')
    bazel_receipt(folder, 'linux' if lane in ('resolver-linux', 'linux') else 'win32')
    return state, {row['name']: row for row in commands}


def resolver(folder):
    state, commands = settled(folder, 'resolver-linux')
    require(state.get('resolver_completed') is True and state.get('native_completed') is False
            and state.get('pre_resolution_format_passed') is True
            and state.get('steps', {}).get('resolve', {}).get('outcome') == 'success',
            'resolver not complete, failed, or incorrectly native-qualified')
    required = {'harness-tests', 'rustsec-oracle', 'rustsec-policy', 'cargo-resolve', 'cargo-locked-metadata',
                'cargo-resolve-repeat', 'cargo-deny-full-policy', 'bazel-lock-update', 'bazel-lock-check',
                'bazel-lock-repeat', 'bazel-lock-recheck', 'version-cargo-deny', 'install-dotslash-version'}
    required.update('version-' + name for name in ('python', 'rustc', 'cargo', 'nextest', 'just', 'uv', 'bazel', 'dotslash'))
    require(required <= commands.keys() and not any(name.endswith('-tests') and name != 'harness-tests'
            for name in commands), 'resolver command scope missing or includes native qualification')
    manifest = verify_bundle(folder / 'locks', state['identity'], state['lock_manifest_sha256'])
    require(manifest['candidate'] == state['candidate'], 'resolver candidate/lock manifest mismatch')
    for lock, prefix in zip(LOCKS, ('Cargo.lock', 'MODULE.bazel.lock')):
        data = (folder / 'locks' / lock).read_bytes()
        require(data == (folder / (prefix + '.first')).read_bytes()
                == (folder / (prefix + '.second')).read_bytes()
                == (folder / 'observed-current-locks' / lock).read_bytes(), 'resolver lock repeat/final bytes disagree')
    return state


def required_commands(lane):
    names = {'install-dotslash-version', 'configured-cquery', 'configured-aquery', 'configured-analysis', 'native-locked-metadata',
             'fmt-check', 'clippy-nonmutating'}
    names.update('version-' + name for name in ('python', 'rustc', 'cargo', 'nextest', 'just', 'uv', 'bazel', 'dotslash'))
    packages = (PACKAGES[0], PACKAGES[-1]) if lane == 'windows-owner' else PACKAGES
    names.update(package + suffix for package in packages for suffix in ('-compiled-census', '-tests'))
    if lane != 'windows-owner':
        names.update(('bazel-testlogs', 'bazel-compiled-census', 'bazel-full-owners'))
    if lane == 'windows':
        names.update(('acquisition-oracle', 'recovery-oracle', 'acquisition-controls', 'recovery-controls'))
    return names, packages


def control_receipts(root, folder, manifest, candidate):
    for family, lanes in (('acquisition', ('positive', 'unchecked-create', 'path-check-open')),
                          ('recovery', ('positive', 'shared-source', 'skip-snapshot'))):
        spec = SPECS[family]; path = root / spec[0]
        binding = manifest['control_bindings']['oracle_files_unchanged'].get(spec[0], {})
        require(digest(path.read_bytes()) == binding.get('sha256'),
                'frozen oracle hash mismatch')
        module_spec = importlib.util.spec_from_file_location('aggregate_' + family, path)
        module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
        controls = folder / (family + '-controls'); receipt = read_json(controls, 'manifest.json')
        require(receipt.get('restored') is True and receipt.get('source_tree') == candidate['tree']
                and receipt.get('source_head', receipt.get('source_sha')) == candidate['commit']
                and receipt.get('qualified', receipt.get('qualified_native_controls')) is True
                and receipt.get('command') == command_for(spec) == module.COMMAND,
                'control restore/source/command/qualification mismatch')
        require([row['lane'] for row in receipt['lanes']] == list(lanes), 'missing/reordered control lanes')
        for row in receipt['lanes']:
            checked = module.check_result(row['lane'], row['exit_code'],
                                          (controls / (row['lane'] + '.log')).read_text())
            require(checked == {key: row[key] for key in ('statuses', 'observations')}, 'frozen oracle receipt mismatch')


def archived_bazel(folder, kind, targets, expected=None, ignored=None):
    events = bep_events((folder / (kind + '.bep.jsonl')).read_bytes(), 0, 'test')
    receipt = read_json(folder, 'bazel-compiled-census.json' if expected is None else 'bazel-counts.json')
    summaries = {e['id']['testSummary']['label']: e for e in events if 'testSummary' in e['id']}
    outcomes = {json.dumps(e['id']['testResult'], sort_keys=True): e['testResult']
                for e in events if 'testResult' in e['id']}
    require(set(receipt['targets']) == set(receipt['compiled_cases']) == set(summaries) == set(targets)
            and receipt.get('all_announced_events_completed') is True, 'missing archived Bazel owner')
    seen = set()
    for target, row in receipt['targets'].items():
        summary = summaries[target]['testSummary']; configuration = summaries[target]['id']['testSummary'].get('configuration')
        shards = max(1, proto_int(summary, 'shardCount'))
        require(row['summary'] == summary and summary.get('overallStatus') == 'PASSED'
                and proto_int(summary, 'totalNumCached') == 0
                and proto_int(summary, 'runCount') == proto_int(summary, 'attemptCount') == 1
                and proto_int(summary, 'totalRunCount') == shards and len(row['shards']) == shards,
                'archived Bazel summary differs or is cached/retried')
        cases = {}; discovered = set(); shard_ids = set(); log_uris = set()
        for shard in row['shards']:
            identity = shard['identity']; key = json.dumps(identity, sort_keys=True); result = shard['result']
            number = proto_int(identity, 'shard'); shard_ids.add(number)
            require(key not in seen and outcomes.get(key) == result and identity['label'] == target
                    and identity.get('configuration') == configuration and configuration
                    and proto_int(identity, 'run') == proto_int(identity, 'attempt') == 1,
                    'archived shard identity/result/configuration mismatch')
            seen.add(key); info = result.get('executionInfo', {})
            require(result.get('status') == 'PASSED' and not result.get('cachedLocally', False)
                    and not info.get('cachedRemotely', False) and proto_int(info, 'exitCode') == 0
                    and info.get('strategy') in ('local', 'standalone', 'sandboxed', 'linux-sandbox', 'windows-sandbox'),
                    'archived non-native/failed/cached shard')
            location = folder / kind / digest(target.encode())[:16] / ('shard-' + str(number))
            log, xml = (location / 'test.log').read_bytes(), (location / 'test.xml').read_bytes()
            items = result.get('testActionOutput', []); outputs = {item.get('name'): item for item in items}
            require(len(items) == len(outputs) and 'test.log' in outputs and 'test.xml' in outputs, 'ambiguous archived BEP outputs')
            require(all(isinstance(outputs[name].get('uri'), str) and outputs[name]['uri'].startswith('file:')
                        for name in ('test.log', 'test.xml')), 'missing/nonlocal archived output reference')
            require(outputs['test.log'].get('uri') not in log_uris, 'same native output reused across shards')
            log_uris.add(outputs['test.log'].get('uri'))
            for name, data in (('test.log', log), ('test.xml', xml)):
                item = outputs[name]
                require(('length' not in item or str(item['length']) == str(len(data)))
                        and (not item.get('digest') or item['digest'] == digest(data)), 'BEP archived output digest/length differs')
            require(digest(log) == shard['log_sha256'] and digest(xml) == shard['xml_sha256']
                    and check_xml(xml) == shard['xml'], 'archived native log/XML hash or XML result differs')
            if expected is None:
                discovered.update(parse_libtest_list(log))
            else:
                parsed = parse_libtest_batches(log)
                require(not set(cases).intersection(parsed['cases']) and all(
                    batch['counts']['filtered'] + len(batch['cases']) == len(expected[target]) for batch in parsed['batches']),
                    'archived native shard batch/compiled count differs')
                cases.update(parsed['cases'])
        require(shard_ids == set(range(1, shards + 1)), 'missing/duplicate native shard')
        require(len(summary.get('passed', [])) == shards and not summary.get('failed')
                and {item.get('uri') for item in summary['passed']} == log_uris, 'BEP summary/result output references differ')
        if expected is not None:
            discovered = set(cases)
            require(discovered == set(expected[target]) and cases == row['cases']
                    and {name for name, status in cases.items() if status == 'ignored'} == set(ignored.get(target, [])),
                    'archived exact native cases/ignored set differ')
        require(sorted(discovered) == receipt['compiled_cases'][target] and len(discovered) == row['native_cases'],
                'archived compiled census/count differs')
    require(seen == set(outcomes), 'unaccounted archived BEP shard')
    return receipt


def native(root, folder, lane, resolved):
    state, commands = settled(folder, lane)
    require(state.get('identity') == resolved['identity'] and state.get('candidate') == resolved['candidate']
            and state.get('lock_manifest_sha256') == resolved['lock_manifest_sha256']
            and state.get('same_run_locks_verified') is True, 'native source/candidate/same-attempt lock mismatch')
    require(state.get('native_completed') is True and state.get('product_qualified') is False
            and state.get('steps', {}).get('native', {}).get('outcome') == 'success', 'native lane did not complete successfully')
    lock_manifest = (folder / 'consumed-lock-manifest.json').read_bytes()
    require(digest(lock_manifest) == resolved['lock_manifest_sha256'], 'consumed lock manifest differs')
    for lock, identity in json.loads(lock_manifest)['files'].items():
        data = (folder / 'observed-current-locks' / lock).read_bytes()
        require({'bytes': len(data), 'sha256': digest(data)} == identity, 'native final lock bytes changed')
    if lane == 'linux':
        require(state.get('linux_prerequisites_queried') is True, 'Linux native prerequisites not observed')
    else:
        require(state.get('token_probe', {}).get('sha256') == digest((folder / 'token.json').read_bytes()),
                'missing native token observation')
        token = read_json(folder, 'token.json')
        require(token.get('schema') == 'a32.sshsig-token-probe.v1' and token.get('thread_impersonating') is False
                and token.get('query_errors') == [] and token.get('process') == state['token_probe'].get('process'),
                'native token query uncertain or receipt differs')
        if lane == 'windows-owner':
            require(state['token_probe'].get('owner_capable') is True and token.get('owner_capable_sid'),
                    'owner setup unavailable is not pass')
    required, packages = required_commands(lane)
    require(required <= commands.keys(), 'native command census incomplete')
    manifest = read_json(folder, 'source-manifest.json')
    require(digest((folder / 'source-manifest.json').read_bytes()) == state['source_manifest_sha256']
            == resolved['source_manifest_sha256'], 'different source/control manifest across lanes')
    platform = 'linux' if lane == 'linux' else 'windows'
    results = {}
    for package in packages:
        listing = (folder / 'logs' / (package + '-compiled-census.log')).read_bytes()
        expected = census(listing, package, manifest['ignored_tests'][platform].get(package, []))
        output = (folder / 'logs' / (package + '-tests.log')).read_bytes()
        actual = reconcile_nextest(output, expected)
        recorded = read_json(folder, package + '-counts.json')
        require(actual == {key: recorded[key] for key in actual}, 'native exact census/count receipt differs')
        if package == 'codex-hepta-memory':
            verify_pass_cases(output.decode(), MEMORY_CASES)
        if platform == 'windows' and package == PACKAGES[-1]:
            required_cases = ['durable::windows::output::tests::read_only_private_directory_exercises_native_sync_helper_error_propagation']
            if lane == 'windows-owner':
                required_cases += ['durable::windows::custody_tests::' + name for name in (
                    'wrong_owner_rejects_even_with_a_current_user_only_dacl',
                    'owner_change_after_open_rejects_the_same_retained_descriptor',
                    'final_symlink_rejects_even_when_its_target_is_private_and_valid')]
            require(recorded.get('required_native_cases') == required_cases and all(
                    actual['cases'].get(package + ' ' + case) == 'PASS' for case in required_cases),
                    'missing native owner/reparse/helper PASS')
        results[package] = {key: actual[key] for key in ('compiled_cases', 'passed', 'skipped')}
    require(state.get('configured_targets') == manifest['bazel_targets'][platform], 'configured owners differ')
    bep_events((folder / 'analysis.bep.jsonl').read_bytes(), 0, 'build', allow_no_build=True)
    if lane != 'windows-owner':
        listing = archived_bazel(folder, 'bazel-list', state['configured_targets'])
        actual = archived_bazel(folder, 'bazel-tests', state['configured_targets'],
                                listing['compiled_cases'], manifest['bazel_ignored_tests'][platform])
        results['bazel_native_cases'] = {label: row['native_cases'] for label, row in actual['targets'].items()}
    if lane == 'windows':
        control_receipts(root, folder, manifest, state['candidate'])
    return {'counts': results, 'scope': state['scope'], 'open_gates': state['open_gates']}


def aggregate(root, incoming, needs):
    require(set(needs) == {'resolver-linux', 'native-linux', 'native-windows'}
            and all(row.get('result') == 'success' for row in needs.values()), 'a required job failed/skipped/cancelled')
    resolved = resolver(incoming / 'resolver-linux')
    require(resolved['source_manifest_sha256'] == digest((root / MANIFEST).read_bytes()),
            'resolver manifest differs from current reviewed source manifest')
    outputs = needs['resolver-linux'].get('outputs', {})
    require(outputs.get('lock-manifest-sha256') == resolved['lock_manifest_sha256']
            and outputs.get('candidate-tree') == resolved['candidate']['tree'], 'resolver job output binding mismatch')
    results = {lane: native(root, incoming / lane, lane, resolved) for lane in LANES[1:]}
    return {'schema': 'a32.sshsig-parallel-aggregate.v1', 'identity': resolved['identity'],
            'candidate': resolved['candidate'], 'lock_manifest_sha256': resolved['lock_manifest_sha256'],
            'resolver_native_qualified': False, 'required_diagnostic_lanes_completed': True, 'lanes': results,
            'product_qualified': False, 'v1_formal_gates_changed': False, 'windows_release_replay_authority': False,
            'normal_user_execution_inferred_from_linked_or_derived_token': False,
            'helper_flush_is_public_g5_device_fault_proof': False, 'independent_evidence_review_required': True}


def release_locks(root, incoming):
    state = resolver(incoming)
    check_clean(root)
    require(git(root, 'rev-parse', 'HEAD').decode().strip() == state['candidate']['commit']
            and git(root, 'rev-parse', 'HEAD^{tree}').decode().strip() == state['candidate']['tree']
            and git(root, 'rev-parse', os.environ['SOURCE_SHA'] + '^{tree}').decode().strip() == state['input_tree'],
            'release checkout is not the settled generated candidate')
    require(git(root, 'rev-list', '--parents', '-n', '1', 'HEAD').decode().split()
            == [state['candidate']['commit'], os.environ['SOURCE_SHA']], 'wrong generated candidate parent')
    changed = set(git(root, 'diff', '--name-only', '-z', os.environ['SOURCE_SHA'], 'HEAD').decode().strip('\0').split('\0'))
    require(changed == set(state['candidate']['changed_paths']) and changed <= set(LOCKS), 'release candidate has non-lock delta')
    return state


def aggregate_to_file(root, incoming, output, needs):
    require(not output.exists(), 'fresh aggregate output required')
    try:
        verify_input(root, os.environ['SOURCE_SHA'], os.environ['GITHUB_REF_NAME'])
        result = aggregate(root, incoming, needs)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, sort_keys=True); stream.write('\n')
    except BaseException as error:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.with_name('aggregate-failure.json').open('x', encoding='utf-8') as stream:
                json.dump({'schema': 'a32.sshsig-parallel-failure.v1', 'needs': needs,
                           'requested_identity': {key: os.environ.get(key) for key in (
                               'SOURCE_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REF_NAME', 'GITHUB_REPOSITORY')},
                           'error': repr(error), 'required_diagnostic_lanes_completed': False,
                           'product_qualified': False}, stream, indent=2, sort_keys=True)
                stream.write('\n')
        except BaseException as secondary:
            error.add_note('aggregate failure receipt could not be written: ' + repr(secondary))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('release-locks', 'aggregate'))
    parser.add_argument('incoming', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.phase == 'release-locks':
        state = release_locks(root, args.incoming)
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            print('lock_manifest_sha256=' + state['lock_manifest_sha256'], file=output)
            print('candidate_tree=' + state['candidate']['tree'], file=output)
    else:
        require(args.output is not None, 'aggregate output path required')
        aggregate_to_file(root, args.incoming, args.output, json.loads(os.environ['NEEDS_RESULTS']))


if __name__ == '__main__':
    main()
