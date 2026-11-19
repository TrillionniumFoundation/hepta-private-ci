"""Pinned model execution evidence on public media; no task quality scoring."""
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np
import torch

sys.path.insert(0, '/workspace/scratch/f1f83ab8f2f0/hepta/qa/stem-bakeoff')
from feature_bundle import MODALITIES
from real_encoder import FrozenRealEncoder, canonical_sha256, source_digests
from real_media_probe import input_tensor_manifest
from shared_feature_contract import SourceEvent
from shared_feature_extract import SharedFeatureEncoder

torch.set_num_threads(4)
root = Path(__file__).parent
meta = json.loads(Path('/tmp/hepta-eg2-sealed-20261023.acquisition.json').read_text())
began = time.perf_counter()
owner = FrozenRealEncoder(candidate='embeddinggemma2_740m',
    snapshot='/tmp/hepta-eg2-sealed-20261023', revision=meta['revision'],
    expected_inventory_sha256=meta['inventory_sha256'], operator_accepted_terms=True,
    max_tokens=1024, profile='full')
shared = SharedFeatureEncoder(owner)
results = {}
print(json.dumps({'stage':'model_loaded','accounting':owner.accounting,'load_ms':owner.load_ms}), flush=True)


def extract(label, text, event, acquisition=None, record=None):
    runs = {}
    vectors = []
    for retention in ('tokens', 'global'):
        calls = {'model':0, 'vision':0, 'audio':0}
        observed_inputs = []
        def observed(module, args, kwargs):
            calls['model'] += 1
            observed_inputs.append(input_tensor_manifest(kwargs))
        def vision(module, args):
            calls['vision'] += 1
        def audio(module, args):
            calls['audio'] += 1
        hooks = [owner._model.register_forward_pre_hook(observed, with_kwargs=True),
                 owner._model.vision_tower.register_forward_pre_hook(vision),
                 owner._model.audio_tower.register_forward_pre_hook(audio)]
        try:
            if record is None:
                batch = shared.extract_text([text], events=[event], expected_identity=owner.identity,
                                            retention=retention)
                expected_source = source_digests([text], [asdict(event)])[0]
            else:
                batch = shared.extract_records([record], events=[event], media_root=root,
                    expected_identity=owner.identity, retention=retention)
                modality = next(key for key in record if key != 'text')
                media = [('text', hashlib.sha256(text.encode()).hexdigest()),
                         (modality, acquisition['sha256'])]
                expected_source = canonical_sha256({
                    'text_source':source_digests([text], [asdict(event)])[0], 'media_sources':media})
            batch.verify_integrity()
            assert batch.source_record_digests == (expected_source,)
            assert calls['model'] == 1
            assert calls['vision'] == int(label == 'image')
            assert calls['audio'] == int(label == 'audio')
            assert len(observed_inputs) == 1
            views = batch.snapshot()
            assert 'time_spans' not in views and 'region_boxes' not in views
            counts = {}
            if retention == 'tokens':
                valid, kinds = views['token_valid'], views['modality_ids']
                counts = {name:int(((kinds == index) & valid).sum())
                          for index,name in enumerate(MODALITIES)}
                assert counts[label] > 0
            else:
                assert batch.read_tokens() is None and batch.read_locations() == {}
            for name, value in views.items():
                np.save(root/f'{label}_{retention}_{name}.npy', value.numpy(), allow_pickle=False)
            vectors.append(batch.read_global())
            runs[retention] = {'forward_receipt':dict(shared.last_receipt),
                'batch_manifest':batch.manifest(), 'base_bundle_manifest':batch.bundle.manifest(),
                'observed_module_calls':calls, 'model_input_tensors':observed_inputs[0],
                'native_token_counts':counts,
                'global_shape':list(views['global_features'].shape),
                'token_shape':list(views['token_features'].shape) if retention == 'tokens' else None,
                'retained_view_files':{name:{'file':f'{label}_{retention}_{name}.npy',
                    'sha256':hashlib.sha256((root/f'{label}_{retention}_{name}.npy').read_bytes()).hexdigest()}
                    for name in views}}
        finally:
            for hook in hooks:
                hook.remove()
        print(json.dumps({'stage':'forward_completed', 'label':label, 'retention':retention,
            'calls':calls, 'forward_ms':shared.last_receipt['forward_ms'],
            'retained_tensor_bytes':batch.retained_tensor_bytes}), flush=True)
    difference = float((vectors[0]-vectors[1]).abs().max())
    assert difference == 0.0
    result = {'label':label, 'source':acquisition, 'text':text, 'event':asdict(event),
        'max_global_retention_mode_difference':difference, 'runs':runs,
        'input_kind':'public-media-execution-fixture-without-quality-labels',
        'quality_qualified':False, 'authority':'DENY_ALL'}
    (root/f'eg2_{label}_receipt.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    results[label] = result


try:
    extract('text', 'Read the evidence before choosing the next diagnostic action.',
            SourceEvent('interface-smoke:eg2-text', 'v1', observed_at_ns=time.time_ns()))
    image_source = json.loads((root/'image_acquisition.json').read_text())
    extract('image', 'A photograph.', SourceEvent(image_source['url'], image_source['sha256'],
        observed_at_ns=image_source['retrieved_at_ns']), acquisition=image_source,
        record={'text':'A photograph.', 'image':'coco_000000039769.jpg'})
    audio_source = json.loads((root/'audio_acquisition.json').read_text())
    extract('audio', 'A recorded steam-train whistle.',
        SourceEvent(audio_source['url'], audio_source['sha256'],
            observed_at_ns=audio_source['retrieved_at_ns'], time_start_ms=0,
            time_end_ms=round(audio_source['duration_ms'])), acquisition=audio_source,
        record={'text':'A recorded steam-train whistle.', 'audio':'steam_train_whistle.wav'})
    summary = {'schema':'hepta.shared-eg2-public-media-smoke.v1', 'status':'EXECUTED',
        'checkpoint_inventory_sha256':meta['inventory_sha256'],
        'extractor_sha256':shared.extractor_sha256, 'loaded_model':owner.accounting,
        'model_forward_calls_total':owner._calls, 'elapsed_ms':1000*(time.perf_counter()-began),
        'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'retained_modes':{label:{mode:data['forward_receipt']['retained_tensor_bytes']
            for mode,data in result['runs'].items()} for label,result in results.items()},
        'quality_qualified':False, 'authority':'DENY_ALL'}
    (root/'eg2_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary), flush=True)
except Exception as error:
    failure = {'status':'FAILED','type':type(error).__name__,'reason':str(error),
               'model_forward_calls_total':owner._calls, 'completed':list(results)}
    (root/'eg2_failure.json').write_text(json.dumps(failure,indent=2)+'\n')
    print(json.dumps(failure), flush=True)
    raise
finally:
    del shared, owner
    gc.collect()
