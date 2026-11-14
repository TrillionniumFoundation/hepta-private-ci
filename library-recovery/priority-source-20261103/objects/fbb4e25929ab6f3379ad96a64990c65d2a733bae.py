"""Static source-only route/scope regression, no workflow execution or builds."""
from pathlib import Path
import fnmatch
import hashlib
import subprocess
import unittest
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import yaml

ROOT = Path(__file__).resolve().parent
CASES = [
    ('taskflow-pending-cap', '/workspace/shared/taskflow-observation-publish', 'ddc265399cce01ef92f803604a2328f2392f7277'),
    ('ui-license-identity', '/workspace/shared/ui-product-foundation', 'e5e5295b13e4d318a9140ecd8848dbbf19ca4d40'),
]

def sources(repo, sha):
    names = subprocess.check_output(['git', '-C', repo, 'ls-tree', '-r', '--name-only', sha, '.github/workflows'], text=True).splitlines()
    return {name: subprocess.check_output(['git', '-C', repo, 'show', f'{sha}:{name}'], text=True) for name in names if name.endswith(('.yml', '.yaml'))}

def triggered(text, branch):
    events = yaml.load(text, Loader=yaml.BaseLoader)['on']
    if isinstance(events, str):
        return events == 'push'
    if isinstance(events, list):
        return 'push' in events
    if 'push' not in events:
        return False
    push = events['push'] or {}
    if 'tags' in push and 'branches' not in push:
        return False
    patterns = push.get('branches', ['**'])
    selected = False
    for pattern in patterns:
        if pattern.startswith('!'):
            if fnmatch.fnmatchcase(branch, pattern[1:]): selected = False
        elif fnmatch.fnmatchcase(branch, pattern): selected = True
    return selected and not any(fnmatch.fnmatchcase(branch, p) for p in push.get('branches-ignore', []))

class StaticRouting(unittest.TestCase):
    def test_only_fixed_diagnostic_push_selected(self):
        for kind, repo, sha in CASES:
            with self.subTest(kind=kind):
                baseline = sources(repo, sha)
                branch = 'dot/' + kind + '-diagnostic-20261006'
                # Conservatively ignore path filters: no ordinary workflow may
                # even admit this branch, regardless of files or new-branch diff.
                self.assertEqual([p for p,s in baseline.items() if triggered(s, branch)], [])
                proposed = (ROOT/kind/'candidate/.github/workflows'/f'{kind}-diagnostic.yml').read_text()
                self.assertTrue(triggered(proposed, branch))
                for other in ['main', 'feature/ordinary', 'feature/full-ci-check', branch+'-other', 'diagnostic/other', 'work/automation-taskflow-durable-causal-chain']:
                    self.assertFalse(triggered(proposed, other), other)
                doc = yaml.load(proposed, Loader=yaml.BaseLoader)
                self.assertEqual(set(doc['on']), {'push'})
                self.assertEqual(doc['jobs']['diagnostic']['if'], f"github.event_name == 'push' && github.ref == 'refs/heads/{branch}'")
                self.assertNotIn('strategy', doc['jobs']['diagnostic'])
                self.assertEqual(doc['permissions'], {'contents': 'read'})
                self.assertIn('ref: ${{ github.sha }}', proposed)
                self.assertIn('persist-credentials: false', proposed)
                self.assertNotIn('actions/cache', proposed)
                self.assertNotIn('workflow_call', proposed)
                self.assertNotIn('workflow_dispatch', proposed)
                self.assertNotIn('pull_request:', proposed)
                self.assertIn('retention-days: 7', proposed)
                self.assertIn('if: always()', proposed)

    def test_additive_patch_preserves_every_existing_gate(self):
        for kind,repo,sha in CASES:
            baseline=sources(repo,sha)
            patch=(ROOT/f'{kind}-ci.patch').read_text()
            path=f'.github/workflows/{kind}-diagnostic.yml'
            self.assertNotIn(path, baseline)
            self.assertEqual(patch.count('diff --git '),1)
            self.assertIn('new file mode 100644',patch)
            self.assertNotIn('\n- ',patch)
            # Exact existing bytes imply unchanged default/PR/reusable routes,
            # including inherited caller event semantics and job predicates.
            self.assertEqual(set(p.relative_to(ROOT/kind/'candidate').as_posix() for p in (ROOT/kind/'candidate').rglob('*') if p.is_file()), {path})

    def test_commands_and_evidence_scope(self):
        task=(ROOT/'taskflow-pending-cap/candidate/.github/workflows/taskflow-pending-cap-diagnostic.yml').read_text()
        for group in ['pending_capacity_tests', 'shutdown_lifetime_tests']:
            self.assertIn(f"--minimum-tests 3 --timeout-seconds \"$budget\" -- just test --locked -p codex-app-server-client --lib -E 'test(remote::{group})'",task)
        self.assertEqual(task.count('CARGO_TARGET_DIR:'),1)
        self.assertNotIn('codex-hepta-agentd',task)
        ui=(ROOT/'ui-license-identity/candidate/.github/workflows/ui-license-identity-diagnostic.yml').read_text()
        self.assertIn('node-version: 22',ui)
        self.assertIn('--test-reporter=junit',ui)
        self.assertIn("counts['tests'] == 3",ui)
        self.assertNotIn('artifact-lifetime',ui)
        self.assertNotIn('cargo ',ui)
        for kind,_,_ in CASES:
            doc=yaml.load((ROOT/kind/'candidate/.github/workflows'/f'{kind}-diagnostic.yml').read_text(),Loader=yaml.BaseLoader)
            for step in doc['jobs']['diagnostic']['steps']:
                if 'run' in step:
                    subprocess.run(['bash','-n'],input=step['run'],text=True,check=True)

    def test_ui_count_checker_rejects_incomplete_or_wrong_evidence(self):
        path=ROOT/'ui-license-identity/candidate/.github/workflows/ui-license-identity-diagnostic.yml'
        doc=yaml.load(path.read_text(),Loader=yaml.BaseLoader)
        step=next(s for s in doc['jobs']['diagnostic']['steps'] if s.get('name','').startswith('Require exactly'))
        program=step['run'].split("python3 - <<'PYCOUNT'\n",1)[1].rsplit('PYCOUNT',1)[0]
        compile(program,'count-checker','exec')
        names=[
            'editing a shipped license invalidates source identity and restoring it recovers identity',
            'adding and removing nested shipped licenses changes the complete source inventory',
            'missing shipped-license directory fails closed',
        ]
        for variant in ['pass','two','wrong-name','skipped','failure','command-failed','changed-source']:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'ui-license-identity-records';out.mkdir()
                identity={'commit':'a'*40,'tree':'b'*40,'dirty':False}
                record={'status':'passed','exit_code':0,'source_sha':'a'*40,'before':identity,'after':identity.copy()}
                cases=names[:2] if variant=='two' else names.copy()
                if variant=='wrong-name':cases[0]='unrelated regression'
                tree=ET.Element('testsuites');suite=ET.SubElement(tree,'testsuite')
                for name in cases: ET.SubElement(suite,'testcase',name=name)
                if variant in ['skipped','failure']: ET.SubElement(suite[0],variant)
                if variant=='command-failed':record.update(status='failed',exit_code=1)
                if variant=='changed-source':record['after']['dirty']=True
                (out/'command.json').write_text(json.dumps(record))
                ET.ElementTree(tree).write(out/'tests.xml')
                result=subprocess.run(['python3','-c',program],env={**os.environ,'RUNNER_TEMP':tmp,'SOURCE_SHA':'a'*40},capture_output=True,text=True)
                self.assertEqual(result.returncode==0,variant=='pass',result.stderr)
                self.assertTrue((out/'counts.json').exists())

if __name__ == '__main__': unittest.main(verbosity=2)
