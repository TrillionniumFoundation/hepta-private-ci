"""Actual two-Head, equal-resident-parameter Cell specialization: P2 shadow only.

Never claims independent source/model origin, future tasks, NDU superiority or
CellSplit cutover. A label-blind evaluation file enters only prediction phase.
One physical pinned Granite model load is provided by the original Stem owner.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

import p1_real_granite_cohort as p1

SCHEMA = 'hepta.p2.equal-resident-cells.v1'
ARMS = ('frozen_no_change','unrouted_equal_parameter','wide_single_equal_parameter','fixed_two_cell','adaptive_train_only')
WIDTH, RANK, STATE = 384, 8, 64
HEAD_PARAMETERS = 7434
TOTAL_RESIDENT = 2 * HEAD_PARAMETERS
OLD_UPDATES = NEW_UPDATES = 20
SPLIT_THRESHOLD = 0.03
TOLERANCE = 4e-5
digest = p1.digest


def fail(ok, why):
    if not ok:
        raise ValueError(why)


def shape_hash(items):
    h=hashlib.sha256()
    for k,v in sorted(items.items()):
        h.update(k.encode()+b'\0'+v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


class TwoHeads(nn.Module):
    """Two resident 7,434-scalar output-only Heads, not layer-internal LoRA."""
    def __init__(self, seed):
        super().__init__()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.down=nn.Parameter(torch.empty(2,WIDTH,RANK).normal_(0,.04))
            self.gate=nn.Parameter(torch.empty(2,STATE,RANK).normal_(0,.03))
            self.g_bias=nn.Parameter(torch.zeros(2,RANK))
            self.up=nn.Parameter(torch.zeros(2,RANK,WIDTH))
            self.out=nn.Parameter(torch.empty(2,WIDTH,2).normal_(0,.03))
            self.out_bias=nn.Parameter(torch.zeros(2,2))
        fail(sum(x.numel() for x in self.parameters())==TOTAL_RESIDENT,
             'two equal resident Head slots expected')

    def forward(self, x):
        fail(isinstance(x,torch.Tensor) and x.ndim==2 and x.shape[1]==WIDTH
             and x.dtype==torch.float32 and x.device.type=='cpu'
             and not x.requires_grad and bool(torch.isfinite(x).all()),
             'frozen genuine Q24 feature bank required')
        common=x.detach()
        state=common[:,:STATE]
        d=torch.einsum('bd,hdr->bhr',common,self.down)
        g=torch.sigmoid(torch.einsum('bs,hsr->bhr',state,self.gate)+self.g_bias)
        delta=torch.einsum('bhr,hrd->bhd',F.silu(d)*g,self.up)
        return torch.einsum('bhd,hdc->bhc',common.unsqueeze(1)+delta,self.out)+self.out_bias


class WideSingleHead(nn.Module):
    """A real, single rank-16 Head + second learned affine skip = exactly 14,868."""
    def __init__(self,seed):
        super().__init__()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.down=nn.Parameter(torch.empty(WIDTH,16).normal_(0,.04))
            self.gate=nn.Parameter(torch.empty(STATE,16).normal_(0,.03))
            self.g_bias=nn.Parameter(torch.zeros(16))
            self.up=nn.Parameter(torch.zeros(16,WIDTH))
            self.out=nn.Parameter(torch.empty(WIDTH,2).normal_(0,.03))
            self.out_bias=nn.Parameter(torch.zeros(2))
            self.skip=nn.Parameter(torch.empty(WIDTH,2).normal_(0,.02))
            self.skip_bias=nn.Parameter(torch.zeros(2))
        fail(sum(p.numel() for p in self.parameters())==TOTAL_RESIDENT,
             'true unsplit wider Head must match two Cell resident parameters')

    def forward(self,x):
        fail(isinstance(x,torch.Tensor) and x.ndim==2 and x.shape[1]==WIDTH
             and x.dtype==torch.float32 and not x.requires_grad and
             bool(torch.isfinite(x).all()),'finite 384D frozen input for wide Head')
        common=x.detach()
        d=common @ self.down
        g=torch.sigmoid(common[:,:STATE] @ self.gate + self.g_bias)
        delta=(F.silu(d)*g) @ self.up
        return ((common+delta)@self.out+self.out_bias
               +common@self.skip+self.skip_bias)


def train_wide(train,y,blind,*,seed):
    model=WideSingleHead(seed)
    original=shape_hash(dict(model.named_parameters()))
    optimizer=torch.optim.SGD(model.parameters(),lr=.15)
    losses=[];begin=time.process_time_ns()
    for inputs,targets,steps in ((train[:64],y[:64],OLD_UPDATES),
                                 (train,y,NEW_UPDATES)):
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            loss=F.cross_entropy(model(inputs),targets)
            fail(bool(torch.isfinite(loss)),'wide Head nonfinite loss')
            loss.backward();optimizer.step()
            losses.append(float(loss.detach().item()))
    cpu=max(1,time.process_time_ns()-begin)
    with torch.no_grad(): logits=model(blind).detach().tolist()
    packed={}
    for name,param in model.named_parameters():
        v=param.detach().cpu().contiguous().numpy().astype('<f4',copy=False)
        packed[name]={'shape':list(v.shape),'bytes_le_hex':v.tobytes().hex()}
    final=shape_hash(dict(model.named_parameters()))
    fail(final!=original,'unsplit width control did not learn')
    return dict(arm='wide_single_equal_parameter',parameter_count=TOTAL_RESIDENT,
       private_head_parameter_count=TOTAL_RESIDENT,initial_weights_sha256=original,
       final_weights_sha256=final,weights=packed,split_proposed=False,
       train_only_split_excess_brier=0.,split_threshold=SPLIT_THRESHOLD,
       parent_to_child_max_abs_error=0.,optimization_steps=40,
       training_example_exposures=3840,train_cpu_ns=cpu,train_loss_history=losses,
       training_uses_test_labels=False,heldout_original_labels_opened=False,
       logits=logits)


def routing(all_logits, x, kind, *, split, threshold):
    if kind in ('frozen_no_change','unrouted_equal_parameter'):
        return all_logits.mean(dim=1)
    if kind == 'adaptive_train_only' and not split:
        return all_logits[:,0,:]
    fail(kind in ('fixed_two_cell','adaptive_train_only'), 'unknown router arm')
    select=(x[:,0]>=threshold).long()
    return all_logits[torch.arange(len(x)),select]


def train_one(initial, train, y, blind, *, arm, threshold):
    fail(arm in ARMS and arm!='wide_single_equal_parameter' and len(train)==128 and len(blind)==96 and y.shape==(128,),
         'exact original train/blind cases required')
    model=copy.deepcopy(initial)
    p0=shape_hash(dict(model.named_parameters()))
    old_x, old_y=train[:64],y[:64]
    split=(arm == 'fixed_two_cell')
    optimizer=torch.optim.SGD(model.parameters(),lr=.15)
    updates=0; examples=0; loss_trace=[]; train_start=time.process_time_ns()
    def step(x,t,chosen,selected):
        nonlocal updates,examples
        optimizer.zero_grad(set_to_none=True)
        logit=routing(model(x),x,chosen,split=selected,threshold=threshold)
        loss=F.cross_entropy(logit,t)
        fail(bool(torch.isfinite(loss)), 'nonfinite task loss')
        loss.backward();optimizer.step()
        updates+=1;examples+=len(x)
        loss_trace.append(float(loss.detach().item()))
    if arm!='frozen_no_change':
        for _ in range(OLD_UPDATES):step(old_x,old_y,arm,split)
    with torch.no_grad():
        old_p=torch.softmax(routing(model(old_x),old_x,arm,split=split,threshold=threshold),dim=-1)[:,1]
        new_p=torch.softmax(routing(model(train[64:]),train[64:],arm,split=split,threshold=threshold),dim=-1)[:,1]
        err_old=float(torch.mean((old_p-old_y.float())**2).item())
        err_new=float(torch.mean((new_p-y[64:].float())**2).item())
    excess=err_new-err_old
    before_copy_error=0.0
    if arm=='adaptive_train_only' and excess>SPLIT_THRESHOLD:
        with torch.no_grad():
            before=model(train[:4])[:,0,:].detach().clone()
            for p in model.parameters():p[1].copy_(p[0])
            after=model(train[:4])[:,1,:].detach()
            before_copy_error=float(torch.max(torch.abs(before-after)).item())
            fail(before_copy_error==0., 'parent-to-child split has altered function')
        split=True
    if arm!='frozen_no_change':
        for _ in range(NEW_UPDATES):step(train,y,arm,split)
    train_cpu_ns=time.process_time_ns()-train_start
    with torch.no_grad():
        prediction=routing(model(blind),blind,arm,split=split,threshold=threshold)
        probs=torch.softmax(prediction,dim=1)[:,1]
        logits=prediction.detach().cpu().tolist()
    fail(all(math.isfinite(z) and 0<=z<=1 for z in probs.tolist()),
         'model output is not finite probability')
    final=shape_hash(dict(model.named_parameters()))
    fail((updates==0 and final==p0) if arm=='frozen_no_change'
         else (updates==40 and final!=p0), 'frozen/learned fit identity mismatch')
    packed={}
    for name,param in model.named_parameters():
        v=param.detach().cpu().contiguous().numpy().astype('<f4',copy=False)
        packed[name]={'shape':list(v.shape),'bytes_le_hex':v.tobytes().hex()}
    return dict(arm=arm,parameter_count=TOTAL_RESIDENT,
         private_head_parameter_count=HEAD_PARAMETERS,initial_weights_sha256=p0,
         final_weights_sha256=final,weights=packed,
         split_proposed=bool(split),train_only_split_excess_brier=float(excess),
         split_threshold=SPLIT_THRESHOLD,parent_to_child_max_abs_error=before_copy_error,
         optimization_steps=updates,training_example_exposures=examples,
         train_cpu_ns=max(1,train_cpu_ns),train_loss_history=loss_trace,
         training_uses_test_labels=False,heldout_original_labels_opened=False,
         logits=logits)


def execute(training,blind,backend,*,seed=7347,weight_origin='fixture'):
    p1.verify_material(training,blind)
    fail(type(seed) is int and 0<seed<2**31 and weight_origin in
         ('fixture','pinned_public_research'), 'registered seed and model profile required')
    torch.set_num_threads(1)
    frozen_sha,params=p1.backend_digest(backend)
    if weight_origin=='pinned_public_research':
        fail(params>=90_000_000 and getattr(backend,'revision',None)==p1.GRANITE_REVISION
             and getattr(backend,'model_id',None)==p1.GRANITE_MODEL
             and getattr(backend,'device',None)=='cpu',
             'real pinned 97M source checkpoint required; no mock fallback')
    begin=time.process_time_ns();features={};counter={'calls':0,'model_encode_wall_ns':0}
    for row in training['rows']+blind['rows']:
        vec=p1.encode(backend,row,call_stats=counter)
        features[row['case_id']]=vec
    fail(counter['calls']==224 and len(features)==224,'exact real 224 Encoder forwards required')
    measured_encoder_cpu_ns=max(1,time.process_time_ns()-begin)
    x=torch.stack([features[r['case_id']] for r in training['rows']])
    label=torch.tensor([r['label'] for r in training['rows']],dtype=torch.long)
    b=torch.stack([features[r['case_id']] for r in blind['rows']])
    threshold=float(torch.median(x[:,0]).item())
    initial=TwoHeads(seed)
    arms={name:(train_wide(x,label,b,seed=seed) if name=='wide_single_equal_parameter'
                else train_one(initial,x,label,b,arm=name,threshold=threshold))
          for name in ARMS}
    final_sha,final_params=p1.backend_digest(backend)
    fail((frozen_sha,params)==(final_sha,final_params),'frozen pretrained model changed during Head training')
    # Real original publisher questions, no dev/test labels, deterministic Q24 bytes.
    identities=[dict(case_id=r['case_id'],group_id=r['group_id'],split=r['split'],
                     joint_input_digest=r['joint_input_digest']) for r in blind['rows']]
    values={r['case_id']:[int(round(float(z)*(1<<24))) for z in features[r['case_id']]]
            for r in blind['rows']}
    fail(all(len(q)==WIDTH for q in values.values()),'incomplete source vector inventory')
    out=dict(schema=SCHEMA,authority='DENY_ALL',production_promotion_permitted=False,
             frozen_pretrained_source_execution_claimed=weight_origin=='pinned_public_research',
             model_revision=p1.GRANITE_REVISION,public_panel_sha256=p1.PANEL_SHA,
             original_source_is_cross_sectional_not_future=True,
             independent_model_origin_authenticated=False,independent_publisher_label_origin_authenticated=False,
             reader_sufficiency_established=False,ndu_system2_superiority_established=False,
             general_reasoning_equivalence_10t_100t_established=False,
             physical_4096_active_pretrained_split_executed=False,
             model_parameter_count=params,frozen_model_weights_sha256=frozen_sha,
             original_source_model_api_calls=224,source_encode_cpu_ns=measured_encoder_cpu_ns,
             source_encoder_wall_ns=counter['model_encode_wall_ns'],
             original_train_count=128,original_calibration_count=32,original_test_count=64,
             source_heldout_cases=identities,source_features_q24=values,
             cutoff_feature0_train_median=threshold,old_new_cohorts_are_temporal=False,
             per_arm_parameter_budget=TOTAL_RESIDENT,
             compared_arms=arms,selection_authorized=False)
    out['report_sha256']=p1.digest(out)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--train-material',required=True)
    ap.add_argument('--blind-material',required=True)
    ap.add_argument('--compact-source',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    train=p1.read_json(args.train_material);blind=p1.read_json(args.blind_material)
    sys.path.insert(0,str(Path(args.compact_source)/'qualification/neuron-stem'))
    from compact_stem_trial import FrozenCompactStem
    model=FrozenCompactStem(p1.GRANITE_MODEL,p1.GRANITE_REVISION,device='cpu',max_tokens=512)
    result=execute(train,blind,model,weight_origin='pinned_public_research')
    p1.write_exclusive(args.output,result)

if __name__=='__main__':main()
