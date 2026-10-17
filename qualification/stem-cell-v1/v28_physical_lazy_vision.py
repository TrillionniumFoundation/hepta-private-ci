"""V28: measure real, source-bound frozen DINO CLS forwards for conditional vision.

This experiment NEVER scores source labels, changes models, selects a Cell, or
claims end-to-end savings. The historical text-score policy was frozen in V24;
only the actual vision-backbone execution is newly run here. DENY_ALL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import time

SCHEMA = 'hepta.stem.v28.physical-conditional-vision.v1'
STEM_SOURCE = 'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
ARCHIVE_SHA = '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'
PLAN_SHA = 'c8f3f3d03ef9bdc9722d1197aaa807d901a4d5cda2e6c40d20f8ddcf7d2b8ad2'
PRED_SHA = 'c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4'
ORIGINAL_E3_HEAD = 'b8b2f10fe38506972301e77e3836729a90200673'
STAGER_HEAD = '751ab11dcb7ff3c20d895c698633e7b2d5ada2b8'
DINO_REPO = 'facebook/dinov2-small'
DINO_REVISION = 'ed25f3a31f01632728cabb09d1542f84ab7b0056'
N_CASES = 64
N_TRIGGER = 21
N_CHANGED = 19
BATCH_MAX = 8
MAX_INPUT_BYTES = 32 * 1024 * 1024


class Reject(ValueError):
    pass


def require(value, message):
    if not value:
        raise Reject(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def h64(value):
    return isinstance(value, str) and len(value) == 64 and all(x in '0123456789abcdef' for x in value)


def strict_json(raw):
    def unique(items):
        out = {}
        for k, v in items:
            require(k not in out, 'duplicate JSON key')
            out[k] = v
        return out
    def invalid(x):
        raise Reject('nonfinite JSON constant')
    require(type(raw) is bytes and 0 < len(raw) <= MAX_INPUT_BYTES, 'unbounded JSON')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def protected_read(path, limit=MAX_INPUT_BYTES):
    require(isinstance(path, Path) and not path.is_symlink() and path.is_file(), 'missing/unsafe file')
    require(0 < path.stat().st_size <= limit, 'wrong file length')
    return path.read_bytes()


def validate_plan(plan):
    """Exact independently presealed, source-only route; no TEST archive here."""
    keys={'schema','archived_prediction_sha256','source_sha256','threshold',
          'policy','rows','prelabel_only','physical_conditional_forwards',
          'training_updates','production_authorized'}
    require(type(plan) is dict and set(plan)==keys, 'unreviewed route profile')
    require(plan['schema']=='hepta.stem.v27.scienceqa-conditional-replay.v1.prelabel-plan'
            and plan['archived_prediction_sha256']==PRED_SHA
            and plan['source_sha256']==STEM_SOURCE
            and type(plan['threshold']) is float and plan['threshold']==0.005
            and plan['policy']=='text_margin_lt_threshold_else_text',
            'original prelabel route identity mismatch')
    require(plan['prelabel_only'] is True
            and plan['physical_conditional_forwards'] is False
            and type(plan['training_updates']) is int and plan['training_updates']==0
            and plan['production_authorized'] is False, 'authority or training contamination')
    rows=plan['rows']
    require(type(rows) is list and len(rows)==N_CASES, 'incorrect route census')
    ids=set()
    for row in rows:
        require(type(row) is dict and set(row)=={'id','group','trigger_vision',
                 'selected_class','text_class','image_class'}, 'changed route row')
        require(h64(row['id']) and h64(row['group']) and row['id'] not in ids,
                'invalid/duplicate case id')
        ids.add(row['id'])
        require(type(row['trigger_vision']) is bool, 'nonboolean trigger')
        for field in ('selected_class','text_class','image_class'):
            require(type(row[field]) is int and 0<=row[field]<4,'invalid class')
        require(row['selected_class']==(row['image_class'] if row['trigger_vision']
                                         else row['text_class']), 'wrong immutable route')
    require(sum(x['trigger_vision'] for x in rows)==N_TRIGGER, 'trigger census')
    require(sum(x['selected_class']!=x['text_class'] for x in rows)==N_CHANGED,
            'selected prediction census')
    return rows


def align_source(rows, sources, seals):
    """Use only source and image digests; never accept TEST targets in the model job."""
    require(type(sources) is list and len(sources) == 192, 'wrong source cohort')
    require(type(seals) is dict and seals.get('source_sha256') == STEM_SOURCE,
            'original source seal mismatch')
    require(seals.get('private_test_labels_sha256') is None
            and seals.get('production_accepted') is False,
            'withheld labels/digest leaked into predictor')
    test = [s for s in sources if s.get('split') == 'test']
    require(len(test) == N_CASES and len({s.get('id') for s in test}) == N_CASES,
            'test cases not unique')
    by_id = {s['id']:s for s in test}
    require(len(rows) == len({p.get('id') for p in rows})
            and set(p['id'] for p in rows) == set(by_id), 'route and source IDs differ')
    selected = []
    for row in rows:
        source = by_id[row['id']]
        require(row['group'] == source.get('group') and h64(source.get('image')),
                'source group or media identity changed')
        if row['trigger_vision']:
            selected.append(source)
    require(len(selected) == N_TRIGGER, 'on-demand selection changed')
    # Preserve route order for both physical arms; also ensure that all feature
    # comparisons use the same bytes, immutable checkpoint, and source identity.
    return [by_id[x['id']] for x in rows], selected


def execute_arm(vision, rows, asset_dir, *, read_bytes, clock=time.perf_counter_ns,
                cpu=time.process_time_ns):
    """One real run: only requested media is read, preprocessed and encoded."""
    require(0 < len(rows) <= N_CASES, 'invalid physical arm cardinality')
    seen, vectors, bytes_read = set(), {}, 0
    before = getattr(vision, 'calls', None)
    require(type(before) is int and before >= 0, 'model has no observable backend counter')
    t0, c0 = clock(), cpu()
    for offset in range(0, len(rows), BATCH_MAX):
        chunk = rows[offset:offset+BATCH_MAX]
        for s in chunk:
            require(type(s) is dict and h64(s.get('id')) and h64(s.get('image')),
                    'invalid source or media SHA')
            require(s['id'] not in seen, 'repeated physical input')
            seen.add(s['id'])
        data = [read_bytes(asset_dir / s['image'], s['image']) for s in chunk]
        require(all(type(raw) is bytes and 0 < len(raw) <= 8 * 1024 * 1024 for raw in data),
                'unbounded decoded source')
        bytes_read += sum(len(raw) for raw in data)
        encoded = vision.encode(data)
        # Compatible with actual FrozenVision torch.Tensor and strict local
        # test driver; no fabricated tensors enter the hosted evidence output.
        require(tuple(encoded.shape) == (len(chunk),384), 'unexpected 384D DINO result')
        for s,v in zip(chunk, encoded):
            values = v.tolist()
            require(len(values) == 384 and all(type(x) in (float,int) and math.isfinite(x)
                                               for x in values), 'nonfinite DINO output')
            vectors[s['id']] = tuple(float(x) for x in values)
    elapsed, cpu_elapsed = clock()-t0, cpu()-c0
    delta = vision.calls-before
    require(delta == math.ceil(len(rows)/BATCH_MAX), 'physical backend batch counter mismatch')
    require(elapsed > 0 and cpu_elapsed >= 0, 'unobserved timers')
    return {'items': len(rows), 'batches':delta, 'media_bytes_read':bytes_read,
            'wall_ns':elapsed, 'cpu_ns':cpu_elapsed}, vectors


def compare_arms(all_rows, chosen_rows, perform, *, abs_tolerance=0.0001):
    """ABBA balanced warm-cache comparisons, not end-to-end service savings."""
    require(len(all_rows) == N_CASES and len(chosen_rows) == N_TRIGGER,
            'unexpected original route proportions')
    all_ids = {r['id'] for r in all_rows}
    selected = {r['id'] for r in chosen_rows}
    require(len(all_ids)==N_CASES and len(selected)==N_TRIGGER and selected<=all_ids,
            'physical source set mismatch')
    require(type(abs_tolerance) is float and 0 < abs_tolerance <= 0.0001,
            'unbounded numeric tolerance')
    traces, full, conditional = [], [], []
    for name in ('all64','conditional21','conditional21','all64'):
        obs, values = perform(all_rows if name=='all64' else chosen_rows)
        require(set(values)==(all_ids if name=='all64' else selected),
                'missing or substituted physical vectors')
        require(type(obs) is dict and obs.get('items') == (N_CASES if name=='all64' else N_TRIGGER)
                and obs.get('batches') == (8 if name=='all64' else 3),
                'wrong actual image count or batches')
        require(type(obs.get('wall_ns')) is int and obs['wall_ns']>0
                and type(obs.get('cpu_ns')) is int and obs['cpu_ns']>=0,
                'not observed physical CPU/wall')
        for key,vec in values.items():
            require(type(vec) in (tuple,list) and len(vec)==384
                    and all(type(x) in (float,int) and math.isfinite(x) for x in vec),
                    'unverifiable physical vector')
        traces.append(dict(obs,profile=name))
        (full if name=='all64' else conditional).append(values)
    max_abs = 0.0
    for a in full:
        for b in conditional:
            for cid in selected:
                max_abs=max(max_abs, max(abs(x-y) for x,y in zip(a[cid],b[cid])))
    require(max_abs<=abs_tolerance, 'physical selected-case DINO feature parity violated')
    return traces,max_abs


def safe_write(path, document):
    require(not path.is_symlink(), 'unsafe output symlink')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(canonical(document)); f.flush();os.fsync(f.fileno())


def run(args):
    # Live withheld labels must be absent in this model-facing process.
    for var in ('HELD_SHA','HEPTA_V24_ORIGINAL_ZIP','HEPTA_V25_ORIGINAL_LABELS'):
        require(var not in os.environ, 'held-label environment entered model process')
    require(not (args.source_dir/'private_labels').exists(), 'withheld TEST data on disk')
    from e3_scienceqa_contract import DINO, validate_source, read_pinned
    from e3_granite_dino_real import verified_acquisition, FrozenVision
    require(DINO == (DINO_REPO,DINO_REVISION), 'original model identity mismatch')
    # The sealed historical ZIP and its withheld label digest are NOT present
    # in this model-facing process; only the exact prelabel route SHA enters.
    plan_bytes=protected_read(args.plan)
    require(sha(plan_bytes)==PLAN_SHA, 'frozen prelabel route bytes changed')
    plan=strict_json(plan_bytes)
    route=validate_plan(plan)
    srcbytes=protected_read(args.source_dir/'inputs'/'sources.jsonl')
    require(sha(srcbytes)==STEM_SOURCE, 'original publisher source byte SHA mismatch')
    sources=[strict_json(line) for line in srcbytes.splitlines()]
    validate_source(sources)
    seals=strict_json(protected_read(args.source_dir/'source-seals.json'))
    all_rows,chosen=align_source(route,sources,seals)
    require(args.weights_dir.is_absolute() and not args.weights_dir.exists(),
            'create-only absolute pretrained staging path required')
    # Only one real checkpoint, once per process. Timing below excludes its
    # acquisition, loading and warm-up, and never claims complete lifecycle cost.
    load0=time.perf_counter_ns()
    manifest=verified_acquisition(*DINO,args.weights_dir)
    model=FrozenVision(args.weights_dir,manifest)
    load_ns=time.perf_counter_ns()-load0
    require(model.identity and model.calls == 0, 'unverified frozen vision driver')
    observed_model_identity=model.identity
    # Warmup comes from original TRAIN images, not any selected TEST image.
    training=next(x for x in sources if x['split']=='train')
    model.encode([read_pinned(args.source_dir/'images'/training['image'],training['image'],maximum=8*1024*1024)])
    preflight_calls=model.calls
    require(preflight_calls == 1,'model warmup missing')
    def perform(rows):
        return execute_arm(model,rows,args.source_dir/'images',read_bytes=lambda p,d:read_pinned(p,d,maximum=8*1024*1024))
    try:
        traces,max_abs=compare_arms(all_rows,chosen,perform)
        model.close()
    finally:
        # Explicit no unbounded second model in this process.
        del model
    require(sum(r['batches'] for r in traces)==22,
            'unexpected real total image encoder batches')
    # Linux ru_maxrss is PROCESS HWM across all arms, not independent per-arm
    # residency, and cannot certify saved RSS or energy.
    peak_kib=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    require(peak_kib > 0,'unmeasured peak RSS')
    doc={'schema':SCHEMA,'authority':'DENY_ALL','disposition':'HOLD_NO_MODEL_SELECTION',
         'production_authorized':False,'stem_winner_verified':False,
         'original_E3_commit':ORIGINAL_E3_HEAD,'source_revision':STEM_SOURCE,
         'historical_archive_sha256':ARCHIVE_SHA,
         'route_policy':'original_label_blind_text_margin_lt_0.005',
         'frozen_route_plan_sha256':PLAN_SHA,
         'model_repository':DINO_REPO,'model_revision':DINO_REVISION,
         'model_identity':model_identity_safe(manifest,observed_model_identity),
         'actual_model_material_sha256':dict(sorted(manifest['files'].items())),
         'physical_device':'cpu','physical_precision':'float32',
         'actual_pretrained_vision_forward':True,'encoder_acquisition_loading_wall_ns':load_ns,
         'warmup_backend_batches':preflight_calls,'real_original_images':N_CASES,
         'frozen_conditional_image_inputs':N_TRIGGER,'frozen_changed_top1':N_CHANGED,
         'arm_traces':traces,'max_selected_feature_abs_difference':max_abs,
         'process_peak_rss_kib_not_incremental':peak_kib,
         'actual_conditional_backend_batches':[x['batches'] for x in traces if x['profile']=='conditional21'],
         'actual_all_backend_batches':[x['batches'] for x in traces if x['profile']=='all64'],
         'real_test_labels_opened':False,'new_training_updates':0,
         'independent_future_windows':0,'physical_end_to_end_savings_proven':False,
         'energy_joules':None,'gpu_peak_bytes':None,
         'pretrained_text_encoder_executed_this_run':False,
         'original_cell_task_efficacy_recomputed_this_run':False}
    safe_write(args.output,doc)
    return doc


def model_identity_safe(manifest,model_identity):
    require(type(manifest) is dict and manifest.get('revision')==DINO_REVISION
            and type(manifest.get('files')) is dict and 'model.safetensors' in manifest['files'],
            'unbound pretrained manifest')
    require(all(h64(d) for d in manifest['files'].values()),'invalid checkpoint files')
    # The original verified FrozenVision validates the physical original
    # tensors, model.load identity, and complete snapshot; no raw tensors leave.
    digest=sha(canonical(manifest))
    require(type(model_identity) is str and model_identity==digest,
            'physical model identity disagrees with verified original files')
    return digest


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--plan',type=Path,required=True)
    cli.add_argument('--source-dir',type=Path,required=True)
    cli.add_argument('--weights-dir',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    response=run(cli.parse_args())
    print(json.dumps({'schema':response['schema'],'authority':'DENY_ALL',
         'actual_pretrained_vision_forward':response['actual_pretrained_vision_forward'],
         'items_by_arm':[x['items'] for x in response['arm_traces']],
         'batches_by_arm':[x['batches'] for x in response['arm_traces']],
         'savings_claim':False},sort_keys=True))
