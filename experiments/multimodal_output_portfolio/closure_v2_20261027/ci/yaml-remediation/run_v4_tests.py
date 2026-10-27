"""Record a targeted v4 test invocation through the repository's just entrypoint."""

from pathlib import Path
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time


ROOT = Path('/workspace/scratch/95988d8d3ab1')
WORKTREE = ROOT / 'ndu-yaml-candidate-worktree'
OUTPUT = ROOT / 'ndu-dependency-remediation/yaml-migration/v4'
TOOLCHAIN = ROOT / 'native_toolchain_20261027/installed/bin'
label, *arguments = sys.argv[1:]
assert label and '/' not in label
log = OUTPUT / (label + '.log')
receipt = log.with_suffix('.json')
assert not log.exists() and not receipt.exists(), 'Never overwrite an earlier attempt.'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


sources = {}
for directory in ('codex-rs/utils/yaml', 'codex-rs/third_party/serde-saphyr-2.0.0'):
    for path in sorted((WORKTREE / directory).rglob('*')):
        if path.is_file() and 'target' not in path.relative_to(WORKTREE).parts:
            sources[str(path.relative_to(WORKTREE))] = sha(path)
for name in ('codex-rs/Cargo.toml', 'codex-rs/Cargo.lock'):
    sources[name] = sha(WORKTREE / name)
if '--manifest-path' in arguments:
    external = Path(arguments[arguments.index('--manifest-path') + 1]).parent
    for path in sorted(external.rglob('*')):
        if path.is_file() and 'target' not in path.relative_to(external).parts:
            sources['qualification:' + str(path)] = sha(path)

environment = os.environ.copy()
environment.update({
    'PATH': str(TOOLCHAIN) + ':' + str(ROOT / 'ndu-dependency-remediation/yaml-migration/bin') + ':' + environment['PATH'],
    'CARGO_HOME': str(ROOT / 'ndu-dependency-remediation/yaml-migration/cargo-home'),
    'CARGO_TARGET_DIR': str(ROOT / 'ndu-dependency-remediation/yaml-migration/target-compatibility'),
    'RUSTC': str(TOOLCHAIN / 'rustc'),
    'CARGO_PROFILE_DEV_DEBUG': '0', 'CARGO_PROFILE_TEST_DEBUG': '0',
    'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '2',
})
command = [str(ROOT / 'continuation_format_tools_20261027/just'), 'test', *arguments]
record = {
    'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'command': command, 'cwd': str(WORKTREE), 'source_inputs_before_execution': sources,
    'rustc_version': subprocess.check_output([str(TOOLCHAIN / 'rustc'), '-vV'], text=True),
    'target_directory': environment['CARGO_TARGET_DIR'],
}
receipt.write_text(json.dumps(record, indent=2) + '\n')
start = time.monotonic()
with log.open('xb') as stream:
    result = subprocess.run(command, cwd=WORKTREE, env=environment, stdout=stream, stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode, seconds=time.monotonic() - start, log_sha256=sha(log), workspace_lock_after_sha256=sha(WORKTREE / 'codex-rs/Cargo.lock'))
receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: value for key, value in record.items() if key != 'source_inputs_before_execution'}, indent=2))
print(log.read_text()[-3500:])
raise SystemExit(result.returncode)
