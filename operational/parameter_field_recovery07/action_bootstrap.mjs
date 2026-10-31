// JavaScript actions receive the runner's artifact runtime credentials. Keep them
// in the inherited environment; never write them to a file or workflow output.
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const executable = process.env.INPUT_PYTHON || 'python3';
const destination = process.env['INPUT_OUTPUT-DIRECTORY'];
if (!destination || !process.env.ACTIONS_RUNTIME_TOKEN || !process.env.ACTIONS_RESULTS_URL) {
  process.stderr.write('Required action runtime context is unavailable.\n');
  process.exitCode = 1;
} else {
  const script = fileURLToPath(new URL('./transport_synthetic.py', import.meta.url));
  const child = spawn(executable, ['-B', script, '--output', destination],
    {stdio: 'inherit', env: {...process.env, HEPTA_ARTIFACT_NODE: process.execPath}});
  child.on('error', () => { process.stderr.write('Unable to start synthetic driver.\n'); process.exitCode = 1; });
  child.on('exit', (code) => { process.exitCode = code ?? 1; });
}
