"""Explicit public-checkpoint canary. No task-quality, training or release claim.

Acquisition is separate from local-only inference. Freeze a Hub commit and exact
file inventory BEFORE transfer; download only stock JSON/safetensors files from
one fixed public model. No credentials, .bin conversion or remote model code.
"""
import argparse
import json
import shutil
from pathlib import Path

from hf_complete_checkpoint import load_complete_mlm, TIED_ALIASES
from hf_encoder_kernel import snapshot_digest, vectorize_case, verify_loaded_safetensors
from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from paired_execution import PHASES, _sha

MODEL_ID = 'answerdotai/ModernBERT-base'
ALLOWED_FILES = frozenset(('config.json', 'model.safetensors', 'tokenizer.json',
                           'tokenizer_config.json', 'special_tokens_map.json'))
REQUIRED_FILES = ALLOWED_FILES - {'special_tokens_map.json'}
MAX_DOWNLOAD_BYTES = 800_000_000


def freeze_public_source(info):
    _sha(info.sha, 'Hub commit', 40)
    files = {}
    for item in info.siblings:
        if item.rfilename in ALLOWED_FILES:
            if item.rfilename in files or type(item.size) is not int or item.size <= 0:
                raise ValueError('invalid or duplicate source file size')
            files[item.rfilename] = item.size
    if not REQUIRED_FILES.issubset(files) or sum(files.values()) > MAX_DOWNLOAD_BYTES:
        raise ValueError('missing safetensors/tokenizer or excessive public download')
    return dict(schema='hepta.public-encoder-source-lock.v1', model_id=MODEL_ID,
                upstream_revision=info.sha, files=dict(sorted(files.items())),
                public_diagnostic_only=True, independent_material_approval=False)


def acquire_public(root, *, revision="main"):
    if revision != "main":
        _sha(revision, "requested immutable Hub commit", 40)
    from huggingface_hub import HfApi, snapshot_download
    info = HfApi(token=False).model_info(MODEL_ID, revision=revision, files_metadata=True)
    lock = freeze_public_source(info)
    if revision != "main" and lock["upstream_revision"] != revision:
        raise ValueError("Hub resolved a different requested commit")
    write_json_exclusive(root / 'source-lock.json', lock)
    cache = root / 'download-cache'
    snapshot_download(MODEL_ID, revision=lock['upstream_revision'], token=False,
                      local_dir=str(cache), allow_patterns=list(lock['files']))
    target = root / 'snapshot'; target.mkdir()
    for name, size in lock['files'].items():
        path = cache / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError('downloaded file differs from pinned inventory')
        shutil.copyfile(path, target / name)
    write_json_exclusive(root / 'downloaded-material.json', {
        'source_lock_sha256': file_sha256(root / 'source-lock.json'),
        'snapshot_sha256': snapshot_digest(target),
        'files': {n: file_sha256(target / n) for n in lock['files']},
        'independent_material_approval': False})
    return target


class ProbeCoverageError(ValueError):
    def __init__(self, observation):
        super().__init__('strict expanded probe failed; retain actual work, not success')
        self.observation = observation


def _measure_features(torch, encoder, tokenizer, policy):
    from execution_meter import WorkLedger
    meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**12))
    features, counts = [], []
    texts = ('The engineer repaired the electric motor.',
             'A garden contains green plants and red flowers.',
             'The engineer repaired the electric motor.')
    try:
        for text in texts:
            with meter.scope('inference', 'encoder'):
                vector, tokens = vectorize_case(torch, encoder, tokenizer,
                    dict(state=text, question='Identify the subject.', options=['person', 'place']),
                    'cpu', max_tokens=128)
            features.append(vector); counts.append(tokens)
    except Exception as exc:
        raise ProbeCoverageError(meter.report()) from exc
    return features, counts, meter.report()


def probe(snapshot, *, compare_arithmetic=False):
    import torch
    import transformers
    from transformers import AutoTokenizer
    from execution_meter import TRANSFORMER_POLICY_SCHEMA, EXTENDED_POLICY_SCHEMA
    from transformer_work import PROFILE
    from head_surgery import tensor_inventory
    if type(compare_arithmetic) is not bool:
        raise ValueError('explicit arithmetic comparison flag required')
    torch.set_num_threads(1)
    before = snapshot_digest(snapshot)
    complete, encoder, receipt = load_complete_mlm(snapshot)
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True, trust_remote_code=False)
    policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE,
                  mode='observe', wall_time_ns=600_000_000_000,
                  max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)
    # Same loaded weights and inputs for both passes; no additional model copy.
    def forbidden(*args):
        raise AssertionError('retained MLM head must not run in feature-only path')
    handle = complete.head.register_forward_pre_hook(forbidden)
    comparison = None
    try:
        features, token_counts, observation = _measure_features(torch, encoder, tokenizer, policy)
        if compare_arithmetic:
            from transformer_work_v3 import PROFILE as expanded_profile
            expanded = {**policy, 'schema': EXTENDED_POLICY_SCHEMA,
                        'arithmetic_profile': expanded_profile, 'mode': 'strict'}
            current, lengths, measured = _measure_features(torch, encoder, tokenizer, expanded)
            if (measured['unknown_operators'] or measured['stopped'] is not None
                    or measured['phase_flops']['inference'] is None):
                raise ProbeCoverageError(measured)
            if lengths != token_counts:
                raise ValueError('input token identities changed across accounting profiles')
            for left, right in zip(features, current, strict=True):
                torch.testing.assert_close(left, right, rtol=0, atol=0)
            # Byte identity is diagnostic only, not signed outcome provenance.
            import hashlib
            digest = lambda v: hashlib.sha256(v.contiguous().numpy().tobytes()).hexdigest()
            comparison = dict(schema='hepta.same-checkpoint-arithmetic-comparison.v1',
                previous_observation=observation, previous_feature_sha256=[digest(v) for v in features],
                current_feature_sha256=[digest(v) for v in current], feature_values_exact=True,
                calls_per_profile=3, accounting_only=True, performance_comparison=False,
                complete_scope='observed_CPU_FP32_ATen_formula_work_only',
                full_system_cost_measured=False, hardware_instruction_count=False)
            features, observation = current, measured
    finally:
        handle.remove()
    torch.testing.assert_close(features[0], features[2], rtol=0, atol=0)
    if torch.equal(features[0], features[1]):
        raise ValueError('different inputs yielded identical feature vectors')
    verify_loaded_safetensors(torch, complete, snapshot, tied_aliases=TIED_ALIASES)
    if snapshot_digest(snapshot) != before:
        raise ValueError('checkpoint bytes changed during probe')
    result = dict(schema='hepta.public-encoder-probe.v1', snapshot_sha256=before,
                complete_checkpoint=receipt, retained_tensor_inventory=tensor_inventory(complete),
                feature_dimension=encoder.config.hidden_size, token_counts=token_counts,
                inference_calls=3, repeated_input_exact=True, different_input_distinguished=True,
                observation=observation, pretrained_provenance_independently_verified=False,
                parameter_training_performed=False, efficacy_established=False,
                paired_experiment_completed=False, production_authorized=False,
                runtime={'torch':torch.__version__, 'transformers':transformers.__version__})
    if comparison is not None:
        result.update(schema='hepta.public-encoder-probe.v2', inference_calls=6,
                      arithmetic_comparison=comparison)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--snapshot')
    choice.add_argument('--acquire-public', action='store_true')
    parser.add_argument('--output', required=True)
    parser.add_argument('--compare-arithmetic', action='store_true')
    parser.add_argument('--upstream-revision', default='main')
    args = parser.parse_args()
    root = Path(args.output); root.mkdir(parents=True, exist_ok=False)
    try:
        if not args.acquire_public and args.upstream_revision != 'main':
            raise ValueError('upstream revision applies only to explicit public acquisition')
        snapshot = acquire_public(root, revision=args.upstream_revision) if args.acquire_public else Path(args.snapshot)
        result = probe(snapshot, compare_arithmetic=args.compare_arithmetic)
        result['accounting_source_sha256'] = {name: file_sha256(Path(__file__).with_name(name))
            for name in ('aten_work.py', 'transformer_work.py', 'transformer_work_v3.py', 'execution_meter.py')}
        result['source_kind'] = ('pinned_public_Hub_checkpoint' if args.acquire_public
                                 else 'operator_supplied_local_checkpoint')
        result['probe_source_sha256'] = file_sha256(__file__)
        write_json_exclusive(root / 'probe.json', result)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    except Exception as exc:
        failure = {'error_type':type(exc).__name__, 'completed':False, 'production_authorized':False}
        if isinstance(exc, ProbeCoverageError):
            failure['work_observation'] = exc.observation
        write_json_exclusive(root / 'FAILED.json', failure)
        raise


if __name__ == '__main__':
    main()
