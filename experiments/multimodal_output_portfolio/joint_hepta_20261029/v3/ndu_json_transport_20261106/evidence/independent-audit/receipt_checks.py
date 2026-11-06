"""Independent receipt helpers; no runner/decoder imports or model/tool calls."""
from datetime import datetime
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys


REL = Path('experiments/multimodal_output_portfolio/joint_hepta_20261029/v3')
LOCAL = 'ndu_json_transport_20261106'
UPSTREAM = 'ndu_frozen_lm_followup_20261106'
PUBLIC_KEYS = ('task_id', 'family', 'source_cluster', 'question', 'answer_format')
SQL_SCHEMA = ('Artist(ArtistId,Name); Album(AlbumId,Title,ArtistId); '
              'Genre(GenreId,Name); Track(TrackId,Name,AlbumId,GenreId,Milliseconds); '
              'Invoice(InvoiceId,BillingCountry,Total).')


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            result.update(block)
    return result.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def need(value, label):
    if not value:
        raise AssertionError(label)


def near(first, second):
    return math.isclose(first, second, rel_tol=1e-10, abs_tol=1e-6)


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def public_prompt(task, stage, observation=None):
    text = task['question']+'\nRequired answer format: '+task['answer_format']+'.'
    if task['family'] == 'sqlite_query':
        text += '\nPublic SQLite schema: '+SQL_SCHEMA
    if stage == 'plan':
        instruction = ('Return only a JSON object with exactly one key "query" whose value is one read-only SQLite SELECT statement.'
                       if task['family'] == 'sqlite_query' else
                       'Return only a JSON object for a source search, either {"needle":"literal search text"} or {"start_line":1,"line_count":20}.')
        return text+'\nYou may make exactly one tool call on the pinned source. '+instruction
    need(stage in ('direct', 'answer'), 'Public prompt stage')
    if observation is not None:
        text += '\nActual tool observation:\n'+json.dumps(observation, sort_keys=True, allow_nan=False)
    return text+'\nReturn only the requested JSON answer. Do not include Markdown, prose or a tool call.'


class Rejection(ValueError):
    pass


def decode_reference(text, schema, stage):
    """Reconstruct the declared bytes/envelope/schema without importing adapter."""
    record = dict(stage=stage, schema=schema, raw_sha256=None, body_sha256=None, envelope=None)
    def reject(code):
        raise Rejection(code)
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                reject('duplicate_key')
            result[key] = value
        return result
    def finite(token):
        value = float(token)
        if not math.isfinite(value):
            reject('nonfinite_number')
        return value
    try:
        if type(text) is not str:
            reject('text_type')
        try:
            raw = text.encode('utf-8')
        except UnicodeEncodeError:
            reject('invalid_unicode')
        record['raw_sha256'] = hashlib.sha256(raw).hexdigest()
        if not raw or len(raw) > 65536:
            reject('text_size')
        body, envelope = raw.strip(b' \t\r\n'), 'native_json'
        if body.startswith(b'```'):
            openings, closings = (b'```json\r\n', b'```json\n'), (b'\r\n```', b'\n```')
            opening = next((x for x in openings if body.startswith(x)), None)
            closing = next((x for x in closings if body.endswith(x)), None)
            if opening is None or closing is None:
                reject('invalid_envelope')
            body, envelope = body[len(opening):-len(closing)], 'json_fence'
        try:
            value = json.loads(body.decode(), object_pairs_hook=unique, parse_float=finite,
                               parse_constant=lambda _: reject('nonfinite_number'))
        except Rejection:
            raise
        except (ValueError, RecursionError):
            reject('invalid_json')
        stack = [value]
        while stack:
            item = stack.pop()
            if type(item) is str:
                try:
                    item.encode('utf-8')
                except UnicodeEncodeError:
                    reject('invalid_unicode')
            elif type(item) is list:
                stack.extend(item)
            elif type(item) is dict:
                stack.extend(item.keys()); stack.extend(item.values())
        if schema == 'sql_query':
            valid = (type(value) is dict and set(value) == {'query'} and type(value['query']) is str
                     and 1 <= len(value['query']) <= 4000)
        elif schema == 'source_read':
            valid = (type(value) is dict and
                     ((set(value) == {'needle'} and type(value['needle']) is str and 1 <= len(value['needle']) <= 128) or
                      (set(value) == {'start_line', 'line_count'} and type(value['start_line']) is int
                       and value['start_line'] >= 1 and type(value['line_count']) is int and 1 <= value['line_count'] <= 120)))
        elif schema == 'rows_answer':
            valid = (type(value) is list and len(value) <= 50 and all(type(row) is list and len(row) <= 32
                     and all(cell is None or type(cell) in (str, int, float, bool) for cell in row) for row in value))
        elif schema == 'strings_answer':
            valid = type(value) is list and all(type(x) is str for x in value)
        elif schema == 'qualification':
            valid = type(value) is list and len(value) == 1 and type(value[0]) is int and value[0] == 1
        else:
            reject('unknown_schema')
        if not valid:
            reject('schema_mismatch')
        record.update(value=value, body_sha256=hashlib.sha256(body).hexdigest(), envelope=envelope, status='accepted')
    except Rejection as error:
        record.update(status='rejected', rejection_code=str(error))
    return record


def parameter_fingerprint(path):
    """Reuse the earlier audit's exact BF16 expansion method, without a model."""
    import numpy as np
    result, count, intervals = hashlib.sha256(), 0, []
    with path.open('rb') as stream:
        header_bytes = int.from_bytes(stream.read(8), 'little')
        header = json.loads(stream.read(header_bytes))
        tensors = {key: value for key, value in header.items() if key != '__metadata__'}
        for name, item in sorted(tensors.items()):
            need(item['dtype'] == 'BF16', 'BF16 tensor source')
            start, end = item['data_offsets']; size = math.prod(item['shape'])
            need(end-start == size*2, 'Tensor byte count')
            count += size; intervals.append((start, end))
            result.update(json.dumps([name, item['shape'], 'torch.float32']).encode())
            stream.seek(8+header_bytes+start); remaining = end-start
            while remaining:
                block = stream.read(min(1048576, remaining)); need(bool(block), 'Complete tensor bytes')
                words = np.frombuffer(block, dtype='<u2').astype('<u4')
                result.update((words << 16).astype('<u4', copy=False).tobytes()); remaining -= len(block)
        intervals.sort()
        need(intervals[0][0] == 0 and all(a[1] == b[0] for a, b in zip(intervals, intervals[1:])), 'No tensor gaps/overlaps')
        need(8+header_bytes+intervals[-1][1] == path.stat().st_size, 'Full tensor file accounting')
    return dict(sha256=result.hexdigest(), parameters=count, tensor_count=len(tensors),
                method='Sorted safetensors metadata plus exact BF16-to-FP32 bit expansion; no model loaded.')


def verify_model(source, runtime):
    manifest, actual = read(source/'model_manifest.json'), read(source/'evidence/acquisition/materialized-model.json')
    need(actual['manifest_sha256'] == sha(source/'model_manifest.json'), 'Materialized manifest binding')
    need(all(actual[k] == manifest[k] for k in ('model_id', 'revision')), 'Fixed model identity')
    files = {row['name']: row for row in actual['files']}
    need(set(files) == {row['name'] for row in manifest['files']} == {p.name for p in (runtime/'model').iterdir()}, 'Complete model files')
    observed = {}
    for row in manifest['files']:
        path = runtime/'model'/row['name']; hashed = sha(path)
        need(not path.is_symlink() and path.stat().st_size == row['bytes'] == files[row['name']]['bytes'], 'Model file size/type')
        need(hashed == files[row['name']]['sha256'], 'Materialized file hash')
        if 'sha256' in row:
            need(hashed == row['sha256'], 'Published weight hash')
        else:
            raw = path.read_bytes()
            need(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == row['git_blob'], 'Tokenizer/config Git blob')
        observed[row['name']] = dict(sha256=hashed, bytes=path.stat().st_size)
    return manifest, observed, parameter_fingerprint(runtime/'model/model.safetensors')


def verify_runtime(source):
    manifest = read(source/'evidence/acquisition/runtime-manifest.json')
    need(sys.version == manifest['python'] and platform.platform() == manifest['platform'], 'Python/platform metadata')
    for row in manifest['packages']:
        package = importlib.metadata.distribution(row['name'])
        need(package.version == row['version'], 'Installed package version: '+row['name'])
        record = package.read_text('RECORD')
        need(record is not None and hashlib.sha256(record.encode()).hexdigest() == row['record_sha256'], 'RECORD digest: '+row['name'])
    return dict(packages_checked=len(manifest['packages']), python=manifest['python'],
                scope='Version/RECORD metadata checks, not independent binary attestation.')


def command_configs(recorded, output_name, manifest, materialized_sha, protocol, runner_python):
    source = recorded/'hepta-research'/REL/UPSTREAM; runtime = recorded/'round3_resources/followup_lm'
    identity = dict(kind='frozen_llm', model_id=manifest['model_id'], revision=manifest['revision'], evidence_sha256=materialized_sha)
    model = dict(kind='command', identity=identity, decoding=dict(do_sample=False, max_new_tokens=protocol['max_output_tokens']),
                 argv=[str(runtime/'venv/bin/python'), str(source/'worker.py'), '--model-directory', str(runtime/'model'),
                       '--materialized', str(source/'evidence/acquisition/materialized-model.json'), '--receipts',
                       str(recorded/'round3_resources'/output_name/'model_responses')])
    tools_file = recorded/'hepta-research'/REL/'ndu_llm_confirmation/external_smoke/tools.py'
    configs = {role: dict(kind='command', identity=dict(kind='tool', model_id=role, revision=sha(tools_file)),
                         argv=[runner_python, '-m', '.'.join(REL.parts)+'.ndu_llm_confirmation.external_smoke.tools', role])
               for role in ('sql', 'source', 'verifier')}
    return model, configs


def model_response(path, terminal, payload, source, manifest, parameter, protocol, tokenizer):
    response = read(path); evidence = response['local_evidence']; ids = evidence['output_token_ids']
    need(path.stem == response['provider_request_id'] and sha(path) == terminal['response_sha256'], 'Response filename/stdout bytes')
    need(all(response[k] == manifest[k] for k in ('model_id', 'revision')), 'Observed model/revision')
    need(terminal['observed_identity_sha256'] == digest({k: response[k] for k in ('model_id', 'revision')}), 'Observed identity hash')
    need(terminal['identity_status'] == 'match' and terminal['usage_status'] == 'reported', 'Identity and usage status')
    need(evidence['parameter_sha256_before'] == evidence['parameter_sha256_after'] == parameter['sha256'] and
         evidence['parameters'] == parameter['parameters'], 'Independently reconstructed parameter invariant')
    for key, rel in (('worker_sha256', 'worker.py'), ('protocol_sha256', 'protocol.json'), ('model_manifest_sha256', 'model_manifest.json'),
                     ('materialized_manifest_sha256', 'evidence/acquisition/materialized-model.json')):
        need(evidence[key] == sha(source/rel), 'Worker source evidence: '+key)
    need(evidence['device'] == 'cpu' and evidence['dtype'] == protocol['dtype'] and evidence['threads'] == protocol['cpu_threads']
         and evidence['torch'] == importlib.metadata.version('torch'), 'Worker runtime metadata')
    messages = [dict(role='system', content=protocol['system_prompt']), dict(role='user', content=payload['prompt'])]
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True)['input_ids']
    need(response['usage'] == terminal['usage'] == dict(input_tokens=len(inputs), output_tokens=len(ids), cached_input_tokens=0), 'Retokenized usage')
    need(tokenizer.decode(ids, skip_special_tokens=True) == response['text'], 'Exact output tokens/text')
    need(len(inputs) <= protocol['max_input_tokens'] and 0 < len(ids) <= protocol['max_output_tokens'], 'Input/output token bounds')
    need(0 <= evidence['generation_seconds'] <= evidence['worker_wall_seconds'] <= terminal['wall_seconds'], 'Worker wall hierarchy')
    need(evidence['actual_host_currency_cost'] is None and evidence['external_paid_model_calls'] == 0, 'Unknown host cost retained')
    audit = dict(request_id=terminal['request_id'], response_sha256=sha(path), request_sha256=terminal['request_sha256'],
                 input_tokens=len(inputs), output_tokens=len(ids), request_wall_seconds=terminal['wall_seconds'],
                 worker_wall_seconds=evidence['worker_wall_seconds'], worker_cpu_seconds=evidence['worker_cpu_seconds'],
                 generation_seconds=evidence['generation_seconds'])
    return response['text'], audit
