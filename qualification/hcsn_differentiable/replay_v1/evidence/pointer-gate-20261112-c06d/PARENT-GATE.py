import json, os, re, subprocess
from pathlib import Path
pointer = json.loads(Path('qualification/hcsn_differentiable/replay_v1/CPU-ARTIFACT.json').read_bytes())
assert pointer['schema'] == 'hcsn-cpu-replay-artifact-pointer-v1'
assert pointer['status'] == 'FROZEN', 'HOLD: immutable archive publication is not yet observed; zero model calls'
assert re.fullmatch('[0-9a-f]{40}', pointer['commit'])
assert pointer['archive'] == {'bytes': 11397159, 'sha256': '37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75'}
source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
out = Path(os.environ['RUNNER_TEMP']) / 'hcsn-cpu-source-identity.json'
out.write_text(json.dumps({'source_commit': source, 'artifact_pointer': pointer}, indent=2) + '\n')
with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
    stream.write('commit=' + pointer['commit'] + '\n')
