"""Isolated post-results control: unchanged fit/data/selection plus a signed mask."""
import time
_ENTRY = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import torch
from qualification.hcsn_smallnet_20261124 import train as t
from .model import SignedOnlySmallHCSN, verify_state_mask

HERE = Path(__file__).resolve().parent
ARM = {'id': 'qvi_signed_only', 'boundary_mode': 'qvi', 'message_mode': 'flow', 'feature_bank': 'value_risk'}


def read(path):
    return json.loads(Path(path).read_text())


def create(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.publish.tmp')
    with temporary.open('x') as h:
        json.dump(value, h, indent=2, sort_keys=True, allow_nan=False)
        h.write('\n'); h.flush(); os.fsync(h.fileno())
    os.link(temporary, path)
    temporary.unlink()


def supplement_sources():
    return {name: t.digest(HERE/name) for name in ('__init__.py', 'model.py', 'run.py', 'tests.py')}


def expected_protocol(root):
    base = t.load_protocol(root/'MAIN_PROTOCOL.json')
    p = copy.deepcopy(base)
    p.update(experiment_id='HCSN-SIGNED-ONLY-POSTRESULTS-20261124-v1', arms=[ARM],
        stage='post_results_descriptive_supplement',
        claim_scope='Exact signed-message-only control added after the main 72 results became public; no confirmatory or untouched-holdout claim.',
        test_policy='Reuse the now-public main test family for descriptive comparison, explicitly departing from the main new-holdout policy. Seal all 9 terminal training records before constructing test data. No test-driven reselection, retries, or tuning.',
        supplement={'source_hashes': supplement_sources(),
          'main_protocol_sha256': t.protocol_digest(base),
          'main_protocol_file_sha256': t.digest(root/'MAIN_PROTOCOL.json'),
          'main_final_results_sha256': t.digest(root/'MAIN_FINAL_RESULTS.json'),
          'registered_after_main_results': True, 'test_family_is_new_or_unseen': False,
          'factory_patch': 'Only fit-worker replaces train.SmallHCSN with SignedOnlySmallHCSN; original 14 files remain byte-identical.',
          'mechanism': 'message_mode=flow masks boundary; synaptic_mask[:,N:2*N]=0 masks unsigned event flow; saved buffer persists in original-core reload.',
          'initialization': 'Same seed and RNG draws as main qvi_flow; only persistent synaptic_mask differs.',
          'test_factory': 'Original SmallHCSN loads the signed-mask checkpoint, then the unchanged evaluate function.'})
    return p


def load(manifest):
    manifest = Path(manifest)
    p = t.load_protocol(manifest)
    if p != expected_protocol(manifest.parent):
        raise ValueError('supplement protocol/source/main artifact binding changed')
    return p


def validate_all(p, training, sealed=False):
    expected = read(training/'SEAL.json')['attempts'] if sealed else None
    records = t.validate_attempts(p, training, expected_records=expected)
    masks = {}
    for name, (row, _) in records.items():
        if row['checkpoint_sha256'] is None:
            continue
        ckpt = torch.load(training/name/'checkpoint.pt', map_location='cpu', weights_only=True)
        config = t.ModelConfig(**ckpt['config'])
        masks[name] = {}
        for key in ('initial_model', 'selected_model', 'last_model'):
            if ckpt[key] is not None:
                verify_state_mask(config, ckpt[key])
                masks[name][key] = t.hashlib.sha256(ckpt[key]['synaptic_mask'].numpy().tobytes()).hexdigest()
    if sealed:
        seal = read(training/'SIGNED_SEAL.json')
        if (seal['training_seal_sha256'] != t.digest(training/'SEAL.json')
                or seal['protocol_sha256'] != t.protocol_digest(p)
                or seal['supplement_sources'] != supplement_sources() or seal['masks'] != masks):
            raise ValueError('signed mask/source seal changed')
    return records, masks


def slot(p, name):
    for n in p['independent_neurons']:
        for seed in p['seeds']:
            if name == f'n{n}-{ARM["id"]}-s{seed}':
                return n, seed
    raise ValueError('unknown immutable slot')


def worker(args):
    status, error = 'failed', None
    directory = args.training/args.attempt
    cost_name = 'worker_cost.json' if args.action == 'fit-worker' else 'test_worker_cost.json'
    try:
        p = load(args.manifest)
        neurons, seed = slot(p, args.attempt)
        if args.action == 'fit-worker':
            original = t.SmallHCSN
            try:
                t.SmallHCSN = SignedOnlySmallHCSN  # Explicit, manifest-bound local factory substitution.
                result = t.fit(p, directory, arm=ARM, neurons=neurons, seed=seed)
            finally:
                t.SmallHCSN = original
            status = result['status']
        else:
            records, _ = validate_all(p, args.training, sealed=True)
            if (args.training/'FINAL_CLAIM').read_text().strip() != t.digest(args.training/'SIGNED_SEAL.json'):
                raise ValueError('test claim mismatch')
            result = records[args.attempt][0]
            if result['status'] != 'completed':
                create(directory/'test_result.json', {'attempt': args.attempt, 'status': 'unavailable', 'reason': result['error']})
            else:
                data = t.make_data('test', per_source=p['data']['test_per_source'], length=p['data']['length'], dtype=torch.float32)
                ckpt = torch.load(directory/'checkpoint.pt', map_location='cpu', weights_only=True)
                model = t.SmallHCSN(t.ModelConfig(**ckpt['config']))
                meter = t.CostMeter(scope='one_selected_and_initial_test_evaluation')
                model.load_state_dict(ckpt['selected_model'])
                verify_state_mask(model.config, model.state_dict())
                metrics, logits, _ = t.evaluate(model, data)
                model.load_state_dict(ckpt['initial_model'])
                verify_state_mask(model.config, model.state_dict())
                initial, initial_logits, _ = t.evaluate(model, data)
                raw = {'ids': data.ids, 'labels': data.y.tolist(), 'source': data.source.tolist(),
                    'prefix_logits': logits.tolist(), 'initial_prefix_logits': initial_logits.tolist(),
                    'final_logits': logits[-1].tolist(), 'initial_margin': data.initial_margin.tolist(),
                    'late_step': data.late_step.tolist(), 'source_hashes': p['source_hashes'],
                    'protocol_sha256': t.protocol_digest(p), 'data_sha256': data.digest()}
                create(directory/'test_predictions.json', raw)
                create(directory/'test_result.json', {'attempt': args.attempt, 'status': 'evaluated',
                    'neurons': neurons, 'arm': ARM['id'], 'seed': seed, 'metrics': metrics, 'initial_metrics': initial,
                    'selected_step': result['selected_step'], 'data_sha256': data.digest(),
                    'predictions_sha256': t.digest(directory/'test_predictions.json'), 'cost': meter.snapshot()})
            status = 'completed'
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
        raise
    finally:
        directory.mkdir(parents=True, exist_ok=True)
        create(directory/cost_name, {'status': status, 'wrapper_error': error,
            'wall_including_import_seconds': time.perf_counter()-_ENTRY,
            'process_cpu_through_report_seconds': time.process_time(),
            'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'energy_joules': None, 'scope': 'Fresh process through report; shutdown excluded.'})
    return 0 if status == 'completed' else 1


def launch_stage(args, p, action):
    start = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    def one(name):
        begin = time.perf_counter()
        directory = args.training/name
        row = {'attempt': name, 'returncode': None, 'error': None}
        try:
            command = [sys.executable, '-m', __package__+'.run', action, '--manifest', str(args.manifest),
                       '--training', str(args.training), '--attempt', name]
            env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
            with (args.training/(name+'.'+action+'.log')).open('x') as log:
                child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=540, check=False)
            row['returncode'] = child.returncode
        except Exception as exc:
            row['error'] = type(exc).__name__+': '+str(exc)
        finally:
            row['launch_through_exit_wall_seconds'] = time.perf_counter()-begin
            directory.mkdir(parents=True, exist_ok=True)
            create(directory/('parent_cost.json' if action == 'fit-worker' else 'test_parent_cost.json'), row)
        print(json.dumps({'stage': action, **row}), flush=True)
        return row
    with ThreadPoolExecutor(max_workers=9) as pool:
        rows = list(pool.map(one, t.expected_attempts(p)))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {'stage': action, 'workers': 9, 'attempts': rows, 'wall_seconds': time.perf_counter()-start,
        'all_child_cpu_seconds_including_shutdown': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        'driver_cpu_through_report_seconds': time.process_time(), 'energy_joules': None}
    create(args.training/('FIT_EXECUTION.json' if action == 'fit-worker' else 'TEST_EXECUTION.json'), receipt)
    return rows


def launch(args):
    p = load(args.manifest)
    args.training.mkdir(parents=True, exist_ok=False)
    create(args.training/'RUN_CLAIM.json', {'protocol_sha256': t.protocol_digest(p), 'supplement_sources': supplement_sources()})
    failure = None
    try:
        launch_stage(args, p, 'fit-worker')
        records, masks = validate_all(p, args.training)
        t.seal(p, args.training)
        create(args.training/'SIGNED_SEAL.json', {'protocol_sha256': t.protocol_digest(p),
            'training_seal_sha256': t.digest(args.training/'SEAL.json'),
            'supplement_sources': supplement_sources(), 'masks': masks})
        with (args.training/'FINAL_CLAIM').open('x') as h:
            h.write(t.digest(args.training/'SIGNED_SEAL.json')+'\n')
        print(json.dumps({'stage': 'all_nine_selection_records_sealed', 'seal_sha256': t.digest(args.training/'SIGNED_SEAL.json')}), flush=True)
        test_workers = launch_stage(args, p, 'test-worker')
        rows = []
        for name in records:
            path = args.training/name/'test_result.json'
            rows.append(read(path) if path.exists() else {'attempt': name, 'status': 'unavailable', 'reason': 'test worker failed; inspect retained receipts'})
        create(args.training/'FINAL_RESULTS.json', {'experiment_id': p['experiment_id'],
            'protocol_sha256': t.protocol_digest(p), 'seal_sha256': t.digest(args.training/'SEAL.json'),
            'cost': {'scope': 'see separate FIT_EXECUTION and TEST_EXECUTION; no merged CPU or energy estimate'}, 'results': rows})
        if any(row['returncode'] != 0 for row in test_workers):
            raise RuntimeError('one or more test workers failed; unavailable slots retained')
    except Exception as exc:
        failure = type(exc).__name__+': '+str(exc)
        raise
    finally:
        create(args.training/'CAMPAIGN_RECEIPT.json', {'status': 'failed' if failure else 'completed', 'error': failure,
            'source_hashes': supplement_sources(), 'protocol_sha256': t.protocol_digest(p),
            'wall_including_import_seconds': time.perf_counter()-_ENTRY, 'driver_cpu_through_report_seconds': time.process_time(),
            'energy_joules': None})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'launch', 'fit-worker', 'test-worker'])
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--training', type=Path)
    parser.add_argument('--attempt')
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.action == 'prepare':
        create(args.manifest, expected_protocol(args.manifest.parent))
        print(json.dumps({'prepared_protocol': str(args.manifest), 'sha256': t.digest(args.manifest)}))
    elif args.action == 'launch':
        launch(args)
    else:
        sys.exit(worker(args))


if __name__ == '__main__':
    main()
