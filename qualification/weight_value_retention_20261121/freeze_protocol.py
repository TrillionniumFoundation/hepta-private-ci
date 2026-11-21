"""Metadata-only preflight and explicit final freeze; no model/solver execution."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import ast
import importlib.metadata
import os
import platform
import resource
import signal
import sys
import time
import traceback
import zipfile
import numpy as np
import own_context
from data_contract import FITS, canonical, digest, exact_radius, head, pin, read, save, verify
from input_contract import original_specs, split_worlds, schedule_hash

AGENTS_SHA = '3f7d567dbed66ca514101f674511d42707dab033c22239f93e62248dbac62a09'
TEACHER_SOURCE_SHA = '68bf0f31749dfb2dc3e50d44666906763898f4c8fe0ecbc9fd79c91de03fa180'
REQUIRED = ('data_contract.py', 'input_contract.py', 'own_context.py', 'value_graph.py',
            'head_candidates.py', 'evaluation_io.py', 'run_support.py', 'public_sampling.py',
            'run_main.py', 'run_confirmation.py', 'verify_records.py', 'supervise.py',
            'freeze_protocol.py', 'test_math_controls.py', 'RECORD_CONTRACT.json', 'README.md', 'requirements.txt')


def utc():
    return datetime.now(timezone.utc).isoformat()


def header(path, key):
    with zipfile.ZipFile(path) as archive, archive.open(key + '.npy') as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, order, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, order, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError('undeclared cached array header format')
    return dict(shape=list(shape), fortran_order=order, dtype=str(dtype))


def collect(args):
    root, work, prior = args.output_root.resolve(), args.input_root.resolve(), args.previous_root.resolve()
    draft_pin = pin(root / 'DRAFT_PROTOCOL.json')
    draft = read(draft_pin['path'])
    if draft['status'] != 'DRAFT_NOT_FROZEN_NOT_EXECUTED':
        raise ValueError('explicit draft state required')
    for name in REQUIRED:
        if not (root / name).is_file():
            raise FileNotFoundError('required implementation not complete: ' + name)
    sources = {path.name: pin(path) for path in sorted(root.glob('*.py'))}
    sources.update({name: pin(root / name) for name in ('RECORD_CONTRACT.json', 'README.md', 'requirements.txt')})
    for name, entry in sources.items():
        if name.endswith('.py'):
            tree = ast.parse(Path(entry['path']).read_text(), filename=entry['path'])
            compile(tree, entry['path'], 'exec')
    source_agents = pin(root.parent / 'publication' / 'SCIENCE_AGENTS.md')
    if source_agents['sha256'] != AGENTS_SHA:
        raise ValueError('applicable instructions differ from reviewed source')
    frozen_joint = work / 'neuron_margin_experiment' / 'vendor' / 'frozen_joint'
    semantics = {name: pin(frozen_joint / (name + '.py')) for name in
                 ('checked_replay', 'legacy_task', 'joint_task', 'joint_deploy', 'run_head_edit')}
    semantics['planning'] = pin(frozen_joint.parent / 'planning.py')
    ctx = own_context.load(semantics)  # Definitions only: no policy, Oracle or forward instantiation.
    teacher_source = pin(work / 'neuron_causal_rescue_20261120' / 'causal_core.py')
    if teacher_source['sha256'] != TEACHER_SOURCE_SHA:
        raise ValueError('original full-state own-teacher source differs')
    provenance = dict(causal_core=teacher_source,
        original_full_mlp=pin(work / 'neuron_full_mlp_experiment' / 'run_full_mlp_experiment.py'),
        original_task_graph=pin(work / 'neuron_margin_experiment' / 'task_graph.py'), applicable_AGENTS=source_agents)
    domain_pin = pin(frozen_joint / 'joint_protocol.json')
    metadata = read(domain_pin['path'])
    domains = dict(iid=metadata['train_domain'], ood=metadata['ood_domain'], prior_distances=metadata['prior_distances'])
    history_pins = [pin(prior / 'attempt001' / name) for name in
                    ('HISTORY.json', 'DEV_WORLDS_FROZEN.json', 'CONF_WORLDS_FROZEN.json')]
    history = [read(entry['path']) for entry in history_pins]
    fields = history[0]['canonical_schedule_fields']
    known = set()
    for count, inventory in zip((3456, 20, 160), history):
        keys = inventory['keys']
        if len(keys) != count or len(set(keys)) != count or known.intersection(keys):
            raise ValueError('historical hash-only exclusion inventory differs')
        known.update(keys)
    if len(fields) != 13 or len(known) != 3636:
        raise ValueError('complete known public history required')
    specs, splits, dimensions = {}, {}, {}
    for fit in FITS:
        spec = original_specs(work, prior, fit)
        specs[str(fit)] = spec
        model = read(spec['model']['path'])
        if model['head_dimensions'] != [85, 48, 4] or model['family'] != 'renewal':
            raise ValueError('source model architecture/family changed')
        exact_radius(head(model))
        reconstruction, family = read(spec['reconstruction']['path']), read(spec['family']['path'])
        for actual, old in ((spec['model'], family['source_C']), (spec['data'], reconstruction['dataset']),
                            (spec['teacher'], family['teacher'])):
            if any(actual[key] != old[key] for key in ('bytes', 'sha256')):
                raise ValueError('source checkpoint/dataset/own-teacher metadata identity')
        if not family['program']['own_law_labels_only'] or len(family['program']['TRAIN']) != 64:
            raise ValueError('source own-law teacher provenance')
        publics = read(spec['publics']['path'])
        if len(publics) != 64:
            raise ValueError('64 original exposed TRAIN worlds required')
        for public in publics:
            ctx.validate_public(public)
            if schedule_hash(public, fields) not in known:
                raise ValueError('original TRAIN schedule absent from historical exclusion')
        splits[str(fit)] = split_worlds(fit, publics, fields)
        dimensions[str(fit)] = dict(X=header(spec['data']['path'], 'X'),
            masks=header(spec['data']['path'], 'legal_masks'), scores=header(spec['data']['path'], 'C_scores'),
            teacher=header(spec['teacher']['path'], 'own_optimal_targets'),
            posterior=header(spec['teacher']['path'], 'own_posterior'))
        n = dimensions[str(fit)]['X']['shape'][0]
        if n != reconstruction['train_rows'] or sum(row['rows'] for row in family['program']['TRAIN']) != n:
            raise ValueError('complete original row count')
        expected = dict(X=[n, 85], masks=[n, 6], scores=[n, 6], teacher=[n, 4], posterior=[n])
        for name, item in dimensions[str(fit)].items():
            if item['shape'] != expected[name] or item['dtype'] != ('bool' if name == 'masks' else 'float64'):
                raise ValueError('authenticated cached array shape/dtype differs')
    versions = {name: importlib.metadata.version(name) for name in ('numpy', 'scipy', 'clarabel')}
    if versions != {'numpy': '2.3.5', 'scipy': '1.17.0', 'clarabel': '0.11.1'}:
        raise ValueError('restored-epoch numerical package version differs')
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        if os.environ.get(name) != '1':
            raise ValueError('one-thread execution environment required')
    cpuinfo = Path('/proc/cpuinfo').read_text()
    model_names = sorted({line.split(':', 1)[1].strip() for line in cpuinfo.splitlines()
                          if line.startswith('model name')})
    return dict(output_root=str(root), draft_pin=draft_pin, source_pins=sources,
        semantic_sources=semantics, provenance_sources=provenance, input_specs=specs,
        public_domain_source=domain_pin, public_domains=domains, schedule_fields=fields,
        history_inputs=history_pins, known_schedule_hashes=sorted(known), splits=splits,
        cache_header_contract=dimensions,
        resources=dict(affinity_CPU=7, address_space_bytes=536870912,
            main=dict(CPU_hard=150, CPU_soft=145, wall_hard=240),
            confirmation=dict(CPU_hard=60, CPU_soft=55, wall_hard=120),
            reader=dict(CPU_hard=60, CPU_soft=55, wall_hard=120)),
        environment=dict(python=sys.version, executable_pin=pin(sys.executable), packages=versions,
            platform=platform.platform(), CPU_models=model_names, affinity=sorted(os.sched_getaffinity(0)),
            PYTHONPATH=os.environ.get('PYTHONPATH'), epoch='restored container; no timing-equivalence claim'),
        source_teacher_contract=dict(locator='hepta-private-ci@ad9309182ef71a6007257464d8b132cd5fc0ee7a:qualification/weight_space_nextstage_20261120/neuron/source/causal_core.py',
            pin=teacher_source, generation='construct_program -> full-state enumerate_graph -> ordered Bellman; no Oracle.q recursion',
            Q_posterior_masks_scores_authentication='exact F64/bool bytes under declared arithmetic'))


def main(args):
    started, wall = time.process_time(), time.perf_counter()
    if args.stage == 'preflight':
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_AS, (536870912,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        def timeout(*unused):
            raise TimeoutError('metadata preflight wall cap')
        signal.signal(signal.SIGALRM, timeout)
        signal.alarm(15)
        save(args.receipt.with_name('PREFLIGHT_STARTED.json'), dict(created_utc=utc(), real_forwards=0,
            solver_calls=0, CPU_hard=5, wall_hard=15, address_space_bytes=536870912, no_retry=True))
        try:
            contract = collect(args)
            save(args.receipt, dict(schema='hepta-value-zero-forward-preflight-v1', status='PASS',
                created_utc=utc(), contract=contract, real_forwards=0, solver_calls=0, scientific_graphs=0,
                resources=dict(CPU_seconds=time.process_time(), preparation_CPU_seconds=time.process_time() - started,
                    wall_seconds=time.perf_counter() - wall, peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)))
        except BaseException as error:
            save(args.receipt.with_name('PREFLIGHT_FAILED.json'), dict(created_utc=utc(), status='FAILED',
                error=str(error), traceback=traceback.format_exc(), retry_permitted=False))
            raise
    else:
        preflight = read(args.receipt)
        if preflight['status'] != 'PASS' or preflight['real_forwards'] != 0 or preflight['solver_calls'] != 0:
            raise ValueError('successful metadata-only preflight required')
        contract = preflight['contract']
        verify(contract['draft_pin'])
        for name in ('source_pins', 'semantic_sources', 'provenance_sources'):
            for expected in contract[name].values():
                verify(expected)
        for spec in contract['input_specs'].values():
            for expected in spec.values():
                verify(expected)
        for expected in contract['history_inputs'] + [contract['public_domain_source']]:
            verify(expected)
        if len(args.review) < 2:
            raise ValueError('independent static review and synthetic qualification required')
        reviews = [pin(path) for path in args.review]
        for expected in reviews:
            record = read(expected['path'])
            if record.get('status') not in ('PASS', 'PASS_AFTER_REVIEW', 'COMPLETED'):
                raise ValueError('review/qualification is not successful')
        frozen = dict(contract, schema='hepta-value-retention-frozen-v1', created_utc=utc(),
            preflight_pin=pin(args.receipt), review_pins=reviews,
            freeze_metadata_CPU_seconds=time.process_time() - started,
            authorization='Parent-approved bounded isolated protocol, complete source/input freeze precedes real science')
        save(args.output, frozen)
    print(canonical(dict(stage=args.stage, output=pin(args.receipt if args.stage == 'preflight' else args.output))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=('preflight', 'freeze'), required=True)
    parser.add_argument('--input-root', type=Path, required=True)
    parser.add_argument('--previous-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path, action='append', default=[])
    main(parser.parse_args())
