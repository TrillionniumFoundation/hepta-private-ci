"""Real temporary Git/SQLite refusal controls; never download or run a model.

Every database here is a disposable synthetic test authority. No production
registration is created and no remote ref, workflow or trial is executed.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('llm_hosted_once', SOURCE / 'scripts/ci/llm_hosted_once.py')
hosted = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hosted)


class HostedOnceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='trnm-hosted-control-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / 'repository'
        self.repo.mkdir()
        self.runner_temp = self.base / 'runner-temp'
        self.runner_temp.mkdir()
        self.saved_path = list(sys.path)
        self.saved_modules = {name: sys.modules.pop(name, None) for name in
            ('llm_runtime_pilot', 'llm_runtime_trial_ledger', 'llm_runtime_assessment')}
        self.addCleanup(self.restore_imports)
        files = (hosted.DRIVER, hosted.WORKFLOW, hosted.LOCK, hosted.FAMILY,
            'scripts/llm_runtime_pilot.py', 'scripts/llm_runtime_trial_ledger.py',
            'scripts/llm_runtime_assessment.py', 'scripts/llm_parent_material.py',
            'scripts/llm_base_material.py')
        for name in files:
            destination = self.repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, destination)
        (self.repo / '.gitignore').write_text('__pycache__/\n*.pyc\n*.ignored\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic refusal fixture')
        self.git('config', 'user.email', 'synthetic@example.invalid')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic source; no trial')
        self.source = self.git('rev-parse', 'HEAD').strip()
        self.runtime, self.ledger = hosted.modules(self.repo)
        self.ledger_path = self.base / 'synthetic-authority.sqlite3'
        self.state = self.ledger.initialize(self.ledger_path, 1)
        self.manifest_path = self.base / 'manifest.json'
        manifest = dict(model=self.runtime.MODEL, revision=self.runtime.REVISION,
            files={name: dict(revision=self.runtime.REVISION, size=size, sha256=sha)
                   for name, (size, sha) in self.runtime.PUBLIC_FILES.items()})
        self.manifest_path.write_bytes(hosted.canonical(manifest) + b'\n')
        self.trial = '1' * 64
        self.registration = hosted.register(self.repo, self.source, self.ledger_path,
                                            self.manifest_path, self.trial)
        self.path = Path(self.registration['registration'])
        self.value = hosted.decode(self.path.read_bytes())
        self.commit_intent()

    def restore_imports(self):
        sys.path[:] = self.saved_path
        for name, module in self.saved_modules.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module

    def git(self, *args, check=True):
        result = subprocess.run(['git', '-C', str(self.repo), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)
        return result.stdout.decode()

    def commit_intent(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic published intent; never executed')
        self.intent = self.git('rev-parse', 'HEAD').strip()
        self.event = dict(repository=dict(full_name=hosted.REPOSITORY), ref=hosted.REF,
            before=self.source, after=self.intent, created=False, deleted=False, forced=False,
            head_commit=dict(id=self.intent))
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push',
            GITHUB_REPOSITORY=hosted.REPOSITORY, GITHUB_REF=hosted.REF,
            GITHUB_RUN_ATTEMPT='1', GITHUB_RUN_ID='12345', GITHUB_SHA=self.intent,
            GITHUB_WORKFLOW_SHA=self.intent,
            GITHUB_WORKFLOW_REF=hosted.REPOSITORY + '/' + hosted.WORKFLOW + '@' + hosted.REF,
            RUNNER_TEMP=str(self.runner_temp))

    def replace_intent(self, value, raw=None):
        self.git('reset', '--hard', self.source)
        path = self.repo / hosted.INTENTS / (self.trial + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if raw is not None else hosted.canonical(value) + b'\n')
        self.commit_intent()

    def refused_before_effects(self, code=None):
        with mock.patch.object(hosted, 'command') as command, \
             mock.patch.object(hosted, 'download_materials') as download:
            with self.assertRaises((ValueError, OSError)) as error:
                hosted.execute(self.repo, self.event, self.env)
            if code is not None:
                self.assertIn(code, str(error.exception))
            command.assert_not_called()
            download.assert_not_called()
        self.assertFalse((self.runner_temp / 'pon-smollm-hosted-once-v1/launch-intent.json').exists())

    def test_original_registration_and_exact_empty_read_only_authority(self):
        before = self.ledger_path.read_bytes()
        self.git('checkout', '-q', '--detach', self.intent)
        with mock.patch.object(self.ledger, 'initialize', side_effect=AssertionError('job must not initialize')):
            value, admitted = hosted.validate(self.repo, self.event, self.env)
        self.assertEqual(value, self.value)
        self.assertTrue(admitted['git_intent_spent'])
        self.assertEqual(value['plan']['threads'], 4)
        self.assertEqual(value['plan']['training_steps'], 10)
        self.assertEqual(value['plan']['training_budget'], dict(wall_seconds=1800, rss_bytes=16 * 1024**3))
        self.assertEqual(value['plan']['inference_budget'], dict(wall_seconds=600, rss_bytes=8 * 1024**3))
        self.assertNotIn('exit_observation', value['plan'])
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(list(self.base.glob('synthetic-authority.sqlite3-*')), [])

    def test_first_attempt_and_exact_workflow_event_only(self):
        for key, value in (('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                           ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_REF', 'refs/heads/main'),
                           ('GITHUB_REF', 'refs/heads/fix/chain-six-axis-performance-20261103'),
                           ('GITHUB_WORKFLOW_SHA', self.source), ('GITHUB_SHA', self.source),
                           ('GITHUB_WORKFLOW_REF', 'other/workflow'), ('GITHUB_RUN_ID', '0')):
            with self.subTest(key=key), mock.patch.dict(self.env, {key: value}):
                self.refused_before_effects()

    def test_created_deleted_forced_and_false_like_are_refused(self):
        for key in ('created', 'deleted', 'forced'):
            for value in (True, 0, None):
                with self.subTest(key=key, value=value), mock.patch.dict(self.event, {key: value}):
                    self.refused_before_effects('PUSH_CONTEXT')

    def test_duplicate_and_unknown_registration_fields(self):
        original = self.path.read_bytes()
        self.replace_intent(self.value, b'{"schema":"duplicate",' + original[1:])
        self.refused_before_effects('DUPLICATE_JSON')
        value = dict(self.value, command=['untrusted'], output='/tmp/arbitrary')
        self.replace_intent(value)
        self.refused_before_effects('FIELDS')

    def test_every_required_source_hash_and_source_commit_are_bound(self):
        for mutation in ('missing', 'extra', 'changed', 'source'):
            value = copy.deepcopy(self.value)
            if mutation == 'missing':
                value['source_hashes'].pop('scripts/llm_base_material.py')
            elif mutation == 'extra':
                value['source_hashes']['../../outside'] = '0' * 64
            elif mutation == 'changed':
                value['source_hashes'][hosted.LOCK] = '0' * 64
            else:
                value['source_commit'] = '0' * 40
            with self.subTest(mutation=mutation):
                self.replace_intent(value)
                self.refused_before_effects()

    def test_plan_changes_even_numerically_equal_types_refuse(self):
        mutations = [('threads', 1), ('training_steps', 11), ('backend', 'cuda'),
                     ('threads', 4.0), ('runtime_source', '0' * 64)]
        for key, item in mutations:
            value = copy.deepcopy(self.value)
            value['plan'][key] = item
            value['plan_id'] = hosted.digest(hosted.canonical(value['plan']))
            with self.subTest(key=key, value=item):
                self.replace_intent(value)
                self.refused_before_effects('EXACT_PLAN')
        value = copy.deepcopy(self.value)
        value['plan']['training_budget']['wall_seconds'] = 1799
        value['plan_id'] = hosted.digest(hosted.canonical(value['plan']))
        self.replace_intent(value)
        self.refused_before_effects('EXACT_PLAN')

    def test_qualification_and_campaign_cannot_create_new_allowance(self):
        for key, item in (('campaign', 'new-campaign'), ('related_identity', 'independent-admin'),
                          ('qualifications', {**hosted.FALSE_QUALIFICATIONS, 'independent_accepted': True})):
            with self.subTest(key=key):
                self.replace_intent({**self.value, key: item})
                self.refused_before_effects('CONTEXT')

    def test_base64_size_hash_and_original_manifest_are_bound(self):
        for key, item in (('size', 1), ('sha256', '0' * 64), ('base64', '!!!')):
            value = copy.deepcopy(self.value)
            value['empty_ledger'][key] = item
            with self.subTest(key=key):
                self.replace_intent(value)
                self.refused_before_effects()
        value = copy.deepcopy(self.value)
        value['material_manifest'] = hosted.packed(self.manifest_path.read_bytes() + b' ')
        self.replace_intent(value)
        self.refused_before_effects('ORIGINAL_MANIFEST')

    def test_wrong_checkpoint_or_more_than_one_attempt_refused(self):
        self.replace_intent({**self.value, 'initial_checkpoint': '0' * 64})
        self.refused_before_effects('EMPTY_ORIGINAL_AUTHORITY')
        path = self.base / 'extra-budget.sqlite3'
        state = self.ledger.initialize(path, 2)
        value = copy.deepcopy(self.value)
        value.update(policy=state['policy'], policy_id=state['policy_id'],
            initial_checkpoint=state['checkpoint'], empty_ledger=hosted.packed(path.read_bytes()))
        self.replace_intent(value)
        self.refused_before_effects('EMPTY_ORIGINAL_AUTHORITY')

    def test_reserved_ledger_is_not_replaced_or_refunded(self):
        authority = self.ledger.TrialLedger(self.ledger_path, self.state['policy_id'])
        authority.reserve(self.value['plan'], self.trial, self.state['checkpoint'], 'synthetic-test')
        value = copy.deepcopy(self.value)
        value['empty_ledger'] = hosted.packed(self.ledger_path.read_bytes())
        self.replace_intent(value)
        self.refused_before_effects('EMPTY_ORIGINAL_AUTHORITY')
        self.assertEqual(authority.inspect()['spent'], 1)

    def test_wal_or_custom_sqlite_schema_refuses(self):
        for change in ('PRAGMA journal_mode=WAL', 'CREATE TABLE extra (value TEXT)'):
            path = self.base / ('changed-' + str(len(change)) + '.sqlite3')
            path.write_bytes(hosted.unpacked(self.value['empty_ledger'], hosted.MAX_EMPTY_LEDGER))
            db = sqlite3.connect(path)
            db.execute(change)
            db.commit()
            db.close()
            value = copy.deepcopy(self.value)
            value['empty_ledger'] = hosted.packed(path.read_bytes())
            with self.subTest(change=change):
                self.replace_intent(value)
                self.refused_before_effects()

    def test_untracked_ignored_and_tracked_import_shadows_refuse(self):
        for name in ('scripts/shadow.py', 'scripts/shadow.pyc', 'scripts/cache.ignored'):
            with self.subTest(name=name):
                path = self.repo / name
                path.write_text('raise RuntimeError("must never import")')
                self.refused_before_effects('DIRTY_OR_SHADOW')
                path.unlink()
        with (self.repo / 'scripts/llm_runtime_pilot.py').open('a') as output:
            output.write('\n# changed\n')
        self.refused_before_effects('DIRTY_OR_SHADOW')

    def test_assume_unchanged_and_skip_worktree_refuse(self):
        for option, clear in (('--assume-unchanged', '--no-assume-unchanged'),
                              ('--skip-worktree', '--no-skip-worktree')):
            with self.subTest(option=option):
                self.git('update-index', option, 'scripts/llm_runtime_pilot.py')
                self.refused_before_effects('INDEX_FLAGS')
                self.git('update-index', clear, 'scripts/llm_runtime_pilot.py')

    def test_grafts_replace_partial_and_alternate_history_refuse(self):
        git_dir = self.repo / '.git'
        for name in ('info/grafts', 'objects/info/alternates', 'shallow'):
            with self.subTest(name=name):
                path = git_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.source + '\n' if name == 'shallow' else '')
                self.refused_before_effects()
                path.unlink()
        self.git('update-ref', 'refs/replace/' + self.source, self.intent)
        self.refused_before_effects('REPLACE_REFS')
        self.git('update-ref', '-d', 'refs/replace/' + self.source)
        self.git('config', 'remote.origin.promisor', 'true')
        self.refused_before_effects('PARTIAL_CLONE')

    def test_executable_git_configuration_is_refused(self):
        self.git('config', 'filter.test.clean', 'false')
        self.refused_before_effects('EXECUTABLE_GIT_CONFIG')

    def test_intent_commit_must_only_add_registration(self):
        self.git('reset', '--hard', self.source)
        path = self.repo / hosted.INTENTS / (self.trial + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(hosted.canonical(self.value) + b'\n')
        (self.repo / 'new-code.txt').write_text('source belongs in S, not I')
        self.commit_intent()
        self.refused_before_effects('INTENT_ONLY_ADDITION')

    def test_wrong_before_and_merge_intent_are_refused(self):
        self.event['before'] = self.intent
        self.refused_before_effects('BEFORE_NOT_SOURCE_ANCESTOR')
        tree = self.git('rev-parse', self.intent + '^{tree}').strip()
        merge = self.git('commit-tree', tree, '-p', self.source, '-p', self.intent,
                         '-m', 'synthetic invalid merge intent').strip()
        self.git('reset', '--hard', merge)
        self.event.update(before=self.source, after=merge, head_commit=dict(id=merge))
        self.env.update(GITHUB_SHA=merge, GITHUB_WORKFLOW_SHA=merge)
        self.refused_before_effects('INTENT_SINGLE_PARENT')

    def test_wrong_registration_filename_and_unsafe_members_refuse_before_import(self):
        self.git('reset', '--hard', self.source)
        path = self.repo / hosted.INTENTS / ('2' * 64 + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(hosted.canonical(self.value) + b'\n')
        self.commit_intent()
        with mock.patch.object(hosted, 'modules') as modules:
            self.refused_before_effects('INTENT_PATH_TRIAL')
            modules.assert_not_called()
        value = copy.deepcopy(self.value)
        value['source_hashes'].pop(hosted.LOCK)
        self.replace_intent(value)
        with mock.patch.object(hosted, 'modules') as modules:
            self.refused_before_effects('SOURCE_HASHES')
            modules.assert_not_called()

    def test_register_refuses_sidecar_without_touching_authority(self):
        self.git('reset', '--hard', self.source)
        sidecar = Path(str(self.ledger_path) + '-journal')
        sidecar.write_bytes(b'unknown')
        original = self.ledger_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'LEDGER_SIDECAR_UNKNOWN'):
            hosted.register(self.repo, self.source, self.ledger_path, self.manifest_path, self.trial)
        self.assertEqual(self.ledger_path.read_bytes(), original)
        self.assertEqual(sidecar.read_bytes(), b'unknown')

    def test_source_is_allowed_after_before_without_separate_push(self):
        self.git('reset', '--hard', self.source)
        before = self.source
        (self.repo / 'reviewed-source.txt').write_text('reviewed source committed before intent')
        self.git('add', '.')
        self.git('commit', '-qm', 'source S may be unpublished until atomic R-to-I update')
        self.source = self.git('rev-parse', 'HEAD').strip()
        registration = hosted.register(self.repo, self.source, self.ledger_path,
                                       self.manifest_path, self.trial)
        self.path = Path(registration['registration'])
        self.commit_intent()
        self.event['before'] = before
        _, admitted = hosted.validate(self.repo, self.event, self.env)
        self.assertEqual(admitted['before'], before)
        self.assertEqual(admitted['source_commit'], self.source)

    def test_previous_same_blob_deleted_then_readded_is_refused(self):
        old_blob = self.path.read_bytes()
        self.path.unlink()
        self.git('add', '-A')
        self.git('commit', '-qm', 'delete already published intent')
        parent = self.git('rev-parse', 'HEAD').strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(old_blob)
        self.commit_intent()
        self.event['before'] = parent
        self.refused_before_effects('PRIOR_PUBLISHED_INTENT')

    def test_other_reachable_ref_and_different_filename_are_refused(self):
        self.git('branch', 'synthetic-current', self.intent)
        self.git('checkout', '-q', '-b', 'synthetic-other', self.source)
        path = self.repo / hosted.INTENTS / 'previous-campaign-name.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(hosted.canonical({**self.value, 'trial_id': '2' * 64}) + b'\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'reachable sibling published marker')
        self.git('checkout', '-q', 'synthetic-current')
        self.refused_before_effects('PRIOR_PUBLISHED_INTENT')

    def test_rename_out_of_namespace_does_not_erase_prior_publication(self):
        self.git('branch', 'synthetic-current', self.intent)
        self.git('checkout', '-q', '-b', 'synthetic-other', self.source)
        path = self.repo / hosted.INTENTS / 'malformed.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('even malformed publication is spent\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'previous marker')
        self.git('mv', str(path.relative_to(self.repo)), 'renamed-marker.json')
        self.git('commit', '-qm', 'rename prior marker away')
        self.git('checkout', '-q', 'synthetic-current')
        self.refused_before_effects('PRIOR_PUBLISHED_INTENT')

    def test_setup_failure_consumes_same_job_entry_without_pilot(self):
        with mock.patch.object(hosted.sys, 'version_info', (3, 12, 3)), \
             mock.patch.object(hosted, 'command', side_effect=RuntimeError('synthetic setup failure')) as command, \
             mock.patch.object(hosted, 'download_materials') as download:
            with self.assertRaisesRegex(RuntimeError, 'synthetic setup failure'):
                hosted.execute(self.repo, self.event, self.env)
            self.assertEqual(command.call_count, 1)
            download.assert_not_called()
            with self.assertRaises(FileExistsError):
                hosted.execute(self.repo, self.event, self.env)
            self.assertEqual(command.call_count, 1)
        root = self.runner_temp / 'pon-smollm-hosted-once-v1'
        self.assertTrue((root / 'launch-intent.json').exists())
        terminal = hosted.decode((root / 'execution-terminal.json').read_bytes())
        self.assertFalse(terminal['pilot_started'])
        self.assertFalse(terminal['automatic_retry_allowed'])
        report = hosted.collect(self.repo, self.event, self.env)
        self.assertEqual(report['ledger']['state'], 'NOT_CREATED')
        self.assertTrue(report['ledger']['git_intent_spent'])

    def prepared_collection(self, returned=True):
        root = hosted.work_root(self.env, self.repo)
        hosted.json_once(root / 'execution-terminal.json', dict(pilot_started=True, pilot_returned=returned))
        hosted.write_once(root / 'ledger.sqlite3', hosted.unpacked(self.value['empty_ledger'], hosted.MAX_EMPTY_LEDGER))
        return root

    def test_collect_never_recovers_hot_journal_or_unobserved_exit(self):
        root = self.prepared_collection()
        (root / 'ledger.sqlite3-journal').write_bytes(b'hot-or-unknown')
        original = (root / 'ledger.sqlite3').read_bytes()
        with mock.patch.object(hosted, 'ledger_readback', wraps=hosted.ledger_readback) as readback:
            report = hosted.collect(self.repo, self.event, self.env)
            # One read validates embedded ORIGINAL authority; live DB is never opened.
            self.assertEqual(readback.call_count, 1)
        self.assertEqual(report['ledger']['state'], 'UNKNOWN')
        self.assertIn('SIDECAR', report['ledger']['reason'])
        self.assertEqual((root / 'ledger.sqlite3').read_bytes(), original)
        self.assertEqual((root / 'ledger.sqlite3-journal').read_bytes(), b'hot-or-unknown')
        self.assertFalse((root / 'evidence/ledger.sqlite3').exists())

    def test_collect_unobserved_exit_stays_unknown(self):
        root = self.prepared_collection(returned=False)
        report = hosted.collect(self.repo, self.event, self.env)
        self.assertEqual(report['ledger']['state'], 'UNKNOWN')
        self.assertIn('TERMINAL_UNKNOWN', report['ledger']['reason'])
        self.assertFalse((root / 'evidence/ledger.sqlite3').exists())

    def test_collect_disappearing_file_is_omitted_without_losing_failure_record(self):
        root = self.prepared_collection()
        path = root / 'original-pilot.log'
        path.write_text('original log')
        original_lstat = Path.lstat
        def fail_one(member, *args, **kwargs):
            if member == path:
                raise OSError('synthetic disappearing log')
            return original_lstat(member, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', fail_one):
            report = hosted.collect(self.repo, self.event, self.env)
        omitted = [row for row in report['omitted'] if row['path'] == 'original-pilot.log']
        self.assertEqual(len(omitted), 1)
        self.assertIsNone(omitted[0]['size'])
        self.assertIn('synthetic disappearing log', omitted[0]['reason'])

    def test_collect_corrupt_event_remains_refused_and_preserves_original_error(self):
        hosted.work_root(self.env, self.repo)
        report = hosted.collect(self.repo, {}, self.env,
            event_error=dict(type='ValueError', message='synthetic corrupt event'))
        self.assertIn('validation_error', report)
        self.assertEqual(report['event_error']['message'], 'synthetic corrupt event')
        self.assertEqual(report['ledger']['state'], 'UNKNOWN')

    def test_collect_allowlist_bounds_symlinks_and_large_model_exclusion(self):
        root = self.prepared_collection()
        (root / 'run/loader-reference').mkdir(parents=True)
        (root / 'run/assessment.json').write_text('{}')
        (root / 'original-pilot.log').write_bytes(b'')
        (root / 'run/loader-reference/predictions.json').symlink_to(self.manifest_path)
        with (root / 'run/loader-reference/actual-receipt.json').open('wb') as stream:
            stream.truncate(hosted.MAX_EVIDENCE_FILE + 1)
        (root / 'run/artifact.safetensors').write_bytes(b'excluded')
        (root / 'run/profiler.json').write_bytes(b'excluded')
        (root / 'venv').mkdir()
        (root / 'venv/private').write_bytes(b'excluded')
        report = hosted.collect(self.repo, self.event, self.env)
        paths = {row['path'] for row in report['files']}
        self.assertIn('run/assessment.json', paths)
        self.assertIn('original-pilot.log', paths)
        self.assertEqual(report['ledger']['state'], 'READ_ONLY_SNAPSHOT')
        self.assertFalse((root / 'evidence/run/artifact.safetensors').exists())
        self.assertFalse((root / 'evidence/run/profiler.json').exists())
        self.assertFalse((root / 'evidence/venv').exists())
        self.assertEqual(len(report['omitted']), 2)

    def test_original_pilot_command_has_no_registration_selected_arguments(self):
        seen = []
        def no_execution(root, name, argv, repo, timeout):
            seen.append((name, argv, timeout))
            hosted.json_once(root / (name + '-exit.json'), dict(command=argv, returncode=0))
            return 0
        with mock.patch.object(hosted.sys, 'version_info', (3, 12, 3)), \
             mock.patch.object(hosted, 'command', side_effect=no_execution), \
             mock.patch.object(hosted, 'download_materials'):
            hosted.execute(self.repo, self.event, self.env)
        self.assertEqual([name for name, _, _ in seen], ['venv', 'dependencies', 'installed-metadata', 'original-pilot'])
        pilot = seen[-1][1]
        self.assertIsNone(seen[-1][2])
        self.assertEqual(pilot[-8:], ['--backend', 'cpu', '--threads', '4', '--steps', '10',
                                     '--exit-observation-profile', 'strict-v1'])
        self.assertNotIn('trial-ledger-init', pilot)
        dependencies = seen[1][1]
        self.assertIn('--require-hashes', dependencies)
        self.assertIn('--only-binary=:all:', dependencies)
        self.assertEqual(dependencies[-1], str(self.repo / hosted.LOCK))

    def test_old_parent_only_timeout_leaves_real_grandchild_alive(self):
        # A bounded two-process counterexample, not a model execution. The
        # grandchild exits on its own after observing the supervisor's death.
        marker = self.base / 'grandchild-survived.json'
        ready = self.base / 'grandchild-pid.txt'
        child = self.base / 'synthetic-grandchild.py'
        child.write_text('import json,os,pathlib,sys,time\n'
            'parent=int(sys.argv[1]); deadline=time.monotonic()+4\n'
            'while time.monotonic()<deadline:\n'
            ' try: os.kill(parent,0)\n'
            ' except ProcessLookupError:\n'
            '  p=pathlib.Path(sys.argv[2]); t=p.with_suffix(".partial")\n'
            '  t.write_text(json.dumps(dict(parent=parent,child=os.getpid(),parent_gone=True))); t.replace(p)\n'
            '  break\n'
            ' time.sleep(0.02)\n')
        parent = self.base / 'synthetic-supervisor.py'
        parent.write_text('import os,pathlib,subprocess,sys,time\n'
            'p=subprocess.Popen([sys.executable,sys.argv[1],str(os.getpid()),sys.argv[2]])\n'
            'pathlib.Path(sys.argv[3]).write_text(str(p.pid))\n'
            'time.sleep(5)\n')
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                subprocess.run([sys.executable, '-I', '-S', '-B', str(parent), str(child),
                    str(marker), str(ready)], timeout=1, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 4
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), 'synthetic parent did not launch its child')
            self.assertTrue(marker.exists(), 'original timeout counterexample did not complete')
            self.assertTrue(json.loads(marker.read_text())['parent_gone'])
        finally:
            # Only our recorded synthetic child is eligible for bounded cleanup.
            if ready.exists() and not marker.exists():
                try:
                    os.kill(int(ready.read_text()), 9)
                except ProcessLookupError:
                    pass

    def test_failed_pilot_exit_and_real_child_log_names_are_preserved(self):
        def no_execution(root, name, argv, repo, timeout):
            code = 17 if name == 'original-pilot' else 0
            hosted.json_once(root / (name + '-exit.json'), dict(command=argv, returncode=code))
            if code:
                child = root / 'run/loader-1thread'
                child.mkdir(parents=True)
                (child / 'process.log').write_text('synthetic original traceback\n')
                raise hosted.Refused('HOSTED_COMMAND_EXIT:original-pilot:17')
            return 0
        with mock.patch.object(hosted.sys, 'version_info', (3, 12, 3)), \
             mock.patch.object(hosted, 'command', side_effect=no_execution), \
             mock.patch.object(hosted, 'download_materials'):
            with self.assertRaisesRegex(ValueError, 'original-pilot:17'):
                hosted.execute(self.repo, self.event, self.env)
        root = self.runner_temp / 'pon-smollm-hosted-once-v1'
        terminal = hosted.decode((root / 'execution-terminal.json').read_bytes())
        self.assertTrue(terminal['pilot_started'])
        self.assertTrue(terminal['pilot_returned'])
        self.assertEqual(terminal['outcome'], 'failed')
        report = hosted.collect(self.repo, self.event, self.env)
        self.assertIn('run/loader-1thread/process.log', {row['path'] for row in report['files']})
        self.assertEqual((root / 'evidence/run/loader-1thread/process.log').read_text(),
                         'synthetic original traceback\n')

    def test_workflow_first_gate_pinned_actions_read_only_and_always_collect(self):
        raw = (SOURCE / hosted.WORKFLOW).read_text()
        self.assertEqual(hosted.REF, 'refs/heads/fix/chain-model-owner-hosted-once-20261105')
        self.assertIn('      - ' + hosted.REF.removeprefix('refs/heads/'), raw)
        self.assertNotIn('workflow_dispatch', raw)
        self.assertNotIn('pull_request:', raw)
        self.assertNotIn('secrets.', raw)
        self.assertIn('contents: read', raw)
        self.assertIn('fetch-depth: 0', raw)
        self.assertIn('persist-credentials: false', raw)
        self.assertIn('timeout-minutes: 300', raw)
        self.assertIn('cancel-in-progress: false', raw)
        self.assertIn('actions/checkout@11d5960a326750d5838078e36cf38b85af677262', raw)
        self.assertLess(raw.index('llm_hosted_once.py validate'), raw.index('actions/setup-python@'))
        self.assertEqual(raw.count('if: always()'), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
