"""Load the native outer MLM, then verify every frozen body tensor byte."""

import argparse
import hashlib
import json
from pathlib import Path

import torch
from safetensors import safe_open
from transformers import AutoModelForMaskedLM


SNAPSHOT = Path('/data/hepta-decisioncell-models/LiquidAI--LFM2.5-Encoder-230M/0b649ad0c684378b03d4d8304f7577a662ab89bc')
CUSTOM_SHA = 'f171f518be2a07da48b17fdea5655cad0a2452ab548e90e8ae903143686647e2'


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_receipt(value):
    if isinstance(value, dict):
        return {key: json_receipt(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [json_receipt(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [json_receipt(item) for item in value]
    return value


def load_frozen_body():
    if sha_file(SNAPSHOT / 'modeling_lfm2_bidirectional.py') != CUSTOM_SHA:
        raise ValueError('reviewed local model implementation changed')
    outer, loading = AutoModelForMaskedLM.from_pretrained(str(SNAPSHOT), local_files_only=True,
        trust_remote_code=True, dtype=torch.float32, attn_implementation='sdpa',
        output_loading_info=True)
    if loading.get('missing_keys') or loading.get('mismatched_keys') or loading.get('unexpected_keys'):
        raise ValueError('native outer checkpoint did not load strictly: ' + str(loading))
    body = outer.lfm2
    if outer.lm_head.weight.data_ptr() != body.embed_tokens.weight.data_ptr():
        raise ValueError('native output head is not tied to the verified embedding')
    body.eval().requires_grad_(False)
    files = sorted(SNAPSHOT.glob('*.safetensors'))
    if not files:
        raise ValueError('native safetensors checkpoint required')
    locations = {}
    for path in files:
        with safe_open(str(path), framework='pt', device='cpu') as checkpoint:
            for key in checkpoint.keys():
                if key in locations:
                    raise ValueError('duplicate checkpoint key across shards')
                locations[key] = path
    body_state = body.state_dict()
    expected_keys = {'lfm2.' + name for name in body_state}
    if set(locations) - expected_keys - {'lm_head.weight'}:
        raise ValueError('checkpoint contains unknown non-body state')
    if expected_keys - set(locations):
        raise ValueError('checkpoint lacks a native body state tensor')
    digest = hashlib.sha256()
    matched_bytes, matched = 0, []
    for name, tensor in sorted(body_state.items()):
        key = 'lfm2.' + name
        with safe_open(str(locations[key]), framework='pt', device='cpu') as checkpoint:
            original = checkpoint.get_tensor(key)
            actual = tensor.detach().cpu().contiguous()
            if (actual.shape != original.shape or actual.dtype != original.dtype
                    or not torch.equal(actual.view(torch.uint8), original.contiguous().view(torch.uint8))):
                raise ValueError('native body differs from checkpoint tensor bytes: ' + key)
        if actual.dtype != torch.float32 or not bool(torch.isfinite(actual).all()):
            raise ValueError('finite FP32 body tensors required')
        tensor_bytes = actual.numel() * actual.element_size()
        matched_bytes += tensor_bytes
        descriptor = {'name': name, 'checkpoint_key': key, 'shape': list(actual.shape),
                      'dtype': str(actual.dtype), 'bytes': tensor_bytes}
        digest.update(json.dumps(descriptor, sort_keys=True, separators=(',', ':')).encode())
        digest.update(memoryview(actual.numpy()).cast('B'))
        matched.append(descriptor)
    receipt = {'loader': 'AutoModelForMaskedLM native outer, then .lfm2',
        'checkpoint_revision': SNAPSHOT.name, 'custom_code_sha256': CUSTOM_SHA,
        'checkpoint_files': {p.name: {'sha256': sha_file(p), 'bytes': p.stat().st_size} for p in files},
        'loading_info': json_receipt(loading), 'body_state_tensor_count': len(matched),
        'body_state_tensor_bytes': matched_bytes, 'body_state_sha256': digest.hexdigest(),
        'every_body_tensor_bitwise_equal_to_checkpoint': True,
        'native_output_embedding_tie_verified': True, 'matched_state': matched,
        'encoder_forwards': 0, 'evaluation_labels_read': False}
    return body, receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    path = Path(parser.parse_args().output)
    if path.exists():
        raise ValueError('new standalone loading receipt path required')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    body, receipt = load_frozen_body()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps({key: receipt[key] for key in ('loader', 'body_state_tensor_count',
        'body_state_tensor_bytes', 'body_state_sha256', 'every_body_tensor_bitwise_equal_to_checkpoint')}), flush=True)
