"""Execute a pinned public T5 text interface; no NDU or quality claim."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import time
import urllib.request

import numpy as np
import torch
from transformers import AutoTokenizer, T5ForConditionalGeneration


REVISION = 'df1b051c49625cf57a3d0d8d3863ed4d13564fe4'
MODEL_ID = 'google-t5/t5-small'
WEIGHT_SHA256 = 'bd944e5f1b3ad9b70dd9d00010a517059e19265671076b8b0a4a58d9491842bc'
FILES = {
    'README.md': (8473, 'ec7fe4d8539a6aa166b27598bd402329eedc4305'),
    'config.json': (1206, '378f74060b20f6a9a1ea41b03fc0504466206255'),
    'generation_config.json': (147, 'd52815623b46b7db1c4b957b5a83a8ad30b0146a'),
    'spiece.model': (791656, '4e28ff6ebdf584f5372d9de68867399142435d9a'),
    'tokenizer.json': (1389353, '41911369be79611d82d152725113e66206bd7b79'),
    'tokenizer_config.json': (2324, '4fd6c49c32ecf41886dba213d40030f063c72b07'),
    'model.safetensors': (242043056, None),
}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def prepare_assets(directory):
    directory.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, (size, git_blob) in FILES.items():
        path = directory / name
        url = f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}'
        if not path.exists():
            temporary = path.with_suffix(path.suffix + '.partial')
            count = 0
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('xb') as stream:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    count += len(block)
                    if count > size:
                        raise ValueError(f'{name}: download exceeds pinned size')
                    stream.write(block)
            temporary.rename(path)
        if path.stat().st_size != size:
            raise ValueError(f'{name}: pinned size mismatch')
        sha = digest(path)
        if name == 'model.safetensors':
            if sha != WEIGHT_SHA256:
                raise ValueError('checkpoint does not match upstream LFS SHA256')
        else:
            actual_blob = hashlib.sha1(f'blob {size}\0'.encode() + path.read_bytes()).hexdigest()
            if actual_blob != git_blob:
                raise ValueError(f'{name}: upstream Git blob mismatch')
        records[name] = dict(url=url, bytes=size, sha256=sha, upstream_git_blob=git_blob)
    return records


def execute(args):
    started = time.perf_counter()
    cpu_started = time.process_time()
    if args.output.exists() or args.receipt.exists():
        raise FileExistsError('use a new output directory and receipt')
    args.output.mkdir(parents=True)
    stage = 'assets'
    try:
        assets = prepare_assets(args.assets)
        assets_wall = time.perf_counter() - started
        stage = 'model_load'
        load_start = time.perf_counter()
        torch.set_num_threads(1)
        tokenizer = AutoTokenizer.from_pretrained(
            args.assets, local_files_only=True, trust_remote_code=False, use_fast=True)
        model = T5ForConditionalGeneration.from_pretrained(
            args.assets, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, attn_implementation='eager').cpu().eval()
        model_load_wall = time.perf_counter() - load_start
        caption_bytes = args.caption.read_bytes()
        caption = caption_bytes.decode('utf-8').strip()
        if not caption:
            raise ValueError('empty caption')
        tokenized = tokenizer(caption, return_tensors='pt', truncation=False)
        if not 0 < tokenized['input_ids'].shape[1] <= 256:
            raise ValueError('caption exceeds declared smoke token cap')

        linear_macs = 0

        def count_linear(module, inputs, output):
            nonlocal linear_macs
            linear_macs += output.numel() * module.in_features

        hooks = [module.register_forward_hook(count_linear)
                 for module in model.modules() if isinstance(module, torch.nn.Linear)]
        stage = 'inference'
        inference_start = time.perf_counter()
        inference_cpu_start = time.process_time()
        with torch.inference_mode():
            hidden = model.get_encoder()(**tokenized).last_hidden_state
            start_token = torch.tensor([[model.config.decoder_start_token_id]])
            logits = model(**tokenized, decoder_input_ids=start_token).logits
            generated = model.generate(**tokenized, max_new_tokens=32,
                                       do_sample=False, num_beams=1)
        inference_wall = time.perf_counter() - inference_start
        inference_cpu = time.process_time() - inference_cpu_start
        for hook in hooks:
            hook.remove()
        if not bool(torch.isfinite(hidden).all() and torch.isfinite(logits).all()):
            raise ValueError('nonfinite pretrained-model output')
        output_text = tokenizer.decode(generated[0], skip_special_tokens=True)
        arrays = dict(input_ids=tokenized['input_ids'].numpy(),
                      attention_mask=tokenized['attention_mask'].numpy(),
                      encoder_hidden=hidden.numpy(), decoder_first_logits=logits.numpy(),
                      generated_ids=generated.numpy())
        np.savez_compressed(args.output / 'text-interface-tensors.npz', **arrays)
        (args.output / 'decoded-output.txt').write_text(output_text + '\n')
        packages = ['torch', 'numpy', 'transformers', 'tokenizers', 'safetensors',
                    'huggingface-hub', 'sentencepiece']
        module_path = Path(sys.modules[T5ForConditionalGeneration.__module__].__file__)
        record = dict(
            schema='hepta.natural-text-interface-smoke.v1', completed=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            command=sys.argv, script_sha256=digest(Path(__file__)),
            model=dict(id=MODEL_ID, revision=REVISION, license='Apache-2.0',
                       card_url=f'https://huggingface.co/{MODEL_ID}/blob/{REVISION}/README.md',
                       parameter_count=sum(p.numel() for p in model.parameters()),
                       assets=assets, remote_code_executed=False, safetensors=True,
                       implementation_module=str(module_path),
                       implementation_sha256=digest(module_path)),
            input=dict(path=str(args.caption), sha256=hashlib.sha256(caption_bytes).hexdigest(),
                       bytes=len(caption_bytes), text=caption, language='de',
                       provenance='existing human Commons description; not a timed transcript',
                       task_prefix=None, task_quality_evaluation=False),
            runtime=dict(python=platform.python_version(), platform=platform.platform(),
                         packages={p: importlib.metadata.version(p) for p in packages},
                         device='cpu', torch_threads=torch.get_num_threads(),
                         cuda_available=torch.cuda.is_available()),
            outputs={key: dict(shape=list(value.shape), dtype=str(value.dtype),
                               finite=bool(np.isfinite(value).all()),
                               sha256=hashlib.sha256(value.tobytes()).hexdigest())
                     for key, value in arrays.items()},
            decoded_text=output_text,
            generation=dict(max_new_tokens=32, do_sample=False, num_beams=1,
                            token_count=int(generated.shape[1])),
            work=dict(asset_preparation_wall_seconds=assets_wall,
                      model_load_wall_seconds=model_load_wall,
                      inference_wall_seconds=inference_wall,
                      inference_process_cpu_seconds=inference_cpu,
                      total_wall_seconds=time.perf_counter() - started,
                      total_process_cpu_seconds=time.process_time() - cpu_started,
                      max_rss_linux_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      linear_macs_only=linear_macs,
                      mac_exclusions=['attention matmul', 'embeddings', 'softmax and activations',
                                      'layer normalization', 'sampling/control', 'loading']),
            scope=dict(pretrained_encoder_executed=True, pretrained_decoder_executed=True,
                       bounded_autoregressive_decoding_executed=True, training=False,
                       ndu=False, multimodal_generation=False, quality_validation=False,
                       foundation_model_blocker_closed=False,
                       statement='Unprefixed German caption is an interface probe, not a validated translation or summarization task.'))
        record['artifacts'] = {p.name: dict(bytes=p.stat().st_size, sha256=digest(p))
                               for p in args.output.iterdir() if p.is_file()}
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
        (args.output / 'text-interface-receipt.json').write_bytes(args.receipt.read_bytes())
        print(json.dumps(dict(completed=True, model_parameters=record['model']['parameter_count'],
                              hidden_shape=list(hidden.shape), decoded_text=output_text,
                              inference_wall_seconds=inference_wall)))
    except Exception as error:
        (args.output / 'failure.json').write_text(json.dumps(dict(
            completed=False, stage=stage, error_type=type(error).__name__, error=str(error),
            wall_seconds=time.perf_counter() - started), indent=2) + '\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--caption', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    execute(parser.parse_args())
