"""Static/identity checks only; never execute a model or load its shared library."""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(candidate, baseline, roots_file, repository_root, output):
    roots = json.loads(Path(roots_file).read_text())
    old, new = [yaml.safe_load(Path(p).read_text()) for p in (baseline, candidate)]
    assert sha(baseline) == 'bac8820cb23ff6637c4a692027f2e3d953b00427349567ff42808fc6785e13a4'
    restored = copy.deepcopy(new)
    job = restored['jobs']['financial-bp-and-bptt']
    prefix = 'tools/hcsn/hx_two_layer_boundary_r16_20261101'
    restored['on']['pull_request']['paths'].remove(prefix+'/**')
    assert job['env'].pop('TWO_LAYER_ROOT') == prefix
    assert job['env'].pop('TWO_LAYER_PROTOCOL_SHA256') == 'da07c580e258f51517f124d6d7b902a8ae3c6700fb58cb96948c18447c740ad7'
    steps = job['steps']
    checkout = steps[0]
    checkout['with']['sparse-checkout'] = ''.join(line for line in checkout['with']['sparse-checkout'].splitlines(True) if line.strip() != prefix)
    runtime = next(row for row in steps if row.get('id') == 'runtime')
    removed = [line for line in runtime['run'].splitlines(True) if 'two_layer' in line]
    assert len(removed) == 3
    runtime['run'] = ''.join(line for line in runtime['run'].splitlines(True) if 'two_layer' not in line)
    added = [row for row in steps if row.get('id') in ('two_layer_audit', 'two_layer_training') or row['name'] == 'Independently check both routes and the full update history']
    assert len(added) == 3
    job['steps'] = [row for row in steps if row not in added]
    assert restored == old, 'An existing workflow field changed'
    original_entrypoints = [row for row in old['jobs']['financial-bp-and-bptt']['steps'] if 'run' in row and '"$HCSN_PYTHON" -B' in row['run']]
    assert len(original_entrypoints) == 8
    job = new['jobs']['financial-bp-and-bptt']
    assert new['permissions'] == {'contents': 'read'}
    assert job['timeout-minutes'] == 20
    assert not any('runner.' in str(value) for value in job['env'].values())
    cli, bash = [], []
    for step in job['steps']:
        assert 'continue-on-error' not in step
        if 'run' not in step:
            continue
        script = step['run']
        assert script.startswith('set -euo pipefail\n')
        check = subprocess.run(['/bin/bash', '-n'], input=script, text=True, capture_output=True)
        assert check.returncode == 0, check.stderr
        bash.append({'name': step['name'], 'exit_code': check.returncode})
        match = re.search(r'"\$HCSN_PYTHON" -B "\$([A-Z_]+)/([^"/]+)"', script)
        if not match:
            continue
        root_name, filename = match.groups()
        path = Path(roots[root_name])/filename
        parsed = ast.parse(path.read_text(), filename=str(path))
        declared = {node.args[0].value for node in ast.walk(parsed)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'add_argument' and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
        supplied = set(re.findall(r'(?m)^\s+(--[a-z0-9-]+) ', script))
        assert declared == supplied, (filename, declared, supplied)
        target = re.search(r'--output "([^"\n]+)"', script).group(1)
        assert target.startswith('$HCSN_RESULTS/')
        cli.append({'script': root_name+'/'+filename, 'source_sha256': sha(path), 'flags': sorted(supplied), 'output': target})
    assert len(cli) == 11 and len(bash) == 14
    assert len({row['output'] for row in cli}) == 11
    checker = added[2]
    assert "steps.two_layer_audit.outcome == 'success'" in checker['if'] and "steps.two_layer_training.outcome == 'success'" in checker['if']
    runtime = next(row for row in job['steps'] if row.get('id') == 'runtime')
    python_source = runtime['run'].split("python3.12 - <<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
    compile(python_source, '<workflow-hash-preflight>', 'exec')
    with tempfile.TemporaryDirectory(prefix='hcsn-two-layer-workflow-check-') as temporary:
        env = {**os.environ, **{name: str(value) for name, value in job['env'].items()}, **roots}
        env['HCSN_RESULTS'] = temporary
        positive = subprocess.run([sys.executable, '-B', '-c', python_source], cwd=repository_root, env=env, text=True, capture_output=True)
        assert positive.returncode == 0, positive.stderr
        bindings = json.loads((Path(temporary)/'source-bindings.json').read_text())
        assert len(bindings['sha256']) == 10
        env['TWO_LAYER_PROTOCOL_SHA256'] = '0'*64
        negative = subprocess.run([sys.executable, '-B', '-c', python_source], cwd=repository_root, env=env, text=True, capture_output=True)
        assert negative.returncode != 0 and 'Frozen identity mismatch' in negative.stderr
    source_seals = []
    for variable, protocol_name in (
        ('ADAPTER_ROOT', 'ADAPTER_PROTOCOL.json'),
        ('RECURRENT_ROOT', 'RECURRENT_PROTOCOL.json'),
        ('ASSET_ROOT', 'ASSET_PROTOCOL.json'),
        ('TWO_LAYER_ROOT', 'TWO_LAYER_PROTOCOL.json'),
        ('FINANCIAL_ROOT', 'RECOVERY_PROTOCOL_V1.json'),
    ):
        directory = Path(roots[variable]); protocol = json.loads((directory/protocol_name).read_text())
        for name, digest in protocol['source_sha256'].items():
            assert sha(directory/name) == digest
            source_seals.append({'root': variable, 'file': name, 'sha256': digest})
    receipt = {
        'schema': 'hcsn.two-layer-workflow-static-check.v1', 'passed': True,
        'workflow_sha256': sha(candidate), 'baseline_sha256': sha(baseline),
        'validator_sha256': sha(__file__), 'existing_eight_entrypoints_unchanged': True,
        'bash_syntax': bash, 'cli_identity_and_outputs': cli,
        'actual_embedded_preflight': {'positive_exit_code': positive.returncode,
            'identities_checked': len(bindings['sha256']), 'wrong_protocol_exit_code': negative.returncode,
            'local_fixture_commit': bindings['head']},
        'nested_source_seals': source_seals, 'financial_calls': 0, 'model_calls': 0,
        'scope': 'Static syntax, real embedded hash preflight, exact CLI signatures and preserved workflow structure only. No remote Actions or candidate runtime result.'}
    with Path(output).open('x') as target:
        json.dump(receipt, target, indent=2); target.write('\n')
    print(json.dumps({'passed': True, 'workflow_sha256': sha(candidate), 'bash_blocks': len(bash), 'entrypoints': len(cli), 'nested_sources': len(source_seals), 'output': str(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('candidate', 'baseline', 'roots-file', 'repository-root', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    main(args.candidate, args.baseline, args.roots_file, args.repository_root, args.output)
