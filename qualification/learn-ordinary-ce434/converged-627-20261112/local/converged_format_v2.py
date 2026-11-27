from pathlib import Path
import ast, hashlib, json, os, subprocess, time

original = Path('/home/qian-qi/hepta-learn-ordinary-ce434-20261111')
repo = Path('/home/qian-qi/hepta-learn-converged-ce434-20261112-format-v2')
out = Path('/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/converged-627-format-v2')
fixed = '627dd30bd9523755c93e1ed8bbbf0b359dd7bea9'
fixed_tree = 'b3b9db8009f1f29e25ceda00cbc8c09acebcca1c'
parent = '1da47b9b79c4dfeea44eddc4596e747da0bbef84'
base = '7832eef16022f1af233e2a48ef46fb1ac61dcd8f'
branch = 'codex/learn-converged-formatted-ce434-20261112-v2'
paths_sha256 = 'b02d238631d8ad26f322eefa3b417a8a6a2154d678268472c242c8e8daea0153'
env = dict(os.environ)
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['PATH'] = '/home/qian-qi/hepta-learn-ce434-tools/uv-venv/bin:/home/qian-qi/.local/bin:/home/qian-qi/.cargo/bin:' + env['PATH']

def git(*args, cwd=None):
    return subprocess.check_output(['git', *args], cwd=cwd or repo, env=env, text=True).strip()

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

if repo.exists() or out.exists():
    raise RuntimeError('dedicated format destination already exists')
if subprocess.run(['git', 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch], cwd=original, env=env).returncode == 0:
    raise RuntimeError('dedicated format branch already exists')
out.mkdir(parents=True, exist_ok=False)
report = {'state': 'starting', 'fixed_input_sha': fixed, 'fixed_input_tree': fixed_tree,
          'baseline': base, 'steps': [], 'source_tests_executed': 0, 'native_tests_executed': 0,
          'full_caller_proof_executed': False,
          'full_chain_acceptance': {'positive': 0, 'no_update': 0, 'daemon_root_cold_restart': 0}}

def save():
    pending = out / 'result.next'
    with pending.open('w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, out / 'result.json')

def step(name, args, cwd=None):
    path = out / (name + '.log')
    start = time.monotonic()
    with path.open('xb') as stream:
        completed = subprocess.run(args, cwd=cwd or repo, env=env, stdout=stream, stderr=subprocess.STDOUT)
    report['steps'].append({'name': name, 'exit_code': completed.returncode,
                            'seconds': time.monotonic() - start, 'bytes': path.stat().st_size,
                            'sha256': digest(path)})
    save()
    if completed.returncode:
        raise RuntimeError(name + ' failed; original log retained')

try:
    save()
    step('fetch-fixed', ['git', 'fetch', '--no-tags', 'origin', fixed], original)
    step('create-worktree', ['git', 'worktree', 'add', '-b', branch, str(repo), fixed], original)
    if git('rev-parse', 'HEAD^{tree}') != fixed_tree or git('show', '-s', '--format=%P', fixed).split() != [parent]:
        raise RuntimeError('fixed source graph differs')
    if git('merge-base', '--all', base, fixed) != base or git('status', '--porcelain=v1', '--untracked-files=all'):
        raise RuntimeError('fixed baseline or clean source differs')
    rust = git('ls-files', '*.rs').splitlines()
    if len(rust) != 6699 or any(not (repo / path).is_file() for path in rust):
        raise RuntimeError('complete original Rust scan domain unavailable')
    changed = set(git('diff', '--name-only', base, fixed).splitlines())
    if len(changed) != 160 or hashlib.sha256(('\n'.join(sorted(changed)) + '\n').encode()).hexdigest() != paths_sha256:
        raise RuntimeError('exact reviewed source delta differs')
    scopes = ('codex-rs/hepta-agentd/', 'codex-rs/hepta-neuron/', 'codex-rs/hepta-intelligence-eval/', 'codex-rs/hepta-learning-artifacts/')
    allowed_rust = {path for path in changed if path.endswith('.rs') and path.startswith(scopes)}
    allowed_python = {path for path in changed if path.endswith('.py') and path.startswith(('scripts/', 'qa/b4-no-bypass/'))}
    allowed = allowed_rust | allowed_python
    python_before = {path: ast.dump(ast.parse((repo / path).read_text()), include_attributes=False) for path in allowed_python}
    cargo = ('codex-rs/Cargo.toml', 'codex-rs/Cargo.lock', 'codex-rs/hepta-agentd/Cargo.toml')
    cargo_before = {path: digest(repo / path) for path in cargo}
    report.update(reviewed_format_scope=sorted(allowed), tracked_rust_files=len(rust), cargo_before=cargo_before)
    save()
    step('format', ['just', 'fmt', '--base', base], repo / 'codex-rs')
    actual = set(git('diff', '--name-only').splitlines())
    patch = out / 'format.patch'
    patch.write_bytes(subprocess.check_output(['git', 'diff', '--binary'], cwd=repo, env=env))
    report.update(formatter_changed_files=sorted(actual), format_patch={'bytes': patch.stat().st_size, 'sha256': digest(patch)},
                  formatter_postimages=[{'path': path, 'bytes': (repo / path).stat().st_size, 'sha256': digest(repo / path)} for path in sorted(actual)])
    save()
    if not actual <= allowed or git('ls-files', '--others', '--exclude-standard'):
        raise RuntimeError('formatter changed outside the exact reviewed source delta')
    if any(ast.dump(ast.parse((repo / path).read_text()), include_attributes=False) != before for path, before in python_before.items()):
        raise RuntimeError('Python formatter changed syntax semantics')
    if any(digest(repo / path) != before for path, before in cargo_before.items()):
        raise RuntimeError('formatter changed a dependency manifest or lock')
    report.update(python_ast_unchanged=True, cargo_unchanged=True)
    step('worktree-diff-check', ['git', 'diff', '--check'])
    if actual:
        step('stage-format', ['git', 'add', '--', *sorted(actual)])
        step('commit-format', ['git', 'commit', '-m', 'style(learn): format the fixed converged original owner source'])
    source, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    if git('status', '--porcelain=v1', '--untracked-files=all') or git('ls-remote', 'origin', 'refs/heads/' + branch):
        raise RuntimeError('formatted source dirty or dedicated remote branch already exists')
    step('push-fixed-source', ['git', 'push', '--force-with-lease=refs/heads/' + branch + ':', 'origin', 'HEAD:refs/heads/' + branch])
    if git('ls-remote', 'origin', 'refs/heads/' + branch).split()[0] != source:
        raise RuntimeError('remote postimage differs')
    report.update(state='formatted-source-published', source_sha=source, source_tree=tree, source_after=source, source_status_after='')
    save()
except BaseException as error:
    report.update(state='failed', error_type=type(error).__name__, error=str(error))
    if repo.exists():
        report.update(source_after=git('rev-parse', 'HEAD'), source_status_after=git('status', '--porcelain=v1', '--untracked-files=all'))
    save()
    raise
print(json.dumps({'state': report['state'], 'source_sha': report.get('source_sha'), 'result_path': str(out / 'result.json')}), flush=True)
