"""Pure AST and actual-proof schema check; no control main/preflight executes."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
AUTHOR = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')
MAINTENANCE = Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1/driver-maintenance.HOLD.py')
CONFIG = Path('/tmp/hepta-36fa-provider-0c59-maintenance-dispatch-prefetch-v1/CONFIG.original.txt')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def check(condition, message):
    if not condition:
        raise AssertionError(message)

def definitions(raw):
    lines = raw.decode().splitlines(True)
    parsed = ast.parse(raw)
    return {node.name: ''.join(lines[node.lineno - 1:node.end_lineno]).encode()
            for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

def constants(parsed):
    found = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return found

def main():
    driver = (AUTHOR / 'driver-apply-fmt.HOLD.py').read_bytes()
    old = (AUTHOR / 'ORIGINAL_9101_DRIVER.py').read_bytes()
    base = MAINTENANCE.read_bytes()
    config_raw = CONFIG.read_bytes()
    hold_raw = (AUTHOR / 'WAITING_CONFIG.json').read_bytes()
    check(pin(driver) == {'bytes': 34454, 'sha256': 'a71789407526e0819056f04c002c932eb91b9f006f3a4ab9126e21f8989db0ed',
                         'git_blob': '0938761e369ddfa215da98b70423cfd5d48ac819'}, 'frozen driver')
    check(pin(old)['git_blob'] == '9101b44fb2ab24ae41a1344425dd74b536a40de4', 'original thin driver')
    parsed = ast.parse(driver)
    literal = constants(parsed)
    check(pin(base) == literal['MAINTENANCE_PIN'], 'entire original maintenance module')
    check(pin(config_raw) == literal['MAINTENANCE_CONFIG_PIN'], 'entire original approved configuration')
    check(pin(hold_raw)['git_blob'] == '0beff4136fc11d35513f2f16d7a26a0c30d77802', 'HOLD config')
    hold = json.loads(hold_raw)
    cfg = json.loads(config_raw)
    check(hold['root_execution_approved'] is False and hold['status'] == 'HOLD_ROOT_EXACT_REVIEW_REQUIRED', 'not execution approval')
    check(cfg['minimum_target_free_bytes'] == 34359738368, 'original 32GiB requirement')
    check(cfg['fmt_argv'] == hold['fmt_argv'] == ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f'], 'unchanged formatter argv')
    check((literal['PREFLIGHT_SECONDS'], literal['FMT_SECONDS'], literal['RECORD_SECONDS'], literal['OUTER_SECONDS']) == (600, 900, 300, 2100), 'same fmt-only budgets')
    before_defs, after_defs = definitions(old), definitions(driver)
    same = sorted(name for name in before_defs.keys() & after_defs.keys() if before_defs[name] == after_defs[name])
    changed = sorted(name for name in before_defs.keys() & after_defs.keys() if before_defs[name] != after_defs[name])
    check(same == ['first_read', 'identity', 'lock_identity', 'main'], 'four original control bodies exact')
    check(changed == ['apply_packet', 'module_from_original', 'prepare', 'retain_terminal'], 'four reviewed adaptations')
    check(set(after_defs) - set(before_defs) == {'prove_actual_failed_maintenance'}, 'new failed proof only')
    check(set(before_defs) - set(after_defs) == {'prove_actual_clean_source'}, 'obsolete clean proof replaced')
    stage_calls = [node for node in ast.walk(parsed) if isinstance(node, ast.Call) and
                   isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and
                   node.func.value.id == 'm' and node.func.attr == 'stage']
    check(len(stage_calls) == 1, 'one stage call')
    call = stage_calls[0]
    check(isinstance(call.args[0], ast.Constant) and call.args[0].value == 'fmt', 'only formatter stage')
    check(ast.unparse(call.args[1]) == 'm.FMT' and ast.unparse(call.args[2]) == 'FMT_SECONDS', 'original argv and timeout')
    forbidden_calls = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == 'm' and node.func.attr in {'main', 'initial_preflight', 'validate_config', 'validate_materialization_current'}:
                forbidden_calls.append(ast.unparse(node.func))
    check(not forbidden_calls, 'no old main/clean preflight/config bypass call')
    mutation_calls = [ast.unparse(node.func) for node in ast.walk(parsed) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                      and node.func.value.id == 'os' and node.func.attr in {'replace', 'remove', 'unlink', 'rename'}]
    check(mutation_calls == ['os.replace'], 'only one reviewed replace loop, no reset/removal')
    lock_calls = [node for node in ast.walk(parsed) if isinstance(node, ast.Call)
                  and ast.unparse(node.func) == 'fcntl.flock']
    check(len(lock_calls) == 1 and ast.unparse(lock_calls[0].args[1]) == 'fcntl.LOCK_EX | fcntl.LOCK_NB', 'single main-owned EX acquisition')

    # Read already retained cloud originals once into a fixed lookup. The extracted
    # predicate receives no OS, subprocess, production module or actual-path reader.
    bodies = {}
    paths = {}
    for name, expected in literal['FAILED_PROOFS'].items():
        path = RUNTIME / name
        if name == 'fix.raw.log':
            path = RUNTIME / 'fix.raw.exact_recovered.log'
        if name == 'final.inventory.json.gz' and not path.is_file():
            path = REPAIR / 'recovered-inventory/final.inventory.json.gz'
        raw = path.read_bytes()
        check(pin(raw) == expected, 'actual frozen proof ' + name)
        bodies[name] = raw
        paths[name] = str(path)
    normal_path = RUNTIME / 'MAIN_STATUS_06.original.json'
    normal = normal_path.read_bytes()
    check(pin(normal) == literal['FAILED_NORMAL_PIN'], 'actual original normal terminal')
    bodies['FAILED_MAINTENANCE_SUPERVISOR.original.json'] = normal
    paths['FAILED_MAINTENANCE_SUPERVISOR.original.json'] = str(normal_path)
    reads, writes = [], []
    def memory_read(path, expected):
        path = Path(path)
        check(path.parent in {Path('/fixed-proof-memory/run'), Path('/fixed-proof-memory/control')}, 'memory-only path namespace')
        raw = bodies[path.name]
        check(pin(raw) == expected, 'original predicate pin ' + path.name)
        reads.append({'name': path.name, 'local_original': paths[path.name], **pin(raw)})
        return raw
    def memory_write(name, raw):
        writes.append({'name': name, **pin(raw)})
    def pin_bytes(raw, expected, label):
        check(pin(raw) == expected, label)
        return raw
    module = SimpleNamespace(read_input=memory_read, write=memory_write, parse=json.loads,
        check=check, pin_bytes=pin_bytes, sha256=lambda raw: hashlib.sha256(raw).hexdigest(),
        REPO=Path(literal['CURRENT_REPO']), FIX=cfg['fix_argv'], FIX_SECONDS=cfg['fix_seconds'],
        MAXIMUM_LOG_BYTES=67108864, cfg=cfg, SUCCESSOR_INVENTORY=cfg['source_inventory'], result={})
    namespace = {**literal, 'gzip': gzip, 'base64': base64,
                 'PREVIOUS_RUN': Path('/fixed-proof-memory/run'), 'CONTROL': Path('/fixed-proof-memory/control')}
    function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == 'prove_actual_failed_maintenance')
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'exact-frozen-proof-function-only', 'exec'), namespace)
    returned = namespace['prove_actual_failed_maintenance'](module)
    check(pin(returned['inventory']) == literal['BASELINE'], 'actual inventory returned')
    check(pin(returned['metadata']) == literal['FAILED_METADATA_RAW_PIN'], 'actual complete raw Git metadata returned')
    check(pin(returned['witness_raw']) == literal['WITNESS_PIN'], 'actual witness returned')
    check(module.result['historical_fix']['returncode'] == 101 and module.result['historical_fix']['already_consumed'] is True
          and module.result['historical_fix']['reclassified'] is False, 'original failure not relabeled')

    # The input packet/tree mapping was independently checked in the separate
    # source peer; verify its exact identity and constants here, without rerunning it.
    peer_path = Path('/tmp/hepta-36fa-provider-0c59-fix101-independent-peer-v1/FROZEN_BYTE_REVIEW.json')
    peer_raw = peer_path.read_bytes()
    check(pin(peer_raw)['git_blob'] == 'dffe771bde8567e5cefd11758dcd477462e99730', 'frozen independent source check')
    peer = json.loads(peer_raw)
    check(peer['packet'] == literal['REPAIR_PROPOSAL_PIN'], 'same exact four-source repair')
    check(peer['actual_inventory'] == literal['BASELINE'] and peer['actual_baseline_physical_tree'] == literal['BASELINE_TREE'], 'same actual dirty baseline')
    check(peer['expected_successor_tree'] == literal['EXPECTED_APPLY_TREE'] and peer['source_count'] == literal['LEAVES'], 'same full expected four-write tree')
    check(hold['allowed_paths'] == literal['REPAIR_PATHS'] == [row['path'] for row in peer['changed_files']], 'closed four path list')
    report = {
        'schema': 'hepta-fix101-fmt-only-independent-control-proof-v1',
        'driver': pin(driver), 'hold_config': pin(hold_raw), 'original_thin_driver': pin(old),
        'original_maintenance_module': pin(base), 'original_maintenance_config': pin(config_raw),
        'unchanged_definitions': same, 'changed_definitions': changed,
        'added_definition': 'prove_actual_failed_maintenance', 'removed_definition': 'prove_actual_clean_source',
        'all_original_maintenance_bytes_reused': True,
        'original_maintenance_top_level_definitions': len(definitions(base)),
        'one_original_formatter_stage': {'argv': cfg['fmt_argv'], 'seconds': literal['FMT_SECONDS']},
        'preflight_record_outer_seconds': [600, 300, 2100],
        'main_owns_one_exact_ex_nb_lock': True,
        'bootstrap_must_not_preacquire_a_second_ex_lease': True,
        'hold_execution_approval': False,
        'actual_failed_records_match_exact_consumer_function': True,
        'read_records': reads, 'would_archive_records': writes,
        'returned_inventory': pin(returned['inventory']),
        'returned_raw_git_metadata': pin(returned['metadata']),
        'returned_witness': pin(returned['witness_raw']),
        'historical_fix': module.result['historical_fix'],
        'source_peer': pin(peer_raw),
        'stage_call_count': 1, 'forbidden_original_main_or_clean_preflight_calls': forbidden_calls,
        'source_mutation_calls': mutation_calls,
        'scope': 'Only AST/byte checks and the exact frozen proof predicate with fixed in-memory original bytes. No original or successor module/main/prepare/runtime environment loaded or executed; no H, formatter, Cargo, QA, Git or source write.',
    }
    data = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
    output = ROOT / 'FROZEN_CONTROL_PROOF.json'
    if output.exists():
        check(output.read_bytes() == data, 'fixed output')
    else:
        with output.open('xb') as stream:
            stream.write(data)
    print(json.dumps({'output': str(output), **pin(data), 'proof_inputs': len(reads), 'runtime_executed': False}))

if __name__ == '__main__':
    main()
