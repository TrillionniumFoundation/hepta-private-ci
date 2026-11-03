"""Focused GitHub context availability regression, not full actionlint."""
from pathlib import Path
import difflib, hashlib, os, re, subprocess, tempfile, time, unittest
import yaml
ROOT=Path(__file__).resolve().parent
BASE=Path('/workspace/shared/focused-candidate-ci-proposals/composition/taskflow/.github/workflows/taskflow-pending-cap-diagnostic.yml')
UI=Path('/workspace/shared/focused-candidate-ci-proposals/composition/ui/.github/workflows/ui-license-identity-diagnostic.yml')
SOURCE='https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability'
JOB_ENV=set('github needs strategy matrix vars secrets inputs'.split())
STEP=set('github needs strategy matrix job runner env vars secrets steps inputs'.split())

def violations(text):
    result=[]
    def walk(obj,path=()):
        if isinstance(obj,dict):
            for k,v in obj.items():walk(v,path+(k,))
        elif isinstance(obj,list):
            for i,v in enumerate(obj):walk(v,path+(i,))
        elif isinstance(obj,str):
            exprs=re.findall(r'\$\{\{(.*?)\}\}',obj,re.S)
            if path[-1:] == ('if',) and not exprs:exprs=[obj]
            if not exprs:return
            if path[:1]==('concurrency',):allowed={'github','inputs','vars'}
            elif len(path)>2 and path[0]=='jobs' and path[2]=='env':allowed=JOB_ENV
            elif len(path)==3 and path[0]=='jobs' and path[2]=='if':allowed={'github','needs','vars','inputs'}
            elif len(path)>4 and path[0]=='jobs' and path[2]=='steps':
                assert path[4] in ['if','env','with','run','name','timeout-minutes','working-directory'],path
                allowed=STEP-({'secrets'} if path[4]=='if' else set())
            else:raise AssertionError(('unaudited expression location',path))
            for expr in exprs:
                expr=re.sub(r"'(?:[^']|'')*'",'',expr)
                used=set(re.findall(r'(?<![.A-Za-z_0-9])([A-Za-z_][A-Za-z_0-9]*)\.',expr))
                if used-allowed:result.append((path,used-allowed))
    walk(yaml.load(text,Loader=yaml.BaseLoader));return result

class ContextRegression(unittest.TestCase):
    def test_reproduces_original_admission_error(self):
        self.assertEqual(violations(BASE.read_text()),[(('jobs','diagnostic','env','CARGO_TARGET_DIR'),{'runner'})])
    def test_all_corrected_and_ui_context_locations_allowed(self):
        self.assertEqual(violations((ROOT/'workflow.yml').read_text()),[])
        self.assertEqual(violations(UI.read_text()),[])
    def test_only_minimal_reviewed_correction(self):
        before=BASE.read_text();after=(ROOT/'workflow.yml').read_text()
        expected=before.replace('      CARGO_TARGET_DIR: ${{ runner.temp }}/taskflow-pending-cap-target\n','').replace('        run: echo "NATIVE_DEADLINE=$(( $(date +%s) + 3000 ))" >> "$GITHUB_ENV"','        run: |\n          echo "NATIVE_DEADLINE=$(( $(date +%s) + 3000 ))" >> "$GITHUB_ENV"\n          echo "CARGO_TARGET_DIR=$RUNNER_TEMP/taskflow-pending-cap-target" >> "$GITHUB_ENV"')
        self.assertEqual(after,expected)
        patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/.github/workflows/taskflow-pending-cap-diagnostic.yml',tofile='b/.github/workflows/taskflow-pending-cap-diagnostic.yml'))
        self.assertEqual(patch,(ROOT/'candidate.patch').read_text())
        self.assertEqual(hashlib.sha256(patch.encode()).hexdigest(),'bd16dc482acdc21137dc930b9592262d4e20e72e5f52b8719278bc0012a1b7b6')
    def test_first_shell_exports_identical_target_before_checkout(self):
        job=yaml.load((ROOT/'workflow.yml').read_text(),Loader=yaml.BaseLoader)['jobs']['diagnostic']
        self.assertNotIn('CARGO_TARGET_DIR',job['env'])
        self.assertIn('actions/checkout@',job['steps'][1]['uses'])
        with tempfile.TemporaryDirectory(prefix='context evidence ') as temp:
            envfile=Path(temp)/'github-env';start=int(time.time())
            subprocess.run(['bash','-e','-c',job['steps'][0]['run']],env={**os.environ,'RUNNER_TEMP':temp,'GITHUB_ENV':str(envfile)},check=True)
            fields=dict(line.split('=',1) for line in envfile.read_text().splitlines())
            self.assertEqual(fields['CARGO_TARGET_DIR'],temp+'/taskflow-pending-cap-target')
            self.assertGreaterEqual(int(fields['NATIVE_DEADLINE']),start+3000)
            self.assertLessEqual(int(fields['NATIVE_DEADLINE']),int(time.time())+3000)
        for step in job['steps']:
            if 'run' in step:subprocess.run(['bash','-n'],input=step['run'],text=True,check=True)
if __name__=='__main__':unittest.main(verbosity=2)
