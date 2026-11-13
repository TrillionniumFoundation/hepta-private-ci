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
        self.m = load(cfg['maintenance_guard_path'], V5_PIN, 'original_maintenance_v5_environment_only')
        m = self.m
        check(str(m.REPO) == cfg['repo'] and str(m.TARGET) == cfg['target'], 'original actual source/target paths')
        m.OUT = self.output
        m.cfg = cfg['runtime_guard']
        check(isinstance(m.cfg, dict) and m.cfg.get('minimum_target_free_bytes') == 32 * 1024**3
              and m.cfg.get('create_target_if_absent') is False, 'original current resource preconditions')
        m.real_directory(self.output.parent)
        os.mkdir(self.output, 0o700)
        self.inventory = load(cfg['inventory_driver_path'], INVENTORY_PIN, 'original_full_inventory_for_qualification')
        self.initial_raw = None
        self.environment = None
        self.initial_git = None
        m.read_input(cfg['maintenance_guard_path'], V5_PIN)
        m.read_input(cfg['inventory_driver_path'], INVENTORY_PIN)

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
              and final_format['source_repo'] == cfg['repo']
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
              and aligned['source_repo'] == cfg['repo']
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
        self.initial_git = m.git_state()
        check(self.initial_git == after['git_state'], 'actual exact canonical raw Git state')
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
            self.environment = m.environment_preflight()
        else:
            # The source-gate driver needs no Cargo, formatter or runtime mutation.
            # Its own immutable implementation validates its complete fresh clone.
            self.environment = {'source_gates_only': True}
        m.jwrite('ADMISSION.json', {'status': 'actual_clean_final_source_admitted',
                 'source': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'],
                 'full_initial_inventory': cfg['full_physical_inventory'],
                 'native_snapshot_sha256': cfg['expected_inventory_sha256'],
                 'qualification': False, 'at': m.now()})
        return self

    def before_native_stage(self, name):
        active = self.m.active_build_processes()
        self.m.jwrite(name + '.BUILD_PROCESS_PREFLIGHT.json', active)
        check(not active['active_matching_processes'] and not active['unreadable_matching_processes'],
              'active/unknown same-UID build/formatter process before ' + name)
        check(self.m.verify_original_inputs()['unchanged'] is True, 'original inputs before native stage')
        self.current_lock()

    def finish(self):
        self.current_lock()
        self.m.verify_original_inputs()
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
