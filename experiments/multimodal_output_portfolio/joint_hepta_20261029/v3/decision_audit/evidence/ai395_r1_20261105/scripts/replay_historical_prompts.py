"""Record actual neural historical-input replays and predeclared negative controls."""
from pathlib import Path
import gc
import hashlib
import json
import platform
import resource
import sys
import time

ROOT = Path('/home/qq/work/hepta-r1-4835-20261105-w0-r1')
SOURCE = ROOT / 'source'
OUT = ROOT / 'evidence/legacy-probes'
OUT.mkdir(exist_ok=False)
TENSORS = OUT / 'tensors'
TENSORS.mkdir()
sys.path.insert(0, str(SOURCE))
start = time.process_time(), time.perf_counter()
plan_path = ROOT / 'LEGACY_PROBE_PLAN.json'
plan = json.loads(plan_path.read_text())
source_manifest = json.loads((ROOT / 'SOURCE_SUBSET.json').read_text())
for entry in source_manifest['files']:
    assert hashlib.sha256((SOURCE / entry['path']).read_bytes()).hexdigest() == entry['sha256']
(OUT / 'PLAN.json').write_bytes(plan_path.read_bytes())
images = {'original': SOURCE / 'inputs/input.png', 'generated': SOURCE / 'inputs/direct.png',
          'refined': SOURCE / 'inputs/refined.png', 'blank': ROOT / 'evidence/diagnostics/blank-white.png'}
assert hashlib.sha256(images['refined'].read_bytes()).hexdigest() == '73befbc72a86e15aeb56d89976bbf06df3f7146897b9b3986b303955606445d3'
record = {'schema': 'hepta.r1-historical-input-execution.v1', 'status': 'started',
          'source_sha': plan['source_sha'], 'source_tree': source_manifest['tree'],
          'observer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
          'host': 'ai395', 'python': sys.version, 'platform': platform.platform(),
          'training_performed': False, 'production_qualified': False,
          'energy_joules': None, 'energy_unavailable_reason': 'No whole-process energy meter configured.',
          'cases': []}
def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
write(OUT / 'EXECUTION.json', record)
try:
    import torch
    from safetensors.torch import save_file
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit import diagnostics
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.local_models import LocalModels
    def snapshot(value):
        info = diagnostics._tensor(value)
        file = TENSORS / (info['sha256'] + '.safetensors')
        if not file.exists():
            save_file({'observed': value.detach().cpu().contiguous()}, str(file),
                      metadata={'raw_tensor_sha256': info['sha256'], 'source_sha': plan['source_sha']})
        return {**info, 'artifact_relative_path': str(file.relative_to(OUT)),
                'artifact_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                'artifact_bytes': file.stat().st_size}
    for index, case in enumerate(plan['cases']):
        before = time.process_time(), time.perf_counter()
        folder = OUT / f'{index:02d}-{case["id"]}'
        folder.mkdir()
        row = {**case, 'index': index, 'status': 'started', 'model_generate_calls': 0,
               'image_sha256': hashlib.sha256(images[case['image']].read_bytes()).hexdigest(),
               'vision_outputs': []}
        backend = template_method = generate_method = hook = vision = None
        write(folder / 'TRACE.json', row)
        try:
            backend = LocalModels(ROOT / 'models/vlm', ROOT / 'models/sd', threads=plan['threads'])
            backend._activate('vlm')
            template_method = backend.processor.apply_chat_template
            generate_method = backend.model.generate
            def template_spy(*args, **kwargs):
                rendered = template_method(*args, **kwargs)
                row['rendered_prompt'] = rendered
                row['rendered_prompt_sha256'] = hashlib.sha256(rendered.encode()).hexdigest()
                return rendered
            def generation_spy(**kwargs):
                row['model_generate_calls'] += 1
                row['inputs'] = {key: snapshot(value) for key,value in kwargs.items() if torch.is_tensor(value)}
                row['input_token_ids'] = kwargs['input_ids'][0].tolist()
                row['input_tokens'] = len(row['input_token_ids'])
                result = generate_method(**kwargs)
                new = result[0, row['input_tokens']:].tolist()
                eos = backend.model.generation_config.eos_token_id
                eos = eos if isinstance(eos, list) else [eos]
                hit_eos = bool(new and new[-1] in eos)
                hit_limit = len(new) >= kwargs['max_new_tokens']
                row.update(output_token_ids=new, output_tokens=len(new), eos_token_ids=eos,
                           last_token_is_eos=hit_eos, hit_max_new_tokens=hit_limit,
                           stop_reason='eos_and_length' if hit_eos and hit_limit else 'eos' if hit_eos else 'max_new_tokens' if hit_limit else 'other')
                return result
            vision = getattr(getattr(backend.model, 'model', None), 'vision_model', None)
            if vision is not None:
                def vision_spy(module, args, result):
                    hidden = getattr(result, 'last_hidden_state', None)
                    if hidden is not None:
                        row['vision_outputs'].append(snapshot(hidden))
                hook = vision.register_forward_hook(vision_spy)
            backend.processor.apply_chat_template = template_spy
            backend.model.generate = generation_spy
            text = backend.describe(images[case['image']], case['prompt'], max_tokens=plan['max_new_tokens'])
            (folder / 'output.txt').write_text(text)
            sha = hashlib.sha256(text.encode()).hexdigest()
            row.update(status='completed', output=text, output_sha256=sha, backend=backend.identity(),
                       equals_historical_text=sha == plan['historical_output_sha256'])
        except Exception as error:
            row.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
        finally:
            if hook is not None:
                hook.remove()
            if backend is not None and template_method is not None:
                backend.processor.apply_chat_template = template_method
            if backend is not None and generate_method is not None:
                backend.model.generate = generate_method
            row['cpu_seconds'] = time.process_time() - before[0]
            row['wall_seconds'] = time.perf_counter() - before[1]
            row['cumulative_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            write(folder / 'TRACE.json', row)
            record['cases'].append({'id': row['id'], 'image': row['image'], 'role': row['role'],
                                    'status': row['status'], 'output': row.get('output'),
                                    'output_sha256': row.get('output_sha256'), 'output_tokens': row.get('output_tokens'),
                                    'stop_reason': row.get('stop_reason'),
                                    'equals_historical_text': row.get('equals_historical_text'),
                                    'cpu_seconds': row['cpu_seconds'], 'wall_seconds': row['wall_seconds'],
                                    'model_generate_calls': row['model_generate_calls']})
            write(OUT / 'EXECUTION.json', record)
            backend = template_method = generate_method = hook = vision = None
            gc.collect()
    if len(record['cases']) != 11 or any(c['status'] != 'completed' or c['model_generate_calls'] != 1 for c in record['cases']):
        raise RuntimeError('One or more registered historical/negative-control probes failed')
    record['status'] = 'completed'
except BaseException as error:
    record['status'] = 'failed';record['error'] = {'type': type(error).__name__, 'message': str(error)}
    raise
finally:
    gc.collect()
    record['cpu_seconds'] = time.process_time() - start[0]
    record['wall_seconds'] = time.perf_counter() - start[1]
    record['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    record['cost_scope'] = 'Inclusive imports, all 11 fresh VLM loads, raw observations, successful/failed probes, artifacts and cleanup before final write; shared setup/acquisition charged in parent EXECUTION.json. No new diffusion generation. Agent orchestration and transport separately unmetered.'
    record['tensor_files'] = [{'path': str(p.relative_to(OUT)), 'size': p.stat().st_size,
                              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(TENSORS.glob('*.safetensors'))]
    record['retained_tensor_bytes'] = sum(p['size'] for p in record['tensor_files'])
    write(OUT / 'EXECUTION.json', record)
    print(json.dumps(record, indent=2, allow_nan=False), flush=True)
