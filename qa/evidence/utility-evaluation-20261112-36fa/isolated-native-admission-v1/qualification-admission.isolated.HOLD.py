"""Exact-source admission only; original native/source gate drivers remain unchanged.

This module has no CLI and performs no work when imported. It is a HOLD until
Root binds the actual final-format, canonical alignment and runtime proofs.
"""
from pathlib import Path
import fcntl
import gzip
import hashlib
import json
import os
import re
import stat
import sys
import types

V5_PIN = {'bytes': 63007, 'sha256': 'ff2078884d48dcb92ec3b681d7479c33e9b074d1677108ce60e913c90f002431', 'git_blob': '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'}
INVENTORY_PIN = {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2', 'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}
PLAN_PIN = {'bytes': 32246, 'sha256': '2a2df598aa5b2673b55465c3978cb6c51a22326fde9878d97f39bf984e905619', 'git_blob': '3aefbc71d69d8014eed9e5a18269bbcc866a7583'}
C0F = 'c0f78493f815780f68b9bf5e390a21314d79311f'

HISTORICAL_REPO = '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
CURRENT_REPO = '/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
MATERIALIZATION_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1')
MATERIALIZER_PIN = {'bytes': 57607, 'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436', 'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'}
MATERIALIZATION_PACKET_PIN = {'bytes': 13764, 'sha256': 'b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3', 'git_blob': '06503652a2895120daf8b66e42b3a01cefeaf4fb'}
MATERIALIZER_CONFIG_PIN = {'bytes': 992, 'sha256': '414a52cdd7802f5d84de65ee70422a14eb93d799ca46912a9d618f734bffe6a0', 'git_blob': '692d2b825dcbb38eb95e91c0fb5f67afa39d0518'}
NATIVE_INVENTORY_PIN = {'bytes': 3530181, 'sha256': '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9', 'git_blob': '2def77faf50ba6d74d923732182dcb3cad916e53'}


class SourceChanged(RuntimeError):
    pass


def check(value, reason):
    if not value:
        raise RuntimeError(reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pin(raw, expected, reason):
    check(isinstance(expected, dict) and all(expected.get(k) == v for k, v in identity(raw).items()), reason)
    return raw


def load(path, expected, name):
    raw = Path(path).read_bytes()
    pin(raw, expected, 'exact original module ' + str(path))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


class Admission:
    def __init__(self, cfg, output, runtime):
        check(cfg.get('state') == 'READY_FOR_FINAL_SOURCE_QUALIFICATION'
              and cfg.get('root_execution_approved') is True, 'final source input remains HOLD')
        self.cfg = cfg
        self.output = Path(output)
        self.lease = None
        self.runtime = runtime
        os.environ['GIT_OPTIONAL_LOCKS'] = '0'
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        sys.dont_write_bytecode = True
        check(cfg.get('historical_source_repo') == HISTORICAL_REPO and cfg.get('repo') == CURRENT_REPO,
              'explicit reviewed historical and isolated current source paths')
        check(cfg.get('source') == 'cc57c7198db6293ccca562253c42fffbe2a04633'
              and cfg.get('tree') == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
              and cfg.get('parents') == ['246d8cb614770252ee42029a5c014f2a4904176a'],
              'unchanged canonical native qualification subject')
        self.h = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_historical_runtime_environment')
        self.m = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_current_source_observation')
        m = self.m
        check(str(m.REPO) == str(self.h.REPO) == HISTORICAL_REPO
              and str(m.TARGET) == str(self.h.TARGET) == cfg['target'], 'original V5 historical source/target constants')
        # Only this separate observation instance follows the new current repository.
        # The unmodified historical instance retains its original 86dd SEED and path.
        m.REPO = Path(cfg['repo']); m.HEAD = cfg['source']; m.TREE = cfg['tree']
        m.OUT = self.output
        m.cfg = cfg['runtime_guard']
        self.h.OUT = self.output / 'historical-runtime'
        self.h.cfg = cfg['runtime_guard']
        check(isinstance(m.cfg, dict) and m.cfg.get('minimum_target_free_bytes') == 32 * 1024**3
              and m.cfg.get('create_target_if_absent') is False, 'original current resource preconditions')
        m.real_directory(self.output.parent)
        os.mkdir(self.output, 0o700)
        os.mkdir(self.h.OUT, 0o700)
        self.inventory = load(cfg['inventory_driver_path'], INVENTORY_PIN, 'original_full_inventory_for_qualification')
        self.initial_raw = None
        self.environment = None
        self.initial_git = None
        m.read_input(cfg['maintenance_guard_path'], V5_PIN)
        m.read_input(cfg['inventory_driver_path'], INVENTORY_PIN)
        self.h.read_input(cfg['maintenance_guard_path'], V5_PIN)

    def read(self, path, expected, name):
        raw = self.m.read_input(path, expected)
        self.m.write(name, raw)
        return self.m.parse(raw)

    def observed_proof(self, value, prefix):
        original = self.read(value['result_path'], value['result'], prefix + '.RESULT.original.json')
        raw = self.m.read_input(value['supervisor_path'], value['supervisor'])
        terminal = self.m.parse_supervisor(raw)
        check(terminal['job_id'] == value['job_id'], prefix + ' exact actual job')
        self.m.write(prefix + '.SUPERVISOR.original.json', raw)
        return original

    def current_lock(self):
        expected = self.cfg['coordination_lock']
        info = os.fstat(self.lease)
        observed = {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid,
                    'mode': stat.S_IMODE(info.st_mode), 'nlink': info.st_nlink}
        check(stat.S_ISREG(info.st_mode) and all(expected[k] == v for k, v in observed.items()),
              'same real task source coordination lock')
        fresh = Path(expected['path']).lstat()
        check(fresh.st_dev == info.st_dev and fresh.st_ino == info.st_ino and not stat.S_ISLNK(fresh.st_mode),
              'coordination lock path still names acquired inode')
        return observed

    def acquire_and_validate(self):
        m = self.m
        cfg = self.cfg
        self.lease = os.open(cfg['coordination_lock']['path'], os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(self.lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        m.jwrite('SOURCE_COORDINATION_SH.json', {'path': cfg['coordination_lock']['path'],
                 **self.current_lock(), 'at': m.now(), 'pid': os.getpid(), 'fd': self.lease,
                 'scope': 'Only cooperative source writers; complete actual source checks remain required.'})
        for key in ('source', 'tree'):
            check(isinstance(cfg.get(key), str) and re.fullmatch('[0-9a-f]{40}', cfg[key]), 'actual final ' + key)
        check(isinstance(cfg.get('parents'), list) and cfg['parents'], 'actual final commit parents')
        check(cfg.get('expected_file_count') == 15188, 'complete current source membership')
        plan = self.read(cfg['plan_path'], PLAN_PIN, 'PLAN.original.json')
        check(plan['schema'] == 'hepta.utility.exact-source-qualification-plan.v2', 'original reviewed qualification plan')
        final_format = self.observed_proof(cfg['final_format'], 'FINAL_FORMAT')
        check(final_format['format'] == 'hepta-reviewed-nonrust-final-format-result-v1'
              and final_format['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
              and final_format['source_repo'] == HISTORICAL_REPO
              and final_format['source_commit'] == '246d8cb614770252ee42029a5c014f2a4904176a'
              and final_format['source_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
              and final_format['parents'] == ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']
              and final_format['qualification'] is False and final_format['fix_dispatched'] is False
              and final_format['test_commands_dispatched'] == 0
              and final_format['attempted_commands'] == ['fmt'] and final_format['not_run_commands'] == []
              and final_format['source_ref_updates'] is False, 'actual final original format prerequisite')
        complete = final_format['actual_final_source']
        check(complete['complete'] is True and final_format['git_metadata_unchanged'] is True
              and complete['postimages']['all_actual_physical_tree'] == cfg['tree']
              and complete['postimages']['all_actual_physical_leaf_count'] == cfg['expected_file_count'],
              'actual final-format physical tree is the canonical qualification subject')
        check(len(final_format['stages']) == 1 and final_format['stages'][0]['name'] == 'fmt', 'one final fmt only')
        stage = final_format['stages'][0]
        check(stage['argv'] == ['just', 'fmt', '--base', C0F] and stage['timeout_seconds'] == 900,
              'unchanged final-format command and budget')
        check(stage['status'] == 'completed_review_required'
              and stage['execution']['returncode'] == 0 and stage['execution']['timed_out'] is False
              and stage['execution']['output_limit_exceeded'] is False, 'actual final fmt normal command terminal')
        check({r['check']: r['status'] for r in final_format['final_audits']} == {
            'actual_complete_source_and_git': 'verified', 'original_inputs': 'verified',
            'same_source_coordination_lock': 'verified'}, 'complete actual final-format audits')
        check(cfg.get('actual_final_format_postimages_reviewed') is True
              and final_format['formatter_changed_paths'] == cfg['reviewed_formatter_changed_paths'],
              'actual final formatter postimages individually reviewed')
        aligned = self.observed_proof(cfg['canonical_alignment'], 'CANONICAL_ALIGNMENT')
        check(aligned['format'] == 'hepta-final-canonical-alignment-result-v1'
              and aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
              and aligned['source_repo'] == HISTORICAL_REPO
              and aligned['physical_source_writes_dispatched'] == 0
              and aligned['cargo_or_formatter_started'] is False
              and aligned['test_commands_dispatched'] == 0
              and aligned['source_branch_refs_updated'] is False
              and aligned['remote_ref_updates'] is False and aligned['automatic_retry'] is False,
              'actual clean canonical alignment only')
        check({r['check']: r['status'] for r in aligned['final_audits']} ==
              {'source': 'verified', 'git': 'verified', 'inputs': 'verified'}, 'complete actual alignment audits')
        after = aligned['after']
        # Only current-source Git expectations change; the original 86dd
        # runtime-restoration SEED identities and validator remain untouched.
        m.HEAD = cfg['source']; m.TREE = cfg['tree']
        self.materialized = self.validate_materialization(aligned)
        self.initial_git = m.git_state()
        check(self.initial_git == self.materialized['current_git_state_after'], 'actual new materialization raw Git state')
        m.jwrite('GIT_STATE.before.json', self.initial_git)
        check(after['commit'] == cfg['source'] and after['tree'] == cfg['tree'] and after['parents'] == cfg['parents'],
              'actual canonical SHA/tree/parents')
        check(all(after['inventory'][k] == v for k, v in cfg['full_physical_inventory'].items()),
              'actual final canonical full inventory identity')
        check(all(aligned['actual'][key] is True for key in (
            'physical_bytes_unchanged', 'physical_modes_unchanged', 'complete_source_clean',
            'detached', 'index_equals_tree', 'normal_stat_refresh_verified')),
            'actual complete physical source and normal canonical index')
        check(aligned['final_format']['job_id'] == cfg['final_format']['job_id']
              and aligned['final_format']['result'] == cfg['final_format']['result']
              and aligned['final_format']['supervisor'] == cfg['final_format']['supervisor'],
              'canonical proof refers to this exact actual final fmt')
        self.initial_raw = self.inventory.inventory(Path(cfg['repo']))
        pin(self.initial_raw, cfg['full_physical_inventory'], 'current complete source equals actual clean alignment')
        self.inventory.require_inventory(self.initial_raw, {'source_sha': cfg['source'], 'source_tree': cfg['tree']})
        check(json.loads(self.initial_raw)['tracked_entries'] == cfg['expected_file_count'], 'all final tracked files')
        m.gzrecord('SOURCE_INITIAL.complete.inventory.json.gz', self.initial_raw)
        for item in plan['unchanged_original_controls']['reviewed_source_pins']['files']:
            m.read_input(Path(cfg['repo']) / item['path'], item)
        m.read_input(cfg['native_driver_path'], plan['unchanged_original_controls']['native_driver'])
        if self.runtime:
            self.environment = self.h.environment_preflight()
            # Re-check path separation for the current repository too; no creation.
            desired = cfg['runtime_guard']['environment']
            external = {'target': m.external_directory(m.TARGET, 'current source external target')}
            for name in ('UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'RUFF_CACHE_DIR'):
                external[name] = m.external_directory(desired[name], 'current source external ' + name)
            m.jwrite('CURRENT_SOURCE_EXTERNAL_DIRECTORIES.json', external)
        else:
            # The source-gate driver needs no Cargo, formatter or runtime mutation.
            # Its own immutable implementation validates its complete fresh clone.
            self.environment = {'source_gates_only': True}
        m.jwrite('ADMISSION.json', {'status': 'actual_clean_final_source_admitted',
                 'source': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'],
                 'full_initial_inventory': cfg['full_physical_inventory'],
                 'native_snapshot_sha256': cfg['expected_inventory_sha256'],
                 'qualification': False, 'at': m.now(),
                 'historical_source_repo': HISTORICAL_REPO,
                 'actual_isolated_materialization': cfg['isolated_materialization']})
        return self

    def validate_materialization(self, aligned):
        """Bind a new actual repository to retained history without changing it."""
        m = self.m
        cfg = self.cfg
        proof = cfg.get('isolated_materialization')
        check(isinstance(proof, dict) and proof.get('result_path') == str(MATERIALIZATION_CONTROL / 'run' / 'RESULT.json')
              and isinstance(proof.get('job_id'), str) and proof['job_id'],
              'actual isolated materialization proof is required; preparation is not a result')
        for name, expected in [('driver.py', MATERIALIZER_PIN), ('MATERIALIZATION_PACKET.json', MATERIALIZATION_PACKET_PIN),
                               ('APPROVED_CONFIG.json', MATERIALIZER_CONFIG_PIN)]:
            m.read_input(MATERIALIZATION_CONTROL / name, expected)
        packet = m.parse(m.read_input(MATERIALIZATION_CONTROL / 'MATERIALIZATION_PACKET.json', MATERIALIZATION_PACKET_PIN))
        check(packet['source_repo'] == HISTORICAL_REPO and packet['destination_repo'] == cfg['repo']
              and packet['current']['commit'] == cfg['source'] and packet['current']['tree'] == cfg['tree']
              and packet['current']['parents'] == cfg['parents'], 'exact reviewed materialization subject')
        value = self.observed_proof(proof, 'ISOLATED_MATERIALIZATION')
        check(value.get('format') == 'hepta-isolated-cc57-materialization-result-v1'
              and value.get('status') == 'MATERIALIZED_EXACT_CC57_FOR_NATIVE_REVIEW_ONLY'
              and value.get('source_repo') == HISTORICAL_REPO and value.get('destination_repo') == cfg['repo']
              and value.get('source_commit') == cfg['source'] and value.get('source_tree') == cfg['tree']
              and value.get('parents') == cfg['parents'], 'complete actual isolated materialization identity')
        for name in ('new_repo_created', 'action_completed', 'new_files_and_directories_synced',
                     'old_physical_and_fixed_git_state_unchanged', 'input_identities_unchanged'):
            check(value.get(name) is True, 'actual isolated materialization ' + name)
        for name in ('qualification', 'old_source_writes', 'remote_ref_updates', 'cargo_or_formatter_started',
                     'dependency_installation_started', 'automatic_retry', 'rollback'):
            check(value.get(name) is False, 'isolated preparation did not authorize ' + name)
        check(value.get('test_commands_dispatched') == 0 and value.get('physical_leaves_created') == 15188
              and value.get('new_objects_fully_verified') == 16449 and value.get('cleanup_errors') == []
              and not any(name in value for name in ('error', 'retention_error')),
              'actual complete materialization, objects and owned process cleanup')
        audits = value.get('final_audits')
        check(isinstance(audits, list) and len(audits) == 3 and {r['check']: r['status'] for r in audits} == {
            'old_physical_source_and_fixed_git_metadata': 'verified', 'new_source_and_git': 'verified',
            'inputs_and_coordination': 'verified'}, 'all three actual materialization audits')
        check(value.get('availability_observation') == packet['observer'], 'same actual original availability observation')
        current = value['current_source_after']
        check(value['current_source_before'] == current == {
            'inventory': cfg['full_physical_inventory'], 'native_inventory': NATIVE_INVENTORY_PIN,
            'head': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'], 'status': ''},
            'actual new complete full source and native projection are both exact and stable')
        check(all(aligned['after']['inventory'][k] == v for k, v in current['inventory'].items())
              and all(packet['current']['inventory'][k] == current['inventory'][k] for k in ('bytes', 'sha256', 'git_blob')),
              'new physical source exactly preserves the actual canonical source content')
        state = value['current_git_state_after']
        check(value['current_git_state_before'] == state and set(state) == {
            'head_raw_sha256', 'head', 'tree', 'index_bytes', 'index_sha256',
            'config_bytes', 'config_sha256', 'refs_bytes', 'refs_sha256'}
              and state['head'] == cfg['source'] and state['tree'] == cfg['tree']
              and state['refs_bytes'] == 0 and state['refs_sha256'] == hashlib.sha256(b'').hexdigest(),
              'new actual detached/no-ref raw Git baseline, independent from historical alignment')
        index = value['current_index']
        check(index['raw']['bytes'] == state['index_bytes'] and index['raw']['sha256'] == state['index_sha256']
              and index['entries'] == 15188 and index['all_entry_logical_identities_verified'] is True
              and index['all_actual_stat_fields_verified'] is True
              and index['assume_unchanged_or_skip_worktree_entries'] == 0
              and all(row['name'] == 'TREE' for row in index['extensions']),
              'normal actual new index entries and stat fields, no copied flags')
        check(value['object_scope'] == {
            'complete_snapshots': [cfg['source'], cfg['parents'][0]], 'objects': 16449,
            'counts': {'blob': 14615, 'tree': 1832, 'commit': 2}, 'complete_ancestry': False,
            'unmaterialized_parent_boundary': '9c4a11f61d30e9cc352bf44d56c98909d202a55d',
            'recursive_history_walk': False, 'network': False}, 'two complete real snapshots, not full ancestry')
        check(value['old_source_before'] == value['old_source_after']
              and value['old_source_after']['present'] == 15181
              and value['old_source_after']['missing'] == sorted(row['path'] for row in packet['seven_missing'])
              and value['old_source_after']['native_inventory'] == packet['expected_old_native_inventory']
              and value['old_git_state_before'] == value['old_git_state_after'] == packet['old_git'],
              'old physical source and declared fixed Git observations were actually preserved')
        check(value['old_git_observation_scope'] == {
            'fixed_raw_files': [row['path'] for row in packet['old_git']['files']],
            'complete_ref_listing_unchanged': True,
            'absent_lookup_paths': packet['old_git']['absent_lookup_paths'],
            'entire_old_object_store_metadata_verified': False}, 'exact historical preservation observation scope')
        lock = value['coordination_lock']
        expected_lock = cfg['coordination_lock']
        check(lock['path'] == expected_lock['path'] and lock['mode'] == 'LOCK_EX'
              and all(lock['stat'][key] == expected_lock[key] for key in ('device', 'inode', 'uid', 'nlink'))
              and stat.S_IMODE(lock['stat']['mode']) == expected_lock['mode'],
              'materialization used the same real task coordination lock')
        records = {}
        for key, filename in [('command_records', 'COMMANDS.json'), ('mutation_records', 'MUTATION_INTENTS.json'),
                              ('input_records', 'INPUT_IDENTITIES.before.json'), ('artifact_records', 'ARTIFACTS.json')]:
            expected = value[key]
            check(expected['name'] == filename, 'fixed actual materialization record path')
            records[key] = self.read(MATERIALIZATION_CONTROL / 'run' / filename, expected,
                                     'ISOLATED_MATERIALIZATION_' + filename)
        commands = records['command_records']
        check(isinstance(commands, list) and bool(commands)
              and all(row.get('actual_terminal') == 'observed' and row.get('returncode') == 0
                      and row.get('timed_out') is False for row in commands),
              'all original materialization command terminals are actually observed and normal')
        intents = records['mutation_records']
        check(isinstance(intents, list) and [row['kind'] for row in intents] == [
            'create_new_repository', 'write_exact_new_physical_source_and_standard_pack',
            'import_independent_standard_pack', 'new_index_and_detached_head']
              and all(row['actual_terminal'] == 'observed' for row in intents),
              'all four scoped new-repository mutation terminals observed')
        inputs = records['input_records']
        for name, expected in [('driver.py', MATERIALIZER_PIN), ('MATERIALIZATION_PACKET.json', MATERIALIZATION_PACKET_PIN),
                               ('APPROVED_CONFIG.json', MATERIALIZER_CONFIG_PIN)]:
            check(inputs[str(MATERIALIZATION_CONTROL / name)] == expected, 'materialization used these exact approved bytes')
        m.jwrite('HISTORICAL_TO_CURRENT_SOURCE_CHAIN.json', {
            'historical_source_repo': HISTORICAL_REPO, 'current_source_repo': cfg['repo'],
            'actual_final_format': cfg['final_format'], 'actual_canonical_alignment': cfg['canonical_alignment'],
            'actual_isolated_materialization': proof, 'source_commit': cfg['source'], 'source_tree': cfg['tree'],
            'full_physical_inventory': current['inventory'], 'native_inventory': current['native_inventory'],
            'current_raw_git_baseline': state, 'qualification': False,
            'scope': 'Historical actual source gates remain their original execution; materialization is a separate exact-content prerequisite.'})
        return value


    def before_native_stage(self, name):
        active = self.m.active_build_processes()
        self.m.jwrite(name + '.BUILD_PROCESS_PREFLIGHT.json', active)
        check(not active['active_matching_processes'] and not active['unreadable_matching_processes'],
              'active/unknown same-UID build/formatter process before ' + name)
        check(self.m.verify_original_inputs()['unchanged'] is True, 'original inputs before native stage')
        check(self.h.verify_original_inputs()['unchanged'] is True, 'historical runtime proof inputs before native stage')
        self.current_lock()

    def finish(self):
        self.current_lock()
        self.m.verify_original_inputs()
        self.h.verify_original_inputs()
        self.h.jwrite('INPUTS.final.json', self.h.input_pins)
        self.h.jwrite('READONLY_COMMANDS.json', self.h.commands)
        current_git = self.m.git_state()
        self.m.jwrite('GIT_STATE.after.json', current_git)
        if current_git != self.initial_git:
            raise SourceChanged('actual raw Git state changed during qualification')
        raw = self.inventory.inventory(Path(self.cfg['repo']))
        self.m.gzrecord('SOURCE_FINAL.complete.inventory.json.gz', raw)
        value = json.loads(raw)
        if value['source'] != {'head': self.cfg['source'], 'tree': self.cfg['tree'], 'status': ''}:
            raise SourceChanged('final source identity changed')
        original = {r['path']: r for r in json.loads(self.initial_raw)['files']}
        actual = {r['path']: r for r in value['files']}
        for path, before in original.items():
            if path not in actual or actual[path] != before:
                raise SourceChanged('source-controlled full inventory row changed: ' + path)
        extras = [r for r in value['files'] if r['path'] not in original]
        # The original b92 native snapshot separately enforces tracked/nonignored
        # equality. Preserve actual ignored JUnit/output entries rather than
        # silently calling this full physical inventory unchanged.
        self.m.jwrite('FULL_PHYSICAL_COMPARISON.json', {'original_rows_identical': True,
                     'full_bytes_equal': raw == self.initial_raw,
                     'additional_physical_entries': extras,
                     'scope': 'Original native snapshot equality is a separate required gate; actual generated outputs remain visible.'})
        self.m.jwrite('INPUTS.final.json', self.m.input_pins)
        self.m.jwrite('READONLY_COMMANDS.json', self.m.commands)
        return {'original_source_rows_unchanged': True, 'extra_physical_entries': len(extras),
                'full_physical_bytes_equal': raw == self.initial_raw}

    def close(self):
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None
