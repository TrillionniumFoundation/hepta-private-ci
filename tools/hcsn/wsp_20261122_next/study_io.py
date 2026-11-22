"""Relative frozen inputs, numeric admission, fresh public schedules and records."""
from pathlib import Path
import ctypes
import hashlib
import json
import os
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
from data_contract import read, verify, pin, save, save_arrays, canonical, digest, head
import own_context
import value_graph
from public_sampling import public_world


def checked(base, spec):
    base = Path(base).resolve()
    relative = Path(spec['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('frozen relative path required')
    path = (base / relative).resolve()
    path.relative_to(base)
    absolute = dict(spec, path=str(path))
    verify(absolute)
    return absolute


def admit(protocol_path, inputs):
    protocol = read(protocol_path)
    if protocol['schema'] != 'hepta-value-sensitive-program-v1':
        raise ValueError('frozen protocol required')
    for spec in protocol['source_pins']:
        checked(ROOT, spec)
    for spec in protocol['input_pins']:
        checked(inputs, spec)
    if sorted(os.sched_getaffinity(0)) != [7] or not sys.dont_write_bytecode:
        raise ValueError('frozen process environment differs')
    if any(os.environ.get(k) for k in ('LD_PRELOAD', 'LD_AUDIT', 'PYTHONOPTIMIZE',
                                     'NPY_DISABLE_CPU_FEATURES', 'NPY_ENABLE_CPU_FEATURES')):
        raise ValueError('numeric dispatcher override')
    numeric = protocol['numeric']
    if pin(sys.executable)['sha256'] != numeric['python_executable']['sha256']:
        raise ValueError('unqualified Python executable')
    binary = Path(np._core._multiarray_umath.__file__).resolve()
    if pin(binary)['sha256'] != numeric['numpy_sha256'] or np.__version__ != numeric['numpy_version']:
        raise ValueError('unqualified NumPy binary')
    dispatch = np.lib.introspect.opt_func_info(func_name='^(exp|add|subtract|multiply|divide)$', signature='float64')
    if dispatch != numeric['dispatch']:
        raise ValueError('unqualified CPU dispatch')
    control = ctypes.CDLL(checked(inputs, numeric['mxcsr'])['path'])
    control.hepta_read_mxcsr.restype = ctypes.c_uint
    if control.hepta_read_mxcsr() & 0xe040:
        raise ValueError('RN/gradual-underflow contract differs')
    return protocol


def context(protocol):
    return own_context.load({key: checked(ROOT, spec) for key, spec in protocol['semantic_sources'].items()})


def gen_items(protocol, inputs, fit):
    spec = protocol['fits'][str(fit)]
    base = read(checked(inputs, spec['model'])['path'])
    with np.load(checked(inputs, spec['hidden'])['path'], allow_pickle=False) as archive:
        hidden = archive['H']
    items = []
    for row in spec['graphs']:
        actual = checked(inputs, row['graph'])
        graph = read(actual['path'])
        H = hidden[row['row_start']:row['row_end']]
        if len(H) != len(graph['states']) or graph['state_order_sha256'] != row['state_order_sha256']:
            raise ValueError('frozen GEN row alignment')
        items.append(dict(graph=graph, H=H, world_index=row['world_index'], graph_pin=actual))
    return base, items


def new_worlds(protocol, stage, previous_seal, used, output):
    """The sole entropy call follows an authenticated phase seal."""
    entropy = os.urandom(32)
    entropy_pin = save(output / 'ENTROPY.json', dict(entropy_hex=entropy.hex(),
        previous_seal_pin=pin(previous_seal), source='single os.urandom(32) after authenticated seal; no external custodian'))
    groups = {}
    domains = ('iid',) if stage == 'selection' else ('iid', 'ood')
    count = protocol['selection_worlds_per_fit'] if stage == 'selection' else protocol['confirmation_worlds_per_domain']
    for fit in protocol['fit_ids']:
        groups[str(fit)] = {}
        for domain in domains:
            seed = int.from_bytes(hashlib.sha256(entropy + canonical(
                [protocol['namespace'], stage, pin(previous_seal)['sha256'], fit, domain]).encode()).digest(), 'big')
            generator = np.random.Generator(np.random.PCG64(seed))
            worlds = []
            for index in range(count):
                public = public_world(generator, protocol['public_domains'][domain],
                    protocol['public_domains']['prior_distances'], f'value_next_{stage}_{fit}_{domain}_{index}')
                key = digest(canonical({k: public[k] for k in protocol['schedule_fields']}).encode())
                if key in used:
                    raise ValueError('schedule collision: no replacement is permitted')
                used.add(key)
                worlds.append(dict(public=public, schedule_sha256=key))
            groups[str(fit)][domain] = dict(seed=str(seed), worlds=worlds)
    result = dict(stage=stage, entropy_pin=entropy_pin, groups=groups, schedule_count=sum(
        len(v['worlds']) for row in groups.values() for v in row.values()))
    save(output / 'WORLDS_FROZEN.json', result)
    return result


def build_items(protocol, ctx, base, worlds, directory, budget):
    started = time.process_time()
    items = []
    policy = ctx.NumpyPolicy(base)
    for index, public_row in enumerate(worlds):
        budget()
        graph = value_graph.build(ctx, public_row['public'], base, protocol['state_cap'], budget)
        X, feature_counts = value_graph.semantic_inputs(ctx, public_row['public'], policy, graph['states'], budget)
        H = value_graph.strict_hidden(base, X)
        graph_pin = save(directory / f'world_{index}.json.gz', graph)
        features_pin = save_arrays(directory / f'world_{index}.npz', X=X, H=H)
        items.append(dict(graph=graph, H=H, X=X, world_index=index, graph_pin=graph_pin,
                          features_pin=features_pin, feature_counts=feature_counts))
    return items, dict(CPU_seconds=time.process_time() - started, worlds=len(items),
                       full_states=sum(len(x['H']) for x in items))


def compact_pin(path, base):
    record = pin(path)
    record['path'] = str(Path(path).resolve().relative_to(Path(base).resolve()))
    return record


def resolve_output_pin(spec, original_root, current_root):
    """A moved run is resolved beneath its explicit root, never an old live path."""
    relative = Path(spec['path']).relative_to(original_root)
    actual = dict(spec, path=str(Path(current_root) / relative))
    verify(actual)
    return actual
