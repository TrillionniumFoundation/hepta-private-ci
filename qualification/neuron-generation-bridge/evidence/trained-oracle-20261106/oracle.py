#!/usr/bin/env python3
"""Independent original-Torch oracle for the pinned trained Joint descendant."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent
REPO = Path('/workspace/scratch/e5ae6a941e52/joint-r2')
QUALIFICATION = REPO / 'qualification/neuron-generation-bridge'
SOURCE = Path('/workspace/scratch/40d04650905b/generation-repo/experiments/multimodal_output_portfolio/joint_hepta_20261029')
ASSETS = Path('/workspace/scratch/050e013c53db/p2-trained-recovery-20261106')
ACCEPTED = Path('/workspace/scratch/e5ae6a941e52/trained-bridge-run/replay-r3')
BUILD = Path('/workspace/scratch/e5ae6a941e52/trained-bridge-run/build-r3')
RUSTC = Path('/workspace/scratch/2e04527a60e8/toolchain/1.95.0-x86_64-unknown-linux-gnu/bin/rustc')
SCHEDULE = [('init', 17, 0), ('advance', 0), ('commit', 1, 16), ('advance', 1),
            ('advance', 2), ('advance', 3), ('advance', 4), ('advance', 5), ('advance', 6)]
TOLERANCE = {'fp64': 1e-9, 'fp32': 5e-5}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = {'schema': 'hepta.trained-joint-original-torch-oracle.v1', 'status': 'running',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'new_training_updates': 0,
              'tolerances_fixed_before_execution': TOLERANCE, 'stages': [], 'comparisons': [],
              'unmeasured': ['energy_joules', 'physical_disk_bytes', 'historical_training_cost',
                             'initial_readonly_discovery_and_code_authoring_cost'],
              'scope': 'Original historical Torch model versus unchanged native kernel and actual helper proposals; no Agentd, optimizer resume, natural quality or Torch/SplitMix RNG equivalence claim.'}
    (args.output / 'oracle.py').write_bytes(Path(__file__).read_bytes())
    def stage(name, function):
        begin, parent_cpu = time.perf_counter(), time.process_time()
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            return function()
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            report['stages'].append({'name': name, 'wall_seconds': time.perf_counter() - begin,
                'harness_cpu_seconds': time.process_time() - parent_cpu,
                'child_cpu_seconds': after.ru_utime + after.ru_stime - usage.ru_utime - usage.ru_stime})
    def command(name, argv):
        result = stage(name, lambda: subprocess.run(argv, capture_output=True, timeout=60))
        (args.output / (name + '.stdout')).write_bytes(result.stdout)
        (args.output / (name + '.stderr')).write_bytes(result.stderr)
        require(result.returncode == 0, name + ': ' + result.stderr.decode(errors='replace'))
        return result
    try:
        manifest = json.loads((QUALIFICATION / 'trained_asset_provenance/joint-trained-v1.json').read_text())
        asset_manifest = json.loads((QUALIFICATION / 'TRAINED-DESCENDANT.json').read_text())
        accepted = json.loads((ACCEPTED / 'RESULTS.json').read_text())
        require((ACCEPTED / 'RESULTS.json').read_bytes() ==
                (QUALIFICATION / 'evidence/trained-descendant-20261106/RESULTS.json').read_bytes(),
                'Accepted run receipt identity')
        build = json.loads((BUILD / 'BUILD.json').read_text())
        report['inputs'] = {'historical_source_sha': manifest['source_sha'],
                           'native_source_sha': build['source_sha'],
                           'accepted_result_sha256': file_sha(ACCEPTED / 'RESULTS.json'),
                           'asset_manifest_sha256': file_sha(QUALIFICATION / 'TRAINED-DESCENDANT.json'),
                           'build_sha256': file_sha(BUILD / 'BUILD.json'),
                           'oracle_source_sha256': file_sha(Path(__file__)),
                           'checkpoint_sha256': file_sha(ASSETS / 'adapter.pt')}
        require(report['inputs']['checkpoint_sha256'] == manifest['checkpoint']['sha256'], 'Checkpoint identity')
        package = args.output / 'historical_joint'
        (package / 'v3').mkdir(parents=True)
        (package / '__init__.py').write_text('')
        (package / 'v3/__init__.py').write_text('')
        for name, expected in manifest['source_files'].items():
            data = (SOURCE / name).read_bytes()
            require(sha(data) == expected, 'Historical source differs: ' + name)
            (package / name).write_bytes(data)
        native = args.output / 'native-source'
        native.mkdir()
        for name in ('codec.rs', 'math.rs', 'model.rs', 'state.rs'):
            key = 'src/joint_generation/' + name
            data = (REPO / 'codex-rs/hepta-infer-worker-host' / key).read_bytes()
            require(sha(data) == build['source_files'][key], 'Native source differs: ' + name)
            (native / name).write_bytes(data)
        for path, expected in build['linked_library_sha256'].items():
            require(file_sha(Path(path)) == expected, 'Linked library identity')
        require(file_sha(RUSTC) == build['compiler_sha256'], 'Compiler identity')
        helper = BUILD / 'hepta-joint-propose'
        require(file_sha(helper) == build['executable_sha256'], 'Helper identity')
        (args.output / 'inspect.rs').write_bytes((ROOT / 'inspect.rs').read_bytes())
        inspector = args.output / 'inspect-joint'
        argv = [str(RUSTC), '--edition=2024', '-C', 'opt-level=2',
                str(args.output / 'inspect.rs'), '-o', str(inspector)]
        command('build-inspector', argv)
        report['inspector'] = {'command': argv, 'source_sha256': file_sha(args.output / 'inspect.rs'),
                               'binary_sha256': file_sha(inspector), 'model_rewritten': False,
                               'operation': 'Read actual helper State packets; call existing Model.inspect unchanged.'}
        sys.path.insert(0, str(args.output))
        def load_torch():
            import numpy as np
            import torch
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
            torch.manual_seed(17)
            return torch, np
        torch, np = stage('import-torch', load_torch)
        model_module = importlib.import_module('historical_joint.v3.model')
        parent_module = importlib.import_module('historical_joint.model')
        bridge = importlib.import_module('historical_joint.v3.native_bridge')
        data_module = importlib.import_module('historical_joint.mechanism_data')
        report['runtime'] = {'torch': str(torch.__version__), 'torch_threads': torch.get_num_threads(),
                             'python': platform.python_version(), 'platform': platform.platform(),
                             'torch_build_config': torch.__config__.show()}
        def load_export():
            payload = torch.load(ASSETS / 'adapter.pt', map_location='cpu', weights_only=True)
            require(parent_module.tensor_digest(payload['state_dict']) == manifest['checkpoint']['joint_tensor_sha256'], 'Joint tensor identity')
            model = model_module.JointGenerator(**payload['config']).eval()
            model.load_state_dict(payload['state_dict'], strict=True)
            public, _ = data_module.batch([3], 'v3-native-implementation')
            weights, inputs, export = bridge.export_model(model, public, args.output / 'reexport')
            require(file_sha(weights) == manifest['export']['weights_sha256'], 'Same-source weight export identity')
            require(file_sha(inputs) == manifest['public']['sha256'], 'Same-source public export identity')
            report['reexport'] = export
            return model, public, weights, inputs
        model, public, weights, inputs = stage('strict-load-and-same-source-reexport', load_export)
        spec = importlib.util.spec_from_file_location('accepted_replay', QUALIFICATION / 'trained_replay.py')
        replay = importlib.util.module_from_spec(spec)
        require(file_sha(Path(spec.origin)) == accepted['qualification_source_sha256']['trained_replay.py'], 'Replay harness identity')
        spec.loader.exec_module(replay)
        fresh = args.output / 'fresh-helper'
        fresh.mkdir()
        experiment = replay.Experiment(SimpleNamespace(weights=weights, public=inputs, checkpoint=ASSETS / 'adapter.pt', executable=helper, output=fresh), asset_manifest)
        by_label = {record['label']: record for record in accepted['steps']}
        def saved(label):
            record = by_label[label]
            stem = ACCEPTED / f"{record['index']:03}-{label}"
            raw = stem.with_suffix('.response').read_bytes()
            require(sha(raw) == record['response_sha256'], 'Accepted raw response identity')
            state, delta, stopped, _ = replay.response(raw, bytes.fromhex(record['request_digest']))
            prefix = stem.with_suffix('.prefix').read_bytes()
            require(state == stem.with_suffix('.state').read_bytes(), 'Accepted saved state identity')
            return state, prefix, stopped, stem.with_suffix('.state')
        def fresh_sequence():
            state, prefix, stopped = b'', b'', False
            for index, selected in enumerate(SCHEDULE):
                actual = experiment.call(f's0-step{index}', state, prefix, replay.command(*selected))
                require(actual == saved(f's0-r0-step{index}')[:3], 'Fresh helper differs from accepted sequence')
                state, prefix, stopped = actual
        stage('nine-fresh-helper-proposals', fresh_sequence)
        report['fresh_helper'] = {'calls': len(experiment.steps), 'exact_accepted_replay': True,
                                  'ipc_bytes': sum(item['ipc_bytes'] for item in experiment.steps),
                                  'steps': experiment.steps}
        inspect_args = [str(inspector), str(weights)]
        inspect_paths = {}
        for sampler in (0, 1):
            for label in [f's{sampler}-r0-step{index}' for index in range(9)] + [f's{sampler}-auto-a']:
                state, prefix, stopped, path = saved(label)
                target = args.output / (label + '.inspect.hps')
                (args.output / (label + '.accepted.state')).write_bytes(state)
                inspect_args += [str(args.output / (label + '.accepted.state')), str(target)]
                inspect_paths[label] = target
        command('inspect-twenty-recorded-states', inspect_args)
        def compare(label, states):
            metadata, actual = bridge.unpack(inspect_paths[label].read_bytes())
            for dtype, reference_model, state in states:
                discrete = {'steps': str(state.steps), 'stopped': str(state.stopped).lower(),
                            'content_revision': str(state.content_revision), 'verified_revision': str(state.verified_revision),
                            'verified': str(state.verified_revision == state.content_revision).lower()}
                require(all(metadata[k] == value for k, value in discrete.items()), 'Discrete state mismatch')
                expected = bridge.reference_tensors(reference_model, state, 1.0, allow_initial_stop=True,
                    verified=state.verified_revision == state.content_revision, suppress_redundant_verify=False)
                require(set(actual) == set(expected), 'Inspection tensor inventory differs')
                errors = {name: float(np.max(np.abs(actual[name] - value))) for name, value in expected.items()}
                maximum = max(errors.values())
                (args.output / (label + '.' + dtype + '.reference.hps')).write_bytes(bridge.pack({'kind': dtype + '-torch-oracle'}, expected))
                report['comparisons'].append({'label': label, 'reference': dtype, 'tensors': len(errors),
                    'elements': sum(value.size for value in expected.values()), 'maximum_absolute_error': maximum,
                    'errors_by_tensor': errors, 'passed': maximum < TOLERANCE[dtype]})
                require(maximum < TOLERANCE[dtype], 'Numerical oracle mismatch: ' + label + ':' + dtype)
        def samples(reference_model, state):
            values, _, _ = reference_model.sample(state, torch.Generator().manual_seed(17), deterministic=True)
            image = np.rint(values['image'][0].numpy().transpose(1, 2, 0) * 255).astype(np.uint8).tobytes()
            video = np.rint(values['video'][0].numpy().transpose(0, 2, 3, 1) * 255).astype(np.uint8).tobytes()
            audio = np.rint(np.clip(values['audio'][0].numpy(), -1, 1) * 32767).astype('<i2').tobytes()
            action, sound = values['text'][0].tolist()
            return [image, audio, video, f'action={action};sound={sound}\n'.encode()]
        def original_oracle():
            m64, m32 = deepcopy(model).double().eval(), deepcopy(model).float().eval()
            p64 = {key: value.to(torch.int64 if key == 'tokens' else torch.float64) for key, value in public.items()}
            p32 = {key: value.to(torch.int64 if key == 'tokens' else torch.float32) for key, value in public.items()}
            s64, s32 = m64.encode(p64), m32.encode(p32)
            initial64, initial32 = s64, s32
            for index, selected in enumerate(SCHEDULE):
                if selected[0] == 'advance':
                    action = parent_module.ACTIONS[selected[1]]
                    s64, _ = m64.advance(s64, action, p64)
                    s32, _ = m32.advance(s32, action, p32)
                for sampler in (0, 1):
                    compare(f's{sampler}-r0-step{index}', [('fp64', m64, s64), ('fp32', m32, s32)])
                if index == 2:
                    early64, early32 = samples(m64, s64)[1][:32], samples(m32, s32)[1][:32]
            final64, final32 = samples(m64, s64), samples(m32, s32)
            final64[1], final32[1] = early64 + final64[1][32:], early32 + final32[1][32:]
            _, actual_media = replay.prefixes(saved('s0-r0-step8')[1])
            report['mean_media'] = []
            for index, name in enumerate(replay.MODALITIES):
                a, b, c = actual_media[index], final64[index], final32[index]
                require(a == b, 'Original FP64 mean sampled output bytes differ: ' + name)
                for kind, data in [('native', a), ('torch-fp64', b), ('torch-fp32', c)]:
                    (args.output / (name + '.' + kind + '.raw')).write_bytes(data)
                report['mean_media'].append({'modality': name, 'bytes': len(a), 'native_sha256': sha(a),
                    'fp64_byte_identical': a == b, 'fp32_byte_identical': a == c,
                    'fp32_differing_bytes': sum(x != y for x, y in zip(a, c))})
            law64 = bridge.reference_tensors(m64, initial64, 1.0, allow_initial_stop=True, verified=False, suppress_redundant_verify=False)['policy.probabilities']
            law32 = bridge.reference_tensors(m32, initial32, 1.0, allow_initial_stop=True, verified=False, suppress_redundant_verify=False)['policy.probabilities']
            require(int(law64.argmax()) == int(law32.argmax()), 'FP32/FP64 Auto action differs')
            action = parent_module.ACTIONS[int(law64.argmax())]
            a64, _ = m64.advance(initial64, action, p64)
            a32, _ = m32.advance(initial32, action, p32)
            for sampler in (0, 1):
                compare(f's{sampler}-auto-a', [('fp64', m64, a64), ('fp32', m32, a32)])
            report['auto_action'] = {'action': action, 'fp64_probabilities': law64.tolist(), 'fp32_probabilities': law32.tolist(), 'both_sampler_successors_match_original_oracle': True}
            require(parent_module.tensor_digest(model.state_dict()) == manifest['checkpoint']['joint_tensor_sha256'], 'Original trained model mutated')
        with torch.inference_mode():
            stage('original-torch-oracle-and-output-comparison', original_oracle)
        report['maximum_absolute_error'] = {dtype: max(row['maximum_absolute_error'] for row in report['comparisons'] if row['reference'] == dtype) for dtype in TOLERANCE}
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        report['cost'] = {'wall_seconds': time.perf_counter() - started, 'harness_cpu_seconds': time.process_time() - cpu,
                          'child_cpu_seconds': after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                          'semantics': 'Main execution includes source/asset checks, imports, isolated inspector build, reexport, 9 helper proposals, 1 inspector process, original Torch computations and evidence writes. Stages are subsets of this total; do not add totals twice. Outer RUN-COST.json includes startup, final receipt write and teardown.'}
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write(args.output / 'ORACLE.json', report)


if __name__ == '__main__':
    main()
