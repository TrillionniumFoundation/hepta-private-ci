"""Post-terminal, explicitly authorized identities. No production input at import time."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from audit_io import require, sha, save, verify_program
from checks import finite

PROGRAM = Path(__file__).resolve().parent
RSS = 2 * 1024**3
AS = 8 * 1024**3
WHOLE = 1800
RESERVE = 60
METADATA = 360
REPLAY = 210
ROSTER = [f'hcsn-s{s}-lr{lr}' for s in (101, 211, 307) for lr in ('0.001', '0.003')]


def identity(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), 'nonregular input: '+str(path))
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


class Inputs:
    def __init__(self, budget=lambda: None):
        self.files = {}
        self.budget = budget

    def bind(self, path, expected=None):
        self.budget()
        path = str(Path(path).resolve())
        item = identity(path)
        require(expected is None or item == expected or item['sha256'] == expected, 'identity differs: '+path)
        require(path not in self.files or self.files[path] == item, 'changed input: '+path)
        self.files[path] = item
        return Path(path)

    def json(self, path, expected=None):
        path = self.bind(path, expected)
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == self.files[str(path)]['sha256'], 'changed during JSON read')
        return json.loads(raw)

    def lines(self, path, expected=None):
        path = self.bind(path, expected)
        with path.open('rb') as stream:
            rows = [json.loads(line) for line in stream]
        require(identity(path) == self.files[str(path)], 'changed journal')
        return rows

    def verify(self):
        for path, item in self.files.items():
            self.budget()
            require(identity(path) == item, 'input changed after audit: '+path)


def safe_child(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    require(path.is_relative_to(root) and path != root, 'input path escapes admitted root')
    return path


def read_authorization(path, digest, binding_path, binding_sha):
    require(sha(path) == digest and sha(binding_path) == binding_sha, 'authorization/snapshot identity')
    value = json.loads(Path(path).read_bytes())
    require(value.get('execution_authorized') is True and value.get('scope') == 'independent-c2-terminal-audit-only'
            and value.get('confirmation_E_access') is False, 'separate terminal audit authorization required')
    require(value['program_manifest_sha256'] == verify_program(PROGRAM)
            and value['plan_sha256'] == sha(PROGRAM/'PLAN.json')
            and value['binding_sha256'] == binding_sha, 'authorization not bound to exact program/plan/snapshot')
    require(value['resources'] == {'whole_hard_wall_seconds': WHOLE, 'metadata_soft_wall_seconds': METADATA,
            'per_full_D_hard_wall_seconds': REPLAY, 'final_reserve_seconds': RESERVE, 'RSS_bytes': RSS,
            'address_space_bytes': AS, 'workers': 1, 'threads': 1}, 'audit resource declaration differs')
    return value


def terminal_barrier(outer, commands, roster, pid_reader):
    require(outer['status'] == 'completed_attempt_roster' and outer['execution_requested'] is True
            and outer['confirmation_access'] is False and outer['source_inputs_unchanged'] is True,
            'no immutable terminal C2 roster/source')
    attempts = outer['attempts']
    require(len(attempts) == len(roster) and {r['name'] for r in attempts} == set(roster), 'terminal roster incomplete')
    require(len({r.get('pid') for r in attempts if r.get('process_started')})
            == sum(r.get('process_started') is True for r in attempts), 'reused process identity')
    for row in attempts:
        require(row.get('process_started') in (True, False) and not row.get('child_terminal_unknown')
                and row.get('status') not in ('running', 'preparing', 'started'), 'unknown/live attempt')
        if row['process_started']:
            require(type(row.get('pid')) is int and type(row.get('returncode')) is int, 'missing process terminal')
            require(pid_reader(row['pid']) in ('absent', 'zombie'), 'known child still running or unreadable')
        selected = [r for r in commands if r['name'] == row['name']]
        require(selected and selected[-1] == row, 'terminal command differs from final roster')
        starts = [r for r in selected if r.get('status') == 'running']
        require(len(starts) == int(row['process_started']), 'missing/duplicate process launch')
        if starts:
            require(starts[0]['pid'] == row['pid'], 'launch/terminal PID differs')
    return {r['name']: r for r in attempts}


def proc_state(pid):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
    except (FileNotFoundError, ProcessLookupError):
        return 'absent'
    # Permission/corruption is deliberately not caught: unknown must block.
    state = text.rsplit(')', 1)[1].split()[0]
    return 'zombie' if state == 'Z' else 'running'


def context(binding_path, binding_sha, output, budget):
    inputs = Inputs(budget)
    plan = json.loads((PROGRAM/'PLAN.json').read_bytes())
    fixed = plan['fixed_identities']
    original = json.loads((PROGRAM/'original-replay-plan.json').read_bytes())
    binding = inputs.json(binding_path, binding_sha)
    require(binding['schema'] == 'independent-c2-terminal-binding-v1'
            and binding['all_attempts_terminal'] is True, 'post-terminal binding required')
    terminal = inputs.json(binding['native_terminal']['path'], binding['native_terminal']['identity'])
    # This is the raw durable daemon JSON, not an arbitrary normalized success bit.
    require(terminal.get('state') in ('succeeded', 'failed', 'cancelled')
            and terminal.get('output_complete') is True and terminal.get('output_durable') is True
            and terminal.get('terminal_publication_confirmed') is True
            and terminal.get('job_id') == binding['native_job_id'], 'native terminal publication not proved')
    require(proc_state(binding['controller_pid']) in ('absent', 'zombie'), 'controller still executing')
    paths = plan['native_paths']
    root = Path(paths['controller'])
    controller = inputs.json(root/'RESULT.json', binding['controller_result'])
    commands = inputs.lines(root/'commands.jsonl', controller['commands'])
    attempts = terminal_barrier(controller, commands, ROSTER, proc_state)
    save(Path(output)/'TERMINAL-ROSTER.json', {'controller_result': identity(root/'RESULT.json'),
        'attempts': attempts, 'cost_scope': 'unaltered terminal process fields; retained even if later source/model admission fails'})
    program = Path(paths['program'])
    manifest = inputs.json(program/'PROGRAM-MANIFEST.json', fixed['C2_program_manifest_sha256'])
    for name, item in manifest['files'].items():
        inputs.bind(safe_child(program, program/name), item)
    decision = inputs.json(binding['decision_path'], fixed['root_decision_sha256'])
    require(decision['execution_authorized'] is True and decision['confirmation_E_access'] is False
            and decision['scope'] == 'six-original-hcsn-c2-only', 'C2 decision differs')
    require(controller['execution_decision'] == inputs.files[str(Path(binding['decision_path']).resolve())], 'controller decision differs')
    contract = inputs.json(program/'CONTRACT.json', fixed['C2_contract_sha256'])
    require(contract['cumulative_active_wall_seconds'] == 43200 and contract['finalization_reserve_seconds'] == 600
            and contract['maximum_epochs'] == 200, 'original C2 envelope differs')
    runtime = inputs.json(contract['runtime_identity_path'], fixed['original_runtime_receipt_sha256'])
    original_campaign = inputs.json(Path(paths['original_campaign'])/'RESULT.json', fixed['original_campaign_result_sha256'])
    parents = {r['name']: r for r in original_campaign['attempts'] if r['name'] in ROSTER}
    require(set(parents) == set(ROSTER), 'original opportunity missing')
    prepared = Path(original['prepared']).resolve()
    data = inputs.json(prepared/'data-manifest.json', fixed['original_manifest_sha256'])
    require(data['mode'] == 'all-development' and data['confirmation_access'] is False, 'unexpected data scope')
    require(len(data['episodes']) == 484 and len({e['id'] for e in data['episodes']}) == 484, 'data roster')
    frontend = inputs.json(prepared/'frontend.json', data['frontend_sha256'])
    require(frontend['test_used'] is False and frontend['fit_subjects'] == list('ABC'), 'frontend scope')
    for entry in data['episodes']:
        require(entry['partition'] in ('train', 'dev') and entry['id'][0] in 'ABCD', 'E access forbidden')
        inputs.bind(safe_child(prepared, prepared/entry['path']), entry['sha256'])
    for name, digest in original['source_files'].items():
        inputs.bind(Path(original['source'])/name, digest)
    costs = []
    for name in ROSTER:
        row, parent = attempts[name], parents[name]
        require(row['parent_full_outer_wall_seconds'] == parent['whole_process_wall_seconds']
                and row['parent_actual_hard_wall_seconds'] == parent['hard_wall_seconds']
                and row['cumulative_active_wall_cap_seconds'] == 43200, 'parent cost/cap changed')
        if 'remaining_at_dispatch_seconds' in row:
            require(abs(row['remaining_at_dispatch_seconds'] - (43200-parent['whole_process_wall_seconds'])) < 1e-7,
                    'parent wall refunded')
        require(all(v is None or finite(v) and v >= 0 for v in
                    (row.get('whole_process_wall_seconds'), row.get('child_cpu_seconds'), row.get('attempt_wrapper_wall_seconds'))),
                'negative or invalid measured cost')
        costs.append({'name': name, 'original_full_process_wall_seconds': parent['whole_process_wall_seconds'],
                      'phase_outer_wall_seconds': row.get('whole_process_wall_seconds'),
                      'phase_wrapper_wall_seconds': row.get('attempt_wrapper_wall_seconds'),
                      'phase_wait4_CPU_seconds': row.get('child_cpu_seconds'),
                      'original_exit_CPU_seconds': None, 'terminal_evidence_complete': row.get('terminal_evidence_complete'),
                      'process_started': row['process_started'], 'original_actual_hard_wall_seconds': parent['hard_wall_seconds']})
    result = {'schema': 'independent-c2-context-v1', 'status': 'passed_terminal_context', 'attempts': attempts,
              'parents': parents, 'costs_all_six': costs, 'source': original['source'], 'prepared': str(prepared),
              'data_manifest': data, 'runtime': runtime, 'contract': contract, 'controller': str(root),
              'original_campaign': paths['original_campaign'], 'original_replay_plan': original,
              'optimization_policy': inputs.json(program/'OPTIMIZATION-POSTERIOR-POLICY-v2.json', fixed['optimization_policy_sha256']),
              'supplement_policy': inputs.json(program/'POSTERIOR-POLICY.json', fixed['supplement_policy_sha256']),
              'inputs': inputs.files, 'no_E': True, 'scientific_admission': 'HOLD'}
    inputs.verify()
    save(Path(output)/'CONTEXT.json', result)
    return {'status': 'passed', 'artifact': identity(Path(output)/'CONTEXT.json'), 'inputs_unchanged': True}
