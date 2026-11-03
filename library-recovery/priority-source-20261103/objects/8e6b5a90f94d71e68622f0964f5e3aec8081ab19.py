#!/usr/bin/env python3
"""Execute qualification resolver/identity shell blocks without GitHub or network.

The extractor supports this workflow's literal step/run layout only. It is a
small test harness, not a YAML parser or an Actions/CodeQL qualification oracle.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/authbus-authority-qualification.yml'
HEAD = 'a' * 40
BASE = 'b' * 40
TRIGGER = 'c' * 40


def step_text(name):
    lines = WORKFLOW.read_text().splitlines()
    marker = '      - name: ' + name
    starts = [i for i, line in enumerate(lines) if line == marker]
    if len(starts) != 1:
        raise AssertionError('expected one literal workflow step: ' + name)
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith('        ')), len(lines))
    return '\n'.join(lines[start:end])


def literal_field(text, indentation, name):
    prefix = ' ' * indentation + name + ': '
    values = [line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)]
    if len(values) != 1:
        raise AssertionError('expected one literal field: ' + name)
    return values[0]


def shell(name):
    text = step_text(name)
    before, marker, block = text.partition('        run: |\n')
    if not marker or any(line.strip() and not line.startswith('          ') for line in block.splitlines()):
        raise AssertionError('unsupported literal run layout: ' + name)
    return '\n'.join(line[10:] if line.strip() else '' for line in block.splitlines())


def run_step(name, values, cwd=None):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / 'output'
        environment = {**os.environ, 'GITHUB_OUTPUT': str(output), **values}
        result = subprocess.run(['bash', '-c', shell(name)], env=environment, cwd=cwd,
                                text=True, capture_output=True, timeout=20)
        outputs = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
        return result, outputs


def event(name='pull_request', **overrides):
    return {'EVENT_NAME': name, 'EVENT_HEAD': HEAD, 'EVENT_BASE': BASE,
            'EVENT_PR': '1272', 'TRIGGER_SHA': TRIGGER,
            'TRIGGER_REF': 'refs/heads/main', **overrides}


class TriggerIdentityTests(unittest.TestCase):
    def test_pr_uses_event_head_and_base(self):
        result, outputs = run_step('Resolve immutable candidate', event(INPUT_PR='other'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {'head': HEAD, 'base': BASE, 'kind': 'exact_head'})

    def test_manual_and_push_main_use_own_event_sha(self):
        for name in ['workflow_dispatch', 'push']:
            result, outputs = run_step('Resolve immutable candidate', event(name, INPUT_PR='999', EVENT_HEAD='d' * 40))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(outputs, {'head': TRIGGER, 'base': '', 'kind': 'main_head'})

    def test_manual_and_push_foreign_refs_rejected_before_checkout(self):
        for name in ['workflow_dispatch', 'push']:
            for ref in ['refs/heads/feature', 'refs/tags/main', 'refs/pull/1272/merge', '']:
                result, outputs = run_step('Resolve immutable candidate', event(name, TRIGGER_REF=ref))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs, {})

    def test_unknown_event_and_malformed_identity_rejected(self):
        for values in [event('pull_request_target'), event('workflow_run'), event(EVENT_HEAD=''),
                       event(EVENT_BASE=''), event(EVENT_HEAD='main'), event('workflow_dispatch', TRIGGER_SHA='$(false)')]:
            result, outputs = run_step('Resolve immutable candidate', values)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs, {})

    def test_merge_resolver_accepts_only_actual_pr_event(self):
        result, outputs = run_step('Resolve pull request identity', event())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {'pr': '1272', 'head': HEAD, 'base': BASE})
        for values in [event('workflow_dispatch', INPUT_PR='1272'), event('push'), event(EVENT_PR='0'), event(EVENT_PR='../1'), event(EVENT_BASE='')]:
            result, outputs = run_step('Resolve pull request identity', values)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs, {})

    def test_gate_rejects_missing_failed_or_skipped_required_lanes(self):
        for name, merge in [('pull_request', 'success'), ('push', 'skipped'), ('workflow_dispatch', 'skipped')]:
            result, _ = run_step('Reject incomplete required jobs', event(name, SOURCE_RESULT='success', MERGE_RESULT=merge))
            self.assertEqual(result.returncode, 0, result.stderr)
        for name, source, merge in [('pull_request','success','skipped'), ('pull_request','success','failure'),
                                   ('workflow_dispatch','failure','skipped'), ('workflow_dispatch','success','success'),
                                   ('workflow_run','success','skipped')]:
            result, _ = run_step('Reject incomplete required jobs', event(name, SOURCE_RESULT=source, MERGE_RESULT=merge))
            self.assertNotEqual(result.returncode, 0)

    def test_checkout_steps_are_split_by_actual_event_scope(self):
        for name in ['Checkout exact PR source', 'Checkout PR candidate controller']:
            text = step_text(name)
            self.assertEqual(literal_field(text, 8, "if"), "github.event_name == 'pull_request'")
            self.assertEqual(literal_field(text, 10, 'ref'), '${{ github.event.pull_request.head.sha }}')
            self.assertIn('          persist-credentials: false', text)
        for name in ['Checkout workflow main source', 'Checkout workflow main controller']:
            text = step_text(name)
            self.assertEqual(literal_field(text, 8, "if"), "github.event_name == 'push' || github.event_name == 'workflow_dispatch'")
            self.assertEqual(literal_field(text, 10, 'ref'), '${{ github.sha }}')
            self.assertIn('          persist-credentials: false', text)
        text = WORKFLOW.read_text()
        self.assertNotIn('pull_request_number', text)
        self.assertNotIn('INPUT_PR', text)
        self.assertNotIn('curl ', text)
        self.assertRegex(text, r"synthetic-merge:\n    name: [^\n]+\n    if: github.event_name == 'pull_request'\n")

    def test_event_context_and_identity_checks_cannot_be_rebound_or_skipped(self):
        expected = {
            'Resolve immutable candidate': {'EVENT_NAME': '${{ github.event_name }}',
                'EVENT_HEAD': '${{ github.event.pull_request.head.sha }}',
                'EVENT_BASE': '${{ github.event.pull_request.base.sha }}',
                'TRIGGER_SHA': '${{ github.sha }}', 'TRIGGER_REF': '${{ github.ref }}'},
            'Verify source identity': {'EXPECTED_HEAD': '${{ steps.resolve.outputs.head }}'},
            'Verify controller identity': {'EXPECTED_HEAD': '${{ needs.source-head.outputs.candidate-sha }}'},
            'Reject incomplete required jobs': {'SOURCE_RESULT': '${{ needs.source-head.result }}',
                'MERGE_RESULT': '${{ needs.synthetic-merge.result }}', 'EVENT_NAME': '${{ github.event_name }}'},
        }
        for step, fields in expected.items():
            text = step_text(step)
            self.assertFalse(any(line.startswith('        if:') for line in text.splitlines()))
            for field, value in fields.items():
                self.assertEqual(literal_field(text, 10, field), value)
        text = WORKFLOW.read_text()
        self.assertRegex(text, r"qualification-gate:\n    name: [^\n]+\n    if: always\(\)\n")

    def test_identity_validation_precedes_candidate_execution(self):
        text = WORKFLOW.read_text()
        for earlier, later in [('Resolve immutable candidate', 'Checkout exact PR source'),
                               ('Resolve immutable candidate', 'Checkout workflow main source'),
                               ('Checkout exact PR source', 'Verify source identity'),
                               ('Checkout workflow main source', 'Verify source identity'),
                               ('Verify source identity', 'Bind commit-neutral AuthBus source map'),
                               ('Reject incomplete required jobs', 'Checkout PR candidate controller'),
                               ('Reject incomplete required jobs', 'Checkout workflow main controller'),
                               ('Checkout PR candidate controller', 'Verify controller identity'),
                               ('Checkout workflow main controller', 'Verify controller identity'),
                               ('Verify controller identity', 'Assemble sole readiness manifest')]:
            self.assertLess(text.index('      - name: ' + earlier + '\n'),
                            text.index('      - name: ' + later + '\n'))
        gate = text[text.index('  qualification-gate:\n'):]
        needs = literal_field(gate, 4, 'needs').strip('[]')
        self.assertTrue({'source-head', 'synthetic-merge'} <= {name.strip() for name in needs.split(',')})

    def test_real_git_source_and_controller_identity_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git','init','-q'],cwd=root,check=True)
            (root/'source').write_text('reviewed\n')
            subprocess.run(['git','add','source'],cwd=root,check=True)
            environment={**os.environ,'GIT_AUTHOR_NAME':'Fixture','GIT_AUTHOR_EMAIL':'fixture@example.invalid',
                         'GIT_COMMITTER_NAME':'Fixture','GIT_COMMITTER_EMAIL':'fixture@example.invalid'}
            subprocess.run(['git','commit','-qm','fixture'],cwd=root,env=environment,check=True)
            commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            for name in ['Verify source identity','Verify controller identity']:
                values={'EXPECTED_HEAD':commit,'EXPECTED_BASE':'','CANDIDATE_KIND':'main_head'}
                result,_=run_step(name,values,root)
                self.assertEqual(result.returncode,0,result.stderr)
                result,_=run_step(name,{**values,'EXPECTED_HEAD':'0'*40},root)
                self.assertNotEqual(result.returncode,0)
                (root/'untracked').write_text('drift')
                result,_=run_step(name,values,root)
                self.assertNotEqual(result.returncode,0)
                (root/'untracked').unlink()

    def test_real_merge_parent_and_tree_guards_reject_stale_pr_reruns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {**os.environ, 'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
                           'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, env=environment, text=True).strip()
            git('init', '-q', '-b', 'main')
            (root / 'initial').write_text('initial')
            git('add', 'initial'); git('commit', '-qm', 'initial')
            initial = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'pr')
            (root / 'pr').write_text('pr')
            git('add', 'pr'); git('commit', '-qm', 'pr')
            head = git('rev-parse', 'HEAD')
            git('checkout', '-q', 'main')
            (root / 'main').write_text('main')
            git('add', 'main'); git('commit', '-qm', 'main')
            base = git('rev-parse', 'HEAD')
            git('merge', '--no-ff', '-qm', 'merge', 'pr')
            result, _ = run_step('Verify deterministic merge identity', {'EXPECTED_HEAD': head, 'EXPECTED_BASE': base}, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            for stale_head, stale_base in [(initial, base), (head, initial)]:
                result, _ = run_step('Verify deterministic merge identity', {'EXPECTED_HEAD': stale_head, 'EXPECTED_BASE': stale_base}, root)
                self.assertNotEqual(result.returncode, 0)
            (root / 'substitution').write_text('unreviewed tree')
            git('add', 'substitution')
            wrong_tree = git('write-tree')
            forged_merge = git('commit-tree', wrong_tree, '-p', base, '-p', head, '-m', 'wrong tree fixture')
            git('reset', '--hard', '-q', forged_merge)
            result, _ = run_step('Verify deterministic merge identity', {'EXPECTED_HEAD': head, 'EXPECTED_BASE': base}, root)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__': unittest.main()
