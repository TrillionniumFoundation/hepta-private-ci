"""Replay a fixed two-call routing rule using two published Hepta archives."""

import argparse
import collections
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path


PANELS = {
    'b2': ('0cda7c982d5fc1e19526bf755d92bedc8fa07ec1bf6a7c51a4bf097234034d41',
           'run/run-1/B2_exposed_followup/', '', 'first_panel'),
    'upstream': ('cdd49201d8c62217ad2777cece0c33e3ec7043edb3a50718edf7527ad150d042',
                 'run-1/upstream/', 'native_', 'transfer_panel'),
}
POLICY_SHA256 = 'de582bab5a35eff9dffb3953a5e97fe141542fda4c255e048c9659eca4190f54'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def read_node(files, key):
    step = files['STEP']
    output = files['OUTPUT']
    verifier = files['VERIFICATION']
    task, arm, slot = key
    require(step['status'] == 'COMPLETE' and step['slot'] == slot, 'incomplete node')
    require(files['REQUEST']['record_id'] == verifier['record_id'] == task, 'task identity')
    require(step['cell_id'] == arm[slot], 'wrong adapter')
    for name in ('REQUEST', 'OUTPUT', 'VERIFICATION'):
        require(digest(files[name]) == step[name.lower() + '_digest'], name + ' digest')
    require(step['verification'] == verifier and step['output'] == output, 'embedded objects')
    require(type(verifier['success']) is bool and verifier['success'] == step['business']['business_success'],
            'business outcome')
    require(sha(output['answer'].encode()) == verifier['answer_sha256'], 'answer verification binding')
    require(verifier['input_sha256'] == output['input_sha256'], 'verifier input binding')
    require(len(output['output_token_ids']) == output['output_tokens'], 'output token count')
    repo = re.search(r'^Source: ([^:\n]+):', files['REQUEST']['task']['input'], re.MULTILINE)
    require(repo is not None, 'missing upstream repository')
    return {'source': repo.group(1), 'request': step['request_digest'], 'output': step['output_digest'],
            'verification': step['verification_digest'], 'model': output['active_adapter_sha256'],
            'prompt': output['rendered_prompt_sha256'], 'generation': output['generation_config_sha256'],
            'answer': verifier['answer_sha256'], 'tokens': digest(output['output_token_ids']),
            'verifier_source': verifier['verifier_source_sha256'], 'reason': verifier['result']['reason'],
            'ok': verifier['success'], 'input_tokens': output['input_tokens'],
            'output_tokens': output['output_tokens'], 'incoming': step['incoming_edges']}


def panel_nodes(raw, panel, a, b):
    expected_sha, prefix, arm_prefix, _ = PANELS[panel]
    require(sha(raw) == expected_sha, 'archive SHA256 differs')
    records = collections.defaultdict(dict)
    arms = {a + a, a + b, b + b, b + a}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r|xz') as archive:
        for member in archive:
            if not member.name.startswith(prefix):
                continue
            parts = member.name[len(prefix):].split('/')
            if len(parts) != 4:
                continue
            task, arm, node, filename = parts
            if not arm.startswith(arm_prefix) or arm.removeprefix(arm_prefix) not in arms:
                continue
            arm = arm.removeprefix(arm_prefix)
            if node not in ('node-0', 'node-1') or filename not in ('STEP.json', 'REQUEST.json', 'OUTPUT.json', 'VERIFICATION.json'):
                continue
            key = task, arm, int(node[-1])
            name = filename.removesuffix('.json')
            require(name not in records[key] and member.isfile(), 'duplicate or irregular node record')
            records[key][name] = json.load(archive.extractfile(member))
    return {key: read_node(files, key) for key, files in records.items()}


def run(panel, path, policy):
    roles = policy[PANELS[panel][3]]
    a, b = roles['first'], roles['other']
    nodes = panel_nodes(path.read_bytes(), panel, a, b)
    tasks = sorted({key[0] for key in nodes})
    require(len(tasks) == 6, 'expected complete published panel')
    arms = sorted({key[1] for key in nodes})
    for required in (a + a, a + b, b + b):
        require(required in arms, 'missing comparator')
    wins = collections.Counter()
    rows = []
    counts = collections.Counter()
    for task in tasks:
        for arm in arms:
            first, last = (nodes[task, arm, slot] for slot in (0, 1))
            require(not first['incoming'] and bool(last['incoming']), 'unexpected full-communication branch')
            wins[arm] += first['ok'] or last['ok']
        first = nodes[task, a + a, 0]
        same = nodes[task, a + a, 1]
        relayed = nodes[task, a + b, 1]
        repeated_first = nodes[task, a + b, 0]
        for field in ('request', 'model', 'prompt', 'generation', 'tokens', 'answer', 'ok', 'reason'):
            require(first[field] == repeated_first[field], 'first-stage history differs: ' + field)
        clean = nodes[task, b + b, 0]
        for field in ('source', 'request', 'prompt', 'generation', 'verifier_source'):
            require(first[field] == clean[field], 'cold alternative context differs: ' + field)
        require(first['model'] != clean['model'], 'fallback adapter identity')
        reset = first['reason'] == policy['if_equals']
        second = clean if reset else same
        selected = first['ok'] or second['ok']
        counts['reason_reset_selected'] += selected
        counts['second_router_with_full_history_oracle_selected'] += first['ok'] or same['ok'] or relayed['ok']
        counts['always_clean_other_selected'] += first['ok'] or clean['ok']
        counts['reason_reset_last'] += second['ok']
        counts['clean_fallback_uses'] += reset
        counts['reason_reset_input_tokens'] += first['input_tokens'] + second['input_tokens']
        counts['reason_reset_output_tokens'] += first['output_tokens'] + second['output_tokens']
        rows.append({'task': task, 'source': first['source'], 'first_reason': first['reason'],
                     'first_ok': first['ok'], 'same_repair_ok': same['ok'], 'other_relay_ok': relayed['ok'],
                     'clean_other_ok': clean['ok'], 'second_origin': (b + b + '/0') if reset else (a + a + '/1'),
                     'retained': selected, 'second_ok': second['ok'],
                     'first_verification': first['verification'], 'second_verification': second['verification']})
    return {'archive_sha256': PANELS[panel][0], 'tasks': len(tasks), 'source_repositories': sorted({r['source'] for r in rows}),
            'matched_nodes_verified': len(nodes), 'observed_fixed_arms_selected': dict(wins),
            'replayed': dict(counts), 'logical_slots_in_reconstructed_policy': 2 * len(tasks),
            'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--b2', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, required=True)
    args = parser.parse_args()
    data = Path(__file__).with_name('route_policy.json').read_bytes()
    require(sha(data) == POLICY_SHA256, 'policy differs from the analyzed rule')
    policy = json.loads(data)
    print(json.dumps({'schema': 'hepta.e4.replayed-route.v1', 'policy_sha256': POLICY_SHA256,
                      'new_model_calls': 0, 'new_task_verifier_calls': 0, 'live_router_executions': 0,
                      'new_independent_tasks': 0, 'new_training_repeats': 0,
                      'panels': {p: run(p, getattr(args, p), policy) for p in PANELS}},
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
