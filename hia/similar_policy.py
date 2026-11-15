#!/usr/bin/env python3
"""Bind real similar/owner compiler invocations to an explicit HIA policy.

This wrapper contains no diff algorithm. It accepts only the pinned native Linux
toolchain, records completed real compiler artifacts, and executes a small
same-codegen arithmetic probe. Cached Cargo output requires --verify-cargo-log.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time

RUSTC_SHA = '4a84e05991ad6f2a84c1361c29b52b38c390365bd1fc269b1936c88d482a8928'
CLIPPY_SHA = '4b6976de2e62e12adaa5e6ef190b1d3f3fbf062e0f8ea5f4014fca45fb918a66'
CATALOG_SHA = '7fceb120e1cefbf4de7677fbc15dfe65ce845c23fb23b64eb73fede8afb8999f'
TARGET = 'x86_64-unknown-linux-gnu'
SCHEMA = 'codex.hia.similar-policy-receipt.v3'
CFG = 'codex_hia_unified_diff_policy'
PROBE = b'''use std::hint::black_box;
#[inline(never)] fn twice(value:usize)->usize { value*2 }
fn main() {
 std::panic::set_hook(Box::new(|_|{}));
 match std::panic::catch_unwind(||twice(black_box(usize::MAX))) {
  Ok(value)=>println!("wrapping:{value}"), Err(_)=>println!("checked")
 }
}
'''


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def binding(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_binding(item):
    require(binding(item['path']) == item, 'bound file changed: ' + item['path'])
    return Path(item['path'])


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def immutable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(data)
    except FileExistsError:
        require(path.read_bytes() == data, 'immutable record conflict: ' + str(path))


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.publish-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def option_values(argv, name):
    result = []
    for i, item in enumerate(argv):
        if item == name:
            require(i + 1 < len(argv), 'truncated option ' + name)
            result.append(argv[i + 1])
        elif item.startswith(name + '='):
            result.append(item[len(name) + 1:])
    return result


def last_option(argv, name):
    values = option_values(argv, name)
    return values[-1] if values else None


def catalog():
    path = Path(__file__).with_name('similar-source.json')
    require(sha(path) == CATALOG_SHA, 'original source catalog changed')
    value = json.loads(path.read_text())
    require(value['package'] == 'similar' and value['version'] == '2.7.0' and len(value['files']) == 73,
            'unqualified original source catalog')
    return value, binding(path)


def config():
    path = Path(os.environ['CODEX_HIA_SIMILAR_POLICY_CONFIG']).resolve(strict=True)
    value = json.loads(path.read_text())
    require(value['schema'] == 'codex.hia.similar-policy-config.v1', 'unknown policy configuration')
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'only Linux x86-64 native is qualified')
    require(sha(value['rustc']) == RUSTC_SHA, 'unqualified rustc binary')
    modes = value.get('supported_modes')
    require(isinstance(modes, list) and modes and all(type(x) is int and x in (0, 1) for x in modes)
            and len(set(modes)) == len(modes), 'only same-policy modes 0 and 1 are qualified for the actual owner')
    catalog()
    value['_binding'] = binding(path)
    value['_root'] = Path(value['receipt_root']).resolve()
    value['_root'].mkdir(parents=True, exist_ok=True)
    return value


def journal(cfg, value):
    with (cfg['_root'] / 'journal.jsonl').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(value, sort_keys=True) + '\n')
        stream.flush()
        fcntl.flock(stream, fcntl.LOCK_UN)


def compiler_chain(raw, cfg):
    require(raw, 'missing compiler executable')
    first = Path(raw[0]).resolve(strict=True)
    compiler = Path(cfg['rustc']).resolve(strict=True)
    if first == compiler:
        return [str(first)], raw[1:], [binding(first)]
    # Actual Cargo Clippy composition: our wrapper -> pinned clippy-driver -> rustc.
    require(len(raw) >= 2 and sha(first) == CLIPPY_SHA and Path(raw[1]).resolve() == compiler,
            'unsupported compiler/workspace-wrapper chain')
    tokens = [x for x in os.environ.get('CLIPPY_ARGS', '').split('__CLIPPY_HACKERY__') if x]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ('-A', '-W', '-D', '-F', '--allow', '--warn', '--deny', '--forbid', '--force-warn', '--cap-lints'):
            require(i + 1 < len(tokens), 'truncated Clippy lint argument')
            i += 2
        elif token == '--no-deps' or token.startswith(('-A', '-W', '-D', '-F', '--allow=', '--warn=', '--deny=', '--forbid=', '--force-warn=', '--cap-lints=')):
            i += 1
        else:
            raise RuntimeError('unqualified CLIPPY_ARGS entry: ' + token)
    return [str(first), str(compiler)], raw[2:], [binding(first), binding(compiler)]


def codegen(argv):
    result, omitted = [], []
    i = 0
    while i < len(argv):
        item = argv[i]
        require(not item.startswith('@'), 'response files are not qualified')
        require(not item.startswith('-Z'), 'unstable codegen flags are not qualified')
        require(item != '--codegen' and not item.startswith('--codegen='), 'long --codegen alias is not qualified')
        if item == '-C' or item.startswith('-C'):
            require(item != '-C' or i + 1 < len(argv), 'truncated -C')
            value = argv[i + 1] if item == '-C' else item[2:]
            raw = argv[i:i + 2] if item == '-C' else [item]
            i += len(raw)
            key = value.split('=', 1)[0]
            if key in ('lto', 'linker-plugin-lto'):
                require(value in (key + '=off', key + '=no', key + '=false'),
                        'unsupported LTO policy arrangement: ' + value)
            require(key not in ('profile-generate', 'profile-use', 'instrument-coverage'),
                    'unqualified instrumented codegen: ' + value)
            if key in ('metadata', 'extra-filename', 'incremental'):
                omitted.append(raw)
            else:
                result.extend(raw)
            continue
        if item in ('-O', '-g'):
            result.append(item)
        elif item in ('--target', '--sysroot', '--cfg') or any(item.startswith(x + '=') for x in ('--target', '--sysroot', '--cfg')):
            split = '=' in item
            require(split or i + 1 < len(argv), 'truncated ' + item)
            name, value = item.split('=', 1) if split else (item, argv[i + 1])
            if name == '--target':
                require(value == TARGET, 'cross or JSON target is not qualified')
            if name == '--cfg':
                require(not value.startswith(CFG), 'pre-existing HIA arithmetic policy is forbidden')
            result.extend([item] if split else [item, value])
            i += 0 if split else 1
        i += 1
    return result, omitted


def context(cfg):
    return {'config': cfg['_binding'], 'helper': binding(__file__), 'catalog': catalog()[1],
            'compiler': binding(cfg['rustc']), 'extra_inputs': [binding(p) for p in cfg['extra_inputs']]}


def source_inputs(source_root):
    source_root = Path(source_root).resolve(strict=True)
    result = []
    for item in catalog()[0]['files']:
        path = source_root / item['relative_path']
        require(not path.is_symlink(), 'original source symlink not admitted')
        actual = binding(path)
        require(actual['sha256'] == item['sha256'] and actual['bytes'] == item['bytes'],
                'original similar source differs: ' + str(path))
        result.append(actual)
    return result


def owner_inputs(cfg):
    root = Path(cfg['consumer_root']).resolve(strict=True)
    paths = []
    for path in root.rglob('*'):
        if not path.is_file() or any(part in ('target', '.git', '__pycache__') for part in path.relative_to(root).parts):
            continue
        require(not path.is_symlink(), 'consumer source symlink not admitted')
        paths.append(path)
    return [binding(p) for p in sorted(paths)]


def probe_result(code, stdout):
    if code == 0 and stdout == b'checked\n':
        return 'checked'
    if code == 0 and stdout == b'wrapping:18446744073709551614\n':
        return 'wrapping'
    if code == -6 and stdout == b'':
        return 'checked'
    raise RuntimeError('same-codegen probe outcome is not qualified: ' + str(code))


def run_probe(cfg, argv):
    flags, omitted = codegen(argv)
    key = hashlib.sha256(canonical({'compiler': RUSTC_SHA, 'helper': sha(__file__), 'codegen': flags, 'source': PROBE.hex()})).hexdigest()
    root = cfg['_root'] / 'probes' / key
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = root / 'receipt.json'
        if receipt.exists():
            result = json.loads(receipt.read_text())
            validate_probe(result)
            require(result['effective_codegen'] == flags, 'probe cache flags differ')
            return result, omitted
        source, binary = root / 'probe.rs', root / 'probe'
        immutable(source, PROBE)
        args = [cfg['rustc'], '--crate-name', 'hia_arithmetic_probe', '--edition=2024', str(source), *flags, '-o', str(binary)]
        # The real compiler retains Cargo's inherited jobserver descriptors. The
        # independent probe has no Cargo work queue and removes only that marker.
        env = {k: v for k, v in os.environ.items() if k != 'CARGO_MAKEFLAGS'}
        compiled = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        immutable(root / 'compile.stdout', compiled.stdout)
        immutable(root / 'compile.stderr', compiled.stderr)
        require(compiled.returncode == 0, 'same-codegen policy probe failed compilation')
        executed = subprocess.run([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        immutable(root / 'execute.stdout', executed.stdout)
        immutable(root / 'execute.stderr', executed.stderr)
        result = {'policy': probe_result(executed.returncode, executed.stdout), 'effective_codegen': flags,
                  'source': binding(source), 'binary': binding(binary),
                  'compile': {'argv': args, 'returncode': compiled.returncode, 'stdout': binding(root / 'compile.stdout'), 'stderr': binding(root / 'compile.stderr')},
                  'execute': {'argv': [str(binary)], 'returncode': executed.returncode, 'stdout': binding(root / 'execute.stdout'), 'stderr': binding(root / 'execute.stderr')},
                  'core_dump_limit': [0, 0]}
        immutable(receipt, canonical(result) + b'\n')
        return result, omitted


def validate_probe(value):
    require(value['compile']['returncode'] == 0, 'probe compilation was not successful')
    for key in ('source', 'binary'):
        verify_binding(value[key])
    for phase in ('compile', 'execute'):
        for output in ('stdout', 'stderr'):
            verify_binding(value[phase][output])
    require(Path(value['source']['path']).read_bytes() == PROBE, 'probe source differs')
    compiler = value['compile']['argv'][0]
    require(sha(compiler) == RUSTC_SHA, 'probe compiler identity differs')
    expected = [compiler, '--crate-name', 'hia_arithmetic_probe', '--edition=2024', value['source']['path'],
                *value['effective_codegen'], '-o', value['binary']['path']]
    require(value['compile']['argv'] == expected and value['execute']['argv'] == [value['binary']['path']],
            'probe command binding differs')
    observed = probe_result(value['execute']['returncode'], Path(value['execute']['stdout']['path']).read_bytes())
    require(observed == value['policy'], 'probe observation differs')


def index_path(cfg, path):
    key = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()
    return cfg['_root'] / 'indices' / (key + '.json')


def validate_receipt(cfg, value):
    require(value['schema'] == SCHEMA and value['context'] == context(cfg), 'policy receipt context changed')
    require(value['compiler_returncode'] == 0, 'producer did not finish successfully')
    require(hashlib.sha256(canonical(value['argv'])).hexdigest() == value['argv_sha256'], 'compiler argv changed')
    flags, omitted = codegen(value['argv'])
    require(flags == value['probe']['effective_codegen'] and omitted == value['identity_flags_omitted_from_probe'], 'probe flags do not match actual compiler arguments')
    validate_probe(value['probe'])
    require([item['sha256'] for item in value['compiler_chain']] in ([RUSTC_SHA], [CLIPPY_SHA, RUSTC_SHA]),
            'receipt compiler chain is not qualified')
    require(value['compiler_chain'][-1]['path'] == str(Path(cfg['rustc']).resolve()), 'receipt compiler path differs')
    for item in value['sources'] + value['artifacts'] + value['compiler_chain']:
        verify_binding(item)
    for output in ('stdout', 'stderr'):
        verify_binding(value['compiler_output'][output])
    if value['kind'] == 'consumer':
        require(value['sources'] == owner_inputs(cfg), 'consumer source set changed')
        actual, defining = select_receipt(cfg, value['selected_extern']['path'], 'defining')
        require(actual == value['selected_extern'] and defining['probe']['policy'] == value['defining_policy'], 'selected defining artifact changed')
        mode = policy_mode(defining['probe']['policy'], value['probe']['policy'])
        require(mode == value['policy_mode'], 'combined arithmetic mode changed')
        expected_argv = value['argv'] + ['--cfg', f'{CFG}="{mode}"', '--check-cfg', f'cfg({CFG}, values("0", "1", "2", "3"))']
    else:
        require(value['sources'] == source_inputs(value['source_root']), 'complete original source set changed')
        expected_argv = value['argv']
    require(value['actual_argv'] == expected_argv, 'actual compiler arguments do not match admitted policy')
    require(actual_artifacts(Path(value['compiler_output']['stderr']['path']).read_bytes(), value['actual_argv']) == value['artifacts'],
            'receipt artifacts differ from real compiler JSON events')


def select_receipt(cfg, selected_path, kind):
    index = index_path(cfg, selected_path)
    require(index.exists(), 'missing defining-crate policy receipt' if kind == 'defining' else 'missing consumer policy receipt')
    pointer = json.loads(index.read_text())
    require(pointer['lookup_path'] == str(Path(selected_path).resolve()), 'receipt index selects another path')
    receipt = verify_binding(pointer['receipt'])
    value = json.loads(receipt.read_text())
    require(value['kind'] == kind, 'receipt kind differs')
    actual = binding(selected_path)
    require(actual['sha256'] == pointer['actual_artifact']['sha256'] and actual['bytes'] == pointer['actual_artifact']['bytes'], 'selected actual artifact changed')
    require(pointer['actual_artifact'] in value['artifacts'], 'index artifact absent from real compiler output')
    validate_receipt(cfg, value)
    return actual, value


def select_cargo_receipt(cfg, record, selected_path, cargo_log):
    selected = Path(selected_path).resolve(strict=True)
    index = index_path(cfg, selected)
    require(index.exists(), 'missing consumer policy receipt: ' + str(selected))
    pointer = json.loads(index.read_text())
    if pointer.get('relation') != 'cargo-publication-alias':
        return select_receipt(cfg, selected, 'consumer')
    # Cargo can republish an already cached unit without invoking rustc. The
    # last compiled unit's hashless alias index is therefore not authoritative.
    # Identify this unit from its hashed peer in the SAME actual Cargo row.
    require(pointer['lookup_path'] == str(selected), 'receipt index selects another path')
    require(selected.suffix in ('.rlib', '.rmeta') and record['target']['kind'] == ['lib']
            and record['target']['crate_types'] == ['lib'], 'unsupported Cargo publication alias class')
    peers = [Path(p).resolve(strict=True) for p in record['filenames']
             if Path(p).resolve() != selected and Path(p).resolve().parent == selected.parent / 'deps'
             and Path(p).suffix in ('.rlib', '.rmeta')]
    require(len(peers) == 1, 'missing or ambiguous hashed Cargo publication peer')
    peer = peers[0]
    peer_index = index_path(cfg, peer)
    require(peer_index.exists(), 'missing consumer policy receipt: ' + str(peer))
    peer_pointer = json.loads(peer_index.read_text())
    require(peer_pointer.get('relation') == 'actual-compiler-event'
            and peer_pointer['actual_artifact']['path'] == str(peer), 'Cargo peer is not an actual compiler output')
    peer_actual, value = select_receipt(cfg, peer, 'consumer')
    argv = value['actual_argv']
    crate = last_option(argv, '--crate-name')
    outdir = Path(last_option(argv, '--out-dir')).resolve(strict=True)
    extra = ''
    for i, item in enumerate(argv):
        if item == '-C' and argv[i + 1].startswith('extra-filename='):
            extra = argv[i + 1].split('=', 1)[1]
        elif item.startswith('-Cextra-filename='):
            extra = item.split('=', 1)[1]
    features = sorted(x[len('feature="'):-1] for x in option_values(argv, '--cfg')
                      if x.startswith('feature="') and x.endswith('"'))
    require(crate == cfg['consumer_crate'] and crate == record['target']['name'].replace('-', '_')
            and option_values(argv, '--crate-type') == ['lib'] and features == sorted(record['features']),
            'Cargo publication unit differs from the actual compiler invocation')
    require(extra and '/' not in extra and '\\' not in extra and outdir == peer.parent
            and outdir == selected.parent / 'deps'
            and selected.name == 'lib' + crate + selected.suffix
            and peer.name == 'lib' + crate + extra + peer.suffix,
            'Cargo publication layout differs from actual out-dir or extra-filename')
    canonical_path = outdir / ('lib' + crate + extra + selected.suffix)
    canonical_actual, canonical_value = select_receipt(cfg, canonical_path, 'consumer')
    canonical_pointer = json.loads(index_path(cfg, canonical_path).read_text())
    require(canonical_pointer.get('relation') == 'actual-compiler-event'
            and canonical_pointer['actual_artifact'] == canonical_actual
            and canonical_pointer['receipt'] == peer_pointer['receipt'] and canonical_value == value,
            'Cargo publication output and peer do not share one actual compiler receipt')
    emitted = 'link' if selected.suffix == '.rlib' else 'metadata'
    events = []
    for line in Path(value['compiler_output']['stderr']['path']).read_bytes().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('$message_type') == 'artifact' and event.get('emit') == emitted:
            events.append(str(Path(event['artifact']).resolve()))
    require(events.count(str(canonical_path)) == 1
            and emitted in (last_option(argv, '--emit') or '').split(','),
            'Cargo publication class lacks its actual compiler artifact event')
    actual = binding(selected)
    require(actual['sha256'] == canonical_actual['sha256'] and actual['bytes'] == canonical_actual['bytes'],
            'selected actual artifact changed')
    refreshed = {'lookup_path': str(selected), 'relation': 'cargo-publication-alias',
                 'actual_artifact': canonical_actual, 'receipt': canonical_pointer['receipt'],
                 'cargo_publication': {'log': binding(cargo_log), 'peer': peer_actual}}
    atomic(index, refreshed)
    journal(cfg, {'event': 'admitted-cargo-publication', **refreshed})
    return actual, value


def policy_mode(defining, owner):
    return {('checked', 'checked'): 0, ('wrapping', 'wrapping'): 1,
            ('checked', 'wrapping'): 2, ('wrapping', 'checked'): 3}[(defining, owner)]


def actual_artifacts(stderr, argv):
    artifacts = []
    outdir = Path(last_option(argv, '--out-dir')).resolve()
    for line in stderr.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if value.get('$message_type') == 'artifact' and value.get('emit') in ('link', 'metadata'):
            path = Path(value['artifact']).resolve()
            require(path.parent == outdir, 'compiler artifact escaped actual out-dir')
            artifacts.append(binding(path))
    require(artifacts, 'no actual Rust compiler artifact event')
    return artifacts


def publish(cfg, value, argv):
    data = canonical(value) + b'\n'
    path = cfg['_root'] / 'receipts' / (hashlib.sha256(data).hexdigest() + '.json')
    immutable(path, data)
    extra = ''
    for i, item in enumerate(argv):
        if item == '-C' and argv[i + 1].startswith('extra-filename='):
            extra = argv[i + 1].split('=', 1)[1]
        elif item.startswith('-Cextra-filename='):
            extra = item.split('=', 1)[1]
    for artifact in value['artifacts']:
        actual = Path(artifact['path'])
        paths = [(actual, 'actual-compiler-event')]
        if actual.parent.name == 'deps' and extra and extra in actual.name:
            # This is an explicit Cargo publication lookup alias, never claimed
            # as a compiler-produced file. Its bytes must equal the real event.
            paths.append((actual.parent.parent / actual.name.replace(extra, '', 1), 'cargo-publication-alias'))
        for lookup, relation in paths:
            atomic(index_path(cfg, lookup), {'lookup_path': str(lookup.resolve()), 'relation': relation,
                                            'actual_artifact': artifact, 'receipt': binding(path)})
    journal(cfg, {'event': 'published', 'kind': value['kind'], 'receipt': binding(path),
                  'artifacts': value['artifacts'], 'policy': value['probe']['policy'], 'policy_mode': value.get('policy_mode')})
    return path


def wrapped_compile(raw):
    cfg = config()
    prefix, argv, chain = compiler_chain(raw, cfg)
    crate = last_option(argv, '--crate-name')
    defining = crate == 'similar' and os.environ.get('CARGO_PKG_VERSION') == '2.7.0'
    consumer = crate == cfg['consumer_crate'] and 'feature="hia-native"' in option_values(argv, '--cfg')
    if not defining and not consumer:
        return subprocess.run([*prefix, *argv], close_fds=False).returncode
    for sysroot in option_values(argv, '--sysroot'):
        require(Path(sysroot).resolve() == Path(cfg['rustc']).resolve().parent.parent, 'custom sysroot is not qualified')
    source_root = Path(os.environ['CARGO_MANIFEST_DIR']).resolve()
    if defining:
        require(os.environ.get('CARGO_PKG_NAME') == 'similar', 'defining package identity differs')
        require(str(source_root / 'src/lib.rs') in argv, 'defining source entry differs')
        sources = source_inputs(source_root)
    else:
        require(source_root == Path(cfg['consumer_root']).resolve() and os.environ.get('CARGO_PKG_NAME') == cfg['consumer_package'], 'consumer package identity differs')
        sources = owner_inputs(cfg)
    before = context(cfg)
    probe, omitted = run_probe(cfg, argv)
    selected = None
    admitted = None
    mode = None
    actual_argv = list(argv)
    if consumer:
        selected_paths = [x.split('=', 1)[1] for x in option_values(argv, '--extern') if x.startswith('similar=')]
        require(len(selected_paths) == 1, 'consumer must select exactly one actual --extern similar')
        selected, admitted = select_receipt(cfg, selected_paths[0], 'defining')
        mode = policy_mode(admitted['probe']['policy'], probe['policy'])
        require(mode in cfg['supported_modes'], 'mixed arithmetic category mapping is not admitted')
        actual_argv += ['--cfg', f'{CFG}="{mode}"', '--check-cfg', f'cfg({CFG}, values("0", "1", "2", "3"))']
    # Buffer only these two small defining/owner compiler calls. Metadata cannot
    # reach Cargo's pipeline before the immutable receipt has been published.
    result = subprocess.run([*prefix, *actual_argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=False)
    if result.returncode != 0:
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode
    require(context(cfg) == before, 'policy context changed during compilation')
    require(sources == (source_inputs(source_root) if defining else owner_inputs(cfg)), 'source changed during compilation')
    artifacts = actual_artifacts(result.stderr, actual_argv)
    # Fix can preserve metadata bytes while changing source and diagnostics.
    # Bind each immutable compiler log to its complete observed content.
    digest = hashlib.sha256(canonical({'argv': actual_argv, 'artifacts': artifacts, 'context': before,
        'sources': sources, 'clippy_args': os.environ.get('CLIPPY_ARGS'),
        'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
        'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()})).hexdigest()
    logs = cfg['_root'] / 'compiler-logs' / digest
    immutable(logs.with_suffix('.stdout'), result.stdout)
    immutable(logs.with_suffix('.stderr'), result.stderr)
    value = {'schema': SCHEMA, 'kind': 'defining' if defining else 'consumer', 'context': before,
             'argv': argv, 'argv_sha256': hashlib.sha256(canonical(argv)).hexdigest(), 'actual_argv': actual_argv,
             'compiler_chain': chain, 'compiler_returncode': result.returncode,
             'compiler_output': {'stdout': binding(logs.with_suffix('.stdout')), 'stderr': binding(logs.with_suffix('.stderr'))},
             'source_root': str(source_root), 'sources': sources, 'artifacts': artifacts,
             'probe': probe, 'identity_flags_omitted_from_probe': omitted,
             'clippy_args': os.environ.get('CLIPPY_ARGS'), 'target': TARGET,
             'cargo_jobserver_inherited': True, 'buffered_metadata_until_receipt': True}
    if consumer:
        value.update({'selected_extern': selected, 'defining_policy': admitted['probe']['policy'], 'policy_mode': mode})
    publish(cfg, value, argv)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return 0


def verify_cargo_log(log_path):
    cfg = config()
    records = [json.loads(line) for line in Path(log_path).read_text().splitlines()]
    require(records and records[-1] == {'reason': 'build-finished', 'success': True}, 'Cargo did not finish successfully')
    selected = [x for x in records if x.get('reason') == 'compiler-artifact' and x['target']['name'].replace('-', '_') == cfg['consumer_crate'] and 'hia-native' in x['features']]
    require(selected, 'Cargo output has no qualified native consumer')
    results = []
    for record in selected:
        require(Path(record['target']['src_path']).resolve().is_relative_to(Path(cfg['consumer_root']).resolve()), 'Cargo consumer source is outside the configured package')
        for path in record['filenames']:
            actual, value = select_cargo_receipt(cfg, record, path, log_path)
            results.append({'actual_cargo_artifact': actual, 'selected_extern': value['selected_extern'],
                            'policy_mode': value['policy_mode'], 'cargo_fresh': record['fresh'],
                            'cargo_package_id': record['package_id'], 'cargo_profile': record['profile']})
    print(json.dumps({'schema': 'codex.hia.similar-policy-cache-admission.v1', 'passed': True, 'cargo_log': binding(log_path), 'consumer_artifacts': results}))
    return 0


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.argv[1:2] == ['--verify-cargo-log']:
        return verify_cargo_log(sys.argv[2])
    if sys.argv[1:2] == ['--verify-defining-artifact']:
        cfg = config()
        actual, receipt = select_receipt(cfg, sys.argv[2], 'defining')
        print(json.dumps({'passed': True, 'actual_extern': actual, 'policy': receipt['probe']['policy']}))
        return 0
    return wrapped_compile(sys.argv[1:])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('HIA arithmetic admission rejected: ' + str(error), file=sys.stderr)
        raise SystemExit(74)
