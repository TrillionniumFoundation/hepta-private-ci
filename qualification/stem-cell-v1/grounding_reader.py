"""V9 learned span localization and shared-metric two-hop Group composition.

Only the six public token/mask tensors enter ordinary inference. Span labels,
canonical entities and context identities belong exclusively to the trainer.
"""
import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F

from bridge_reader import BridgeReader, reader_identity
from token_reader import _attention, _normalize


ARMS = ("latent_chain", "grounded_chain", "grounded_reset", "latent_reset")


def public_fact_groups(facts, mask):
    """Deduplicate this call's equal public facts/masks, ignoring masked payloads."""
    representatives, inverse, seen = [], [], {}
    for row in range(facts.shape[0]):
        present = mask[row].detach().contiguous()
        values = facts[row][present].detach().contiguous()
        digest = hashlib.sha256(str((str(facts.dtype),tuple(present.shape))).encode())
        digest.update(present.numpy().tobytes())
        digest.update(values.numpy().tobytes())
        key = digest.digest()
        if key not in seen:
            seen[key] = len(representatives)
            representatives.append(row)
        else:
            other = representatives[seen[key]]
            if not torch.equal(mask[other],present) or not torch.equal(facts[other][present],values):
                raise ValueError("public fact grouping hash collision")
        inverse.append(seen[key])
    return torch.tensor(representatives,dtype=torch.long),torch.tensor(inverse,dtype=torch.long)


class GroundingCore(nn.Module):
    """One Group feature/localizer/metric, with shared updates and a tiny logit Head."""
    def __init__(self, hidden_dim=32):
        super().__init__()
        self.feature = nn.Linear(hidden_dim,hidden_dim,bias=False)
        self.metric = nn.Linear(hidden_dim,hidden_dim,bias=False)
        self.queries = nn.Parameter(torch.empty(4,hidden_dim))
        nn.init.normal_(self.queries,std=1/math.sqrt(hidden_dim))
        self.head = nn.Sequential(nn.Linear(6,16),nn.GELU(),nn.Linear(16,2))
        nn.init.zeros_(self.head[2].weight)
        nn.init.zeros_(self.head[2].bias)

    def localize(self, features, mask, queries):
        tokens = F.layer_norm(F.gelu(self.feature(features)),(features.shape[-1],))
        scores = torch.einsum("...th,sh->...st",tokens,queries)/math.sqrt(tokens.shape[-1])
        weights = _attention(scores,mask.unsqueeze(-2).expand_as(scores))
        raw = torch.einsum("...st,...th->...sh",weights,tokens)
        addresses = F.normalize(self.metric(raw),dim=-1,eps=1e-8)
        return raw,addresses,weights

    def walk(self, slots, question, candidate, present, *, depth=2, reset=False,
             value_permutation=None, question_present=None, candidate_present=None):
        """Select source addresses, retrieve destinations, and carry the new frontier."""
        if (type(depth) is not int or not 1 <= depth <= 4 or type(reset) is not bool
                or slots.ndim != 4 or slots.shape[-2] != 2 or present.shape != slots.shape[:2]
                or present.dtype != torch.bool or question.shape != slots.shape[:1]+slots.shape[-1:]
                or candidate.shape != question.shape):
            raise ValueError("bounded graph depth, two slots and aligned metric addresses required")
        batch,count,_,hidden = slots.shape
        if (not 1 <= count <= 256 or hidden != self.feature.in_features
                or any(value.device.type != "cpu" or value.dtype != torch.float32
                       or not torch.isfinite(value).all() or value.abs().max().item() > 1.000001
                       or value.norm(dim=-1).max().item() > 1.00001 for value in (slots,question,candidate))):
            raise ValueError("finite CPU FP32 unit-bounded graph addresses required")
        identity = torch.arange(count,dtype=torch.long).expand(batch,count)
        permutation = identity if value_permutation is None else value_permutation
        if (permutation.shape != (batch,count) or permutation.dtype != torch.long
                or permutation.device.type != "cpu"):
            raise ValueError("aligned public diagnostic value permutation required")
        for row in range(batch):
            valid = torch.where(present[row])[0]
            if (not torch.equal(permutation[row,~present[row]],identity[row,~present[row]])
                    or not torch.equal(permutation[row,valid].sort().values,valid)):
                raise ValueError("value permutation must preserve valid facts and padding")
        question_present = torch.ones(batch,dtype=torch.bool) if question_present is None else question_present
        candidate_present = torch.ones(batch,dtype=torch.bool) if candidate_present is None else candidate_present
        if any(value.shape != (batch,) or value.dtype != torch.bool or value.device.type != "cpu"
               for value in (question_present,candidate_present)):
            raise ValueError("aligned boolean public address-presence masks required")
        active = present & question_present[:,None]
        source = slots[:,:,0]
        payload = torch.gather(slots[:,:,1],1,permutation[:,:,None].expand(batch,count,hidden))
        state,states,attentions,readouts,features = question,[],[],[],[]
        for _ in range(depth):
            previous = question if reset else state
            scores = (source*previous[:,None]).sum(-1)*math.sqrt(hidden)
            attention = _attention(scores,active)
            state = F.normalize((attention[:,:,None]*payload).sum(1),dim=-1,eps=1e-8)
            if not torch.isfinite(state).all() or state.abs().max().item() > 1.000001:
                raise ValueError("graph state must remain finite inside [-1,1]")
            entropy = -(attention*attention.clamp(min=1e-12).log()).sum(-1)/active.sum(-1).clamp(min=2).to(state.dtype).log()
            readout = torch.stack(((state*candidate).sum(-1),(state*question).sum(-1),
                (state*previous).sum(-1),attention.max(-1).values,entropy,
                (active.any(-1)&candidate_present).to(state.dtype)),-1)
            states.append(state)
            attentions.append(attention)
            features.append(readout)
            readouts.append(self.head(readout))
        return dict(graph_initial_state=question,graph_states=states,graph_fact_attentions=attentions,
            graph_readouts=readouts,graph_readout_features=features,graph_depth=depth,graph_reset=reset,
            graph_value_permutation=permutation,graph_value_permutation_supplied=value_permutation is not None)


class GroundingReader(BridgeReader):
    """Retain the V6 Reader and add a separately observable learned Group walk."""
    def __init__(self,input_dim=384,hidden_dim=32,max_hops=8,*,arm="grounded_chain",
                 residual_seed=0,grounding_seed=0):
        if arm not in ARMS:
            raise ValueError("registered grounding arm required")
        super().__init__(input_dim,hidden_dim,max_hops=max_hops,residual_seed=residual_seed)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(grounding_seed)
            self.grounding = GroundingCore(hidden_dim)
        self.grounding_arm = arm
        self.graph_reset_default = arm.endswith("_reset")

    def _prepare_graph(self,facts,question,candidate,fact_mask,question_mask,candidate_mask,
                       *,graph_depth=2,graph_reset=None,value_permutation=None):
        reset = self.graph_reset_default if graph_reset is None else graph_reset
        if (type(graph_depth) is not int or not 1 <= graph_depth <= 4 or type(reset) is not bool):
            raise ValueError("bounded graph depth and explicit reset rule required")
        self._validate(facts,question,candidate,fact_mask,question_mask,candidate_mask)
        if facts.shape[0]*(facts.shape[1]*facts.shape[2]+question.shape[1]+candidate.shape[1])*self.hidden_dim > 64_000_000:
            raise ValueError("graph feature tensor bound exceeded; reduce batch size")
        prepared = super().prepare(facts,question,candidate,fact_mask,question_mask,candidate_mask)
        representatives,inverse = public_fact_groups(facts,fact_mask)
        unique = self.project(_normalize(facts[representatives]))
        raw,slots,attention = self.grounding.localize(unique,fact_mask[representatives],self.grounding.queries[:2])
        raw,slots,attention = raw[inverse],slots[inverse],attention[inverse]
        addresses,raw_addresses,role_attentions = [],[],[]
        for tokens,mask,index in ((question,question_mask,2),(candidate,candidate_mask,3)):
            feature = self.project(_normalize(tokens))
            role_raw,address,role_attention = self.grounding.localize(feature,mask,self.grounding.queries[index:index+1])
            raw_addresses.append(role_raw.squeeze(-2))
            addresses.append(address.squeeze(-2))
            role_attentions.append(role_attention.squeeze(-2))
        graph = dict(graph_slots=slots,graph_slot_features=raw,graph_question=addresses[0],graph_candidate=addresses[1],
            graph_question_features=raw_addresses[0],graph_candidate_features=raw_addresses[1],
            graph_slot_attentions=attention,graph_q_attention=role_attentions[0],graph_c_attention=role_attentions[1],
            graph_fact_present=fact_mask.any(-1),graph_q_present=question_mask.any(-1),graph_c_present=candidate_mask.any(-1),
            graph_representative_rows=representatives,graph_group_inverse=inverse,
            graph_grouped_counts=dict(input_rows=facts.shape[0],unique_fact_groups=len(representatives),
                reused_rows=facts.shape[0]-len(representatives)))
        graph.update(self.grounding.walk(slots,*addresses,fact_mask.any(-1),depth=graph_depth,reset=reset,
            value_permutation=value_permutation,question_present=question_mask.any(-1),candidate_present=candidate_mask.any(-1)))
        return {**prepared,"graph":graph}

    def prepare(self,facts,question,candidate,fact_mask,question_mask,candidate_mask):
        return self._prepare_graph(facts,question,candidate,fact_mask,question_mask,candidate_mask)

    def step_prepared(self,prepared,state=None,feedback=None):
        state,logits,attention,tokens = BridgeReader.step_prepared(self,prepared,state,feedback)
        return state,logits+prepared["graph"]["graph_readouts"][-1],attention,tokens

    def forward(self,facts,question,candidate,fact_mask,question_mask,candidate_mask,steps=3,
                state=None,feedback=None,return_attention=False,reset_state=False,*,graph_depth=2,
                graph_reset=None,value_permutation=None):
        if type(steps) is not int or not 1 <= steps <= self.max_hops:
            raise ValueError("bounded old Reader depth required")
        prepared = self._prepare_graph(facts,question,candidate,fact_mask,question_mask,candidate_mask,
            graph_depth=graph_depth,graph_reset=graph_reset,value_permutation=value_permutation)
        states,base_logits,attentions,token_attentions = [],[],[],[]
        for _ in range(steps):
            state,logits,attention,tokens = BridgeReader.step_prepared(
                self,prepared,None if reset_state else state,feedback)
            states.append(state)
            base_logits.append(logits)
            attentions.append(attention)
            token_attentions.append(tokens)
        residual = prepared["graph"]["graph_readouts"][-1]
        logits_trace = [value+residual for value in base_logits]
        if not return_attention:
            return logits_trace[-1]
        return dict(state=state,logits=logits_trace[-1],states=states,step_logits=logits_trace,
            base_logits=base_logits[-1],base_step_logits=base_logits,attentions=attentions,
            token_attentions=token_attentions,**prepared["graph"])


def build_grounding_reader(arm,seed):
    if arm not in ARMS or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("registered grounding arm and bounded integer seed required")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        return GroundingReader(arm=arm,residual_seed=seed^0x6B12,grounding_seed=seed^0x9A61)


def load_grounding_warmup(core,arm,*,seed):
    identity = reader_identity(core)
    if (identity["arm"] != "bridge" or core.training or any(p.requires_grad for p in core.parameters())
            or (core.input_dim,core.hidden_dim,core.max_hops) != (384,32,8)):
        raise ValueError("registered frozen V6 Bridge warmup required")
    source = core.state_dict()
    if any(v.dtype != torch.float32 or v.device.type != "cpu" or not torch.isfinite(v).all() for v in source.values()):
        raise ValueError("finite CPU FP32 warmup tensors required")
    model = build_grounding_reader(arm,seed)
    result = model.load_state_dict(source,strict=False)
    if result.unexpected_keys or set(result.missing_keys) != set(model.state_dict())-set(source):
        raise ValueError("warmup does not match common Group core keys")
    for name,value in source.items():
        if model.state_dict()[name].detach().numpy().tobytes() != value.detach().numpy().tobytes():
            raise ValueError("an actual warmup tensor changed during copying")
    model.training_source_groups = tuple(getattr(core,"training_source_groups",()))
    return model.eval().requires_grad_(False)


def restore_grounding_reader(arm,seed,state_dict,*,training_source_groups=()):
    model = build_grounding_reader(arm,seed)
    if any(not isinstance(v,torch.Tensor) or v.dtype != torch.float32 or v.device.type != "cpu"
           or not torch.isfinite(v).all() for v in state_dict.values()):
        raise ValueError("finite CPU FP32 saved Group tensors required")
    model.load_state_dict(state_dict,strict=True)
    model.training_source_groups = tuple(training_source_groups)
    grounding_identity(model)
    return model.eval().requires_grad_(False)


def grounding_identity(model):
    if (type(model) is not GroundingReader or model.grounding_arm not in ARMS or model.reader_arm != "bridge"
            or model.interaction != "token" or model.graph_reset_default != model.grounding_arm.endswith("_reset")):
        raise ValueError("registered grounding class, arm and graph reset rule required")
    h,i = model.hidden_dim,model.input_dim
    shapes = {"project.weight":(h,i),"query.weight":(h,4*h),"query.bias":(h,),
        "relation.weight":(h,8*h),"relation.bias":(h,),"token_score.weight":(1,h),"token_key.weight":(h,h),
        "fact_score.weight":(1,h),"fact_key.weight":(h,h),"state_query.weight":(h,2*h),
        "proposal.weight":(h,3*h+4),"proposal.bias":(h,),"update_gate.weight":(h,3*h+4),"update_gate.bias":(h,),
        "head.0.weight":(h,3*h+1),"head.0.bias":(h,),"head.2.weight":(2,h),"head.2.bias":(2,)}
    shapes.update({"fact_bridge."+name+".weight":(h,h) for name in ("query","key","value","output")})
    shapes.update({"grounding.feature.weight":(h,h),"grounding.metric.weight":(h,h),"grounding.queries":(4,h),
        "grounding.head.0.weight":(16,6),"grounding.head.0.bias":(16,),"grounding.head.2.weight":(2,16),"grounding.head.2.bias":(2,)})
    if {n:tuple(v.shape) for n,v in model.state_dict().items()} != shapes:
        raise ValueError("registered grounding parameter names and shapes required")
    common,added = i*h+29*h*h+18*h+2,2*h*h+4*h+146
    if sum(v.numel() for v in model.parameters()) != common+added:
        raise ValueError("registered grounding parameter count required")
    return dict(schema="hepta.grounding-reader.v9",arm=model.grounding_arm,input_dim=i,hidden_dim=h,
        max_hops=model.max_hops,max_facts=model.max_facts,max_tokens=model.max_tokens,
        parameter_count=common+added,common_parameter_count=common,added_parameter_count=added,
        graph_depth_default=2,max_graph_depth=4,graph_reset_default=model.graph_reset_default,
        grounding_auxiliary_expected=model.grounding_arm.startswith("grounded_"),
        old_reader_state_transition="TokenReader-v4",old_reader_reset_changed=False,
        graph_state="unit_normalized_32d_frontier",graph_metric="shared_linear_cosine_for_slots_Q_C_walk_readout",
        graph_readout_features=["cos_frontier_C","cos_frontier_Q","cos_previous_frontier","attention_max","normalized_entropy","public_presence"],
        grouped_fact_prepare="within_call_public_facts_and_masks_no_persistent_autograd_cache",
        public_feature_arguments=6,annotations_enter_forward=False,parameter_sharing_across_graph_hops=True,
        extra_last_logit_layer_zero_initialized=True,same_parameter_count_is_same_compute=False)
