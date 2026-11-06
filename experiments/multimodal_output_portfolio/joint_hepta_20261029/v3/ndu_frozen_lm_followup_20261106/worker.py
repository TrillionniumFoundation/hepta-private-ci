"""Offline frozen CPU inference worker; one bounded request per process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parent


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            result.update(chunk)
    return result.hexdigest()


def verify_model(directory, materialized):
    declared = json.loads((ROOT/'model_manifest.json').read_text())
    actual = json.loads(materialized.read_text())
    if actual['manifest_sha256'] != sha(ROOT/'model_manifest.json'):
        raise ValueError('Materialization is not bound to the published model')
    if actual['model_id'] != declared['model_id'] or actual['revision'] != declared['revision']:
        raise ValueError('Model identity differs')
    files = {row['name']: row for row in actual['files']}
    if set(files) != {row['name'] for row in declared['files']}:
        raise ValueError('Model file inventory differs')
    for row in declared['files']:
        path = directory/row['name']
        if path.is_symlink() or path.stat().st_size != row['bytes'] or sha(path) != files[row['name']]['sha256']:
            raise ValueError('Actual model file differs')
        if row.get('sha256') and sha(path) != row['sha256']:
            raise ValueError('Published weight SHA differs')
        if not row.get('sha256'):
            data = path.read_bytes()
            git = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if git != row['git_blob']:
                raise ValueError('Published tokenizer/configuration blob differs')
    return declared


def fingerprint(model):
    result = hashlib.sha256()
    for name, parameter in sorted(model.named_parameters()):
        result.update(json.dumps([name, list(parameter.shape), str(parameter.dtype)]).encode())
        result.update(parameter.detach().contiguous().numpy().tobytes())
    return result.hexdigest()


def generate(directory, materialized, receipts):
    started, cpu = time.perf_counter(), time.process_time()
    request = json.load(sys.stdin)
    if set(request) != {'prompt'} or not isinstance(request['prompt'], str) or len(request['prompt']) > 16000:
        raise ValueError('Bounded prompt required')
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        os.environ[name] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    identity = verify_model(directory, materialized)
    protocol = json.loads((ROOT/'protocol.json').read_text())
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig
    torch.set_num_threads(protocol['cpu_threads'])
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(directory, local_files_only=True,
            trust_remote_code=False, use_safetensors=True, dtype=torch.float32, attn_implementation='eager')
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    before = fingerprint(model)
    messages = [{'role': 'system', 'content': protocol['system_prompt']},
                {'role': 'user', 'content': request['prompt']}]
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True,
              tokenize=True, return_dict=True, return_tensors='pt')
    input_tokens = int(inputs['input_ids'].shape[-1])
    if input_tokens > protocol['max_input_tokens']:
        raise ValueError('Input token cap exceeded; no silent truncation')
    decoding = GenerationConfig(do_sample=False, num_beams=1, use_cache=True,
               max_new_tokens=protocol['max_output_tokens'], eos_token_id=tokenizer.eos_token_id,
               pad_token_id=tokenizer.eos_token_id, bos_token_id=tokenizer.bos_token_id)
    inference_started = time.perf_counter()
    with torch.inference_mode():
        output = model.generate(**inputs, generation_config=decoding)
    inference_seconds = time.perf_counter()-inference_started
    tokens = output[0, input_tokens:].tolist()
    text = tokenizer.decode(tokens, skip_special_tokens=True)
    after = fingerprint(model)
    if before != after or any(p.requires_grad for p in model.parameters()):
        raise ValueError('Frozen parameter invariant failed')
    response = {'model_id': identity['model_id'], 'revision': identity['revision'], 'text': text,
                'provider_request_id': uuid.uuid4().hex,
                'usage': {'input_tokens': input_tokens, 'output_tokens': len(tokens), 'cached_input_tokens': 0},
                'local_evidence': {'parameters': sum(p.numel() for p in model.parameters()),
                    'parameter_sha256_before': before, 'parameter_sha256_after': after,
                    'model_manifest_sha256': sha(ROOT/'model_manifest.json'),
                    'materialized_manifest_sha256': sha(materialized), 'worker_sha256': sha(Path(__file__)),
                    'protocol_sha256': sha(ROOT/'protocol.json'), 'torch': torch.__version__,
                    'device': 'cpu', 'dtype': 'float32', 'threads': protocol['cpu_threads'],
                    'output_token_ids': tokens, 'generation_seconds': inference_seconds,
                    'worker_wall_seconds': time.perf_counter()-started,
                    'worker_cpu_seconds': time.process_time()-cpu,
                    'actual_host_currency_cost': None, 'external_paid_model_calls': 0}}
    encoded = json.dumps(response, sort_keys=True, allow_nan=False)+'\n'
    receipts.mkdir(parents=True, exist_ok=True)
    with (receipts/(response['provider_request_id']+'.json')).open('x') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(encoded, end='')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-directory', type=Path, required=True)
    parser.add_argument('--materialized', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    args = parser.parse_args()
    try:
        generate(args.model_directory, args.materialized, args.receipts)
    except Exception as exc:
        args.receipts.mkdir(parents=True, exist_ok=True)
        error = {'status': 'worker_failure', 'exception': type(exc).__name__,
                 'traceback': traceback.format_exc(), 'worker_sha256': sha(Path(__file__))}
        with (args.receipts/('failure-'+uuid.uuid4().hex+'.json')).open('x') as stream:
            json.dump(error, stream, indent=2)
        print(json.dumps({'_transport_error': type(exc).__name__}))
        raise SystemExit(1)
