"""Read-only identities and censored-best selection; no Torch or model loading."""

import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def read_bound(path, expected, inputs):
    path = Path(path)
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'input hash differs: ' + str(path))
    inputs[str(path)] = expected
    return json.loads(raw)


def verify_files(inputs):
    for path, digest in inputs.items():
        require(sha(path) == digest, 'input changed: ' + path)


def verify_program(program):
    program = Path(program)
    manifest = json.loads((program / 'MANIFEST.json').read_bytes())
    for relative, item in manifest['files'].items():
        path = program / relative
        require(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'],
                'auditor program differs: ' + relative)
    return sha(program / 'MANIFEST.json')


def construction(plan):
    return dict(arm=plan['arm'], width=plan['width'], seed=plan['seed'],
                s4_repo=plan.get('s4_repo'), hcsn_grid=plan['hcsn_grid_json'],
                freeze_shared=not plan['train_shared'],
                cache_frozen_tables=plan['cache_frozen_tables'],
                learn_core_adapter=plan['learn_core_adapter'], plif_configuration=None)


def strict_best(report):
    rows = report['epochs']
    require(bool(rows), 'no complete epoch')
    for number, row in enumerate(rows, 1):
        require(row['epoch'] == number and row['complete'] is True, 'incomplete epoch history')
        value = row['development']['macro_f1_11_classes']
        require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
                'invalid D score')
    best = max(rows, key=lambda row: row['development']['macro_f1_11_classes'])
    require(report['best_epoch'] == best['epoch'], 'best must be first strict maximum')
    return best


def validate_terminal(report, outer, plan, name):
    require(outer['name'] == name and outer['status'] == 'failed' and outer['returncode'] == 2,
            'candidate is not an intact censored terminal process')
    require(outer['fit_status'] == report['status'] == 'budget_exhausted', 'terminal statuses differ')
    require(report['training_adequacy_established'] is False and outer['adequate'] is False,
            'censored training cannot receive adequacy credit')
    require(report['confirmation_access'] is False and report['source_unchanged'] is True
            and report['source_before'] == report['source_after'], 'invalid original source/split')
    require(report['common_weights_unchanged'] is True, 'original shared tensors changed')
    require(report['arm'] == plan['arm'] == 'hcsn' and report['seed'] == plan['seed'], 'identity mismatch')
    require(name == f"hcsn-s{plan['seed']}-lr{plan['learning_rate']:g}", 'fit name/config mismatch')
    require(report['model_configuration'] == construction(plan), 'construction differs from fit plan')
    require(report['dtype'] == 'float64' and report['device'] == 'cpu' and plan['batch_size'] == 32,
            'original evaluation layout differs')
    return strict_best(report)


def checkpoint_metadata(checkpoint, report, fit_plan, best):
    require(checkpoint['epochs_completed'] == best['epoch'], 'loaded checkpoint is not best epoch')
    expected = best['epoch'] * math.ceil(report['episodes_train'] / fit_plan['batch_size'])
    require(checkpoint['main_updates'] == expected <= report['main_updates'], 'checkpoint update count differs')
    require(checkpoint['data_manifest_sha256'] == fit_plan['manifest_sha256'], 'checkpoint data differs')
    require(checkpoint['model_configuration'] == construction(fit_plan), 'checkpoint construction differs')


def bind_candidate(program, plan, name):
    """Original terminal journals are checked before candidate/model file reads."""
    require(name in plan['fit_roster'], 'undeclared candidate')
    inputs = {}
    base = Path(plan['native_base'])
    campaign = base / 'campaign-v2'
    snapshot = read_bound(Path(program) / 'terminal-snapshot.json', plan['terminal_snapshot_sha256'], inputs)
    final = read_bound(campaign / 'RESULT.json', plan['original_campaign_final_sha256'], inputs)
    require(final['confirmation_access'] is False and final['source_unchanged'] is True,
            'original final campaign lacks source/split identity')
    require(final['plan_sha256'] == plan['original_campaign_plan_sha256'], 'original campaign plan differs')
    locked = read_bound(base / 'campaign-v2-plan.json', plan['original_campaign_plan_sha256'], inputs)
    require(locked['source_capsule_sha256'] == plan['source_capsule_sha256'], 'source capsule differs')
    raw = (campaign / 'commands.jsonl').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == plan['original_commands_sha256'], 'terminal commands changed')
    inputs[str(campaign / 'commands.jsonl')] = plan['original_commands_sha256']
    commands = [json.loads(line) for line in raw.splitlines()]
    commands = [row for row in commands if row['name'] == name]
    require(len(commands) == 2 and commands[0]['status'] == 'started' and commands[1]['status'] == 'failed',
            'exactly one original terminal process required')
    attempts = [row for row in final['attempts'] if row['name'] == name]
    entries = [row for row in snapshot['fits'] if row['name'] == name]
    require(len(attempts) == len(entries) == 1, 'missing/duplicate terminal candidate')
    outer, entry = attempts[0], entries[0]
    require(commands[1] == outer, 'campaign final differs from raw terminal command')
    require(all(outer.get(key) == value for key, value in entry['outer'].items()), 'terminal handoff differs')
    require(outer['status'] == 'failed' and outer['returncode'] == 2, 'live/killed candidate rejected before model read')
    root = campaign / name
    identities = entry['artifact_identities']
    report = read_bound(root / 'result.json', outer['result_sha256'], inputs)
    fit_plan = read_bound(root / 'plan.json', report['plan_sha256'], inputs)
    best = validate_terminal(report, outer, fit_plan, name)
    require(fit_plan['prepared'] == plan['prepared'] and fit_plan['manifest_sha256'] == plan['data_manifest_sha256'],
            'prepared data location/identity differs')
    require(fit_plan['width'] == plan['expected_construction']['width']
            and fit_plan['hcsn_grid_json'] == plan['expected_construction']['grid']
            and not fit_plan['train_shared'] and fit_plan['cache_frozen_tables'] and fit_plan['learn_core_adapter'],
            'predeclared model regime differs')
    for filename, field in [('best.pt', 'best_checkpoint_sha256'), ('initial.pt', 'initialization_sha256'),
                            ('events.jsonl', 'events_sha256'), ('result.json', None), ('plan.json', None)]:
        path, item = root / filename, identities[filename]
        require(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'], 'artifact differs: ' + filename)
        require(field is None or report[field] == item['sha256'], 'report/artifact identity differs')
        inputs[str(path)] = item['sha256']
    events = [json.loads(line) for line in (root / 'events.jsonl').read_bytes().splitlines()]
    require(events[-1]['kind'] == 'finished' and events[-1]['status'] == 'budget_exhausted', 'unfinished event journal')
    completed = [row for row in events if row['kind'] == 'epoch_completed']
    require(len(completed) == len(report['epochs']), 'missing complete-epoch event')
    for event, row in zip(completed, report['epochs']):
        require(all(event.get(key) == value for key, value in row.items()), 'epoch report/journal differs')
    for path, digest in report['source_before'].items():
        require(sha(path) == digest, 'original source/runtime dependency changed: ' + path)
        inputs[path] = digest
    for suffix, digest in plan['source_files'].items():
        path = Path(plan['source']) / suffix
        require(sha(path) == digest, 'v8 source differs: ' + suffix)
        inputs[str(path)] = digest
    return inputs, root, report, fit_plan, best, outer


def read_dev(plan, inputs):
    root = Path(plan['prepared']).resolve()
    manifest = read_bound(root / 'data-manifest.json', plan['data_manifest_sha256'], inputs)
    require(manifest['mode'] == 'all-development' and manifest['confirmation_access'] is False, 'wrong data scope')
    entries = manifest['episodes']
    require(len({row['id'] for row in entries}) == len(entries), 'duplicate episode identity')
    require(all(row['partition'] in ('train', 'dev') for row in entries), 'unexpected partition')
    dev = [row for row in entries if row['partition'] == 'dev']
    require(dev == plan['dev_entries'] and len(dev) == plan['expected_dev_episodes'], 'ordered D roster differs')
    selection = read_bound(root / 'selection.json', manifest['selection_sha256'], inputs)
    require(len({row['id'] for row in selection}) == len(selection), 'duplicate selection identity')
    selection = {row['id']: row for row in selection}
    require(set(selection) == {row['id'] for row in entries}, 'selection roster differs')
    frontend = read_bound(root / 'frontend.json', manifest['frontend_sha256'], inputs)
    require(frontend['test_used'] is False and frontend['fit_subjects'] == list('ABC'), 'frontend leakage')
    rows = []
    for entry in dev:
        path = (root / entry['path']).resolve()
        require(path.is_relative_to(root) and entry['id'].startswith('D'), 'D path/subject violation')
        row = read_bound(path, entry['sha256'], inputs)
        require(row['partition'] == 'dev' and row['sequence'].startswith('D'), 'non-D episode')
        require({key: row[key] for key in selection[entry['id']]} == selection[entry['id']], 'frozen row selection differs')
        n = entry['events']
        require(n > 0 and all(len(row[key]) == n for key in ('x', 'dt', 'y', 'source_rows', 'delta_ticks')), 'bad episode length')
        require(row['dt'] == [tick / 10000000 for tick in row['delta_ticks']] and all(v >= 0 for v in row['dt']), 'gap identity differs')
        require(all(type(y) is int and 0 <= y < 11 for y in row['y']), 'invalid D label')
        require(all(len(x) == 25 and all(math.isfinite(v) for v in x) and any(x[12:24]) for x in row['x']), 'invalid D feature/mask')
        rows.append(row)
    require(sum(len(row['y']) for row in rows) == plan['expected_dev_events'], 'incomplete full D')
    return rows
