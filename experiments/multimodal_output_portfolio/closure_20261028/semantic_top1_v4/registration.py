"""Register the original top-one observer task before any new model fitting."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

PARENT_SOURCE = 'ad58bf5529af473f722c8e48a44f34ae07e364356b664a3a79458fecf1405b9d'
PARENT_SOURCE_FILE = '27fe1c30e95216d68b1be2d20855188db468472be85ef1839666dd2f57dacd40'
SOURCE_REGISTER = '59b91f554034db64086bebc7872aa89ca961c7095429dca8a29c06392bb02fad'
SPEC = {
    'schema': 'hepta.closure.original-top1-observer-v4.v1',
    'task_identity': 'Original two-second selected action/sound label task; four-second public context; unchanged63action/17sound ontology,112px8fps video and16kHz audio.',
    'task_revision': False,
    'runtime_versions': {'python':'3.12.14','torch':'2.8.0+cpu','torchvision':'0.23.0+cpu','numpy':'2.3.5','scipy':'1.17.0','Pillow':'12.3.0'},
    'training_sources': 512,
    'development_rule': 'Five source folds within the original observer_train role only. No old development, observer calibration, policy calibration or qualification prepared data or predictions.',
    'fold_order_seed': 'hepta-top1-v4-inner-fold-20261028',
    'fold_assignment': 'Sort source IDs by SHA256(seed+colon+source_id), then rank modulo5. Every retained event from an original video stays in its fold.',
    'mechanism_seed': 'hepta-top1-v4-mechanism-20261028',
    'mechanism_sources': 8,
    'mechanism_events': 'All originally retained events of each of the eight fixed training sources; no replacement based on result or resource failure.',
    'feature_law': {
        'video_tokens': 'Eight2048-dimensional TSM frame features before temporal mean; exact existing TSM normalization and temporal shifts.',
        'audio_tokens': 'PANN1280-dimensional convolution features after frequency mean, before global time max/mean; adaptive average into eight ordered time bins.',
        'video_pooled': 'Existing S3D1024 embedding plus400 softmax probabilities.',
        'audio_pooled': 'Existing PANN1024 embedding plus527 sigmoid probabilities.',
        'source_media': 'Frozen original v3 decode/window. Recompute features from physically serialized and reopened FFV1 RGB video and PCM16 WAV.',
        'image_and_text': 'PNG at target frame8 and the original selected-label caption are delivered and hashed for the mechanism check; they are not independent semantic observers.',
        'no_new_pretrained_model_download': True,
        'feature_storage': 'float32, per-original-video NPZ, lazy reads; no full dataset tensor copy',
    },
    'candidate_order': {
        'action': ['pooled_s3d_mlp', 'temporal_tsm', 'temporal_tsm_aux025'],
        'sound': ['pooled_pann_ridge100', 'temporal_pann', 'temporal_pann_aux025'],
    },
    'heads': {
        'pooled_s3d_mlp': '1424->128 SiLU dropout0.15 ->63; same family and hyperparameters as prior selected action baseline',
        'pooled_pann_ridge100': 'source-uniform weighted ridge; lambda100; no bias penalty; all17 classes',
        'temporal': 'feature-wise training-fold standardization; linear(D,128), learned8x128 position embeddings, SiLU, dropout0.15, linear128->1 temporal attention with softmax over8, weighted sum, linear128->class_count',
        'aux025': 'Independent linear128->class_count auxiliary head; add0.25 times mean classwise BCE against all training annotations overlapping target by at least0.15s. Primary score and caption target remain the originally selected single label.',
        'normalization': 'Source-uniform training-fold means/std only; token moments weight eight bins equally; std floor0.01 and clamp[-8,8]. No validation-fold normalization fitting.',
        'auxiliary_scope': 'Unannotated is the auxiliary training zero, not proof of physical absence. No set-based terminal reward or qualification score is introduced.',
    },
    'optimization': {
        'optimizer': 'AdamW', 'learning_rate': 0.001, 'weight_decay': 0.01,
        'steps_per_neural_fit': 1024, 'batch_size': 64, 'torch_threads': 2,
        'sampling': 'Uniform original training source, then uniform retained event within that source, with replacement.',
        'base_seed': 7319, 'fold_seed': 'base_seed+fold_index', 'final_seed': 7324,
        'seed_selection': False, 'gradient_clipping': None,
        'recover_every_steps': 64,
        'recovery_state': 'model, optimizer, sampler RNG, global RNG, fold/candidate/step, source and feature and implementation identities; retain latest recovery and completed-fit checkpoints',
    },
    'selection': {
        'metric': 'Source-uniform out-of-fold selected-label top1 accuracy, pooling exactly one held-out prediction per retained event across the five source folds.',
        'ties': 'First registered candidate in the modality candidate_order.',
        'development_gate': 'For each modality, selected candidate accuracy>=0.60 and strictly above the source-uniform majority control fitted separately on each training fold.',
        'final_fit': 'Retrain only selected family on all512 observer sources with the fixed final seed and1024steps; ridge is one deterministic solve.',
        'all_folds_and_candidates_reported': True,
    },
    'budget': {
        'cross_validation_neural_fits': 25, 'cross_validation_ridge_solves': 5,
        'cross_validation_neural_updates': 25600, 'maximum_final_neural_updates': 2048,
        'maximum_total_neural_updates': 27648,
        'dense_feature_bytes_2517_events': 298002732,
        'training_feature_and_metadata_disk_budget_bytes': 400000000,
        'model_and_recovery_budget_bytes': 50000000,
        'maximum_original_member_bytes': 12000000,
        'initial_process_headroom_minimum_bytes': 1610612736,
        'source_boundary_headroom_minimum_bytes': 402653184,
        'mechanism_minimum_free_disk_bytes': 134217728,
        'one_heavy_process_only': True,
        'estimated_peak_rss_bytes_not_yet_measured': [650000000,800000000],
        'old_recorded512source_feature_cpu_seconds': 5674.059669333997,
        'estimate_limit': 'Previous recorded feature CPU excludes surrounding download/decode and other overhead; no guaranteed new runtime or peak is inferred.',
    },
    'fresh_observer_adequacy': {
        'sources': 128, 'events_per_source': 1,
        'allocation_seed': 'hepta-top1-v4-fresh-observer-adequacy-20261028',
        'allocation': 'Same original task event eligibility and event ordering; among official valid sources, exclude every ID in the frozen1024+historical112+host16 registry, then sort SHA256(seed+colon+source_id) and take128 eligible original videos. No class, confidence or performance selection.',
        'allocation_checkpoint': 'Freeze exact source IDs/events/archive generation and byte identities before any new adequacy media/prediction access; no silent replacement if unavailable or duplicated.',
        'old_reserved_policy64_and_qualification64_used_as_calibration': False,
        'decode_access_guard': 'Selected heads, statistics, preprocessing, ontology and complete source bindings frozen; development gate passed; mechanism passed; all matching new-source IDs/receipts exact.',
        'gate': {'action_accuracy': 0.6, 'sound_accuracy': 0.6, 'strictly_above_own_training_majority_for_both': True},
        'uncertainty': 'Report per-modality binomial intervals and source-paired majority contrasts; the empirical gate is not an unconditional future-accuracy certificate.',
        'new_sources_allocated_by_this_registration': False,
    },
    'stopping': ['Any pin, source-role, label-order, shape, fresh-source or receipt mismatch stops the phase.',
                 'Insufficient measured memory/disk stops before model import/download, or at a completed source/recovery boundary; never shorten the registered training update budget to claim completion.',
                 'Mechanism numerical or codec failure retains evidence and blocks fitting pending an explicitly versioned repair; no new sample choice.',
                 'If the five-fold development gate fails, no fresh adequacy data are decoded.',
                 'If fresh adequacy fails, no generator training, policy calibration or qualification is authorized by this protocol.'],
    'mechanism_checks': {
        'precodec_pooled_reference_atol': 0.0001, 'precodec_pooled_reference_rtol': 0.0001,
        'rgb_ffv1_and_png_bit_exact': True, 'pcm16_compared_against_clipped_source': True,
        'actual_four_file_readback': True, 'cached_target_features_used_for_output_inference': False,
        'fitted_heads_or_generator_updates': 0,
    },
    'limits': ['Calibration is originally selected-label recognition on serialized original clips, not general open-domain generation.',
               'Actual generated-output semantic reliability needs separate output-distribution evidence and fixed negative controls; original-media accuracy alone does not prove it.',
               'No current policy/qualification consumption or physical-CPU tail certificate is introduced.',
               'Three published action classes are absent from the entire official training annotation inventory; retain every class and report this limitation.'],
}


def digest(value):
    if not isinstance(value, bytes): value=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(value).hexdigest()


def freeze(assets, output):
    parent=Path(__file__).parent.parent
    source_path=assets/'SOURCE_PROTOCOL.json'
    if digest(source_path.read_bytes())!=PARENT_SOURCE_FILE: raise ValueError('Parent source bytes changed')
    source=json.loads(source_path.read_text())
    if source['protocol_sha256']!=PARENT_SOURCE: raise ValueError('Parent task changed')
    register_path=parent/'data_source_usage_register.json'
    if digest(register_path.read_bytes())!=SOURCE_REGISTER: raise ValueError('Source usage register changed')
    selected=[row for row in source['selected'] if row['role']=='observer_train']
    if len(selected)!=512: raise ValueError('Expected the original512 observer fitting sources')
    ids=sorted(row['source_id'] for row in selected)
    ranked=sorted(ids,key=lambda sid:digest((SPEC['fold_order_seed']+':'+sid).encode()))
    folds={sid:index%5 for index,sid in enumerate(ranked)}
    mechanism=sorted(ids,key=lambda sid:digest((SPEC['mechanism_seed']+':'+sid).encode()))[:8]
    pins={}
    for path in sorted(Path(__file__).parent.glob('*.py')):pins[str(path.relative_to(parent))]=digest(path.read_bytes())
    for name in ['data_prepare.py','data_prepare_v2.py','data_sources.py','semantic_backbones.py','semantic_tsm.py','semantic_terminal.py','../unified_20261028/natural_data.py']:
        pins[name]=digest((parent/name).read_bytes())
    result={'schema':SPEC['schema'],'created_at_unix':time.time(),'specification':SPEC,
            'parent_assets':str(assets),'parent_source_protocol_sha256':PARENT_SOURCE,
            'parent_source_file_sha256':PARENT_SOURCE_FILE,'source_usage_register_sha256':SOURCE_REGISTER,
            'ontology_sha256':digest(source['ontology']),'original_task_decode_sha256':digest(source['decode']),
            'training_source_ids':ids,'fold_by_source':folds,'fold_source_counts':dict(Counter(folds.values())),
            'training_retained_events':sum(row['retained_event_count'] for row in selected),
            'mechanism_source_ids':mechanism,
            'mechanism_events':sum(row['retained_event_count'] for row in selected if row['source_id'] in mechanism),
            'implementation_sha256':pins,'new_training_updates':0,'old_development_or_calibration_predictions_read':False,
            'new_adequacy_or_reserved_policy_or_qualification_media_read':False,
            'execution_stage':'Registered architecture/source-fold/budget and runnable mechanism entry; fitting implementation must be separately pinned before optimizer execution without changing these specifications.'}
    result['registration_sha256']=digest(result)
    output.mkdir(parents=True,exist_ok=True)
    path=output/'REGISTRATION.json'
    with path.open('x') as stream:stream.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result


def load_registration(path, assets_override=None):
    value=json.loads(path.read_text());body=dict(value);expected=body.pop('registration_sha256')
    if digest(body)!=expected or value['specification']!=SPEC:raise ValueError('Frozen registration changed')
    parent=Path(__file__).parent.parent
    for name,pin in value['implementation_sha256'].items():
        if digest((parent/name).read_bytes())!=pin:raise ValueError('Registered implementation changed')
    assets=Path(value['parent_assets']) if assets_override is None else Path(assets_override)
    if digest((parent/'data_source_usage_register.json').read_bytes())!=value['source_usage_register_sha256']:
        raise ValueError('Frozen source usage register changed')
    if digest((assets/'SOURCE_PROTOCOL.json').read_bytes())!=value['parent_source_file_sha256']:
        raise ValueError('Parent source identity changed')
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--assets',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();value=freeze(args.assets,args.output)
    print(json.dumps({'registration_sha256':value['registration_sha256'],'mechanism_source_ids':value['mechanism_source_ids'],
                      'mechanism_events':value['mechanism_events'],'maximum_updates':SPEC['budget']['maximum_total_neural_updates']}))
