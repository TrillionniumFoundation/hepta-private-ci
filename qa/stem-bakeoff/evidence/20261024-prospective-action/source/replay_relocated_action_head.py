"""One no-refit relocated replay: Granite field770 / seed7 / n8 / gated.

Run only after package_cell_local_evidence.py restore has succeeded. No sealed
receipt is rewritten; archive root mappings resolve every old data path.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys
import tarfile
import time

import numpy as np

ORIGINAL = Path('/tmp/hepta-prospective-action-20261024')
CONDITION = 'granite_clean_field770'
FEATURE = '00b09d213137fd60d33b39761d462f69b6e692155f51b7efd77896911cbd62c0'
PREDICTOR = '3cd92ad0c14be7b08c804a015d20815267b462e84d70abc3de2f6958aa3262c5'
PINNED = {
    'inputs/inputs.json': '42f2fa9ef5a19df8c43d2e39b4103c04bd421931c879f2f64c85aaff7b4c26ab',
    'learning-preparation/report.json': '77fac73c27874c1f4a81a574edd4c34054d437510d246fb8a3f5628c00f97e00',
    'learning-preparation/seal.json': 'aef77ab22412c73a7c31da6aa5d2b6340d9c13363904a59b32d468089eb5a725',
    'learning-inference/report.json': '4b1e5c5d3ac8d96aa569e92a52c21f4bc5a92ba937cbd9c285348324ad64395a',
    'learning-inference/seal.json': '54ebe16c7ff43d6ff54345fbe2bacaaa745a6e1cc833d7adb436ee13d6319215',
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def main(args):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    helper_pin = sha(__file__)
    archive, index_path = Path(args.archive).resolve(), Path(args.index).resolve()
    if Path(args.restored_root).is_symlink():
        raise ValueError('restored root cannot be a symbolic link')
    restored, source, output = Path(args.restored_root).resolve(), Path(args.source_dir).resolve(), Path(args.output).resolve()
    if (not restored.is_dir() or output.exists() or output.is_relative_to(restored)
            or any(output.is_relative_to((ORIGINAL/name).resolve())
                   for name in ('learning-preparation', 'learning-inference', 'inputs'))):
        raise ValueError('ordinary restored root and fresh separate output required')
    if sha(index_path) != args.index_sha256:
        raise ValueError('independent index pin differs')
    index = read(index_path)
    if archive.stat().st_size != index['archive_bytes'] or sha(archive) != index['archive_sha256']:
        raise ValueError('archive bytes differ from pinned independent index')
    with tarfile.open(archive, 'r|gz') as stream:
        member = stream.next()
        if member.name != 'manifest.json' or not member.isfile() or member.size > 32*1024**2:
            raise ValueError('bounded first manifest required')
        raw = stream.extractfile(member).read()
    if hashlib.sha256(raw).hexdigest() != index['manifest_sha256']:
        raise ValueError('archive manifest pin differs')
    manifest = json.loads(raw)
    if manifest['provenance'] != index['provenance'] or manifest['file_count'] != index['file_count']:
        raise ValueError('manifest/index provenance differs')
    members = {r['path']: r for r in manifest['files']}
    if len(members) != manifest['file_count']:
        raise ValueError('duplicate archive logical membership')
    consumed = {}

    def locate(original):
        original = Path(original)
        matches = []
        for label, root in manifest['provenance']['roots'].items():
            root = Path(root)
            if original == root:
                logical = label
            elif original.is_relative_to(root):
                logical = str(Path(label)/original.relative_to(root))
            else:
                continue
            if logical in members:
                matches.append(logical)
        if len(matches) != 1:
            raise ValueError(f'one authenticated logical member required: {original}')
        logical = matches[0]
        if Path(logical).is_absolute() or '..' in Path(logical).parts:
            raise ValueError('unsafe logical path')
        path = restored/logical
        if (any(p.is_symlink() for p in (path, *path.parents) if p == restored or p.is_relative_to(restored))
                or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1):
            raise ValueError('consumed restore must be independent ordinary files')
        expected = members[logical]
        if path.stat().st_size != expected['bytes'] or sha(path) != expected['sha256']:
            raise ValueError('restored member differs from archive')
        consumed[str(path)] = {'sha256': expected['sha256'], 'original_path': str(original), 'logical_path': logical}
        return path

    for name, digest in PINNED.items():
        if sha(locate(ORIGINAL/name)) != digest:
            raise ValueError('fixed experiment pin differs')
    prep_root = locate(ORIGINAL/'learning-preparation/seal.json').parent
    infer_root = locate(ORIGINAL/'learning-inference/seal.json').parent
    prep_report, infer_report = read(prep_root/'report.json'), read(infer_root/'report.json')
    prep_record = next(r for r in prep_report['conditions'] if r['name'] == CONDITION)
    infer_record = next(r for r in infer_report['conditions'] if r['name'] == CONDITION)
    if output.is_relative_to(Path(prep_record['feature_directory']).resolve()):
        raise ValueError('output cannot alter the original sealed feature alias')
    frozen_path = locate(Path(prep_record['prepared_dir'])/'frozen.json')
    frozen = read(frozen_path)
    original_infer = Path(infer_record['inference_dir'])
    child_report_path = locate(original_infer/'report.json')
    child = read(child_report_path)
    if (prep_record['feature_identity'] != FEATURE or infer_record['feature_identity'] != FEATURE
            or child['plan']['feature_identity'] != FEATURE or frozen['plan']['feature_identity'] != FEATURE
            or child['source_ids'] != infer_record['source_ids'] or child['group_ids'] != infer_record['group_ids']
            or child['plan']['prepared_seal_sha256'] != prep_record['preparation_seal_sha256']
            or not (child['plan']['input_bindings'] == frozen['plan']['input_bindings']
                    == prep_record['input_bindings'] == infer_record['input_bindings'])
            or frozen['plan']['input_bindings']['proposal_plan_sha256'] != PINNED['inputs/inputs.json']):
        raise ValueError('feature, source order or preparation lineage differs')
    code = dict(prep_report['plan']['code_sha256'])
    for name, digest in frozen['plan']['code_sha256'].items():
        if name in code and code[name] != digest:
            raise ValueError('conflicting expected numerical source pins')
        code[name] = digest
    for name, digest in code.items():
        if sha(source/name) != digest:
            raise ValueError(f'original numerical source differs: {name}')
    expected_runtime = prep_report['plan']['runtime']
    if expected_runtime != {'python': sys.version, 'numpy': np.__version__, 'platform': sys.platform}:
        raise ValueError('representative bitwise proof requires original Python/NumPy/platform')
    sys.path.insert(0, str(source))
    from cell_action_prepare import calibration_bindings, inventory, verify_action_prepared
    from cell_action_inference import _input_digest
    from cell_calibration_bounded import validate_bounded_calibrator
    from cell_learning_models import canonical

    def verify_trees():
        for tree, schema in ((prep_root, 'hepta.prospective-global-preparation-seal.v1'),
                             (infer_root, 'hepta.prospective-global-inference-seal.v1'),
                             (child_report_path.parent, 'hepta.action-label-free-inference-seal.v1')):
            if read(tree/'seal.json') != {'schema': schema, 'files': inventory(tree)}:
                raise ValueError('restored sealed tree has changed, missing or extra files')
        if verify_action_prepared(frozen_path.parent) != frozen:
            raise ValueError('restored selected preparation differs')

    verify_trees()
    if (sha(child_report_path) != infer_record['inference_report_sha256']
            or sha(frozen_path) != prep_record['preparation_report_sha256']
            or infer_report['preparation_report_sha256'] != PINNED['learning-preparation/report.json']
            or infer_report['preparation_seal_sha256'] != PINNED['learning-preparation/seal.json']):
        raise ValueError('global/child report pins differ')
    features_path = locate(original_infer/'features.npy')
    features = np.load(features_path, allow_pickle=False)
    original_inputs = read(locate(ORIGINAL/'inputs/inputs.json'))
    by_id = {r['source_id']: r for r in original_inputs['rows']}
    rows = [{k: by_id[sid][k] for k in ('source_id', 'group_id', 'text')} for sid in child['source_ids']]
    if (features.dtype != np.float32 or features.shape != (168, 770) or not np.isfinite(features).all()
            or [r['group_id'] for r in rows] != child['group_ids'] or _input_digest(features, rows) != child['plan']['input_sha256']):
        raise ValueError('saved feature bytes and original public source order differ')
    prep_run = next(r for r in frozen['runs'] if (r['seed'], r['budget']) == (7, 8))
    infer_run = next(r for r in child['runs'] if (r['seed'], r['budget']) == (7, 8))
    spec, observed = prep_run['arms']['gated'], infer_run['arms']['gated']
    original_location = original_infer/infer_run['directory']
    model_manifest = locate(Path(prep_record['prepared_dir'])/spec['artifact']/'manifest.json')
    locate(Path(prep_record['prepared_dir'])/spec['artifact']/'weights.npz')
    descriptor_path = locate(original_location/'gated-fresh.descriptor.json')
    calibration_path = locate(original_location/'gated-fresh.calibration.json')
    reference_path = locate(original_location/observed['prediction_file'])
    bindings = calibration_bindings(FEATURE, PREDICTOR, frozen['plan']['cohorts']['calibration'])
    if (spec['predictor_sha256'] != PREDICTOR or observed['tensor_sha256'] != PREDICTOR
            or read(descriptor_path) != {'feature_identity': FEATURE, 'bindings': bindings}
            or read(calibration_path) != spec['calibration'] or observed['calibration'] != spec['calibration']
            or sha(reference_path) != observed['prediction_sha256']):
        raise ValueError('frozen target, calibration or reference prediction differs')
    validate_bounded_calibrator(spec['calibration'], expected_bindings=bindings)
    alias_report = locate(Path(prep_record['feature_directory'])/'report.json')
    if sha(alias_report) != prep_record['feature_report_sha256'] or read(alias_report)['feature_identity'] != FEATURE:
        raise ValueError('feature alias identity differs')
    output.mkdir(parents=True, exist_ok=False)
    replay = output/'gated-replay.npz'
    command = [sys.executable, str(source/'cell_action_evaluate.py'), '--model', str(model_manifest.parent),
               '--features', str(features_path), '--descriptor', str(descriptor_path),
               '--calibration', str(calibration_path), '--output', str(replay)]
    start, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_process = subprocess.run(command, capture_output=True, timeout=60,
        env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    replay_cost = {'wall_ns': time.perf_counter_ns()-start, 'parent_cpu_ns': time.process_time_ns()-parent_cpu,
                  'child_cpu_ns': round(1e9*(after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime))}
    (output/'stdout.log').write_bytes(child_process.stdout)
    (output/'stderr.log').write_bytes(child_process.stderr)
    if child_process.returncode:
        raise ValueError(f'fresh replay failed: {child_process.returncode}')
    equal, digests = {}, {}
    with np.load(reference_path, allow_pickle=False) as original, np.load(replay, allow_pickle=False) as replayed:
        if set(replayed.files) != {'logits', 'probabilities'} or set(original.files) != {'logits', 'probabilities', 'eligible'}:
            raise ValueError('unexpected reference/replay array contract')
        for name in ('logits', 'probabilities'):
            a, b = original[name], replayed[name]
            equal[name] = a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
            digests[name] = {'dtype': a.dtype.str, 'shape': list(a.shape), 'bytes': a.nbytes,
                             'original': hashlib.sha256(a.tobytes()).hexdigest(), 'replayed': hashlib.sha256(b.tobytes()).hexdigest()}
    if not all(equal.values()):
        raise ValueError('relocated replay changed exact array bytes')
    verify_trees()
    if any(sha(p) != v['sha256'] for p, v in consumed.items()) or any(sha(source/n) != d for n, d in code.items()):
        raise ValueError('consumed restored inputs or source mutated during replay')
    if (sha(index_path) != args.index_sha256 or sha(archive) != index['archive_sha256']
            or sha(__file__) != helper_pin):
        raise ValueError('archive/index/helper changed during replay')
    receipt = {'schema': 'hepta.relocated-action-head-replay.v1', 'condition': CONDITION, 'seed': 7, 'budget': 8,
        'head': 'gated', 'rows': 168, 'groups': len(set(child['group_ids'])), 'feature_identity': FEATURE,
        'predictor_sha256': PREDICTOR, 'runtime': expected_runtime, 'array_bitwise_equal': equal, 'array_sha256': digests,
        'archive_sha256': index['archive_sha256'], 'manifest_sha256': index['manifest_sha256'],
        'index_sha256': args.index_sha256, 'restored_root': str(restored), 'consumed_files': consumed,
        'source_sha256': code, 'helper_sha256': helper_pin, 'fresh_process_command': command,
        'fresh_process_cost': replay_cost, 'total_wall_ns': time.perf_counter_ns()-began,
        'total_parent_cpu_ns': time.process_time_ns()-cpu, 'output_sha256': sha(replay),
        'fits': 0, 'encoder_calls': 0, 'metrics_computed': False, 'new_independent_quality_evidence': False,
        'original_provenance_rewritten': False, 'recovery_scope': 'one representative path relocation under original numerical runtime; not arbitrary architecture/version portability',
        'child_inputs': 'saved weights, saved feature matrix, frozen descriptor and calibrator; no outcome labels',
        'isolation_scope': 'argument/file allowlist only; shared filesystem remains accessible'}
    (output/'receipt.json').write_bytes(canonical(receipt)+b'\n')
    print(json.dumps({'receipt': str(output/'receipt.json'), 'sha256': sha(output/'receipt.json'), 'bitwise_equal': equal}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'index', 'index-sha256', 'restored-root', 'source-dir', 'output'):
        parser.add_argument('--'+name, required=True)
    main(parser.parse_args())
