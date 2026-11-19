"""Frozen admission rules for the desktop HCSN campaign; no tensor imports."""
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

BASE_COMMIT = '28a61d14ea7d4c3b3c515ab57b29c98de22e5673'
BASE_MAP = '13860b933a93966e880e64840efa0ac26b70ab62cbe7e38bf71587575d9831a3'
CANDIDATE_MAP = '415f6a2f2d7a89ad0585f29bea0d91928898a11ec8a672de39ce6e22f04d39e9'
CANDIDATE_SOURCE = '7e89657ae4bd9444d0ed53b27cadaa70de1fa09027205cf2a0b8ca78891774bc'
FULL_CONFIG = '7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a'
REMAT_CONFIG = '43fb7b280bb80643c0bcdbfceae6788b37dd1d45fad682805ec6045088b31611'
PROBE = '70331f392c9695e0522da52817b3511b544304a6f4e23a169a016a07ea9f1285'
REMAT_PROBE = 'f8a2b7c193d2750cafb95446eff314195ca54ebb0305c008a35336f6bd874e08'
CHECKER = '664a508d7e1c70ee81efe077225b5f4f751bb790efc83cecfc6f1494a09bb509'
REMAT_MODULE = 'ea0be5db010342050437fc5aa5d0458b8601b744670a4d7e3abd84cfbc52ae38'
REMAT_MANIFEST = 'd864fdb4819a7f21c7e1a8178686b6bf9ec82df92cf88609240faa918876f51b'
GPU_UUID = 'GPU-a33875b7-7eb7-679e-df08-19227d3decee'
CANDIDATE_TEST_COUNT = 109
TORCH_MANIFEST = '5b8df3b8ff4583f10f43a1ecfb05f35574a3f95a16a458d107e36e8a89175701'
MAMBA_MANIFEST = '86f88c5d54c74e5baccdd99cace8f056a6ed6acc11f4bd8f633e122c951d5501'
PINS = {'numpy': '2.3.5', 'scipy': '1.17.0', 'ncps': '1.0.1',
        'nvidia-ml-py': '13.610.43', 'torch': '2.8.0+cu128', 'triton': '3.4.0',
        'mamba-ssm': '2.3.1', 'causal-conv1d': '1.5.4', 'transformers': '4.57.1'}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def normalize_gpu_uuid(value):
    """Match one physical GPU UUID; never guess an ordinal, prefix, or MIG mapping.

    PyTorch 2.8 _CUuuid.__str__ returns the bare hexadecimal UUID. NVML uses
    the GPU-prefixed form. Both must encode exactly the same 128-bit value.
    """
    require(isinstance(value, str) and re.fullmatch(
        r'(?:GPU-)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        value) is not None, 'invalid or unsupported physical GPU UUID')
    return 'GPU-' + value.removeprefix('GPU-').lower()


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'not a regular pinned file: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def read_json(path):
    def reject(value):
        raise ValueError(f'nonfinite JSON literal: {value}')
    return json.loads(Path(path).read_text(), parse_constant=reject)


def source_map(root):
    package = Path(root) / 'qualification/hcsn'
    return {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob('*.py'))}


def validate_source(root, expected):
    actual = source_map(root)
    require(canonical_sha(actual) == expected, 'research source-map drift')
    require(sha(Path(root)/'qualification/hcsn/configs/full.json') == FULL_CONFIG,
            'original full configuration drift')
    return actual


def execution_config(base, selected, policy):
    require(type(policy) is int and policy in (0, 1), 'policy is not fixed 0/1')
    require(type(selected.get('population_checkpoint_steps')) is int
            and type(selected.get('cuda_memory_fraction')) in (int, float), 'execution policy types differ')
    require(selected == dict(base, population_checkpoint_steps=policy, cuda_memory_fraction=0.5),
            'execution configuration changes a research budget/identity or undeclared policy')
    require(len(list(itertools.product(base['tasks'], base['models'], base['seeds']))) == 170,
            'matrix must retain 170 identities')


def validate_checks(report, expected_count, root):
    require(report.get('status') == 'passed' and report.get('require_torch') is True,
            'strict tensor checks did not pass')
    require(all(report.get(k) == v for k, v in {'tests_run': expected_count, 'passed': expected_count,
            'failed': 0, 'errors': 0, 'skipped': 0}.items()), 'strict tensor coverage incomplete')
    package = Path(root)/'qualification/hcsn'
    expected = {str(p.relative_to(package)): sha(p) for p in
                sorted(package.rglob('*.py')) + sorted((package/'configs').glob('*.json'))}
    require(report.get('source_files_sha256') == expected, 'strict tests source/config mismatch')


def validate_probe(report, model, rematerialized=False, permit_oom=False):
    require(report.get('model') == model and report.get('task') == 'delayed_recall'
            and report.get('seed') == 0, 'probe identity mismatch')
    require(report.get('probe_sha256') == (REMAT_PROBE if rematerialized else PROBE),
            'probe code mismatch')
    require(report.get('actual_source_map_sha256') == BASE_MAP
            and report.get('config_sha256') == FULL_CONFIG
            and report.get('source_unchanged') is True, 'probe source/config invalid')
    require(report.get('counts_toward_170_runs') is False
            and report.get('heldout_evaluated') is False, 'probe scope invalid')
    require(normalize_gpu_uuid(report.get('hardware', {}).get('uuid')) == GPU_UUID
            and report.get('hardware', {}).get('device') == 'cuda:0'
            and report.get('memory_fraction') == 0.5, 'probe GPU/cap mismatch')
    require(report.get('input_shape') == [64, 64, 2]
            and report.get('training_examples_submitted') == 64
            and report.get('training_tokens_submitted') == 4096
            and report.get('peak_reset_before_step') is True, 'probe shape/budget not reached')
    require(report.get('terminal_cuda_synchronized') is True, 'probe terminal synchronization missing')
    if permit_oom and report.get('status') == 'failed' and report.get('oom') is True:
        require(not rematerialized and model == 'population_flux'
                and report.get('failure_stage') in ('forward', 'loss', 'backward'),
                'OOM does not establish the declared original B graph limitation')
        return 'original_b_oom'
    require(report.get('status') == 'completed' and report.get('optimizer_steps_completed') == 1,
            'full-shape training step did not complete')
    require(report.get('missing_gradients') == [] and all(report.get('finite', {}).get(k) is True
            for k in ('prediction', 'loss', 'gradients', 'updated_parameters')),
            'full-shape numerical checks incomplete')
    require(isinstance(report.get('peak_allocated_bytes'), int)
            and isinstance(report.get('peak_reserved_bytes'), int), 'CUDA peak memory absent')
    if rematerialized:
        require(report.get('candidate_unchanged') is True, 'candidate source changed during step')
    return 'completed'


def validate_parity(report, device):
    require(report.get('status') == 'passed' and report.get('device') == device,
            'parity failed or wrong device')
    require(report.get('shape') == [2, 9, 2] and report.get('hidden_size') == 3
            and report.get('bins') == 32, 'parity fixture changed')
    require(report.get('checker_sha256') == CHECKER
            and report.get('candidate_module_sha256') == REMAT_MODULE
            and report.get('manifest_sha256') == REMAT_MANIFEST, 'parity code/manifest drift')
    expected = set(itertools.product(('float32', 'float64'), (True, False), (1, 4), (False, True)))
    rows = report.get('records', [])
    observed = [(r.get('dtype'), r.get('recovery'), r.get('segment_steps'),
                 r.get('input_requires_grad')) for r in rows]
    require(len(rows) == 16 and len(set(observed)) == 16 and set(observed) == expected
            and all(r.get('status') == 'passed' for r in rows), 'parity coverage incomplete')


def summarize_matrix(report, config, root, checkpoint_directory):
    require(report.get('config') == config and report.get('source_sha256') == CANDIDATE_SOURCE
            and report.get('source_files_sha256') == source_map(root), 'matrix provenance mismatch')
    expected = set(itertools.product(config['tasks'], config['models'], config['seeds']))
    rows = report.get('runs', [])
    observed = [(r.get('task'), r.get('model'), r.get('seed')) for r in rows]
    require(len(rows) == 170 and len(set(observed)) == 170 and set(observed) == expected,
            'matrix is missing identities or has duplicates')
    require(all(type(r.get('seed')) is int for r in rows), 'matrix seed types changed')
    require(report.get('hardware', {}).get('device') == 'cuda:0'
            and report.get('hardware', {}).get('cuda_available') is True,
            'matrix did not use CUDA')
    device = report['hardware'].get('cuda_execution', {})
    policy = {k:config[k] for k in ('population_checkpoint_steps', 'cuda_memory_fraction')}
    require(device.get('uuid') == GPU_UUID
            and normalize_gpu_uuid(device.get('uuid_raw')) == GPU_UUID
            and device.get('memory_fraction_readback') == 0.5
            and device.get('memory_fraction_set') is True and device.get('setup_error') is None,
            'matrix physical GPU or allocator policy mismatch')
    require(report.get('execution_policy') == policy, 'matrix execution policy differs')
    checkpoint_directory = Path(checkpoint_directory).resolve()
    for r in rows:
        require(r.get('status') in ('completed', 'failed', 'unavailable'), 'invalid matrix status')
        require(r.get('execution_policy') == policy, 'per-run execution policy differs')
        if r.get('status') == 'completed':
            require(r.get('training_steps_completed') == 400
                    and r.get('training_examples_seen') == 25600
                    and r.get('training_tokens_seen') == 1638400, 'completed row has reduced budget')
            require(r.get('training_status') == 'completed'
                    and bool(r.get('best_checkpoint_sha256')), 'completed row lacks trained weights')
            require(r.get('peak_gpu_measurement_status') == 'measured'
                    and r.get('peak_gpu_interval_complete') is True
                    and type(r.get('peak_gpu_allocated_bytes')) is int
                    and type(r.get('peak_gpu_reserved_bytes')) is int, 'completed row lacks GPU memory evidence')
            require(r.get('energy', {}).get('terminal_cuda_synchronized') is True,
                    'completed training interval not synchronized')
            require(all(type(r.get(k)) in (int, float) and math.isfinite(r[k])
                        for k in ('best_validation_mse', 'test_mse')), 'completed row has invalid quality metrics')
            relative = Path(r.get('best_checkpoint_relative', ''))
            weights = checkpoint_directory/relative
            require(not relative.is_absolute() and weights.resolve().is_relative_to(checkpoint_directory)
                    and sha(weights) == r['best_checkpoint_sha256'], 'completed checkpoint absent or changed')
            if r['model'] in ('population_flux', 'population_flux_no_recovery'):
                expected_class = 'RematerializedPopulationFluxEncoder' if config['population_checkpoint_steps'] else 'PopulationFluxEncoder'
                require(r.get('encoder_class') == expected_class
                        and r.get('implementation', {}).get('population_checkpoint_steps') == config['population_checkpoint_steps'],
                        'B implementation differs from uniform declared policy')
    counts = {s: sum(r.get('status') == s for r in rows) for s in ('completed', 'failed', 'unavailable')}
    require(report.get('status') == ('completed' if counts['completed'] == 170 else 'partial'),
            'aggregate completion contradicts rows')
    def physical_energy_present(record):
        energy = record.get('energy', {})
        if not isinstance(energy, dict):
            return False
        readings = energy.get('joules_by_physical_counter') or {}
        if not isinstance(readings, dict):
            return False
        value = readings.get('nvml_'+GPU_UUID)
        identity = energy.get('gpu_device_identity') or {}
        if not isinstance(identity, dict):
            return False
        try:
            same_device = (identity.get('mapping_verified') is True
                and identity.get('cuda_uuid') == GPU_UUID and identity.get('nvml_uuid') == GPU_UUID
                and normalize_gpu_uuid(identity.get('cuda_uuid_raw')) == GPU_UUID
                and normalize_gpu_uuid(identity.get('nvml_uuid_raw')) == GPU_UUID)
        except ValueError:
            same_device = False
        return (energy.get('interval_complete') is True and type(value) in (int, float)
                and math.isfinite(value) and value >= 0 and same_device)
    return dict(requested=170, **counts,
                physical_gpu_energy_complete=counts['completed'] == 170 and all(map(physical_energy_present, rows)),
                resolution_independence_established=False)
