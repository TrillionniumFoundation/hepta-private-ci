// Runner-provided artifact credentials remain inherited environment only.
import {spawn} from 'node:child_process';

const sha = process.env.GITHUB_SHA;
if (!/^[0-9a-f]{40}$/.test(sha || '') || !process.env.ACTIONS_RUNTIME_TOKEN ||
    !process.env.ACTIONS_RESULTS_URL) {
  process.stderr.write('Required committed source and artifact runtime context are unavailable.\n');
  process.exitCode = 1;
} else {
  const child = spawn('/opt/runtime/venv/bin/python', [
    '-B', '/work/source/operational/parameter_field_recovery07/bootstrap.py',
    '--source-commit', sha,
  ], {
    cwd: '/work/source',
    stdio: 'inherit',
    env: {...process.env, HEPTA_ARTIFACT_NODE: process.execPath,
      HEPTA_ARTIFACT_SDK_ROOT: '/work/transport-sdk', PYTHONDONTWRITEBYTECODE: '1'},
  });
  const relay = signal => { if (child.exitCode === null) child.kill(signal); };
  process.on('SIGTERM', () => relay('SIGTERM'));
  process.on('SIGINT', () => relay('SIGTERM'));
  child.on('error', () => {
    process.stderr.write('Unable to launch the registered scientific lifecycle.\n');
    process.exitCode = 1;
  });
  child.on('exit', code => { process.exitCode = code ?? 1; });
}
