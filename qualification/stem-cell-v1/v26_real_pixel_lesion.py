"""Original physical ScienceQA image intervention, RESEARCH_ONLY / DENY_ALL.

The dataset source and legacy model loader are byte-locked by the read-only CI.
Original/black/shuffled images are actually fed through a pinned DINOv2 Encoder;
TRAIN/CAL images and all text are shared between the paired conditions. The
64 historical test labels never enter this process. No production invocation.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import time
import zipfile

ARCHIVE_SHA = '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'
PRED_SHA = 'c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4'
SOURCE_SHA = 'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
FIT_SHA = 'e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e'
HELD_SHA = 'b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3'
SCHEMA = 'hepta.stem.v26.original-pixel-conditional-vision.v1'
THRESHOLD = 0.005  # Frozen in V24 before reopening the real publisher labels.
DENY = 'DENY_ALL'

class Invalid(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()


def safe_new(path: Path, value) -> str:
    data = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return digest(data)


def strict_archive(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != 29629:
        raise Invalid('original archive absent or size mismatch')
    if digest(path.read_bytes()) != ARCHIVE_SHA:
        raise Invalid('original archive digest mismatch')
    with zipfile.ZipFile(path) as z:
        pred = z.read('sealed-source-bound-predictions.json')
        if digest(pred) != PRED_SHA:
            raise Invalid('original prediction bytes drift')
        obj = json.loads(pred)
        if obj.get('source_sha256') != SOURCE_SHA or obj.get('production_accepted') is not False:
            raise Invalid('original source or authorization drift')
        original = obj.get('predictions')
        if not isinstance(original, list) or len(original) != 64:
            raise Invalid('original 64-case roster incomplete')
        by_id = {}
        for row in original:
            if set(row) != {'id', 'group', 'split', 'source_input_sha256', 'arms'}:
                raise Invalid('original case fields changed')
            if row['id'] in by_id or row['split'] != 'test' or set(row['arms']) != set(obj['arms']):
                raise Invalid('original case duplicated/missing arms')
            for key in ('text_only', 'train_gate'):
                validate_probs(row['arms'][key])
            by_id[row['id']] = row
        return obj, by_id


def validate_probs(p):
    if (not isinstance(p, list) or len(p) != 4 or any(type(x) not in (float, int)
        or not math.isfinite(x) or not 0 <= x <= 1 for x in p) or abs(math.fsum(p)-1) > 1e-6):
        raise Invalid('bad 4-way probabilities')
    return p


def top1(p):
    validate_probs(p)
    return max(range(4), key=lambda j:(p[j],-j))


def margin(p):
    validate_probs(p)
    a,b=sorted(p,reverse=True)[:2]
    return a-b


def route_from_text(by_id):
    if len(by_id) != 64:
        raise Invalid('incomplete source cohort')
    return frozenset(k for k,v in by_id.items() if margin(v['arms']['text_only']) < THRESHOLD)


def validate_source_set(rows, archived):
    if type(rows) is not list or len(rows) != 192:
        raise Invalid('original complete 192-case source required')
    held = [r for r in rows if r.get('split') == 'test']
    if len(held) != 64 or {r['id'] for r in held} != set(archived):
        raise Invalid('test source identities changed')
    for r in held:
        if r['group'] != archived[r['id']]['group'] or digest(canonical(r)) != archived[r['id']]['source_input_sha256']:
            raise Invalid('case source bytes / group do not match sealed forecast')
    return held


def shuffled_donors(held):
    if len(held) < 2 or len({r['id'] for r in held}) != len(held):
        raise Invalid('invalid donor roster')
    donors = {}
    for i,row in enumerate(held):
        match = next((held[(i+j)%len(held)] for j in range(1,len(held))
                      if held[(i+j)%len(held)]['group'] != row['group']
                      and held[(i+j)%len(held)]['image'] != row['image']),None)
        if match is None or match['id'] == row['id']:
            raise Invalid('non-self shuffled image donor missing')
        donors[row['id']] = match
    return donors


def black_image(raw):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        if im.format not in ('JPEG','PNG') or im.width * im.height > 4_194_304:
            raise Invalid('invalid original image before black-pixel lesion')
        im.load()
        out = Image.new('RGB', im.size, (0,0,0))
        data = io.BytesIO(); out.save(data, format='PNG')
        return data.getvalue()


def close_to_archived(current, archived, tol=0.0005):
    """Retrospective numerical parity gate, not cross-host bitwise equality."""
    if set(current) != set(archived):
        raise Invalid('not all historical cases re-forwarded')
    maximum=0.0
    for rid, row in current.items():
        for arm in ('text_only','bridge_image_only','train_gate'):
            a=validate_probs(row['arms'][arm]);b=validate_probs(archived[rid]['arms'][arm])
            maximum=max(maximum,*(abs(u-v) for u,v in zip(a,b)))
            if top1(a)!=top1(b):
                raise Invalid('original model class parity changed')
    if maximum>tol:
        raise Invalid('original model probability parity exceeded prescribed tolerance')
    return maximum


def shadow_scores(held, text_rows, intervention_rows, selected, selected_arm='bridge_image_only'):
    out=[]
    if len(held)!=64 or set(selected) - {r['id'] for r in held}:
        raise Invalid('invalid shadow route inventory')
    if set(text_rows)!=set(intervention_rows) or len(text_rows)!=64:
        raise Invalid('original and intervention cases mismatch')
    if selected_arm not in ('bridge_image_only','train_gate'):
        raise Invalid('wrong frozen selected visual arm')
    for r in held:
        rid=r['id'];t=text_rows[rid]['arms']['text_only'];v=intervention_rows[rid]['arms'][selected_arm]
        out.append({'id':rid,'group':r['group'],'source_input_sha256':digest(canonical(r)),
                    'selected':rid in selected,'probabilities':validate_probs(v if rid in selected else t)})
    return out


def _make_vectors(tensors, ordered, vision, root, source_reader):
    out=[]
    started=time.perf_counter_ns();cpu=time.process_time_ns();before=vision.calls
    for i in range(0,len(ordered),8):
        raw=[source_reader(root / r['image'],r['image'],maximum=8*1024*1024) for r in ordered[i:i+8]]
        out.append(vision.encode(raw))
    if not out:raise Invalid('cannot claim an empty model intervention')
    return tensors.cat(out), {'image_count':len(ordered), 'physical_dino_batches':vision.calls-before,
                             'wall_ns':time.perf_counter_ns()-started,'process_cpu_ns':time.process_time_ns()-cpu}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--fit-labels',type=Path,required=True)
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    import torch
    import torch.nn.functional as F
    from e3_scienceqa_contract import (GRANITE,DINO,read_jsonl,read_pinned,validate_source,validate_labels,unit_probabilities)
    from e3_granite_dino_real import (verified_acquisition,FrozenVision,fit_and_predict,input_prompts)
    from execution import LocalEncoder
    torch.set_num_threads(2)
    frozen,archived=strict_archive(a.archive)
    sources=read_jsonl(a.source,SOURCE_SHA); validate_source(sources)
    held=validate_source_set(sources,archived)
    if a.fit_labels.is_symlink() or digest(a.fit_labels.read_bytes()) != FIT_SHA:
        raise Invalid('original TRAIN/CAL labels changed')
    fit_labels=read_jsonl(a.fit_labels,FIT_SHA)
    validate_labels(sources,fit_labels,{'train','validation'})
    selected_archived=route_from_text(archived)
    if len(selected_archived)!=21:
        raise Invalid('V24 preregistered route cardinality drift')
    all_ids={r['id']:i for i,r in enumerate(sources)}
    a.output.mkdir(parents=True,exist_ok=False)
    stage=a.output/'private-original-model-weight-source'
    granite=verified_acquisition(*GRANITE,stage/'granite')
    dino=verified_acquisition(*DINO,stage/'dino')
    text=LocalEncoder(stage/'granite',granite,maximum_tokens=512)
    vision=FrozenVision(stage/'dino',dino)
    try:
        # Actual text forward: original input renderer, five prompts per case.
        prompts=[p for r in sources for p in input_prompts(r)]
        start=time.perf_counter_ns();before=text.forward_calls
        vectors=[]
        for i in range(0,len(prompts),16):
            vectors.append(text.encode(prompts[i:i+16],pooling='cls-first-token'))
        text_all=F.normalize(torch.cat(vectors).view(192,5,384),dim=-1)
        q,c=text_all[:,0].contiguous(),text_all[:,1:].contiguous()
        text_receipt={'text_prompt_count':len(prompts),'physical_granite_batches':text.forward_calls-before,
                      'wall_ns':time.perf_counter_ns()-start}
        ts=torch.einsum('nd,ncd->nc',q,c)
        route=set()
        for r in held:
            i=all_ids[r['id']]
            p=unit_probabilities((ts[i]*8).tolist())
            if margin(p)<THRESHOLD:route.add(r['id'])
        if route!=selected_archived:
            raise Invalid('physical text forward route != V24 precommitted 21 cases')
        traincal=[r for r in sources if r['split']!='test']
        original_tc,cost_tc=_make_vectors(torch,traincal,vision,a.images,read_pinned)
        if len(traincal)!=128 or cost_tc['physical_dino_batches']!=16:
            raise Invalid('unexpected TRAIN/CAL image cost')
        index_tc={r['id']:i for i,r in enumerate(traincal)}
        img=torch.zeros((192,384),dtype=torch.float32)
        for r in traincal:img[all_ids[r['id']]]=original_tc[index_tc[r['id']]]
        # Placeholder is a TRAIN visual feature, never an unseen test image;
        # its scores are discarded for unselected test cases.
        for r in held:img[all_ids[r['id']]]=original_tc[0]
        chosen=[r for r in held if r['id'] in route]
        selected_img,cost_selected=_make_vectors(torch,chosen,vision,a.images,read_pinned)
        if len(chosen)!=21 or cost_selected['physical_dino_batches']!=3:
            raise Invalid('real conditional DINO execution missing')
        for j,r in enumerate(chosen):img[all_ids[r['id']]]=selected_img[j]
        # Training never accesses test labels; only train+cal features update fitted bridge/gate.
        original_cond,fit_cond=fit_and_predict(sources,fit_labels,q,c,img)
        pred_cond={r['id']:r for r in original_cond}
        cond=shadow_scores(held,pred_cond,pred_cond,route)
        sealed={'schema':SCHEMA,'source_sha256':SOURCE_SHA,'original_archive_sha256':ARCHIVE_SHA,
                'original_prediction_sha256':PRED_SHA,'original_fit_label_sha256':FIT_SHA,
                'original_held_label_sha256':HELD_SHA,'route_threshold':THRESHOLD,'visual_route_arm':'bridge_image_only',
                'selected_test_count':len(route),'unselected_test_pixels_never_loaded_before_seal':True,
                'training':{k:fit_cond[k] for k in ('organ_fitted_bridge_sha256','gate_sha256','private_cell_head_parameters','cell_optimizer_updates')},
                'text_cost':text_receipt,'training_image_cost':cost_tc,
                'conditional_test_image_cost':cost_selected,
                'predictions':cond,'production_authorized':False,'authority_posture':DENY,
                'real_new_encoder_forwards':True,'true_independent_future_windows':0}
        safe_new(a.output/'sealed-conditional-before-full-images.json',sealed)
        # Secondary validation baseline MUST happen AFTER the conditional seal.
        full_img,cost_full=_make_vectors(torch,held,vision,a.images,read_pinned)
        if cost_full['physical_dino_batches']!=8:
            raise Invalid('full 64-image comparison never physically executed')
        for j,r in enumerate(held):img[all_ids[r['id']]]=full_img[j]
        original_full,fit_full=fit_and_predict(sources,fit_labels,q,c,img)
        pred_full={r['id']:r for r in original_full}
        for field in ('organ_fitted_bridge_sha256','gate_sha256'):
            if fit_full[field]!=fit_cond[field]:
                raise Invalid('test-time intervention retrained weights')
        drift=close_to_archived(pred_full,archived)
        original_cond_vs_full=max(abs(x-y) for rid in route for x,y in zip(
            pred_cond[rid]['arms']['bridge_image_only'],pred_full[rid]['arms']['bridge_image_only']))
        if original_cond_vs_full>0.0005 or any(top1(pred_cond[rid]['arms']['bridge_image_only'])!=top1(pred_full[rid]['arms']['bridge_image_only']) for rid in route):
            raise Invalid('conditional original pixels failed full-equivalence gate')
        # Real transformed PIXEL inputs, never numeric feature masking.
        black_batches=[];swap_batches=[]
        donors=shuffled_donors(held)
        transform_bindings=[]
        for r in chosen:
            raw=read_pinned(a.images/r['image'],r['image'],maximum=8*1024*1024)
            black=black_image(raw)
            if digest(black)==digest(raw):raise Invalid('black intervention is identical')
            black_batches.append(black)
            swap_r=donors[r['id']]
            swapped=read_pinned(a.images/swap_r['image'],swap_r['image'],maximum=8*1024*1024)
            if digest(swapped)==digest(raw):raise Invalid('swapped pixels identical')
            swap_batches.append(swapped)
            transform_bindings.append({'id':r['id'],'source_image_sha256':r['image'],
                'masked_input_sha256':digest(black),'donor_id':swap_r['id'],
                'donor_image_sha256':swap_r['image']})
        def variants(raws):
            start=time.perf_counter_ns();before=vision.calls
            vectors=torch.cat([vision.encode(raws[i:i+8]) for i in range(0,len(raws),8)])
            if vision.calls-before!=3 or vectors.shape!=(21,384):
                raise Invalid('fake transformed-media forward counter')
            alt=img.clone()
            for j,r in enumerate(chosen):alt[all_ids[r['id']]]=vectors[j]
            pred,fit=fit_and_predict(sources,fit_labels,q,c,alt)
            if any(fit[k]!=fit_cond[k] for k in ('organ_fitted_bridge_sha256','gate_sha256')):
                raise Invalid('pixel lesion mutated pretrained/trained weights')
            return shadow_scores(held,{x['id']:x for x in pred_full},{x['id']:x for x in pred},route),\
                 {'physical_dino_batches':vision.calls-before,'image_count':len(raws),'wall_ns':time.perf_counter_ns()-start}
        masked,cost_mask=variants(black_batches)
        swapped,cost_swap=variants(swap_batches)
        final={'schema':SCHEMA+'.sealed-interventions','source_sha256':SOURCE_SHA,
               'original_archive_sha256':ARCHIVE_SHA,'frozen_conditional_sha256':digest((a.output/'sealed-conditional-before-full-images.json').read_bytes()),
               'source_model_revision':{'text':list(GRANITE),'vision':list(DINO)},
               'total_original_media_bytes_attached_to_public_receipt':0,
               'transform_bindings':transform_bindings,
               'conditional':cond,'text_reference':shadow_scores(held,pred_full,pred_full,set()),
               'full_reference':shadow_scores(held,pred_full,pred_full,set(r['id'] for r in held)),
               'full_gate_diagnostic':shadow_scores(held,pred_full,pred_full,set(r['id'] for r in held),selected_arm='train_gate'),
               'black_pixels':masked,'shuffled_real_pixels':swapped,
               'test_image_cost':{'conditional':cost_selected,'full':cost_full,'black':cost_mask,'shuffled':cost_swap},
               'max_abs_compatibility_drift_vs_archived_original':drift,
               'max_abs_conditional_selected_vs_full':original_cond_vs_full,
               'identical_fit_weights_across_all_arms':True,'production_authorized':False,
               'authority_posture':DENY,'true_independent_future_windows':0}
        safe_new(a.output/'sealed-interventions-before-labels.json',final)
    finally:
        text.close();vision.close()

if __name__=='__main__':
    main()
