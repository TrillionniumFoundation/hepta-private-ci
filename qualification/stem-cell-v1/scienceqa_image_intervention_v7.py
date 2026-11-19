"""Source-locked E3 image-intervention follow-up; research only, DENY_ALL.

One genuine pretrained Granite97+DINO feature pass, frozen TRAIN-only ridge and
769-parameter learned gate. Correct-image / other-source-image / real black-image
DINO observations reuse the SAME fitted gate and question/choice features.
Re-executes original E3 training once as numerical control, then independently
refits identical TRAIN-only parameters and requires exact checkpoint digests.
No held labels enter this producer; no model promotion or real-life authority.
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

PINNED_E3 = '2dc43da7d9bf343acc871219ddce44d0e14d8911'
SOURCE_SHA = 'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
FIT_SHA = 'e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e'
HISTORICAL_PRED = 'e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7'
SCHEMA = 'hepta.stem.scienceqa-physical-image-intervention.v7'
ARMS = ('correct_image', 'other_group_image', 'black_image', 'text_only')

class InterventionError(ValueError):
    pass

def need(ok, reason):
    if not ok:
        raise InterventionError(reason)

def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()

def sha(blob):
    return hashlib.sha256(blob).hexdigest()

def _top1(values):
    return max(range(4), key=lambda k: (values[k], -k))

def source_derangement(sources):
    """Deterministic within-TEST different-image intervention; no labels read."""
    rows = [row for row in sources if row['split'] == 'test']
    need(len(rows) == 64 and len({r['id'] for r in rows}) == 64 and
         len({r['group'] for r in rows}) == 64, 'TEST source/visual groups not distinct')
    ordered = sorted(rows, key=lambda row: row['id'])
    mapping = {row['id']: ordered[(i+1)%len(ordered)]['id']
               for i, row in enumerate(ordered)}
    groups = {row['id']: row['group'] for row in rows}
    need(all(a != b and groups[a] != groups[b] for a,b in mapping.items()),
         'not a different-image group permutation')
    return mapping

def training_once(sources, fit_labels, question, choices, image, *, steps=80):
    """Frozen original E3 numeric recipe in separate training implementation."""
    import torch
    import torch.nn.functional as F
    need(type(steps) is int and 1 <= steps <= 80, 'unregistered SGD steps')
    n = len(sources)
    need(n == 192 and tuple(question.shape) == (n,384) and
         tuple(choices.shape) == (n,4,384) and tuple(image.shape) == (n,384),
         'unreviewed original feature geometry')
    need(all(torch.isfinite(v).all().item() for v in (question, choices, image)),
         'nonfinite pretrained image/text features')
    scope = {k:[i for i,row in enumerate(sources) if row['split'] == k]
             for k in ('train','validation','test')}
    tr,cal,held = scope['train'],scope['validation'],scope['test']
    need((len(tr),len(cal),len(held)) == (96,32,64), 'wrong publisher cohort sizes')
    known = {r['id']:r['label'] for r in fit_labels}
    need(len(known) == len(fit_labels) == 128 and set(known)=={
         sources[i]['id'] for i in tr + cal} and
         all(type(y) is int and 0<=y<4 for y in known.values()),
         'new training received missing, duplicate or TEST labels')
    labels = torch.tensor([known[sources[i]['id']] for i in tr],dtype=torch.long)
    right_choices = choices[tr][torch.arange(len(tr)), labels]
    torch.manual_seed(20261015)
    x = torch.cat((image[tr].double(), torch.ones(len(tr),1,dtype=torch.float64)),dim=1)
    penalty = torch.eye(385,dtype=torch.float64)*.25
    penalty[-1,-1]=0
    solved = torch.linalg.solve(x.T@x+penalty,x.T@right_choices.double())
    need(tuple(solved.shape)==(385,384) and torch.isfinite(solved).all().item() and
         solved.abs().max().item()<=8,'invalid fitted original organ bridge')
    w,b=solved[:-1].float().T.contiguous(),solved[-1].float()
    def mapped(image_vector):
        z = image_vector@w.T+b
        need(torch.isfinite(z).all().item() and (z.norm(dim=1)>1e-10).all().item(),
             'degenerate frozen organ projection')
        return F.normalize(z,dim=-1)
    mv=mapped(image)
    score_text=torch.einsum('nd,ncd->nc',question,choices)
    score_image=torch.einsum('nd,ncd->nc',mv,choices)
    gate=torch.nn.Linear(768,1)
    torch.nn.init.zeros_(gate.weight);torch.nn.init.zeros_(gate.bias)
    optim=torch.optim.AdamW(gate.parameters(),lr=.01,weight_decay=0.)
    covars=torch.cat((question,mv),dim=1).detach()
    for _ in range(steps):
        optim.zero_grad(set_to_none=True)
        g=torch.sigmoid(gate(covars[tr]))
        logits=8*(score_text[tr]*(1-g)+score_image[tr]*g)
        loss=F.cross_entropy(logits,labels)
        need(torch.isfinite(loss).item(),'train-only loss nonfinite')
        loss.backward();optim.step()
    bridge_hash=sha(canonical([w.tolist(),b.tolist()]))
    gate_hash=sha(canonical({k:v.detach().tolist() for k,v in gate.state_dict().items()}))
    need(sum(v.numel() for v in gate.parameters())==769,'wrong gate budget')
    gate.eval().requires_grad_(False)
    return {'w':w,'b':b,'gate':gate,'bridge_hash':bridge_hash,
            'gate_hash':gate_hash,'steps':steps}

def prediction_variant(question, choices, alternate, fitted):
    """Image intervention forwards through unchanged learned bridge and gate."""
    import torch
    import torch.nn.functional as F
    need(tuple(question.shape)==(64,384) and tuple(choices.shape)==(64,4,384)
         and tuple(alternate.shape)==(64,384),'counterfactual shape changed')
    with torch.inference_mode():
        transformed=alternate@fitted['w'].T+fitted['b']
        need(torch.isfinite(transformed).all().item() and
             (transformed.norm(dim=1)>1e-10).all().item(), 'invalid changed image projection')
        transformed=F.normalize(transformed,dim=-1)
        selector=torch.sigmoid(fitted['gate'](torch.cat((question,transformed),dim=1)))
        ts=torch.einsum('nd,ncd->nc',question,choices)
        ms=torch.einsum('nd,ncd->nc',transformed,choices)
        logits=8*(ts*(1-selector)+ms*selector)
        return torch.softmax(logits,dim=-1).tolist()

def validate_original_parity(new, prior, *, maximum_delta=.002):
    """Historical real original 8-arm model output MUST precede new claims."""
    need(type(new) is list and len(new)==64 and type(prior) is list and len(prior)==64,
         'original predictor inventory')
    previous={r['id']:r for r in prior}
    need(len(previous)==64 and len({r['id'] for r in new})==64,
         'duplicate original or reproduced predictor ID')
    maximum=0.
    for row in new:
        old=previous.get(row['id'])
        need(old is not None and row['group']==old['group'] and
             row['source_input_sha256']==old['source_input_sha256'] and
             set(row['arms'])==set(old['arms']), 'original model source/arm mismatch')
        for name in old['arms']:
            a,b=row['arms'][name],old['arms'][name]
            need(len(a)==len(b)==4 and _top1(a)==_top1(b), 'original pretrained class drift')
            maximum=max(maximum,max(abs(x-y) for x,y in zip(a,b)))
    need(maximum<=maximum_delta, 'pretrained historical model probabilities not reproduced')
    return maximum

def run(sources_path, fit_path, images_path, original_archive, output_path,
        *, model_root):
    """Load EXACT original source-owned model functions, fail on changed source."""
    import torch
    from PIL import Image
    from e3_scienceqa_contract import (read_jsonl, validate_source, validate_labels,
                                       unit_probabilities, read_pinned, write_new,
                                       GRANITE, DINO)
    from e3_granite_dino_real import (verified_acquisition, FrozenVision,
                                     real_features, fit_and_predict)
    from execution import LocalEncoder
    from scienceqa_independent_rejudge_v5 import read_archive
    from pathlib import Path
    started=time.perf_counter_ns()
    source=read_jsonl(Path(sources_path),SOURCE_SHA)
    validate_source(source)
    fit=read_jsonl(Path(fit_path),FIT_SHA)
    validate_labels(source,fit,{'train','validation'})
    original=read_archive(Path(original_archive))
    historical=json.loads(original['sealed-source-bound-predictions.json'])
    need(sha(original['sealed-source-bound-predictions.json'])==HISTORICAL_PRED and
         historical['source_sha256']==SOURCE_SHA,
         'original model archive not from frozen source')
    root=Path(model_root)
    root.mkdir(parents=True,exist_ok=False)
    manifest_txt=verified_acquisition(*GRANITE,root/'granite')
    manifest_img=verified_acquisition(*DINO,root/'dino')
    txt=LocalEncoder(root/'granite',manifest_txt,maximum_tokens=512)
    img=FrozenVision(root/'dino',manifest_img)
    q,choices,images=real_features(source,Path(images_path),txt,img)
    txt_forwards=txt.forward_calls
    vision_forwards=img.calls
    original_pred,original_fit=fit_and_predict(source,fit,q,choices,images)
    baseline_delta=validate_original_parity(original_pred,historical['predictions'])
    fitted=training_once(source,fit,q,choices,images)
    need(fitted['bridge_hash']==original_fit['organ_fitted_bridge_sha256'] and
         fitted['gate_hash']==original_fit['gate_sha256'] and
         original_fit['cell_optimizer_updates']==80,
         'independent training did not reproduce original exact fitted bytes')
    test_indices=[i for i,row in enumerate(source) if row['split']=='test']
    test_rows=[source[i] for i in test_indices]
    need(len(test_rows)==64,'source test panel incomplete')
    lookup={row['id']:j for j,row in enumerate(test_rows)}
    swap=source_derangement(source)
    mispaired=torch.stack([images[test_indices[lookup[swap[r['id']]]]]
                           for r in test_rows])
    # Mask is a genuine DINOv2 forward on an explicit black RGB PNG; the image
    # for another-source swap is also a genuine previously computed DINO embedding.
    picture=Image.new('RGB',(224,224),(0,0,0))
    buf=io.BytesIO();picture.save(buf,format='PNG')
    mask_bytes=buf.getvalue()
    mask=img.encode([mask_bytes])
    need(tuple(mask.shape)==(1,384) and img.calls==vision_forwards+1,
         'no real frozen DINO mask forward')
    img.close()
    base_q=q[test_indices];base_choices=choices[test_indices]
    correct=prediction_variant(base_q,base_choices,images[test_indices],fitted)
    other=prediction_variant(base_q,base_choices,mispaired,fitted)
    black=prediction_variant(base_q,base_choices,mask.repeat(64,1),fitted)
    ts=torch.einsum('nd,ncd->nc',base_q,base_choices)
    text_only=torch.softmax(ts*8,dim=-1).tolist()
    original_new={r['id']:r for r in original_pred}
    max_refit_delta=0.
    for i,row in enumerate(test_rows):
        reference=original_new[row['id']]['arms']['train_gate']
        max_refit_delta=max(max_refit_delta,max(abs(a-b) for a,b in zip(correct[i],reference)))
        need(_top1(correct[i])==_top1(reference), 'trained Head control changed its class')
        need(max(abs(a-b) for a,b in zip(text_only[i],original_new[row['id']]['arms']['text_only']))<=1e-6,
             'question/text stem changed under image intervention')
    need(max_refit_delta<=1e-5,'independent frozen Head did not reproduce genuine original')
    pairs=[]
    for i,row in enumerate(test_rows):
        peer=test_rows[lookup[swap[row['id']]]]
        need(row['group']!=peer['group'] and row['id']!=peer['id'],
             'source interventional peer equals original')
        pairs.append({'id':row['id'],'group':row['group'],'split':'test',
                      'source_input_sha256':sha(canonical(row)),
                      'other_group_image_from_id':peer['id'],
                      'other_group_image_source_group':peer['group'],
                      'arms':{'correct_image':correct[i],
                              'other_group_image':other[i],
                              'black_image':black[i],
                              'text_only':text_only[i]}})
    pairs.sort(key=lambda row:row['id'])
    report={'schema':SCHEMA,'source_sha256':SOURCE_SHA,'fit_labels_sha256':FIT_SHA,
            'original_prediction_sha256':HISTORICAL_PRED,
            'original_model_code_commit':PINNED_E3,
            'model_text_repo':GRANITE[0],'model_text_revision':GRANITE[1],
            'model_vision_repo':DINO[0],'model_vision_revision':DINO[1],
            'original_trained_bridge_sha256':fitted['bridge_hash'],
            'original_trained_gate_sha256':fitted['gate_hash'],
            'historical_bridge_sha256':historical['fit']['organ_fitted_bridge_sha256'],
            'historical_gate_sha256':historical['fit']['gate_sha256'],
            'historical_bridge_byte_parity':(
                fitted['bridge_hash']==historical['fit']['organ_fitted_bridge_sha256']),
            'historical_gate_byte_parity':(
                fitted['gate_hash']==historical['fit']['gate_sha256']),
            'history_max_probability_delta':baseline_delta,
            'independent_refit_max_probability_delta':max_refit_delta,
            'training_steps_original':80,'training_steps_independent_check':80,
            'text_forward_batches_original':txt_forwards,
            'vision_forward_batches_original':vision_forwards,
            'vision_forward_batches_black_mask':img.calls-vision_forwards,
            'vision_forward_batches_other_image_extra':0,
            'black_image_png_sha256':sha(mask_bytes),
            'per_case_predictions':pairs,
            'physical_research_wall_ns':time.perf_counter_ns()-started,
            'test_labels_loaded_by_producer':False,
            'actual_frozen_pretrained_model_executed':True,
            'same_head_parameters_in_all_image_arms':True,
            'actual_image_mask_dino_forward_executed':True,
            'other_group_image_source_was_physically_encoded':True,
            'independent_human_necessity_adjudication':False,
            'genuine_future_task_reliability_established':False,
            'model_promoted':False,'production_authorized':False,'authority':'DENY_ALL'}
    need(not Path(output_path).exists(), 'existing output cannot be overwritten')
    with Path(output_path).open('xb') as handle:
        handle.write(canonical(report));handle.flush();os.fsync(handle.fileno())
    return report

def main():
    p=argparse.ArgumentParser()
    for name in ('sources','fit-labels','images','original-archive','model-root','output'):
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    run(args.sources,args.fit_labels,args.images,args.original_archive,args.output,
        model_root=args.model_root)

if __name__=='__main__':
    main()
